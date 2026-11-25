"""Presentation-only imagery; names, prices and availability stay in MenuItem."""
from django import template
from menu.presentation import product_visual

register = template.Library()


@register.filter
def menu_photo(item):
    return product_visual(item)['url']


@register.filter
def menu_photo_alt(item):
    return product_visual(item)['alt']


@register.filter
def menu_photo_label(item):
    return product_visual(item)['label']
