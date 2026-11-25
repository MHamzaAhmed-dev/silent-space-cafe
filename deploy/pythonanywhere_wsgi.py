"""Copy into the WSGI file linked from PythonAnywhere's Web tab; edit username."""
import os
import sys

os.environ['STAGING_CONFIG'] = '/home/YOUR_USERNAME/.config/silent-space/staging.json'
os.environ['DJANGO_SETTINGS_MODULE'] = 'silent_space.settings_staging'
sys.path.insert(0, '/home/YOUR_USERNAME/silent-space/current')

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
