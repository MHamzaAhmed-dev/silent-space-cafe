"""Isolated reservation-page browser acceptance. No real reservations or email."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import time, timedelta
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time as clock
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','silent_space.settings')
from django.conf import settings
from django.core.management import call_command
from django.db import connections
import django
from playwright.sync_api import sync_playwright, expect
from tools.check_acceptance import fingerprint, stop_process

BASE='http://127.0.0.1:8005'
OUTPUT=ROOT/'artifacts'


def run():
    import socket
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', 8005)) == 0:
            raise RuntimeError('Reservation QA port 8005 is busy; stop the other rehearsal before retrying.')
    real_db=settings.DATABASES['default']['NAME']
    original=fingerprint(real_db)
    OUTPUT.mkdir(exist_ok=True)
    passed=[]
    with tempfile.TemporaryDirectory(prefix='silent-space-reservations-') as directory, ExitStack() as stack:
        folder=Path(directory); db=folder/'booking.sqlite3'
        settings.DATABASES['default']['NAME']=str(db)
        settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
        settings.STAFF_NOTIFICATION_RECIPIENTS=['owner@example.test']
        django.setup()
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        from django.utils import timezone
        from bookings.models import BookingHours, ReservationRequest, ZoneCapacity
        from notifications.models import Notification
        from notifications.services import process_pending
        call_command('migrate',verbosity=0)
        day=timezone.localdate()+timedelta(days=1)
        BookingHours.objects.create(weekday=day.weekday(),opens=time(10),closes=time(18))
        for zone,seats in [('quiet',2),('reading',4),('solo',1)]:ZoneCapacity.objects.create(zone=zone,seats=seats)
        password=secrets.token_urlsafe(24)
        operator=get_user_model().objects.create_user('booking-qa',password=password,is_staff=True)
        operator.user_permissions.set(Permission.objects.filter(content_type__app_label__in=['bookings','notifications']))
        code="""import os,sys
os.environ['DJANGO_SETTINGS_MODULE']='silent_space.settings'
from django.conf import settings
settings.DATABASES['default']['NAME']=sys.argv[1]
settings.DEBUG=True
settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
import django
django.setup()
from django.core.management import call_command
call_command('runserver','127.0.0.1:8005',use_reloader=False,verbosity=0)
"""
        log=stack.enter_context(open(folder/'server.log','w'))
        process=subprocess.Popen([sys.executable,'-c',code,str(db)],cwd=ROOT,stdout=log,stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        stack.callback(lambda:clock.sleep(1));stack.callback(connections.close_all);stack.callback(stop_process,process)
        for _ in range(60):
            try:
                if urlopen(BASE+'/book-a-table/',timeout=2).status==200:break
            except Exception:
                if process.poll() is not None:raise RuntimeError('Reservation preview failed')
                clock.sleep(.25)
        else:raise RuntimeError('Reservation preview unavailable')
        executor=stack.enter_context(ThreadPoolExecutor(max_workers=1))
        def orm(function):
            def invoke():
                try:return function()
                finally:connections.close_all()
            return executor.submit(invoke).result()
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            try:
                for width in (390,768,1440):
                    context=browser.new_context(viewport={'width':width,'height':960})
                    page=context.new_page(); errors=[]; failed=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('response',lambda r:failed.append(r.url) if r.status>=400 else None)
                    page.goto(BASE+'/book-a-table/')
                    expect(page.get_by_role('heading',name='Reserve your quiet moment',exact=True)).to_be_visible()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    form=page.locator('.reservation-form-column').bounding_box()
                    guide=page.locator('.space-guide').bounding_box()
                    if width<=800:assert form['y']<guide['y']
                    else:assert guide['x']<form['x']
                    page.evaluate('scrollTo({top:0,behavior:"instant"})')
                    page.screenshot(path=str(OUTPUT/f'reservation-page-{width}.png'),full_page=True)
                    page.screenshot(path=str(OUTPUT/f'reservation-first-screen-{width}.png'))
                    page.get_by_label('Your name',exact=False).focus()
                    assert page.locator('#id_name').evaluate('el=>getComputedStyle(el).outlineStyle')!='none'
                    page.keyboard.press('Tab');expect(page.locator('#id_phone')).to_be_focused()
                    page.locator('#id_date').fill(day.isoformat())
                    page.locator('#id_guests').select_option('2')
                    page.locator('#id_zone').select_option('quiet')
                    page.locator('#id_time').select_option('11:00')
                    expect(page.locator('#availability-message')).to_contain_text('Pakistan Standard Time')
                    page.locator('#id_zone').select_option('solo')
                    expect(page.locator('#availability-message')).to_contain_text('one guest')
                    assert page.locator('#id_time option[value="11:00"]').count()==0
                    page.locator('#id_guests').select_option('1')
                    page.locator('#id_time').select_option('11:00')
                    page.locator('#id_date').fill((day+timedelta(days=1)).isoformat())
                    expect(page.locator('#availability-message')).to_contain_text('No available times')
                    # Date changes as well as party size/zone refresh the choices.
                    page.locator('#id_date').fill(day.isoformat())
                    page.locator('#id_time').select_option('12:00')
                    # A past date is rejected by the public endpoint and form server-side.
                    token=page.locator('input[name=submission_token]').input_value()
                    csrf=page.locator('input[name=csrfmiddlewaretoken]').first.input_value()
                    invalid=page.request.post(BASE+'/book-a-table/',form={
                        'csrfmiddlewaretoken':csrf,'submission_token':token,'date':(day-timedelta(days=2)).isoformat(),
                        'guests':'1','zone':'quiet','time':'11:00','name':'Preserved guest','phone':'03001234567'})
                    assert 'Choose a future date' in invalid.text() and 'Preserved guest' in invalid.text()
                    assert not errors,errors
                    # API validation 400 is expected for the deliberately invalid Solo selection.
                    assert all('/bookings/availability/' in url for url in failed),failed
                    context.close()
                    passed.append(f'{width}px: layout order, overflow, keyboard focus, dynamic date/party/zone times, closed-day feedback and past-date rejection passed')
                    print(passed[-1],flush=True)
                context=browser.new_context(viewport={'width':390,'height':960})
                guest=context.new_page();guest.goto(BASE+'/book-a-table/')
                guest.locator('#id_date').fill(day.isoformat());guest.locator('#id_guests').select_option('2');guest.locator('#id_zone').select_option('quiet')
                guest.locator('#id_time').select_option('11:00')
                guest.locator('#id_name').fill('Acceptance Guest');guest.locator('#id_phone').fill('03001234567')
                guest.locator('#id_special_request').fill('Near the books, please.')
                token=guest.locator('input[name=submission_token]').input_value();csrf=guest.locator('input[name=csrfmiddlewaretoken]').first.input_value()
                payload={'csrfmiddlewaretoken':csrf,'submission_token':token,'date':day.isoformat(),'guests':'2','zone':'quiet','time':'11:00','name':'Acceptance Guest','phone':'03001234567','special_request':'Near the books, please.'}
                guest.get_by_role('button',name='Request a reservation',exact=True).click()
                status_url=guest.url;reference=guest.locator('.workflow-reference').inner_text()
                expect(guest.get_by_role('heading',name='Pending review',exact=True)).to_be_visible()
                repeat=guest.request.post(BASE+'/book-a-table/',form=payload)
                assert repeat.url==status_url
                row=orm(lambda:ReservationRequest.objects.get(reference=reference))
                assert orm(lambda:ReservationRequest.objects.filter(reference=reference).count())==1
                assert orm(lambda:Notification.objects.filter(reservation=row,kind='new_reservation').count())==1
                def email_check():
                    from django.core import mail
                    process_pending();process_pending()
                    return [message.body for message in mail.outbox if str(row.reference) in message.subject]
                assert len(orm(email_check))==1
                staff_context=browser.new_context(viewport={'width':1440,'height':960});staff=staff_context.new_page()
                staff.goto(BASE+'/staff/login/');staff.get_by_label('Username').fill('booking-qa');staff.get_by_label('Password').fill(password);staff.get_by_role('button',name='Sign in',exact=True).click()
                staff.goto(BASE+f'/admin/bookings/reservationrequest/{row.pk}/change/')
                expect(staff.locator('.field-reference')).to_contain_text(reference)
                staff.locator('#id_change_status').select_option('approve_requests')
                staff.get_by_role('button',name='Save',exact=True).click()
                guest.reload();expect(guest.get_by_role('heading',name='Approved — Your reservation is confirmed.',exact=True)).to_be_visible()
                staff.goto(BASE+'/staff/reservations/?view=upcoming&q='+reference)
                expect(staff.get_by_role('link',name='Acceptance Guest',exact=True)).to_be_visible()
                # Form opened before another approval must retain contact details after rejection.
                stale_context=browser.new_context();stale=stale_context.new_page();stale.goto(BASE+'/book-a-table/')
                stale.locator('#id_date').fill(day.isoformat());stale.locator('#id_guests').select_option('2');stale.locator('#id_zone').select_option('quiet')
                expect(stale.locator('#availability-message')).to_contain_text('Choose an available time')
                assert stale.locator('#id_time option[value="11:00"]').count()==0
                stale.locator('#id_time').evaluate('el=>{el.add(new Option("11:00","11:00"));el.value="11:00"}')
                stale.locator('#id_name').fill('Details kept');stale.locator('#id_phone').fill('03001234567')
                stale.locator('#id_special_request').fill('Keep this note')
                stale.get_by_role('button',name='Request a reservation',exact=True).click()
                expect(stale.get_by_role('alert')).to_contain_text('details have been kept')
                expect(stale.get_by_text('This zone cannot accommodate your group at that time.',exact=True)).to_be_visible()
                expect(stale.locator('#id_name')).to_have_value('Details kept');expect(stale.locator('#id_special_request')).to_have_value('Keep this note')
                stale.screenshot(path=str(OUTPUT/'reservation-stale-slot-feedback.png'),full_page=True)
                staff.goto(BASE+f'/staff/reservations/{row.pk}/')
                staff.get_by_label('Internal cancellation reason').fill('Acceptance release')
                staff.get_by_role('button',name='Cancel reservation',exact=True).click()
                guest.reload();expect(guest.get_by_role('heading',name='Cancelled',exact=True)).to_be_visible()
                assert 'Acceptance release' not in guest.content()
                repeated=guest.request.post(BASE+'/book-a-table/',form=payload)
                assert repeated.url==status_url and orm(lambda:ReservationRequest.objects.count())==1
                stale.get_by_role('button',name='Check available times',exact=True).click()
                stale.locator('#id_time').select_option('11:00')
                stale.get_by_role('button',name='Request a reservation',exact=True).click()
                expect(stale.get_by_role('heading',name='Pending review',exact=True)).to_be_visible()
                assert orm(lambda:ReservationRequest.objects.count())==2
                passed.append('Valid pending request matches staff/customer reference; duplicate POST queues one notification; approval, Upcoming, full-slot feedback, cancellation, private status and capacity release passed')
                print(passed[-1],flush=True)
                # The no-JavaScript action does not validate contact fields or create a request.
                nojs_context=browser.new_context(java_script_enabled=False,viewport={'width':390,'height':960})
                nojs=nojs_context.new_page();nojs.goto(BASE+'/book-a-table/?zone=reading')
                nojs.locator('#id_date').fill(day.isoformat());nojs.locator('#id_guests').select_option('1')
                nojs.locator('#id_name').fill('No JS Guest');nojs.locator('#id_phone').fill('03001234567')
                nojs.get_by_role('button',name='Check available times',exact=True).click()
                expect(nojs.locator('#id_name')).to_have_value('No JS Guest')
                nojs.locator('#id_time').select_option('13:00')
                nojs.get_by_role('button',name='Request a reservation',exact=True).click()
                expect(nojs.get_by_role('heading',name='Pending review',exact=True)).to_be_visible()
                guest.goto(BASE);guest.locator('.hero-actions').get_by_role('link',name='Reserve a seat',exact=True).click()
                assert guest.url==BASE+'/book-a-table/'
                guest.goto(BASE+'/menu/');guest.locator('.menu-reservation').get_by_role('link',name='Reserve a seat',exact=True).click()
                assert guest.url==BASE+'/book-a-table/'
                passed.append('No-JavaScript availability/submission with retained details and homepage/menu reservation links passed')
                print(passed[-1],flush=True)
            finally:browser.close()
    assert fingerprint(real_db)==original,'Real business records changed'
    (OUTPUT/'reservation-checks.json').write_text(json.dumps({'passed':passed,'data':'isolated; existing records unchanged','email':'in-memory only'},indent=2))


if __name__=='__main__':run()
