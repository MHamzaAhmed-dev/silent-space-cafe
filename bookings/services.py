"""Reservation workflow shared by all staff interfaces."""
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .availability import slot_error
from .models import ReservationRequest, ZoneCapacity

TRANSITIONS = {
    'approve_requests': ('pending', 'approved', 'Approve request'),
    'reject_requests': ('pending', 'rejected', 'Reject request'),
    'cancel_reservations': ('approved', 'cancelled', 'Cancel reservation'),
}


@dataclass
class TransitionResult:
    count: int = 0
    errors: list = field(default_factory=list)


def permitted_actions(reservation):
    return [(key, label) for key, (source, target, label) in TRANSITIONS.items() if reservation.status == source]


def transition_reservations(queryset, action, reason=''):
    source, target, _ = TRANSITIONS[action]
    result = TransitionResult()
    if action != 'approve_requests':
        changes = {'status': target}
        if action == 'cancel_reservations':
            changes.update(cancelled_at=timezone.now(), cancellation_reason=reason[:1000])
        result.count = queryset.filter(status=source).update(**changes)
        return result
    for pk, zone in queryset.filter(status=source).values_list('pk', 'zone'):
        with transaction.atomic():
            # Serializes approvals in this zone, including SQLite writers.
            ZoneCapacity.objects.filter(zone=zone).update(seats=F('seats'))
            row = ReservationRequest.objects.filter(pk=pk, status=source).first()
            if row is None:
                continue
            error = slot_error(date=row.date, time=row.time, zone=row.zone, guests=row.guests)
            if error:
                result.errors.append(f'{row.reference}: {error[1]}')
                continue
            result.count += ReservationRequest.objects.filter(pk=pk, status=source).update(status=target)
    return result
