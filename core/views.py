from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_safe
from bookings.forms import ReservationForm
from bookings.submissions import new_submission_token
from menu.models import MenuItem


@require_safe
def home(request):
    catalogue = MenuItem.objects.filter(active=True)
    # Curate known favourites without copying prices, names or availability.
    active_items = list(catalogue)
    favourites = ['classic-cappuccino', 'rose-latte', 'waffle-sandwich']
    by_slug = {item.slug: item for item in active_items}
    preview = [by_slug[slug] for slug in favourites if slug in by_slug]
    preview += [item for item in active_items if item.slug not in favourites]
    return render(request, 'core/home.html', {
        'page': 'home', 'reservation_form': ReservationForm(initial={'submission_token': new_submission_token(request)}),
        'catalogue': catalogue, 'menu_preview': preview[:3],
    })


@require_safe
def content_page(request, page):
    return render(request, f'core/{page}.html', {'page': page, 'catalogue': MenuItem.objects.filter(active=True)})


@require_safe
def spaces(request):
    from .spaces import SPACE_DETAILS
    return render(request, 'core/zones.html', {'page': 'zones', 'spaces': SPACE_DETAILS})


@require_safe
def legacy_spaces(request):
    url = reverse('core:zones')
    query = request.GET.urlencode()
    return redirect(url + ('?' + query if query else ''), permanent=True)
