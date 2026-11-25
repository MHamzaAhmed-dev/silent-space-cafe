from django.db import models
from django.utils import timezone


class Notification(models.Model):
    event_key = models.CharField(max_length=160, unique=True)
    kind = models.CharField(max_length=40)
    order = models.ForeignKey('orders.DineInOrder', null=True, blank=True, on_delete=models.PROTECT)
    reservation = models.ForeignKey('bookings.ReservationRequest', null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, default='pending', choices=[(v, v.title()) for v in ['pending', 'processing', 'sent', 'failed', 'skipped']])
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
