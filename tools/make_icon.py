"""The listing icon for extensions.blender.org (256 x 256 PNG), drawn with signed distances at 4x
and box-filtered down: an L-shaped roller conveyor turning a corner on a rounded dark tile, two
cartons on it. Pure Python + numpy (Blender's bundled Python has numpy). Not shipped in the zip.
  <Blender>/Contents/Resources/<ver>/python/bin/python3.13 tools/make_icon.py <out.png>"""
import math, struct, sys, zlib
import numpy as np

S = 4                      # supersampling
N = 256 * S
y, x = np.mgrid[0:N, 0:N].astype(np.float64) / S + 0.5 / S   # pixel centres in 256-space


def hexrgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])


def cover(d):              # signed distance (negative inside) -> coverage, ~1 px soft edge
    return np.clip(0.5 - d, 0.0, 1.0)


def rrect(cx, cy, hw, hh, r):
    qx = np.abs(x - cx) - (hw - r)
    qy = np.abs(y - cy) - (hh - r)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


img = np.zeros((N, N, 3))
alpha = np.zeros((N, N))


def paint(cov, col):
    global img, alpha
    c = cov[..., None]
    img = img * (1 - c) + col * c
    alpha = alpha + cov * (1 - alpha)


# Tile: rounded square, vertical gradient
tile = cover(rrect(128, 128, 120, 120, 40))
t = (y - 8) / 240.0
grad = hexrgb("#2A3B57")[None, None, :] * (1 - t[..., None]) + hexrgb("#141B27")[None, None, :] * t[..., None]
img = grad * tile[..., None]
alpha = tile.copy()

# The conveyor's centreline: up from the bottom at x = XC, a quarter turn about (C, C), right at y = YC
XC, YC, C, R = 80.0, 80.0, 156.0, 76.0
W = 30.0                   # half width of the bed


def along_and_across():
    """(distance along the path from its start, signed distance across) for every pixel:
    the piece (vertical leg, quarter turn, horizontal leg) nearest to it."""
    inf = np.full_like(x, np.inf)
    # vertical leg: from (XC, 248) up to (XC, C)
    ok_v = y >= C
    d_v, s_v = x - XC, 248 - y
    # quarter turn about (C, C): pixels in the upper-left quadrant of its centre
    ok_a = (x <= C) & (y <= C)
    ang = np.arctan2(y - C, x - C)
    ang = np.where(ang < 0, ang + 2 * np.pi, ang)
    rad = np.hypot(x - C, y - C)
    d_a, s_a = R - rad, (248 - C) + (ang - np.pi) * R
    # horizontal leg: from (C, YC) right to (248, YC)
    ok_h = x >= C
    d_h, s_h = y - YC, (248 - C) + R * np.pi / 2 + (x - C)
    dv = np.where(ok_v, np.abs(d_v), inf)
    da = np.where(ok_a, np.abs(d_a), inf)
    dh = np.where(ok_h, np.abs(d_h), inf)
    pick_v = (dv <= da) & (dv <= dh)
    pick_h = ~pick_v & (dh <= da)
    s = np.where(pick_v, s_v, np.where(pick_h, s_h, s_a))
    d = np.where(pick_v, d_v, np.where(pick_h, d_h, d_a))
    d = np.where(np.isinf(np.minimum(np.minimum(dv, da), dh)), 1e6, d)
    return s, d


s, d = along_and_across()
inside_tile = rrect(128, 128, 120, 120, 40) < -0.5
bed = cover(np.abs(d) - W) * inside_tile
rail_out = cover(np.abs(d) - (W + 7)) * inside_tile
paint(rail_out, hexrgb("#7C8AA0"))                     # side frames
paint(bed, hexrgb("#C7D0DD"))                          # roller bed
# rollers: thin darker lines across the bed every 13 units along the path
phase = np.mod(s, 13.0)
roller = cover(np.abs(phase - 6.5) - 1.6) * cover(np.abs(d) - (W - 3)) * inside_tile
paint(roller * 0.55, hexrgb("#8E9BB0"))


def carton(cx, cy, rot):
    c, sn = math.cos(rot), math.sin(rot)
    global x, y
    x0, y0 = x, y
    x, y = (x0 - cx) * c + (y0 - cy) * sn + cx, -(x0 - cx) * sn + (y0 - cy) * c + cy
    shadow = cover(rrect(cx + 3, cy + 4, 21, 21, 5))
    box = cover(rrect(cx, cy, 21, 21, 5))
    tape = cover(np.abs(x - cx) - 3.2) * cover(rrect(cx, cy, 21, 21, 5) + 0.0)
    flap = cover(np.abs(y - cy) - 0.9) * cover(rrect(cx, cy, 21, 21, 5))
    x, y = x0, y0
    paint(shadow * 0.35, hexrgb("#0B0F16"))
    paint(box, hexrgb("#F4A63A"))
    paint(flap * 0.6, hexrgb("#C97A1E"))
    paint(tape, hexrgb("#E08A26"))


carton(XC, 196.0, 0.0)              # on the leg coming up
carton(196.0, YC, math.pi / 2)      # on the leg going right
# box-filter down to 256
rgb = img.reshape(256, S, 256, S, 3).mean(axis=(1, 3))
a = alpha.reshape(256, S, 256, S).mean(axis=(1, 3))
# un-premultiply where needed (img already composited over transparent black at the tile edge)
out = np.zeros((256, 256, 4))
safe = np.maximum(a, 1e-6)[..., None]
out[..., :3] = np.where(a[..., None] > 0, rgb / safe, 0)
out[..., 3] = a
px = (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)


def write_png(path, rgba):
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[r].tobytes() for r in range(h))
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    open(path, "wb").write(png)


write_png(sys.argv[1], px)
print("wrote", sys.argv[1])
