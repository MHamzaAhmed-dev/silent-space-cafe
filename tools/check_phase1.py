"""Optional Phase 1 browser check: pip install playwright; uses installed Chrome."""
from pathlib import Path
from playwright.sync_api import sync_playwright

out = Path('artifacts')
out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    for width in (390, 768, 1440):
        page.set_viewport_size({'width': width, 'height': 900})
        response = page.goto('http://127.0.0.1:8000/')
        assert response.status == 200
        assert page.locator('.menu-card').count() == 6
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow at {width}'
        assert page.locator('.story img').evaluate('(img) => img.complete && img.naturalWidth > 0')
        if width > 640:
            assert not page.locator('.nav-toggle').is_visible()
        if width == 390:
            toggle = page.get_by_role('button', name='Menu', exact=False).first
            toggle.click()
            assert toggle.get_attribute('aria-expanded') == 'true'
            page.get_by_role('link', name='Our Story', exact=True).click()
            assert toggle.get_attribute('aria-expanded') == 'false'
            toggle.click()
            page.keyboard.press('Escape')
            assert toggle.get_attribute('aria-expanded') == 'false'
        for anchor in page.locator('.nav-links a').all():
            assert page.locator('#' + anchor.get_attribute('href').split('#')[-1]).count() == 1
        assert page.locator('.bag').get_attribute('href') == '/orders/bag/'
        assert page.locator('.booking-form button').is_disabled()
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(out / f'home-{width}.png'), full_page=True, animations='disabled')
        print(f'{width}px: no overflow; image, links, disabled actions OK')
    assert not errors, errors
    browser.close()
