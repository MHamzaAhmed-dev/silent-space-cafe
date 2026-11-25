from django.urls import path
from . import views
from bookings.views import request_seat

app_name = 'core'
urlpatterns = [
    path('', views.home, name='home'),
    path('our-story/', views.content_page, {'page': 'story'}, name='story'),
    path('menu/', views.content_page, {'page': 'menu'}, name='menu'),
    path('spaces/', views.spaces, name='zones'),
    path('quiet-zones/', views.legacy_spaces, name='legacy_zones'),
    path('book-a-table/', request_seat, name='booking'),
]
