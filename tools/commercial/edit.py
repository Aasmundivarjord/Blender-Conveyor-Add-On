"""The promo edit: the rendered shots (tools/commercial/shots.py), the panel cards (ui_capture.py)
and the overlays (overlays.py) cut together in Blender's video editor with titles, keycaps, a
pointer and an eyedropper -- a product-video look. Renders the MP4 and the listing stills.
Not shipped. Headless, CPU:
  Blender -b --factory-startup --python tools/commercial/edit.py -- <shots dir> <cards dir> <overlays dir> <out dir> [video|stills|both|check] [draft] [check frames ...]
"""
import json, os, struct, sys
import bpy

ARGS = sys.argv[sys.argv.index("--") + 1:]
SHOTS, CARDS, OVER, OUT = ARGS[:4]
WHAT = ARGS[4] if len(ARGS) > 4 else "both"
DRAFT = "draft" in ARGS[5:]  # half resolution, for checking the timing
W, H, FPS = 1920, 1080, 30
FADE = 8
DARK = (0.06, 0.07, 0.09, 1.0)
GREY = (0.30, 0.33, 0.38, 1.0)
ACCENT = (0.23, 0.51, 0.96, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)
FONT = bpy.data.fonts.load(os.path.join(bpy.utils.system_resource('DATAFILES'), "fonts", "Inter.woff2"))

sc = bpy.context.scene
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 50 if DRAFT else 100
sc.render.fps, sc.render.fps_base = FPS, 1.0
sc.view_settings.view_transform = 'Standard'  # the shots are graded already (AgX): no second tone curve
sc.view_settings.look = 'None'
se = sc.sequence_editor_create()
STILLS = []  # (frame, name) for the listing previews


def png_size(path):
    """(width, height) from the PNG header: the editor only knows a strip's size once it has drawn it."""
    with open(path, "rb") as fh:
        head = fh.read(24)
    return struct.unpack(">II", head[16:24])


def sidecar(shot):
    with open(os.path.join(SHOTS, f"{shot}.json")) as fh:
        return json.load(fh)


# ---------------------------------------------------------------- strips
def footage(shot, start, src_first, src_last, channel):
    """Frames src_first..src_last (shot frames, 1-based) of a rendered shot, from `start`; a shot
    rendered with a step holds each frame `step` frames."""
    info = sidecar(shot)
    step = info.get("step", 1)
    first = info.get("first", 1)
    folder = os.path.join(SHOTS, shot)
    names = []
    for f in range(src_first, src_last + 1):
        k = (f - first) // step + 1
        k = max(1, min(k, info["frames"]))
        names.append(f"f_{k:04d}.png")
    strip = se.strips.new_image(name=shot, filepath=os.path.join(folder, names[0]), channel=channel, frame_start=start, fit_method='FIT')
    for n in names[1:]:
        strip.elements.append(n)
    strip.blend_type = 'ALPHA_OVER'
    return strip


def fade(strip, frame, a, b, frames=FADE):
    strip.blend_alpha = a
    strip.keyframe_insert("blend_alpha", frame=frame)
    strip.blend_alpha = b
    strip.keyframe_insert("blend_alpha", frame=frame + frames)


def text(body, start, length, x, y, size, color=DARK, bold=False, channel=6, anchor_x='LEFT', anchor_y='TOP', box=None,
         align='LEFT', fade_in=10, fade_out=8, slide=0.012, wrap=0.6, margin=0.012):
    t = se.strips.new_effect(name=body[:20], type='TEXT', channel=channel, frame_start=start, length=length)
    t.text = body.replace("-", "\u2010")  # Blender's Inter draws "-" as a spaced minus
    t.font = FONT
    t.font_size = size
    t.use_bold = bold
    t.color = color
    t.anchor_x, t.anchor_y = anchor_x, anchor_y
    t.alignment_x = align
    t.wrap_width = wrap
    t.location = (x, y)
    if box is not None:
        t.use_box = True
        t.box_color = box
        t.box_margin = margin
        t.box_roundness = 0.6
    if fade_in:
        fade(t, start, 0.0, 1.0, fade_in)
        if slide:
            t.location = (x + slide, y)
            t.keyframe_insert("location", frame=start)
            t.location = (x, y)
            t.keyframe_insert("location", frame=start + fade_in + 4)
    if fade_out:
        t.blend_alpha = 1.0
        t.keyframe_insert("blend_alpha", frame=start + length - fade_out)
        t.blend_alpha = 0.0
        t.keyframe_insert("blend_alpha", frame=start + length - 1)
    return t


def caption(start, length, tag, title, sub, x=0.055, scrim_ch=4, text_ch=6, scrim="scrim.png"):
    """Tag, title and subtitle top left over a soft scrim; a caption cross-fading with another takes other channels."""
    s = se.strips.new_image(name="scrim", filepath=os.path.join(OVER, scrim), channel=scrim_ch, frame_start=start, fit_method='ORIGINAL')
    s.frame_final_duration = length
    s.blend_type = 'ALPHA_OVER'
    fade(s, start, 0.0, 1.0, 10)
    s.blend_alpha = 1.0
    s.keyframe_insert("blend_alpha", frame=start + length - 8)
    s.blend_alpha = 0.0
    s.keyframe_insert("blend_alpha", frame=start + length - 1)
    text(tag.upper(), start + 4, length - 4, x, 0.905, 26, ACCENT, bold=True, channel=text_ch)
    text(title, start + 6, length - 6, x, 0.865, 66, DARK, bold=True, channel=text_ch + 1)
    text(sub, start + 9, length - 9, x, 0.79, 32, GREY, channel=text_ch + 2, wrap=0.5)


def image(path, start, length, channel, x, y, hot=(0.5, 0.5), scale=1.0):
    """An overlay image placed so its hotspot (fractions of the image, from the top-left) sits at
    (x, y) of the frame (0-1, from the bottom-left)."""
    s = se.strips.new_image(name=os.path.basename(path), filepath=path, channel=channel, frame_start=start, fit_method='ORIGINAL')
    s.frame_final_duration = length
    s.blend_type = 'ALPHA_OVER'
    s["size"] = png_size(path)
    place(s, x, y, hot, scale)
    return s


def place(s, x, y, hot=(0.5, 0.5), scale=1.0, frame=None):
    iw, ih = s["size"]
    s.transform.scale_x = s.transform.scale_y = scale
    s.transform.offset_x = x * W - W / 2 - (hot[0] - 0.5) * iw * scale
    s.transform.offset_y = y * H - H / 2 + (hot[1] - 0.5) * ih * scale
    if frame is not None:
        for prop in ("offset_x", "offset_y", "scale_x", "scale_y"):
            s.transform.keyframe_insert(prop, frame=frame)


def card(name, start, length, channel=5, cx=0.835, cy=0.5, width=0.30):
    """A panel card in the right third, sliding in from the right."""
    path = os.path.join(CARDS, f"card_{name}.png")
    s = se.strips.new_image(name=f"card {name}", filepath=path, channel=channel, frame_start=start, fit_method='ORIGINAL')
    s.frame_final_duration = length
    s.blend_type = 'ALPHA_OVER'
    s["size"] = iw, ih = png_size(path)
    scale = min(width * W / iw, 0.82 * H / ih)
    place(s, cx + 0.06, cy, scale=scale, frame=start)
    place(s, cx, cy, scale=scale, frame=start + 12)
    fade(s, start, 0.0, 1.0, 10)
    s.blend_alpha = 1.0
    s.keyframe_insert("blend_alpha", frame=start + length - 8)
    s.blend_alpha = 0.0
    s.keyframe_insert("blend_alpha", frame=start + length - 1)
    return s, scale, (iw, ih)


def card_point(cx, cy, scale, size, px, py):
    """Frame coordinates (0-1) of pixel (px, py) (from the card image's top-left)."""
    iw, ih = size
    return (cx * W + (px - iw / 2) * scale) / W, (cy * H - (py - ih / 2) * scale) / H


def click(start, x, y, channel=10):
    r = image(os.path.join(OVER, "ripple.png"), start, 14, channel, x, y, scale=0.25)
    place(r, x, y, scale=0.15, frame=start)
    place(r, x, y, scale=0.55, frame=start + 13)
    fade(r, start, 1.0, 0.0, 13)


# ---------------------------------------------------------------- the cut
segments = []
t = 1


def segment(shot, src_first, src_last):
    global t
    length = src_last - src_first + 1
    ch = 1 + len(segments) % 2
    start = t if not segments else t - FADE
    s = footage(shot, start, src_first, src_last, ch)
    if segments:
        prev = segments[-1][0]
        if ch > prev.channel:
            fade(s, start, 0.0, 1.0)
        else:
            prev.blend_alpha = 1.0
            prev.keyframe_insert("blend_alpha", frame=start)
            prev.blend_alpha = 0.0
            prev.keyframe_insert("blend_alpha", frame=start + FADE)
    segments.append((s, start, length))
    print("EDIT segment", shot, start, length)
    t = start + length
    return start, length


# 0. intro: the warehouse, the name
start, n = segment("warehouse", 1, 90)
blur = se.strips.new_effect(name="intro blur", type='GAUSSIAN_BLUR', channel=3, frame_start=start, length=n, input1=segments[0][0])
blur.size_x = blur.size_y = 18.0
blur.blend_type = 'ALPHA_OVER'
fade(blur, start + 62, 1.0, 0.0, 24)  # the title leaves, the footage sharpens
veil = se.strips.new_effect(name="intro veil", type='COLOR', channel=4, frame_start=start, length=n)
veil.color = (0.93, 0.94, 0.95)
veil.blend_type = 'ALPHA_OVER'
fade(veil, start + 62, 0.5, 0.0, 24)
text("Path-Driven Conveyor System", start + 10, n - 10, 0.5, 0.60, 92, DARK, bold=True, anchor_x='CENTER', anchor_y='CENTER',
     align='CENTER', slide=0.0, wrap=0.9)
text("Conveyor lines for Blender, built in seconds", start + 18, n - 18, 0.5, 0.51, 40, GREY, anchor_x='CENTER',
     anchor_y='CENTER', align='CENTER', slide=0.0, wrap=0.9)
STILLS.append((start + 60, "00_title"))

# 1. build: keys, the line grows (top view); a second line snaps on
start, n = segment("build", 1, 270)
caption(start, 168, "Build", "Lay out a line in seconds", "Arrow keys for straights and curves, More for RATs and spirals.")
caption(start + 160, n - 160, "Snap", "Lines snap together", "Point a line at another: it docks with a merge.", scrim_ch=3, text_ch=17)
c, sc_card, size = card("build", start, n)
info = sidecar("build")
KEY_STEP, KEY_MARGIN = 0.075, 0.009  # keycaps apart, not touching (as on the poster)
keys = {k: (g, 0.36 + (i - 1.5) * KEY_STEP, lab) for i, (k, g, lab) in
        enumerate((("left", "←", "Curve L"), ("up", "↑", "Straight"), ("right", "→", "Curve R"), ("down", "↓", "More")))}
buttons = {"left": (175, 381), "up": (373, 312), "right": (573, 381), "down": (396, 381)}  # the same buttons on the card (pixels)
for k, (glyph, x, lab) in keys.items():
    text(f" {glyph} ", start + 14, n - 14, x, 0.12, 54, DARK, bold=True, channel=11, anchor_x='CENTER', anchor_y='CENTER',
         align='CENTER', box=(0.97, 0.97, 0.98, 0.95), slide=0.0, margin=KEY_MARGIN)
    text(lab, start + 14, n - 14, x, 0.055, 22, GREY, channel=12, anchor_x='CENTER', anchor_y='CENTER', align='CENTER', slide=0.0)


def new_line_click(fr):
    """The pointer comes in and clicks New Line at Cursor on the card."""
    bx, by = card_point(0.835, 0.5, sc_card, size, 350, 167)
    p = image(os.path.join(OVER, "pointer.png"), fr - 6, 26, 14, bx + 0.06, by - 0.08, hot=(0.04, 0.04))
    place(p, bx + 0.06, by - 0.08, hot=(0.04, 0.04), frame=fr - 6)
    place(p, bx, by, hot=(0.04, 0.04), frame=fr)
    fade(p, fr + 10, 1.0, 0.0, 8)
    click(fr, bx, by)


for f, k in info.get("keys", []):
    key, _sep, what = k.partition(":")
    if key == "new":
        new_line_click(start + f - 1)
    elif key in keys:
        glyph, x, _lab = keys[key]
        text(f" {glyph} ", start + f - 1, 9, x, 0.12, 54, WHITE, bold=True, channel=13, anchor_x='CENTER', anchor_y='CENTER',
             align='CENTER', box=ACCENT, fade_in=0, fade_out=4, slide=0.0, margin=KEY_MARGIN)
        click(start + f - 1, *card_point(0.835, 0.5, sc_card, size, *buttons[key]))
        if what:  # what More added: a pill over the keys
            text(f" {what} ", start + f - 1, 26, x, 0.205, 30, WHITE, bold=True, channel=15, anchor_x='CENTER',
                 anchor_y='CENTER', align='CENTER', box=ACCENT, fade_in=4, fade_out=6, slide=0.0)
snap = info.get("snap") or []
if len(snap) == 3:
    sf, sx, sy = snap
    click(start + sf - 1, sx, sy, channel=16)
    click(start + sf + 5, sx, sy, channel=20)
    text(" Snap ", start + sf - 1, 40, sx + 0.035, sy - 0.05, 30, WHITE, bold=True, channel=15, anchor_x='LEFT', anchor_y='CENTER',
         align='LEFT', box=ACCENT, fade_in=4, fade_out=8, slide=0.0)
STILLS.append((start + 150, "01_build"))
STILLS.append((start + n - 30, "01b_snap"))

# 2. height: drag the arrow
start, n = segment("height", 1, 120)
caption(start, n, "Elevation", "Drag to change the height", "Inclines with nose-overs. The goods ride up with it.")
info = sidecar("height")
pts = info.get("cursor", [])
if pts:
    d0, d1 = info["drag"]
    hnd = image(os.path.join(OVER, "handle.png"), start + 12, n - 24, 14, pts[0][1], pts[0][2], hot=(0.5, 0.9), scale=0.7)
    ptr = image(os.path.join(OVER, "pointer.png"), start + 12, n - 24, 15, pts[0][1], pts[0][2], hot=(0.04, 0.04))
    for f, x, y in pts:
        place(hnd, x, y + 0.03, hot=(0.5, 0.9), scale=0.7, frame=start + f - 1)
        place(ptr, x + 0.004, y + 0.05, hot=(0.04, 0.04), frame=start + f - 1)
STILLS.append((start + n - 15, "02_height"))

# 3. floors: spiral and vertical conveyor
start, n = segment("floors", 1, 150)
caption(start, n, "Levels", "Spirals and vertical conveyors", "Up through every floor. Legs land on the slab below.")
card("spiral", start, n)
STILLS.append((start + n - 20, "03_floors"))

# 4. split
start, n = segment("split", 1, 135)
caption(start, n, "Divert and merge", "Split the flow", "Diverters, angled rollers and right-angle transfers.")
card("diverter", start, n)
STILLS.append((start + n - 20, "04_split"))

# 5. right-angle transfer
start, n = segment("rat", 1, 135)
caption(start, n, "Transfers", "Right-angle transfers", "Each item stops, lifts and leaves at 90 degrees.")
STILLS.append((start + 70, "05_rat"))

# 6. eyedropper
start, n = segment("eyedropper", 1, 150)
caption(start, n, "Your goods", "Carry your own models", "Pick any object with the eyedropper: bins, cartons, letters.")
c, sc_card, size = card("populate", start, n, cy=0.42)
info = sidecar("eyedropper")
bx, by = card_point(0.835, 0.42, sc_card, size, 350, 235)
tx, ty = info.get("target", [0.3, 0.3])
clk = info.get("click", 70)
click(start + 22, bx, by)
eye = image(os.path.join(OVER, "eyedropper.png"), start + 24, clk - 13, 15, bx, by, hot=(0.06, 0.94), scale=0.7)
place(eye, bx, by, hot=(0.06, 0.94), scale=0.7, frame=start + 24)
place(eye, tx, ty, hot=(0.06, 0.94), scale=0.7, frame=start + clk - 6)
fade(eye, start + clk + 2, 1.0, 0.0, 8)
click(start + clk - 2, tx, ty)
STILLS.append((start + n - 10, "06_eyedropper"))

# 7. the whole thing, then the end card
start, n = segment("warehouse", 91, 240)
caption(start, n, "In the warehouse", "Whole systems, in minutes", "Loops, pallets, pick & pack, in and out.",
        scrim="scrim_deep.png")  # the zoom lifts the back wall into the caption
STILLS.append((start + 45, "07_warehouse"))  # early in the zoom: the wall well below the text
end = t - FADE
bg = se.strips.new_effect(name="end", type='COLOR', channel=3, frame_start=end, length=90)
bg.color = (0.86, 0.87, 0.89)
fade(bg, end, 0.0, 1.0, FADE)
icon = image(os.path.join(OVER, "icon.png"), end + 6, 84, 9, 0.5, 0.64, scale=1.1)
fade(icon, end + 6, 0.0, 1.0, 10)
text("Path-Driven Conveyor System", end + 10, 80, 0.5, 0.40, 72, DARK, bold=True, anchor_x='CENTER', anchor_y='CENTER',
     align='CENTER', slide=0.0, wrap=0.9, fade_out=0)
text("Get it on extensions.blender.org", end + 16, 74, 0.5, 0.31, 38, ACCENT, bold=True, anchor_x='CENTER', anchor_y='CENTER',
     align='CENTER', slide=0.0, wrap=0.9, fade_out=0)
text("Free and open source (GPL)  ·  Blender 5.2+", end + 20, 70, 0.5, 0.245, 28, GREY, anchor_x='CENTER', anchor_y='CENTER',
     align='CENTER', slide=0.0, wrap=0.9, fade_out=0)
t = end + 90
sc.frame_start, sc.frame_end = 1, t - 1
print("EDIT", "frames", t - 1, f"{(t - 1) / FPS:.1f} s")

# ---------------------------------------------------------------- render
os.makedirs(OUT, exist_ok=True)
sc.render.use_sequencer = True
if WHAT in ("stills", "both"):
    im = sc.render.image_settings
    if hasattr(im, "media_type"):
        im.media_type = 'IMAGE'
    im.file_format = 'PNG'
    for f, name in STILLS:
        sc.frame_set(f)
        sc.render.filepath = os.path.join(OUT, f"{name}.png")
        bpy.ops.render.render(write_still=True)
    print("EDIT stills", [n for _f, n in STILLS])
if WHAT == "check":  # single frames of the cut, for reviewing the overlay timing
    im = sc.render.image_settings
    if hasattr(im, "media_type"):
        im.media_type = 'IMAGE'
    im.file_format = 'PNG'
    for f in [int(a) for a in ARGS[5:] if a.isdigit()]:
        sc.frame_set(f)
        sc.render.filepath = os.path.join(OUT, f"check_{f:04d}.png")
        bpy.ops.render.render(write_still=True)
if WHAT in ("video", "both"):
    im = sc.render.image_settings
    if hasattr(im, "media_type"):
        im.media_type = 'VIDEO'
    im.file_format = 'FFMPEG'
    ff = sc.render.ffmpeg
    ff.format, ff.codec, ff.constant_rate_factor, ff.ffmpeg_preset, ff.gopsize = 'MPEG4', 'H264', 'HIGH', 'GOOD', 30
    ff.audio_codec = 'NONE'
    sc.render.filepath = os.path.join(OUT, "conveyor_promo.mp4")
    bpy.ops.render.render(animation=True)
    print("EDIT video", sc.render.filepath)
