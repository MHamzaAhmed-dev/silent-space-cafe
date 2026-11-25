"""
Silent Space Café — WSGI Configuration
"""

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'silent_space.settings')

application = get_wsgi_application()
