"""Product upload validation shared by ModelForms and model validation."""
from pathlib import Path

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP'}


def validate_product_image(value):
    # Existing stored photos are not new uploads; allow unrelated edits even if storage is offline.
    if getattr(value, '_committed', False):
        return
    if value.size > MAX_IMAGE_BYTES:
        raise ValidationError('Choose a product photo no larger than 5 MB.', code='image_too_large')
    extension = Path(value.name).suffix.lower()
    if extension not in {'.jpg', '.jpeg', '.png', '.webp'}:
        raise ValidationError('Use a JPEG, PNG or WebP photo. SVG, GIF and other formats are not accepted.', code='image_type')
    position = value.tell()
    try:
        value.seek(0)
        with Image.open(value) as photo:
            if photo.format not in ALLOWED_FORMATS:
                raise ValidationError('The file must contain a real JPEG, PNG or WebP image.', code='image_type')
            if getattr(photo, 'n_frames', 1) != 1:
                raise ValidationError('Use a still product photo; animated images are not accepted.', code='image_animation')
            if photo.width * photo.height > MAX_IMAGE_PIXELS:
                raise ValidationError('Choose a photo with at most 20 megapixels (for example 4000 x 5000).', code='image_dimensions')
            photo.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError('This photo could not be read. Upload a valid JPEG, PNG or WebP image.', code='invalid_image') from exc
    finally:
        value.seek(position)
