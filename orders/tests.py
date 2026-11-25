from decimal import Decimal
from io import StringIO
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from menu.models import MenuItem


class BagTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_menu', stdout=StringIO())

    def setUp(self):
        self.item = MenuItem.objects.get(slug='classic-cappuccino')

    def change(self, action, item=None, **data):
        return self.client.post(reverse('orders:bag_change', args=[(item or self.item).pk, action]), data, follow=True)

    def test_seed_names_prices_and_repeat_preserves_edits(self):
        expected = [('Classic Cappuccino', Decimal('1100')), ('Bubble Shot', Decimal('1000')),
                    ('Waffle Sandwich', Decimal('1800')), ('Orange Malt', Decimal('800')),
                    ('Rose Latte', Decimal('1500')), ('Hot Double Chocolate', Decimal('1300'))]
        self.assertEqual(list(MenuItem.objects.values_list('name', 'price')), expected)
        self.item.price = Decimal('1234.50')
        self.item.active = False
        self.item.display_order = 99
        self.item.save()
        call_command('seed_menu', stdout=StringIO())
        self.item.refresh_from_db()
        self.assertEqual(MenuItem.objects.count(), 6)
        self.assertEqual(self.item.price, Decimal('1234.50'))
        self.assertFalse(self.item.active)
        self.assertEqual(self.item.display_order, 99)

    def test_empty_and_active_storefront_order(self):
        response = self.client.get(reverse('orders:bag'))
        self.assertContains(response, 'Your bag is empty')
        self.item.active = False
        self.item.save()
        rose = MenuItem.objects.get(slug='rose-latte')
        rose.display_order = 0
        rose.save()
        response = self.client.get('/')
        self.assertNotContains(response, 'Classic Cappuccino')
        self.assertEqual(list(response.context['catalogue'])[0], rose)

    def test_totals_quantities_remove_and_persistence(self):
        self.change('add')
        self.change('increase')
        rose = MenuItem.objects.get(slug='rose-latte')
        response = self.change('add', rose, price='0.01', quantity='9999')
        bag = response.context['bag']
        self.assertEqual(bag['count'], 3)
        self.assertEqual(bag['total'], Decimal('3700'))
        self.assertEqual(bag['lines'][0]['subtotal'], Decimal('2200'))
        self.assertContains(response, 'Bag (3)')
        # A new client with the same browser cookie retains the session-backed bag.
        refreshed = Client()
        refreshed.cookies = self.client.cookies
        self.assertEqual(refreshed.get(reverse('orders:bag')).context['bag']['total'], Decimal('3700'))
        response = self.change('decrease')
        self.assertEqual(response.context['bag']['total'], Decimal('2600'))
        self.change('remove', rose)
        response = self.change('decrease')
        self.assertEqual(response.context['bag']['count'], 0)
        self.assertContains(response, 'Your bag is empty')

    def test_server_reprices(self):
        self.change('add')
        self.item.price = Decimal('1200.50')
        self.item.save()
        response = self.client.get(reverse('orders:bag'))
        self.assertEqual(response.context['bag']['total'], Decimal('1200.50'))
        self.assertContains(response, '1,200.50')

    def test_disabled_after_add_is_removed_and_cannot_be_added(self):
        self.change('add')
        self.item.active = False
        self.item.save()
        response = self.client.get(reverse('orders:bag'))
        self.assertEqual(response.context['bag']['count'], 0)
        self.assertEqual(self.client.session['bag'], {})
        self.assertContains(response, 'Unavailable items')
        response = self.change('add')
        self.assertEqual(response.context['bag']['count'], 0)
        self.assertContains(response, 'no longer available')

    def test_deleted_after_add_and_stale_post(self):
        self.change('add')
        pk = self.item.pk
        self.item.delete()
        response = self.client.get(reverse('orders:bag'))
        self.assertEqual(response.context['bag']['total'], Decimal('0'))
        for action in ['add', 'increase', 'decrease', 'remove']:
            response = self.client.post(reverse('orders:bag_change', args=[pk, action]), follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['bag']['count'], 0)

    def test_post_only_and_csrf_for_every_action(self):
        strict = Client(enforce_csrf_checks=True)
        for action in ['add', 'increase', 'decrease', 'remove']:
            url = reverse('orders:bag_change', args=[self.item.pk, action])
            self.assertEqual(strict.get(url).status_code, 405)
            self.assertEqual(strict.post(url).status_code, 403)
        strict.get('/')
        token = strict.cookies['csrftoken'].value
        response = strict.post(reverse('orders:bag_change', args=[self.item.pk, 'add']), {'csrfmiddlewaretoken': token}, follow=True)
        self.assertEqual(response.context['bag']['count'], 1)

    def test_quantity_limit_and_invalid_session(self):
        session = self.client.session
        session['bag'] = {str(self.item.pk): 10000, 'bogus': 'bad', '9'*100: 5}
        session.save()
        response = self.client.get(reverse('orders:bag'))
        self.assertEqual(response.context['bag']['count'], 99)
        response = self.change('increase')
        self.assertEqual(response.context['bag']['count'], 99)
        self.assertContains(response, 'Maximum quantity')

    def test_remove_last_and_increase_absent(self):
        self.change('increase')
        self.assertEqual(self.client.session['bag'], {})
        self.change('add')
        self.change('remove')
        self.assertEqual(self.client.session['bag'], {})
