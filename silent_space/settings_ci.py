"""Isolated CI: no local .env, persistent data, SMTP or gateway credentials."""
import os
import tempfile
from pathlib import Path

os.environ['SILENT_SPACE_SKIP_DOTENV'] = '1'
from .settings import *  # noqa: F403,E402

SECRET_KEY = 'ci-only-not-a-deployment-secret-0123456789abcdefghijk'
DEBUG = False
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
_temporary_files = tempfile.TemporaryDirectory(prefix='silent-space-ci-')
MEDIA_ROOT = Path(_temporary_files.name) / 'media'
STATIC_ROOT = Path(_temporary_files.name) / 'static'
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
EMAIL_HOST = EMAIL_HOST_USER = EMAIL_HOST_PASSWORD = ''
STAFF_NOTIFICATION_RECIPIENTS = ['ci@example.test']
STRIPE_SECRET_KEY = STRIPE_WEBHOOK_SECRET = ''
SECURE_SSL_REDIRECT = SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
