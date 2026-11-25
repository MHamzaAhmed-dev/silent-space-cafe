from django.urls import path
from . import views

app_name = 'staff'
urlpatterns = [
    path('orders/<int:pk>/verify-payment/', views.payment_verify, name='payment_verify'),
    path('login/', views.StaffLoginView.as_view(), name='login'),
    path('logout/', views.StaffLogoutView.as_view(), name='logout'),
    path('', views.overview, name='overview'),
    path('orders/', views.orders, name='orders'),
    path('orders/<int:pk>/', views.order_detail, name='order_detail'),
    path('orders/<int:pk>/action/', views.order_action, name='order_action'),
    path('reservations/', views.reservations, name='reservations'),
    path('reservations/<int:pk>/', views.reservation_detail, name='reservation_detail'),
    path('reservations/<int:pk>/action/', views.reservation_action, name='reservation_action'),
    path('catalogue/', views.catalogue, name='catalogue'),
    path('notifications/', views.notifications, name='notifications'),
    path('notifications/<int:pk>/retry/', views.notification_retry, name='notification_retry'),
]
