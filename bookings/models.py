import uuid

from django.db import models


class ReservationRequest(models.Model):
    class Zone(models.TextChoices):
        QUIET = 'quiet', 'Quiet Corner'
        READING = 'reading', 'Reading Zone'
        SOLO = 'solo', 'Solo Space'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending review'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        CANCELLED = 'cancelled', 'Cancelled'

    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    submission_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=1000, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    name = models.CharField(max_length=120)
    email = models.EmailField(blank=True)
    date = models.DateField()
    time = models.TimeField()
    guests = models.PositiveSmallIntegerField(choices=[(n, str(n)) for n in range(1, 7)])
    zone = models.CharField(max_length=12, choices=Zone.choices)
    special_request = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.get_zone_display()} | {self.date} | {self.name}'


class ZoneCapacity(models.Model):
    zone = models.CharField(max_length=12, choices=ReservationRequest.Zone.choices, unique=True)
    seats = models.PositiveSmallIntegerField(help_text='Zero closes this zone to new bookings.')

    def __str__(self):
        return self.get_zone_display()


class BookingHours(models.Model):
    weekday = models.PositiveSmallIntegerField(choices=list(enumerate(
        ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    )), unique=True)
    opens = models.TimeField()
    closes = models.TimeField()

    class Meta:
        verbose_name_plural = 'booking hours'
        constraints = [models.CheckConstraint(
            condition=models.Q(opens__lt=models.F('closes')), name='booking_hours_open_before_close'
        )]

    def __str__(self):
        return self.get_weekday_display()
