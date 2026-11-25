"""
Silent Space Café — ASGI Configuration
"""

import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'silent_space.settings')

application = get_asgi_application()
