from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse

from notifications.models import Notification
from .models import DineInOrder, OrderLine
from .services import transition_orders, verify_payments


class ManualPaymentReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user('payment-reviewer', is_staff=True)
        cls.staff.user_permissions.set(Permission.objects.filter(
            content_type__app_label='orders', codename__in=[
                'view_dineinorder', 'change_dineinorder', 'verify_payment']))
        cls.viewer = get_user_model().objects.create_user('payment-viewer', is_staff=True)
        cls.viewer.user_permissions.add(Permission.objects.get(codename='view_dineinorder'))

    def order(self, method='jazzcash', fulfilment='delivery', **extra):
        values = dict(submission_key=uuid4(), location_label='Lahore', fulfilment=fulfilment,
            total=1500, payment_method=method, payment_receiver='TEST-ACCOUNT',
            payment_status='pending', transaction_reference='TEST-TRANSFER', notes='PRIVATE NOTE')
        values.update(extra)
        row = DineInOrder.objects.create(**values)
        OrderLine.objects.create(order=row, name='Coffee', unit_price=1500, quantity=1)
        return row

    def submit(self, row, decision='approve', interface='staff', client=None):
        name = 'staff:payment_verify' if interface == 'staff' else 'admin:orders_dineinorder_change'
        data = {'decision': decision} if interface == 'staff' else {
            'change_payment_status': decision, '_save': 'Save',
            'lines-TOTAL_FORMS': '1', 'lines-INITIAL_FORMS': '1',
            'lines-MIN_NUM_FORMS': '0', 'lines-MAX_NUM_FORMS': '1000',
            'lines-0-id': row.lines.get().pk, 'lines-0-order': row.pk}
        return (client or self.client).post(reverse(name, args=[row.pk]), data, follow=True)

    def test_approval_original_links_and_delivery_pickup_progression(self):
        self.client.force_login(self.staff)
        for method, fulfilment, action, message in (
            ('jazzcash', 'delivery', 'out_for_delivery', 'Your order is on its way.'),
            ('easypaisa', 'pickup', 'ready_for_pickup', 'Your order is ready for pickup.'),
        ):
            row = self.order(method, fulfilment)
            link = reverse('orders:receipt', args=[row.reference])
            guest = Client()
            self.assertContains(guest.get(link), 'We’re checking your transfer.')
            self.assertEqual(self.submit(row).status_code, 200)
            row.refresh_from_db()
            stamp = row.verified_at
            self.assertEqual(row.verified_by, self.staff)
            self.assertIsNotNone(stamp)
            self.assertEqual(row.status, 'received')
            self.assertEqual(row.payment_status, 'paid')
            response = guest.get(link)
            self.assertContains(response, 'Payment approved.')
            self.assertContains(response, 'We’ll start preparing your order shortly')
            self.assertIn('no-store', response['Cache-Control'])
            for private in ('PRIVATE NOTE', 'payment-reviewer', 'Verified'):
                self.assertNotContains(response, private)
            count = Notification.objects.count()
            self.submit(row)
            row.refresh_from_db()
            self.assertEqual(row.verified_at, stamp)
            self.assertEqual(Notification.objects.count(), count)
            url = reverse('staff:order_action', args=[row.pk])
            self.client.post(url, {'action': 'start_preparing'})
            self.assertContains(guest.get(link), 'We’re preparing your order')
            self.client.post(url, {'action': action})
            self.assertContains(guest.get(link), message)
            self.client.post(url, {'action': 'finish_delivery' if fulfilment == 'delivery' else 'finish_pickup'})
            row.refresh_from_db()
            self.assertEqual(row.status, 'completed')

    def test_admin_approval_rejection_and_stale_decisions(self):
        self.client.force_login(self.staff)
        for decision, expected in [('approve', 'paid'), ('reject', 'rejected')]:
            row = self.order()
            detail = self.client.get(reverse('admin:orders_dineinorder_change', args=[row.pk]))
            self.assertContains(detail, 'Change payment status')
            self.assertEqual(self.submit(row, decision, 'admin').status_code, 200)
            row.refresh_from_db()
            self.assertEqual(row.payment_status, expected)
            self.assertEqual(row.verified_by, self.staff)
            stamp = row.verified_at
            self.submit(row, 'reject' if decision == 'approve' else 'approve', 'admin')
            row.refresh_from_db()
            self.assertEqual(row.payment_status, expected)
            self.assertEqual(row.verified_at, stamp)

    def test_rejection_and_unpaid_transfer_handoff_guards(self):
        self.client.force_login(self.staff)
        row = self.order()
        self.submit(row, 'reject')
        row.refresh_from_db()
        self.assertEqual(row.payment_status, 'rejected')
        self.assertContains(self.client.get(reverse('orders:receipt', args=[row.reference])),
            'We couldn’t verify your payment. Please check your transfer details or contact the café.')
        for fulfilment, action in [('delivery', 'out_for_delivery'), ('pickup', 'ready_for_pickup')]:
            for state in ('pending', 'unpaid', 'rejected'):
                row = self.order(fulfilment=fulfilment, payment_status=state, status='preparing')
                qs = DineInOrder.objects.filter(pk=row.pk)
                self.assertEqual(transition_orders(qs, action), 0)
                self.assertEqual(transition_orders(qs, 'complete_orders'), 0)
        for method in ('cash', 'cod', 'card'):
            row = self.order(method=method, status='preparing', payment_status='unpaid')
            self.assertEqual(transition_orders(DineInOrder.objects.filter(pk=row.pk), 'complete_orders'), 1)

    def test_permissions_csrf_invalid_and_leave_pending(self):
        row = self.order()
        self.client.force_login(self.viewer)
        for interface in ('staff', 'admin'):
            self.assertEqual(self.submit(row, interface=interface).status_code, 403)
            csrf = Client(enforce_csrf_checks=True)
            csrf.force_login(self.staff)
            self.assertEqual(self.submit(row, interface=interface, client=csrf).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.submit(row, 'invalid').status_code, 400)
        self.submit(row, 'leave_pending')
        row.refresh_from_db()
        self.assertEqual(row.payment_status, 'pending')
        row.transaction_reference = ''
        row.save()
        self.assertEqual(verify_payments(DineInOrder.objects.filter(pk=row.pk), self.staff), 0)
