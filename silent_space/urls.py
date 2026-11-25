"""
Silent Space Café — URL Configuration
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.views.generic import RedirectView
from django.templatetags.static import static as static_url
from django.conf.urls.static import static

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url=static_url('images/favicon.svg'), permanent=True), name='favicon'),
    path('admin/', admin.site.urls),
    path('staff/', include('staff_portal.urls')),
    path('', include('core.urls')),
    path('menu/', include('menu.urls')),
    path('bookings/', include('bookings.urls')),
    path('orders/', include('orders.urls')),
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
