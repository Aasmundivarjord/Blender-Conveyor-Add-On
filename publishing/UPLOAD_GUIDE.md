# Publishing on extensions.blender.org

Everything the listing needs is in this folder; the extension zip is attached to the GitHub
release v2.26.4 (or build it from the tag). Publishing needs a Blender ID, and the extension goes
live only after the moderators approve it. 2.26.4 is the first public release.

## Files

| What | File | Where it goes |
|---|---|---|
| The extension | `conveyor_system-2.26.4.zip` (GitHub release v2.26.4) | Upload page (the zip itself) |
| Icon (256 x 256 PNG) | `icon_256.png` | Listing > Icon |
| Featured image (2560 x 1440, 16:9) | `featured_2560x1440.png` | Listing > Featured image |
| Video preview (MP4, 1920 x 1080, 30 fps) | `previews/conveyor_promo.mp4` | Listing > Previews (put it first) |
| Previews (1920 x 1080) | `previews/00_title.png` ... `07_warehouse.png` | Listing > Previews, in this order |
| Description | `listing_description.md` | Listing > Description (Markdown) |

## Image sizes on the site

The site does not publish a size rule for listing media, but its pages show how they are used
(checked 2026-10-25):
- the add-on cards on https://extensions.blender.org/add-ons/ show 640 x 360 thumbnails (16:9);
- on an add-on's page the gallery thumbnails are 640 x 360 and open 1920 x 1080 versions, and the
  featured image is shown at the top (example: https://extensions.blender.org/add-ons/image-packer/).
So every image here is 16:9: the previews at 1920 x 1080, the featured image at 2560 x 1440 (sharper
on high-density screens), its text large enough to read at 640 x 360.

## Listing fields

- **Name**: Path-Driven Conveyor System (from the manifest)
- **Tagline**: from the manifest
- **Tags**: Geometry Nodes, Modeling, Animation, Object
- **License**: GPL-3.0-or-later (the zip carries the LICENSE text)
- **Blender version**: 5.2.0 and newer (tested on 5.2.3 LTS and 5.3)
- **Platforms**: all (pure Python + Geometry Nodes, nothing compiled)
- **Permissions**: none (no files written, no network)

## Steps

1. Log in at https://extensions.blender.org with your Blender ID.
2. Upload `conveyor_system-2.26.4.zip` at https://extensions.blender.org/submit/. The platform reads
   the name, version, tagline, tags and license from the manifest inside.
3. Fill in the listing: description, icon, featured image, previews (video first).
4. Submit for review; the extension waits in the approval queue until a moderator approves it.

Before uploading, install the zip once yourself (Preferences > Get Extensions > Install from Disk)
in a clean Blender 5.2 to see the first-run experience.

## Notes

- New in 2.26.4: the piece icons carry no file metadata (a render stamp named a local path).
- New in 2.26.3: Edit stands puts a − on every stand and a + in every gap between two stands, so
  single stands can be taken out or added anywhere along the line.
- New in 2.26.2: in build mode Shift + arrows adjust the piece just added (a straight's length, a
  curve's radius and turn) and Ctrl + up / down (Cmd on a Mac) its height.
- New in 2.26.1 (2.26.0 to 2.26.3 were never published):
  - a right-angle transfer with several lines on it: one stand per joint, the lines on its sides
    resting on its frame; one item drawn per stop; goods going straight through a corner ride on
    without stopping; goods set down at the transfer's edge, not over the next line's rollers;
  - the Cleated belt type is retired (saved lines open as a Belt);
  - the Omni-wheel deck is hidden until its redesign (saved lines still open);
  - the pouch sorter looks like the real thing (I-section rail, plastic trolleys with wheels,
    rounded bags, bevelled portal posts).
- Build mode (2.26.0): after New Line at Cursor the plain arrow keys build the line (the listing
  text, the README, the video and the featured image show it).
- Where the media come from:
  - from the tagged 2.26.4 build: the panel cards and the featured image's panel;
  - from the tagged 2.26.1 build: the four 3D shots with a transfer or a 90° junction in them
    (build, split, RAT, warehouse). 2.26.2 to 2.26.4 change only the build-mode keys, the
    stand-editing buttons (stands added by hand only) and icon metadata, no geometry of these shots;
  - from the tagged 2.25.5 build (EEVEE, orthographic): the other shots (height, floors, eyedropper)
    and the featured image's render. Nothing in them changed since: no transfer, no 90° junction,
    no pouch, cleated or omni line.
- The optional hooks for the author's Racks and Floorplan add-ons stay; they do nothing without them.
- Copyright line: "2026 Åsmund Ivarjord". The platform checks that the uploader owns the extension.
