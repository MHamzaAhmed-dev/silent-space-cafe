from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Sum
from django.utils import timezone

from .models import BookingHours, ReservationRequest, ZoneCapacity

PKT = ZoneInfo('Asia/Karachi')


def local_now(now=None):
    return timezone.localtime(now or timezone.now(), PKT)


def active_zone_choices():
    """Positive configured capacity is the existing open/active-zone rule."""
    configured = set(ZoneCapacity.objects.filter(seats__gt=0).values_list('zone', flat=True))
    return [(zone.value, zone.label) for zone in ReservationRequest.Zone if zone.value in configured]


def selection_error(*, date, guests, zone, now=None):
    if date < local_now(now).date():
        return 'date', 'Choose a future date and time in Pakistan Standard Time.'
    if guests < 1 or guests > 6:
        return 'guests', 'Choose between one and six guests.'
    if zone == ReservationRequest.Zone.SOLO and guests != 1:
        return 'guests', 'Solo Space is for one guest. Choose one guest or a different seating zone.'
    return None


def slot_error(*, date, time, guests, zone, now=None):
    """One-hour slots on the hour. Used by forms, availability and staff approval."""
    error = selection_error(date=date, guests=guests, zone=zone, now=now)
    if error:
        return error
    start = datetime.combine(date, time)
    if start <= local_now(now).replace(tzinfo=None):
        return 'date', 'Choose a future date and time in Pakistan Standard Time.'
    if time.minute or time.second or time.microsecond:
        return 'time', 'Choose a time on the hour. Reservations last one hour.'
    hours = BookingHours.objects.filter(weekday=date.weekday()).first()
    if not hours or time < hours.opens or start + timedelta(hours=1) > datetime.combine(date, hours.closes):
        return 'time', 'This one-hour slot is outside the configured booking hours.'
    seats = ZoneCapacity.objects.filter(zone=zone).values_list('seats', flat=True).first() or 0
    used = ReservationRequest.objects.filter(
        date=date, time=time, zone=zone, status=ReservationRequest.Status.APPROVED,
    ).aggregate(total=Sum('guests'))['total'] or 0
    if used + guests > seats:
        return 'zone', 'This zone cannot accommodate your group at that time.'
    return None


def available_slots(*, date, guests, zone, now=None):
    """Offer only slots accepted by the existing approval rule; Pending holds no seats."""
    now = now or timezone.now()
    if selection_error(date=date, guests=guests, zone=zone, now=now):
        return []
    hours = BookingHours.objects.filter(weekday=date.weekday()).first()
    if not hours:
        return []
    cursor = datetime.combine(date, hours.opens).replace(minute=0, second=0, microsecond=0)
    if cursor.time() < hours.opens:
        cursor += timedelta(hours=1)
    closes = datetime.combine(date, hours.closes)
    slots = []
    while cursor + timedelta(hours=1) <= closes:
        if not slot_error(date=date, time=cursor.time(), guests=guests, zone=zone, now=now):
            slots.append(cursor.time())
        cursor += timedelta(hours=1)
    return slots
