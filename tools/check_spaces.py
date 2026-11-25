"""Isolated Spaces-to-Reservations browser acceptance with no external email."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import time, timedelta
import json
import os
from pathlib import Path
import secrets
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

BASE='http://127.0.0.1:8006'
OUTPUT=ROOT/'artifacts'


def run():
    real_db=settings.DATABASES['default']['NAME']; original=fingerprint(real_db)
    OUTPUT.mkdir(exist_ok=True); passed=[]
    with tempfile.TemporaryDirectory(prefix='silent-space-spaces-') as directory, ExitStack() as stack:
        folder=Path(directory); db=folder/'spaces.sqlite3'
        settings.DATABASES['default']['NAME']=str(db)
        settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
        django.setup()
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        from django.utils import timezone
        from bookings.models import BookingHours, ReservationRequest, ZoneCapacity
        call_command('migrate',verbosity=0)
        day=timezone.localdate()+timedelta(days=1)
        BookingHours.objects.create(weekday=day.weekday(),opens=time(10),closes=time(18))
        for zone,seats in [('quiet',2),('reading',4),('solo',1)]:ZoneCapacity.objects.create(zone=zone,seats=seats)
        password=secrets.token_urlsafe(24)
        staff=get_user_model().objects.create_user('spaces-qa',password=password,is_staff=True)
        staff.user_permissions.set(Permission.objects.filter(codename__in=['view_reservationrequest','change_reservationrequest']))
        code="""import os,sys
os.environ['DJANGO_SETTINGS_MODULE']='silent_space.settings'
from django.conf import settings
settings.DATABASES['default']['NAME']=sys.argv[1]
settings.DEBUG=True
settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
import django
django.setup()
from django.core.management import call_command
call_command('runserver','127.0.0.1:8006',use_reloader=False,verbosity=0)
"""
        log=stack.enter_context(open(folder/'server.log','w'))
        process=subprocess.Popen([sys.executable,'-c',code,str(db)],cwd=ROOT,stdout=log,stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        stack.callback(lambda:clock.sleep(1));stack.callback(connections.close_all);stack.callback(stop_process,process)
        for _ in range(60):
            try:
                if urlopen(BASE+'/spaces/',timeout=2).status==200:break
            except Exception:
                if process.poll() is not None:raise RuntimeError('Spaces preview failed')
                clock.sleep(.25)
        else:raise RuntimeError('Spaces preview did not start')
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
                    page=context.new_page();errors=[];failed=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.on('response',lambda response:failed.append(response.url) if response.status>=400 else None)
                    page.goto(BASE)
                    shell_script="""() => ['.site-header','.brand','.nav-links','.nav-reserve','.site-footer'].map(selector=>{
                      const style=getComputedStyle(document.querySelector(selector));
                      return [selector,style.backgroundColor,style.color,style.fontFamily,style.fontSize,style.padding];
                    })"""
                    home_shell=page.evaluate(shell_script)
                    page.locator('.hero-actions').get_by_role('link',name='Explore the spaces',exact=True).click()
                    assert page.url==BASE+'/spaces/'
                    expect(page.get_by_role('heading',name='Find your quiet.',exact=True)).to_be_visible()
                    assert page.evaluate(shell_script)==home_shell
                    for image in page.locator('img').all():image.scroll_into_view_if_needed()
                    page.wait_for_function('Array.from(document.images).every(img=>img.complete && img.naturalWidth>0)')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    for index,row in enumerate(page.locator('.space-row').all()):
                        image=row.locator('.space-row-photo').bounding_box();copy=row.locator('.space-row-copy').bounding_box()
                        if width<=640:assert image['y']<copy['y']
                        elif index%2:assert copy['x']<image['x']
                        else:assert image['x']<copy['x']
                    page.evaluate('scrollTo({top:0,behavior:"instant"})')
                    page.screenshot(path=str(OUTPUT/f'spaces-page-{width}.png'),full_page=True)
                    page.screenshot(path=str(OUTPUT/f'spaces-first-screen-{width}.png'))
                    for zone in ['quiet','reading','solo']:
                        link=page.locator(f'#space-{zone} .reserve-space')
                        link.focus();assert link.evaluate('el=>getComputedStyle(el).outlineStyle')!='none'
                        link.press('Enter')
                        assert page.url==BASE+'/book-a-table/?zone='+zone
                        expect(page.locator('#id_zone')).to_have_value(zone)
                        page.locator('#id_date').fill(day.isoformat())
                        page.locator('#id_time').select_option('11:00')
                        page.locator('#id_zone').select_option('reading' if zone!='reading' else 'quiet')
                        page.locator('#id_time').select_option('12:00')
                        page.goto(BASE+'/spaces/')
                    page.locator('.spaces-reservation').get_by_role('link',name='Reserve a seat',exact=True).click()
                    assert page.url==BASE+'/book-a-table/'
                    expect(page.locator('#id_zone')).to_have_value('')
                    if width<=900:
                        toggle=page.get_by_role('button',name='Menu',exact=True)
                        toggle.click();page.keyboard.press('Escape');expect(toggle).to_be_focused()
                        toggle.click();page.locator('.nav-links').get_by_role('link',name='Spaces',exact=True).click()
                        assert page.url==BASE+'/spaces/'
                        expect(page.locator('.nav-toggle')).to_have_attribute('aria-expanded','false')
                    assert not errors and not failed,(errors,failed)
                    context.close()
                    passed.append(f'{width}px: separate photos, shared homepage shell, responsive rows, all three preselected links, zone changes, general button, keyboard and navigation passed')
                    print(passed[-1],flush=True)
                context=browser.new_context(viewport={'width':390,'height':960});guest=context.new_page()
                guest.goto(BASE+'/spaces/');guest.locator('#space-solo .reserve-space').click()
                guest.locator('#id_date').fill(day.isoformat());guest.locator('#id_guests').select_option('2')
                expect(guest.locator('#availability-message')).to_contain_text('Solo Space is for one guest')
                assert guest.locator('#id_time option[value="11:00"]').count()==0
                csrf=guest.locator('input[name=csrfmiddlewaretoken]').first.input_value()
                token=guest.locator('input[name=submission_token]').input_value()
                rejected=guest.request.post(BASE+'/book-a-table/',form={'csrfmiddlewaretoken':csrf,'submission_token':token,
                    'date':day.isoformat(),'guests':'2','zone':'solo','time':'11:00','name':'Solo Guest','phone':'03001234567'})
                assert 'Solo Space is for one guest' in rejected.text()
                assert orm(lambda:ReservationRequest.objects.count())==0
                guest.goto(BASE+'/spaces/');guest.locator('#space-reading .reserve-space').click()
                guest.locator('#id_date').fill(day.isoformat());guest.locator('#id_guests').select_option('2');guest.locator('#id_time').select_option('13:00')
                guest.locator('#id_name').fill('Spaces Flow Guest');guest.locator('#id_phone').fill('03001234567')
                guest.get_by_role('button',name='Request a reservation',exact=True).click()
                reference=guest.locator('.workflow-reference').inner_text();status_url=guest.url
                expect(guest.get_by_role('heading',name='Pending review',exact=True)).to_be_visible()
                expect(guest.get_by_text('Reading Zone',exact=False)).to_be_visible()
                row=orm(lambda:ReservationRequest.objects.get(reference=reference))
                assert row.zone=='reading' and row.guests==2
                staff_context=browser.new_context(viewport={'width':1440,'height':960});operator=staff_context.new_page()
                operator.goto(BASE+'/staff/login/');operator.get_by_label('Username').fill('spaces-qa');operator.get_by_label('Password').fill(password);operator.get_by_role('button',name='Sign in',exact=True).click()
                operator.goto(BASE+f'/staff/reservations/{row.pk}/')
                expect(operator.locator('.full-reference')).to_have_text(reference)
                expect(operator.locator('.facts')).to_contain_text('Reading Zone')
                operator.screenshot(path=str(OUTPUT/'spaces-booking-staff-reference.png'),full_page=True)
                operator.locator('#change-status').select_option('approve_requests')
                operator.get_by_role('button',name='Save',exact=True).click()
                guest.reload();expect(guest.get_by_role('heading',name='Approved',exact=True)).to_be_visible()
                guest.screenshot(path=str(OUTPUT/'spaces-booking-customer-reference.png'),full_page=True)
                passed.append('Reading Zone link completed a booking with matching zone/reference in customer status and staff dashboard; approval and two-guest Solo rejection passed')
                print(passed[-1],flush=True)
                orm(lambda:ZoneCapacity.objects.filter(zone='reading').update(seats=0))
                guest.goto(BASE+'/spaces/');guest.locator('#space-reading .reserve-space').click()
                expect(guest.locator('#id_zone')).to_have_value('')
                assert guest.locator('#id_zone option[value="reading"]').count()==0
                assert guest.locator('#id_zone option[value="quiet"]').count()==1
                guest.goto(BASE+'/book-a-table/?zone=invalid');expect(guest.locator('#id_zone')).to_have_value('')
                guest.goto(status_url);expect(guest.get_by_role('heading',name='Approved',exact=True)).to_be_visible()
                # An active but full zone stays selected and uses the existing no-times message.
                def fill_quiet():
                    for hour in range(10,18):ReservationRequest.objects.create(date=day,time=time(hour),zone='quiet',guests=2,name='Capacity fixture',status='approved')
                orm(fill_quiet)
                guest.goto(BASE+'/spaces/');guest.locator('#space-quiet .reserve-space').click()
                guest.locator('#id_date').fill(day.isoformat())
                expect(guest.locator('#availability-message')).to_contain_text('No available times for this selection')
                expect(guest.locator('#id_zone')).to_have_value('quiet')
                guest.locator('#id_date').fill((day+timedelta(days=7)).isoformat());guest.locator('#id_time').select_option('11:00')
                # Old addresses still work, including fragment targets and query strings.
                guest.goto(BASE+'/quiet-zones/?from=old-link#quiet-zones')
                assert guest.url==BASE+'/spaces/?from=old-link#quiet-zones'
                nojs_context=browser.new_context(java_script_enabled=False,viewport={'width':390,'height':960});nojs=nojs_context.new_page()
                nojs.goto(BASE+'/spaces/');nojs.locator('#space-solo .reserve-space').click()
                expect(nojs.locator('#id_zone')).to_have_value('solo')
                nojs.locator('#id_date').fill(day.isoformat());nojs.get_by_role('button',name='Check available times',exact=True).click();nojs.locator('#id_time').select_option('12:00')
                passed.append('Inactive/missing/invalid preselection handling, active choices, full-zone message, alternative date, preserved status, legacy redirect and no-JavaScript availability passed')
                print(passed[-1],flush=True)
            finally:browser.close()
    assert fingerprint(real_db)==original,'Real business records changed'
    (OUTPUT/'spaces-checks.json').write_text(json.dumps({'passed':passed,'data':'isolated database; real cafe records unchanged','email':'not sent externally'},indent=2))


if __name__=='__main__':run()
