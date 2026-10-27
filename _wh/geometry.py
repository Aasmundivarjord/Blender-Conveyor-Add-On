"""
Plan geometry for footprints, obstacles and placement (contract v2.1, R8 and R13).

Polygons are lists of (x, y) in WORLD plan coordinates (frames.polygon_world turns a
`wh_system.footprint` into one). They may be non-convex: a conveyor line publishes its swept
frame. Simple polygons only (no self-intersections); either winding is accepted.
"""

import math

EPS = 1e-9


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------

def signed_area(poly):
    """Positive for counter-clockwise."""
    a = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i][0], poly[i][1]
        x1, y1 = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        a += x0 * y1 - x1 * y0
    return a * 0.5


def is_ccw(poly):
    return signed_area(poly) > 0.0


def ccw(poly):
    """The polygon wound counter-clockwise (the contract's footprint winding)."""
    pts = [(p[0], p[1]) for p in poly]
    return pts if signed_area(pts) >= 0.0 else pts[::-1]


def bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _edges(poly):
    n = len(poly)
    for i in range(n):
        yield (poly[i][0], poly[i][1]), (poly[(i + 1) % n][0], poly[(i + 1) % n][1])


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(p, a, b, eps=EPS):
    if abs(_cross(a, b, p)) > eps * max(1.0, math.hypot(b[0] - a[0], b[1] - a[1])):
        return False
    return (min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps and
            min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps)


def point_on_boundary(p, poly):
    return any(_on_segment(p, a, b) for a, b in _edges(poly))


def point_in_polygon(p, poly, boundary=True):
    """Inside test; a point on the boundary counts as inside when `boundary`."""
    if point_on_boundary(p, poly):
        return boundary
    x, y = p[0], p[1]
    inside = False
    for (x0, y0), (x1, y1) in _edges(poly):
        if (y0 > y) != (y1 > y):
            xc = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if xc > x:
                inside = not inside
    return inside


def point_strictly_inside(p, poly):
    return point_in_polygon(p, poly, boundary=False)


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------

def segments_intersect(a0, a1, b0, b1):
    """True when the closed segments share at least one point (touching counts)."""
    d1, d2 = _cross(b0, b1, a0), _cross(b0, b1, a1)
    d3, d4 = _cross(a0, a1, b0), _cross(a0, a1, b1)
    if ((d1 > EPS and d2 < -EPS) or (d1 < -EPS and d2 > EPS)) and \
       ((d3 > EPS and d4 < -EPS) or (d3 < -EPS and d4 > EPS)):
        return True
    return (_on_segment(a0, b0, b1) or _on_segment(a1, b0, b1) or
            _on_segment(b0, a0, a1) or _on_segment(b1, a0, a1))


def segments_cross_properly(a0, a1, b0, b1):
    """True when the segments cross at one point interior to BOTH (no touching, no overlap)."""
    d1, d2 = _cross(b0, b1, a0), _cross(b0, b1, a1)
    d3, d4 = _cross(a0, a1, b0), _cross(a0, a1, b1)
    return (((d1 > EPS and d2 < -EPS) or (d1 < -EPS and d2 > EPS)) and
            ((d3 > EPS and d4 < -EPS) or (d3 < -EPS and d4 > EPS)))


def point_segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 <= EPS * EPS:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def segment_distance(a0, a1, b0, b1):
    if segments_intersect(a0, a1, b0, b1):
        return 0.0
    return min(point_segment_distance(a0, b0, b1), point_segment_distance(a1, b0, b1),
               point_segment_distance(b0, a0, a1), point_segment_distance(b1, a0, a1))


# ---------------------------------------------------------------------------
# Polygons
# ---------------------------------------------------------------------------

def _interior_point(poly):
    """A point strictly inside a simple polygon (best effort): the midpoint of the widest
    horizontal chord through it, trying a few heights across its bounding box."""
    x0, y0, x1, y1 = bbox(poly)
    for frac in (0.5, 0.37, 0.63, 0.21, 0.79, 0.11, 0.89):
        y = y0 + (y1 - y0) * frac
        xs = []
        for (ax, ay), (bx, by) in _edges(poly):
            if (ay > y) != (by > y):
                xs.append(ax + (y - ay) * (bx - ax) / (by - ay))
        xs.sort()
        best = None
        for i in range(0, len(xs) - 1, 2):
            w = xs[i + 1] - xs[i]
            if w > EPS and (best is None or w > best[0]):
                best = (w, (xs[i] + xs[i + 1]) * 0.5, y)
        if best:
            return best[1], best[2]
    return None


def interiors_overlap(a, b):
    """True when the two polygons share area (touching along an edge or at a point does not
    count). Exact for proper crossings and containment; coincident outlines are caught by
    sample points (edge midpoints and an interior point)."""
    for a0, a1 in _edges(a):
        for b0, b1 in _edges(b):
            if segments_cross_properly(a0, a1, b0, b1):
                return True
    for poly, other in ((a, b), (b, a)):
        for (p0, p1) in _edges(poly):
            if point_strictly_inside(p0, other):
                return True
            mid = ((p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5)
            if point_strictly_inside(mid, other):
                return True
        ip = _interior_point(poly)
        if ip is not None and point_strictly_inside(ip, other):
            return True
    return False


def polygon_distance(a, b):
    """Plan distance between two polygons: 0 when they overlap or touch."""
    if interiors_overlap(a, b):
        return 0.0
    if point_in_polygon(a[0], b) or point_in_polygon(b[0], a):
        return 0.0
    best = float("inf")
    for a0, a1 in _edges(a):
        for b0, b1 in _edges(b):
            d = segment_distance(a0, a1, b0, b1)
            if d < best:
                best = d
                if best == 0.0:
                    return 0.0
    return best


# ---------------------------------------------------------------------------
# R8: conflicts and free placement
# ---------------------------------------------------------------------------

def conflict(fp_a, clearance_a, fp_b, clearance_b):
    """R8: two footprints conflict when they share area, or when the plan distance between
    them is below the larger of their clearances. An obstacle has clearance 0."""
    if interiors_overlap(fp_a, fp_b):
        return True
    need = max(float(clearance_a or 0.0), float(clearance_b or 0.0))
    return need > 0.0 and polygon_distance(fp_a, fp_b) < need - 1e-6


def first_conflict(footprint, clearance, others):
    """The first entry of `others` the footprint conflicts with, else None. Each other is a dict
    {"footprint": world polygon, "clearance_m": float, "container": bool, "linked": bool, ...}.
    Containers hold systems and linked systems are docked to this one: both are skipped (R8).
    Obstacles go in with clearance_m 0 (the caller filters them by level and z first)."""
    for other in others:
        if other.get("container") or other.get("linked"):
            continue
        fp = other.get("footprint")
        if not fp or len(fp) < 3:
            continue
        if conflict(footprint, clearance, fp, other.get("clearance_m", 0.0)):
            return other
    return None


def polygon_inside(inner, outer):
    """True when polygon `inner` lies within `outer` (touching its boundary is allowed);
    `outer` may be non-convex."""
    if not all(point_in_polygon(p, outer) for p in inner):
        return False
    for a0, a1 in _edges(inner):
        mid = ((a0[0] + a1[0]) * 0.5, (a0[1] + a1[1]) * 0.5)
        if not point_in_polygon(mid, outer):
            return False
        for b0, b1 in _edges(outer):
            if segments_cross_properly(a0, a1, b0, b1):
                return False
    return True


def _grown_bbox(poly, d):
    x0, y0, x1, y1 = bbox(poly)
    return x0 - d, y0 - d, x1 + d, y1 + d


def _bboxes_meet(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


_OFFSETS = {}


def _offsets(n):
    """Grid offsets (i, j) with |i|, |j| <= n, nearest first (cached)."""
    if n not in _OFFSETS:
        pts = [(i, j) for i in range(-n, n + 1) for j in range(-n, n + 1)]
        pts.sort(key=lambda ij: (ij[0] * ij[0] + ij[1] * ij[1], abs(ij[1]), -ij[0]))
        _OFFSETS[n] = pts
    return _OFFSETS[n]


def find_nearest_free_location(local_footprint, clearance, others, start, yaw_deg=0.0,
                               step_m=0.5, max_radius_m=40.0, inside=None, max_candidates=20000):
    """R8 free placement, nearest first (contract v2.1, R8 as amended 2026-10-12): the location
    closest to `start`, on a `step_m` grid in every direction, where the system's footprint
    (local, at yaw) conflicts with none of `others` (same dicts as first_conflict). `inside`: a
    world polygon the whole footprint must stay within, normally the container whose outline
    contains `start`, so a rack started in a hall stays in it. Ties prefer +X. Returns (x, y), or
    None when nothing is free within `max_radius_m` / `max_candidates`."""
    from .frames import polygon_world
    prepared = []
    for other in others:
        if other.get("container") or other.get("linked"):
            continue
        fp = other.get("footprint")
        if not fp or len(fp) < 3:
            continue
        need = max(float(clearance or 0.0), float(other.get("clearance_m", 0.0) or 0.0))
        prepared.append((fp, float(other.get("clearance_m", 0.0) or 0.0), _grown_bbox(fp, need)))
    n = max(0, int(max_radius_m / step_m))
    for k, (i, j) in enumerate(_offsets(n)):
        if k >= max_candidates:
            break
        loc = (start[0] + i * step_m, start[1] + j * step_m)
        fp = polygon_world(local_footprint, loc, yaw_deg)
        if inside is not None and not polygon_inside(fp, inside):
            continue
        fbb = bbox(fp)
        free = True
        for ofp, oclr, obb in prepared:
            if _bboxes_meet(fbb, obb) and conflict(fp, clearance, ofp, oclr):
                free = False
                break
        if free:
            return loc
    return None


def find_nearest_free_pose(local_footprint, clearance, others, start, yaws=(0.0, 90.0),
                           step_m=0.5, max_radius_m=40.0, inside=None, max_candidates=20000):
    """As find_nearest_free_location, also trying each heading in `yaws` (the first one is
    preferred at equal distance): a rack that does not fit lengthwise may fit turned 90°.
    Returns (x, y, yaw) or None."""
    from .frames import polygon_world
    prepared = []
    for other in others:
        if other.get("container") or other.get("linked"):
            continue
        fp = other.get("footprint")
        if not fp or len(fp) < 3:
            continue
        need = max(float(clearance or 0.0), float(other.get("clearance_m", 0.0) or 0.0))
        prepared.append((fp, float(other.get("clearance_m", 0.0) or 0.0), _grown_bbox(fp, need)))
    n = max(0, int(max_radius_m / step_m))
    tried = 0
    for i, j in _offsets(n):
        loc = (start[0] + i * step_m, start[1] + j * step_m)
        for yaw in yaws:
            tried += 1
            if tried > max_candidates:
                return None
            fp = polygon_world(local_footprint, loc, yaw)
            if inside is not None and not polygon_inside(fp, inside):
                continue
            fbb = bbox(fp)
            if all(not (_bboxes_meet(fbb, obb) and conflict(fp, clearance, ofp, oclr))
                   for ofp, oclr, obb in prepared):
                return loc[0], loc[1], float(yaw)
    return None


def containing(point, polygons):
    """Index of the first polygon containing the plan point, else None (e.g. which container
    footprint the 3D cursor is in)."""
    for k, poly in enumerate(polygons):
        if poly and len(poly) >= 3 and point_in_polygon(point, poly):
            return k
    return None


def find_free_location(local_footprint, clearance, others, start, yaw_deg=0.0,
                       direction=(1.0, 0.0), step_m=0.5, max_steps=2000):
    """R8 free placement along ONE direction (0.1.x behaviour, kept for callers that want it):
    the first location from `start`, stepping `step_m` along the world `direction`, where the
    footprint conflicts with none of `others`. Prefer find_nearest_free_location: stepping one
    way can walk a system out through a wall. Returns (x, y) or None."""
    from .frames import polygon_world
    dl = math.hypot(direction[0], direction[1]) or 1.0
    ux, uy = direction[0] / dl, direction[1] / dl
    for k in range(max_steps + 1):
        loc = (start[0] + ux * step_m * k, start[1] + uy * step_m * k)
        fp = polygon_world(local_footprint, loc, yaw_deg)
        if first_conflict(fp, clearance, others) is None:
            return loc
    return None


# ---------------------------------------------------------------------------
# R13: obstacles
# ---------------------------------------------------------------------------

def _z_overlap(a0, a1, b0, b1):
    return min(a1, b1) - max(a0, b0) > 1e-6


def segment_enters_polygon(p, q, poly):
    """True when the plan segment p-q passes through the polygon's interior (running along an
    edge or touching a corner does not count)."""
    for a0, a1 in _edges(poly):
        if segments_cross_properly(p, q, a0, a1):
            return True
    if point_strictly_inside(p, poly) or point_strictly_inside(q, poly):
        return True
    mid = ((p[0] + q[0]) * 0.5, (p[1] + q[1]) * 0.5)
    return point_strictly_inside(mid, poly)


def path_obstacle_hits(path, envelope_m, obstacles):
    """R13 for a conveyor: which obstacles a line's centreline crosses. `path` = world
    [(x, y, z), ...] (wh_path through matrix_world); the goods envelope at each segment spans
    z from the lower end up to the higher end + `envelope_m` (load height, 1.0 m without a
    load). `obstacles` = [{"id", "polygon": world, "z0", "z1", ...}]. Returns
    [(obstacle, segment index)], one entry per obstacle (its first crossing)."""
    hits = []
    for ob in obstacles:
        poly = ob.get("polygon")
        if not poly or len(poly) < 3:
            continue
        z0, z1 = float(ob.get("z0", 0.0)), float(ob.get("z1", 1e9))
        for i in range(len(path) - 1):
            p, q = path[i], path[i + 1]
            lo, hi = min(p[2], q[2]), max(p[2], q[2]) + float(envelope_m)
            if _z_overlap(lo, hi, z0, z1) and segment_enters_polygon(p, q, poly):
                hits.append((ob, i))
                break
    return hits


def footprint_obstacle_hits(footprint, z0, z1, obstacles):
    """R13 for a rack or station: obstacles whose polygon shares area with the footprint and
    whose z-range overlaps [z0, z1] (the system's floor to its top)."""
    out = []
    for ob in obstacles:
        poly = ob.get("polygon")
        if not poly or len(poly) < 3:
            continue
        if _z_overlap(z0, z1, float(ob.get("z0", 0.0)), float(ob.get("z1", 1e9))) and \
                interiors_overlap(footprint, poly):
            out.append(ob)
    return out
