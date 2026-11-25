from django import forms
from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html

from .services import transition_orders, verify_payments

from .models import DineInOrder, OrderLine, ServiceLocation, DeliveryArea, PaymentMethod, PaymentEvent


@admin.register(DeliveryArea)
class DeliveryAreaAdmin(admin.ModelAdmin):
    list_display = ('name', 'fee', 'enabled')
    list_editable = ('fee', 'enabled')
    search_fields = ('name',)
    list_filter = ('enabled',)


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ('code', 'enabled', 'delivery', 'pickup', 'dine_in', 'receiver', 'display_order')
    list_filter = ('enabled', 'delivery', 'pickup', 'dine_in')
    fields = ('code', 'enabled', 'delivery', 'pickup', 'dine_in', 'receiver', 'instructions', 'display_order')

    def get_readonly_fields(self, request, obj=None):
        return ('code',) if obj else ()


@admin.register(ServiceLocation)
class ServiceLocationAdmin(admin.ModelAdmin):
    list_display = ('label', 'enabled', 'scan_link')
    list_editable = ('enabled',)
    readonly_fields = ('scan_link',)

    @admin.display(description='QR menu link')
    def scan_link(self, obj):
        if not obj.pk:
            return '-'
        url = reverse('orders:scan', args=[obj.token])
        return format_html('<a href="{}">{}</a>', url, url)


class PaymentReviewForm(forms.ModelForm):
    change_payment_status = forms.ChoiceField(label='Change payment status', required=False,
        choices=[('', 'Leave pending'), ('approve', 'Approve payment'), ('reject', 'Reject payment')],
        help_text='Before choosing Approve payment, verify the amount and transaction reference against the receiving account.')

    class Meta:
        model = DineInOrder
        fields = ()


class OrderLineInline(admin.TabularInline):
    model = OrderLine
    fields = readonly_fields = ('name', 'unit_price', 'quantity')
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DineInOrder)
class DineInOrderAdmin(admin.ModelAdmin):
    form = PaymentReviewForm
    list_display = ('reference', 'fulfilment', 'location_label', 'status', 'payment_method', 'payment_status', 'total', 'created_at')
    list_filter = ('fulfilment', 'payment_status', 'payment_method', 'status', 'location')
    ordering = ('-created_at',)
    inlines = [OrderLineInline]
    readonly_fields = tuple(field.name for field in DineInOrder._meta.fields if field.name != 'id')
    actions = ['start_preparing', 'complete_orders', 'verify_manual_payments', 'reject_manual_payments',
               'out_for_delivery', 'ready_for_pickup', 'finish_delivery', 'finish_pickup']

    def get_fields(self, request, obj=None):
        fields = list(self.readonly_fields)
        if obj and self.has_verify_permission(request) and (obj.manual_payment_pending or request.POST.get('change_payment_status')):
            fields.append('change_payment_status')
        return fields

    def save_model(self, request, obj, form, change):
        decision = form.cleaned_data.get('change_payment_status')
        if request.POST.get('change_payment_status') and not self.has_verify_permission(request):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        if decision:
            count = verify_payments(DineInOrder.objects.filter(pk=obj.pk, fulfilment__in=['delivery', 'pickup']), request.user, decision)
            self.message_user(request, 'Payment decision saved.' if count else
                'Payment already reviewed or no eligible transfer submitted. Review the current status.',
                messages.SUCCESS if count else messages.WARNING)
        obj.refresh_from_db()

    @admin.action(description='Reject submitted manual payments', permissions=['verify'])
    def reject_manual_payments(self, request, queryset):
        count = verify_payments(queryset, request.user, 'reject')
        self.message_user(request, f'{count} manual payment(s) rejected.')

    @admin.action(description='Mark delivery orders out for delivery', permissions=['change'])
    def out_for_delivery(self, request, queryset):
        self.message_user(request, f"{transition_orders(queryset, 'out_for_delivery')} order(s) updated; transfers require approved payment.")

    @admin.action(description='Mark pickup orders ready for pickup', permissions=['change'])
    def ready_for_pickup(self, request, queryset):
        self.message_user(request, f"{transition_orders(queryset, 'ready_for_pickup')} order(s) updated; transfers require approved payment.")

    @admin.action(description='Mark dispatched orders delivered', permissions=['change'])
    def finish_delivery(self, request, queryset):
        self.message_user(request, f"{transition_orders(queryset, 'finish_delivery')} order(s) delivered.")

    @admin.action(description='Mark ready pickup orders collected', permissions=['change'])
    def finish_pickup(self, request, queryset):
        self.message_user(request, f"{transition_orders(queryset, 'finish_pickup')} order(s) collected.")

    def has_verify_permission(self, request):
        return request.user.has_perm('orders.verify_payment')

    @admin.action(description='Verify submitted manual payments', permissions=['verify'])
    def verify_manual_payments(self, request, queryset):
        count = verify_payments(queryset, request.user)
        self.message_user(request, f'{count} manual payment(s) verified.')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='Move received orders to preparing')
    def start_preparing(self, request, queryset):
        count = transition_orders(queryset, 'start_preparing')
        self.message_user(request, f'{count} order(s) moved to preparing.')

    @admin.action(description='Complete preparing orders')
    def complete_orders(self, request, queryset):
        count = transition_orders(queryset, 'complete_orders')
        self.message_user(request, f'{count} order(s) completed.')
