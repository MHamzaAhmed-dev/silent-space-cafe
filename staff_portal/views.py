from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_safe

from bookings.models import ReservationRequest
from bookings.services import permitted_actions as reservation_actions, transition_reservations
from menu.models import MenuItem
from notifications.models import Notification
from notifications.services import retry_notifications
from orders.models import DineInOrder
from orders.services import TRANSITIONS, permitted_actions as order_actions, transition_orders, verify_payments
from .access import can_view, staff_access
from .forms import ReservationActionForm, StaffAuthenticationForm


class StaffLoginView(LoginView):
    template_name = 'staff/login.html'
    authentication_form = StaffAuthenticationForm
    next_page = 'staff:overview'


class StaffLogoutView(LogoutView):
    next_page = 'staff:login'


def page_context(request, title, section, **extra):
    access = {key: can_view(request.user, model) for key, model in {
        'orders': 'orders.dineinorder', 'reservations': 'bookings.reservationrequest',
        'notifications': 'notifications.notification', 'menu': 'menu.menuitem',
        'locations': 'orders.servicelocation'}.items()}
    return dict(title=title, section=section, access=access, **extra)


def paginate(request, rows):
    page = Paginator(rows, 25).get_page(request.GET.get('page'))
    params = request.GET.copy()
    for key in ['page', 'fragment']:
        params.pop(key, None)
    return {'page_obj': page, 'page_query': params.urlencode()}


def upcoming(rows, now):
    local = timezone.localtime(now)
    return rows.filter(Q(date__gt=local.date()) | Q(date=local.date(), time__gte=local.time().replace(tzinfo=None)))


@staff_access()
@require_safe
def overview(request):
    now = timezone.now()
    today = timezone.localdate(now)
    context = page_context(request, 'Overview', 'overview', now=now)
    if can_view(request.user, 'orders.dineinorder'):
        orders = DineInOrder.objects.all()
        context.update(received_count=orders.filter(status='received').count(),
                       preparing_count=orders.filter(status='preparing').count(),
                       urgent_orders=orders.filter(status='received').order_by('created_at', 'pk')[:5])
    if can_view(request.user, 'bookings.reservationrequest'):
        bookings = ReservationRequest.objects.all()
        arrivals = upcoming(bookings.filter(status='approved', date=today), now).order_by('date', 'time', 'pk')
        context.update(today_count=arrivals.count(), pending_count=bookings.filter(status='pending').count(),
                       next_reservation=upcoming(bookings.filter(status='approved'), now).order_by('date', 'time', 'pk').first(),
                       arrivals=arrivals[:5])
    if can_view(request.user, 'notifications.notification'):
        context['failed_count'] = Notification.objects.filter(status='failed').count()
    return render(request, 'staff/overview.html', context)


@staff_access('orders.dineinorder')
@require_safe
def orders(request):
    state = request.GET.get('status', 'live')
    if state not in ['live', 'all', *DineInOrder.Status.values]:
        return HttpResponseBadRequest('Invalid order status.')
    rows = DineInOrder.objects.all()
    fulfilment = request.GET.get('fulfilment', '')
    payment = request.GET.get('payment', '')
    if fulfilment and fulfilment not in DineInOrder.Fulfilment.values:
        return HttpResponseBadRequest('Invalid fulfilment type.')
    if fulfilment:
        rows = rows.filter(fulfilment=fulfilment)
    if payment == 'pending':
        rows = rows.filter(payment_status='pending')
    elif payment:
        return HttpResponseBadRequest('Invalid payment filter.')
    if state == 'live':
        rows = rows.exclude(status='completed')
    elif state != 'all':
        rows = rows.filter(status=state)
    query = request.GET.get('q', '').strip()[:160]
    if query:
        rows = rows.filter(Q(reference__icontains=query) | Q(location_label__icontains=query))
    rows = rows.annotate(urgency=Case(When(status='received', then=Value(0)),
        When(status='preparing', then=Value(1)), default=Value(2), output_field=IntegerField())).order_by('urgency', 'created_at', 'pk')
    context = page_context(request, 'Orders', 'orders', status=state, q=query, fulfilment=fulfilment,
        payment=payment, now=timezone.now(), **paginate(request, rows))
    template = 'staff/partials/order_queue.html' if request.GET.get('fragment') == '1' else 'staff/orders.html'
    return render(request, template, context)


@staff_access('orders.dineinorder')
@require_safe
def order_detail(request, pk):
    order = get_object_or_404(DineInOrder.objects.prefetch_related('lines'), pk=pk)
    return render(request, 'staff/order_detail.html', page_context(request, 'Order detail', 'orders',
        order=order, actions=order_actions(order)))


@staff_access('orders.dineinorder', change=True)
@require_POST
def order_action(request, pk):
    get_object_or_404(DineInOrder, pk=pk)
    action = request.POST.get('action')
    if action not in TRANSITIONS:
        return HttpResponseBadRequest('Invalid order action.')
    count = transition_orders(DineInOrder.objects.filter(pk=pk), action)
    messages.info(request, 'Order updated.' if count else 'Order already changed or payment approval is required. Review its current status.')
    return redirect('staff:order_detail', pk=pk)


@staff_access('orders.dineinorder')
@require_POST
def payment_verify(request, pk):
    get_object_or_404(DineInOrder, pk=pk)
    if not request.user.has_perm('orders.verify_payment'):
        raise PermissionDenied
    decision = request.POST.get('decision', 'approve')
    if decision not in ('leave_pending', 'approve', 'reject'):
        return HttpResponseBadRequest('Invalid payment decision.')
    if decision == 'leave_pending':
        messages.info(request, 'No payment change saved. Review the current status below.')
        return redirect('staff:order_detail', pk=pk)
    count = verify_payments(DineInOrder.objects.filter(pk=pk), request.user, decision)
    messages.info(request, 'Payment decision saved.' if count else 'Payment already reviewed or no manual reference submitted.')
    return redirect('staff:order_detail', pk=pk)


@staff_access('bookings.reservationrequest')
@require_safe
def reservations(request):
    view = request.GET.get('view', 'today')
    rows = ReservationRequest.objects.all()
    if view == 'today':
        rows = rows.filter(date=timezone.localdate())
    elif view == 'upcoming':
        rows = upcoming(rows.filter(status='approved'), timezone.now())
    elif view in ['pending', 'cancelled']:
        rows = rows.filter(status=view)
    elif view != 'all':
        return HttpResponseBadRequest('Invalid reservation view.')
    day = request.GET.get('day', '')
    if day == 'today':
        rows = rows.filter(date=timezone.localdate())
    query = request.GET.get('q', '').strip()[:160]
    if query:
        rows = rows.filter(Q(reference__icontains=query) | Q(name__icontains=query))
    rows = rows.order_by('date', 'time', 'created_at', 'pk')
    return render(request, 'staff/reservations.html', page_context(request, 'Reservations', 'reservations',
        view=view, day=day, q=query, **paginate(request, rows)))


@staff_access('bookings.reservationrequest')
@require_safe
def reservation_detail(request, pk):
    row = get_object_or_404(ReservationRequest, pk=pk)
    return render(request, 'staff/reservation_detail.html', page_context(request, 'Reservation detail', 'reservations',
        reservation=row, actions=reservation_actions(row), action_form=ReservationActionForm()))


@staff_access('bookings.reservationrequest', change=True)
@require_POST
def reservation_action(request, pk):
    row = get_object_or_404(ReservationRequest, pk=pk)
    form = ReservationActionForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest('Invalid action or cancellation reason (maximum 1000 characters).')
    if form.cleaned_data['action'] == 'leave_pending':
        messages.info(request, 'Reservation left pending.' if row.status == 'pending' else 'Reservation already changed. Review its current status.')
        return redirect('staff:reservation_detail', pk=pk)
    result = transition_reservations(ReservationRequest.objects.filter(pk=pk),
        form.cleaned_data['action'], form.cleaned_data['reason'])
    for error in result.errors:
        messages.error(request, error)
    if not result.errors:
        messages.info(request, 'Reservation updated.' if result.count else 'Reservation already changed. Review its current status.')
    return redirect('staff:reservation_detail', pk=pk)


@staff_access()
@require_safe
def catalogue(request):
    if not any(can_view(request.user, model) for model in ['menu.menuitem', 'orders.servicelocation']):
        raise PermissionDenied
    context = page_context(request, 'Menu & QR locations', 'catalogue')
    if can_view(request.user, 'menu.menuitem'):
        rows = MenuItem.objects.all()
        state = request.GET.get('status', 'all')
        if state not in ['all', 'active', 'inactive']:
            return HttpResponseBadRequest('Invalid menu status.')
        if state != 'all':
            rows = rows.filter(active=state == 'active')
        query = request.GET.get('q', '').strip()[:160]
        if query:
            rows = rows.filter(Q(name__icontains=query) | Q(slug__icontains=query))
        context.update(paginate(request, rows), status=state, q=query)
    return render(request, 'staff/catalogue.html', context)


@staff_access('notifications.notification')
@require_safe
def notifications(request):
    state = request.GET.get('status', 'all')
    if state not in ['all', 'failed', 'pending', 'processing', 'sent', 'skipped']:
        return HttpResponseBadRequest('Invalid notification status.')
    rows = Notification.objects.select_related('order', 'reservation')
    if state != 'all':
        rows = rows.filter(status=state)
    rows = rows.annotate(urgency=Case(When(status='failed', then=Value(0)),
        When(status='processing', then=Value(1)), default=Value(2), output_field=IntegerField())).order_by('urgency', '-created_at', '-pk')
    return render(request, 'staff/notifications.html', page_context(request, 'Notifications', 'notifications',
        status=state, **paginate(request, rows)))


@staff_access('notifications.notification', change=True)
@require_POST
def notification_retry(request, pk):
    get_object_or_404(Notification, pk=pk)
    count = retry_notifications(Notification.objects.filter(pk=pk))
    messages.info(request, 'Notification queued for retry.' if count else 'Only failed notifications can be retried here. No changes made.')
    return redirect('staff:notifications')
