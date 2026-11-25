"""Private receipt actions and Stripe-hosted checkout. Never accept card details."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError
from django.conf import settings
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .forms import TransactionReferenceForm, gateway_ready
from .models import DineInOrder, PaymentEvent


@require_POST
def transfer_reference(request, reference):
    order = get_object_or_404(DineInOrder, reference=reference)
    form = TransactionReferenceForm(request.POST)
    if not form.is_valid():
        return render(request, 'orders/receipt.html', {'order': order, 'payment_form': form}, status=400)
    # A private receipt may submit once. Replays cannot overwrite a reviewed reference.
    DineInOrder.objects.filter(pk=order.pk, payment_method__in=['jazzcash', 'easypaisa'],
        payment_status='unpaid', transaction_reference='').update(
            transaction_reference=form.cleaned_data['transaction_reference'], payment_status='pending')
    return redirect('orders:receipt', reference=reference)


@require_POST
def hosted_checkout(request, reference):
    order = get_object_or_404(DineInOrder, reference=reference, payment_method='card')
    if order.payment_status == 'paid' or not gateway_ready():
        return redirect('orders:receipt', reference=reference)
    # Stripe idempotency key makes concurrent/repeated network attempts create one session.
    url = settings.SITE_BASE_URL.rstrip('/') + reverse('orders:receipt', args=[order.reference])
    fields = {'mode': 'payment', 'payment_method_types[0]': 'card', 'success_url': url, 'cancel_url': url,
        'client_reference_id': str(order.reference), 'metadata[order_reference]': str(order.reference),
        'line_items[0][price_data][currency]': 'pkr',
        'line_items[0][price_data][product_data][name]': f'Silent Space order {order.reference}',
        'line_items[0][price_data][unit_amount]': int(order.total * 100), 'line_items[0][quantity]': 1}
    try:
        if order.gateway_session:
            req = Request('https://api.stripe.com/v1/checkout/sessions/' + order.gateway_session,
                headers={'Authorization': 'Bearer ' + settings.STRIPE_SECRET_KEY})
        else:
            req = Request('https://api.stripe.com/v1/checkout/sessions', data=urlencode(fields).encode(),
                headers={'Authorization': 'Bearer ' + settings.STRIPE_SECRET_KEY,
                         'Idempotency-Key': 'order-' + str(order.reference), 'Stripe-Version': '2025-02-24.acacia'})
        with urlopen(req, timeout=20) as response:
            session = json.load(response)
        hosted_url = session.get('url', '')
        if urlparse(hosted_url).scheme != 'https' or urlparse(hosted_url).hostname != 'checkout.stripe.com':
            raise ValueError('No active hosted session')
        DineInOrder.objects.filter(pk=order.pk).update(gateway_session=session['id'], gateway_url=hosted_url)
    except (URLError, ValueError, KeyError, TimeoutError):
        messages.error(request, 'Card checkout is unavailable. Your order is saved; contact the cafe with your reference.')
        return redirect('orders:receipt', reference=reference)
    return redirect(hosted_url)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    # This endpoint alone is CSRF-exempt; authenticity comes from signed raw bytes.
    if not gateway_ready():
        return HttpResponse(status=503)
    raw = request.body
    try:
        header = request.headers.get('Stripe-Signature', '')
        values = [part.split('=', 1) for part in header.split(',')]
        timestamp = next(value for key, value in values if key == 't')
        if abs(time.time() - int(timestamp)) > 300:
            raise ValueError('Expired signature')
        digest = hmac.new(settings.STRIPE_WEBHOOK_SECRET.encode(), timestamp.encode()+b'.'+raw, hashlib.sha256).hexdigest()
        if not any(key == 'v1' and hmac.compare_digest(value, digest) for key, value in values):
            raise ValueError('Bad signature')
        event = json.loads(raw)
        if event['type'] not in ['checkout.session.completed', 'checkout.session.async_payment_succeeded',
                                  'checkout.session.async_payment_failed', 'checkout.session.expired']:
            return HttpResponse(status=200)
        session = event['data']['object']
        reference = session['client_reference_id']
        with transaction.atomic():
            order = DineInOrder.objects.select_for_update().get(reference=reference, payment_method='card')
            if (session.get('metadata', {}).get('order_reference') != str(order.reference)
                    or session.get('currency') != 'pkr' or session.get('amount_total') != int(order.total * 100)
                    or not order.gateway_session or session['id'] != order.gateway_session
                    or bool(event.get('livemode')) != settings.STRIPE_SECRET_KEY.startswith('sk_live_')):
                raise ValueError('Payment does not match saved order')
            _, fresh = PaymentEvent.objects.get_or_create(event_id=event['id'], defaults={'order': order})
            if fresh and session.get('payment_status') == 'paid' and event['type'] in [
                    'checkout.session.completed', 'checkout.session.async_payment_succeeded']:
                DineInOrder.objects.filter(pk=order.pk).exclude(payment_status='paid').update(
                    payment_status='paid', verified_at=timezone.now())
    except (ValueError, KeyError, TypeError, StopIteration, ValidationError, DineInOrder.DoesNotExist):
        return HttpResponseBadRequest('Invalid payment notification')
    return HttpResponse(status=200)
