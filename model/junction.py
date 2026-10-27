"""Merge-junction geometry, pure Python (no bpy), in the MODULE's local
frame: travel +Y, X = right of travel, the module footprint starting at
y = 0, conveying surface z = 0.

A merge junction is a module on the MAIN line with an angled infeed face
on one side. A feeding line ends FLAT against that face (its end face is
the junction's face), so the feeder needs no special geometry at all.
Between the face and the main line's edge the junction carries a wedge
deck with rollers that get progressively longer, and along the wedge's
outer edge a fence tapers back (tangent arc) onto the main line's fence
so goods are funnelled into the main flow.

    theta   approach angle between feeder travel and main travel
            (90 = perpendicular side dock, like a right-angle transfer)
    infeed  feeder frame width D (the face length)
    side    +1 = infeed on the RIGHT of the main line's travel, -1 = LEFT
"""
from __future__ import annotations

import math
from dataclasses import dataclass

CATALOG_ANGLES_DEG = (15, 30, 45, 60, 75, 90)
MIN_ANGLE_DEG = 15  # a shallower wedge is several metres long and reads as a parallel run
ANGLE_STEP_DEG = 15
UPSTREAM_MARGIN_M = 0.0  # the junction starts exactly at the face: as wide along the main line as the docking conveyor
DOWNSTREAM_MARGIN_M = 0.0
TAPER_RADIUS_M = 0.6
TAPER_TAIL_M = 0.10  # taper runs this far along the main fence line past its landing
FENCE_RESUME_M = 0.08  # the main fence resumes this far past the landing (overlaps the tail)
GAP_LEAD_M = 0.05  # the main fence stops this far before the face
TAPER_STEP_RAD = math.radians(5.0)


@dataclass(frozen=True)
class JunctionGeometry:
    length_m: float  # module footprint along the main line
    y_face_start: float  # near corner P1 (on the deck edge)
    y_face_end: float  # far corner P2
    y_landing: float  # where the taper fence meets the main line's fence line (P3)
    y_gap_start: float  # main-line fence opening on the infeed side: from here...
    y_gap_end: float  # ...to here (the taper's tail overlaps the resuming fence)
    face_center: tuple[float, float]  # (x, y) the feeder's end center docks here
    outline: list[tuple[float, float]]  # closed deck outline (first point repeated last)
    fence: list[tuple[float, float, float]]  # taper fence (x, y, heading) from the feeder's outer fence end to the tail
    wedge_across_m: float  # how far the wedge sticks out beyond the deck edge
    connectors: tuple = ()  # short fence pieces joining the main fence to the feeder's fence ends


def snap_angle(theta_deg: float, tolerance_deg: float = 8.0):
    """Nearest catalog angle within tolerance, else None."""
    best = min(CATALOG_ANGLES_DEG, key=lambda a: abs(a - theta_deg))
    return best if abs(best - theta_deg) <= tolerance_deg else None


def snap_step(theta_deg: float, step_deg: float = ANGLE_STEP_DEG) -> int:
    """Nearest multiple of `step_deg`, clamped to [MIN_ANGLE_DEG, 90]: an
    attached line always gets a junction, however it is rotated."""
    step = max(float(step_deg), 1.0)
    return int(max(MIN_ANGLE_DEG, min(90.0, round(theta_deg / step) * step)))


def _heading(ax, ay, bx, by) -> float:
    """Frame-convention heading (forward = (-sin h, cos h)) of the direction A -> B."""
    return math.atan2(-(bx - ax), by - ay)


def junction_geometry(theta_deg: float, infeed_m: float, deck_half_width_m: float, side: int,
                      fence_offset_m: float | None = None, fence_inset_m: float = 0.01) -> JunctionGeometry:
    """`fence_offset_m` is the lateral position of the main line's fence
    (rail center); the taper lands exactly on it so the fence continues
    seamlessly into the next straight. Defaults to the deck edge.
    `fence_inset_m` is how far inside the frame corners the feeder's own
    fences end (half its rail thickness); the junction fences start there."""
    theta = math.radians(theta_deg)
    s = 1.0 if side >= 0 else -1.0
    sin_t, cos_t = math.sin(theta), math.cos(theta)
    x_edge = s * deck_half_width_m
    x_fence = s * (fence_offset_m if fence_offset_m is not None else deck_half_width_m)
    y1 = UPSTREAM_MARGIN_M
    # Face: from the near corner on the deck edge, D long, perpendicular to the
    # feeder travel; it climbs downstream by D sin(theta) and out by D cos(theta).
    p1 = (x_edge, y1)
    p2 = (x_edge + s * infeed_m * cos_t, y1 + infeed_m * sin_t)
    # The feeder's fences end `fence_inset_m` inside the frame corners along the face.
    ux, uy = (p2[0] - p1[0]) / infeed_m, (p2[1] - p1[1]) / infeed_m
    inner_end = (p1[0] + ux * fence_inset_m, p1[1] + uy * fence_inset_m)
    outer_end = (p2[0] - ux * fence_inset_m, p2[1] - uy * fence_inset_m)
    across = abs(outer_end[0]) - abs(x_fence)  # lateral distance from the taper start to the fence line
    # The main fence ends exactly where the feeder's inner fence line meets
    # the main fence line: a clean T-join, no connector stub (the stub read
    # as "a fence profile in the middle of the merge", 2026-09-24).
    dir_x, dir_y = -s * sin_t, cos_t  # feeder travel in the module frame
    if abs(dir_x) > 1e-6:
        t_meet = (x_fence - inner_end[0]) / dir_x
        y_gap_start = inner_end[1] + dir_y * t_meet
    else:
        y_gap_start = inner_end[1]
    connectors: list = []

    # Taper fence from the feeder's outer fence end: heading = feeder heading
    # (theta off the main direction, pointing inward), straight `a`, then an
    # arc of radius R turning onto the main direction, ending exactly on the
    # main fence line.
    fence: list[tuple[float, float, float]] = []
    if across > 1e-6 and sin_t > 1e-6 and cos_t > 1e-6:
        r_max = across / (1.0 - cos_t)
        radius = min(TAPER_RADIUS_M, 0.95 * r_max)
        a = max(0.0, (across - radius * (1.0 - cos_t)) / sin_t)
        # Direction angles in the module plane, measured from +X toward +Y.
        # Feeder travel: inward (-s along x) and downstream: (-s sin(theta), cos(theta)).
        dir_x, dir_y = -s * sin_t, cos_t
        heading_module = math.atan2(-dir_x, dir_y)  # frame convention: forward = (-sin h, cos h)
        pts = [(outer_end[0], outer_end[1], heading_module)]
        q = (outer_end[0] + dir_x * a, outer_end[1] + dir_y * a)
        pts.append((q[0], q[1], heading_module))
        # Arc turning from the feeder heading to the main heading (0). Turning
        # LEFT when the infeed is on the right (s=+1): the center is to the left.
        turn = -s  # +1 = left turn (heading increases)
        # left of the current direction (frame convention): (-cos h, -sin h)
        cx = q[0] + turn * (-math.cos(heading_module)) * radius
        cy = q[1] + turn * (-math.sin(heading_module)) * radius
        steps = max(1, math.ceil(theta / TAPER_STEP_RAD))
        for i in range(1, steps + 1):
            h = heading_module * (1.0 - i / steps)
            px = cx - turn * (-math.cos(h)) * radius
            py = cy - turn * (-math.sin(h)) * radius
            pts.append((px, py, h))
        y3 = pts[-1][1]
        pts.append((x_fence, y3 + TAPER_TAIL_M, 0.0))
        fence = pts
        y_gap_end = y3 + FENCE_RESUME_M
    else:
        # Perpendicular (RAT-style) dock: the feeder's fences end right on the
        # main's deck edge, so the main fence simply stops where they begin
        # and resumes where they end -- no lead, no stubs (they showed up as
        # loose bits of rail at every 90 junction).
        y3 = p2[1]
        y_gap_start = inner_end[1]
        y_gap_end = outer_end[1]
        connectors = []
    # Footprint: the face (plus the taper's tail when there is one), nothing more.
    length = (y3 + TAPER_TAIL_M if fence else p2[1]) + DOWNSTREAM_MARGIN_M
    outline = [(-x_edge, 0.0), (x_edge, 0.0), p1, p2]
    # Deck follows the taper (arc points) but never narrower than the deck edge.
    for px, py, _h in fence[2:-1]:
        outline.append((s * max(abs(px), deck_half_width_m), py))
    outline += [(x_edge, y3), (x_edge, length), (-x_edge, length), (-x_edge, 0.0)]
    face_center = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
    return JunctionGeometry(length, y1, p2[1], y3, y_gap_start, y_gap_end, face_center, outline, fence,
                            abs(infeed_m * cos_t), tuple(connectors))


@dataclass(frozen=True)
class JunctionLayout:
    """One junction module's full layout: one or two infeed faces."""
    length_m: float
    outline: list[tuple[float, float]]  # closed deck outline
    fences: list[list[tuple[float, float, float]]]  # taper fences, one per infeed side
    gaps: list[tuple[float, float, int]]  # (y_start, y_end, side) fence openings
    faces: dict  # side (+1 / -1) -> (x, y) face center
    sides: dict  # side -> JunctionGeometry


def junction_layout(theta_deg: float, infeed_m, deck_half_width_m: float, sides: tuple[int, ...],
                    fence_offset_m: float | None = None, fence_inset_m: float = 0.01) -> JunctionLayout:
    """Layout for infeed on the given sides ((1,), (-1,) or (1, -1)). With
    both sides the deck is the union of both wedges over a common length.
    `infeed_m`: one width for every face, or {side: width} -- each face is
    as wide as the line docking on it (user, 2026-10-10: "the merge
    junction scales with the width of the merged conveyor")."""
    def width(sd):
        return infeed_m[sd] if isinstance(infeed_m, dict) else infeed_m

    geoms = {sd: junction_geometry(theta_deg, width(sd), deck_half_width_m, sd, fence_offset_m, fence_inset_m) for sd in sides}
    length = max(g.length_m for g in geoms.values())
    xe = deck_half_width_m

    def side_points(sd):
        """Outline points of one side's wedge from y = 0 to y = length, in +y order."""
        g = geoms.get(sd)
        if g is None:
            return [(sd * xe, 0.0), (sd * xe, length)]
        pts = [(sd * xe, 0.0)]
        # g.outline = [(-xe,0), (xe,0), p1, p2, arc..., (xe, y3), (xe, L), (-xe, L), (-xe, 0)] for side +1
        # (mirrored x for side -1); take the wedge part between the two straight edges.
        wedge = g.outline[2:-3]  # p1, p2, arc points, (x_edge, y3)
        pts += wedge
        pts.append((sd * xe, length))
        return pts

    right = side_points(1)
    left = side_points(-1)
    outline = [(-xe, 0.0)] + right + [(-xe, length)] + list(reversed(left[1:-1])) + [(-xe, 0.0)]
    fences = [g.fence for g in geoms.values() if g.fence]
    for g in geoms.values():
        fences += [list(c) for c in g.connectors]
    gaps = [(g.y_gap_start, g.y_gap_end, sd) for sd, g in geoms.items()]
    faces = {sd: g.face_center for sd, g in geoms.items()}
    return JunctionLayout(length, outline, fences, gaps, faces, geoms)


def mirror_layout(layout: JunctionLayout) -> JunctionLayout:
    """The outbound twin of a junction: a DIVERTER where a branch line
    leaves the main line. Same wedge and taper, mirrored along the main
    direction (y -> L - y): the taper now opens from the main fence toward
    the branch, and the face sits at the downstream end of the wedge."""
    L = layout.length_m
    outline = [(x, L - y) for x, y in layout.outline]
    fences = [[(x, L - y, -h) for x, y, h in reversed(f)] for f in layout.fences]
    gaps = [(L - y1, L - y0, sd) for y0, y1, sd in layout.gaps]
    faces = {sd: (x, L - y) for sd, (x, y) in layout.faces.items()}
    return JunctionLayout(L, outline, fences, gaps, faces, layout.sides)
