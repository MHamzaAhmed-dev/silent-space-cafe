from decimal import Decimal
from django.contrib import messages
from menu.models import MenuItem
from .models import ServiceLocation

SESSION_KEY = 'bag'
MAX_QUANTITY = 99


def resolve_bag(request):
    """Only store IDs and quantities. Reprice and check availability on every request."""
    raw = request.session.get(SESSION_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    quantities = {}
    for key, quantity in raw.items():
        if isinstance(key, str) and key.isascii() and key.isdigit() and len(key) <= 18 and type(quantity) is int and quantity > 0:
            quantities[str(int(key))] = min(quantity, MAX_QUANTITY)
    items = MenuItem.objects.filter(pk__in=quantities, active=True)
    lines, cleaned = [], {}
    for item in items:
        quantity = quantities[str(item.pk)]
        cleaned[str(item.pk)] = quantity
        lines.append({'item': item, 'quantity': quantity, 'subtotal': item.price * quantity})
    if cleaned != request.session.get(SESSION_KEY, {}):
        request.session[SESSION_KEY] = cleaned
        messages.warning(request, 'Your bag was updated. Unavailable items or invalid quantities were removed or adjusted.')
    return {'lines': lines, 'count': sum(cleaned.values()),
            'total': sum((line['subtotal'] for line in lines), Decimal('0.00'))}


def current_location(request):
    pk = request.session.get('service_location')
    return ServiceLocation.objects.filter(pk=pk, enabled=True).first() if pk else None


def bag_context(request):
    return {'bag': resolve_bag(request), 'service_location': current_location(request)}
