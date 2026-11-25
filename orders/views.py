from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST, require_safe
from menu.models import MenuItem
from .bag import MAX_QUANTITY, SESSION_KEY, resolve_bag


@require_safe
def bag_detail(request):
    from .customer_checkout import bag_page
    return bag_page(request)


@require_POST
def bag_change(request, pk, action):
    if action not in {'add', 'increase', 'decrease', 'remove'}:
        return redirect('orders:bag')
    resolve_bag(request)
    quantities = request.session.get(SESSION_KEY, {}).copy()
    key = str(pk)
    item = MenuItem.objects.filter(pk=pk, active=True).first()
    if action == 'remove':
        quantities.pop(key, None)
    elif item is None:
        quantities.pop(key, None)
        messages.warning(request, 'This item is no longer available.')
    elif action in {'add', 'increase'}:
        # Ignore client-supplied prices, names, totals and quantities.
        if action == 'add' or key in quantities:
            old = quantities.get(key, 0)
            quantities[key] = min(old + 1, MAX_QUANTITY)
            if old >= MAX_QUANTITY:
                messages.info(request, f'Maximum quantity is {MAX_QUANTITY} per item.')
            elif action == 'add':
                messages.success(request, f'{item.name} added to your bag.')
    elif key in quantities:
        quantities[key] -= 1
        if quantities[key] <= 0:
            quantities.pop(key)
    request.session.pop('checkout_key', None)
    request.session[SESSION_KEY] = quantities
    return redirect('orders:bag')
