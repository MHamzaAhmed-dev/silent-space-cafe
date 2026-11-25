from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8001'
Path('artifacts').mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    for width in (390, 768, 1440):
        context = browser.new_context(java_script_enabled=False, viewport={'width': width, 'height': 900})
        page = context.new_page()
        page.goto(BASE)
        assert page.locator('.menu-card').count() == 6
        assert page.locator('body').bounding_box()['width'] == width
        page.screenshot(path=f'artifacts/phase2-home-{width}.png', full_page=True)
        page.get_by_role('button', name='Add Classic Cappuccino to bag', exact=True).click()
        assert page.locator('.line-subtotal').inner_text() == 'Subtotal: Rs. 1,100'
        page.get_by_role('button', name='Increase Classic Cappuccino', exact=True).click()
        assert page.locator('.bag-total').inner_text() == 'Rs. 2,200'
        page.reload()
        assert page.get_by_role('link', name='Bag (2)', exact=True).count() == 1
        # JS is disabled: use the DOM layout engine through locator bounds to check overflow.
        for element in page.locator('main, .bag-layout, .bag-line, .bag-summary, .quantity-controls').all():
            bounds = element.bounding_box()
            assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width + 1, bounds
        page.screenshot(path=f'artifacts/phase2-bag-{width}.png', full_page=True)
        page.get_by_role('button', name='Decrease Classic Cappuccino', exact=True).click()
        assert page.locator('.bag-total').inner_text() == 'Rs. 1,100'
        page.get_by_role('button', name='Remove Classic Cappuccino', exact=True).click()
        assert page.get_by_text('Your bag is empty.', exact=False).count() == 1
        page.get_by_role('link', name='Back to the menu', exact=True).click()
        assert page.url.endswith('/#menu')
        print(f'{width}px: no-JavaScript add/increase/decrease/remove, refresh, empty state and menu link passed')
        context.close()
    browser.close()
