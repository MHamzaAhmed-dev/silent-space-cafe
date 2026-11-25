import uuid

from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator


class DeliveryArea(models.Model):
    name = models.CharField(max_length=100, unique=True)
    fee = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        constraints = [models.CheckConstraint(condition=models.Q(fee__gte=0), name='delivery_fee_nonnegative')]

    def __str__(self):
        return self.name


class PaymentMethod(models.Model):
    class Code(models.TextChoices):
        JAZZCASH = 'jazzcash', 'JazzCash'
        EASYPAISA = 'easypaisa', 'Easypaisa'
        CARD = 'card', 'Card (Visa / Mastercard)'
        COD = 'cod', 'Cash on delivery'
        CASH = 'cash', 'Cash at pickup / cafe'

    code = models.CharField(max_length=12, choices=Code.choices, unique=True)
    enabled = models.BooleanField(default=True)
    delivery = models.BooleanField(default=False)
    pickup = models.BooleanField(default=False)
    dine_in = models.BooleanField(default=False)
    receiver = models.CharField(max_length=100, blank=True)
    instructions = models.TextField(blank=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'pk']

    def __str__(self):
        return self.get_code_display()


class ServiceLocation(models.Model):
    label = models.CharField(max_length=80, unique=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return self.label


class DineInOrder(models.Model):
    class Fulfilment(models.TextChoices):
        DINE_IN = 'dine_in', 'Dine-in'
        DELIVERY = 'delivery', 'Delivery'
        PICKUP = 'pickup', 'Pickup'

    class PaymentStatus(models.TextChoices):
        UNPAID = 'unpaid', 'Awaiting payment'
        PENDING = 'pending', 'Pending verification'
        PAID = 'paid', 'Paid'
        REJECTED = 'rejected', 'Rejected'

    class Status(models.TextChoices):
        RECEIVED = 'received', 'Received'
        PREPARING = 'preparing', 'Preparing'
        OUT_DELIVERY = 'out_delivery', 'Out for delivery'
        READY_PICKUP = 'ready_pickup', 'Ready for pickup'
        COMPLETED = 'completed', 'Completed'

    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    submission_key = models.UUIDField(unique=True, editable=False)
    location = models.ForeignKey(ServiceLocation, on_delete=models.PROTECT, null=True, blank=True)
    location_label = models.CharField(max_length=100)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RECEIVED)
    total = models.DecimalField(max_digits=16, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    fulfilment = models.CharField(max_length=12, choices=Fulfilment.choices, default=Fulfilment.DINE_IN)
    customer_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    delivery_area = models.ForeignKey(DeliveryArea, null=True, blank=True, on_delete=models.PROTECT)
    delivery_area_name = models.CharField(max_length=100, blank=True)
    street_address = models.CharField(max_length=500, blank=True)
    notes = models.TextField(blank=True)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=12, choices=PaymentMethod.Code.choices, blank=True)
    payment_receiver = models.CharField(max_length=100, blank=True)
    payment_instructions = models.TextField(blank=True)
    payment_status = models.CharField(max_length=12, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    transaction_reference = models.CharField(max_length=120, blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    verified_at = models.DateTimeField(null=True, blank=True)
    gateway_session = models.CharField(max_length=255, blank=True)
    gateway_url = models.URLField(max_length=2048, blank=True)

    @property
    def manual_payment_pending(self):
        return (self.fulfilment in ('delivery', 'pickup') and
                self.payment_method in ('jazzcash', 'easypaisa') and
                self.payment_status == 'pending' and bool(self.transaction_reference.strip()))

    class Meta:
        permissions = [('verify_payment', 'Can verify order payments')]


class PaymentEvent(models.Model):
    event_id = models.CharField(max_length=255, unique=True)
    order = models.ForeignKey(DineInOrder, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class OrderLine(models.Model):
    order = models.ForeignKey(DineInOrder, related_name='lines', on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveSmallIntegerField()

    @property
    def subtotal(self):
        return self.unit_price * self.quantity
