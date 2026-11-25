"""Editorial homepage browser review with isolated data and no outgoing email."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import time, timedelta
from io import StringIO
import json
import os
from pathlib import Path
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
from tools.booking_browser import choose_booking_time

BASE='http://127.0.0.1:8003'
OUTPUT=ROOT/'artifacts'


def run():
    original_db=settings.DATABASES['default']['NAME']
    original=fingerprint(original_db)
    OUTPUT.mkdir(exist_ok=True)
    results=[]
    with tempfile.TemporaryDirectory(prefix='silent-space-homepage-') as directory, ExitStack() as stack:
        folder=Path(directory)
        db=folder/'homepage.sqlite3'
        settings.DATABASES['default']['NAME']=str(db)
        settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
        django.setup()
        from django.utils import timezone
        from bookings.models import BookingHours, ZoneCapacity
        from menu.models import MenuItem
        from orders.models import ServiceLocation
        call_command('migrate',verbosity=0)
        call_command('seed_menu',stdout=StringIO())
        day=timezone.localdate()+timedelta(days=1)
        BookingHours.objects.create(weekday=day.weekday(),opens=time(10),closes=time(18))
        ZoneCapacity.objects.create(zone='quiet',seats=6)
        ZoneCapacity.objects.create(zone='reading',seats=4)
        ZoneCapacity.objects.create(zone='solo',seats=1)
        location=ServiceLocation.objects.create(label='Homepage QA Table')
        code="""import os,sys
os.environ['DJANGO_SETTINGS_MODULE']='silent_space.settings'
from django.conf import settings
settings.DATABASES['default']['NAME']=sys.argv[1]
settings.DEBUG=True
settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
import django
django.setup()
from django.core.management import call_command
call_command('runserver','127.0.0.1:8003',use_reloader=False,verbosity=0)
"""
        log=stack.enter_context(open(folder/'server.log','w'))
        process=subprocess.Popen([sys.executable,'-c',code,str(db)],cwd=ROOT,stdout=log,stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        stack.callback(lambda:clock.sleep(1))
        stack.callback(connections.close_all)
        stack.callback(stop_process,process)
        for _ in range(60):
            try:
                if urlopen(BASE,timeout=2).status==200: break
            except Exception:
                if process.poll() is not None: raise RuntimeError('Homepage preview failed')
                clock.sleep(.25)
        else: raise RuntimeError('Homepage preview did not start')
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
                    page=context.new_page()
                    errors=[]; failed=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('response',lambda r:failed.append(r.url) if r.status>=400 else None)
                    page.goto(BASE)
                    page.locator('#book-a-table').scroll_into_view_if_needed()
                    page.locator('.site-header').scroll_into_view_if_needed()
                    page.evaluate('window.scrollTo(0,0)')
                    expect(page.get_by_role('heading',name='A quiet place to think.',exact=True)).to_be_visible()
                    assert page.locator('.menu-card').count()==3
                    assert page.locator('.zone-card').count()==3
                    assert page.locator('.booking-form').count()==1
                    assert page.locator('.booking-form').get_attribute('action')=='/book-a-table/'
                    assert page.locator('input[name=csrfmiddlewaretoken]').count()>=4
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert page.locator('img').evaluate_all('(images)=>images.every(img=>img.complete && img.naturalWidth>0)')
                    assert page.locator('.menu-photo').evaluate_all('(images)=>images.every(img=>img.clientHeight/img.clientWidth<0.8)')
                    for anchor in page.locator('a[href^="#"]').all():
                        target=anchor.get_attribute('href')
                        assert page.locator(target).count()==1,target
                    page.screenshot(path=str(OUTPUT/f'homepage-editorial-{width}.png'),full_page=True)
                    page.screenshot(path=str(OUTPUT/f'homepage-editorial-first-screen-{width}.png'))
                    page.get_by_role('link',name='Explore the spaces',exact=True).click()
                    assert page.url==BASE+'/spaces/'
                    page.goto(BASE)
                    page.get_by_role('link',name='View full menu',exact=True).click()
                    assert page.url==BASE+'/menu/'
                    assert page.locator('.menu-card').count()==6
                    page.goto(BASE)
                    page.get_by_role('button',name='Add Classic Cappuccino to bag',exact=True).click()
                    expect(page.locator('.bag-total')).to_have_text('Rs. 1,100')
                    expect(page.locator('.nav-links .bag')).to_contain_text('Bag (1)')
                    page.get_by_role('button',name='Increase Classic Cappuccino',exact=True).click()
                    expect(page.locator('.bag-total')).to_have_text('Rs. 2,200')
                    page.reload()
                    expect(page.locator('.bag-total')).to_have_text('Rs. 2,200')
                    page.get_by_role('button',name='Decrease Classic Cappuccino',exact=True).click()
                    page.get_by_role('button',name='Remove Classic Cappuccino',exact=True).click()
                    page.goto(BASE)
                    # Real shared navigation, including its keyboard mobile toggle.
                    if width<=900:
                        page.get_by_role('button',name='Menu',exact=True).click()
                    page.locator('.nav-links .bag').click()
                    assert page.url==BASE+'/orders/bag/'
                    page.goto(BASE)
                    hero_reserve=page.locator('.hero-actions').get_by_role('link',name='Reserve a seat',exact=True)
                    hero_reserve.focus()
                    assert hero_reserve.evaluate("el=>getComputedStyle(el).outlineStyle")!='none'
                    hero_reserve.press('Enter')
                    assert page.url==BASE+'/book-a-table/'
                    page.goto(BASE)
                    page.locator('.reservation-banner').get_by_role('link',name='Reserve a seat',exact=True).click()
                    assert page.url==BASE+'/book-a-table/'
                    page.locator('#id_name').fill('Homepage Guest')
                    page.locator('#id_email').fill('guest@example.test')
                    page.locator('#id_phone').fill('03001234567')
                    choose_booking_time(page,day,guests='1',value='18:00',unavailable=True)
                    page.locator('[data-request-submit]').click()
                    expect(page.get_by_role('alert')).to_contain_text('Check the highlighted fields')
                    expect(page.get_by_text('This one-hour slot is outside the configured booking hours.',exact=True)).to_be_visible()
                    expect(page.locator('#id_name')).to_have_value('Homepage Guest')
                    page.locator('#id_time').select_option('11:00')
                    page.locator('[data-request-submit]').click()
                    expect(page.get_by_role('heading',name='Pending review',exact=True)).to_be_visible()
                    page.goto(BASE+'/orders/scan/'+str(location.token)+'/')
                    if width<=900:
                        page.get_by_role('button',name='Menu',exact=True).click()
                    page.locator('.nav-links').get_by_role('link',name='Menu',exact=True).click()
                    expect(page.locator('.service-notice')).to_contain_text(location.label)
                    page.get_by_role('button',name='Add Classic Cappuccino to bag',exact=True).click()
                    page.get_by_role('link',name='Review dine-in order',exact=True).click()
                    expect(page.get_by_text(location.label,exact=True)).to_be_visible()
                    # Escape closes the mobile navigation and returns focus to its toggle.
                    if width<=900:
                        toggle=page.get_by_role('button',name='Menu',exact=True)
                        toggle.click(); page.keyboard.press('Escape')
                        expect(toggle).to_have_attribute('aria-expanded','false')
                        expect(toggle).to_be_focused()
                    assert not errors,errors
                    assert not failed,failed
                    for route in ['/our-story/','/quiet-zones/','/menu/','/book-a-table/','/orders/bag/']:
                        assert page.goto(BASE+route).status==200
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,route)
                    results.append(f'{width}px: images, anchors, hero/menu/bag/reserve navigation, keyboard focus, bag persistence, QR location and invalid/valid booking feedback passed')
                    print(results[-1],flush=True)
                    context.close()
                context=browser.new_context(java_script_enabled=False,viewport={'width':390,'height':960})
                page=context.new_page(); page.goto(BASE)
                page.get_by_role('button',name='Add Rose Latte to bag',exact=True).click()
                expect(page.locator('.bag-total')).to_have_text('Rs. 1,500')
                page.goto(BASE)
                page.locator('.nav-links').get_by_role('link',name='Reservations',exact=True).click()
                assert page.url==BASE+'/book-a-table/'
                context.close()
                context=browser.new_context(viewport={'width':1440,'height':960})
                page=context.new_page()
                orm(lambda:MenuItem.objects.filter(slug='rose-latte').update(price='1523.45'))
                page.goto(BASE)
                expect(page.locator('.menu-card').filter(has=page.get_by_role('heading',name='Rose Latte',exact=True))).to_contain_text('Rs. 1,523.45')
                orm(lambda:MenuItem.objects.filter(slug='rose-latte').update(active=False))
                page.reload()
                assert page.get_by_role('heading',name='Rose Latte',exact=True).count()==0
                assert page.locator('.menu-card').count()==3
                page.get_by_role('link',name='Reserve Reading Zone',exact=True).click()
                expect(page.locator('#id_zone')).to_have_value('reading')
                context.close()
                results.append('No-JavaScript navigation/bag, live price/availability changes and zone preselection passed')
                print(results[-1],flush=True)
            finally:browser.close()
    assert fingerprint(original_db)==original,'Real business records changed'
    (OUTPUT/'homepage-editorial-checks.json').write_text(json.dumps({'passed':results,'database':'isolated; real business records unchanged'},indent=2))


if __name__=='__main__': run()
