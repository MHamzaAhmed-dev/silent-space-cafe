"""Final acceptance journey using a disposable DB, browser and SMTP capture inbox.

No production records, SMTP credentials or staff recipients are used.
"""
import argparse
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta
from hashlib import sha256
from io import StringIO
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
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'silent_space.settings')
from django.conf import settings
from django.core.management import call_command
from django.db import connections
import django
from playwright.sync_api import sync_playwright, expect
from tools.acceptance_support import TEST_INBOX, smtp_capture
from tools.booking_browser import choose_booking_time

ARTIFACTS = ROOT/'artifacts'


def fingerprint(path):
    if not Path(path).exists():
        return None
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True) as db:
        rows = {table: db.execute(f'SELECT * FROM {table} ORDER BY id').fetchall() for table in
                ['orders_dineinorder','orders_orderline','orders_servicelocation','bookings_reservationrequest','menu_menuitem']}
    return sha256(repr(rows).encode()).hexdigest()


def stop_process(process):
    if process.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        else:
            process.terminate()
        process.wait(timeout=10)


def powershell(script):
    return subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',script],
        capture_output=True,text=True,timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)


def ps_quote(value):
    return "'"+str(value).replace("'", "''")+"'"


def scheduler_probe(config_path, marker):
    if os.name != 'nt':
        return {'status':'unverified','detail':'Windows Task Scheduler is unavailable on this host.'}
    name='SilentSpaceAcceptance-'+uuid4().hex
    arguments=subprocess.list2cmdline([str(ROOT/'tools/run_acceptance_worker.py'),str(config_path)])
    script=f"""$ErrorActionPreference='Stop'
$action=New-ScheduledTaskAction -Execute {ps_quote(sys.executable)} -Argument {ps_quote(arguments)} -WorkingDirectory {ps_quote(ROOT)}
$trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(8) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Minutes 3)
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName {ps_quote(name)} -Action $action -Trigger $trigger -Settings $settings | Out-Null
"""
    try:
        result=powershell(script)
        if result.returncode:
            return {'status':'unverified','detail':'Temporary Task Scheduler registration failed: '+result.stderr.strip()[:900]}
        deadline=clock.monotonic()+80
        while clock.monotonic()<deadline:
            if marker.exists():
                return {'status':'passed','detail':'A temporary one-minute repeating Windows task executed the real worker and wrote its success marker.'}
            clock.sleep(.5)
        return {'status':'unverified','detail':'The temporary task did not finish within 80 seconds; deployment-account scheduling still needs verification.'}
    finally:
        powershell(f"Get-ScheduledTask -TaskName {ps_quote(name)} -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false")


def run(check_scheduler=False):
    ARTIFACTS.mkdir(exist_ok=True)
    production_db=settings.DATABASES['default']['NAME']
    original=fingerprint(production_db)
    report={'passed':[], 'unverified':['Physical QR scanning on a real phone',
            'External SMTP provider acceptance, actual external inbox delivery and spam placement'],
            'test_inbox':TEST_INBOX, 'email_transport':'loopback SMTP capture only'}
    def passed(message):
        report['passed'].append(message)
        print('PASS: '+message,flush=True)
    with tempfile.TemporaryDirectory(prefix='silent-space-acceptance-') as directory, ExitStack() as stack:
        temp=Path(directory)
        database=temp/'acceptance.sqlite3'
        settings.DATABASES['default']['NAME']=str(database)
        settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
        django.setup()
        call_command('migrate',verbosity=0)
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        from django.utils import timezone
        from bookings.models import BookingHours, ReservationRequest, ZoneCapacity
        from notifications.models import Notification
        from notifications.services import enqueue, queue_reminders, reservation_start
        from menu.models import MenuItem
        from orders.models import DineInOrder, OrderLine, ServiceLocation
        password=secrets.token_urlsafe(24)
        staff=get_user_model().objects.create_user('acceptance-operator',password=password,is_staff=True)
        staff.user_permissions.set(Permission.objects.filter(content_type__app_label__in=['orders','bookings','menu','notifications'],codename__regex=r'^(view|change)_'))
        viewer=get_user_model().objects.create_user('acceptance-viewer',password=password,is_staff=True)
        viewer.user_permissions.set(Permission.objects.filter(codename__in=['view_dineinorder','view_reservationrequest','view_notification']))
        get_user_model().objects.create_user('acceptance-customer',password=password)
        table=ServiceLocation.objects.create(label='Acceptance Quiet Corner / Table 07')
        disabled=ServiceLocation.objects.create(label='Acceptance Disabled Table 08')
        item=MenuItem.objects.create(name='Acceptance Cappuccino',slug='acceptance-cappuccino',price='550.00')
        day=timezone.localdate()+timedelta(days=1)
        BookingHours.objects.create(weekday=day.weekday(),opens=time(10),closes=time(18))
        ZoneCapacity.objects.create(zone='quiet',seats=2)
        inbox=stack.enter_context(smtp_capture())
        config={'database':str(database),'smtp_port':inbox.server_address[1],'base_url':'http://127.0.0.1:8002'}
        config_path=temp/'worker.json'
        def write_config(now=None,marker=None):
            value={**config,'now':now.isoformat() if now else None}
            if marker: value['marker']=str(marker)
            config_path.write_text(json.dumps(value))
        def workers(now=None, parallel=1):
            write_config(now)
            processes=[subprocess.Popen([sys.executable,str(ROOT/'tools/run_acceptance_worker.py'),str(config_path)],
                cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0) for _ in range(parallel)]
            try:
                for process in processes:
                    out,err=process.communicate(timeout=60)
                    assert process.returncode==0,(out,err)
                    assert 'Processed ' in out
            finally:
                for process in processes:
                    stop_process(process)
        server_code="""import os,sys
os.environ['DJANGO_SETTINGS_MODULE']='silent_space.settings'
from django.conf import settings
settings.DATABASES['default']['NAME']=sys.argv[1]
settings.DEBUG=True
settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
import django
django.setup()
from django.core.management import call_command
call_command('runserver','127.0.0.1:8002',use_reloader=False,verbosity=0)
"""
        log=stack.enter_context(open(temp/'server.log','w',encoding='utf-8'))
        server=subprocess.Popen([sys.executable,'-c',server_code,str(database)],cwd=ROOT,stdout=log,stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        stack.callback(lambda:clock.sleep(1))
        stack.callback(connections.close_all)
        stack.callback(stop_process,server)
        for _ in range(60):
            try:
                if urlopen(config['base_url']+'/staff/login/',timeout=2).status==200: break
            except Exception:
                if server.poll() is not None: raise RuntimeError('Acceptance server failed')
                clock.sleep(.25)
        else: raise RuntimeError('Acceptance server unavailable')
        qr_output=StringIO()
        call_command('export_location_qr',table.label,config['base_url'],str(temp/'table.svg'),stdout=qr_output)
        qr_url=qr_output.getvalue().strip()
        disabled_output=StringIO()
        call_command('export_location_qr',disabled.label,config['base_url'],str(temp/'disabled.svg'),stdout=disabled_output)
        disabled_url=disabled_output.getvalue().strip()
        assert qr_url==config['base_url']+f'/orders/scan/{table.token}/'
        assert '<svg' in (temp/'table.svg').read_text()
        (ARTIFACTS/'acceptance-demo-qr.svg').write_bytes((temp/'table.svg').read_bytes())
        passed('QR export creates a displayed/printable SVG with the correct service-location URL (physical scan not performed)')
        executor=stack.enter_context(ThreadPoolExecutor(max_workers=1))
        def orm(function):
            # Playwright owns an event loop. Keep synchronous Django ORM work on a dedicated thread.
            def invoke():
                try:
                    return function()
                finally:
                    connections.close_all()
            return executor.submit(invoke).result()
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            customer_context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
            customer=customer_context.new_page()
            staff_context=browser.new_context(viewport={'width':1440,'height':960})
            operator=staff_context.new_page()
            errors=[]
            customer.on('pageerror',lambda error:errors.append(str(error)))
            operator.on('pageerror',lambda error:errors.append(str(error)))
            def login(page,username):
                page.goto(config['base_url']+'/staff/login/')
                page.get_by_label('Username').fill(username)
                page.get_by_label('Password').fill(password)
                page.get_by_role('button',name='Sign in',exact=True).click()
            def place_order():
                customer.goto(qr_url)
                customer.get_by_role('button',name='Add Acceptance Cappuccino to bag',exact=True).click()
                customer.goto(config['base_url']+'/orders/bag/')
                customer.get_by_role('link',name='Review dine-in order',exact=True).click()
                quote=customer.locator('input[name=quote]').input_value()
                csrf=customer.locator('input[name=csrfmiddlewaretoken]').input_value()
                expect(customer.get_by_text(table.label,exact=True)).to_be_visible()
                customer.get_by_role('button',name='Place dine-in order',exact=True).click()
                reference=customer.locator('.workflow-reference').inner_text()
                order=orm(lambda:DineInOrder.objects.get(reference=reference))
                return order,customer.url,quote,csrf
            def staff_order(order):
                operator.goto(config['base_url']+f'/staff/orders/{order.pk}/')
            login(operator,'acceptance-operator')
            order,receipt,quote,csrf=place_order()
            assert order.location_label==table.label and order.total==550
            retry=customer.request.post(config['base_url']+'/orders/checkout/',form={'quote':quote,'csrfmiddlewaretoken':csrf})
            assert retry.url==receipt
            assert orm(lambda:DineInOrder.objects.count())==1
            assert orm(lambda:Notification.objects.filter(order=order,kind='new_order').count())==1
            operator.goto(config['base_url']+'/staff/orders/?q='+str(order.reference))
            operator.get_by_role('link',name=str(order.reference)[:8],exact=True).click()
            expect(operator.locator('.full-reference')).to_have_text(str(order.reference))
            expect(operator.get_by_role('heading',name=table.label,exact=True)).to_be_visible()
            operator.screenshot(path=str(ARTIFACTS/'acceptance-staff-order.png'),full_page=True)
            workers()
            messages=inbox.matching('New Order',order.reference)
            assert len(messages)==1
            message=messages[0]
            body=message.get_content()
            for part in [str(order.reference),table.label,'Acceptance Cappuccino x 1','PKR 550.00','PKT',f'/admin/orders/dineinorder/{order.pk}/change/']:
                assert part in body,part
            assert str(message['To'])==TEST_INBOX
            (ARTIFACTS/'acceptance-new-order.eml').write_bytes(message.as_bytes())
            passed('Mobile QR URL -> dine-in checkout -> matching receipt/table in staff dashboard -> one New Order email received in the local SMTP test inbox; repeat checkout stays idempotent')
            operator.get_by_role('button',name='Start preparing',exact=True).click()
            expect(operator.locator('.badge.preparing')).to_be_visible()
            operator.get_by_role('button',name='Mark completed',exact=True).click()
            customer.goto(receipt)
            expect(customer.get_by_role('heading',name='Completed',exact=True)).to_be_visible()
            customer.screenshot(path=str(ARTIFACTS/'acceptance-completed-receipt-390.png'),full_page=True)
            passed('Staff transitions Received -> Preparing -> Completed; original customer receipt reflects Completed')
            orm(lambda:ServiceLocation.objects.filter(pk=disabled.pk).update(enabled=False))
            response=customer.goto(disabled_url)
            assert response.status==404
            expect(customer.get_by_role('heading',name='Service location unavailable',exact=True)).to_be_visible()
            customer.get_by_role('link',name='Browse the menu',exact=True).click()
            customer.get_by_role('button',name='Add Acceptance Cappuccino to bag',exact=True).click()
            customer.goto(config['base_url']+'/orders/checkout/')
            assert customer.url.endswith('/orders/bag/')
            assert customer.get_by_role('link',name='Review dine-in order',exact=True).count()==0
            assert orm(lambda:DineInOrder.objects.count())==1
            customer.get_by_role('button',name='Remove Acceptance Cappuccino',exact=True).click()
            passed('Disabled QR URL returns the unavailable page, clears the previous location and cannot create an order')
            def book():
                customer.goto(config['base_url']+'/book-a-table/')
                for field,value in {'name':'Acceptance Guest','email':'guest@silent-space.test','phone':'03001234567',
                                    'date':day.isoformat()}.items():
                    customer.locator('#id_'+field).fill(value)
                choose_booking_time(customer,day)
                customer.locator('[data-request-submit]').click()
                reference=customer.locator('.workflow-reference').inner_text()
                return orm(lambda:ReservationRequest.objects.get(reference=reference)),customer.url
            reservation,status_url=book()
            operator.goto(config['base_url']+f'/staff/reservations/{reservation.pk}/')
            operator.locator('#change-status').select_option('approve_requests')
            operator.get_by_role('button',name='Save',exact=True).click()
            operator.goto(config['base_url']+'/staff/reservations/?view=upcoming&q='+str(reservation.reference))
            expect(operator.get_by_role('link',name='Acceptance Guest',exact=True)).to_be_visible()
            operator.set_viewport_size({'width':768,'height':1024})
            operator.screenshot(path=str(ARTIFACTS/'acceptance-upcoming-768.png'),full_page=True)
            # Controlled clock is confined to a separate worker process, never the web app.
            due=reservation_start(reservation)-timedelta(minutes=60)
            workers(due); workers(due)
            assert len(inbox.matching('Upcoming Approved Reservation',reservation.reference))==1
            assert len(inbox.matching('New Reservation Request',reservation.reference))==1
            customer.goto(config['base_url']+'/book-a-table/')
            # Re-submit the same full slot directly with the real browser CSRF token.
            token=customer.locator('input[name=csrfmiddlewaretoken]').input_value()
            blocked=customer.request.post(config['base_url']+'/book-a-table/',form={
                'csrfmiddlewaretoken':token,'name':'Blocked Guest','email':'blocked@silent-space.test','phone':'03001234567',
                'date':day.isoformat(),'time':'11:00','guests':'2','zone':'quiet'})
            assert 'cannot accommodate' in blocked.text()
            assert orm(lambda:ReservationRequest.objects.count())==1
            operator.goto(config['base_url']+f'/staff/reservations/{reservation.pk}/')
            operator.get_by_label('Internal cancellation reason').fill('Acceptance cancellation')
            operator.get_by_role('button',name='Cancel reservation',exact=True).click()
            orm(reservation.refresh_from_db); stamp=reservation.cancelled_at
            token=operator.locator('form[action="/staff/logout/"] input[name=csrfmiddlewaretoken]').input_value()
            operator.request.post(config['base_url']+f'/staff/reservations/{reservation.pk}/action/',form={
                'csrfmiddlewaretoken':token,'action':'cancel_reservations','reason':'Repeat attempt'})
            orm(reservation.refresh_from_db); assert reservation.cancelled_at==stamp
            customer.goto(status_url)
            expect(customer.get_by_role('heading',name='Cancelled',exact=True)).to_be_visible()
            expect(customer.get_by_text('Acceptance cancellation',exact=True)).to_have_count(0)
            workers(due)
            assert len(inbox.matching('Upcoming Approved Reservation',reservation.reference))==1
            replacement,replacement_url=book()
            operator.goto(config['base_url']+f'/staff/reservations/{replacement.pk}/')
            operator.locator('#change-status').select_option('approve_requests')
            operator.get_by_role('button',name='Save',exact=True).click()
            orm(replacement.refresh_from_db); assert replacement.status=='approved'
            passed('Reservation approval appears in Upcoming; one controlled 60-minute reminder; cancellation preserves reference/time, updates customer status, and frees the full slot for a new approved booking')
            unattended,_,_,_=place_order()
            processed,_,_,_=place_order()
            workers()
            now=timezone.now()
            orm(lambda:DineInOrder.objects.filter(pk__in=[unattended.pk,processed.pk]).update(created_at=now-timedelta(minutes=10,seconds=1)))
            # Simulate the real race: reminder queued while Received, staff acts before delivery.
            orm(lambda:queue_reminders(now))
            staff_order(processed)
            operator.get_by_role('button',name='Start preparing',exact=True).click()
            workers(now+timedelta(seconds=1)); workers(now+timedelta(seconds=1))
            assert len(inbox.matching('Order still Received',unattended.reference))==1
            assert len(inbox.matching('Order still Received',processed.reference))==0
            assert orm(lambda:Notification.objects.get(order=processed,kind='order_reminder').status)=='skipped'
            assert not orm(lambda:Notification.objects.filter(order=order,kind='order_reminder').exists())
            passed('Unattended Received order generates one reminder at the controlled 10-minute threshold; Preparing and Completed orders are skipped, including a queued-before-action reminder')
            recovering,recovery_receipt,_,_=place_order()
            inbox.reject_deliveries=True
            recovery_clock=timezone.now()+timedelta(seconds=1)
            workers(recovery_clock)
            job=orm(lambda:Notification.objects.get(order=recovering,kind='new_order'))
            assert (job.status,job.attempts)==('pending',1)
            workers(recovery_clock+timedelta(seconds=2))
            orm(job.refresh_from_db); assert (job.status,job.attempts)==('failed',2)
            assert '451' in job.last_error
            customer.goto(recovery_receipt)
            expect(customer.get_by_role('heading',name='Received',exact=True)).to_be_visible()
            operator.goto(config['base_url']+'/staff/notifications/?status=failed')
            operator.locator(f'form[action="/staff/notifications/{job.pk}/retry/"]').get_by_role('button').click()
            inbox.reject_deliveries=False
            workers(parallel=2)
            orm(job.refresh_from_db); assert job.status=='sent'
            assert len(inbox.matching('New Order',recovering.reference))==1
            passed('SMTP 451 outage leaves the order saved, retries twice then records Failed; dashboard retry recovers delivery; two overlapping command processes deliver the queued event once')
            viewer_context=browser.new_context(viewport={'width':768,'height':960})
            viewer_page=viewer_context.new_page()
            login(viewer_page,'acceptance-viewer')
            viewer_page.goto(config['base_url']+f'/staff/orders/{unattended.pk}/')
            assert viewer_page.get_by_role('button',name='Start preparing',exact=True).count()==0
            token=viewer_page.locator('form[action="/staff/logout/"] input[name=csrfmiddlewaretoken]').input_value()
            for url,form in [(f'/staff/orders/{unattended.pk}/action/',{'action':'start_preparing'}),
                             (f'/staff/reservations/{replacement.pk}/action/',{'action':'cancel_reservations'}),
                             (f'/staff/notifications/{job.pk}/retry/',{})]:
                response=viewer_page.request.post(config['base_url']+url,form={'csrfmiddlewaretoken':token,**form})
                assert response.status==403
            other_context=browser.new_context()
            other=other_context.new_page()
            login(other,'acceptance-customer')
            expect(other.get_by_text('A staff account is required.',exact=True)).to_be_visible()
            def check_sessions_and_csrf():
                from django.test import Client
                ordinary=Client(HTTP_HOST='127.0.0.1'); ordinary.force_login(get_user_model().objects.get(username='acceptance-customer'))
                assert ordinary.get('/staff/').status_code==403
                secure=Client(enforce_csrf_checks=True,HTTP_HOST='127.0.0.1'); secure.force_login(staff)
                assert secure.post(f'/staff/orders/{unattended.pk}/action/',{'action':'start_preparing'}).status_code==403
            orm(check_sessions_and_csrf)
            passed('Authorized staff can act; view-only staff cannot POST order/reservation/retry changes; non-staff login/access and missing-CSRF actions are rejected')
            for page,url in [(customer,'/'),(operator,'/staff/')]:
                page.goto(config['base_url']+url)
                icon=page.locator('link[rel="icon"]').get_attribute('href')
                response=page.request.get(config['base_url']+icon)
                assert response.status==200 and 'image/svg+xml' in response.headers['content-type']
                response=page.request.get(config['base_url']+'/favicon.ico')
                assert response.status==200 and '<svg' in response.text()
            assert not errors,errors
            passed('Branded SVG favicon loads on storefront and dashboard; /favicon.ico resolves successfully without a 404; no JavaScript page errors')
            if check_scheduler:
                scheduled,_,_,_=place_order()
                marker=temp/'scheduled-worker.json'
                write_config(marker=marker)
                report['windows_scheduler']=scheduler_probe(config_path,marker)
                if report['windows_scheduler']['status']=='passed':
                    assert len(inbox.matching('New Order',scheduled.reference))==1
                    passed('Windows Task Scheduler executed the isolated worker and delivered its New Order email; temporary task removed')
                else:
                    print('UNVERIFIED: '+report['windows_scheduler']['detail'],flush=True)
                    workers()
            else:
                report['windows_scheduler']={'status':'unverified','detail':'Run with --check-windows-scheduler to attempt a temporary scheduled-task probe.'}
            browser.close()
    assert fingerprint(production_db)==original,'Acceptance QA changed real cafe business records'
    passed('Real cafe order, booking, menu and location records unchanged; temporary database/server/inbox cleaned up')
    report['windows_scheduler_production_account']='unverified: verify task under the deployment service account, including logged-out execution'
    report['run_at']=timezone.localtime().isoformat()
    report['status']='passed with explicitly listed external verification limits'
    (ARTIFACTS/'acceptance-results.json').write_text(json.dumps(report,indent=2))
    print('Report: artifacts/acceptance-results.json',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-windows-scheduler',action='store_true')
    args=parser.parse_args()
    run(args.check_windows_scheduler)
