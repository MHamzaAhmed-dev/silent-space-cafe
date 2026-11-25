"""PythonAnywhere staging. Configuration is mandatory and outside the checkout."""
import json
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

os.environ['SILENT_SPACE_SKIP_DOTENV'] = '1'
config_path = Path(os.environ['STAGING_CONFIG']).expanduser().resolve()
config = json.loads(config_path.read_text())
from .settings import *  # noqa: F403,E402

data_dir = Path(config['data_dir']).expanduser().resolve()
if config_path.is_relative_to(BASE_DIR) or data_dir.is_relative_to(BASE_DIR):
    raise ImproperlyConfigured('Staging secrets and data must be outside the Git checkout.')
SECRET_KEY = config['secret_key']
if len(SECRET_KEY) < 50 or SECRET_KEY.startswith(('django-insecure-', 'GENERATE_')):
    raise ImproperlyConfigured('Provide a random staging secret of at least 50 characters.')
DEBUG = False
STAGING_MODE = True
ALLOWED_HOSTS = [config['hostname']]
CSRF_TRUSTED_ORIGINS = ['https://' + config['hostname']]
SITE_BASE_URL = CSRF_TRUSTED_ORIGINS[0]
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': data_dir / 'db.sqlite3'}}
MEDIA_ROOT = data_dir / 'media'
MEDIA_URL = '/media/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATIC_URL = '/static/'
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
# PythonAnywhere supplies the HTTPS scheme to its WSGI application.
# Do not trust arbitrary client proxy headers here.
SECURE_PROXY_SSL_HEADER = None
SECURE_HSTS_SECONDS = 0  # Enable only after host HTTPS has been verified.
EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'
EMAIL_FILE_PATH = data_dir / 'test-emails'
EMAIL_HOST = EMAIL_HOST_USER = EMAIL_HOST_PASSWORD = ''
DEFAULT_FROM_EMAIL = 'staging@example.test'
STAFF_NOTIFICATION_RECIPIENTS = ['staging-inbox@example.test']
STRIPE_SECRET_KEY = STRIPE_WEBHOOK_SECRET = ''
