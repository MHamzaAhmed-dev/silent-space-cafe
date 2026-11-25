from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification
from notifications.services import process_pending
from .availability import available_slots
from .models import BookingHours, ReservationRequest, ZoneCapacity
from .services import transition_reservations


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   STAFF_NOTIFICATION_RECIPIENTS=['owner@example.test'])
class ReservationJourneyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.day = timezone.localdate()+timedelta(days=1)
        BookingHours.objects.create(weekday=cls.day.weekday(), opens=time(10), closes=time(18))
        ZoneCapacity.objects.create(zone='quiet', seats=2)
        ZoneCapacity.objects.create(zone='reading', seats=4)
        ZoneCapacity.objects.create(zone='solo', seats=4)
        cls.staff=get_user_model().objects.create_superuser('booking-owner', password='test-only')

    def data(self, **changes):
        data={'date':self.day.isoformat(), 'guests':2, 'zone':'quiet', 'time':'11:00',
              'name':'Quiet Guest', 'phone':'03001234567', 'special_request':'Near the books, if possible.'}
        data.update(changes)
        return data

    def start(self, client=None):
        client=client or self.client
        response=client.get(reverse('core:booking'))
        return response.context['reservation_form'].initial['submission_token']

    def approved(self, **changes):
        return ReservationRequest.objects.create(**dict(self.data(email='existing@example.test'), status='approved', **changes))

    def test_valid_request_optional_email_repeat_reference_and_one_notification(self):
        token=self.start()
        payload=self.data(submission_token=token)
        first=self.client.post(reverse('core:booking'),payload)
        second=self.client.post(reverse('core:booking'),payload)
        self.assertEqual(first.status_code,302)
        self.assertEqual(first.url,second.url)
        row=ReservationRequest.objects.get()
        self.assertEqual(row.status,'pending')
        self.assertEqual(row.email,'')
        self.assertIsNotNone(row.submission_key)
        self.assertContains(self.client.get(first.url),str(row.reference))
        self.assertEqual(Notification.objects.filter(reservation=row,kind='new_reservation').count(),1)
        process_pending(); process_pending()
        self.assertEqual(len(mail.outbox),1)
        self.assertIn(str(row.reference),mail.outbox[0].body)
        self.client.force_login(self.staff)
        detail=self.client.get(reverse('staff:reservation_detail',args=[row.pk]))
        self.assertContains(detail,str(row.reference))
        self.assertContains(detail,'03001234567')
        self.assertContains(detail,'Not provided')

    def test_repeat_returns_existing_reference_even_after_cancellation_or_expired_slot(self):
        token=self.start()
        payload=self.data(submission_token=token)
        response=self.client.post(reverse('core:booking'),payload)
        row=ReservationRequest.objects.get()
        ReservationRequest.objects.filter(pk=row.pk).update(status='approved')
        transition_reservations(ReservationRequest.objects.filter(pk=row.pk),'cancel_reservations','Guest called')
        # A replay is idempotent even when time-based validation would now reject the old date.
        with patch('bookings.forms.slot_error', return_value=('date','Expired')):
            retry=self.client.post(reverse('core:booking'),payload)
        self.assertEqual(retry.url,response.url)
        self.assertContains(self.client.get(retry.url),'Cancelled')
        self.assertEqual(ReservationRequest.objects.count(),1)
        self.assertEqual(Notification.objects.count(),1)

    def test_legacy_submission_retries_are_deduplicated_and_new_get_starts_new_request(self):
        payload=self.data()
        first=self.client.post(reverse('core:booking'),payload)
        self.assertEqual(self.client.post(reverse('core:booking'),payload).url,first.url)
        self.start()
        second=self.client.post(reverse('core:booking'),payload)
        self.assertNotEqual(first.url,second.url)
        self.assertEqual(ReservationRequest.objects.count(),2)

    def test_available_times_and_shared_solo_limit(self):
        url=reverse('bookings:availability')
        response=self.client.get(url,{'date':self.day,'guests':2,'zone':'quiet'})
        values=[row['value'] for row in response.json()['times']]
        self.assertEqual(values,[f'{hour}:00' for hour in range(10,18)])
        self.assertEqual(response.json()['times'][0]['label'],'10:00 PKT')
        full=self.approved()
        response=self.client.get(url,{'date':self.day,'guests':2,'zone':'quiet'})
        self.assertNotIn('11:00',[row['value'] for row in response.json()['times']])
        invalid=self.client.get(url,{'date':self.day,'guests':2,'zone':'solo'})
        self.assertEqual(invalid.status_code,400)
        self.assertIn('one guest',invalid.json()['message'])
        self.assertEqual(invalid.json()['times'],[])
        result=self.client.post(reverse('core:booking'),self.data(zone='solo'))
        self.assertContains(result,'Solo Space is for one guest')
        self.assertEqual(ReservationRequest.objects.count(),1)
        legacy=ReservationRequest.objects.create(**self.data(zone='solo',email='existing@example.test'))
        result=transition_reservations(ReservationRequest.objects.filter(pk=legacy.pk),'approve_requests')
        self.assertEqual(result.count,0)
        self.assertIn('one guest',result.errors[0])

    def test_no_javascript_availability_check_keeps_details_and_creates_nothing(self):
        token=self.start()
        response=self.client.post(reverse('core:booking'),self.data(action='check_availability',submission_token=token,name='Still typing',time=''))
        self.assertEqual(response.status_code,200)
        form=response.context['reservation_form']
        self.assertFalse(form.is_bound)
        self.assertEqual(form.initial['name'],'Still typing')
        self.assertEqual(form.initial['submission_token'],token)
        self.assertIn(time(11),form.available_times)
        self.assertFalse(ReservationRequest.objects.exists())
        self.assertFalse(Notification.objects.exists())
        response=self.client.post(reverse('core:booking'),self.data(action='check_availability',date=(self.day-timedelta(days=2)).isoformat()))
        self.assertContains(response,'Choose a future date')
        self.assertNotIn('name',response.context['availability_form'].errors)

    def test_past_closed_full_and_race_preserve_entered_details(self):
        url=reverse('core:booking')
        token=self.start()
        past=self.client.post(url,self.data(date=(self.day-timedelta(days=2)).isoformat(),submission_token=token))
        self.assertContains(past,'Choose a future date')
        self.assertContains(past,'Near the books, if possible.')
        closed=self.client.post(url,self.data(time='18:00',submission_token=token))
        self.assertContains(closed,'outside the configured booking hours')
        self.approved()
        full=self.client.post(url,self.data(submission_token=token))
        self.assertContains(full,'cannot accommodate')
        self.assertEqual(full.context['reservation_form']['name'].value(),'Quiet Guest')
        self.assertIn('(unavailable - choose another)',full.content.decode())
        ReservationRequest.objects.all().update(status='cancelled')
        with patch('bookings.views.slot_error', return_value=('time','The slot just became unavailable. Choose another time.')):
            race=self.client.post(url,self.data(submission_token=token))
        self.assertContains(race,'just became unavailable')
        self.assertEqual(ReservationRequest.objects.count(),1)
        self.assertEqual(Notification.objects.count(),0)

    def test_approval_capacity_cancellation_release_and_reference_preservation(self):
        a=self.client.post(reverse('core:booking'),self.data(submission_token=self.start()))
        other=Client()
        b=other.post(reverse('core:booking'),self.data(submission_token=self.start(other)))
        first,second=ReservationRequest.objects.order_by('pk')
        self.assertEqual(transition_reservations(ReservationRequest.objects.filter(pk=first.pk),'approve_requests').count,1)
        self.assertEqual(transition_reservations(ReservationRequest.objects.filter(pk=second.pk),'approve_requests').count,0)
        self.assertNotIn(time(11),available_slots(date=self.day,guests=2,zone='quiet'))
        reference=first.reference
        transition_reservations(ReservationRequest.objects.filter(pk=first.pk),'cancel_reservations','Test release')
        first.refresh_from_db(); stamp=first.cancelled_at
        transition_reservations(ReservationRequest.objects.filter(pk=first.pk),'cancel_reservations','Repeat')
        first.refresh_from_db()
        self.assertEqual((first.reference,first.cancelled_at),(reference,stamp))
        self.assertIn(time(11),available_slots(date=self.day,guests=2,zone='quiet'))
        self.assertContains(self.client.get(a.url),'Cancelled')
        self.assertEqual(transition_reservations(ReservationRequest.objects.filter(pk=second.pk),'approve_requests').count,1)
        self.assertContains(other.get(b.url),'Approved')

    def test_fully_closed_and_full_selection_messages_and_non_hour_hours(self):
        ZoneCapacity.objects.filter(zone='quiet').update(seats=0)
        response=self.client.get(reverse('bookings:availability'),{'date':self.day,'guests':1,'zone':'quiet'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(response.json()['times'],[])
        self.assertIn('not available',response.json()['message'])
        ZoneCapacity.objects.filter(zone='quiet').update(seats=2)
        BookingHours.objects.all().update(opens=time(10,30),closes=time(13,30))
        self.assertEqual(available_slots(date=self.day,guests=1,zone='quiet'),[time(11),time(12)])
        BookingHours.objects.all().delete()
        self.assertEqual(available_slots(date=self.day,guests=1,zone='quiet'),[])

    def test_signed_token_tampering_cross_session_and_csrf_are_rejected(self):
        token=self.start()
        from django.core import signing
        from .submissions import SALT
        self.assertNotIn(self.client.session.session_key, str(signing.loads(token, salt=SALT)))
        response=Client().post(reverse('core:booking'),self.data(submission_token=token))
        self.assertContains(response,'changed browser sessions')
        self.assertEqual(response.context['reservation_form']['name'].value(),'Quiet Guest')
        response=self.client.post(reverse('core:booking'),self.data(submission_token=token+'changed'))
        self.assertContains(response,'form expired')
        self.assertFalse(ReservationRequest.objects.exists())
        csrf=Client(enforce_csrf_checks=True)
        self.assertEqual(csrf.post(reverse('core:booking'),self.data()).status_code,403)
        self.assertEqual(self.client.post(reverse('bookings:availability')).status_code,405)

    def test_availability_uses_pakistan_time_and_excludes_elapsed_slots(self):
        local=timezone.make_aware(datetime.combine(self.day,time(11,15)),timezone.get_default_timezone())
        with patch('bookings.availability.timezone.now',return_value=local):
            self.assertEqual(available_slots(date=self.day,guests=1,zone='reading'),[time(h) for h in range(12,18)])

    def test_expired_saved_token_replays_but_unsent_token_requires_refresh(self):
        import time as clock
        token=self.start()
        payload=self.data(submission_token=token)
        first=self.client.post(reverse('core:booking'),payload)
        later=clock.time()+86402
        with patch('django.core.signing.time.time',return_value=later):
            repeated=self.client.post(reverse('core:booking'),payload)
        self.assertEqual(first.url,repeated.url)
        unsent=self.start()
        with patch('django.core.signing.time.time',return_value=later):
            expired=self.client.post(reverse('core:booking'),self.data(submission_token=unsent))
        self.assertContains(expired,'form expired')
        self.assertEqual(ReservationRequest.objects.count(),1)
