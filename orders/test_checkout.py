"""Checkout regressions using isolated database records and no live gateway/email."""
from decimal import Decimal
import hashlib
import hmac
import json
import time
from unittest.mock import patch
from uuid import uuid4
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import mail
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from menu.models import MenuItem
from notifications.models import Notification
from notifications.services import process_pending
from .models import DeliveryArea, DineInOrder, OrderLine, PaymentMethod, PaymentEvent, ServiceLocation


@override_settings(STRIPE_SECRET_KEY='', STRIPE_WEBHOOK_SECRET='', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', STAFF_NOTIFICATION_RECIPIENTS=['checkout@example.test'])
class CheckoutTests(TestCase):
    def setUp(self):
        self.item = MenuItem.objects.create(slug='classic-cappuccino', name='Classic Cappuccino', price='1100')
        self.area = DeliveryArea.objects.create(name='Test area A', fee='100')
        self.other = DeliveryArea.objects.create(name='Test area B', fee='250')
        self.cash = PaymentMethod.objects.get(code='cod')
        self.jazz = PaymentMethod.objects.get(code='jazzcash')
        self.staff = get_user_model().objects.create_user('payment-reviewer', is_staff=True)
        self.staff.user_permissions.set(Permission.objects.filter(codename__in=['view_dineinorder', 'verify_payment']))
        self.client.post(reverse('orders:bag_change', args=[self.item.pk, 'add']))

    def quote(self):
        return self.client.get(reverse('orders:bag')).context['customer_quote']

    def data(self, quote=None, **values):
        return {'customer_quote': quote or self.quote(), 'fulfilment': 'delivery', 'customer_name': 'Test Guest',
            'phone': '03001234567', 'delivery_area': self.area.pk, 'street_address': '42 Test Road',
            'notes': 'Ring once', 'payment_method': self.jazz.pk, **values}

    def submit(self, data):
        return self.client.post(reverse('orders:checkout'), data)

    def test_delivery_area_fees_repeat_checkout_email_and_snapshot(self):
        data = self.data(delivery_area=self.other.pk, total='0.01', delivery_fee='0')
        first = self.submit(data); second = self.submit(data)
        self.assertEqual(first.url, second.url)
        row = DineInOrder.objects.get()
        self.assertEqual(row.total, Decimal('1350'))
        self.assertEqual(row.delivery_fee, Decimal('250'))
        self.assertEqual(row.fulfilment, 'delivery')
        self.assertEqual(row.payment_receiver, '03249233487')
        self.assertEqual(Notification.objects.filter(kind='new_order').count(), 1)
        self.item.price = 5000; self.item.save()
        self.other.fee = 900; self.other.save()
        self.jazz.receiver = '03009999999'; self.jazz.save()
        row.refresh_from_db()
        self.assertEqual(row.total, Decimal('1350'))
        self.assertEqual(row.lines.get().unit_price, Decimal('1100'))
        self.assertEqual(row.payment_receiver, '03249233487')
        process_pending()
        self.assertEqual(len(mail.outbox), 1)
        for text in ['Delivery', str(row.reference), 'Classic Cappuccino x 1', '1350.00', 'Awaiting payment']:
            self.assertIn(text, mail.outbox[0].body)
        self.assertContains(self.client.get(first.url), 'Copy receiver number')

    def test_changed_fee_requires_review_and_unserved_area_is_rejected(self):
        data = self.data()
        DeliveryArea.objects.filter(pk=self.area.pk).update(fee=200)
        result = self.submit(data)
        self.assertContains(result, 'delivery fee changed')
        self.assertContains(result, '42 Test Road')
        self.assertContains(result, '1,300')
        self.assertFalse(DineInOrder.objects.exists())
        data = self.data()
        DeliveryArea.objects.filter(pk=self.area.pk).update(enabled=False)
        self.assertEqual(self.submit(data).status_code, 200)
        self.assertFalse(DineInOrder.objects.exists())
        self.assertEqual(self.submit(self.data(delivery_area=999999)).status_code, 200)
        self.assertFalse(DineInOrder.objects.exists())

    def test_payment_reference_permission_verification_and_replay(self):
        result = self.submit(self.data())
        row = DineInOrder.objects.get()
        transfer = reverse('orders:transfer_reference', args=[row.reference])
        self.assertEqual(self.client.get(transfer).status_code, 405)
        self.client.post(transfer, {'transaction_reference': 'TX-12345'})
        row.refresh_from_db(); self.assertEqual(row.payment_status, 'pending')
        url = reverse('staff:payment_verify', args=[row.pk])
        viewer = get_user_model().objects.create_user('viewer', is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(codename='view_dineinorder'))
        self.client.force_login(viewer)
        self.assertEqual(self.client.post(url).status_code, 403)
        customer = get_user_model().objects.create_user('customer')
        self.client.force_login(customer); self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url).status_code, 302)
        row.refresh_from_db(); stamp = row.verified_at
        self.assertEqual(row.verified_by, self.staff); self.assertEqual(row.payment_status, 'paid')
        self.client.post(url); self.client.post(transfer, {'transaction_reference': 'OTHER'})
        row.refresh_from_db(); self.assertEqual(row.verified_at, stamp)
        self.assertEqual(row.transaction_reference, 'TX-12345')
        self.assertEqual(row.status, 'received')
        self.assertContains(self.client.get(result.url), 'Paid')
        strict = Client(enforce_csrf_checks=True); strict.force_login(self.staff)
        self.assertEqual(strict.post(url).status_code, 403)

    def test_cod_pickup_and_method_eligibility(self):
        self.submit(self.data(payment_method=self.cash.pk))
        row = DineInOrder.objects.get(); self.assertEqual(row.payment_status, 'unpaid')
        self.client.post(reverse('orders:bag_change', args=[self.item.pk, 'add']))
        cash = PaymentMethod.objects.get(code='cash')
        data = self.data(fulfilment='pickup', payment_method=cash.pk, delivery_area=self.other.pk, street_address='ignore')
        self.submit(data)
        row = DineInOrder.objects.latest('pk'); self.assertEqual(row.total, Decimal('1100'))
        self.assertEqual(row.delivery_fee, 0); self.assertIsNone(row.delivery_area)
        self.assertEqual(row.street_address, '')
        self.client.post(reverse('orders:bag_change', args=[self.item.pk, 'add']))
        for method in [self.cash, PaymentMethod.objects.get(code='easypaisa'), PaymentMethod.objects.get(code='card')]:
            self.submit(self.data(fulfilment='pickup', payment_method=method.pk))
        self.assertEqual(DineInOrder.objects.count(), 2)
        response = self.client.get(reverse('orders:bag'))
        self.assertNotContains(response, 'Card (Visa / Mastercard)')

    def test_qr_context_methods_and_unavailable_bag_item(self):
        location = ServiceLocation.objects.create(label='Reading Table 08')
        self.client.get(reverse('orders:scan', args=[location.token]))
        self.assertContains(self.client.get(reverse('orders:bag')), location.label)
        quote = self.client.get(reverse('orders:checkout')).context['quote']
        self.client.post(reverse('orders:checkout'), {'quote': quote, 'payment_method': self.jazz.pk})
        row = DineInOrder.objects.get()
        self.assertEqual(row.location, location); self.assertEqual(row.fulfilment, 'dine_in')
        self.assertEqual(row.payment_method, 'jazzcash'); self.assertEqual(row.total, Decimal('1100'))
        self.client.post(reverse('orders:bag_change', args=[self.item.pk, 'add']))
        self.item.active = False; self.item.save()
        self.assertContains(self.client.get(reverse('orders:bag')), 'Unavailable items')

    def test_server_rendered_refresh_and_staff_filters(self):
        response = self.submit(self.data(action='refresh', delivery_area=self.other.pk))
        self.assertContains(response, '1,350')
        self.assertFalse(DineInOrder.objects.exists())
        self.submit(self.data())
        row = DineInOrder.objects.get(); row.payment_status = 'pending'; row.save()
        self.client.force_login(self.staff)
        response = self.client.get(reverse('staff:orders'), {'fulfilment': 'delivery', 'payment': 'pending'})
        self.assertEqual([r.pk for r in response.context['page_obj']], [row.pk])
        response = self.client.get(reverse('staff:orders'), {'fulfilment': 'pickup'})
        self.assertEqual(response.context['page_obj'].paginator.count, 0)
        self.assertContains(self.client.get(reverse('staff:order_detail', args=[row.pk])), '42 Test Road')

    def test_disabled_method_and_price_change_and_cross_session_quote(self):
        data = self.data()
        self.assertEqual(Client().post(reverse('orders:checkout'), data).status_code, 302)
        self.assertFalse(DineInOrder.objects.exists())
        self.item.price = 1200; self.item.save()
        self.assertContains(self.submit(data), 'prices changed')
        data = self.data()
        self.jazz.enabled = False; self.jazz.save()
        self.submit(data); self.assertFalse(DineInOrder.objects.exists())

    def test_easypaisa_when_configured(self):
        method = PaymentMethod.objects.get(code='easypaisa')
        method.receiver = '03001111111'; method.enabled = True; method.save()
        self.submit(self.data(payment_method=method.pk))
        row = DineInOrder.objects.get(); self.assertEqual(row.payment_receiver, method.receiver)
        self.client.post(reverse('orders:transfer_reference', args=[row.reference]), {'transaction_reference': 'EP-123'})
        row.refresh_from_db(); self.assertEqual(row.payment_status, 'pending')

    @override_settings(STRIPE_SECRET_KEY='sk_test_not_real', STRIPE_WEBHOOK_SECRET='whsec_test_not_real')
    def test_hosted_card_creation_signed_webhook_and_repeated_events(self):
        method = PaymentMethod.objects.get(code='card'); method.enabled = True; method.save()
        self.submit(self.data(payment_method=method.pk))
        row = DineInOrder.objects.get()
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps({'id': 'cs_test_qa', 'url': 'https://checkout.stripe.com/c/pay/test_qa'}).encode()
        with patch('orders.payments.urlopen', return_value=Response()) as api:
            result = self.client.post(reverse('orders:hosted_checkout', args=[row.reference]))
            self.assertEqual(result.url, 'https://checkout.stripe.com/c/pay/test_qa')
            request = api.call_args.args[0]
            self.assertIn(b'unit_amount%5D=120000', request.data)
        row.refresh_from_db(); self.assertEqual(row.payment_status, 'unpaid')
        self.client.get(reverse('orders:receipt', args=[row.reference]), {'success': 'true'})
        row.refresh_from_db(); self.assertEqual(row.payment_status, 'unpaid')
        event = {'id': 'evt_test_qa', 'type': 'checkout.session.completed', 'livemode': False, 'data': {'object': {
            'id': row.gateway_session, 'client_reference_id': str(row.reference),
            'metadata': {'order_reference': str(row.reference)}, 'amount_total': 120000, 'currency': 'pkr', 'payment_status': 'paid'}}}
        url = reverse('orders:stripe_webhook')
        def send(value, signed=True, offset=0):
            raw = json.dumps(value).encode(); stamp = str(int(time.time())+offset)
            digest = hmac.new(b'whsec_test_not_real', stamp.encode()+b'.'+raw, hashlib.sha256).hexdigest()
            return self.client.post(url, raw, content_type='application/json', HTTP_STRIPE_SIGNATURE=f't={stamp},v1={digest if signed else "bad"}')
        self.assertEqual(send(event, False).status_code, 400)
        self.assertEqual(send(event, offset=-400).status_code, 400)
        event['data']['object']['amount_total'] = 1
        self.assertEqual(send(event).status_code, 400)
        event['data']['object']['amount_total'] = 120000
        self.assertEqual(send(event).status_code, 200)
        row.refresh_from_db(); self.assertEqual(row.payment_status, 'paid'); stamp = row.verified_at
        self.assertEqual(send(event).status_code, 200)
        event['id'] = 'evt_test_qa_2'; self.assertEqual(send(event).status_code, 200)
        row.refresh_from_db(); self.assertEqual(row.verified_at, stamp)
        self.assertEqual(DineInOrder.objects.count(), 1); self.assertEqual(PaymentEvent.objects.count(), 2)

    def test_admin_area_configuration_and_payment_permissions(self):
        superuser = get_user_model().objects.create_superuser('config-owner', password='only-test')
        self.client.force_login(superuser)
        url = reverse('admin:orders_deliveryarea_change', args=[self.area.pk])
        result = self.client.post(url, {'name': self.area.name, 'fee': '175.50', 'enabled': 'on', '_save': 'Save'})
        self.assertEqual(result.status_code, 302)
        self.area.refresh_from_db(); self.assertEqual(self.area.fee, Decimal('175.50'))
        result = self.client.post(url, {'name': self.area.name, 'fee': '-10', 'enabled': 'on', '_save': 'Save'})
        self.assertEqual(result.status_code, 200)
        self.area.refresh_from_db(); self.assertEqual(self.area.fee, Decimal('175.50'))
        self.client.post(reverse('admin:orders_paymentmethod_change', args=[self.jazz.pk]), {
            'enabled': 'on', 'delivery': 'on', 'pickup': 'on', 'dine_in': 'on',
            'receiver': '03008888888', 'instructions': 'Use your order reference.', 'display_order': 0, '_save': 'Save'})
        self.jazz.refresh_from_db(); self.assertEqual(self.jazz.receiver, '03008888888')
        self.client.logout()
        self.client.post(reverse('orders:bag_change', args=[self.item.pk, 'add']))
        self.submit(self.data())
        row = DineInOrder.objects.get(); self.assertEqual(row.payment_receiver, '03008888888')
        self.assertEqual(row.total, Decimal('1275.50'))

    @override_settings(STRIPE_SECRET_KEY='sk_test_not_real', STRIPE_WEBHOOK_SECRET='whsec_test_not_real')
    def test_gateway_outage_keeps_saved_order_unpaid(self):
        from urllib.error import URLError
        method = PaymentMethod.objects.get(code='card'); method.enabled = True; method.save()
        result = self.submit(self.data(payment_method=method.pk))
        row = DineInOrder.objects.get()
        with patch('orders.payments.urlopen', side_effect=URLError('controlled outage')):
            response = self.client.post(reverse('orders:hosted_checkout', args=[row.reference]), follow=True)
        self.assertContains(response, 'Your order is saved')
        row.refresh_from_db(); self.assertEqual(row.payment_status, 'unpaid')
        self.assertEqual(Notification.objects.filter(order=row, kind='new_order').count(), 1)
