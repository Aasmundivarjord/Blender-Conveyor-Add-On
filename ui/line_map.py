"""Pictograms for the side panel: schematic icons of the piece kinds
(straight, curves, spiral, transfer, merge, lift, buffer ...) for the
segment list, the value strip and as the fallback of the piece library
(ui/piece_library.py, which prefers rendered pictures).

Drawn with numpy into bpy.utils.previews images (no image files, no GPU
context needed), once per kind. The whole-line map and the close-up of the
two earlier rounds (2026-09-30 .. 10-02) were dropped on 2026-10-05: in a
narrow panel they read as decoration and pushed the controls down; the
viewport carries the drawing now (ui/dimensions.py).
"""
from __future__ import annotations

import math

import bpy
import bpy.utils.previews
import numpy as np

ICON_SIZE = 64

_pcoll = None
_signatures: dict = {}  # picture -> signature of what it shows
_current: dict = {}  # picture -> the preview holding it (a fresh one per redraw)
_versions: dict = {}


# ------------------------------------------------------------- raster

class Canvas:
    """RGBA float image, premultiplied while drawing, rows bottom-up (as
    Blender stores images): (0, 0) is the bottom-left pixel's corner."""

    def __init__(self, width: int, height: int, background=None):
        self.w, self.h = width, height
        self.rgb = np.zeros((height, width, 3), np.float32)
        self.a = np.zeros((height, width), np.float32)
        if background is not None:
            self.rgb[:] = background
            self.a[:] = 1.0

    def _blend(self, y0, y1, x0, x1, cov, color):
        cov = cov[..., None]
        self.rgb[y0:y1, x0:x1] = np.asarray(color, np.float32) * cov + self.rgb[y0:y1, x0:x1] * (1.0 - cov)
        self.a[y0:y1, x0:x1] = cov[..., 0] + self.a[y0:y1, x0:x1] * (1.0 - cov[..., 0])

    def polyline(self, pts, r: float, color, alpha: float = 1.0) -> None:
        """Round-capped stroke of radius r (pixels) through the points,
        anti-aliased; overlapping pieces of one stroke do not double up."""
        if len(pts) < 1:
            return
        pts = np.asarray(pts, np.float32)
        lo = np.floor(pts.min(axis=0) - r - 1).astype(int)
        hi = np.ceil(pts.max(axis=0) + r + 1).astype(int)
        x0, y0 = max(lo[0], 0), max(lo[1], 0)
        x1, y1 = min(hi[0], self.w), min(hi[1], self.h)
        if x1 <= x0 or y1 <= y0:
            return
        cov = np.zeros((y1 - y0, x1 - x0), np.float32)
        segs = [(pts[k], pts[k + 1]) for k in range(len(pts) - 1)] or [(pts[0], pts[0])]
        for a, b in segs:
            sx0 = max(int(math.floor(min(a[0], b[0]) - r - 1)), x0)
            sy0 = max(int(math.floor(min(a[1], b[1]) - r - 1)), y0)
            sx1 = min(int(math.ceil(max(a[0], b[0]) + r + 1)), x1)
            sy1 = min(int(math.ceil(max(a[1], b[1]) + r + 1)), y1)
            if sx1 <= sx0 or sy1 <= sy0:
                continue
            ys, xs = np.mgrid[sy0:sy1, sx0:sx1].astype(np.float32) + 0.5
            d = b - a
            l2 = float(d[0] * d[0] + d[1] * d[1])
            if l2 < 1e-9:
                dist = np.hypot(xs - a[0], ys - a[1])
            else:
                t = np.clip(((xs - a[0]) * d[0] + (ys - a[1]) * d[1]) / l2, 0.0, 1.0)
                dist = np.hypot(xs - (a[0] + t * d[0]), ys - (a[1] + t * d[1]))
            c = np.clip(r + 0.5 - dist, 0.0, 1.0)
            sub = cov[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0]
            np.maximum(sub, c, out=sub)
        self._blend(y0, y1, x0, x1, cov * alpha, color)

    def polygon(self, pts, color, alpha: float = 1.0) -> None:
        """Filled polygon (even-odd), 4x4 supersampled edges."""
        pts = np.asarray(pts, np.float32)
        lo = np.floor(pts.min(axis=0)).astype(int)
        hi = np.ceil(pts.max(axis=0)).astype(int)
        x0, y0 = max(lo[0], 0), max(lo[1], 0)
        x1, y1 = min(hi[0] + 1, self.w), min(hi[1] + 1, self.h)
        if x1 <= x0 or y1 <= y0:
            return
        n = 4
        ys, xs = np.mgrid[y0 * n:y1 * n, x0 * n:x1 * n].astype(np.float32)
        xs, ys = (xs + 0.5) / n, (ys + 0.5) / n
        inside = np.zeros(xs.shape, bool)
        m = len(pts)
        for k in range(m):
            ax, ay = pts[k]
            bx, by = pts[(k + 1) % m]
            cond = (ay > ys) != (by > ys)
            with np.errstate(divide='ignore', invalid='ignore'):
                xint = ax + (ys - ay) * (bx - ax) / (by - ay)
            inside ^= cond & (xs < xint)
        cov = inside.reshape(y1 - y0, n, x1 - x0, n).mean(axis=(1, 3)).astype(np.float32)
        self._blend(y0, y1, x0, x1, cov * alpha, color)

    def disc(self, c, r: float, color, alpha: float = 1.0) -> None:
        self.polyline([c], r, color, alpha)

    def pixels(self) -> np.ndarray:
        """Straight (not premultiplied) RGBA, flat."""
        out = np.empty((self.h, self.w, 4), np.float32)
        safe = np.maximum(self.a, 1e-6)[..., None]
        out[..., :3] = np.clip(self.rgb / safe * (self.a[..., None] > 0), 0.0, 1.0)
        out[..., 3] = self.a
        return out.ravel()


def _preview(name: str, size: int):
    """A FRESH preview for picture `name` (the previous one is released):
    Blender caches an icon's texture by icon id, so a picture redrawn into
    the same preview could keep showing its old pixels. A new preview has a
    new id and is uploaded on first draw."""
    global _pcoll
    if _pcoll is None:
        _pcoll = bpy.utils.previews.new()
    old = _current.get(name)
    if old is not None and old in _pcoll:
        try:
            del _pcoll[old]
        except Exception:
            pass
    _versions[name] = _versions.get(name, 0) + 1
    key = f"{name}#{_versions[name]}"
    pv = _pcoll.new(key)
    pv.image_size = (size, size)
    _current[name] = key
    return pv


def _icon(name: str) -> int:
    return _pcoll[_current[name]].icon_id


def _store(pv, canvas: Canvas) -> int:
    pv.image_pixels_float.foreach_set(canvas.pixels())
    return pv.icon_id


PICTO_FG = (0.92, 0.93, 0.95)  # set per theme by picto(): dark ink on a light side panel
PICTO_ACCENT = (1.0, 0.62, 0.12)


def _theme_colours():
    """(ink, accent, tone) for the side panel's background."""
    from .._wh import contrast
    from .theme import sidebar_background

    light = contrast.is_light(sidebar_background())
    return (contrast.INK_DARK if light else (0.92, 0.93, 0.95)), contrast.accent("orange", light), ("light" if light else "dark")


def _picto(key: str) -> Canvas:
    c = Canvas(ICON_SIZE, ICON_SIZE)
    s = ICON_SIZE / 64.0
    band = 9.0 * s

    def arc(cx, cy, r, a0, a1, n=24):
        return [(cx + r * math.cos(a0 + (a1 - a0) * k / n), cy + r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]

    def arrow(tip, direction, size=9.0):
        dx, dy = direction
        size *= s
        c.polygon([tip, (tip[0] - dx * size - dy * size * 0.6, tip[1] - dy * size + dx * size * 0.6),
                   (tip[0] - dx * size + dy * size * 0.6, tip[1] - dy * size - dx * size * 0.6)], PICTO_ACCENT)

    if key in ('STRAIGHT', 'INCLINE'):
        c.polyline([(10 * s, 32 * s), (54 * s, 32 * s)], band, PICTO_FG)
        for x in (18, 26, 34, 42):
            c.polyline([(x * s, 25 * s), (x * s, 39 * s)], 1.1 * s, (0.35, 0.36, 0.40))
        arrow((60 * s, 32 * s), (1.0, 0.0))
    elif key in ('CURVE_LEFT', 'CURVE_RIGHT', 'CURVE'):
        # In from the bottom heading up, a quarter turn to the left / right.
        left = key != 'CURVE_RIGHT'
        pts = arc((10 if left else 54) * s, 8 * s, 22 * s, 0.0 if left else math.pi, math.pi / 2.0)
        c.polyline(pts, band, PICTO_FG)
        end = pts[-1]
        arrow((end[0] + (-8.0 if left else 8.0) * s, end[1]), (-1.0 if left else 1.0, 0.0))
    elif key == 'SPIRAL':
        for k, r in enumerate((24, 17, 10)):
            c.polyline(arc(32 * s, 30 * s, r * s, 0.2 + k, 2 * math.pi - 0.4 + k), 3.2 * s, PICTO_FG)
        arrow((32 * s, 60 * s), (0.0, 1.0))
    elif key == 'RAT':
        c.polyline([(10 * s, 20 * s), (40 * s, 20 * s)], band, PICTO_FG)
        c.polyline([(40 * s, 20 * s), (40 * s, 50 * s)], band, PICTO_FG)
        for y in (14, 20, 26):
            c.polyline([(33 * s, y * s), (47 * s, y * s)], 1.6 * s, PICTO_ACCENT)
        arrow((40 * s, 61 * s), (0.0, 1.0))
    elif key in ('MERGE', 'DIVERTER'):
        c.polyline([(8 * s, 24 * s), (56 * s, 24 * s)], band, PICTO_FG)
        c.polyline([(14 * s, 56 * s), (34 * s, 30 * s)], band * 0.8, PICTO_FG)
        arrow((60 * s, 24 * s), (1.0, 0.0))
    elif key == 'LIFT':
        c.polyline([(8 * s, 12 * s), (24 * s, 12 * s)], band * 0.8, PICTO_FG)
        c.polyline([(40 * s, 52 * s), (56 * s, 52 * s)], band * 0.8, PICTO_FG)
        c.polyline([(24 * s, 8 * s), (24 * s, 56 * s)], 2.2 * s, PICTO_FG)
        c.polyline([(40 * s, 8 * s), (40 * s, 56 * s)], 2.2 * s, PICTO_FG)
        for y in (20, 32, 44):
            c.polyline([(26 * s, y * s), (38 * s, y * s)], 2.0 * s, PICTO_ACCENT)
        arrow((32 * s, 62 * s), (0.0, 1.0), 7.0)
    elif key == 'BUFFER':
        c.polyline([(8 * s, 28 * s), (56 * s, 28 * s)], band, PICTO_FG)
        for x in (16, 28, 40):
            c.polygon([(x * s - 5 * s, 34 * s), (x * s + 5 * s, 34 * s), (x * s + 5 * s, 44 * s), (x * s - 5 * s, 44 * s)], PICTO_ACCENT)
        c.polyline([(52 * s, 30 * s), (52 * s, 46 * s)], 2.2 * s, (0.95, 0.3, 0.2))
    elif key == 'WRAPPER':
        # A turntable with the chain through it, the mast beside it.
        c.polygon(arc(28 * s, 32 * s, 17 * s, 0.0, 2 * math.pi), PICTO_ACCENT)
        c.polyline([(6 * s, 32 * s), (50 * s, 32 * s)], band * 0.8, PICTO_FG)
        c.polyline([(54 * s, 10 * s), (54 * s, 58 * s)], 3.0 * s, PICTO_FG)
        c.polygon([(46 * s, 36 * s), (54 * s, 36 * s), (54 * s, 48 * s), (46 * s, 48 * s)], PICTO_FG)
        arrow((28 * s, 60 * s), (0.0, 1.0))
    elif key in ('ARB', 'PIVOT'):
        c.polyline([(10 * s, 32 * s), (54 * s, 32 * s)], band, PICTO_FG)
        for x in (18, 28, 38, 48):
            c.polyline([(x * s - 3 * s, 27 * s), (x * s + 3 * s, 37 * s)], 1.6 * s, PICTO_ACCENT)
    else:  # MODULE / anything else
        c.polygon([(12 * s, 18 * s), (52 * s, 18 * s), (52 * s, 46 * s), (12 * s, 46 * s)], PICTO_FG)
        c.polygon([(18 * s, 24 * s), (46 * s, 24 * s), (46 * s, 40 * s), (18 * s, 40 * s)], PICTO_ACCENT)
    return c


PICTO_KEYS = ('STRAIGHT', 'CURVE_LEFT', 'CURVE_RIGHT', 'SPIRAL', 'RAT', 'MERGE', 'DIVERTER', 'LIFT', 'BUFFER', 'ARB', 'WRAPPER', 'MODULE')


def picto(key: str) -> int:
    """Icon id of a piece-kind pictogram (drawn once per theme tone: dark ink on a
    light side panel, light ink on a dark one; redrawn when the theme flips)."""
    global PICTO_FG, PICTO_ACCENT
    name = f"picto:{key}"
    ink, accent, tone = _theme_colours()
    if _signatures.get(name) == tone and _current.get(name) in (_pcoll or {}):
        return _icon(name)
    PICTO_FG, PICTO_ACCENT = ink, accent
    pv = _preview(name, ICON_SIZE)
    canvas = _picto(key)
    pv.icon_size = (32, 32)
    small = canvas.pixels().reshape(ICON_SIZE, ICON_SIZE, 4)[::2, ::2]
    pv.icon_pixels_float.foreach_set(np.ascontiguousarray(small).ravel())
    _signatures[name] = tone
    return _store(pv, canvas)


def picto_for_segment(seg) -> int:
    if seg.kind == 'CURVE':
        return picto('CURVE_LEFT' if seg.curve_direction == 'LEFT' else 'CURVE_RIGHT')
    if seg.kind == 'MODULE':
        return picto(seg.module_kind if seg.module_kind in PICTO_KEYS else 'MODULE')
    return picto(seg.kind if seg.kind in PICTO_KEYS else 'STRAIGHT')


def register():
    global _pcoll
    _pcoll = bpy.utils.previews.new()
    _signatures.clear()
    _current.clear()


def unregister():
    global _pcoll
    if _pcoll is not None:
        bpy.utils.previews.remove(_pcoll)
    _pcoll = None
    _signatures.clear()
    _current.clear()
