from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from bookings.models import ReservationRequest
from orders.models import DineInOrder
from .models import Notification

PKT = ZoneInfo('Asia/Karachi')


def enqueue(kind, *, order=None, reservation=None):
    obj = order or reservation
    return Notification.objects.get_or_create(
        event_key=f'{kind}:{obj.reference}',
        defaults={'kind': kind, 'order': order, 'reservation': reservation},
    )[0]


def reservation_start(row):
    return timezone.make_aware(datetime.combine(row.date, row.time), PKT)


def eligible(job, now):
    if job.kind == 'order_reminder':
        return job.order.status == DineInOrder.Status.RECEIVED
    if job.kind == 'reservation_reminder':
        return (job.reservation.status == ReservationRequest.Status.APPROVED
                and reservation_start(job.reservation) > now)
    return True


def queue_reminders(now):
    for row in DineInOrder.objects.filter(status='received', created_at__lte=now-timedelta(minutes=settings.ORDER_REMINDER_MINUTES)):
        enqueue('order_reminder', order=row)
    local = now.astimezone(PKT)
    end = local + timedelta(minutes=settings.RESERVATION_REMINDER_MINUTES)
    for row in ReservationRequest.objects.filter(status='approved', date__range=(local.date(), end.date())):
        if now < reservation_start(row) <= end:
            enqueue('reservation_reminder', reservation=row)


def content(job):
    if job.order_id:
        row = job.order
        title = 'New Order' if job.kind == 'new_order' else 'Order still Received'
        lines = [f'{line.name} x {line.quantity}' for line in row.lines.all()]
        body = [f'Reference: {row.reference}', f'Placed: {row.created_at.astimezone(PKT):%Y-%m-%d %H:%M:%S} PKT',
                f'Table / zone: {row.location_label}', *lines, f'Total: PKR {row.total:.2f}']
        body.extend([f'Fulfilment: {row.get_fulfilment_display()}',
                     f'Delivery fee: PKR {row.delivery_fee:.2f}',
                     f'Payment method: {row.get_payment_method_display() or "Arrange with staff"}',
                     f'Payment status: {row.get_payment_status_display()}'])
        if row.fulfilment == 'delivery':
            body.append(f'Delivery: {row.delivery_area_name}, {row.street_address}')
        url = reverse('admin:orders_dineinorder_change', args=[row.pk])
    else:
        row = job.reservation
        title = 'New Reservation Request' if job.kind == 'new_reservation' else 'Upcoming Approved Reservation'
        body = [f'Reference: {row.reference}', f'Requested: {row.date} {row.time:%H:%M} PKT',
                f'Zone: {row.get_zone_display()}', f'Party size: {row.guests}']
        url = reverse('admin:bookings_reservationrequest_change', args=[row.pk])
    return f'{title}: {row.reference}', '\n'.join([*body, f'Staff detail: {settings.SITE_BASE_URL}{url}'])


def process_pending(limit=100):
    now = timezone.now()
    queue_reminders(now)
    ids = list(Notification.objects.filter(status='pending', next_attempt_at__lte=now,
               attempts__lt=settings.NOTIFICATION_MAX_ATTEMPTS).order_by('next_attempt_at', 'pk').values_list('pk', flat=True)[:limit])
    processed = 0
    for pk in ids:
        # Atomic compare-and-set: only one overlapping worker can claim this job.
        if not Notification.objects.filter(pk=pk, status='pending', next_attempt_at__lte=now).update(
                status='processing', attempts=F('attempts')+1, claimed_at=timezone.now()):
            continue
        job = Notification.objects.select_related('order', 'reservation').get(pk=pk)
        if not eligible(job, timezone.now()):
            Notification.objects.filter(pk=pk).update(status='skipped')
            continue
        try:
            if not settings.STAFF_NOTIFICATION_RECIPIENTS:
                raise ValueError('STAFF_NOTIFICATION_RECIPIENTS is empty')
            subject, body = content(job)
            sent = send_mail(subject, body, settings.DEFAULT_FROM_EMAIL,
                             settings.STAFF_NOTIFICATION_RECIPIENTS, fail_silently=False)
            if sent != 1:
                raise RuntimeError('Email backend did not confirm delivery')
        except Exception as exc:
            Notification.objects.filter(pk=pk).update(
                status='failed' if job.attempts >= settings.NOTIFICATION_MAX_ATTEMPTS else 'pending',
                last_error=str(exc)[:2000], next_attempt_at=timezone.now()+timedelta(
                    seconds=settings.NOTIFICATION_RETRY_SECONDS * 2**(job.attempts-1)))
        else:
            Notification.objects.filter(pk=pk).update(status='sent', sent_at=timezone.now(), last_error='')
        processed += 1
    return processed


def retry_notifications(queryset, *, recover_processing=False):
    """Explicit staff retry. In-flight claims require stopped-worker confirmation."""
    states = ['failed', 'processing'] if recover_processing else ['failed']
    return queryset.filter(status__in=states).update(
        status='pending', attempts=0, next_attempt_at=timezone.now(), claimed_at=None)
