from django import forms
from django.core.validators import RegexValidator

from .availability import active_zone_choices, available_slots, selection_error, slot_error
from .models import ReservationRequest

GUEST_CHOICES = [(n, f'{n} guest' + ('s' if n != 1 else '')) for n in range(1, 7)]


class AvailabilityForm(forms.Form):
    date = forms.DateField()
    guests = forms.TypedChoiceField(choices=GUEST_CHOICES, coerce=int)
    zone = forms.ChoiceField(choices=ReservationRequest.Zone.choices, error_messages={
        'invalid_choice': 'This seating zone is not available. Choose another space.',
    })

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['zone'].choices = active_zone_choices()

    def clean(self):
        data = super().clean()
        if all(key in data for key in ('date', 'guests', 'zone')):
            error = selection_error(**{key: data[key] for key in ('date', 'guests', 'zone')})
            if error:
                self.add_error(*error)
        return data


def availability_result(data):
    selection = AvailabilityForm(data)
    if not selection.is_valid():
        return selection, [], 'Choose a valid date, party size and seating zone to see available times.'
    times = available_slots(**selection.cleaned_data)
    message = ('Choose an available time. All times are Pakistan Standard Time (PKT).'
               if times else 'No available times for this selection. Try another date, party size or seating zone.')
    return selection, times, message


class ReservationForm(forms.ModelForm):
    submission_token = forms.CharField(required=False, widget=forms.HiddenInput())
    guests = forms.TypedChoiceField(label='Guests', choices=GUEST_CHOICES, coerce=int, initial=1)
    zone = forms.ChoiceField(label='Seating zone', choices=[('', 'Choose a space')],
        error_messages={'invalid_choice': 'This seating zone is not available. Choose another space.'})
    time = forms.TimeField(label='Available time', input_formats=['%H:%M', '%H:%M:%S'], widget=forms.Select())
    email = forms.EmailField(label='Email (optional)', max_length=254, required=False,
        widget=forms.EmailInput(attrs={'autocomplete': 'email'}))
    phone = forms.CharField(label='Phone number', max_length=30,
        validators=[RegexValidator(r'^\+?[0-9 ()-]{7,30}$'), RegexValidator(r'(?:\d\D*){7}')],
        widget=forms.TextInput(attrs={'type': 'tel', 'autocomplete': 'tel'}))

    class Meta:
        model = ReservationRequest
        fields = ['date', 'guests', 'zone', 'time', 'name', 'phone', 'email', 'special_request']
        labels = {'name': 'Your name', 'special_request': 'Special request (optional)'}
        widgets = {
            'name': forms.TextInput(attrs={'autocomplete': 'name'}),
            'date': forms.DateInput(attrs={'type': 'date'}),
            'special_request': forms.Textarea(attrs={'rows': 4, 'maxlength': 1000}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['zone'].choices = [('', 'Choose a space'), *active_zone_choices()]
        values = self.data if self.is_bound else self.initial
        selection, times, message = availability_result({
            'date': values.get('date', ''), 'guests': values.get('guests', 1), 'zone': values.get('zone', ''),
        })
        self.available_times = times
        self.availability_message = message
        choices = [('', 'Choose a time'), *[(value.strftime('%H:%M'), value.strftime('%H:%M')+' PKT') for value in times]]
        # Keep a stale selected time visible after a rejected submission, while offering alternatives.
        selected = values.get('time', '')
        try:
            parsed = forms.TimeField().clean(selected) if selected else None
        except forms.ValidationError:
            parsed = None
        if parsed and parsed not in times:
            choices.append((parsed.strftime('%H:%M'), parsed.strftime('%H:%M')+' PKT (unavailable - choose another)'))
        self.fields['time'].widget.choices = choices
        self.order_fields([*self.Meta.fields, 'submission_token'])

    def clean(self):
        data = super().clean()
        if all(key in data for key in ('date', 'guests', 'zone')):
            error = selection_error(**{key: data[key] for key in ('date', 'guests', 'zone')})
            if error:
                self.add_error(*error)
                return data
        keys = ('date', 'time', 'guests', 'zone')
        if all(key in data for key in keys):
            error = slot_error(**{key: data[key] for key in keys})
            if error:
                self.add_error(*error)
        return data
