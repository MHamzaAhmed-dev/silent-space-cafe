"""Bag checkout presentation and regular-customer submission; QR uses the same order ledger."""
from uuid import uuid4
from decimal import Decimal
from django.contrib import messages
from django.core import signing
from django.db import transaction
from django.db.models import F
from django.shortcuts import redirect, render
from django.utils.crypto import salted_hmac
from django.contrib.sessions.models import Session
from menu.models import MenuItem
from notifications.services import enqueue
from .bag import SESSION_KEY, current_location, resolve_bag
from .forms import CheckoutForm, available_methods
from .models import DeliveryArea, DineInOrder, OrderLine, PaymentMethod

SALT = 'customer-checkout-v1'


def session_binding(request):
    return salted_hmac(SALT, request.session.session_key or '').hexdigest()


def quote_for(request, bag):
    from .checkout import snapshot
    if not request.session.session_key:
        request.session.save()
    key = request.session.get('checkout_key') or str(uuid4())
    request.session['checkout_key'] = key
    fees = {str(a.pk): str(a.fee) for a in DeliveryArea.objects.filter(enabled=True)}
    return signing.dumps({'key': key, 'session': session_binding(request),
        'lines': snapshot(bag), 'fees': fees}, salt=SALT)


def bag_page(request, form=None, *, status=200):
    bag = resolve_bag(request)
    location = current_location(request)
    form = form or CheckoutForm(initial={'fulfilment': 'delivery'})
    kind = form.data.get('fulfilment', 'delivery') if form.is_bound else 'delivery'
    area = None
    if form.is_bound:
        area = DeliveryArea.objects.filter(pk=form.data.get('delivery_area'), enabled=True).first() if str(form.data.get('delivery_area', '')).isdigit() else None
    fee = area.fee if kind == 'delivery' and area else Decimal('0')
    areas = {str(a.pk): str(a.fee) for a in DeliveryArea.objects.filter(enabled=True)}
    methods = {kind: list(available_methods(kind).values('id', 'code')) for kind in ['delivery', 'pickup']}
    return render(request, 'orders/bag.html', {'checkout_form': form, 'customer_quote': quote_for(request, bag),
        'delivery_fee': fee, 'checkout_total': bag['total'] + fee, 'selected_kind': kind,
        'needs_area': kind == 'delivery' and area is None,
        'checkout_data': {'subtotal': str(bag['total']), 'areas': areas, 'methods': methods}}, status=status)


def submit_customer(request):
    from .checkout import snapshot
    try:
        quote = signing.loads(request.POST.get('customer_quote', ''), salt=SALT, max_age=3600)
        if quote['session'] != session_binding(request):
            raise signing.BadSignature()
    except (signing.BadSignature, KeyError, TypeError):
        messages.error(request, 'Your checkout expired. Review your bag and try again.')
        return redirect('orders:bag')
    form = CheckoutForm(request.POST)
    if request.POST.get('action') == 'refresh':
        # Server-rendered fallback: keep all entered details, update fees and methods.
        return bag_page(request, form)
    with transaction.atomic():
        # Serialize repeated submissions, including on SQLite (select_for_update is a no-op there).
        Session.objects.filter(session_key=request.session.session_key).update(expire_date=F('expire_date'))
        existing = DineInOrder.objects.filter(submission_key=quote['key']).first()
        if existing:
            return redirect('orders:receipt', reference=existing.reference)
        list(MenuItem.objects.select_for_update().filter(pk__in=[line[0] for line in quote['lines']]))
        bag = resolve_bag(request)
        if not bag['lines'] or snapshot(bag) != quote['lines'] or quote['key'] != request.session.get('checkout_key'):
            messages.error(request, 'Your bag or prices changed. Review your bag before ordering.')
            return bag_page(request, form)
        if current_location(request):
            messages.error(request, 'Use the dine-in checkout for your scanned seat.')
            return redirect('orders:bag')
        # Lock configured prices/options while validating and saving the quote.
        list(DeliveryArea.objects.select_for_update().all())
        list(PaymentMethod.objects.select_for_update().all())
        if not form.is_valid():
            return bag_page(request, form)
        data = form.cleaned_data
        area, method = data['delivery_area'], data['payment_method']
        fee = area.fee if area else Decimal('0')
        if area and quote['fees'].get(str(area.pk)) != str(fee):
            form.add_error('delivery_area', 'The delivery fee changed. Review the updated total and place your order again.')
            return bag_page(request, form)
        order = DineInOrder.objects.create(submission_key=quote['key'], fulfilment=data['fulfilment'],
            location_label=area.name if area else 'Pickup', customer_name=data['customer_name'], phone=data['phone'],
            delivery_area=area, delivery_area_name=area.name if area else '', street_address=data['street_address'],
            notes=data['notes'], delivery_fee=fee, total=bag['total']+fee, payment_method=method.code,
            payment_receiver=method.receiver, payment_instructions=method.instructions)
        OrderLine.objects.bulk_create([OrderLine(order=order, name=line['item'].name,
            unit_price=line['item'].price, quantity=line['quantity']) for line in bag['lines']])
        enqueue('new_order', order=order)
    request.session.pop(SESSION_KEY, None)
    request.session.pop('checkout_key', None)
    return redirect('orders:receipt', reference=order.reference)
