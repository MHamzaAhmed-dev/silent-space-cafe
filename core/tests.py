from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from menu.models import MenuItem
from bookings.models import ZoneCapacity


class EditorialHomepageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_menu', stdout=StringIO())
        ZoneCapacity.objects.create(zone='reading', seats=4)

    def test_curated_preview_uses_current_database_names_and_prices(self):
        MenuItem.objects.filter(slug='rose-latte').update(name='Seasonal Rose Latte', price='1523.45')
        response = self.client.get(reverse('core:home'))
        self.assertEqual([item.slug for item in response.context['menu_preview']],
                         ['classic-cappuccino', 'rose-latte', 'waffle-sandwich'])
        self.assertContains(response, 'Seasonal Rose Latte')
        self.assertContains(response, 'Rs. 1,523.45')
        self.assertEqual(response.context['menu_preview'][1].price, Decimal('1523.45'))

    def test_unavailable_favourite_is_omitted_and_full_menu_remains_complete(self):
        MenuItem.objects.filter(slug='rose-latte').update(active=False)
        response = self.client.get(reverse('core:home'))
        self.assertNotContains(response, 'Rose Latte')
        self.assertEqual(len(response.context['menu_preview']), 3)
        self.assertEqual(response.context['menu_preview'][-1].slug, 'bubble-shot')
        self.assertEqual(len(list(response.context['catalogue'])), 5)
        self.assertEqual(len(list(self.client.get(reverse('core:menu')).context['catalogue'])), 5)

    def test_empty_menu_keeps_booking_and_custom_items_have_a_safe_image_fallback(self):
        MenuItem.objects.update(active=False)
        response = self.client.get(reverse('core:home'))
        self.assertContains(response, 'No menu items are available right now')
        self.assertContains(response, 'Send reservation request')
        self.assertContains(response, 'id="book-a-table"')
        MenuItem.objects.create(slug='seasonal-drink', name='Seasonal Drink', price='800')
        response = self.client.get(reverse('core:home'))
        self.assertContains(response, 'Seasonal Drink')
        self.assertContains(response, 'Product photo not yet provided')

    def test_zone_link_initial_value_is_validated_and_does_not_override_post(self):
        url = reverse('core:booking')
        self.assertEqual(self.client.get(url, {'zone': 'reading'}).context['reservation_form'].initial['zone'], 'reading')
        self.assertNotIn('zone', self.client.get(url, {'zone': 'invalid'}).context['reservation_form'].initial)
        response = self.client.post(url+'?zone=reading', {'zone': 'invalid'})
        self.assertIn('zone', response.context['reservation_form'].errors)


class SpacesBookingFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from datetime import time, timedelta
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        from django.utils import timezone
        from bookings.models import BookingHours
        cls.day = timezone.localdate()+timedelta(days=1)
        BookingHours.objects.create(weekday=cls.day.weekday(), opens=time(10), closes=time(18))
        for zone,seats in [('quiet',2),('reading',4),('solo',1)]:
            ZoneCapacity.objects.create(zone=zone,seats=seats)
        cls.operator=get_user_model().objects.create_user('spaces-operator',password='test-only',is_staff=True)
        cls.operator.user_permissions.set(Permission.objects.filter(codename__in=['view_reservationrequest','change_reservationrequest']))

    def test_spaces_route_real_identifiers_guest_copy_and_legacy_link(self):
        response=self.client.get(reverse('core:zones'))
        self.assertEqual(reverse('core:zones'),'/spaces/')
        self.assertTemplateUsed(response,'base.html')
        self.assertContains(response,'Find your quiet.')
        for zone in ['quiet','reading','solo']:
            self.assertContains(response,reverse('core:booking')+'?zone='+zone)
        self.assertContains(response,'Keep calls outside the quiet zones.')
        self.assertContains(response,'Ask us about the book exchange.')
        for word in ['proposal','thesis','demo','implementation']:
            self.assertNotContains(response,word)
        self.assertRedirects(self.client.get('/quiet-zones/?zone=reading'),'/spaces/?zone=reading',status_code=301)
        homepage=self.client.get(reverse('core:home'))
        self.assertContains(homepage,'href="/spaces/">Explore the spaces</a>')
        self.assertContains(homepage,'id="quiet-zones"')

    def test_all_links_preselect_active_zone_and_general_form_is_unselected(self):
        url=reverse('core:booking')
        for zone in ['quiet','reading','solo']:
            form=self.client.get(url,{'zone':zone}).context['reservation_form']
            self.assertEqual(form['zone'].value(),zone)
            self.assertEqual([value for value,label in form.fields['zone'].choices],['','quiet','reading','solo'])
        self.assertFalse(self.client.get(url).context['reservation_form']['zone'].value())
        self.assertFalse(self.client.get(url,{'zone':'not-a-zone'}).context['reservation_form']['zone'].value())

    def test_inactive_and_missing_configuration_omit_preselection_and_reject_post(self):
        from bookings.models import ReservationRequest
        ZoneCapacity.objects.filter(zone='reading').update(seats=0)
        ZoneCapacity.objects.filter(zone='solo').delete()
        for zone in ['reading','solo']:
            form=self.client.get(reverse('core:booking'),{'zone':zone}).context['reservation_form']
            self.assertFalse(form['zone'].value())
            self.assertEqual([value for value,label in form.fields['zone'].choices],['','quiet'])
        response=self.client.post(reverse('core:booking'),{'date':self.day,'time':'11:00','zone':'reading','guests':1,'name':'Preserved Guest','phone':'03001234567'})
        self.assertContains(response,'This seating zone is not available')
        self.assertEqual(response.context['reservation_form']['name'].value(),'Preserved Guest')
        self.assertFalse(ReservationRequest.objects.exists())

    def test_full_active_zone_keeps_selection_and_reuses_availability_message(self):
        from datetime import time
        from bookings.models import ReservationRequest
        from bookings.services import transition_reservations
        for hour in range(10,18):
            ReservationRequest.objects.create(date=self.day,time=time(hour),zone='quiet',guests=2,name='Approved Guest',status='approved')
        form=self.client.get(reverse('core:booking'),{'zone':'quiet'}).context['reservation_form']
        self.assertEqual(form['zone'].value(),'quiet')
        response=self.client.post(reverse('core:booking'),{'action':'check_availability','date':self.day,'zone':'quiet','guests':1,'name':'Keep my details'})
        self.assertContains(response,'No available times for this selection')
        self.assertEqual(response.context['reservation_form']['zone'].value(),'quiet')
        self.assertEqual(response.context['reservation_form']['name'].value(),'Keep my details')
        transition_reservations(ReservationRequest.objects.filter(time=time(11)),'cancel_reservations')
        result=self.client.get(reverse('bookings:availability'),{'date':self.day,'zone':'quiet','guests':1}).json()
        self.assertEqual([row['value'] for row in result['times']],['11:00'])

    def test_space_booking_zone_and_reference_match_customer_and_staff(self):
        from bookings.models import ReservationRequest
        entry=self.client.get(reverse('core:booking'),{'zone':'reading'})
        token=entry.context['reservation_form'].initial['submission_token']
        result=self.client.post(reverse('core:booking'),{'date':self.day,'guests':1,'zone':'reading','time':'12:00','name':'Spaces Guest','phone':'03001234567','submission_token':token})
        self.assertEqual(result.status_code,302)
        row=ReservationRequest.objects.get()
        self.assertEqual(row.zone,ReservationRequest.Zone.READING)
        self.assertEqual(row.status,'pending')
        status=self.client.get(result.url)
        self.assertContains(status,str(row.reference))
        self.assertContains(status,'Reading Zone')
        self.client.force_login(self.operator)
        staff=self.client.get(reverse('staff:reservation_detail',args=[row.pk]))
        self.assertContains(staff,str(row.reference))
        self.assertContains(staff,'Reading Zone')
