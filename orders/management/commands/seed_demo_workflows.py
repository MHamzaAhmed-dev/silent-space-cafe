from datetime import time

from django.core.management.base import BaseCommand
from django.db import transaction

from bookings.models import BookingHours, ZoneCapacity
from orders.models import ServiceLocation


class Command(BaseCommand):
    help = 'Create missing DEMO booking hours, capacities and service locations.'

    @transaction.atomic
    def handle(self, *args, **options):
        for weekday in range(7):
            BookingHours.objects.get_or_create(
                weekday=weekday, defaults={'opens': time(10), 'closes': time(18)},
            )
        for zone, seats in [('quiet', 6), ('reading', 4), ('solo', 1)]:
            ZoneCapacity.objects.get_or_create(zone=zone, defaults={'seats': seats})
        for label in ['Demo Table 01', 'Demo Reading Zone']:
            ServiceLocation.objects.get_or_create(label=label)
        self.stdout.write('Demo defaults added where missing. Existing configuration was preserved.')
