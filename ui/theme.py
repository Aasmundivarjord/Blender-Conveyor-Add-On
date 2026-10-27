"""The viewport's background and the drawing helpers every overlay shares
(suite UI rule "contrast in both themes", 2026-10-13): strokes with a halo,
text on a rounded box with an edge. The colours come from _wh.contrast
(warehouse_common) for the background the user actually sees: the shading's own background in
Solid / Wireframe (Viewport colour or World), else the theme's 3D view
gradient."""
from __future__ import annotations

import math

import bpy
from gpu_extras.batch import batch_for_shader

from .._wh import contrast

HALO_PX = 1.5  # each side of a stroke


def viewport_background(context) -> tuple:
    space = getattr(context, "space_data", None)
    shading = getattr(space, "shading", None)
    try:
        if shading is not None and shading.type in ('SOLID', 'WIREFRAME'):
            if shading.background_type == 'VIEWPORT':
                return tuple(shading.background_color)[:3]
            world = getattr(context.scene, "world", None)
            if shading.background_type == 'WORLD' and world is not None:
                return tuple(world.color)[:3]
        grad = context.preferences.themes[0].view_3d.space.gradients
        high = tuple(grad.high_gradient)[:3]
        if grad.background_type == 'SINGLE_COLOR':
            return high
        low = tuple(grad.gradient)[:3]
        return tuple((a + b) / 2.0 for a, b in zip(high, low))
    except Exception:
        return (0.23, 0.23, 0.23)


def palette(context) -> dict:
    return contrast.palette(viewport_background(context))


def sidebar_background(context=None) -> tuple:
    """The side panel's background (where the pictograms sit)."""
    context = context or bpy.context
    try:
        theme = context.preferences.themes[0]
        ui = theme.user_interface
        for owner, name in ((ui, "panel_back"), (getattr(theme.view_3d.space, "panelcolors", None), "back"), (theme.view_3d.space, "button")):
            value = getattr(owner, name, None) if owner is not None else None
            if value is not None:
                rgba = tuple(value)
                if len(rgba) < 4 or rgba[3] > 0.2:
                    return rgba[:3]
    except Exception:
        pass
    return (0.18, 0.18, 0.18)


def rgba(rgb, alpha: float) -> tuple:
    return (rgb[0], rgb[1], rgb[2], alpha)


def stroke(shader, mode: str, coords, rgb_or_rgba, width_px: float, pal: dict, alpha: float = 1.0, scale: float = 1.0) -> None:
    """A polyline with a halo under it (the opposite tone), so it reads on any background."""
    colour = tuple(rgb_or_rgba)
    colour = colour if len(colour) == 4 else rgba(colour, alpha)
    halo = pal["halo"]
    shader.uniform_float("lineWidth", width_px + 2.0 * HALO_PX * scale)
    shader.uniform_float("color", (halo[0], halo[1], halo[2], halo[3] * min(1.0, colour[3] + 0.15)))
    batch_for_shader(shader, mode, {"pos": coords}).draw(shader)
    shader.uniform_float("lineWidth", width_px)
    shader.uniform_float("color", colour)
    batch_for_shader(shader, mode, {"pos": coords}).draw(shader)


def rounded_rect(x0, y0, x1, y1, r):
    """(triangles, outline ring) of a rounded rectangle."""
    r = max(0.0, min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    corners = ((x1 - r, y1 - r, 0.0), (x0 + r, y1 - r, math.pi / 2.0), (x0 + r, y0 + r, math.pi), (x1 - r, y0 + r, 1.5 * math.pi))
    ring = []
    for cx, cy, a0 in corners:
        for k in range(4):
            a = a0 + (math.pi / 2.0) * k / 3.0
            ring.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    c = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
    tris = []
    for a, b in zip(ring, ring[1:] + ring[:1]):
        tris += [c, a, b]
    return tris, ring


def box(fill_shader, line_shader, rect, radius: float, fill, edge=None, scale: float = 1.0) -> None:
    """A label box: the fill, and an edge when one is given (the light theme's near-white boxes need it)."""
    tris, ring = rounded_rect(*rect, radius)
    fill_shader.uniform_float("color", tuple(fill))
    batch_for_shader(fill_shader, 'TRIS', {"pos": tris}).draw(fill_shader)
    if edge is not None and line_shader is not None:
        line_shader.uniform_float("lineWidth", 1.0 * scale)
        line_shader.uniform_float("color", tuple(edge))
        batch_for_shader(line_shader, 'LINE_LOOP', {"pos": ring}).draw(line_shader)


def _glyph(angle_deg: float, arm: float = 0.42, half_w: float = 0.075) -> bytes:
    """A plus (0 deg) or a cross (45 deg) as ONE polygon (no overlap to darken
    under alpha), encoded the way a GIZMO_GT_button_2d `shape` takes it:
    (x, y) bytes over -1..1 of the button's radius, the last point repeated to
    close it."""
    a, w = arm, half_w
    ring = [(a, w), (w, w), (w, a), (-w, a), (-w, w), (-a, w), (-a, -w), (-w, -w), (-w, -a), (w, -a), (w, -w), (a, -w)]
    c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    pts = [(x * c - y * s, x * s + y * c) for x, y in ring]
    pts.append(pts[-1])
    return bytes(max(0, min(255, round((v + 1.0) * 127.5))) for p in pts for v in p)


# Glyphs for buttons that need a clearer mark than the theme's icon ink: with a
# backdrop, Blender draws a shape in black over a light disc and in white over
# a dark one (probed on 5.3, 2026-10-13).
GLYPH_CROSS = _glyph(45.0)
GLYPH_PLUS = _glyph(0.0)
GLYPH_MINUS = bytes(max(0, min(255, round((v + 1.0) * 127.5))) for p in ((0.42, 0.075), (-0.42, 0.075), (-0.42, -0.075), (0.42, -0.075), (0.42, -0.075))
                    for v in p)  # a bar, the plus's arm across


def style_buttons(group, context, accent: str) -> dict:
    """Round gizmo buttons follow the theme. On a light theme a button is a
    light disc with a dark ring -- the label boxes' edge (`box_edge`) as a
    2 px ring over a 15 % fill of it -- so it reads on a near-white viewport;
    on a dark theme a dark disc, like Blender's own navigation buttons.
    Hovered, the theme's accent. A `shape` glyph (GLYPH_CROSS / GLYPH_PLUS)
    is drawn in the opposite ink by Blender itself; an icon keeps the theme's
    icon colour. Returns the palette."""
    pal = palette(context)
    light = pal["light"]
    back = tuple(pal["box_edge"][:3]) if light else (0.12, 0.12, 0.12)
    high = contrast.accent(accent, light)
    for gz in group.gizmos:
        if hasattr(gz, "icon"):  # the button_2d gizmos; not the arrows
            gz.color = back
            gz.color_highlight = high
            gz.backdrop_fill_alpha = 0.15 if light else 1.0
            gz.line_width = 2.0 if light else 1.0
    return pal


def text_colour(fill) -> tuple:
    return rgba(contrast.text_on(fill[:3]), 1.0)
