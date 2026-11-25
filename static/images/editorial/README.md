# Editorial homepage imagery

The primary visual reference is the supplied **Silent Space Cafe editorial homepage.png**. The implementation uses individual images in real Django templates; the reference is not embedded as a page background or flattened interface.

The existing `../concept-cafe.jpg` remains the hero photograph and decorative booking-banner background. Its existing source is https://images.unsplash.com/photo-1554118811-1e0d58224f24. It is an illustrative stock cafe interior, not a verified photograph of Silent Space.

These six separate WebP assets were AI generated for this redesign, in warm natural light with ivory, walnut, olive and brass styling:

- `quiet-corner.webp`: olive armchair, book, side table and reading lamp.
- `reading-zone.webp`: reading table and bookshelves.
- `solo-space.webp`: private study booth, desk and olive chair.
- `classic-cappuccino.webp`: cappuccino with latte art.
- `rose-latte.webp`: illustrative rose latte.
- `waffle-sandwich.webp`: illustrative savoury waffle sandwich.

They are illustrative replacements, not evidence of actual interiors, product appearance, recipes or ingredients. The page labels their use and supplies descriptive alt text. Replace them with approved cafe/product photography when available. Menu names, descriptions, prices and availability always come from active Django MenuItem records; images never set those values. Unknown menu items now use the neutral cup placeholder described below rather than an invented product photo.

The original generated PNGs remain outside the project in Codex's generated-image library; the page consumes only the optimized project-local WebP files. Each image is at most 900px square and below 205KB. No external image request is needed at page load.

## Full menu additions

The full menu also uses `orange-malt.webp` and `hot-double-chocolate.webp`, generated as separate illustrative product photographs in the same visual style. They are not evidence of actual recipes or presentation.

`bubble-shot.webp` is a locally saved illustrative stock iced-coffee photograph, sourced from https://images.unsplash.com/photo-1461023058943-07fcbe16d735. It is explicitly labelled **Illustrative serving** because the cafe's actual Bubble Shot serving is unverified; the image does not establish its ingredients. Built-in generation of this additional image failed, so a stock replacement was used rather than a fabricated claim about the product.

Uploaded images take precedence over these defaults and use their staff-entered alt text. The shared photo resolver is `menu/presentation.py`. Old and new items without an uploaded photo or a matching default use `../product-placeholder.svg`, a neutral cup icon labelled Photo coming soon. All existing names, prices, availability flags and display order remain database values. Replacing/clearing a photo does not create or delete menu items.
