from pathlib import Path
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from .validators import validate_product_image


def product_image_path(instance, filename):
    return f'menu/products/{uuid4().hex}{Path(filename).suffix.lower()}'


class MenuItem(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    image = models.ImageField(
        upload_to=product_image_path, blank=True, validators=[validate_product_image],
        help_text='Optional JPEG, PNG or WebP photo, up to 5 MB and 20 megapixels. Replaceable without changing the menu item.',
    )
    image_alt = models.CharField(max_length=240, blank=True,
        help_text='Describe the product and meaningful details, e.g. Cappuccino with heart latte art in a ceramic cup. Required when a photo is uploaded.')
    active = models.BooleanField(default=True, verbose_name='Available / visible',
        help_text='When disabled, the item is hidden from the public menu and removed from customer bags. Existing orders are retained.')
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'pk']
        constraints = [models.CheckConstraint(condition=models.Q(price__gte=0), name='menu_price_nonnegative')]

    def clean(self):
        super().clean()
        if self.image and not self.image_alt.strip():
            raise ValidationError({'image_alt': 'Describe this product photo for customers using screen readers.'})

    def __str__(self):
        return self.name
