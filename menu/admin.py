from django.contrib import admin
from django.utils.html import format_html
from .models import MenuItem
from .presentation import product_visual


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ['photo_thumbnail', 'name', 'price', 'active', 'display_order']
    list_display_links = ['photo_thumbnail', 'name']
    list_editable = ['price', 'active', 'display_order']
    list_filter = ['active']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['photo_preview']
    fieldsets = (
        (None, {'fields': ('name', 'slug', 'description', 'price', 'active', 'display_order')}),
        ('Product photography', {'fields': ('photo_preview', 'image', 'image_alt'),
            'description': 'Uploaded photos replace default images everywhere. Clear an upload to restore the default or neutral placeholder. Upload a single-frame JPEG, PNG or WebP; descriptions and prices remain separate.'}),
    )

    @admin.display(description='Photo')
    def photo_thumbnail(self, obj):
        visual = product_visual(obj)
        return format_html('<img src="{}" alt="{}" width="64" height="64" style="object-fit:cover;vertical-align:middle">', visual['url'], visual['alt'])

    @admin.display(description='Current photo preview')
    def photo_preview(self, obj):
        if obj is None or not obj.pk:
            return 'Save the item with a photo to see its preview.'
        visual = product_visual(obj)
        return format_html('<div><img src="{}" alt="{}" width="240" height="240" style="max-width:100%;height:auto;object-fit:cover"><p>{}</p></div>',
            visual['url'], visual['alt'], visual['label'])
