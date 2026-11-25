from django import forms
from django.contrib.auth.forms import AuthenticationForm
from bookings.services import TRANSITIONS


class StaffAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise forms.ValidationError('A staff account is required.', code='not_staff')


class ReservationActionForm(forms.Form):
    action = forms.ChoiceField(choices=[('leave_pending', 'Leave pending')] + [(key, label) for key, (_, _, label) in TRANSITIONS.items()])
    reason = forms.CharField(required=False, max_length=1000, strip=True)
