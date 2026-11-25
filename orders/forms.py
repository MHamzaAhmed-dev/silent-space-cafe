from django import forms
from django.conf import settings
from .models import DeliveryArea, PaymentMethod


def gateway_ready():
    if getattr(settings, 'STAGING_MODE', False):
        return False
    return bool(settings.STRIPE_SECRET_KEY and settings.STRIPE_WEBHOOK_SECRET)


def available_methods(fulfilment):
    if fulfilment not in {'delivery', 'pickup', 'dine_in'}:
        return PaymentMethod.objects.none()
    rows = PaymentMethod.objects.filter(enabled=True, **{fulfilment: True})
    excluded = ['card'] if not gateway_ready() else []
    if getattr(settings, 'STAGING_MODE', False):
        excluded.extend(['jazzcash', 'easypaisa'])
    if fulfilment != 'delivery':
        excluded.append('cod')
    if fulfilment == 'delivery':
        excluded.append('cash')
    return rows.exclude(code__in=excluded).exclude(code__in=['jazzcash', 'easypaisa'], receiver='')


class CheckoutForm(forms.Form):
    fulfilment = forms.ChoiceField(choices=[('delivery', 'Delivery'), ('pickup', 'Pickup')])
    customer_name = forms.CharField(label='Full name', max_length=120)
    phone = forms.RegexField(r'^\+?[0-9 ()-]{7,40}$', label='Phone number', max_length=40,
                            error_messages={'invalid': 'Enter a valid phone number.'})
    delivery_area = forms.ModelChoiceField(queryset=DeliveryArea.objects.none(), required=False, empty_label='Select a delivery area')
    street_address = forms.CharField(max_length=500, required=False)
    notes = forms.CharField(label='Notes (optional)', required=False, max_length=2000, widget=forms.Textarea(attrs={'rows': 3}))
    payment_method = forms.ModelChoiceField(queryset=PaymentMethod.objects.none(), widget=forms.RadioSelect(attrs={'form': 'customer-checkout'}), empty_label=None)

    def __init__(self, *args, location=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.location = location
        if location:
            self.fields['fulfilment'].choices = [('dine_in', 'Dine-in')]
            self.fields['customer_name'].required = False
            self.fields['phone'].required = False
        kind = self.data.get('fulfilment') if self.is_bound else self.initial.get('fulfilment', 'dine_in' if location else 'delivery')
        self.fields['delivery_area'].queryset = DeliveryArea.objects.filter(enabled=True)
        self.fields['payment_method'].queryset = available_methods(kind)
        for name in ['customer_name', 'phone', 'street_address']:
            self.fields[name].widget.attrs['autocomplete'] = {'customer_name': 'name', 'phone': 'tel', 'street_address': 'street-address'}[name]

    def clean(self):
        data = super().clean()
        if data.get('fulfilment') == 'delivery':
            if not data.get('delivery_area'):
                self.add_error('delivery_area', 'Choose a served delivery area.')
            if not data.get('street_address'):
                self.add_error('street_address', 'Enter your street address.')
        else:
            data['delivery_area'] = None
            data['street_address'] = ''
        return data


class TransactionReferenceForm(forms.Form):
    transaction_reference = forms.CharField(label='Transaction reference', max_length=120, min_length=3)
