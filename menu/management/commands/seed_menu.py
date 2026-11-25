from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify
from menu.models import MenuItem
from menu.seed_data import CATALOGUE


class Command(BaseCommand):
    help = 'Create missing approved menu items; preserve existing staff edits.'

    @transaction.atomic
    def handle(self, *args, **options):
        created = 0
        for order, item in enumerate(CATALOGUE, start=1):
            _, added = MenuItem.objects.get_or_create(
                slug=slugify(item['name']), defaults={**item, 'display_order': order})
            created += added
        self.stdout.write(self.style.SUCCESS(f'Created {created} items; existing items unchanged.'))
