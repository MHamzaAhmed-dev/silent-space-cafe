"""Isolated browser checkout acceptance: temporary records, no live email/payment."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json, os, secrets, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','silent_space.settings')
import django
from django.conf import settings
from django.core.management import call_command
from django.db import connections
from playwright.sync_api import sync_playwright, expect
from tools.check_acceptance import fingerprint, stop_process
BASE='http://127.0.0.1:8007'
OUTPUT=ROOT/'artifacts'


def run():
    original_db=settings.DATABASES['default']['NAME']; original=fingerprint(original_db)
    OUTPUT.mkdir(exist_ok=True); passed=[]
    with tempfile.TemporaryDirectory(prefix='silent-checkout-') as directory, ExitStack() as stack:
        folder=Path(directory); db=folder/'qa.sqlite3'
        settings.DATABASES['default']['NAME']=str(db)
        settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
        django.setup()
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        from menu.models import MenuItem
        from orders.models import DeliveryArea, PaymentMethod, DineInOrder, ServiceLocation
        # Prove old order history survives the additive migrations with nonempty records.
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        from uuid import uuid4
        call_command('migrate', 'orders', '0001', verbosity=0)
        old = MigrationExecutor(connection).loader.project_state([('orders','0001_initial')]).apps
        old_location = old.get_model('orders','ServiceLocation').objects.create(label='Historic table')
        old_order = old.get_model('orders','DineInOrder').objects.create(reference=uuid4(), submission_key=uuid4(),
            location_id=old_location.pk, location_label=old_location.label, total='750.00', status='completed')
        old.get_model('orders','OrderLine').objects.create(order_id=old_order.pk, name='Historic coffee', unit_price='750', quantity=1)
        call_command('migrate',verbosity=0)
        historic = DineInOrder.objects.get(reference=old_order.reference)
        assert historic.location_label == 'Historic table' and str(historic.total) == '750.00'
        assert str(historic.lines.get().unit_price) == '750.00' and historic.status == 'completed'
        passed.append('Legacy nonempty order, receipt reference and line prices preserved through migrations')
        coffee=MenuItem.objects.create(slug='classic-cappuccino',name='Classic Cappuccino',price='1100')
        rose=MenuItem.objects.create(slug='rose-latte',name='Rose Latte',price='1500')
        a=DeliveryArea.objects.create(name='QA area A',fee=100)
        b=DeliveryArea.objects.create(name='QA area B',fee=250)
        location=ServiceLocation.objects.create(label='QA Table 12')
        password=secrets.token_urlsafe(24)
        staff=get_user_model().objects.create_superuser('checkout-qa',password=password)
        viewer=get_user_model().objects.create_user('checkout-viewer',password=password,is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(codename='view_dineinorder'))
        code="""import os,sys
os.environ['DJANGO_SETTINGS_MODULE']='silent_space.settings'
from django.conf import settings
settings.DATABASES['default']['NAME']=sys.argv[1]
settings.DEBUG=True
settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
settings.STRIPE_SECRET_KEY=''
settings.STRIPE_WEBHOOK_SECRET=''
import django
django.setup()
from django.core.management import call_command
call_command('runserver','127.0.0.1:8007',use_reloader=False,verbosity=0)
"""
        log=stack.enter_context(open(folder/'server.log','w'))
        process=subprocess.Popen([sys.executable,'-c',code,str(db)],cwd=ROOT,stdout=log,stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        stack.callback(lambda:time.sleep(1));stack.callback(connections.close_all);stack.callback(stop_process,process)
        for _ in range(60):
            try:
                if urlopen(BASE+'/orders/bag/',timeout=2).status==200:break
            except Exception:time.sleep(.25)
        else:raise RuntimeError('QA preview failed')
        executor=stack.enter_context(ThreadPoolExecutor(max_workers=1))
        def orm(fn):
            def invoke():
                try:return fn()
                finally:connections.close_all()
            return executor.submit(invoke).result()
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            try:
                def add(page,item):
                    page.goto(BASE+'/menu/')
                    page.locator(f'form[action="/orders/bag/{item.pk}/add/"] button').click()
                def login(page,user):
                    page.goto(BASE+'/staff/login/')
                    page.get_by_label('Username').fill(user);page.get_by_label('Password').fill(password)
                    page.get_by_role('button',name='Sign in',exact=True).click()
                for width in [390,768,1440]:
                    context=browser.new_context(viewport={'width':width,'height':1000})
                    page=context.new_page();errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(BASE)
                    shell="() => ['.site-header','.site-footer'].map(s=>{const e=document.querySelector(s),c=getComputedStyle(e),copy=e.cloneNode(true);copy.querySelectorAll('[aria-current]').forEach(a=>a.removeAttribute('aria-current'));return [copy.innerHTML,c.backgroundColor,c.color,c.fontFamily]})"
                    # Bag count changes; compare shell styling and structure after adding.
                    add(page,coffee);add(page,rose)
                    page.goto(BASE);home=page.evaluate(shell)
                    page.goto(BASE+'/orders/bag/')
                    assert page.evaluate(shell)==home
                    expect(page.locator('#delivery-fee')).to_have_text('Calculated for your area')
                    page.get_by_label('Delivery area',exact=True).select_option(str(a.pk))
                    expect(page.locator('#checkout-total')).to_have_text('Rs. 2,700')
                    page.get_by_label('Delivery area',exact=True).select_option(str(b.pk))
                    expect(page.locator('#checkout-total')).to_have_text('Rs. 2,850')
                    assert page.get_by_label('Card (Visa / Mastercard)',exact=True).count()==0
                    page.get_by_label('Full name',exact=True).fill('Browser Guest')
                    page.get_by_label('Phone number',exact=True).fill('03001234567')
                    page.get_by_label('Street address',exact=True).fill('12 Quiet Road')
                    page.get_by_label('JazzCash',exact=True).check()
                    page.keyboard.press('Tab')
                    page.get_by_label('JazzCash',exact=True).focus()
                    assert page.get_by_label('JazzCash',exact=True).evaluate('e=>getComputedStyle(e).outlineStyle')!='none'
                    page.wait_for_function('Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    left=page.locator('.checkout-left').bounding_box();right=page.locator('.checkout-right').bounding_box()
                    if width==390:assert right['y']>left['y']+left['height']
                    else:assert right['x']>left['x']
                    page.evaluate('scrollTo({top:0,behavior:"instant"})')
                    page.screenshot(path=str(OUTPUT/f'checkout-{width}.png'),full_page=True)
                    page.get_by_role('button',name='Place order',exact=True).click()
                    expect(page.locator('.workflow-reference')).to_be_visible()
                    reference=page.locator('.workflow-reference').inner_text()
                    expect(page.get_by_text('03249233487',exact=True)).to_be_visible()
                    page.get_by_label('Transaction reference',exact=False).fill('QA-TX-'+str(width))
                    page.get_by_role('button',name='Submit transaction reference',exact=True).click()
                    expect(page.get_by_text('Pending verification',exact=True)).to_be_visible()
                    row=orm(lambda:DineInOrder.objects.get(reference=reference))
                    assert str(row.total)=='2850.00' and row.delivery_area_id==b.pk
                    admin=context.new_page();login(admin,'checkout-qa')
                    admin.goto(BASE+f'/staff/orders/{row.pk}/')
                    expect(admin.get_by_role('heading',name='QA area B',exact=True)).to_be_visible()
                    admin.locator('#payment-decision').select_option('approve')
                    admin.get_by_role('button',name='Save',exact=True).click()
                    page.reload();expect(page.get_by_text('Paid',exact=True)).to_be_visible()
                    expect(page.get_by_text('Approved: Payment approved.',exact=True)).to_be_visible()
                    admin.get_by_role('button',name='Start preparing',exact=True).click()
                    page.reload();expect(page.get_by_text('We’re preparing your order.',exact=True)).to_be_visible()
                    admin.get_by_role('button',name='Mark out for delivery',exact=True).click()
                    page.reload();expect(page.get_by_text('Your order is on its way.',exact=True)).to_be_visible()
                    assert not errors, errors
                    context.close();passed.append(f'{width}px: matching shared shell, images, no overflow, fee changes, keyboard, delivery/JazzCash/staff verification')
                # Easypaisa is enabled only in the isolated test database.
                orm(lambda:PaymentMethod.objects.filter(code='easypaisa').update(enabled=True,receiver='TEST-EASYPAISA'))
                context=browser.new_context()
                page=context.new_page();add(page,coffee)
                page.get_by_label('How would you like your order?',exact=True).select_option('pickup')
                page.get_by_label('Full name',exact=True).fill('Easypaisa Pickup Guest')
                page.get_by_label('Phone number',exact=True).fill('03001234567')
                page.get_by_label('Easypaisa',exact=True).check()
                page.get_by_role('button',name='Place order',exact=True).click()
                original_link=page.url
                reference=page.locator('.workflow-reference').inner_text()
                page.get_by_label('Transaction reference',exact=False).fill('QA-EASYPAISA-PICKUP')
                page.get_by_role('button',name='Submit transaction reference',exact=True).click()
                row=orm(lambda:DineInOrder.objects.get(reference=reference))
                operator=context.new_page();login(operator,'checkout-qa')
                operator.goto(BASE+f'/staff/orders/{row.pk}/')
                operator.get_by_label('Change payment status',exact=True).select_option('approve')
                operator.get_by_role('button',name='Save',exact=True).click()
                page.goto(original_link);expect(page.get_by_text('Approved: Payment approved.',exact=True)).to_be_visible()
                operator.get_by_role('button',name='Start preparing',exact=True).click()
                page.reload();expect(page.get_by_text('We’re preparing your order.',exact=True)).to_be_visible()
                operator.get_by_role('button',name='Mark ready for pickup',exact=True).click()
                page.reload();expect(page.get_by_text('Your order is ready for pickup.',exact=True)).to_be_visible()
                page.screenshot(path=str(OUTPUT/'payment-easypaisa-pickup.png'),full_page=True)
                context.close();passed.append('Easypaisa pickup: original guest link, staff approval, preparing and ready for pickup')
                context=browser.new_context(java_script_enabled=False)
                page=context.new_page();add(page,coffee)
                page.get_by_label('How would you like your order?',exact=True).select_option('pickup')
                page.get_by_role('button',name='Update fees & payment options',exact=True).click()
                expect(page.get_by_label('Delivery area',exact=True)).to_be_hidden()
                page.get_by_label('Full name',exact=True).fill('Pickup Guest')
                page.get_by_label('Phone number',exact=True).fill('03001234567')
                page.get_by_label('Cash at pickup / cafe',exact=True).check()
                page.get_by_role('button',name='Place order',exact=True).click()
                expect(page.get_by_role('heading',name='Pickup order',exact=True)).to_be_visible()
                context.close();passed.append('No-JavaScript refresh and cash pickup')
                context=browser.new_context();page=context.new_page()
                page.goto(BASE+f'/orders/scan/{location.token}/');add(page,coffee)
                page.get_by_role('link',name='Review dine-in order',exact=True).click()
                page.get_by_label('Payment method',exact=True).select_option(label='Cash at pickup / cafe')
                page.get_by_role('button',name='Place dine-in order',exact=True).click()
                expect(page.get_by_text(location.label,exact=True)).to_be_visible()
                context.close();passed.append('QR dine-in table context and order receipt retained')
            finally:browser.close()
    assert fingerprint(original_db)==original, 'Real database changed'
    result={'passed':passed,'unverified':['Live SMTP','Merchant sandbox payments','Physical phone scanning'],'real_database_unchanged':True}
    (OUTPUT/'checkout-acceptance.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':run()
