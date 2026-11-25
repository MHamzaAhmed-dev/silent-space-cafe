"""Isolated browser acceptance of product photos, Admin edits and QR ordering."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from decimal import Decimal
from io import StringIO
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

BASE='http://127.0.0.1:8004'
OUTPUT=ROOT/'artifacts'


def run():
    original_db=settings.DATABASES['default']['NAME']
    original=fingerprint(original_db)
    OUTPUT.mkdir(exist_ok=True)
    passed=[]
    with tempfile.TemporaryDirectory(prefix='silent-space-menu-') as directory, ExitStack() as stack:
        folder=Path(directory); database=folder/'menu.sqlite3'; media=folder/'media'
        settings.DATABASES['default']['NAME']=str(database)
        settings.MEDIA_ROOT=media; settings.MEDIA_URL='/media/'
        settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
        django.setup()
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        from menu.models import MenuItem
        from orders.models import DineInOrder, ServiceLocation
        call_command('migrate',verbosity=0)
        call_command('seed_menu',stdout=StringIO())
        password=secrets.token_urlsafe(24)
        staff=get_user_model().objects.create_user('menu-qa',password=password,is_staff=True)
        staff.user_permissions.set(Permission.objects.filter(content_type__app_label__in=['menu','orders']))
        viewer=get_user_model().objects.create_user('menu-viewer',password=password,is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(codename='view_menuitem'))
        get_user_model().objects.create_user('menu-customer',password=password)
        location=ServiceLocation.objects.create(label='Menu QA Reading Table 04')
        coffee=MenuItem.objects.get(slug='classic-cappuccino')
        rose=MenuItem.objects.get(slug='rose-latte')
        code="""import os,sys
os.environ['DJANGO_SETTINGS_MODULE']='silent_space.settings'
from django.conf import settings
settings.DATABASES['default']['NAME']=sys.argv[1]
settings.MEDIA_ROOT=sys.argv[2]
settings.MEDIA_URL='/media/'
settings.DEBUG=True
settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
import django
django.setup()
from django.core.management import call_command
call_command('runserver','127.0.0.1:8004',use_reloader=False,verbosity=0)
"""
        log=stack.enter_context(open(folder/'server.log','w'))
        process=subprocess.Popen([sys.executable,'-c',code,str(database),str(media)],cwd=ROOT,stdout=log,stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        stack.callback(lambda:clock.sleep(1)); stack.callback(connections.close_all); stack.callback(stop_process,process)
        for _ in range(60):
            try:
                if urlopen(BASE+'/menu/',timeout=2).status==200:break
            except Exception:
                if process.poll() is not None:raise RuntimeError('Menu preview failed')
                clock.sleep(.25)
        else:raise RuntimeError('Menu preview did not start')
        executor=stack.enter_context(ThreadPoolExecutor(max_workers=1))
        def orm(function):
            def invoke():
                try:return function()
                finally:connections.close_all()
            return executor.submit(invoke).result()
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            try:
                def login(page,name):
                    page.goto(BASE+'/staff/login/')
                    page.get_by_label('Username').fill(name); page.get_by_label('Password').fill(password)
                    page.get_by_role('button',name='Sign in',exact=True).click()
                def images_loaded(page):
                    for img in page.locator('img').all():img.scroll_into_view_if_needed()
                    page.wait_for_function('Array.from(document.images).every(img=>img.complete && img.naturalWidth>0)')
                    page.evaluate('scrollTo(0,0)')
                for width,columns in [(390,1),(768,2),(1440,3)]:
                    context=browser.new_context(viewport={'width':width,'height':960})
                    page=context.new_page(); errors=[]; failed=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.on('response',lambda r:failed.append(r.url) if r.status>=400 else None)
                    page.goto(BASE+'/menu/')
                    images_loaded(page)
                    expect(page.get_by_role('heading',name='The menu',exact=True)).to_be_visible()
                    assert page.locator('.product-card').count()==6
                    assert page.locator('.product-grid').evaluate('el=>getComputedStyle(el).gridTemplateColumns.split(" ").length')==columns
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert page.locator('.product-price').evaluate_all('(nodes)=>nodes.every(el=>el.scrollWidth<=el.clientWidth)')
                    page.screenshot(path=str(OUTPUT/f'menu-public-{width}.png'),full_page=True)
                    add=page.get_by_role('button',name='Add Classic Cappuccino to bag',exact=True)
                    add.focus(); assert add.evaluate('el=>getComputedStyle(el).outlineStyle')!='none'
                    assert add.bounding_box()['width']>=44 and add.bounding_box()['height']>=44
                    add.press('Enter')
                    expect(page.locator('.bag-total')).to_have_text('Rs. 1,100')
                    expect(page.locator('.nav-links .bag')).to_contain_text('Bag (1)')
                    assert not errors and not failed,(errors,failed)
                    staff_context=browser.new_context(viewport={'width':width,'height':960})
                    staff_page=staff_context.new_page(); login(staff_page,'menu-qa')
                    staff_page.goto(BASE+'/staff/catalogue/')
                    images_loaded(staff_page)
                    assert staff_page.locator('.staff-product').count()==6
                    assert staff_page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    staff_page.screenshot(path=str(OUTPUT/f'menu-staff-{width}.png'),full_page=True)
                    staff_page.get_by_label('Name or slug').fill('Rose')
                    staff_page.get_by_role('button',name='Apply filters',exact=True).click()
                    assert staff_page.locator('.staff-product').count()==1
                    expect(staff_page.locator('.staff-product')).to_contain_text('Rose Latte')
                    staff_context.close(); context.close()
                    passed.append(f'{width}px: public {columns}-column grid and staff thumbnails, images, prices, keyboard Add to bag and search passed')
                    print(passed[-1],flush=True)
                customer_context=browser.new_context(viewport={'width':390,'height':960})
                customer=customer_context.new_page()
                customer.goto(BASE+f'/orders/scan/{location.token}/')
                expect(customer.locator('.service-notice')).to_contain_text(location.label)
                customer.get_by_role('button',name='Add Classic Cappuccino to bag',exact=True).click()
                customer.get_by_role('link',name='Review dine-in order',exact=True).click()
                customer.get_by_role('button',name='Place dine-in order',exact=True).click()
                receipt_url=customer.url
                reference=customer.locator('.workflow-reference').inner_text()
                order=orm(lambda:DineInOrder.objects.get(reference=reference))
                assert order.location_id==location.pk and order.location_label==location.label
                assert orm(lambda:order.lines.get().unit_price)==Decimal('1100')
                staff_context=browser.new_context(viewport={'width':1440,'height':960})
                operator=staff_context.new_page(); login(operator,'menu-qa')
                edit=BASE+f'/admin/menu/menuitem/{coffee.pk}/change/'
                operator.goto(edit)
                operator.locator('#id_image').set_input_files(str(ROOT/'static/images/editorial/classic-cappuccino.webp'))
                operator.locator('#id_image_alt').fill('Cappuccino with heart latte art in a ceramic cup')
                operator.locator('#id_price').fill('1245.75')
                operator.locator('#id_display_order').fill('99')
                operator.get_by_role('button',name='Save',exact=True).click()
                orm(coffee.refresh_from_db)
                first_photo=coffee.image.name
                customer.goto(BASE+'/menu/')
                card=customer.locator('.product-card').filter(has=customer.get_by_role('heading',name=coffee.name,exact=True))
                expect(card).to_contain_text('Rs. 1,245.75')
                expect(card.locator('img')).to_have_attribute('src',coffee.image.url)
                expect(card.locator('img')).to_have_attribute('alt','Cappuccino with heart latte art in a ceramic cup')
                assert customer.locator('.product-card').last.locator('h2').inner_text()==coffee.name
                assert customer.request.get(BASE+coffee.image.url).status==200
                operator.goto(edit)
                operator.screenshot(path=str(OUTPUT/'menu-admin-photo-preview.png'),full_page=True)
                operator.locator('#id_image').set_input_files(str(ROOT/'static/images/editorial/rose-latte.webp'))
                operator.locator('#id_image_alt').fill('Replacement test product photo')
                operator.get_by_role('button',name='Save',exact=True).click()
                orm(coffee.refresh_from_db); assert coffee.image.name!=first_photo
                customer.reload()
                expect(card.locator('img')).to_have_attribute('src',coffee.image.url)
                customer.goto(receipt_url)
                expect(customer.get_by_text('Total: Rs. 1,100',exact=True)).to_be_visible()
                assert orm(lambda:order.lines.get().unit_price)==Decimal('1100')
                customer.goto(BASE+'/menu/')
                customer.get_by_role('button',name='Add Rose Latte to bag',exact=True).click()
                operator.goto(BASE+f'/admin/menu/menuitem/{rose.pk}/change/')
                operator.locator('#id_active').uncheck()
                operator.get_by_role('button',name='Save',exact=True).click()
                customer.reload()
                expect(customer.get_by_text('Your bag was updated.',exact=False)).to_be_visible()
                expect(customer.get_by_text('Your bag is empty.',exact=False)).to_be_visible()
                customer.goto(BASE+'/menu/')
                assert customer.get_by_role('button',name='Add Rose Latte to bag',exact=True).count()==0
                operator.goto(BASE+'/staff/catalogue/?status=inactive')
                expect(operator.locator('.staff-product')).to_contain_text('Rose Latte')
                passed.append('Actual Admin upload/replacement, alt text, price, display order and visibility propagate to public menu; uploaded media loads; past receipt/line price stays 1100; QR table survives checkout; unavailable bag item is removed with feedback')
                print(passed[-1],flush=True)
                # Upload errors are returned in the same editor without losing the item.
                invalid=folder/'invalid.svg'; invalid.write_text('<svg/>')
                operator.goto(edit)
                operator.locator('#id_image').set_input_files(str(invalid))
                operator.get_by_role('button',name='Save',exact=True).click()
                expect(operator.locator('.errornote')).to_be_visible()
                custom=orm(lambda:MenuItem.objects.create(name='Seasonal menu addition with a longer name',slug='menu-qa-new',price='9876.54',display_order=1))
                customer.goto(BASE+'/menu/')
                new_card=customer.locator('.product-card').filter(has=customer.get_by_role('heading',name=custom.name,exact=True))
                expect(new_card.locator('img')).to_have_attribute('src','/static/images/product-placeholder.svg')
                expect(new_card).to_contain_text('Rs. 9,876.54')
                assert new_card.locator('.product-price').evaluate('el=>el.scrollWidth<=el.clientWidth')
                assert customer.request.get(BASE+'/static/images/product-placeholder.svg').status==200
                viewer_context=browser.new_context(); view=viewer_context.new_page(); login(view,'menu-viewer')
                view.goto(BASE+'/staff/catalogue/')
                assert view.get_by_role('link',name='Edit item',exact=False).count()==0
                view.goto(edit)
                assert view.locator('input[name=_save]').count()==0
                view.goto(BASE+'/staff/catalogue/')
                csrf=view.locator('form[action="/staff/logout/"] input[name=csrfmiddlewaretoken]').input_value()
                assert view.request.post(edit,form={'csrfmiddlewaretoken':csrf,'price':'1'}).status==403
                outsider_context=browser.new_context(); outsider=outsider_context.new_page(); login(outsider,'menu-customer')
                expect(outsider.get_by_text('A staff account is required.',exact=True)).to_be_visible()
                passed.append('Invalid upload feedback, image-less/new-item fallback and long price/name, read-only staff permissions and non-staff rejection passed')
                print(passed[-1],flush=True)
            finally:browser.close()
    assert fingerprint(original_db)==original,'Real cafe records changed'
    (OUTPUT/'menu-checks.json').write_text(json.dumps({'passed':passed,'data':'isolated database/media; real business records unchanged'},indent=2))


if __name__=='__main__':run()
