"""
Contrast in both themes: overlays must read on a light theme (viewport background about 0.95)
as well as on Blender's default dark one. Lifted from the Conveyor add-on 2.12.0 (model/contrast.py) so every
add-on draws its overlays the same way. Pure maths: sRGB luminance, the WCAG contrast ratio and
the overlay palette for a background colour. On a light background overlays draw dark strokes
with a light halo and deep accents; on a dark one light strokes with a dark halo and bright
accents. Text always sits on a box. Strokes keep >= 7:1 and accents >= 3:1 on every dark grey up
to 0.30 (Blender 5.3's default 3D view is 0.239) and on light backgrounds from 0.95 to 1.0.
Reading the background from Blender (the shading's Viewport / World colour, else the theme's
3D view gradient) stays in each add-on's UI code.
"""


def _lin(c):
    c = max(0.0, min(1.0, float(c)))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    """Relative luminance of an sRGB colour (0 black .. 1 white)."""
    r, g, b = (_lin(v) for v in tuple(rgb)[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """WCAG contrast ratio of two sRGB colours (1 .. 21). Text wants >= 4.5, strokes >= 3."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


INK_DARK = (0.07, 0.07, 0.08)
INK_LIGHT = (0.94, 0.94, 0.95)


def is_light(bg):
    """A light background: dark ink reads better on it than light ink."""
    return contrast(bg, INK_DARK) > contrast(bg, INK_LIGHT)


# name: (on a dark background, on a light background), sRGB
ACCENTS = {
    "orange": ((0.95, 0.55, 0.10), (0.68, 0.29, 0.00)),   # the selection, a free end, the active item
    "blue": ((0.45, 0.75, 1.00), (0.05, 0.36, 0.75)),     # docked / linked
    "red": ((1.00, 0.42, 0.36), (0.76, 0.08, 0.06)),      # over capacity, an alert (0.3.1: dark red
                                                          # brightened; 0.95/0.25/0.20 was 2.9:1 on Blender's 0.239)
    "cyan": ((0.30, 0.80, 1.00), (0.00, 0.42, 0.66)),     # hover
    "green": ((0.40, 0.85, 0.40), (0.05, 0.45, 0.12)),    # inbound / OK
}


def accent(name, light):
    return ACCENTS[name][1 if light else 0]


def text_on(fill):
    """Dark or light text, whichever reads better on `fill`."""
    return INK_DARK if contrast(fill, INK_DARK) >= contrast(fill, INK_LIGHT) else INK_LIGHT


def palette(bg):
    """The overlay colours for a viewport background `bg` (sRGB). RGB tuples; `halo` and the
    `box*` entries carry their alpha."""
    light = is_light(bg)
    out = {
        "light": light,
        "stroke": INK_DARK if light else INK_LIGHT,          # 0.3.1: was 0.90 (6.8:1 on a 0.30 grey)
        "halo": (1.0, 1.0, 1.0, 0.85) if light else (0.0, 0.0, 0.0, 0.55),
        "box": (0.985, 0.985, 0.99, 0.94) if light else (0.10, 0.10, 0.11, 0.86),
        "box_hover": (0.84, 0.90, 0.97, 0.97) if light else (0.28, 0.28, 0.30, 0.96),
        "box_edge": (0.35, 0.35, 0.38, 0.85) if light else (0.55, 0.55, 0.58, 0.45),
        "text": INK_DARK if light else INK_LIGHT,
    }
    for name in ACCENTS:
        out[name] = accent(name, light)
    return out
