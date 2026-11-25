from django.contrib import admin
from django import forms
from django.contrib.admin.helpers import ActionForm
from .services import retry_notifications
from .models import Notification


class RecoveryActionForm(ActionForm):
    workers_stopped = forms.BooleanField(required=False, label='All workers stopped: also recover interrupted Processing jobs')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('event_key', 'status', 'attempts', 'next_attempt_at', 'claimed_at', 'sent_at')
    list_filter = ('status', 'kind')
    search_fields = ('event_key', 'last_error')
    readonly_fields = tuple(f.name for f in Notification._meta.fields)

    action_form = RecoveryActionForm
    actions = ['retry_reviewed']

    @admin.action(description='Retry reviewed failed/interrupted deliveries (may duplicate email)', permissions=['change'])
    def retry_reviewed(self, request, queryset):
        count = retry_notifications(queryset, recover_processing=request.POST.get('workers_stopped') == 'on')
        self.message_user(request, f'Requeued {count} reviewed delivery(s). Stop workers before recovering processing jobs.')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
