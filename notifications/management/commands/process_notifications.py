from django.core.management.base import BaseCommand
from notifications.services import process_pending


class Command(BaseCommand):
    help = 'Queue due staff reminders and deliver pending emails with bounded retries.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        if options['limit'] < 1:
            raise ValueError('--limit must be positive')
        self.stdout.write(f"Processed {process_pending(options['limit'])} email(s).")
