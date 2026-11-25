from datetime import time, timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import BookingHours, ReservationRequest, ZoneCapacity
from notifications.models import Notification
from notifications.services import enqueue
from orders.models import DineInOrder, OrderLine, ServiceLocation


class DashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.operator = User.objects.create_user('operator', password='test-only', is_staff=True)
        cls.operator.user_permissions.set(Permission.objects.filter(
            content_type__app_label__in=['orders', 'bookings', 'menu', 'notifications'],
            codename__regex=r'^(view|change)_'))
        cls.limited = User.objects.create_user('viewer', password='test-only', is_staff=True)
        cls.limited.user_permissions.add(Permission.objects.get(codename='view_dineinorder'))
        cls.customer = User.objects.create_user('customer', password='test-only')
        cls.location = ServiceLocation.objects.create(label='Reading table 04')
        cls.day = timezone.localdate()+timedelta(days=1)
        BookingHours.objects.create(weekday=cls.day.weekday(), opens=time(10), closes=time(18))
        ZoneCapacity.objects.create(zone='quiet', seats=2)

    def setUp(self):
        self.client.force_login(self.operator)

    def order(self, **overrides):
        data = dict(submission_key=uuid4(), location=self.location, location_label=self.location.label, total=400)
        data.update(overrides)
        order = DineInOrder.objects.create(**data)
        OrderLine.objects.create(order=order, name='Coffee', unit_price=200, quantity=2)
        return order

    def booking(self, **overrides):
        data = dict(name='Guest', email='guest@example.test', phone='03001234567', date=self.day,
                    time=time(11), guests=2, zone='quiet', special_request='A quiet table')
        data.update(overrides)
        return ReservationRequest.objects.create(**data)

    def test_authorized_staff_screens_and_admin_available(self):
        order = self.order(); reservation = self.booking()
        enqueue('new_order', order=order)
        for name in ['overview', 'orders', 'reservations', 'catalogue', 'notifications']:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse('staff:'+name)).status_code, 200)
        self.assertContains(self.client.get(reverse('staff:order_detail', args=[order.pk])), 'Coffee')
        detail = self.client.get(reverse('staff:reservation_detail', args=[reservation.pk]))
        self.assertContains(detail, '03001234567')
        self.assertContains(detail, 'A quiet table')
        self.assertEqual(self.client.get(reverse('admin:menu_menuitem_changelist')).status_code, 200)
        response = self.client.get(reverse('staff:orders'))
        self.assertIn('no-store', response['Cache-Control'])

    def test_anonymous_and_nonstaff_blocked_on_all_routes(self):
        order = self.order(); row = self.booking(); job = enqueue('new_order', order=order)
        reads = [reverse('staff:'+name) for name in ['overview','orders','reservations','catalogue','notifications']]
        reads += [reverse('staff:order_detail', args=[order.pk]), reverse('staff:reservation_detail', args=[row.pk])]
        writes = [reverse('staff:order_action', args=[order.pk]), reverse('staff:reservation_action', args=[row.pk]),
                  reverse('staff:notification_retry', args=[job.pk])]
        self.client.logout()
        for url in reads:
            self.assertRedirects(self.client.get(url), reverse('staff:login')+'?next='+url, fetch_redirect_response=False)
        for url in writes:
            self.assertEqual(self.client.post(url).status_code, 302)
        self.client.force_login(self.customer)
        for url in reads:
            self.assertEqual(self.client.get(url).status_code, 403)
        for url in writes:
            self.assertEqual(self.client.post(url).status_code, 403)

    def test_limited_staff_has_view_only_without_data_leaks(self):
        order = self.order(); row = self.booking(); job = enqueue('new_order', order=order)
        self.client.force_login(self.limited)
        response = self.client.get(reverse('staff:overview'))
        self.assertContains(response, 'New orders')
        self.assertNotContains(response, 'Pending requests')
        self.assertNotContains(response, 'Failed emails')
        detail = self.client.get(reverse('staff:order_detail', args=[order.pk]))
        self.assertContains(detail, 'Coffee')
        self.assertNotContains(detail, 'Start preparing')
        self.assertEqual(self.client.get(reverse('staff:orders')+'?fragment=1').status_code, 200)
        for name in ['reservations', 'notifications', 'catalogue']:
            self.assertEqual(self.client.get(reverse('staff:'+name)).status_code, 403)
        self.assertEqual(self.client.get(reverse('staff:reservation_detail', args=[row.pk])).status_code, 403)
        for name, pk in [('order_action',order.pk), ('reservation_action',row.pk), ('notification_retry',job.pk)]:
            self.assertEqual(self.client.post(reverse('staff:'+name,args=[pk]), {'action':'start_preparing'}).status_code, 403)
        order.refresh_from_db(); self.assertEqual(order.status, 'received')

    def test_change_permission_also_grants_read_access_like_admin(self):
        self.limited.user_permissions.set(Permission.objects.filter(codename='change_reservationrequest'))
        self.client.force_login(self.limited)
        self.assertEqual(self.client.get(reverse('staff:reservations')).status_code, 200)
        row=self.booking()
        self.client.post(reverse('staff:reservation_action',args=[row.pk]), {'action':'approve_requests'})
        row.refresh_from_db(); self.assertEqual(row.status,'approved')

    def test_login_uses_existing_auth_and_rejects_nonstaff_and_external_next(self):
        self.client.logout()
        response=self.client.post(reverse('staff:login'), {'username':'customer','password':'test-only'})
        self.assertContains(response,'A staff account is required.')
        response=self.client.post(reverse('staff:login'), {'username':'operator','password':'test-only','next':'https://evil.example/'})
        self.assertRedirects(response,reverse('staff:overview'))
        self.assertEqual(self.client.get(reverse('staff:logout')).status_code,405)
        self.assertRedirects(self.client.post(reverse('staff:logout')),reverse('staff:login'))

    def test_csrf_and_post_required_for_every_state_change(self):
        order=self.order(); row=self.booking(); job=enqueue('new_order',order=order)
        secure=Client(enforce_csrf_checks=True); secure.force_login(self.operator)
        for name, pk in [('order_action',order.pk),('reservation_action',row.pk),('notification_retry',job.pk)]:
            url=reverse('staff:'+name,args=[pk])
            self.assertEqual(self.client.get(url).status_code,405)
            self.assertEqual(secure.post(url, {'action':'approve_requests'}).status_code,403)

    def test_order_transitions_are_conditional_and_idempotent(self):
        order=self.order(); url=reverse('staff:order_action',args=[order.pk])
        self.client.post(url, {'action':'complete_orders'})
        order.refresh_from_db(); self.assertEqual(order.status,'received')
        self.client.post(url, {'action':'start_preparing'})
        self.client.post(url, {'action':'start_preparing'})
        order.refresh_from_db(); self.assertEqual(order.status,'preparing')
        self.client.post(url, {'action':'complete_orders'})
        order.refresh_from_db(); self.assertEqual(order.status,'completed')
        self.assertEqual(self.client.post(url, {'action':'bogus'}).status_code,400)
        self.assertEqual(DineInOrder.objects.count(),1)

    def test_order_filters_search_and_urgent_sorting(self):
        preparing=self.order(status='preparing')
        first=self.order(location_label='Quiet booth')
        second=self.order(location_label='Reading table 12')
        done=self.order(status='completed')
        url=reverse('staff:orders')
        response=self.client.get(url)
        self.assertEqual([r.pk for r in response.context['page_obj']], [first.pk,second.pk,preparing.pk])
        self.assertEqual(self.client.get(url,{'status':'completed'}).context['page_obj'].object_list[0].pk,done.pk)
        self.assertEqual(self.client.get(url,{'q':'Quiet'}).context['page_obj'].object_list[0].pk,first.pk)
        self.assertEqual(self.client.get(url,{'q':str(second.reference)[:8]}).context['page_obj'].object_list[0].pk,second.pk)
        fragment=self.client.get(url,{'fragment':1,'status':'received','q':'Quiet'})
        self.assertContains(fragment,'Quiet booth'); self.assertNotContains(fragment,'<!doctype')
        self.assertEqual(self.client.get(url,{'status':'bad'}).status_code,400)

    def test_dashboard_approval_capacity_cancellation_and_customer_link(self):
        a=self.booking(); b=self.booking()
        def act(row, action, **extra):
            return self.client.post(reverse('staff:reservation_action',args=[row.pk]), {'action':action,**extra},follow=True)
        act(a,'approve_requests')
        result=act(b,'approve_requests')
        self.assertContains(result,'cannot accommodate')
        b.refresh_from_db(); self.assertEqual(b.status,'pending')
        act(a,'cancel_reservations',reason='Staff requested')
        a.refresh_from_db(); stamp=a.cancelled_at
        act(a,'cancel_reservations',reason='Other')
        a.refresh_from_db(); self.assertEqual(a.cancelled_at,stamp); self.assertEqual(a.cancellation_reason,'Staff requested')
        act(b,'approve_requests'); b.refresh_from_db(); self.assertEqual(b.status,'approved')
        self.assertContains(self.client.get(reverse('bookings:status',args=[a.reference])),'Cancelled')
        self.assertEqual(self.client.post(reverse('staff:reservation_action',args=[a.pk]),{'action':'bad'}).status_code,400)

    def test_dashboard_reject_and_approval_outside_hours(self):
        a=self.booking(time=time(18))
        self.client.post(reverse('staff:reservation_action',args=[a.pk]),{'action':'approve_requests'})
        a.refresh_from_db(); self.assertEqual(a.status,'pending')
        self.client.post(reverse('staff:reservation_action',args=[a.pk]),{'action':'reject_requests'})
        a.refresh_from_db(); self.assertEqual(a.status,'rejected')

    @patch('django.utils.timezone.now', return_value=timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0))
    def test_reservation_filters_and_overview_arrivals(self, clock):
        pending=self.booking(); cancelled=self.booking(status='cancelled'); approved=self.booking(status='approved')
        today=self.booking(date=timezone.localdate(),time=time(23),status='approved')
        url=reverse('staff:reservations')
        for view, expected in [('pending',[pending.pk]),('cancelled',[cancelled.pk]),('today',[today.pk])]:
            response=self.client.get(url,{'view':view})
            self.assertEqual([r.pk for r in response.context['page_obj']],expected)
        response=self.client.get(url,{'view':'upcoming','day':'today'})
        self.assertEqual([r.pk for r in response.context['page_obj']],[today.pk])
        response=self.client.get(url,{'view':'all','q':str(approved.reference)[:8]})
        self.assertEqual(response.context['page_obj'].object_list[0].pk,approved.pk)
        overview=self.client.get(reverse('staff:overview'))
        self.assertEqual(overview.context['pending_count'],1)
        self.assertEqual(overview.context['today_count'],1)
        self.assertEqual(overview.context['next_reservation'].pk,today.pk)

    def test_failed_notification_retry_preserves_state_of_other_jobs(self):
        order=self.order()
        for state in ['failed','sent','pending','processing','skipped']:
            job=Notification.objects.create(event_key=state,kind='new_order',order=order,status=state,attempts=3,last_error='Example error')
            self.client.post(reverse('staff:notification_retry',args=[job.pk]))
            job.refresh_from_db()
            self.assertEqual(job.status,'pending' if state=='failed' else state)
            self.assertEqual(job.attempts,0 if state=='failed' else 3)
            self.assertEqual(job.last_error,'Example error')
        response=self.client.get(reverse('staff:notifications'),{'status':'processing'})
        self.assertEqual(response.context['page_obj'].paginator.count,1)
        self.assertNotContains(response,'Retry delivery')

    def test_pagination_preserves_filters(self):
        for n in range(27): self.order()
        response=self.client.get(reverse('staff:orders'),{'status':'received','q':'Reading','page':2})
        self.assertEqual(len(response.context['page_obj']),2)
        self.assertContains(response,'status=received&amp;q=Reading&amp;page=1')

    def test_admin_recovery_requires_explicit_stopped_worker_confirmation(self):
        job=enqueue('new_order',order=self.order())
        Notification.objects.filter(pk=job.pk).update(status='processing')
        url=reverse('admin:notifications_notification_changelist')
        data={'action':'retry_reviewed','_selected_action':job.pk}
        self.client.post(url,data); job.refresh_from_db(); self.assertEqual(job.status,'processing')
        self.client.post(url,{**data,'workers_stopped':'on'})
        job.refresh_from_db(); self.assertEqual(job.status,'pending')

    def test_view_only_reservations_and_notifications_cannot_change(self):
        self.limited.user_permissions.add(*Permission.objects.filter(codename__in=['view_reservationrequest','view_notification']))
        self.client.force_login(self.limited)
        row=self.booking(status='approved')
        job=enqueue('new_order',order=self.order())
        Notification.objects.filter(pk=job.pk).update(status='failed')
        response=self.client.get(reverse('staff:reservation_detail',args=[row.pk]))
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'Cancel reservation')
        response=self.client.get(reverse('staff:notifications'))
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'Retry delivery')
        self.assertEqual(self.client.post(reverse('staff:reservation_action',args=[row.pk]),{'action':'cancel_reservations'}).status_code,403)
        self.assertEqual(self.client.post(reverse('staff:notification_retry',args=[job.pk])).status_code,403)
        row.refresh_from_db(); job.refresh_from_db()
        self.assertEqual(row.status,'approved'); self.assertEqual(job.status,'failed')
