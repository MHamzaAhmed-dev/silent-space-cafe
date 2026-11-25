"""Isolated DEBUG=False WSGI rehearsal with a local host static/media adapter."""
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ['DJANGO_SETTINGS_MODULE'] = 'silent_space.settings'


def serve(folder):
    from django.conf import settings
    settings.DEBUG = False
    settings.ALLOWED_HOSTS = ['127.0.0.1']
    settings.DATABASES['default']['NAME'] = str(folder / 'qa.sqlite3')
    settings.STATIC_ROOT = folder / 'static'
    settings.MEDIA_ROOT = folder / 'media'
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    settings.STRIPE_SECRET_KEY = settings.STRIPE_WEBHOOK_SECRET = ''
    from django.core.wsgi import get_wsgi_application
    app = get_wsgi_application()
    # Models the host's static/media server; this is not a deployment server.
    def hosted(environ, start_response):
        path = environ.get('PATH_INFO', '')
        for prefix, root in [('/static/', settings.STATIC_ROOT), ('/media/', settings.MEDIA_ROOT)]:
            if path.startswith(prefix):
                target = (root / path[len(prefix):]).resolve()
                if target.is_relative_to(root.resolve()) and target.is_file():
                    body = target.read_bytes()
                    start_response('200 OK', [('Content-Type', mimetypes.guess_type(str(target))[0] or 'application/octet-stream'), ('Content-Length', str(len(body)))])
                    return [body]
                start_response('404 Not Found', [('Content-Type', 'text/plain')])
                return [b'Not found']
        return app(environ, start_response)
    from wsgiref.simple_server import make_server
    make_server('127.0.0.1', 8011, hosted).serve_forever()


def run():
    from django.conf import settings
    from tools.check_acceptance import fingerprint, stop_process
    original_db = settings.DATABASES['default']['NAME']
    before = fingerprint(original_db)
    results = []
    with tempfile.TemporaryDirectory(prefix='silent-launch-') as directory:
        folder = Path(directory)
        settings.DEBUG = False
        settings.DATABASES['default']['NAME'] = str(folder / 'qa.sqlite3')
        settings.STATIC_ROOT = folder / 'static'
        settings.MEDIA_ROOT = folder / 'media'
        settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
        import django
        django.setup()
        from django.core.management import call_command
        from django.core.files.base import ContentFile
        from django.db import connections
        from menu.models import MenuItem
        from PIL import Image
        from io import BytesIO, StringIO
        call_command('migrate', verbosity=0)
        call_command('seed_menu', stdout=StringIO())
        photo = BytesIO()
        Image.new('RGB', (100, 100), '#808060').save(photo, format='PNG')
        item = MenuItem.objects.first()
        item.image.save('launch-test.png', ContentFile(photo.getvalue()), save=False)
        item.image_alt = 'Launch test product photo'
        item.save()
        upload = item.image.url
        call_command('collectstatic', interactive=False, verbosity=0)
        with open(folder / 'server.log', 'w') as log:
            process = subprocess.Popen([sys.executable, __file__, '--serve', directory], cwd=ROOT,
                stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                for _ in range(60):
                    try:
                        urlopen('http://127.0.0.1:8011/', timeout=2).close()
                        break
                    except OSError:
                        time.sleep(.5)
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    browser = p.chromium.launch(channel='chrome', headless=True)
                    page = browser.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    for width in (390, 768, 1440):
                        page.set_viewport_size({'width': width, 'height': 1000})
                        for path in ('/', '/menu/', '/spaces/', '/book-a-table/', '/orders/bag/'):
                            if path == '/orders/bag/':
                                page.goto('http://127.0.0.1:8011/menu/')
                                page.locator('.product-add').first.click()
                            assert page.goto('http://127.0.0.1:8011' + path).status == 200
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, path)
                            assets = page.locator('link[rel=stylesheet],script[src],img').evaluate_all('(els)=>els.map(e=>e.href||e.src)')
                            for url in assets:
                                response = page.request.get(url)
                                assert response.status == 200, (url, response.status)
                                content_type = response.headers.get('content-type', '')
                                assert 'text/html' not in content_type, (url, content_type)
                                if '.css' in url: assert 'text/css' in content_type
                            results.append(f'{width}px {path}: collected CSS/JS/photos, layout and HTTP 200')
                    response = page.request.get('http://127.0.0.1:8011' + upload)
                    assert response.status == 200 and 'image/png' in response.headers['content-type']
                    assert not errors, errors
                    browser.close()
            finally:
                stop_process(process)
                connections.close_all()
    assert before == fingerprint(original_db), 'Live business records changed during rehearsal'
    report = {'status': 'Pass', 'debug': False, 'server': 'WSGI with local host static/media adapter',
        'checks': results, 'uploaded_media': 'Pass', 'live_database_unchanged': True,
        'limits': 'Host server configuration, real TLS and external storage still require deployment verification.'}
    (ROOT / 'artifacts' / 'launch-production.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    serve(Path(sys.argv[2])) if len(sys.argv) > 1 and sys.argv[1] == '--serve' else run()
