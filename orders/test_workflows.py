from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import BookingHours, ReservationRequest, ZoneCapacity
from menu.models import MenuItem
from orders.models import DineInOrder, ServiceLocation


class WorkflowTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_superuser('operator', password='test-only')
        self.item = MenuItem.objects.create(slug='coffee', name='Coffee', price='123.45')
        self.location = ServiceLocation.objects.create(label='Test table')
        self.date = timezone.localdate() + timedelta(days=1)
        BookingHours.objects.create(weekday=self.date.weekday(), opens=time(10), closes=time(18))
        ZoneCapacity.objects.create(zone='quiet', seats=2)

    def staff_action(self, model, action, row):
        self.client.force_login(self.staff)
        response = self.client.post(reverse(f'admin:{model}_changelist'), {
            'action': action, '_selected_action': row.pk, 'index': '0',
        })
        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()

    def open_checkout(self):
        response = self.client.get(reverse('orders:scan', args=[self.location.token]), follow=True)
        self.assertContains(response, self.location.label)
        self.client.post(reverse('orders:bag_change', args=[self.item.pk, 'add']))
        return self.client.get(reverse('orders:checkout')).context['quote']

    def test_qr_order_retry_snapshot_and_staff_queue(self):
        quote = self.open_checkout()
        url = reverse('orders:checkout')
        first = self.client.post(url, {'quote': quote})
        second = self.client.post(url, {'quote': quote})
        self.assertEqual(first.url, second.url)
        order = DineInOrder.objects.get()
        self.assertEqual(order.location, self.location)
        self.assertEqual(order.lines.get().unit_price, Decimal('123.45'))
        self.assertContains(self.client.get(first.url), 'Received')
        self.staff_action('orders_dineinorder', 'start_preparing', order)
        self.assertEqual(order.status, 'preparing')
        self.staff_action('orders_dineinorder', 'complete_orders', order)
        self.assertContains(self.client.get(first.url), 'Completed')

    def test_disabled_location_and_changed_price_prevent_checkout(self):
        quote = self.open_checkout()
        MenuItem.objects.filter(pk=self.item.pk).update(price=200)
        result = self.client.post(reverse('orders:checkout'), {'quote': quote}, follow=True)
        self.assertContains(result, 'prices changed')
        quote = self.client.get(reverse('orders:checkout')).context['quote']
        ServiceLocation.objects.filter(pk=self.location.pk).update(enabled=False)
        result = self.client.post(reverse('orders:checkout'), {'quote': quote}, follow=True)
        self.assertContains(result, 'location is unavailable')
        self.assertEqual(self.client.get(reverse('orders:scan', args=[self.location.token])).status_code, 404)
        self.assertFalse(DineInOrder.objects.exists())

    def test_reservation_approval_rechecks_capacity_and_status(self):
        data = {'name': 'Guest', 'email': 'guest@example.test', 'phone': '+92 300 1234567',
                'date': self.date.isoformat(), 'time': '11:00', 'guests': 2, 'zone': 'quiet'}
        url = reverse('core:booking')
        first = self.client.post(url, data)
        # Two distinct guests; retrying one submission now returns its existing reference.
        second = Client().post(url, data)
        a, b = ReservationRequest.objects.order_by('pk')
        self.assertContains(self.client.get(first.url), 'Pending review')
        self.staff_action('bookings_reservationrequest', 'approve_requests', a)
        self.assertContains(self.client.get(first.url), 'Approved')
        self.staff_action('bookings_reservationrequest', 'approve_requests', b)
        self.assertEqual(b.status, 'pending')
        self.staff_action('bookings_reservationrequest', 'reject_requests', b)
        self.assertContains(self.client.get(second.url), 'Rejected')
        self.client.get(url)  # Start a new request rather than replay the first submission.
        self.assertContains(self.client.post(url, data), 'cannot accommodate')
        self.assertContains(self.client.post(url, {**data, 'time': '18:00'}), 'outside the configured')

    def test_staff_menu_edit_reaches_storefront(self):
        self.client.force_login(self.staff)
        result = self.client.post(reverse('admin:menu_menuitem_change', args=[self.item.pk]), {
            'name': self.item.name, 'slug': self.item.slug, 'description': 'Updated description',
            'price': '150.50', 'display_order': 1, 'active': 'on', '_save': 'Save',
        })
        self.assertEqual(result.status_code, 302)
        page = self.client.get(reverse('core:menu'))
        self.assertContains(page, '150.50')
        self.assertContains(page, 'Updated description')
