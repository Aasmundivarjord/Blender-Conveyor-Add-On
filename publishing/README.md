# Publishing material

Everything the add-on's listing needs, kept with the source. None of it is packed into the
extension zip (the manifest excludes this folder).

| What | File |
|---|---|
| Listing description (Markdown) | `listing_description.md` |
| Icon, 256 x 256 | `icon_256.png` |
| Featured image, 2560 x 1440 (16:9) | `featured_2560x1440.png` |
| Video preview, 1920 x 1080, 30 fps | `previews/conveyor_promo.mp4` |
| Previews, 1920 x 1080, in listing order | `previews/00_title.png` ... `previews/07_warehouse.png` |
| Notes for a GitHub release | `RELEASE_NOTES_v2.26.4.md` |
| Step by step for extensions.blender.org | `UPLOAD_GUIDE.md` |

The extension zip itself is attached to the GitHub release (or built from the tag:
`blender --command extension build --source-dir . --output-dir ../dist`).
