"""One photo resolver for the public menu, homepage, staff list and Admin."""
from django.templatetags.static import static

ILLUSTRATIONS = {
    'classic-cappuccino': ('classic-cappuccino', 'cappuccino with latte art in a ceramic cup'),
    'bubble-shot': ('bubble-shot', 'iced coffee with milk'),
    'waffle-sandwich': ('waffle-sandwich', 'savoury waffle sandwich on a ceramic plate'),
    'orange-malt': ('orange-malt', 'orange drink with ice and a citrus slice'),
    'rose-latte': ('rose-latte', 'pink rose latte with dried rose petals'),
    'hot-double-chocolate': ('hot-double-chocolate', 'hot chocolate with chocolate shavings'),
}


def product_visual(item):
    if item.image:
        return {'url': item.image.url, 'alt': item.image_alt or f'Product photo of {item.name}', 'label': 'Product photo'}
    illustration = ILLUSTRATIONS.get(item.slug)
    if illustration:
        return {'url': static(f'images/editorial/{illustration[0]}.webp'), 'alt': illustration[1],
                'label': ''}
    return {'url': static('images/product-placeholder.svg'),
            'alt': 'Product photo not yet provided', 'label': 'Photo coming soon'}
