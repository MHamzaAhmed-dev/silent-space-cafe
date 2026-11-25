from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8002'
Path('artifacts').mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    for width in (390, 768, 1440):
        context = browser.new_context(viewport={'width': width, 'height': 900})
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        for path in ('/', '/our-story/', '/menu/', '/quiet-zones/', '/book-a-table/', '/orders/bag/'):
            response = page.goto(BASE + path)
            assert response.status == 200, path
            assert page.locator('h1').count() == 1, path
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, path)
            assert page.locator('.footer-grid > div').count() == 4
            for anchor in page.locator('.nav-links a, .site-footer a').all():
                assert not anchor.get_attribute('href').startswith('#')
            if width <= 900:
                toggle = page.locator('.nav-toggle')
                toggle.click()
                assert toggle.get_attribute('aria-expanded') == 'true'
                page.keyboard.press('Escape')
                assert toggle.get_attribute('aria-expanded') == 'false'
            if path in ('/', '/menu/', '/orders/bag/'):
                page.screenshot(path=f'artifacts/multipage-{width}-{path.strip("/").replace("/", "-") or "home"}.png', full_page=True)
        page.goto(BASE + '/menu/')
        page.get_by_role('button', name='Add Classic Cappuccino to bag', exact=True).click()
        assert page.url.endswith('/orders/bag/')
        assert page.locator('.line-subtotal').inner_text() == 'Subtotal: Rs. 1,100'
        page.get_by_role('link', name='Back to the menu', exact=True).click()
        assert page.url.endswith('/menu/')
        assert not errors, errors
        print(f'{width}px: all six pages, navigation, footer, overflow and bag links passed')
        context.close()
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(BASE + '/menu/')
    page.get_by_role('button', name='Add Rose Latte to bag', exact=True).click()
    assert page.locator('.bag-total').inner_text() == 'Rs. 1,500'
    print('No-JavaScript database menu-to-bag flow passed')
    browser.close()
