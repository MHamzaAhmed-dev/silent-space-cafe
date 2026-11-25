from django.urls import path
from .views import availability, reservation_status

app_name = 'bookings'
urlpatterns = [
    path('availability/', availability, name='availability'),
    path('status/<uuid:reference>/', reservation_status, name='status'),
]
