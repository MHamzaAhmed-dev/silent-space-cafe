from pathlib import Path
from urllib.parse import urlsplit

import qrcode
from qrcode.image.svg import SvgPathFillImage
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from orders.models import ServiceLocation


class Command(BaseCommand):
    help = 'Write a printable SVG QR for an enabled dine-in service location.'

    def add_arguments(self, parser):
        parser.add_argument('label')
        parser.add_argument('base_url')
        parser.add_argument('output', type=Path)

    def handle(self, *args, **options):
        location = ServiceLocation.objects.filter(label=options['label'], enabled=True).first()
        if not location:
            raise CommandError('Choose an enabled location by its exact label.')
        base = urlsplit(options['base_url'])
        if base.scheme not in ('http', 'https') or not base.hostname or base.username or base.path not in ('', '/') or base.query or base.fragment:
            raise CommandError('Provide an HTTP(S) origin reachable by the phone.')
        url = options['base_url'].rstrip('/') + reverse('orders:scan', args=[location.token])
        try:
            with options['output'].open('xb') as output:
                qrcode.make(url, image_factory=SvgPathFillImage).save(output)
        except FileExistsError as exc:
            raise CommandError('Output already exists. Choose another filename.') from exc
        self.stdout.write(url)
