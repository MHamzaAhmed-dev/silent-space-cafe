from django.core import signing
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from notifications.services import enqueue
from .availability import active_zone_choices, slot_error
from .forms import ReservationForm, availability_result
from .models import ReservationRequest, ZoneCapacity
from .submissions import new_submission_token, submission_key


@never_cache
@require_http_methods(['GET', 'HEAD', 'POST'])
def request_seat(request):
    zone = request.GET.get('zone', '')
    initial = {'zone': zone} if zone in dict(active_zone_choices()) else {}
    availability_form = None
    if request.method == 'POST' and request.POST.get('action') == 'check_availability':
        availability_form, _, _ = availability_result(request.POST)
        initial.update({key: request.POST.get(key, '') for key in [*ReservationForm.Meta.fields, 'submission_token']})
        if not initial['submission_token']:
            initial['submission_token'] = new_submission_token(request)
        form = ReservationForm(initial=initial)
        for name in availability_form.errors:
            if name in form.fields:
                form.fields[name].widget.attrs.update({'aria-invalid': 'true', 'aria-describedby': f'id_{name}_error'})
    elif request.method == 'POST':
        form = ReservationForm(request.POST)
        try:
            key = submission_key(request)
        except (signing.BadSignature, KeyError, TypeError, ValueError):
            data = request.POST.copy()
            data['submission_token'] = new_submission_token(request)
            form = ReservationForm(data)
            form.is_valid()
            form.add_error(None, 'This booking form expired or changed browser sessions. Your details are kept; check them and submit again.')
        else:
            existing = ReservationRequest.objects.filter(submission_key=key).first()
            if existing:
                return redirect('bookings:status', reference=existing.reference)
            if form.is_valid():
                with transaction.atomic():
                    # Use the same zone lock as approval, then recheck current availability.
                    ZoneCapacity.objects.filter(zone=form.cleaned_data['zone']).update(seats=F('seats'))
                    existing = ReservationRequest.objects.filter(submission_key=key).first()
                    if existing:
                        return redirect('bookings:status', reference=existing.reference)
                    error = slot_error(**{name: form.cleaned_data[name] for name in ('date', 'time', 'guests', 'zone')})
                    if error:
                        form.add_error(*error)
                    else:
                        reservation, created = ReservationRequest.objects.get_or_create(
                            submission_key=key,
                            defaults={name: form.cleaned_data[name] for name in ReservationForm.Meta.fields},
                        )
                        if created:
                            enqueue('new_reservation', reservation=reservation)
                        return redirect('bookings:status', reference=reservation.reference)
    else:
        initial['submission_token'] = new_submission_token(request)
        form = ReservationForm(initial=initial)
    return render(request, 'core/booking.html', {
        'page': 'booking', 'reservation_form': form, 'availability_form': availability_form,
    })


@never_cache
@require_safe
def availability(request):
    form, times, message = availability_result(request.GET)
    errors = {name: list(items) for name, items in form.errors.items()}
    if errors:
        message = ' '.join(error for items in errors.values() for error in items)
    return JsonResponse({
        'times': [{'value': value.strftime('%H:%M'), 'label': value.strftime('%H:%M')+' PKT'} for value in times],
        'message': message, 'errors': errors,
    }, status=400 if errors else 200)


@never_cache
@require_safe
def reservation_status(request, reference):
    reservation = get_object_or_404(ReservationRequest, reference=reference)
    return render(request, 'core/request_status.html', {'reservation': reservation})
