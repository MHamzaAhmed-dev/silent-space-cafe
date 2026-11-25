from django.urls import path
from . import checkout, views, payments

app_name = 'orders'
urlpatterns = [
    path('payments/stripe/webhook/', payments.stripe_webhook, name='stripe_webhook'),
    path('receipt/<uuid:reference>/transfer/', payments.transfer_reference, name='transfer_reference'),
    path('receipt/<uuid:reference>/card/', payments.hosted_checkout, name='hosted_checkout'),
    path('scan/<uuid:token>/', checkout.scan, name='scan'),
    path('checkout/', checkout.checkout, name='checkout'),
    path('receipt/<uuid:reference>/', checkout.receipt, name='receipt'),
    path('bag/', views.bag_detail, name='bag'),
    path('bag/<int:pk>/<str:action>/', views.bag_change, name='bag_change'),
]
