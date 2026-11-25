from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import BookingHours, ReservationRequest, ZoneCapacity


class DetailReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.day = timezone.localdate() + timedelta(days=1)
        BookingHours.objects.create(weekday=cls.day.weekday(), opens=time(10), closes=time(18))
        ZoneCapacity.objects.create(zone='quiet', seats=2)
        cls.editor = get_user_model().objects.create_user('reviewer', is_staff=True)
        cls.editor.user_permissions.set(Permission.objects.filter(
            content_type__app_label='bookings', codename__in=['view_reservationrequest', 'change_reservationrequest']))
        cls.viewer = get_user_model().objects.create_user('readonly', is_staff=True)
        cls.viewer.user_permissions.add(Permission.objects.get(codename='view_reservationrequest'))

    def booking(self):
        return ReservationRequest.objects.create(name='Review guest', date=self.day,
            time=time(11), zone='quiet', guests=2, cancellation_reason='PRIVATE STAFF NOTE')

    def endpoint(self, interface, row):
        return reverse('admin:bookings_reservationrequest_change', args=[row.pk]) if interface == 'admin' else reverse('staff:reservation_action', args=[row.pk])

    def submit(self, interface, row, action, client=None):
        data = {'change_status': action, '_save': 'Save'} if interface == 'admin' else {'action': action}
        return (client or self.client).post(self.endpoint(interface, row), data, follow=True)

    def test_each_interface_updates_original_private_links_and_handles_full_or_stale(self):
        self.client.force_login(self.editor)
        for interface in ('admin', 'staff'):
            with self.subTest(interface=interface):
                approved, rejected, full = self.booking(), self.booking(), self.booking()
                for row, action, status, text in (
                    (approved, 'approve_requests', 'approved', 'Your reservation is confirmed.'),
                    (rejected, 'reject_requests', 'rejected', 'We couldn\u2019t confirm this request.'),
                ):
                    reference = row.reference
                    link = reverse('bookings:status', args=[reference])
                    self.assertContains(self.client.get(link), 'Pending review')
                    response = self.submit(interface, row, action)
                    self.assertEqual(response.status_code, 200)
                    row.refresh_from_db()
                    self.assertEqual(row.status, status)
                    self.assertEqual(row.reference, reference)
                    guest = Client().get(link)
                    self.assertContains(guest, text)
                    self.assertNotContains(guest, 'PRIVATE STAFF NOTE')
                    self.assertIn('no-store', guest['Cache-Control'])
                response = self.submit(interface, full, 'approve_requests')
                self.assertContains(response, 'cannot accommodate')
                full.refresh_from_db()
                self.assertEqual(full.status, 'pending')
                response = self.submit(interface, approved, 'reject_requests')
                self.assertContains(response, 'already changed')
                approved.refresh_from_db()
                self.assertEqual(approved.status, 'approved')
                ReservationRequest.objects.all().delete()

    def test_viewer_cannot_change_and_posts_require_csrf(self):
        row = self.booking()
        for interface in ('admin', 'staff'):
            self.client.force_login(self.viewer)
            detail = reverse('staff:reservation_detail', args=[row.pk]) if interface == 'staff' else self.endpoint(interface, row)
            self.assertNotContains(self.client.get(detail), 'Change status')
            response = self.submit(interface, row, 'approve_requests')
            self.assertEqual(response.status_code, 403)
            row.refresh_from_db()
            self.assertEqual(row.status, 'pending')
            csrf = Client(enforce_csrf_checks=True)
            csrf.force_login(self.editor)
            self.assertEqual(self.submit(interface, row, 'approve_requests', csrf).status_code, 403)

    def test_controls_and_leave_pending(self):
        self.client.force_login(self.editor)
        row = self.booking()
        for name in ('admin:bookings_reservationrequest_change', 'staff:reservation_detail'):
            response = self.client.get(reverse(name, args=[row.pk]))
            for label in ('Change status', 'Leave pending', 'Approve', 'Reject'):
                self.assertContains(response, label)
        self.submit('admin', row, '')
        self.submit('staff', row, 'leave_pending')
        row.refresh_from_db()
        self.assertEqual(row.status, 'pending')
