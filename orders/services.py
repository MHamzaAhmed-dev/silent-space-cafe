"""Order transitions shared by Admin and the staff dashboard."""
from .models import DineInOrder
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.db.models import Q

TRANSITIONS = {
    'start_preparing': (DineInOrder.Status.RECEIVED, DineInOrder.Status.PREPARING, 'Start preparing'),
    'complete_orders': (DineInOrder.Status.PREPARING, DineInOrder.Status.COMPLETED, 'Mark completed'),
    'out_for_delivery': ('preparing', 'out_delivery', 'Mark out for delivery'),
    'ready_for_pickup': ('preparing', 'ready_pickup', 'Mark ready for pickup'),
    'finish_delivery': ('out_delivery', 'completed', 'Mark delivered'),
    'finish_pickup': ('ready_pickup', 'completed', 'Mark collected'),
}


def transition_orders(queryset, action):
    source, target, _ = TRANSITIONS[action]
    rows = queryset.filter(status=source)
    if action in ('out_for_delivery', 'finish_delivery'):
        rows = rows.filter(fulfilment='delivery')
    elif action in ('ready_for_pickup', 'finish_pickup'):
        rows = rows.filter(fulfilment='pickup')
    if action != 'start_preparing':
        rows = rows.exclude(Q(fulfilment__in=['delivery', 'pickup'],
            payment_method__in=['jazzcash', 'easypaisa']) & ~Q(payment_status='paid'))
    return rows.update(status=target)


def permitted_actions(order):
    return [(key, label) for key, (source, target, label) in TRANSITIONS.items()
            if order.status == source
            and (key not in ('out_for_delivery', 'finish_delivery') or order.fulfilment == 'delivery')
            and (key not in ('ready_for_pickup', 'finish_pickup') or order.fulfilment == 'pickup')
            and (key == 'start_preparing' or order.fulfilment == 'dine_in'
                 or order.payment_method not in ('jazzcash', 'easypaisa') or order.payment_status == 'paid')]


def verify_payments(queryset, user, decision='approve'):
    if not user.is_active or not user.is_staff or not user.has_perm('orders.verify_payment'):
        raise PermissionDenied
    if decision not in ('approve', 'reject'):
        raise ValueError('Invalid payment decision')
    return queryset.filter(payment_method__in=['jazzcash', 'easypaisa'], payment_status='pending').exclude(
        transaction_reference='').update(payment_status='paid' if decision == 'approve' else 'rejected',
            verified_by=user, verified_at=timezone.now())
