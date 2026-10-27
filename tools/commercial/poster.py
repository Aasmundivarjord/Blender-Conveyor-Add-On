"""The listing's featured image ("poster"), 16:9 PNG at the render's size (2560 x 1440): one conveyor line
as the panel builds it (shots.py poster_build), the real Conveyor panel over its lower right, and on the
left the icon, the name, "Build conveyor lines in seconds" and the arrow keys. extensions.blender.org
shows it in its cards at 640 x 360, so the type is large and the text short. Not shipped. Headless:
  Blender -b --factory-startup --python tools/commercial/poster.py -- <render.png> <overlays dir> <panel card.png> <out.png>
"""
import os, struct, sys
import bpy

ARGS = sys.argv[sys.argv.index("--") + 1:]
RENDER, OVER, CARD, OUT = ARGS[:4]
DARK, GREY, ACCENT, WHITE = (0.06, 0.07, 0.09, 1.0), (0.30, 0.33, 0.38, 1.0), (0.23, 0.51, 0.96, 1.0), (1.0, 1.0, 1.0, 1.0)
FONT = bpy.data.fonts.load(os.path.join(bpy.utils.system_resource('DATAFILES'), "fonts", "Inter.woff2"))


def png_size(path):
    with open(path, "rb") as fh:
        return struct.unpack(">II", fh.read(24)[16:24])


W, H = png_size(RENDER)
K = H / 1080.0  # sizes below are for 1080 lines
sc = bpy.context.scene
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
sc.view_settings.view_transform = 'Standard'  # the render is graded already
sc.view_settings.look = 'None'
se = sc.sequence_editor_create()


def image(path, channel, x=0.5, y=0.5, scale=1.0, fit='ORIGINAL'):
    s = se.strips.new_image(name=os.path.basename(path), filepath=path, channel=channel, frame_start=1, fit_method=fit)
    s.blend_type = 'ALPHA_OVER'
    if fit == 'ORIGINAL':
        s.transform.scale_x = s.transform.scale_y = scale
        s.transform.offset_x, s.transform.offset_y = x * W - W / 2, y * H - H / 2
    return s


def text(body, channel, x, y, size, color, bold=False, anchor_x='LEFT', box=None):
    t = se.strips.new_effect(name=body[:20], type='TEXT', channel=channel, frame_start=1, length=1)
    t.text = body.replace("-", "‐")  # Blender's Inter draws "-" as a spaced minus
    t.font, t.font_size, t.use_bold, t.color = FONT, int(size * K), bold, color
    t.anchor_x, t.anchor_y, t.alignment_x = anchor_x, 'TOP' if anchor_x == 'LEFT' else 'CENTER', anchor_x
    t.wrap_width = 0.5
    t.location = (x, y)
    if box is not None:
        t.use_box, t.box_color, t.box_margin, t.box_roundness = True, box, 0.009, 0.6
    return t


image(RENDER, 1, fit='FIT')
image(os.path.join(OVER, "side_scrim.png"), 2, scale=W / 1920.0)
iw, _ih = png_size(os.path.join(OVER, "icon.png"))
image(os.path.join(OVER, "icon.png"), 3, x=0.06 + 0.5 * 140 * K / W, y=0.84, scale=140 * K / iw)
text("Path-Driven\nConveyor\nSystem", 4, 0.06, 0.745, 100, DARK, bold=True)
text("Build conveyor lines in seconds", 5, 0.06, 0.365, 40, GREY)
for i, (glyph, lab) in enumerate((("←", "Curve L"), ("↑", "Straight"), ("→", "Curve R"), ("↓", "More"))):
    x = 0.06 + 0.028 + i * 0.075  # keycaps apart, not touching
    text(f" {glyph} ", 6 + i, x, 0.235, 52, WHITE if glyph == "↑" else DARK, bold=True, anchor_x='CENTER',
         box=ACCENT if glyph == "↑" else (0.97, 0.97, 0.98, 0.95))
    text(lab, 10 + i, x, 0.165, 20, GREY, anchor_x='CENTER')
text("Free and open source  ·  Blender 5.2+", 14, 0.06, 0.11, 30, ACCENT, bold=True)
cw, ch = png_size(CARD)
cs = 0.2 * W / cw
image(CARD, 15, x=0.865, y=0.30, scale=cs)  # the real panel, over the lower right of the render
sc.frame_start = sc.frame_end = 1
sc.render.use_sequencer = True
im = sc.render.image_settings
if hasattr(im, "media_type"):
    im.media_type = 'IMAGE'
im.file_format = 'PNG'
sc.render.filepath = OUT
bpy.ops.render.render(write_still=True)
print("POSTER", W, "x", H, OUT)
