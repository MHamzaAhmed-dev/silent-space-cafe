from uuid import uuid4

from django.contrib import messages
from django.core import signing
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_safe
from django.views.decorators.cache import never_cache

from notifications.services import enqueue

from .bag import SESSION_KEY, current_location, resolve_bag
from .models import DineInOrder, OrderLine, ServiceLocation
from .forms import available_methods
from .customer_checkout import session_binding
from menu.models import MenuItem

QUOTE_SALT = 'dine-in-checkout'


@require_safe
def scan(request, token):
    location = ServiceLocation.objects.filter(token=token, enabled=True).first()
    if location is None:
        request.session.pop('service_location', None)
        request.session.pop('checkout_key', None)
        return render(request, 'orders/location_unavailable.html', status=404)
    if request.session.get('service_location') != location.pk:
        request.session.pop('checkout_key', None)
    request.session['service_location'] = location.pk
    return redirect('core:menu')


def snapshot(bag):
    return [[line['item'].pk, line['quantity'], str(line['item'].price)] for line in bag['lines']]


@require_http_methods(['GET', 'HEAD', 'POST'])
def checkout(request):
    if request.method == 'POST':
        if 'customer_quote' in request.POST:
            from .customer_checkout import submit_customer
            return submit_customer(request)
        return submit(request)
    location = current_location(request)
    bag = resolve_bag(request)
    if not location:
        return redirect('orders:bag')
    if not bag['lines']:
        messages.error(request, 'Scan an enabled dine-in QR and add items before checkout.')
        return redirect('orders:bag')
    key = request.session.get('checkout_key')
    if not key:
        key = request.session['checkout_key'] = str(uuid4())
    quote = signing.dumps(
        {'key': key, 'location': location.pk, 'lines': snapshot(bag), 'session': session_binding(request)},
        salt=QUOTE_SALT,
    )
    return render(request, 'orders/checkout.html', {'quote': quote, 'location': location, 'checkout_bag': bag,
        'methods': available_methods('dine_in')})


def submit(request):
    try:
        quote = signing.loads(request.POST.get('quote', ''), salt=QUOTE_SALT, max_age=3600)
    except signing.BadSignature:
        messages.error(request, 'Your checkout expired. Review your bag and try again.')
        return redirect('orders:bag')
    if quote['session'] != session_binding(request):
        return redirect('orders:bag')
    with transaction.atomic():
        # Recheck location under a write lock before recording the order.
        available = ServiceLocation.objects.filter(pk=quote['location'], enabled=True).update(enabled=F('enabled'))
        order = DineInOrder.objects.filter(submission_key=quote['key']).first()
        if order:
            return redirect('orders:receipt', reference=order.reference)
        if not available or request.session.get('service_location') != quote['location']:
            messages.error(request, 'This service location is unavailable. Scan the QR at your current seat.')
            return redirect('orders:bag')
        list(MenuItem.objects.select_for_update().filter(pk__in=[line[0] for line in quote['lines']]))
        bag = resolve_bag(request)
        if (not bag['lines'] or snapshot(bag) != quote['lines']
                or quote['key'] != request.session.get('checkout_key')):
            messages.error(request, 'Your bag or prices changed. Review your bag before ordering.')
            return redirect('orders:bag')
        location = ServiceLocation.objects.get(pk=quote['location'])
        methods = available_methods('dine_in')
        method = methods.filter(pk=request.POST.get('payment_method')).first() if str(request.POST.get('payment_method', '')).isdigit() else methods.filter(code='cash').first()
        if not method:
            messages.error(request, 'Choose an available payment method.')
            return redirect('orders:checkout')
        order = DineInOrder.objects.create(
            submission_key=quote['key'], location=location,
            location_label=location.label, total=bag['total'], payment_method=method.code,
            payment_receiver=method.receiver, payment_instructions=method.instructions,
        )
        OrderLine.objects.bulk_create([
            OrderLine(order=order, name=line['item'].name, unit_price=line['item'].price, quantity=line['quantity'])
            for line in bag['lines']
        ])
        enqueue('new_order', order=order)
    request.session.pop(SESSION_KEY, None)
    request.session.pop('checkout_key', None)
    return redirect('orders:receipt', reference=order.reference)


@never_cache
@require_safe
def receipt(request, reference):
    from django.conf import settings
    order = get_object_or_404(DineInOrder.objects.prefetch_related('lines'), reference=reference)
    from .forms import TransactionReferenceForm
    return render(request, 'orders/receipt.html', {'order': order, 'payment_form': TransactionReferenceForm(),
        'staging_mode': getattr(settings, 'STAGING_MODE', False)})
