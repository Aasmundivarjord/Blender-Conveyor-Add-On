"""2D overlay graphics for the promo edit (tools/commercial/edit.py): a pointer, an eyedropper, a
click ripple, a drag handle, and the frame (rounded corners, soft shadow) for the panel cards.
Pure Python + numpy, drawn with signed distances at 4x and box-filtered. Not shipped.
  <Blender python> tools/commercial/overlays.py <out dir> [panel.png ...]"""
import math, os, struct, sys, zlib
import numpy as np

S = 4


def grid(w, h):
    y, x = np.mgrid[0:h * S, 0:w * S].astype(np.float64) / S + 0.5 / S
    return x, y


def cover(d):
    return np.clip(0.5 - d, 0.0, 1.0)


def seg_dist(x, y, ax, ay, bx, by):
    px, py = x - ax, y - ay
    vx, vy = bx - ax, by - ay
    t = np.clip((px * vx + py * vy) / (vx * vx + vy * vy), 0, 1)
    return np.hypot(px - t * vx, py - t * vy)


def poly_inside(x, y, pts):
    """Even-odd fill of a polygon (signed distance sign only, distance to edges for anti-aliasing)."""
    inside = np.zeros_like(x, dtype=bool)
    d = np.full_like(x, np.inf)
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        cond = ((ay > y) != (by > y)) & (x < (bx - ax) * (y - ay) / (by - ay + 1e-12) + ax)
        inside ^= cond
        d = np.minimum(d, seg_dist(x, y, ax, ay, bx, by))
    return np.where(inside, -d, d)


class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.x, self.y = grid(w, h)
        self.rgb = np.zeros((h * S, w * S, 3))
        self.a = np.zeros((h * S, w * S))

    def paint(self, cov, col, alpha=1.0):
        c = (cov * alpha)[..., None]
        self.rgb = self.rgb * (1 - c) + np.array(col) * c
        self.a = self.a + cov * alpha * (1 - self.a)

    def save(self, path):
        rgb = self.rgb.reshape(self.h, S, self.w, S, 3).mean(axis=(1, 3))
        a = self.a.reshape(self.h, S, self.w, S).mean(axis=(1, 3))
        out = np.zeros((self.h, self.w, 4))
        out[..., :3] = np.where(a[..., None] > 0, rgb / np.maximum(a, 1e-6)[..., None], 0)
        out[..., 3] = a
        write_png(path, (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8))


def write_png(path, rgba):
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[r].tobytes() for r in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def read_png(path):
    """8-bit RGBA / RGB PNG reader (enough for Blender's screenshots)."""
    data = open(path, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w = 8, b"", 0
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
        elif tag == b"IDAT":
            idat += body
        pos += 12 + n
    ch = {6: 4, 2: 3}[ctype]
    raw = zlib.decompress(idat)
    stride = w * ch
    img = np.zeros((h, stride), dtype=np.int32)
    prev = np.zeros(stride, dtype=np.int32)
    i = 0
    for r in range(h):
        f = raw[i]
        line = np.frombuffer(raw[i + 1:i + 1 + stride], dtype=np.uint8).astype(np.int32)
        i += 1 + stride
        cur = np.zeros(stride, dtype=np.int32)
        if f == 0:
            cur = line
        elif f == 2:
            cur = (line + prev) & 255
        else:  # Sub (1), Average (3), Paeth (4): per byte
            for k in range(stride):
                a = cur[k - ch] if k >= ch else 0
                b = prev[k]
                c = prev[k - ch] if k >= ch else 0
                if f == 1:
                    p = a
                elif f == 3:
                    p = (a + b) // 2
                else:
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    p = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                cur[k] = (line[k] + p) & 255
        img[r] = cur
        prev = cur
    img = img.reshape(h, w, ch).astype(np.uint8)
    if ch == 3:
        img = np.concatenate([img, np.full((h, w, 1), 255, np.uint8)], axis=2)
    return img


# ---------------------------------------------------------------- shapes
def pointer(path, size=96):
    """A macOS-like arrow pointer: white with a dark outline, tip at the top-left (2, 2)."""
    c = Canvas(size, size)
    k = size / 96.0
    pts = [(4, 4), (4, 74), (22, 58), (34, 86), (46, 81), (34, 54), (58, 54)]
    pts = [(px * k, py * k) for px, py in pts]
    d = poly_inside(c.x, c.y, pts)
    shadow = poly_inside(c.x - 3 * k, c.y - 4 * k, pts)
    c.paint(cover(shadow - 3 * k) * 0.35, (0, 0, 0))
    c.paint(cover(d - 2.6 * k), (0.06, 0.07, 0.09))
    c.paint(cover(d + 1.2 * k), (1, 1, 1))
    c.save(path)


def eyedropper(path, size=128):
    """An eyedropper at 45 degrees, its tip at the bottom-left corner (6, size - 6)."""
    c = Canvas(size, size)
    k = size / 128.0
    tip = (8 * k, 120 * k)
    end = (98 * k, 30 * k)
    d_body = seg_dist(c.x, c.y, 34 * k, 94 * k, 84 * k, 44 * k) - 9 * k
    d_tip = seg_dist(c.x, c.y, tip[0], tip[1], 36 * k, 92 * k) - 3.2 * k
    d_bulb = seg_dist(c.x, c.y, 86 * k, 42 * k, end[0], end[1]) - 16 * k
    shape = np.minimum(np.minimum(d_body, d_tip), d_bulb)
    c.paint(cover(shape - 3 * k), (0.06, 0.07, 0.09))
    c.paint(cover(d_tip + 0.5 * k), (0.85, 0.88, 0.92))
    c.paint(cover(d_body + 1.5 * k), (0.92, 0.94, 0.96))
    c.paint(cover(d_bulb + 1.5 * k), (0.23, 0.51, 0.96))
    c.save(path)


def ripple(path, size=256):
    """A ring for the click ripple (scaled up and faded by the edit)."""
    c = Canvas(size, size)
    r = np.hypot(c.x - size / 2, c.y - size / 2)
    c.paint(cover(np.abs(r - size * 0.40) - size * 0.025), (0.23, 0.51, 0.96))
    c.paint(cover(r - size * 0.12) * 0.5, (0.23, 0.51, 0.96))
    c.save(path)


def handle(path, size=128):
    """The add-on's blue elevation arrow, as a drag handle."""
    c = Canvas(size, size)
    k = size / 128.0
    shaft = seg_dist(c.x, c.y, 64 * k, 112 * k, 64 * k, 40 * k) - 5 * k
    head = poly_inside(c.x, c.y, [(64 * k, 8 * k), (88 * k, 48 * k), (40 * k, 48 * k)])
    shape = np.minimum(shaft, head)
    c.paint(cover(shape - 2.5 * k), (1, 1, 1))
    c.paint(cover(shape + 0.5 * k), (0.23, 0.51, 0.96))
    c.save(path)


def scrim(path, w=1920, h=1080, depth=0.40, colour=(0.86, 0.87, 0.89)):
    """A soft studio-grey gradient from the top-left corner, behind the captions: they stay readable
    when a close-up runs a line through the corner (smooth, so no supersampling)."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    a = np.clip(1.0 - y / (depth * h), 0.0, 1.0) ** 1.5 * np.clip(1.25 - x / (0.65 * w), 0.0, 1.0) ** 0.8
    out = np.zeros((h, w, 4))
    out[..., :3] = colour
    out[..., 3] = np.clip(a * 0.92, 0.0, 1.0)
    write_png(path, (out * 255 + 0.5).astype(np.uint8))


def side_scrim(path, w=1920, h=1080, depth=0.55, colour=(0.86, 0.87, 0.89)):
    """A soft studio-grey gradient from the left edge, behind the poster's name."""
    x = np.tile(np.arange(w, dtype=np.float64), (h, 1))
    out = np.zeros((h, w, 4))
    out[..., :3] = colour
    out[..., 3] = np.clip(1.0 - x / (depth * w), 0.0, 1.0) ** 1.4 * 0.9
    write_png(path, (out * 255 + 0.5).astype(np.uint8))


def card(src, dst, radius=22, pad=40):
    """A panel screenshot as a card: rounded corners and a soft shadow, `pad` px of transparent margin."""
    img = read_png(src).astype(np.float64) / 255.0
    h, w = img.shape[:2]
    W, H = w + 2 * pad, h + 2 * pad
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64) + 0.5

    def rrect(cx, cy, hw, hh, r):
        qx = np.abs(xx - cx) - (hw - r)
        qy = np.abs(yy - cy) - (hh - r)
        return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r

    out = np.zeros((H, W, 4))
    sd = rrect(W / 2, H / 2 + 10, w / 2, h / 2, radius)
    shadow = np.clip(1 - (sd + 2) / 28.0, 0, 1) ** 2 * 0.45
    out[..., 3] = shadow
    inside = np.clip(0.5 - rrect(W / 2, H / 2, w / 2, h / 2, radius), 0, 1)
    region = out[pad:pad + h, pad:pad + w]
    a = inside[pad:pad + h, pad:pad + w][..., None] * img[..., 3:4]
    region[..., :3] = img[..., :3] * a + region[..., :3] * (1 - a)
    region[..., 3:4] = a + region[..., 3:4] * (1 - a)
    out[pad:pad + h, pad:pad + w] = region
    write_png(dst, (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8))


if __name__ == "__main__":
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    pointer(os.path.join(out, "pointer.png"))
    eyedropper(os.path.join(out, "eyedropper.png"))
    ripple(os.path.join(out, "ripple.png"))
    handle(os.path.join(out, "handle.png"))
    scrim(os.path.join(out, "scrim.png"))
    scrim(os.path.join(out, "scrim_deep.png"), depth=0.58)  # a wide shot whose back wall rises into the caption
    side_scrim(os.path.join(out, "side_scrim.png"))
    for src in sys.argv[2:]:
        card(src, os.path.join(out, "card_" + os.path.basename(src)))
    print("OVERLAYS", sorted(os.listdir(out)))
