"""Isolated Phase 4 browser QA. Never writes to the cafe database or sends email."""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time as clock
from datetime import time, timedelta
from uuid import uuid4
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'silent_space.settings')
from tools.booking_browser import choose_booking_time

from django.conf import settings
from django.core.management import call_command
from django.db import connections
import django
from playwright.sync_api import sync_playwright, expect


def run():
    with tempfile.TemporaryDirectory(prefix='silent-space-staff-') as directory:
        db = Path(directory)/'qa.sqlite3'
        settings.DATABASES['default']['NAME'] = str(db)
        settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
        django.setup()
        call_command('migrate', verbosity=0)
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        from django.utils import timezone
        from bookings.models import BookingHours, ReservationRequest, ZoneCapacity
        from menu.models import MenuItem
        from notifications.models import Notification
        from orders.models import DineInOrder, OrderLine, ServiceLocation

        password = secrets.token_urlsafe(20)
        operator = get_user_model().objects.create_user('qa-operator', password=password, is_staff=True)
        operator.user_permissions.set(Permission.objects.filter(
            content_type__app_label__in=['orders','bookings','menu','notifications'], codename__regex=r'^(view|change)_'))
        viewer = get_user_model().objects.create_user('qa-viewer', password=password, is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(codename='view_dineinorder'))
        get_user_model().objects.create_user('qa-customer', password=password)
        locations = [ServiceLocation.objects.create(label=label) for label in ['Quiet Corner / Table 01', 'Reading Zone / Table 04', 'Solo Space / Seat 02']]
        orders = []
        for index in range(7):
            order = DineInOrder.objects.create(submission_key=uuid4(),location=locations[index%3],
                location_label=locations[index%3].label,total='1480.00',status='preparing' if index==6 else 'received')
            DineInOrder.objects.filter(pk=order.pk).update(created_at=timezone.now()-timedelta(minutes=18-index*2))
            OrderLine.objects.create(order=order,name='Classic Cappuccino',unit_price='550.00',quantity=2)
            OrderLine.objects.create(order=order,name='Butter Croissant',unit_price='380.00',quantity=1)
            orders.append(order)
        day=timezone.localdate()+timedelta(days=1)
        BookingHours.objects.create(weekday=day.weekday(),opens=time(10),closes=time(18))
        ZoneCapacity.objects.create(zone='quiet',seats=6)
        reservations=[]
        for index,name in enumerate(['Ayesha Khan','Omar Ali','Sara Ahmed']):
            reservations.append(ReservationRequest.objects.create(name=name,email='guest@example.test',phone='03001234567',
                date=day,time=time(11+index),guests=2,zone='quiet',special_request='Near the reading shelves, if possible.'))
        ReservationRequest.objects.create(name='Hassan Raza',email='guest@example.test',date=timezone.localdate(),time=time(23),guests=1,zone='reading',status='approved')
        jobs=[]
        for index,order in enumerate(orders[:4]):
            jobs.append(Notification.objects.create(event_key=f'new_order:{order.reference}',kind='new_order',order=order,
                status='failed' if index<3 else 'sent',attempts=3,last_error='SMTP connection timed out' if index<3 else ''))
        item=MenuItem.objects.create(name='QA Cappuccino',slug='qa-cappuccino',price='550.00')
        output=ROOT/'artifacts'
        output.mkdir(exist_ok=True)
        server_code = """import os, sys
os.environ['DJANGO_SETTINGS_MODULE']='silent_space.settings'
from django.conf import settings
settings.DATABASES['default']['NAME']=sys.argv[1]
settings.DEBUG=True
settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
import django
django.setup()
from django.core.management import call_command
call_command('runserver','127.0.0.1:8001',use_reloader=False,verbosity=0)
"""
        with open(Path(directory)/'server.log','w',encoding='utf-8') as log:
            server=subprocess.Popen([sys.executable,'-c',server_code,str(db)],cwd=ROOT,stdout=log,stderr=log,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            try:
                for _ in range(60):
                    try:
                        if urlopen('http://127.0.0.1:8001/staff/login/',timeout=2).status==200: break
                    except Exception:
                        if server.poll() is not None: raise RuntimeError('QA server failed to start')
                        clock.sleep(.25)
                else: raise RuntimeError('QA server did not become ready')
                with sync_playwright() as p:
                    browser=p.chromium.launch(channel='chrome',headless=True)
                    def login(page,user):
                        page.goto('http://127.0.0.1:8001/staff/login/')
                        page.get_by_label('Username').fill(user)
                        page.get_by_label('Username').press('Tab')
                        expect(page.get_by_label('Password')).to_be_focused()
                        page.get_by_label('Password').fill(password)
                        page.get_by_role('button',name='Sign in',exact=True).click()
                    for index,width in enumerate((390,768,1440)):
                        context=browser.new_context(viewport={'width':width,'height':960})
                        page=context.new_page()
                        errors=[]
                        page.on('pageerror',lambda err:errors.append(str(err)))
                        login(page,'qa-operator')
                        expect(page.get_by_role('heading',name='Overview',exact=True)).to_be_visible()
                        def inspect(name):
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'{name}: page overflow at {width}'
                            page.screenshot(path=str(output/f'phase4-{name}-{width}.png'),full_page=True)
                        inspect('overview')
                        page.get_by_role('navigation',name='Staff navigation').get_by_role('link',name='Orders',exact=True).click()
                        inspect('orders')
                        page.get_by_label('Reference or location').fill('Reading')
                        page.get_by_role('button',name='Search',exact=True).click()
                        assert page.locator('tbody tr').count()==(1 if index==2 else 2)
                        page.get_by_role('link',name='Clear search',exact=True).click()
                        page.goto(f'http://127.0.0.1:8001/staff/orders/{orders[index].pk}/')
                        inspect('order-detail')
                        page.get_by_role('button',name='Start preparing',exact=True).click()
                        expect(page.locator('.badge.preparing')).to_be_visible()
                        page.get_by_role('button',name='Mark completed',exact=True).click()
                        expect(page.locator('.badge.completed')).to_be_visible()
                        page.goto('http://127.0.0.1:8001/staff/reservations/?view=pending')
                        inspect('reservations')
                        page.goto(f'http://127.0.0.1:8001/staff/reservations/{reservations[index].pk}/')
                        page.locator('#change-status').select_option('approve_requests')
                        page.get_by_role('button',name='Save',exact=True).click()
                        expect(page.locator('.badge.approved')).to_be_visible()
                        page.get_by_label('Internal cancellation reason').fill('Browser QA cancellation')
                        inspect('reservation-detail')
                        page.get_by_role('button',name='Cancel reservation',exact=True).click()
                        expect(page.locator('.badge.cancelled')).to_be_visible()
                        page.goto('http://127.0.0.1:8001/staff/reservations/?view=cancelled')
                        expect(page.get_by_role('link',name=reservations[index].name,exact=True)).to_be_visible()
                        page.goto('http://127.0.0.1:8001/staff/notifications/?status=failed')
                        inspect('notifications')
                        page.locator(f'form[action="/staff/notifications/{jobs[index].pk}/retry/"]').get_by_role('button').click()
                        expect(page.get_by_text('Notification queued for retry.',exact=True)).to_be_visible()
                        page.goto('http://127.0.0.1:8001/staff/catalogue/')
                        inspect('catalogue')
                        page.get_by_role('link',name='Manage menu',exact=True).click()
                        expect(page.get_by_role('heading',name='Select menu item to change',exact=True)).to_be_visible()
                        assert not errors,errors
                        context.close()
                        print(f'{width}px: layouts, order transitions, reservation approval/cancellation, search, delivery retry and Admin link passed')
                    context=browser.new_context(viewport={'width':1440,'height':960})
                    page=context.new_page()
                    login(page,'qa-viewer')
                    assert page.get_by_role('navigation',name='Staff navigation').get_by_role('link',name='Reservations',exact=True).count()==0
                    page.goto('http://127.0.0.1:8001/staff/reservations/')
                    assert '403' in page.title()
                    page.goto('http://127.0.0.1:8001/staff/orders/')
                    page.clock.install()
                    with page.expect_response(lambda r:'fragment=1' in r.url):
                        page.clock.fast_forward(21000)
                    expect(page.locator('#refresh-status')).to_contain_text('Queue updated')
                    page.get_by_label('Reference or location').focus()
                    original=page.locator('#queue-region').inner_html()
                    page.clock.fast_forward(21000)
                    assert page.locator('#queue-region').inner_html()==original
                    expect(page.get_by_label('Reference or location')).to_be_focused()
                    page.get_by_label('Reference or location').fill('unsent search')
                    page.clock.fast_forward(21000)
                    expect(page.get_by_label('Reference or location')).to_have_value('unsent search')
                    expect(page.get_by_label('Reference or location')).to_be_focused()
                    page.reload()
                    row=page.locator('.reference').first
                    row.focus()
                    page.clock.fast_forward(21000)
                    expect(row).to_be_focused()
                    page.get_by_role('button',name='Refresh queue').focus()
                    with page.expect_response(lambda r:'fragment=1' in r.url):
                        page.get_by_role('button',name='Refresh queue').click()
                    expect(page.get_by_role('button',name='Refresh queue')).to_be_focused()
                    expect(page.locator('#refresh-status')).to_contain_text('Queue updated')
                    page.get_by_role('button',name='Sign out',exact=True).click()
                    login(page,'qa-customer')
                    expect(page.get_by_text('A staff account is required.',exact=True)).to_be_visible()
                    context.close()
                    # Storefront regression: existing no-JavaScript bag and reservation form.
                    context=browser.new_context(java_script_enabled=False,viewport={'width':390,'height':960})
                    page=context.new_page()
                    page.goto('http://127.0.0.1:8001/menu/')
                    page.get_by_role('button',name='Add QA Cappuccino to bag',exact=True).click()
                    page.goto('http://127.0.0.1:8001/orders/bag/')
                    expect(page.get_by_text('QA Cappuccino',exact=True)).to_be_visible()
                    page.reload()
                    expect(page.get_by_text('QA Cappuccino',exact=True)).to_be_visible()
                    page.get_by_role('button',name='Increase QA Cappuccino',exact=True).click()
                    page.get_by_role('button',name='Decrease QA Cappuccino',exact=True).click()
                    page.get_by_role('button',name='Remove QA Cappuccino',exact=True).click()
                    expect(page.get_by_text('Your bag is empty.',exact=False)).to_be_visible()
                    page.goto('http://127.0.0.1:8001/book-a-table/')
                    page.locator('#id_name').fill('Browser Guest')
                    page.locator('#id_email').fill('browser@example.test')
                    page.locator('#id_phone').fill('03001234567')
                    choose_booking_time(page,day,value='18:00',javascript=False,unavailable=True)
                    page.locator('[data-request-submit]').click()
                    expect(page.get_by_text('This one-hour slot is outside the configured booking hours.',exact=True)).to_be_visible()
                    page.locator('#id_time').select_option('15:00')
                    page.locator('[data-request-submit]').click()
                    expect(page.get_by_role('heading',name='Pending review',exact=True)).to_be_visible()
                    context.close()
                    browser.close()
                    print('Keyboard navigation and valid/invalid storefront reservation submissions passed')
                    print('Limited/non-staff access, queue form/focus preservation, manual refresh and storefront bag regression passed')
            finally:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(server.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    server.terminate()
                server.wait(timeout=10)
                connections.close_all()
                clock.sleep(1)


if __name__=='__main__':
    run()
