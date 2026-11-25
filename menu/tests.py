from decimal import Decimal
from io import BytesIO
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from core.templatetags.cafe_images import menu_photo, menu_photo_alt
from orders.models import DineInOrder, ServiceLocation
from .models import MenuItem
from .validators import MAX_IMAGE_BYTES


def photo_upload(name='coffee.png', format='PNG', color='olive'):
    stream = BytesIO()
    Image.new('RGB', (48, 48), color).save(stream, format=format)
    return SimpleUploadedFile(name, stream.getvalue(), content_type='image/'+format.lower())


class MenuControlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff = User.objects.create_user('menu-operator', password='test-only', is_staff=True)
        cls.staff.user_permissions.set(Permission.objects.filter(content_type__app_label='menu'))
        cls.viewer = User.objects.create_user('menu-viewer', password='test-only', is_staff=True)
        cls.viewer.user_permissions.add(Permission.objects.get(codename='view_menuitem'))
        cls.customer = User.objects.create_user('menu-customer', password='test-only')
        cls.item = MenuItem.objects.create(name='Classic Cappuccino', slug='classic-cappuccino', price='1100', description='Espresso with milk.')
        cls.custom = MenuItem.objects.create(name='New seasonal drink', slug='seasonal', price='876.50', display_order=2)
        cls.location = ServiceLocation.objects.create(label='Menu test table')

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.directory.name, MEDIA_URL='/media/')
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.client.force_login(self.staff)

    def edit_data(self, **changes):
        data = dict(name=self.item.name, slug=self.item.slug, description=self.item.description,
                    price='1100.00', display_order=0, active='on', image_alt='')
        data.update(changes)
        return data

    def test_upload_replace_alt_price_order_and_visibility_through_admin(self):
        url = reverse('admin:menu_menuitem_change', args=[self.item.pk])
        response = self.client.post(url, self.edit_data(image=photo_upload(), image_alt='A cappuccino in an olive ceramic cup', price='1234.50', display_order=9))
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        first_image = self.item.image.name
        self.assertTrue(self.item.image.storage.exists(first_image))
        public = self.client.get(reverse('core:menu'))
        self.assertContains(public, self.item.image.url)
        self.assertContains(public, 'A cappuccino in an olive ceramic cup')
        self.assertContains(public, 'Rs. 1,234.50')
        self.assertEqual(list(public.context['catalogue'])[0].pk, self.custom.pk)
        self.assertContains(self.client.get(url), self.item.image.url)
        self.assertContains(self.client.get(reverse('admin:menu_menuitem_changelist')), 'Photo')
        response = self.client.post(url, self.edit_data(image=photo_upload('replacement.webp', 'WEBP'), image_alt='Replacement cappuccino photo'))
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertNotEqual(self.item.image.name, first_image)
        self.assertContains(self.client.get(reverse('core:home')), self.item.image.url)
        self.assertContains(self.client.get(reverse('staff:catalogue')), self.item.image.url)
        response = self.client.post(url, self.edit_data(active='', image_alt='Replacement cappuccino photo'))
        self.assertEqual(response.status_code, 302)
        response = self.client.get(reverse('core:menu'))
        self.assertNotIn(self.item.pk, [item.pk for item in response.context['catalogue']])
        self.assertContains(self.client.get(reverse('staff:catalogue'), {'status': 'inactive'}), self.item.name)

    def test_admin_upload_requires_alt_and_valid_type_size_and_content(self):
        url = reverse('admin:menu_menuitem_change', args=[self.item.pk])
        response = self.client.post(url, self.edit_data(image=photo_upload()))
        self.assertContains(response, 'Describe this product photo')
        self.item.refresh_from_db(); self.assertFalse(self.item.image)
        for upload in [SimpleUploadedFile('bad.svg', b'<svg/>', content_type='image/svg+xml'),
                       SimpleUploadedFile('bad.jpg', b'not an image', content_type='image/jpeg'),
                       photo_upload('animated.gif', 'GIF')]:
            response = self.client.post(url, self.edit_data(image=upload, image_alt='A test product'))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['adminform'].form.errors.get('image'))
        valid = photo_upload().read()
        large = SimpleUploadedFile('large.png', valid+b'0'*(MAX_IMAGE_BYTES+1-len(valid)), content_type='image/png')
        response = self.client.post(url, self.edit_data(image=large, image_alt='A test product'))
        self.assertContains(response, 'no larger than 5 MB')
        self.assertEqual(MenuItem.objects.count(), 2)

    def test_model_validation_rejects_large_dimensions_and_alt_omission(self):
        item = MenuItem(name='Test', slug='test', price=1, image=photo_upload())
        with self.assertRaises(ValidationError) as caught:
            item.full_clean()
        self.assertIn('image_alt', caught.exception.message_dict)
        from unittest.mock import MagicMock, patch
        image = MagicMock(); image.format='PNG'; image.width=5000; image.height=5000; image.n_frames=1
        image.__enter__.return_value=image
        with patch('menu.validators.Image.open', return_value=image):
            with self.assertRaises(ValidationError) as caught:
                MenuItem(name='Large', slug='large', price=1, image=photo_upload(), image_alt='Large photo').full_clean()
            self.assertIn('20 megapixels', str(caught.exception))

    def test_image_less_items_keep_fallbacks_without_illustrative_captions(self):
        self.assertEqual(menu_photo(self.custom), '/static/images/product-placeholder.svg')
        self.assertEqual(menu_photo_alt(self.custom), 'Product photo not yet provided')
        self.assertIn('classic-cappuccino.webp', menu_photo(self.item))
        response = self.client.get(reverse('core:menu'))
        self.assertContains(response, 'Photo coming soon')
        self.assertNotContains(response, 'Illustrative')
        self.assertContains(response, 'New seasonal drink')
        self.assertContains(response, 'Rs. 876.5')

    def test_clearing_upload_restores_default_without_deleting_item(self):
        self.item.image=photo_upload(); self.item.image_alt='Coffee'; self.item.save()
        url=reverse('admin:menu_menuitem_change',args=[self.item.pk])
        response=self.client.post(url,self.edit_data(**{'image-clear':'on'}))
        self.assertEqual(response.status_code,302)
        self.item.refresh_from_db(); self.assertFalse(self.item.image)
        self.assertIn('classic-cappuccino.webp',menu_photo(self.item))
        self.assertEqual(MenuItem.objects.count(),2)

    def test_unavailable_bag_recheck_and_order_history_price_snapshot(self):
        customer=Client()
        customer.get(reverse('orders:scan',args=[self.location.token]))
        customer.post(reverse('orders:bag_change',args=[self.item.pk,'add']))
        quote=customer.get(reverse('orders:checkout')).context['quote']
        receipt=customer.post(reverse('orders:checkout'),{'quote':quote})
        order=DineInOrder.objects.get()
        self.assertEqual(order.location,self.location)
        self.assertEqual(order.lines.get().unit_price,Decimal('1100'))
        url=reverse('admin:menu_menuitem_change',args=[self.item.pk])
        self.client.post(url,self.edit_data(price='1500.25'))
        customer.post(reverse('orders:bag_change',args=[self.item.pk,'add']))
        self.assertEqual(customer.get(reverse('orders:bag')).context['bag']['total'],Decimal('1500.25'))
        self.client.post(url,self.edit_data(active=''))
        bag=customer.get(reverse('orders:bag'))
        self.assertContains(bag,'Unavailable items')
        self.assertEqual(bag.context['bag']['count'],0)
        order.refresh_from_db()
        self.assertEqual(order.total,Decimal('1100'))
        self.assertEqual(order.lines.get().unit_price,Decimal('1100'))
        self.assertContains(customer.get(receipt.url),'1,100')
        customer.post(reverse('orders:bag_change',args=[self.item.pk,'add']))
        self.assertEqual(customer.get(reverse('orders:bag')).context['bag']['count'],0)

    def test_staff_permissions_filters_and_readonly_admin(self):
        url=reverse('staff:catalogue')
        self.assertContains(self.client.get(url,{'q':'seasonal'}),self.custom.name)
        self.assertNotContains(self.client.get(url,{'q':'seasonal'}),self.item.name)
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(url),'View item')
        self.assertNotContains(self.client.get(url),'Edit item')
        edit=reverse('admin:menu_menuitem_change',args=[self.item.pk])
        self.assertEqual(self.client.get(edit).status_code,200)
        self.assertEqual(self.client.post(edit,self.edit_data(price=1)).status_code,403)
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(url).status_code,403)
