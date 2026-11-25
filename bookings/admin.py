from django import forms
from django.contrib.admin.helpers import ActionForm
from django.contrib import admin, messages

from .services import transition_reservations
from .models import BookingHours, ReservationRequest, ZoneCapacity


class ReservationReviewForm(forms.ModelForm):
    change_status = forms.ChoiceField(label='Change status', required=False, choices=[
        ('', 'Leave pending'), ('approve_requests', 'Approve'), ('reject_requests', 'Reject'),
    ])

    class Meta:
        model = ReservationRequest
        fields = ()


class CancellationActionForm(ActionForm):
    cancellation_reason = forms.CharField(required=False, max_length=1000, label='Internal cancellation reason')


@admin.register(ReservationRequest)
class ReservationRequestAdmin(admin.ModelAdmin):
    form = ReservationReviewForm
    list_display = ('reference', 'name', 'date', 'time', 'zone', 'guests', 'status')
    list_filter = ('status', 'zone', 'date')
    search_fields = ('name', 'email', 'phone', 'reference')
    ordering = ('-created_at',)
    readonly_fields = tuple(field.name for field in ReservationRequest._meta.fields if field.name != 'id')
    action_form = CancellationActionForm
    actions = ['approve_requests', 'reject_requests', 'cancel_reservations']

    def get_fields(self, request, obj=None):
        fields = list(self.readonly_fields)
        if obj and (obj.status == 'pending' or request.POST.get('change_status')) and self.has_change_permission(request, obj):
            fields.append('change_status')
        return fields

    def save_model(self, request, obj, form, change):
        action = form.cleaned_data.get('change_status')
        if action and self.has_change_permission(request, obj):
            self.apply_transition(request, ReservationRequest.objects.filter(pk=obj.pk), action)
        # The transition service owns writes, including the pending-state guard.
        obj.refresh_from_db()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='Cancel selected approved reservations', permissions=['change'])
    def cancel_reservations(self, request, queryset):
        self.apply_transition(request, queryset, 'cancel_reservations')

    def has_add_permission(self, request):
        return False

    @admin.action(description='Approve selected pending requests', permissions=['change'])
    def approve_requests(self, request, queryset):
        self.apply_transition(request, queryset, 'approve_requests')

    @admin.action(description='Reject selected pending requests', permissions=['change'])
    def reject_requests(self, request, queryset):
        self.apply_transition(request, queryset, 'reject_requests')

    def apply_transition(self, request, queryset, action):
        result = transition_reservations(queryset, action, request.POST.get('cancellation_reason', ''))
        for error in result.errors:
            self.message_user(request, error, messages.ERROR)
        if not result.count and not result.errors:
            self.message_user(request, 'Reservation already changed. Review its current status.', messages.WARNING)
        self.message_user(request, f'Updated {result.count} reservation(s).')


admin.site.register(BookingHours)
admin.site.register(ZoneCapacity)
