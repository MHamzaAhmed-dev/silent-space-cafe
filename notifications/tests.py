from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bookings.models import BookingHours, ReservationRequest, ZoneCapacity
from menu.models import MenuItem
from orders.models import DineInOrder, ServiceLocation
from .models import Notification
from .services import enqueue, process_pending, queue_reminders, reservation_start


@override_settings(STAFF_NOTIFICATION_RECIPIENTS=['owner@example.test'],
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   SITE_BASE_URL='https://cafe.example.test', NOTIFICATION_MAX_ATTEMPTS=2)
class PhaseThreeTests(TestCase):
    def setUp(self):
        self.day = timezone.localdate() + timedelta(days=1)
        BookingHours.objects.create(weekday=self.day.weekday(), opens=time(10), closes=time(18))
        ZoneCapacity.objects.create(zone='quiet', seats=2)
        self.staff = get_user_model().objects.create_superuser('owner', password='test')
        self.location = ServiceLocation.objects.create(label='Table 1 / Quiet Corner')
        self.item = MenuItem.objects.create(name='Coffee', slug='coffee', price='200.00')

    def booking(self, **changes):
        return ReservationRequest.objects.create(**dict(dict(name='Guest', email='guest@example.test',
            date=self.day, time=time(11), zone='quiet', guests=2), **changes))

    def order(self):
        import uuid
        return DineInOrder.objects.create(location=self.location, location_label=self.location.label,
            submission_key=uuid.uuid4(), total=200)

    def action(self, row, action, **extra):
        self.client.force_login(self.staff)
        return self.client.post(reverse('admin:bookings_reservationrequest_changelist'),
            {'action': action, '_selected_action': row.pk, **extra})

    def test_checkout_enqueues_once_and_delivers_complete_message(self):
        self.client.get(reverse('orders:scan', args=[self.location.token]))
        self.client.post(reverse('orders:bag_change', args=[self.item.pk, 'add']))
        quote = self.client.get(reverse('orders:checkout')).context['quote']
        with patch('notifications.services.send_mail', side_effect=OSError('offline')) as sender:
            a = self.client.post(reverse('orders:checkout'), {'quote': quote})
            b = self.client.post(reverse('orders:checkout'), {'quote': quote})
            sender.assert_not_called()
        self.assertEqual(a.url, b.url)
        self.assertEqual(DineInOrder.objects.count(), 1)
        self.assertEqual(Notification.objects.count(), 1)
        process_pending()
        process_pending()
        self.assertEqual(len(mail.outbox), 1)
        order = DineInOrder.objects.get()
        body = mail.outbox[0].body
        for part in [str(order.reference), 'Coffee x 1', 'PKR 200.00', self.location.label, 'PKT',
                     f'https://cafe.example.test/admin/orders/dineinorder/{order.pk}/change/']:
            self.assertIn(part, body)
        self.assertEqual(mail.outbox[0].to, ['owner@example.test'])
        self.assertEqual(self.client.get(reverse('admin:orders_dineinorder_change', args=[order.pk])).status_code, 302)

    def test_new_booking_enqueued_and_staff_link_protected(self):
        response = self.client.post(reverse('core:booking'), {'name': 'Guest', 'email': 'guest@example.test',
            'phone': '03001234567', 'date': self.day, 'time': '11:00', 'zone': 'quiet', 'guests': 2})
        self.assertEqual(response.status_code, 302)
        row = ReservationRequest.objects.get()
        self.assertEqual(row.phone, '03001234567')
        process_pending()
        self.assertIn(str(row.reference), mail.outbox[0].body)
        self.assertIn('Party size: 2', mail.outbox[0].body)
        self.assertIn('Quiet Corner', mail.outbox[0].body)
        self.assertEqual(self.client.get(reverse('admin:bookings_reservationrequest_change', args=[row.pk])).status_code, 302)

    def test_cancellation_lifecycle_capacity_and_repetition(self):
        a, b = self.booking(), self.booking()
        self.action(a, 'approve_requests')
        self.action(b, 'approve_requests')
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual(a.status, 'approved'); self.assertEqual(b.status, 'pending')
        self.action(a, 'cancel_reservations', cancellation_reason='Owner request')
        a.refresh_from_db()
        stamp, ref = a.cancelled_at, a.reference
        self.assertEqual(a.status, 'cancelled')
        self.assertIsNotNone(stamp)
        self.action(a, 'cancel_reservations', cancellation_reason='Changed')
        a.refresh_from_db()
        self.assertEqual((a.cancelled_at, a.reference, a.cancellation_reason), (stamp, ref, 'Owner request'))
        self.action(b, 'approve_requests'); b.refresh_from_db()
        self.assertEqual(b.status, 'approved')
        page = self.client.get(reverse('bookings:status', args=[ref]))
        self.assertContains(page, 'Cancelled'); self.assertNotContains(page, 'Owner request')

    def test_cancel_requires_change_permission(self):
        row = self.booking(status='approved')
        user = get_user_model().objects.create_user('viewer', is_staff=True)
        from django.contrib.auth.models import Permission
        user.user_permissions.add(Permission.objects.get(codename='view_reservationrequest'))
        self.client.force_login(user)
        self.client.post(reverse('admin:bookings_reservationrequest_changelist'),
            {'action': 'cancel_reservations', '_selected_action': row.pk})
        row.refresh_from_db(); self.assertEqual(row.status, 'approved')

    def test_failure_retry_exhaustion_and_saved_order(self):
        row = self.order(); job = enqueue('new_order', order=row)
        with patch('notifications.services.send_mail', side_effect=OSError('SMTP unavailable')):
            process_pending()
            job.refresh_from_db()
            self.assertEqual((job.status, job.attempts), ('pending', 1))
            self.assertIn('SMTP unavailable', job.last_error)
            process_pending(); job.refresh_from_db(); self.assertEqual(job.attempts, 1)
            Notification.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now()-timedelta(seconds=1))
            process_pending(); process_pending()
        job.refresh_from_db()
        self.assertEqual((job.status, job.attempts), ('failed', 2))
        self.assertTrue(DineInOrder.objects.filter(pk=row.pk).exists())

    def test_retry_success(self):
        job = enqueue('new_order', order=self.order())
        with patch('notifications.services.send_mail', side_effect=OSError('offline')):
            process_pending()
        Notification.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now()-timedelta(seconds=1))
        process_pending(); job.refresh_from_db()
        self.assertEqual((job.status, job.attempts), ('sent', 2))
        self.assertEqual(len(mail.outbox), 1)

    def test_due_and_skipped_reminders(self):
        now = timezone.now()
        row = self.booking(status='approved')
        due = reservation_start(row)-timedelta(minutes=60)
        queue_reminders(due); queue_reminders(due)
        self.assertEqual(Notification.objects.filter(kind='reservation_reminder').count(), 1)
        ReservationRequest.objects.filter(pk=row.pk).update(status='cancelled')
        old = self.order(); fresh = self.order(); acted = self.order()
        DineInOrder.objects.filter(pk__in=[old.pk, acted.pk]).update(created_at=now-timedelta(minutes=11))
        DineInOrder.objects.filter(pk=acted.pk).update(status='preparing')
        queue_reminders(now)
        self.assertTrue(Notification.objects.filter(order=old, kind='order_reminder').exists())
        self.assertFalse(Notification.objects.filter(order=fresh).exists())
        self.assertFalse(Notification.objects.filter(order=acted).exists())
        DineInOrder.objects.filter(pk=old.pk).update(status='preparing')
        process_pending()
        self.assertEqual(Notification.objects.filter(status='skipped').count(), 2)

    def test_reservation_reminder_delivery_past_and_pending_exclusion(self):
        row = self.booking(status='approved')
        self.booking(status='pending')
        self.booking(status='cancelled')
        due = reservation_start(row)-timedelta(minutes=30)
        with patch('notifications.services.timezone.now', return_value=due):
            process_pending(); process_pending()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Upcoming Approved Reservation', mail.outbox[0].subject)
        past = self.booking(status='approved')
        with patch('notifications.services.timezone.now', return_value=reservation_start(past)+timedelta(minutes=1)):
            process_pending()
        self.assertFalse(Notification.objects.filter(reservation=past).exists())

    def test_overlapping_worker_cannot_claim_processing_job(self):
        job = enqueue('new_order', order=self.order())
        def nested_send(*args, **kwargs):
            self.assertEqual(process_pending(), 0)
            return 1
        with patch('notifications.services.send_mail', side_effect=nested_send) as sender:
            process_pending()
            self.assertEqual(sender.call_count, 1)
        job.refresh_from_db(); self.assertEqual(job.status, 'sent')

    @override_settings(ORDER_REMINDER_MINUTES=5, RESERVATION_REMINDER_MINUTES=20)
    def test_configured_thresholds_and_single_order_reminder(self):
        now = timezone.now()
        row = self.booking(status='approved')
        queue_reminders(reservation_start(row)-timedelta(minutes=21))
        self.assertFalse(Notification.objects.filter(reservation=row).exists())
        order = self.order()
        DineInOrder.objects.filter(pk=order.pk).update(created_at=now-timedelta(minutes=6))
        process_pending(); process_pending()
        self.assertEqual(Notification.objects.filter(order=order).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Order still Received', mail.outbox[0].subject)
        late = enqueue('reservation_reminder', reservation=row)
        with patch('notifications.services.timezone.now', return_value=reservation_start(row)):
            process_pending()
        late.refresh_from_db(); self.assertEqual(late.status, 'skipped')
