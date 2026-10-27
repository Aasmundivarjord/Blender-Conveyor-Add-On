"""A line along a path of points (contract R21:
`conveyor.new_line(points=...)`). Pure Python; every plan is checked against
model/segments.evaluate_chain before it is returned.

The line starts exactly at the first point, heading for the second, and ends
exactly at the last. A point where the path turns by MERGE_DEG or more is a
corner: it gets a flat curve of a standard inside radius (the type's default;
a smaller catalogue radius where a leg is too short) tangent to both legs.
Smaller turns are merged into one straight run, whose points keep their
heights as points of the run's profile. A height change becomes an incline:
curves stay flat at their corner's height, so a run climbs between the curves
at its ends, and the nose-over arcs the build inserts between two pitches
(model/segments: an arc of the transition radius, added to the chain) are
fitted in as fillets, so the corner heights and the end are met exactly."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .segments import Curve, Incline, Pose, Straight, evaluate_chain, incline_from_rise

MERGE_DEG = 1.0  # smaller turns are merged (contract R21)
SAME_POINT_M = 0.001  # consecutive points closer than this are one point
LATERAL_TOL_M = 0.05  # merged points stay this close to their run's straight line, else the worst becomes a corner
MAX_TURN_DEG = 179.0  # a U-turn on one point needs two corners
MIN_INCLINE_M = 0.05  # an incline shorter than this between its transitions cannot be built
END_TOL_M = 0.002  # the checked end must be this close to the last point
PITCH_TOL_DEG = 0.05


class RouteError(ValueError):
    """A path the line cannot follow; the message is the operator's warning."""


class _TooShort(Exception):
    def __init__(self, run: int, why: str):
        super().__init__(why)
        self.run = run
        self.why = why


@dataclass
class Piece:
    kind: str  # "STRAIGHT" or "CURVE"
    length_m: float = 0.0  # straights: along the slope
    rise_m: float = 0.0  # straights: height gained (+) or lost (-)
    angle_deg: float = 0.0  # curves
    direction: str = "LEFT"  # curves: LEFT = counter-clockwise
    radius_id: str = ""  # curves: the catalogue radius
    inside_radius_m: float = 0.0


@dataclass
class Route:
    start: tuple
    heading: float  # radians, 0 = +Y, counter-clockwise
    pieces: list = field(default_factory=list)
    end: tuple = (0.0, 0.0, 0.0)  # where the checked chain ends
    end_error_m: float = 0.0
    max_pitch_deg: float = 0.0


def heading_of(dx: float, dy: float) -> float:
    """The chain's heading of a plan direction (0 = +Y, counter-clockwise)."""
    return math.atan2(-dx, dy)


def _wrap(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def _plan(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _turn(a, b, c) -> float:
    return _wrap(heading_of(c[0] - b[0], c[1] - b[1]) - heading_of(b[0] - a[0], b[1] - a[1]))


def _lateral(a, b, p) -> float:
    """Plan distance of p from the line through a and b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    return abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / n if n > 1e-12 else _plan(a, p)


def _along(a, b, p) -> float:
    """Plan distance from a of p projected onto the line a -> b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    return ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / n


def clean_points(points) -> tuple[list, list]:
    """(points as float xyz, their 1-based numbers in the caller's list), consecutive duplicates dropped."""
    out, numbers = [], []
    for k, p in enumerate(points):
        q = (float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0)
        if out and math.dist(out[-1], q) < SAME_POINT_M:
            continue
        out.append(q)
        numbers.append(k + 1)
    return out, numbers


def corners_of(pts) -> list[int]:
    """Indices of the points the line turns at, the first and last included."""
    keep = [0] + [i for i in range(1, len(pts) - 1) if abs(math.degrees(_turn(pts[i - 1], pts[i], pts[i + 1]))) >= MERGE_DEG]
    keep.append(len(pts) - 1)
    while True:  # a gentle bend made of many small turns keeps its worst point as a corner
        worst = None
        for a, b in zip(keep, keep[1:]):
            for i in range(a + 1, b):
                d = _lateral(pts[a], pts[b], pts[i])
                if d > LATERAL_TOL_M and (worst is None or d > worst[1]):
                    worst = (i, d)
        if worst is None:
            return keep
        keep = sorted(keep + [worst[0]])


def _run_pieces(run: int, profile, start_flat: bool, end_flat: bool, radius: float):
    """The straight pieces of one run between flat curves (or the line's ends).
    `profile`: [(plan distance, z)], from the end of the curve before to the
    start of the curve after, increasing. Returns [(slope length, pitch rad)]."""
    if all(abs(z - profile[0][1]) < 1e-9 for _s, z in profile):
        run_len = profile[-1][0] - profile[0][0]
        return [(run_len, 0.0)] if run_len > 1e-9 else []
    def _shape(t0: float, t1: float):
        verts = list(profile)
        if start_flat:
            verts[0] = (profile[0][0] + t0, profile[0][1])
        if end_flat:
            verts[-1] = (profile[-1][0] - t1, profile[-1][1])
        if any(b[0] - a[0] <= 1e-9 for a, b in zip(verts, verts[1:])):
            raise _TooShort(run, "too short to climb with its transitions")
        return verts, [math.atan2(b[1] - a[1], b[0] - a[0]) for a, b in zip(verts, verts[1:])]

    t0 = t1 = 0.0
    for _ in range(60):  # the end fillets' tangents depend on the pitches they meet
        _verts, pitches = _shape(t0, t1)
        n0 = radius * math.tan(abs(pitches[0]) / 2.0) if start_flat else 0.0
        n1 = radius * math.tan(abs(pitches[-1]) / 2.0) if end_flat else 0.0
        if abs(n0 - t0) < 1e-12 and abs(n1 - t1) < 1e-12:
            break
        t0, t1 = n0, n1
    verts, pitches = _shape(t0, t1)
    cuts = [t0] + [radius * math.tan(abs(p2 - p1) / 2.0) for p1, p2 in zip(pitches, pitches[1:])] + [t1]
    out = []
    for k, (a, b) in enumerate(zip(verts, verts[1:])):
        length = math.hypot(b[0] - a[0], b[1] - a[1]) - cuts[k] - cuts[k + 1]
        if abs(pitches[k]) > 1e-12 and length < MIN_INCLINE_M:
            raise _TooShort(run, "too short to climb with its transitions")
        if length < -1e-9:
            raise _TooShort(run, "too short for its transitions")
        out.append((max(length, 0.0), pitches[k]))
    return out


def plan_route(points, width_m: float, radii, transition_radius_m: float = 0.0,
               max_pitch_deg: float | None = None, type_label: str = "This conveyor") -> Route:
    """`radii`: [(id, inside radius m)] to try at a corner, the preferred first.
    `max_pitch_deg`: the type's incline limit (None: none; 0: it cannot climb)."""
    pts, numbers = clean_points(points)
    if len(pts) < 2:
        raise RouteError("A line along points needs at least 2 different points")
    for i, (a, b) in enumerate(zip(pts, pts[1:])):
        if _plan(a, b) < SAME_POINT_M:
            raise RouteError(f"Points {numbers[i]} and {numbers[i + 1]} are straight above each other: "
                             "a line cannot climb vertically (use a vertical conveyor or a spiral)")
    if not radii:
        raise RouteError("No curve radius to turn with")
    keep = corners_of(pts)
    K = [pts[i] for i in keep]
    turns = [_turn(K[j - 1], K[j], K[j + 1]) for j in range(1, len(K) - 1)]  # turns[j - 1] at K[j]
    for j, t in enumerate(turns, start=1):
        if abs(math.degrees(t)) > MAX_TURN_DEG:
            raise RouteError(f"Point {numbers[keep[j]]} turns back on itself ({abs(math.degrees(t)):.0f}°): "
                             "a U-turn needs two corners")
    choice = [0] * len(turns)
    while True:
        tangent = [(radii[choice[j]][1] + width_m / 2.0) * math.tan(abs(t) / 2.0) for j, t in enumerate(turns)]
        try:
            runs = []
            for r in range(len(K) - 1):
                a, b = K[r], K[r + 1]
                length = _plan(a, b)
                lo = tangent[r - 1] if r > 0 else 0.0
                hi = length - (tangent[r] if r < len(turns) else 0.0)
                if hi - lo < -1e-9:
                    raise _TooShort(r, "too short for the curves at its ends")
                profile = [(lo, a[2])]
                for i in range(keep[r] + 1, keep[r + 1]):
                    s, z = _along(a, b, pts[i]), pts[i][2]
                    if lo + 1e-6 < s < hi - 1e-6:
                        profile.append((s, z))
                    elif abs(z - (a[2] if s <= lo else b[2])) > 0.001:
                        raise RouteError(f"Point {numbers[i]} lies on a curve, where the line cannot change height")
                profile.append((max(hi, lo), b[2]))
                runs.append(_run_pieces(r, profile, True, r < len(K) - 2, transition_radius_m))
            break
        except _TooShort as e:
            ends = [j for j in (e.run - 1, e.run) if 0 <= j < len(turns) and choice[j] + 1 < len(radii)]
            if not ends:
                a, b = numbers[keep[e.run]], numbers[keep[e.run + 1]]
                raise RouteError(f"The leg from point {a} to point {b} ({_plan(K[e.run], K[e.run + 1]):.2f} m) is {e.why}")
            j = max(ends, key=lambda j: tangent[j])
            choice[j] += 1
    pieces, max_pitch = [], 0.0
    for r, run_pieces in enumerate(runs):
        for length, pitch in run_pieces:
            if length <= 1e-9:
                continue
            pieces.append(Piece("STRAIGHT", length_m=length, rise_m=length * math.sin(pitch)))
            max_pitch = max(max_pitch, abs(math.degrees(pitch)))
            if max_pitch_deg is not None and abs(math.degrees(pitch)) > max_pitch_deg + PITCH_TOL_DEG:
                a, b = numbers[keep[r]], numbers[keep[r + 1]]
                if max_pitch_deg <= 0.0:
                    raise RouteError(f"{type_label} cannot climb: the leg from point {a} to point {b} "
                                     f"changes height by {K[r + 1][2] - K[r][2]:+.2f} m")
                raise RouteError(f"{type_label}: the leg from point {a} to point {b} climbs {abs(math.degrees(pitch)):.1f}° "
                                 f"(limit {max_pitch_deg:.0f}°)")
        if r < len(turns):
            t = turns[r]
            if abs(math.degrees(t)) > 1e-6:
                rid, inside = radii[choice[r]]
                pieces.append(Piece("CURVE", angle_deg=abs(math.degrees(t)), direction="LEFT" if t > 0 else "RIGHT",
                                    radius_id=rid, inside_radius_m=inside))
    heading = heading_of(K[1][0] - K[0][0], K[1][1] - K[0][1])
    route = Route(start=pts[0], heading=heading, pieces=pieces, max_pitch_deg=max_pitch)
    spine = evaluate_chain(model_segments(pieces), Pose(pts[0][0], pts[0][1], pts[0][2], heading, 0.0, 0.0), width_m,
                           transition_radius_m=transition_radius_m)
    route.end = (spine.x[-1], spine.y[-1], spine.z[-1])
    route.end_error_m = math.dist(route.end, pts[-1])
    if route.end_error_m > END_TOL_M:
        raise RouteError(f"The planned line misses the last point by {route.end_error_m * 1000.0:.0f} mm (please report this path)")
    return route


def model_segments(pieces) -> list:
    """The geometry model of the pieces, made the way build_line makes it from
    the pieces' settings (a straight with a rise is an Incline)."""
    out = []
    for p in pieces:
        if p.kind == "CURVE":
            out.append(Curve(p.angle_deg, p.inside_radius_m, p.direction))
        elif abs(p.rise_m) > 1e-9:
            out.append(Incline(incline_from_rise(p.rise_m, p.length_m), p.length_m))
        else:
            out.append(Straight(p.length_m))
    return out
