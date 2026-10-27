"""Junctions: a MERGE module lives on the MAIN line (its infeed side and
catalog angle 30/45/60/90 are segment settings); a FEEDING line whose end
aims at a main line snaps onto such a junction with a flat end.

sync_feeder runs at the end of every build_line and on transform changes:
  1. aim: a ray from the feeder's end along its heading (find_target);
  2. snap the feeder's heading to the nearest catalog angle (rotating the
     object about its end point) and fit its end so the near corner of its
     end face sits on the main line's edge: a trailing straight is
     re-lengthened, a curve ending gets a fitted filler straight;
  3. dock: a free junction of the right angle and side near the end is
     used (the feeder is moved onto its face); otherwise a junction is
     inserted into the main line by splitting the straight under it
     (`merge_auto`), and removed again when the feeder leaves.
The junction's own geometry (wedge deck, taper fence, fence opening) is
built by the main line from model/junction.py -- the feeder needs nothing
special, exactly like real catalog merge sections.
"""
from __future__ import annotations

import functools
import math

import bpy
from mathutils import Matrix, Vector

from ..config import loader, units
from ..model import junction, segments as seg_model

_busy = False

RAIL_THICKNESS_M = 0.02  # must match build_line._FRAME_DEFAULTS["Rail Thickness"]


def _reach(context) -> float:
    """Aim reach: scene setting (Scene panel, 'Dock Distance')."""
    return float(context.scene.conveyor_settings.dock_distance_m)
POSITION_TOLERANCE_M = 0.005
MIN_PIECE_MM = 50.0


# ---------------------------------------------------------------- aiming --

def _world_matrix(obj) -> Matrix:
    """`obj.matrix_world` recomputed from the object's own channels. The
    cached matrix is stale until the depsgraph runs, i.e. right after a
    script created or moved the line (create_line builds -- and docks --
    before any update); docking with it moved new lines to wrong places."""
    local = Matrix.LocRotScale(obj.location, obj.rotation_euler, obj.scale)
    if obj.parent is not None:
        return obj.parent.matrix_world @ obj.matrix_parent_inverse @ local
    return local


def _own_point_range(obj) -> tuple[int, int]:
    """[first, stop) of the FULL spline points that belong to the line itself:
    the contiguous block with segment_index >= 0. The docked main lines'
    paths sit before (-2) and/or after (-1) it, whichever end they attach to."""
    cd = obj.data
    n0 = cd.curves[0].points_length if len(cd.curves) else 0
    if "segment_index" not in cd.attributes:
        return 0, n0
    seg_idx = [v.value for v in cd.attributes["segment_index"].data][:n0]
    first = next((i for i, v in enumerate(seg_idx) if v >= 0), n0)
    stop = first
    while stop < n0 and seg_idx[stop] >= 0:
        stop += 1
    return first, stop


def _world_spine(obj, with_incline: bool = False, full: bool = False):
    """GEOMETRIC world polyline of the line with arc lengths, headings (and
    inclines): own points only, arcs from the line's own start -- or the
    whole full spline (`full`) with the stored arc values."""
    cd = obj.data
    first, stop = _own_point_range(obj)
    n0 = cd.curves[0].points_length if len(cd.curves) else 0
    sl = slice(0, n0) if full else slice(first, stop)
    pts = [Vector(v.vector) for v in cd.attributes["position"].data][sl]
    arc = [v.value for v in cd.attributes["arc_len"].data][sl]
    if not full and arc:
        base = arc[0]
        arc = [a - base for a in arc]
    heading = [v.value for v in cd.attributes["heading"].data][sl]
    world = [_world_matrix(obj) @ p for p in pts]
    if with_incline:
        incline = [v.value for v in cd.attributes["incline"].data][sl]
        return world, arc, heading, incline
    return world, arc, heading


def _spine_yaw(obj, full: bool = False) -> list:
    """The items' yaw offset along the line (the turn they did NOT make at a
    right-angle transfer: items ride sideways after it), per spine point,
    in the same order as _world_spine."""
    cd = obj.data
    first, stop = _own_point_range(obj)
    n0 = cd.curves[0].points_length if len(cd.curves) else 0
    sl = slice(0, n0) if full else slice(first, stop)
    if "yaw_offset" not in cd.attributes:
        return [0.0] * len(range(*sl.indices(n0)))
    return [v.value for v in cd.attributes["yaw_offset"].data][sl]


def _flow_yaw(obj, full: bool = False) -> list:
    yaw = _spine_yaw(obj, full)
    return list(reversed(yaw)) if flow_reversed(obj) else yaw


def _yaw_at(arc, yaw, s: float) -> float:
    if not yaw:
        return 0.0
    if s <= arc[0]:
        return yaw[0]
    for i in range(1, len(arc)):
        if arc[i] >= s:
            return yaw[i - 1]  # piecewise constant: the offset changes at a transfer's corner
    return yaw[-1]


def flow_reversed(obj) -> bool:
    """A reversed line runs its goods from the curve's end to its start."""
    return bool(obj.conveyor_line.reverse)


def _flow_spine(obj, with_incline: bool = False, full: bool = False):
    """`_world_spine` in FLOW order with flow arcs (0 at the flow start),
    headings along the flow: a reversed line is mirrored."""
    res = _world_spine(obj, with_incline, full)
    if not flow_reversed(obj):
        return res
    poly, arc, heading = res[0], res[1], res[2]
    total = arc[-1] if arc else 0.0
    poly = list(reversed(poly))
    arc = [total - a for a in reversed(arc)]
    heading = [h + math.pi for h in reversed(heading)]
    if with_incline:
        return poly, arc, heading, [-i for i in reversed(res[3])]
    return poly, arc, heading


def _flow_end(obj, spine):
    """(world point, world flow heading, local point, local flow heading)
    where goods LEAVE this line: its end, or its start when reversed."""
    yaw = obj.rotation_euler.z
    M = _world_matrix(obj)
    if flow_reversed(obj):
        return M @ Vector((0.0, 0.0, 0.0)), yaw + math.pi, Vector((0.0, 0.0, 0.0)), math.pi
    end = spine.pose_at(len(spine) - 1)
    local = Vector((end.x, end.y, end.z))
    return M @ local, yaw + end.heading, local, end.heading


def _flow_start(obj, spine):
    """Where goods ENTER this line: its start, or its end when reversed."""
    yaw = obj.rotation_euler.z
    M = _world_matrix(obj)
    if flow_reversed(obj):
        end = spine.pose_at(len(spine) - 1)
        local = Vector((end.x, end.y, end.z))
        return M @ local, yaw + end.heading + math.pi, local, end.heading + math.pi
    return M @ Vector((0.0, 0.0, 0.0)), yaw, Vector((0.0, 0.0, 0.0)), 0.0


def _rotate_about(obj, local_point: Vector, world_point: Vector, new_yaw: float) -> None:
    """Sets the line's yaw keeping `local_point` at `world_point`."""
    rot = Vector((math.cos(new_yaw) * local_point.x - math.sin(new_yaw) * local_point.y,
                  math.sin(new_yaw) * local_point.x + math.cos(new_yaw) * local_point.y, local_point.z))
    obj.rotation_euler.z = new_yaw
    obj.location = world_point - rot


def _sample_polyline(poly, arc, heading, incline, s: float):
    """Linear interpolation of (point, heading, incline) at arc length s."""
    if s <= arc[0]:
        return poly[0].copy(), heading[0], incline[0]
    for i in range(1, len(poly)):
        if arc[i] >= s:
            span = arc[i] - arc[i - 1]
            t = 0.0 if span <= 1e-12 else (s - arc[i - 1]) / span
            return poly[i - 1].lerp(poly[i], t), heading[i - 1] + (heading[i] - heading[i - 1]) * t, incline[i - 1] + (incline[i] - incline[i - 1]) * t
    return poly[-1].copy(), heading[-1], incline[-1]


CONTINUE_KEYS = ("continue_target", "continue_from", "continue_blend")


def _set_continuation(settings, target, s_from: float, blend: float) -> None:
    settings["continue_target"] = target.name
    settings["continue_from"] = float(s_from)
    settings["continue_blend"] = float(max(blend, 0.3))


def _clear_continuation(settings) -> bool:
    had = any(k in settings for k in CONTINUE_KEYS)
    for k in CONTINUE_KEYS + ("continue_extra_m",):
        if k in settings:
            del settings[k]
    return had


def continuation_for(context, obj, spine, own_length_m: float) -> list[tuple]:
    """The docked feeder's onward path on its target, FLOW-wise, in the
    feeder's local space: (x, y, z, flow heading, incline, flow arc,
    yaw_offset) points with arcs continuing from `own_length_m`. Empty when
    not docked. build_line places them at the right geometric end.

    30/45/60 merges: the goods keep the feeder's direction into the wedge
    and are turned onto the main centerline by the taper (a Hermite blend
    that starts tangent to the feeder and ends parallel to the main over
    the taper length), aligning with the main as they go.

    90 (RAT-style) merges: a right-angle transfer pushes the goods sideways
    without turning them -- the path slides straight to the centerline, then
    follows the main with `yaw_offset` = the 90 deg the item did NOT turn.
    The slide's length is stored as `continue_extra_m` for the shared
    stream (operators/stream.py)."""
    settings = obj.conveyor_line
    name = settings.get("continue_target")
    target = context.scene.objects.get(name) if name else None
    if target is None or len(spine) == 0 or target.type != 'CURVES' or len(target.data.curves) == 0:
        # No continuation: the extra length from an earlier one must not
        # linger -- the group's item spacing is held above every member's
        # `continue_extra_m` (operators/stream.py "lag"), and a line turned
        # from merge to divert kept its old slide (7.8 m on a 90° merge):
        # the whole group's goods thinned out to one item per 8 m.
        settings["continue_extra_m"] = 0.0
        return []
    s_from = float(settings.get("continue_from", 0.0))  # target FULL flow arc of the face center
    blend = float(settings.get("continue_blend", 1.0))
    poly, arc, heading, incline = _flow_spine(target, with_incline=True, full=True)
    if not poly or s_from >= arc[-1] - 1e-6:
        settings["continue_extra_m"] = 0.0
        return []
    yaw_t = target.rotation_euler.z
    yaw_f = obj.rotation_euler.z
    inv = _world_matrix(obj).inverted()
    end_world, h_f_world, _end_local, h_ref = _flow_end(obj, spine)
    q0, h0, _i0 = _sample_polyline(poly, arc, heading, incline, s_from)
    offset = end_world - q0
    offset.z = 0.0
    x0 = offset.length
    delta = _wrap(h_f_world - h0)  # approach angle, signed (target headings are already world flow headings + yaw? no: local)
    out = []

    def local_point(p: Vector, h_world: float, inc: float, s_arc: float, yaw_off: float):
        local = inv @ p
        return (local.x, local.y, local.z, h_ref + _wrap(h_world - h_f_world), inc, s_arc, yaw_off)

    # target headings from _flow_spine are the target's LOCAL flow headings: make them world.
    def h_world_at(h_local: float) -> float:
        return h_local + yaw_t

    delta = _wrap(h_f_world - h_world_at(h0))
    theta = abs(delta)
    right_angle = theta > math.radians(80.0)
    if right_angle:
        steps = 6
        _q, _h, inc0 = _sample_polyline(poly, arc, heading, incline, s_from)
        for k in range(1, steps + 1):
            t = k / steps
            out.append(local_point(end_world - offset * t, h_f_world, inc0, own_length_m + x0 * t, 0.0))
        settings["continue_extra_m"] = x0
        keep = delta  # the turn the item did not make
        for s in [a for a in arc if a > s_from + 1e-6]:
            q, h_t, inc = _sample_polyline(poly, arc, heading, incline, s)
            out.append(local_point(q, h_world_at(h_t), inc, own_length_m + x0 + (s - s_from), keep))
        return out

    # Hermite lateral blend: x(0) = x0 at the face, x'(0) = -tan(theta)
    # (still moving in the feeder's direction), x(L) = 0, x'(L) = 0.
    # Arc lengths are GEOMETRIC (the populate group samples the curve by
    # its true length): the blend path is longer than the main's stretch
    # by `extra`, which the shared stream compensates for after the landing.
    lateral = offset / x0 if x0 > 1e-9 else Vector((0.0, 0.0, 0.0))
    slope = -math.tan(min(theta, math.radians(75.0)))
    n = 12
    pts = []
    for k in range(1, n + 1):
        t = k / n
        s = s_from + blend * t
        if s >= arc[-1]:
            break
        h00 = 2 * t ** 3 - 3 * t ** 2 + 1
        h10 = t ** 3 - 2 * t ** 2 + t
        x = max(x0 * h00 + blend * slope * h10, 0.0)
        q, h_t, inc = _sample_polyline(poly, arc, heading, incline, s)
        pts.append((q + lateral * x, h_world_at(h_t), inc, s))
    prev = end_world
    cum = 0.0
    s_land = s_from
    for i, (p, h_main, inc, s) in enumerate(pts):
        cum += (p - prev).length
        s_land = s
        nxt = pts[i + 1][0] if i + 1 < len(pts) else None
        d = (nxt - prev) if nxt is not None else (p - prev)
        # Heading convention: 0 = +y, a left turn increases it -> atan2(-dx, dy).
        h_move = math.atan2(-d.x, d.y) if d.length > 1e-9 else h_main
        h_move = h_main + _wrap(h_move - h_main)
        out.append(local_point(p, h_move if i + 1 < len(pts) else h_main, inc, own_length_m + cum, 0.0))
        prev = p
    extra = cum - (s_land - s_from)
    settings["continue_extra_m"] = extra
    for s in [a for a in arc if a > s_land + 1e-6]:
        q, h_t, inc = _sample_polyline(poly, arc, heading, incline, s)
        out.append(local_point(q, h_world_at(h_t), inc, own_length_m + extra + (s - s_from), 0.0))
    return out


BRANCH_KEYS = ("branch_target", "branch_from", "branch_blend", "branch_keep_yaw", "branch_slide")
RIGHT_ANGLE_DEG = 80  # a dock at least this steep is a right-angle transfer: the goods slide sideways, unturned


def _set_branch(settings, target, s_from: float, blend: float, keep_yaw: float = 0.0) -> None:
    """`blend` 0 = right-angle divert (no lateral blend: the goods ride to
    the divert centre, then slide straight out); `keep_yaw` = the turn the
    goods do NOT make there, carried by the whole branch (its items ride
    sideways, like off a real pop-up transfer)."""
    settings["branch_target"] = target.name
    settings["branch_from"] = float(s_from)
    settings["branch_blend"] = 0.0 if blend <= 1e-9 else float(max(blend, 0.3))
    settings["branch_keep_yaw"] = float(keep_yaw)


def _clear_branch(settings) -> bool:
    had = any(k in settings for k in BRANCH_KEYS)
    for k in BRANCH_KEYS:
        if k in settings:
            del settings[k]
    return had


def prefix_for(context, obj, spine) -> tuple[list[tuple], float]:
    """(points, shift) of a routed branch's path BEFORE its flow start,
    FLOW-wise in its local space: the main line's full flow path from its
    start up to the switch point, then a lateral blend from the main's
    centerline onto the branch's flow start (the diverter face center) over
    `branch_blend`. The branch's own flow arcs are shifted by `shift` (= the
    face center's flow arc on the main) so both lines run one item stream.
    ([], 0) when not docked on a diverter."""
    settings = obj.conveyor_line
    name = settings.get("branch_target")
    target = context.scene.objects.get(name) if name else None
    if target is None or len(spine) == 0 or target.type != 'CURVES' or len(target.data.curves) == 0:
        return [], 0.0
    s_div = float(settings.get("branch_from", 0.0))
    blend = float(settings.get("branch_blend", 1.0))
    keep = float(settings.get("branch_keep_yaw", 0.0))
    poly, arc, heading, incline = _flow_spine(target, with_incline=True, full=True)
    if not poly or s_div <= arc[0] + 1e-6:
        return [], 0.0
    yaw_t = target.rotation_euler.z
    inv = _world_matrix(obj).inverted()
    start_world, h_s_world, _sl, h_ref = _flow_start(obj, spine)
    q_div, h_div, inc_div = _sample_polyline(poly, arc, heading, incline, s_div)
    offset = start_world - q_div
    offset.z = 0.0
    if blend <= 1e-9:
        # Right-angle divert (pop-up belts / wheels / chain): the goods ride
        # the main to the divert centre, then slide straight out to the face
        # keeping their orientation (yaw = the turn not made), and ride the
        # branch sideways from there. The slide's length shifts the branch's
        # arcs (`branch_slide`, read by operators/stream.py for the belts).
        # The items' yaw offset along the main (sideways after a RAT there)
        # rides along: the branch's own body carries it too (branch_keep_yaw).
        yaw_main = _flow_yaw(target, full=True)
        out = []
        for s_a in [a for a in arc if a < s_div - 1e-6] + [s_div]:
            q, h_t, inc = _sample_polyline(poly, arc, heading, incline, s_a)
            local = inv @ q
            out.append((local.x, local.y, local.z, h_ref + _wrap((h_t + yaw_t) - h_s_world), inc, s_a, _yaw_at(arc, yaw_main, s_a)))
        x0 = offset.length
        steps = 6
        for k in range(1, steps + 1):
            t = k / steps
            local = inv @ (q_div + offset * t)
            out.append((local.x, local.y, local.z, h_ref, inc_div, s_div + x0 * t, keep))
        settings["branch_slide"] = x0
        return out, s_div + x0
    settings["branch_slide"] = 0.0
    s_switch = max(s_div - blend, arc[0])
    blend = s_div - s_switch
    s_values = [a for a in arc if a < s_switch - 1e-6] + [s_switch + blend * k / 8.0 for k in range(0, 8)]
    yaw_main = _flow_yaw(target, full=True)
    out = []
    for s in s_values:
        q, h_t, inc = _sample_polyline(poly, arc, heading, incline, s)
        t = 0.0 if blend <= 1e-9 else min(1.0, max(0.0, (s - s_switch) / blend))
        p = q + offset * t
        local = inv @ p
        h_main = h_ref + _wrap((h_t + yaw_t) - h_s_world)  # main flow heading in this line's local frame
        h = h_main + _wrap(h_ref - h_main) * t  # onto the branch's flow start heading
        out.append((local.x, local.y, local.z, h, inc, s, _yaw_at(arc, yaw_main, s)))
    return out, s_div


def routing_root(context, obj):
    """The line whose item stream `obj` shares (operators/stream.py)."""
    from .stream import stream_root

    return stream_root(context, obj)


def stream_length_for(context, obj) -> float:
    """Wrap length of the stream `obj` shares (operators/stream.py)."""
    from .stream import tree_for

    tree = tree_for(context, obj)
    return tree.length if tree.shared else 0.0


def _closest_on_polyline(p: Vector, poly, arc, heading):
    best = (math.inf, None, 0.0, 0.0)
    for i in range(1, len(poly)):
        a, b = poly[i - 1], poly[i]
        ab = b - a
        l2 = ab.length_squared
        t = 0.0 if l2 < 1e-12 else max(0.0, min(1.0, (p - a).dot(ab) / l2))
        q = a + ab * t
        d = (p - q).length
        if d < best[0]:
            best = (d, q, arc[i - 1] + (arc[i] - arc[i - 1]) * t, heading[i - 1] + (heading[i] - heading[i - 1]) * t)
    return best


def _ray_hit_polyline(origin: Vector, forward: Vector, poly, arc, heading, t_min: float, t_max: float):
    best = None
    fx, fy = forward.x, forward.y
    for i in range(1, len(poly)):
        a, b = poly[i - 1], poly[i]
        dx, dy = b.x - a.x, b.y - a.y
        denom = fx * dy - fy * dx
        if abs(denom) < 1e-9:
            continue
        rx, ry = a.x - origin.x, a.y - origin.y
        t = (rx * dy - ry * dx) / denom
        u = (rx * fy - ry * fx) / denom
        if -1e-6 <= u <= 1.0 + 1e-6 and t_min <= t <= t_max:
            if best is None or t < best[0]:
                u = max(0.0, min(1.0, u))
                best = (t, a + (b - a) * u, arc[i - 1] + (arc[i] - arc[i - 1]) * u, heading[i - 1] + (heading[i] - heading[i - 1]) * u)
    return best


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _forward(h: float) -> Vector:
    return Vector((-math.sin(h), math.cos(h), 0.0))


def _left(h: float) -> Vector:
    return Vector((-math.cos(h), -math.sin(h), 0.0))


REFIT_REACH_M = 3.0  # when re-aiming a curve ending, the target may be this far ahead
CURVE_REFIT_ORDER = (45, 30, 60, 90)  # preferred approach angles for a re-aimed curve


def find_target(context, obj, end_world: Vector, heading_world: float, reach: float | None = None,
                proximity: float | None = None):
    """(target, centerline point the aim ray hits, distance, target half
    width, s_at, target heading world) or None. `proximity` widens the
    fallback test on the end itself (default: inside the target's body)."""
    from .build_line import all_lines, resolve_width_mm

    scene = context.scene
    if reach is None:
        reach = _reach(context)
    forward = _forward(heading_world)
    tol = units.mm_to_bu(loader.get_segment_catalog().junction_snap_tolerance_mm, scene)
    best = None
    for other in all_lines(scene):
        if other == obj or len(other.data.curves) == 0:
            continue
        poly, arc, heading = _world_spine(other)
        if not poly:
            continue
        half_width = units.mm_to_bu(resolve_width_mm(other.conveyor_line), scene) / 2.0
        # Reach is measured to the target's near EDGE along the aim, so it
        # reads as "how far from the conveyor", whatever the approach angle.
        hit = _ray_hit_polyline(end_world, forward, poly, arc, heading, -(half_width + tol), reach + half_width / 0.2)
        if hit is not None:
            t, q, s_at, h_at = hit
            sin_d = max(abs(math.sin(_wrap(heading_world - (h_at + other.rotation_euler.z)))), 0.2)
            if t - half_width / sin_d > reach:
                hit = None
        if hit is not None:
            score = max(t, 0.0)
        else:
            d, q, s_at, h_at = _closest_on_polyline(end_world, poly, arc, heading)
            if q is None or d > (proximity if proximity is not None else half_width + tol):
                continue
            score = d
        # Height at the hit, not at the target's start: an inclined main line
        # used to reject feeders level with its raised part (and accept ones
        # at its start height passing under it).
        if abs(q.z - end_world.z) > tol:
            continue
        if best is None or score < best[2]:
            best = (other, q, score, half_width, s_at, h_at + other.rotation_euler.z)
    return best


# --------------------------------------------------------- line helpers --

def _line_data(context, obj):
    """(spine, segments, width_m, starts, frames) of a line in local space."""
    from .build_line import evaluate_line

    spine, segments, width_m = evaluate_line(context, obj)
    settings = obj.conveyor_line
    radius_m = 0.0
    if settings.nose_over:
        conveyor_type = loader.get_conveyor_types()[settings.conveyor_type]
        radius_m = units.mm_to_bu(loader.get_segment_catalog().nose_over_radius_for(conveyor_type.cross_section), context.scene)
    starts = seg_model.segment_starts(segments, width_m, radius_m)
    frames = seg_model.segment_frames(segments, seg_model.Pose(0, 0, 0, 0, 0), width_m, transition_radius_m=radius_m)
    return spine, segments, width_m, starts, frames


def _is_merge(seg) -> bool:
    return seg.kind == 'MODULE' and seg.module_kind == 'MERGE'


def _is_diverter(seg) -> bool:
    return seg.kind == 'MODULE' and seg.module_kind == 'DIVERTER'


def _is_junction(seg) -> bool:
    """A module other lines dock on: a merge / diverter -- or a right-angle
    transfer, whose two side faces each take a line (user, 2026-10-10: "the
    RAT should be standalone and connect on all sides, + signs on all
    sides"). A RAT has no role of its own: each docked line brings its own
    (`_line_role`), so one RAT can feed and sort at once."""
    return seg.kind == 'MODULE' and seg.module_kind in ('MERGE', 'DIVERTER', 'RAT')


JUNCTION_KINDS = ('MERGE', 'DIVERTER')


def _two_sided(seg) -> bool:
    return seg.merge_side == 'BOTH' or seg.module_kind == 'RAT'


def _junction_angle(seg) -> int:
    return 90 if seg.module_kind == 'RAT' else int(seg.merge_angle)


def _line_role(obj) -> str:
    """The role of a line docked by its origin: what the attach recorded,
    else its flow (goods running to the origin = it feeds in)."""
    role = obj.conveyor_line.get(_ROLE_KEY)
    return role if role in JUNCTION_KINDS else ('MERGE' if flow_reversed(obj) else 'DIVERTER')


def _junction_role(seg, obj) -> str:
    """The role junction `seg` gives `obj`: the module's own kind; a RAT
    hosts both, per line."""
    return _line_role(obj) if seg.module_kind == 'RAT' else seg.module_kind


def _source_role(context, seg, name: str) -> str:
    line = context.scene.objects.get(name)
    return _junction_role(seg, line) if (line is not None and seg.module_kind == 'RAT') else seg.module_kind


def _has_end_face(seg) -> bool:
    """A corner RAT's far face: the goods go straight through to a line
    docked there (user, 2026-10-11 night: "add conveyors to ALL its sides,
    two independently sized pallets attached to it")."""
    return seg.kind == 'MODULE' and seg.module_kind == 'RAT' and seg.module_exit in ('LEFT', 'RIGHT')


def _has_side(seg, side: str) -> bool:
    if side == 'END':
        return _has_end_face(seg)
    return seg.merge_side == side or _two_sided(seg)


def _source(seg, side: str) -> str:
    if side == 'END':
        return getattr(seg, "rat_source_end", "")
    return seg.merge_source_right if (_two_sided(seg) and side == 'RIGHT') else seg.merge_source


def _infeed(seg, side: str) -> float:
    from .build_line import infeed_for_side

    return infeed_for_side(seg, 1 if side == 'RIGHT' else -1)


def _set_infeed(seg, side: str, infeed_mm: float) -> bool:
    """The face on `side` as wide as the line docking there. True when it changed."""
    if seg.module_kind == 'RAT':
        # A RAT's face takes the docked line's frame width (a side face grows
        # the module to it, the line is never resized): 1200 in, 800 out.
        key = {'LEFT': "rat_face_left_mm", 'RIGHT': "rat_face_right_mm", 'END': "rat_face_end_mm"}[side]
        if abs(float(getattr(seg, key)) - infeed_mm) <= 0.5:
            return False
        seg[key] = float(infeed_mm)
        return True
    if abs(_infeed(seg, side) - infeed_mm) <= 0.5:
        return False
    key = "merge_infeed_right_mm" if side == 'RIGHT' and seg.merge_side == 'BOTH' else "merge_infeed_mm"
    seg[key] = float(infeed_mm)
    return True


def _set_source(seg, side: str, name: str) -> None:
    if side == 'END':
        seg.rat_source_end = name
    elif _two_sided(seg) and side == 'RIGHT':
        seg.merge_source_right = name
    else:
        seg.merge_source = name


def _sources(seg):
    return [n for n in (seg.merge_source, seg.merge_source_right, getattr(seg, "rat_source_end", "")) if n]


def _free_face(seg, side: str) -> None:
    """Nothing docks on `side` any more: its source goes and a RAT's face is
    its own width again, so the module shrinks back. (The handler's
    deleted-feeder cleanup cleared the name alone and left a 540 mm face
    on an empty side.)"""
    if side == 'END':
        seg.rat_source_end = ""
        seg["rat_face_end_mm"] = 0.0
    elif side == 'RIGHT' and (_two_sided(seg) or seg.merge_source_right):
        seg.merge_source_right = ""
        if seg.module_kind == 'RAT':
            seg["rat_face_right_mm"] = 0.0
    else:
        seg.merge_source = ""
        if seg.module_kind == 'RAT':
            seg["rat_face_left_mm"] = 0.0


def _renamed_source(context, target, index: int, side: str, lines):
    """The line a face of `target` still names by its OLD name: one that
    records its dock on `target` (its dock keys), sits on that face with
    its origin or its flow end, and is named by no face of `target` any
    more -- renamed, not deleted. None when it is gone."""
    segs = target.conveyor_line.segments
    named = {n for sg in segs if _is_junction(sg) for n in _sources(sg)}
    try:
        center, _h, _g = _module_face_world(context, target, index, side)
    except Exception:
        return None
    for other in lines:
        if other == target or other.name in named:
            continue
        s = other.conveyor_line
        if target.name not in (s.get("continue_target"), s.get("branch_target")):
            continue
        m = _world_matrix(other)
        points = [m @ Vector((0.0, 0.0, 0.0))]
        spine = _line_data(context, other)[0]
        if len(spine):
            end = spine.pose_at(len(spine) - 1)
            points.append(m @ Vector((end.x, end.y, end.z)))
        if any((p - center).length <= 0.3 for p in points):
            return other
    return None


def _rebuild(context, obj):
    from .build_line import build_line

    build_line(context, obj)


def _remove_junction(target, index: int) -> None:
    """Turns the MERGE module at `index` back into plain straight and folds
    it into straight neighbours (no rebuild)."""
    from ..props.line_settings import suspended_rebuild

    segs = target.conveyor_line.segments
    with suspended_rebuild():
        seg = segs[index]
        length = seg.length_mm
        seg.kind = 'STRAIGHT'
        seg["length_mm"] = max(length, MIN_PIECE_MM)
        seg.rise_mm = 0.0
        seg.merge_source = ""
        seg.merge_source_right = ""
        seg.merge_auto = False
        from .junction_ports import clear_uids

        clear_uids(seg)  # a re-fit carries them (_choices); a straight has no faces
        # Fold with the straight after, then the straight before.
        if index + 1 < len(segs) and segs[index + 1].kind == 'STRAIGHT' and abs(segs[index + 1].rise_mm) < 1e-6:
            seg["length_mm"] = seg.length_mm + segs[index + 1].length_mm
            segs.remove(index + 1)
        if index - 1 >= 0 and segs[index - 1].kind == 'STRAIGHT' and abs(segs[index - 1].rise_mm) < 1e-6:
            segs[index - 1]["length_mm"] = segs[index - 1].length_mm + seg.length_mm
            segs.remove(index)
            index -= 1
        settings = target.conveyor_line
        settings.active_segment_index = max(0, min(settings.active_segment_index, len(segs) - 1))


def _release_source(context, source_name: str, keep_target=None, kinds=JUNCTION_KINDS) -> None:
    """Undo everything `source_name` occupies on other lines (junctions of
    the given kinds: its END docks on merges, its START on diverters): auto
    junctions are removed, manual ones are marked free."""
    from .build_line import all_lines

    for line in all_lines(context.scene):
        if line == keep_target or line.name == source_name:
            continue
        segs = line.conveyor_line.segments
        changed = False
        for i in range(len(segs) - 1, -1, -1):
            seg = segs[i]
            if _is_junction(seg) and source_name in _sources(seg) and _source_role(context, seg, source_name) in kinds:
                if seg.merge_auto:
                    _remove_junction(line, i)
                else:
                    if seg.merge_source == source_name:
                        _free_face(seg, 'LEFT')
                    if seg.merge_source_right == source_name:
                        _free_face(seg, 'RIGHT')
                    if getattr(seg, "rat_source_end", "") == source_name:
                        _free_face(seg, 'END')
                changed = True
        gaps = line.conveyor_line.guide_gaps  # legacy openings from the old feeder-side merge
        for i in range(len(gaps) - 1, -1, -1):
            if gaps[i].source == source_name:
                gaps.remove(i)
                changed = True
        if changed:
            _rebuild(context, line)


def _probe_layout(context, target, module_kind: str, angle_deg: int, side: str, infeed_mm: float):
    """Layout a junction of this kind / angle / infeed would have on
    `target`, evaluated on a scratch segment (no rebuild)."""
    from ..props.line_settings import suspended_rebuild
    from .build_line import merge_layout_for

    settings = target.conveyor_line
    with suspended_rebuild():
        probe = settings.segments.add()
        probe.kind = 'MODULE'
        probe.module_kind = module_kind
        probe.merge_side = side
        probe.merge_angle = str(angle_deg)
        probe["merge_infeed_mm"] = infeed_mm
        layout = merge_layout_for(probe, settings, context.scene)
        settings.segments.remove(len(settings.segments) - 1)
    return layout


def _insert_junction(context, target, s_start_m: float, angle_deg: int, side: str, infeed_mm: float, source_name: str,
                     module_kind: str = 'MERGE'):
    """Splits the straight under [s_start, s_start + L] into straight /
    junction / straight. Returns the module index or None when it does not fit."""
    from ..props.line_settings import suspended_rebuild

    scene = context.scene
    settings = target.conveyor_line
    _spine, segments, _w, starts, _frames = _line_data(context, target)
    length_m = _probe_layout(context, target, module_kind, angle_deg, side, infeed_mm).length_m
    s_end_m = s_start_m + length_m
    for i, seg in enumerate(segments):
        if not isinstance(seg, seg_model.Straight) or settings.segments[i].kind != 'STRAIGHT':
            continue
        seg_start, seg_end = starts[i], starts[i] + seg.length_m
        a_mm = units.bu_to_mm(s_start_m - seg_start, scene)
        b_mm = units.bu_to_mm(seg_end - s_end_m, scene)
        if a_mm < -1.0 or b_mm < -1.0:
            continue
        with suspended_rebuild():
            segs = settings.segments
            n = len(segs)
            module = segs.add()
            module.kind = 'MODULE'
            module.module_kind = module_kind
            module.merge_side = side
            module.merge_angle = str(angle_deg)
            module["merge_infeed_mm"] = infeed_mm
            module.merge_source = source_name
            module.merge_auto = True
            after = segs.add()
            after.kind = 'STRAIGHT'
            after["length_mm"] = max(b_mm, MIN_PIECE_MM)
            after.rise_mm = 0.0
            segs.move(n, i + 1)
            segs.move(n + 1, i + 2)
            segs[i]["length_mm"] = max(a_mm, MIN_PIECE_MM)
        return i + 1
    return None


def _module_face_world(context, target, index: int, side: str | None = None, role: str | None = None):
    """World (face center, docked line's heading, junction geometry) of a
    MERGE / DIVERTER module's face on `side` ('LEFT'/'RIGHT'; the module's
    own side when None), or of a RAT's side face. For a merge the heading
    is the feeder's (pointing into the main line), for a diverter the
    branch's (leaving it); a RAT takes either (`role`, a branch by default)."""
    from .build_line import merge_layout_for

    settings = target.conveyor_line
    seg = settings.segments[index]
    if side is None:
        side = 'RIGHT' if seg.merge_side == 'RIGHT' else 'LEFT'
    sd = 1 if side == 'RIGHT' else -1
    _spine, segments, width_m, _starts, frames = _line_data(context, target)
    start = frames[index][0]
    yaw = target.rotation_euler.z
    h = yaw + start.heading
    fwd, right = _forward(h), Vector((math.cos(h), math.sin(h), 0.0))
    start_world = _world_matrix(target) @ Vector((start.x, start.y, start.z))
    if seg.module_kind == 'RAT':
        from types import SimpleNamespace

        from ..geonodes.modules.common import SIDE_PLATE

        # The face is the deck's side edge at the module's middle, where the
        # pop-up belts carry the goods out (model/transfer_parts.rat_parts);
        # the END face is the far edge, where they go straight through.
        if side == 'END':
            fx, fy = 0.0, segments[index].length_m
        else:
            fx, fy = sd * (width_m / 2.0 + SIDE_PLATE), segments[index].length_m / 2.0
        layout = None
        geom = SimpleNamespace(face_center=(fx, fy), y_landing=fy)
    else:
        layout = merge_layout_for(seg, settings, context.scene)
        geom = layout.sides[sd]
        fx, fy = layout.faces[sd]
    center = start_world + right * fx + fwd * fy
    theta = math.radians(float(_junction_angle(seg)))
    role = role or ('DIVERTER' if seg.module_kind == 'RAT' else seg.module_kind)
    if side == 'END' and seg.module_kind == 'RAT':
        # Straight through: a branch leaves along the incoming heading, a feeder's goods run against it.
        return center, h + (math.pi if role == 'MERGE' else 0.0), geom
    # Frame convention: a LEFT turn increases heading. A feeder docking from
    # the RIGHT points left -> heading = h + theta; from the LEFT -> h - theta.
    # A branch leaving to the RIGHT turns right -> h - theta. On a reversed
    # target the flow runs against the geometry: the wedge is laid out along
    # the flow (merge_layout_for), so the docked line's heading mirrors too.
    flow_h = h + (math.pi if flow_reversed(target) else 0.0)
    flow_right = (side == 'RIGHT') != flow_reversed(target)
    turn = theta if flow_right else -theta  # a feeder from the flow-right points left (+)
    feeder_heading = flow_h + (-turn if role == 'DIVERTER' else turn)
    return center, feeder_heading, geom


def free_junction_faces(context, target, only: int | None = None) -> list:
    """Where another conveyor could dock on `target`'s junctions: for every
    MERGE / DIVERTER module (or just the one at `only`) each side whose face
    is free -- a configured face without a docked line, or the other side
    of a one-sided junction (docking there makes it two-sided). Returns
    [(target, module index, side, world face centre, world outward unit
    vector)], from the caches build_line writes, so it is cheap enough for
    a gizmo's draw_prepare (no chain evaluation)."""
    from .build_line import merge_layout_for

    settings = target.conveyor_line
    frames = settings.get("segment_frames")
    heads = settings.get("segment_start_heading")
    if not frames or not heads:
        return []
    W = _world_matrix(target)
    yaw = target.rotation_euler.z
    out = []
    for i, seg in enumerate(settings.segments):
        if (only is not None and i != only) or not _is_junction(seg) or 6 * i + 6 > len(frames) or i >= len(heads):
            continue
        start = W @ Vector(frames[6 * i:6 * i + 3])
        h = yaw + float(heads[i])
        fwd, right = _forward(h), Vector((math.cos(h), math.sin(h), 0.0))
        if seg.module_kind == 'RAT':
            # A RAT's side faces: the two the line itself does not leave
            # through, each free until a line docks there.
            from ..geonodes.modules.common import SIDE_PLATE
            from .build_line import rat_footprint_mm, resolve_width_mm

            half = units.mm_to_bu(resolve_width_mm(settings), context.scene) / 2.0 + SIDE_PLATE
            mid = units.mm_to_bu(rat_footprint_mm(seg, settings, context.scene), context.scene) / 2.0
            for side in ('LEFT', 'RIGHT'):
                if side == seg.module_exit or _source(seg, side):
                    continue
                sd = 1 if side == 'RIGHT' else -1
                out.append((target, i, side, start + right * (sd * half) + fwd * mid, right * float(sd)))
            if _has_end_face(seg):
                if not _source(seg, 'END'):  # the far face of a corner: a line straight through
                    out.append((target, i, 'END', start + fwd * (2.0 * mid), fwd))
            elif i in (0, len(settings.segments) - 1):
                # A straight transfer's own start / end: a + beside the piece
                # keys that starts a SEPARATE line there -- a feeder the RAT
                # carries on from, the takeaway after it (operators/new_line).
                from .build_line import _rat_free_ends

                start_free, end_free = _rat_free_ends(context, target, settings, i)
                if i == 0 and start_free:
                    out.append((target, i, 'START', start + right * 0.35, -fwd))
                if i == len(settings.segments) - 1 and end_free:
                    out.append((target, i, 'END', start + fwd * (2.0 * mid) + right * 0.35, fwd))
            continue
        try:
            layout = merge_layout_for(seg, settings, context.scene)
        except Exception:
            continue
        for side in ('LEFT', 'RIGHT'):
            sd = 1 if side == 'RIGHT' else -1
            if _has_side(seg, side):
                if _source(seg, side):
                    continue
                fx, fy = layout.faces[sd]
            else:
                # The other side of a one-sided junction: its face mirrored across the centreline.
                ox, oy = layout.faces[-sd]
                fx, fy = -ox, oy
            centre = start + right * fx + fwd * fy
            out.append((target, i, side, centre, right * float(sd)))
    return out


def open_junction_face(context, target, index: int, side: str, role: str | None = None):
    """Makes `side` of the junction at `index` a free MANUAL face -- a
    one-sided junction becomes two-sided, keeping the line docked on its
    first side -- and returns (world face centre, body heading of a line
    docking there). A manual junction keeps its angle and stays when a line
    leaves it, which is what a junction someone deliberately built on wants.
    A RAT's side faces are always there: `role` says what docks (a branch
    by default)."""
    from ..props.line_settings import suspended_rebuild

    settings = target.conveyor_line
    seg = settings.segments[index]
    if seg.module_kind == 'RAT':
        role = role or 'DIVERTER'
        centre, dock_h, _geom = _module_face_world(context, target, index, side, role=role)
        return centre, dock_h + (math.pi if role == 'MERGE' else 0.0)
    if seg.merge_side != 'BOTH' and seg.merge_side != side:
        with suspended_rebuild():
            left_src = seg.merge_source if seg.merge_side == 'LEFT' else ""
            right_src = seg.merge_source if seg.merge_side == 'RIGHT' else ""
            seg.merge_side = 'BOTH'
            seg.merge_source, seg.merge_source_right = left_src, right_src
            seg.merge_auto = False
        _rebuild(context, target)
    elif seg.merge_auto:
        seg.merge_auto = False
    centre, dock_h, _geom = _module_face_world(context, target, index, side)
    return centre, dock_h + (math.pi if seg.module_kind == 'MERGE' else 0.0)


# ----------------------------------------------------------- the sync --

_refit_depth = [0]


def _refit_curve_ending(context, obj, segments, width_m, target) -> bool:
    """The feeder's last segment is a curve whose end runs parallel (or too
    shallow) to `target`: change its angle so the line approaches at a
    catalog angle and its end can reach the target's edge (a filler
    straight is added by the normal fitting afterwards). Returns True when
    the segment list was changed."""
    settings = obj.conveyor_line
    last_ui = settings.segments[-1]
    if last_ui.kind != 'CURVE' or not segments or not isinstance(segments[-1], seg_model.Curve):
        return False
    radius_m = 0.0
    if settings.nose_over:
        conveyor_type = loader.get_conveyor_types()[settings.conveyor_type]
        radius_m = units.mm_to_bu(loader.get_segment_catalog().nose_over_radius_for(conveyor_type.cross_section), context.scene)
    yaw = obj.rotation_euler.z
    infeed_m = width_m + 2.0 * RAIL_THICKNESS_M
    min_piece = units.mm_to_bu(MIN_PIECE_MM, context.scene)
    old = segments[-1]
    for angle in CURVE_REFIT_ORDER:
        trial = list(segments[:-1]) + [seg_model.Curve(float(angle), old.inside_radius_m, old.direction)]
        end = seg_model.end_pose(trial, seg_model.Pose(0, 0, 0, 0, 0), width_m, transition_radius_m=radius_m)
        end_world = _world_matrix(obj) @ Vector((end.x, end.y, end.z))
        h_f = yaw + end.heading
        hit = find_target(context, obj, end_world, h_f, reach=REFIT_REACH_M)
        if hit is None or hit[0] != target:
            continue
        _t, q, _d, half_w, _s, h_t = hit
        delta = _wrap(h_f - h_t)
        if junction.snap_angle(math.degrees(abs(delta))) is None:
            continue
        theta = math.radians(junction.snap_angle(math.degrees(abs(delta))))
        t_center = (q - end_world).dot(_forward(h_f))
        t_end = t_center - half_w / math.sin(theta) - (infeed_m / 2.0) * math.cos(theta) / math.sin(theta)
        if t_end < -POSITION_TOLERANCE_M:
            continue  # the shorter curve would already sit inside the target
        if 0.0 <= t_end < min_piece:
            t_end = 0.0
        last_ui["curve_angle_deg"] = int(angle)
        return True
    return False


def dock_status(context, obj) -> str:
    """Panel text explaining why a line's flow end is not docked."""
    settings = obj.conveyor_line
    if not settings.dock_enabled:
        return "Docking off"
    if not settings.segments:
        return "Not docked"
    try:
        spine, segments, width_m, _starts, _frames = _line_data(context, obj)
    except Exception:
        return "Not docked"
    end_world, h_f, _l, _h = _flow_end(obj, spine)
    hit = find_target(context, obj, end_world, h_f)
    where = "start" if flow_reversed(obj) else "end"
    if hit is None:
        if origin_dock(context, obj) is None and not attach_note(obj):
            return "Not attached: move the origin onto a line (G), rotate (R) for the angle"
        return f"End not docked: no line within {context.scene.conveyor_settings.dock_distance_m:.1f} m ahead of the {where}"
    target, _q, _d, _hw, _s, h_t = hit
    approach = math.degrees(abs(_wrap(h_f - h_t)))
    if junction.snap_angle(approach) is None:
        return f"Not docked: {approach:.0f}° to {target.name}, needs 15-90° in 15° steps"
    return f"Not docked: junction does not fit on {target.name} here"


_REVERSE_KEY = "conveyor_last_reverse"


def sync_feeder(context, obj) -> None:
    """Dock `obj` onto other lines. The ORIGIN attaches by proximity
    (_sync_origin): placed on or next to another line it becomes a merge
    or an outfeed there, at the angle it is rotated to. The FAR end docks
    by aim, by its flow role: goods leave at the flow end (a merge on the
    line it aims at, _sync) and enter at the flow start (a diverter on the
    line it leaves from, _sync_branch)."""
    global _busy
    if _busy:
        return
    settings = obj.conveyor_line
    if not settings.segments:
        return
    _busy = True
    try:
        rev = bool(settings.reverse)
        toggled = settings.get(_REVERSE_KEY) is not None and bool(settings.get(_REVERSE_KEY)) != rev
        if toggled:
            # Direction flipped: every dock changes role, start over.
            _release_source(context, obj.name)
            _clear_branch(settings)
            _clear_continuation(settings)
        settings[_REVERSE_KEY] = rev
        if _drop_stale_docks(context, obj):
            _rebuild(context, obj)
        if settings.dock_enabled:
            from .ports import sync_port, sync_port_end

            # A rack's port under the origin comes first: the origin snaps
            # there and is pinned (operators/ports.py); otherwise a line.
            pinned = sync_port(context, obj) or _sync_origin(context, obj, toggled)
            rev = bool(settings.reverse)  # the attachment may have set the flow
            settings[_REVERSE_KEY] = rev
            if not rev:
                if sync_port_end(context, obj):
                    pass  # the end feeds a rack: nothing else to dock there
                elif settings.segments[-1].kind != 'MODULE':  # a flow end that is a module (RAT, junction) is not a feeder
                    _sync(context, obj, pinned)
                else:
                    _release_source(context, obj.name, kinds=('MERGE',))
                    if _clear_continuation(settings):
                        _rebuild(context, obj)
            else:
                _sync_branch(context, obj, pinned)
            _sync_tail(context, obj)
            # ...and a line standing where this END now is carries the goods
            # on. Adopted here, not in the handler, so a line BUILT with its
            # end at a RAT's start face docks too (the feeder's
            # matrix was remembered by its first build, the handler saw no
            # move and adopted nothing).
            from .build_line import all_lines

            adopt_tails(context, obj, all_lines(context.scene))
        else:
            _undock(context, obj)
        _remember_matrix(obj)
    finally:
        _busy = False


def _drop_stale_docks(context, obj) -> bool:
    """A continuation / prefix whose junction is gone (the main line was
    edited, moved or deleted underneath it) is dropped, so the line never
    claims a dock that does not exist."""
    settings = obj.conveyor_line
    changed = False
    if settings.get("continue_target") and docked_junction(context, obj, 'MERGE') is None:
        changed |= _clear_continuation(settings)
    if settings.get("branch_target") and docked_junction(context, obj, 'DIVERTER') is None and not settings.get(TAIL_KEY):
        changed |= _clear_branch(settings)
    return changed


# ------------------------------------------------------- origin attach --
#
# The workflow the user asked for (2026-09-30): a line's ORIGIN is its
# attachment point. Move the origin onto another line (G) and it snaps onto
# that line's edge right there; rotate it (R, which pivots on the origin)
# and the junction follows in 15 degree steps. The rotation also decides
# the flow: the body swung UPSTREAM is an infeed (merge, goods run to the
# origin), swung DOWNSTREAM an outfeed (diverter, goods run away from it);
# at 90 degrees either works and the Direction button chooses. The line
# attached to follows along when it moves.

ROLE_KEY = _ROLE_KEY = "conveyor_attach_role"  # the dock role a new line asks for (operators/new_line.create_line)
_NOTE_KEY = "conveyor_attach_note"
ATTACH_Z_TOL_M = 0.3  # the origin attaches to a line whose surface is this close in height
MANUAL_FOOTPRINT_M = 0.3  # an origin this close to a junction's footprint along the main counts as at that junction
FACE_TOL_M = 0.3  # ...when it sits no further out than the junction's faces plus this
FACE_OUT_MAX_M = 2.0  # no junction face sits further outside the line's edge than this (a cheap pre-check)
# The far end of an origin-attached line docks only when drawn right up to
# another line: attached lines sit at 15 degree steps, so their far ends
# meet NEIGHBOURING feeders at exact junction angles and grabbed them.
PINNED_REACH_M = 0.15
END_MARGIN_M = 0.05  # an origin at another line's very end (New Line from End) continues it, it does not attach
MAX_SLIDE_M = 1.0  # a junction that does not fit where the origin is may slide this far along the line


def origin_dock(context, obj):
    """(line, module index) of the junction the ORIGIN of `obj` sits on: its
    flow end on a MERGE when reversed, its flow start on a DIVERTER otherwise."""
    return docked_junction(context, obj, 'MERGE' if flow_reversed(obj) else 'DIVERTER')


def attach_note(obj) -> str:
    """Why the origin did not attach, when it was close to a line."""
    return str(obj.conveyor_line.get(_NOTE_KEY, ""))


def _docked_side(seg, name: str) -> str:
    if getattr(seg, "rat_source_end", "") == name:
        return 'END'
    if seg.merge_side == 'RIGHT' or (_two_sided(seg) and seg.merge_source_right == name):
        return 'RIGHT'
    return 'LEFT'


def _hangs_on(context, line, obj) -> bool:
    """True when `line` is docked onto `obj`, directly or through other
    docked lines: attaching `obj` to it would close a loop."""
    seen, todo = set(), [line]
    while todo:
        cur = todo.pop()
        if cur.name in seen:
            continue
        seen.add(cur.name)
        for kind in JUNCTION_KINDS:
            dock = docked_junction(context, cur, kind)
            if dock is None:
                continue
            if dock[0] == obj:
                return True
            todo.append(dock[0])
    return False


def _closest_xy(p: Vector, poly, arc, heading, z_tol: float):
    """Closest point to `p` in plan on a polyline, among the stretches at
    about p's height (a spiral's other turns are ignored)."""
    best = (math.inf, None, 0.0, 0.0)
    for i in range(1, len(poly)):
        a, b = poly[i - 1], poly[i]
        abx, aby = b.x - a.x, b.y - a.y
        l2 = abx * abx + aby * aby
        t = 0.0 if l2 < 1e-12 else max(0.0, min(1.0, ((p.x - a.x) * abx + (p.y - a.y) * aby) / l2))
        q = a.lerp(b, t)
        if abs(q.z - p.z) > z_tol:
            continue
        d = math.hypot(p.x - q.x, p.y - q.y)
        if d < best[0]:
            best = (d, q, arc[i - 1] + (arc[i] - arc[i - 1]) * t, heading[i - 1] + (heading[i] - heading[i - 1]) * t)
    return best


def attach_candidate(context, obj, point: Vector | None = None):
    """(line, centerline point, arc on it, its world heading there, half
    width) of the line `point` (default: the origin of `obj`) can attach to:
    within that line's body plus the Dock Distance, at about its height,
    not at its very ends. None when there is none."""
    from .build_line import all_lines, resolve_width_mm

    scene = context.scene
    if point is None:
        point = _world_matrix(obj) @ Vector((0.0, 0.0, 0.0))
    reach = _reach(context)
    best = None
    for other in all_lines(scene):
        if other == obj or len(other.data.curves) == 0:
            continue
        poly, arc, heading = _world_spine(other)
        if len(poly) < 2:
            continue
        half_w = units.mm_to_bu(resolve_width_mm(other.conveyor_line), scene) / 2.0
        d, q, s_at, h_at = _closest_xy(point, poly, arc, heading, ATTACH_Z_TOL_M)
        if q is None:
            continue
        # Within the Dock Distance of the edge -- or at one of its junctions,
        # whose faces sit outside the edge (0.93 m out on a 1240 mm 60°
        # merge): a line made with the + at a face never attached once Dock
        # Distance was set small (user's file, 2026-10-10, "Not attached").
        if d > half_w + reach and not _near_junction(context, other, point, s_at, d, half_w):
            continue
        if s_at <= END_MARGIN_M or s_at >= arc[-1] - END_MARGIN_M:
            continue
        if best is not None and d >= best[0]:
            continue
        if obj is not None and _hangs_on(context, other, obj):
            continue
        best = (d, other, q, s_at, h_at + other.rotation_euler.z, half_w)
    return None if best is None else best[1:]


def _near_junction(context, line, point: Vector, s_at: float, d: float, half_w: float) -> bool:
    """True when `point` sits at a junction of `line`: within its footprint
    along the line and no further out than its faces (plus FACE_TOL_M).
    The faces of an angled merge sit well outside the edge and move out
    when the junction widens for the line on its other side, so the Dock
    Distance alone would lose a line that was put on a face."""
    segs = line.conveyor_line.segments
    if d > half_w + FACE_OUT_MAX_M or not any(_is_junction(sg) for sg in segs):
        return False
    _sp, _segs, _w, starts, _fr = _line_data(context, line)
    poly, arc, heading = _world_spine(line)
    for i, sg in enumerate(segs):
        if not _is_junction(sg):
            continue
        s_end = starts[i + 1] if i + 1 < len(starts) else arc[-1]
        if not (starts[i] - MANUAL_FOOTPRINT_M <= s_at <= s_end + MANUAL_FOOTPRINT_M):
            continue
        for side in ('LEFT', 'RIGHT'):
            if not _has_side(sg, side):
                continue
            center, _h, _g = _module_face_world(context, line, i, side)
            d_face = _closest_xy(center, poly, arc, heading, ATTACH_Z_TOL_M)[0]
            if d <= d_face + FACE_TOL_M:
                return True
    return False


def attach_heading_at(context, point: Vector):
    """World heading for a new line starting at `point` on (or next to)
    another line: square off it, on the side `point` is on, so it attaches
    as a 90 degree merge right away (rotate it to change the angle). None
    when `point` is not on a line."""
    hit = attach_candidate(context, None, point)
    if hit is None:
        return None
    _target, q, _s, h_geo, _half_w = hit
    on_left = (point - q).dot(_left(h_geo)) >= 0.0
    return h_geo + (math.pi / 2.0 if on_left else -math.pi / 2.0)


def _rat_end_face_at(context, target, origin: Vector):
    """Index of the corner RAT of `target` whose far face centre is under
    `origin` (within 0.3 m), or None."""
    for i, seg in enumerate(target.conveyor_line.segments):
        if not _has_end_face(seg):
            continue
        try:
            center, _h, _g = _module_face_world(context, target, i, 'END')
        except Exception:
            continue
        if (center - origin).length <= 0.3:
            return i
    return None


def _place_origin(obj, world_point: Vector, heading: float) -> bool:
    """Puts the origin of `obj` at `world_point` with the line leaving it at
    world `heading`. Writes only what changed (every write is a depsgraph
    update and another pass of the handler)."""
    moved = False
    yaw_now = obj.rotation_euler.z
    new_yaw = yaw_now + _wrap(heading - yaw_now)
    if abs(new_yaw - yaw_now) > 1e-6:
        obj.rotation_euler.z = new_yaw
        moved = True
    delta = world_point - _world_matrix(obj) @ Vector((0.0, 0.0, 0.0))
    if delta.length > 1e-6:
        obj.location = obj.location + delta
        moved = True
    return moved


def _release_origin(context, obj) -> None:
    settings = obj.conveyor_line
    kind = 'MERGE' if flow_reversed(obj) else 'DIVERTER'
    _release_source(context, obj.name, kinds=(kind,))
    changed = _clear_continuation(settings) if kind == 'MERGE' else _clear_branch(settings)
    if _ROLE_KEY in settings:
        del settings[_ROLE_KEY]
    if changed:
        _rebuild(context, obj)


_JUNCTION_CHOICES = ("junction_tech", "route_class")  # what the user set on a junction: it survives a re-fit


def _choices(seg) -> dict:
    """The user's settings on a junction, carried across a re-fit (remove +
    insert on every sync that finds the junction a little off: 2.6 dropped
    them, so a chosen Technology or Route vanished on the next rebuild) --
    and its faces' port ids (R22.1), so a feeder sliding along keeps its port."""
    from .junction_ports import JUNCTION_UID_KEYS

    carry = {key: getattr(seg, key) for key in _JUNCTION_CHOICES}
    carry.update({key: str(seg[key]) for key in JUNCTION_UID_KEYS.values() if seg.get(key)})
    return carry


def _apply_choices(seg, carry: dict) -> None:
    from ..props.line_settings import suspended_rebuild
    from .junction_ports import JUNCTION_UID_KEYS

    ids = set(JUNCTION_UID_KEYS.values())
    with suspended_rebuild():
        for key, value in carry.items():
            if key in ids:
                if seg.get(key) != value:
                    seg[key] = value
            elif getattr(seg, key) != value:
                setattr(seg, key, value)


def _insert_junction_fit(context, target, s_start_m: float, angle_deg: int, side: str, infeed_mm: float,
                         source_name: str, module_kind: str):
    """_insert_junction at the nearest position within MAX_SLIDE_M of
    `s_start_m` where the junction fits on one straight, keeping both
    remaining pieces at least MIN_PIECE_MM long (so a re-sync finds the
    junction exactly where it was put). Returns the module index or None."""
    _sp, segments, _w, starts, _fr = _line_data(context, target)
    length = _probe_layout(context, target, module_kind, angle_deg, side, infeed_mm).length_m
    pad = units.mm_to_bu(MIN_PIECE_MM, context.scene)
    best = None
    for i, seg in enumerate(segments):
        if not isinstance(seg, seg_model.Straight) or target.conveyor_line.segments[i].kind != 'STRAIGHT':
            continue
        lo, hi = starts[i] + pad, starts[i] + seg.length_m - length - pad
        if hi < lo:
            continue
        s = min(max(s_start_m, lo), hi)
        if best is None or abs(s - s_start_m) < abs(best - s_start_m):
            best = s
    if best is None or abs(best - s_start_m) > MAX_SLIDE_M:
        return None
    return _insert_junction(context, target, best, angle_deg, side, infeed_mm, source_name, module_kind=module_kind)


def _sync_origin(context, obj, toggled: bool) -> bool:
    """Attaches the ORIGIN of `obj` to the line it sits on (see the block
    comment above). Returns True when attached (the line is then pinned:
    the far end may not move or rotate it)."""
    from ..props.line_settings import suspended_rebuild

    scene = context.scene
    settings = obj.conveyor_line
    settings[_NOTE_KEY] = ""
    first = settings.segments[0]
    first_is_rat = first.kind == 'MODULE' and first.module_kind == 'RAT'
    if first.kind == 'MODULE' and not first_is_rat:  # a line that starts with its own module is not a feeder
        _release_origin(context, obj)
        return False
    hit = attach_candidate(context, obj)
    if hit is None:
        _release_origin(context, obj)
        return False
    target, q, s_at, h_geo, _half_w = hit
    h_flow = h_geo + (math.pi if flow_reversed(target) else 0.0)
    origin = _world_matrix(obj) @ Vector((0.0, 0.0, 0.0))
    body = _forward(obj.rotation_euler.z)
    phi = math.degrees(math.acos(max(-1.0, min(1.0, body.dot(_forward(h_flow))))))  # 0 = body along the flow
    lateral = body.dot(_left(h_geo))
    if abs(lateral) < 0.02:  # body along the line: the side the origin is on
        lateral = (origin - q).dot(_left(h_geo)) or 1.0
    side = 'LEFT' if lateral > 0.0 else 'RIGHT'
    angle = junction.snap_step(min(phi, 180.0 - phi))
    at_end_face = _rat_end_face_at(context, target, origin) is not None
    if at_end_face:
        side, angle = 'END', 90  # straight through a corner RAT: no angle to snap, the role comes from the flow
    rev = bool(settings.reverse)
    fresh = origin_dock(context, obj) is None
    if toggled:
        role = 'MERGE' if rev else 'DIVERTER'  # the Direction button: the line swings to the mirrored angle
    elif angle >= 90:
        was = settings.get(_ROLE_KEY)
        role = was if was in JUNCTION_KINDS else 'MERGE'
    else:
        role = 'MERGE' if phi > 90.0 else 'DIVERTER'
    if (role == 'MERGE') != rev:
        # The attachment decides the flow; whatever the line docked in its
        # old role goes (its far end changes role too).
        _release_source(context, obj.name)
        _clear_branch(settings)
        _clear_continuation(settings)
        settings["reverse"] = role == 'MERGE'  # ID write: no update callback, rebuilt below
        settings[_REVERSE_KEY] = role == 'MERGE'
        _rebuild(context, obj)
        fresh = True
    kind = role

    _spine, _segs, width_m, _starts, _frames = _line_data(context, obj)
    infeed_m = width_m + 2.0 * RAIL_THICKNESS_M
    infeed_mm = units.bu_to_mm(infeed_m, scene)
    segs = target.conveyor_line.segments
    target_dirty = False
    existing = next((i for i, sg in enumerate(segs) if _is_junction(sg) and sg.module_kind == kind and sg.merge_auto
                     and sg.merge_source == obj.name), None)
    names = {o.name for o in scene.objects}
    if existing is None:
        # Renamed since it attached: its junction still carries the old name.
        # Without adopting it a second junction was inserted, found no room
        # beside the first and slid ~0.6 m along the line.
        for i, sg in enumerate(segs):
            if (_is_junction(sg) and sg.module_kind == kind and sg.merge_auto and sg.merge_source
                    and sg.merge_source not in names):
                center, _h, _g = _module_face_world(context, target, i, _docked_side(sg, sg.merge_source))
                if (center - origin).length <= 0.05:
                    sg.merge_source = obj.name
                    existing = i
                    break
    # A free (or manual) junction of this kind and side whose face is at the
    # origin: dock there with ITS angle (instead of this line's own auto one).
    manual = None
    t_spine, _tsegs, _tw, t_starts, _tfr = _line_data(context, target)
    for i, seg in enumerate(segs):
        if not _is_junction(seg) or seg.module_kind not in (kind, 'RAT') or seg.merge_auto or not _has_side(seg, side):
            continue
        taken_by = _source(seg, side)
        if taken_by not in ("", obj.name) and taken_by in names:
            continue  # (a name no line has is this line's old one: renamed, it docks again)
        if seg.module_kind == 'RAT' and side == seg.module_exit:
            continue  # the RAT's own line leaves there
        if first_is_rat and seg.module_kind != 'RAT':
            continue  # a line that starts with a RAT joins another RAT's face only (a sorter grid)
        center, _h, _g = _module_face_world(context, target, i, side, role=kind)
        s_end = t_starts[i + 1] if i + 1 < len(t_starts) else t_spine.length
        # At the face -- or anywhere over the junction's footprint: the face
        # moves when the junction widens for the line on its other side,
        # and the origin is snapped onto it below (user's file, 2026-10-10:
        # the second feeder of a 60° merge was left behind, "needs a level
        # straight").
        if (center - origin).length <= 0.3 or t_starts[i] - MANUAL_FOOTPRINT_M <= s_at <= s_end + MANUAL_FOOTPRINT_M:
            manual = seg
            break
    index = None
    if manual is None and first_is_rat:
        _release_origin(context, obj)  # no RAT face here: a RAT-first line gets no junction cut into a straight
        return False
    if manual is not None:
        if existing is not None:
            _remove_junction(target, existing)
            existing = None
        index = next(i for i, sg in enumerate(segs) if sg == manual)
        angle = _junction_angle(manual)
        # Each face as wide as its own line (user, 2026-10-10: "the merge
        # junction scales with the width of the merged conveyor").
        _set_infeed(manual, side, infeed_mm)
        if _source(manual, side) != obj.name:
            _set_source(manual, side, obj.name)
        target_dirty = True
    sd = 1 if side == 'RIGHT' else -1
    carry = {}
    if index is None:
        layout = _probe_layout(context, target, kind, angle, side, infeed_mm)
        s_start = s_at - layout.faces[sd][1]  # the face center lands where the origin is
        if existing is not None:
            seg = segs[existing]
            _sp, _sg, _w, t_starts, _fr = _line_data(context, target)
            if (abs(t_starts[existing] - s_start) <= POSITION_TOLERANCE_M and int(seg.merge_angle) == angle
                    and seg.merge_side == side and abs(_infeed(seg, side) - infeed_mm) <= 0.5):
                index = existing
            else:
                # Moving along keeps what the user chose on the junction.
                carry = _choices(seg)
                _remove_junction(target, existing)
    _release_source(context, obj.name, keep_target=target, kinds=(kind,))
    if index is None:
        index = _insert_junction_fit(context, target, s_start, angle, side, infeed_mm, obj.name, kind)
        if index is None:
            _rebuild(context, target)  # folds a removed junction back into the straight
            settings[_NOTE_KEY] = f"Can't attach to {target.name} here: needs a level straight for the {angle}° junction"
            if kind == 'MERGE':
                if _clear_continuation(settings):
                    _rebuild(context, obj)
            elif _clear_branch(settings):
                _rebuild(context, obj)
            return False
        seg = segs[index]
        with suspended_rebuild():
            for key, value in carry.items():
                setattr(seg, key, value)
        target_dirty = True
    if fresh:
        _link_goods_on_attach(context, obj, target, segs[index])
        target_dirty = True
    if target_dirty:
        _rebuild(context, target)
    seg = segs[index]
    center, dock_h, _geom = _module_face_world(context, target, index, side, role=kind)
    # A merge's line flows INTO the face, so its body points the other way;
    # an outfeed's body leaves the face in its flow direction.
    _place_origin(obj, center, dock_h + (math.pi if kind == 'MERGE' else 0.0))
    settings[_ROLE_KEY] = kind
    if kind == 'MERGE':
        _attach_continuation(context, obj, target, index, side)
    else:
        _attach_branch(context, obj, target, index, side)
    return True


def _link_goods_on_attach(context, obj, target, seg) -> bool:
    """Attachment: the goods of the two lines join up without extra
    clicks. A merge onto a populated line brings its own goods in. (An
    outfeed needs nothing: a docked branch takes its share of the main
    line's goods whenever that line is populated -- operators/stream.py --
    and a Route on the junction narrows it to one item class.) Returns
    True when the line was switched on (the caller rebuilds it)."""
    from .stream import stream_root

    root = stream_root(context, target)
    if not root.conveyor_line.populate:
        return False
    settings = obj.conveyor_line
    if _junction_role(seg, obj) == 'MERGE' and not settings.populate:
        settings["populate"] = True
        return True
    return False


def feeders_of(context, obj, seen=None) -> list:
    """Every line whose goods end up on `obj`: the sources of its merge
    junctions and, recursively, theirs."""
    scene = context.scene
    seen = set() if seen is None else seen
    out = []
    for seg in obj.conveyor_line.segments:
        if not _is_junction(seg) or seg.module_kind == 'DIVERTER':
            continue
        for name in _sources(seg):
            line = scene.objects.get(name)
            if line is None or name in seen or line == obj or _junction_role(seg, line) != 'MERGE':
                continue
            seen.add(name)
            out.append(line)
            out += feeders_of(context, line, seen)
    return out


def _role_for_pose(context, obj, target, index) -> str | None:
    """The role the CURRENT pose of `obj` gives its origin on junction
    `index` of `target` (body upstream = MERGE, downstream = DIVERTER), None
    at 90 degrees where both work."""
    if _junction_angle(target.conveyor_line.segments[index]) == 90:
        return None
    poly, arc, heading = _world_spine(target)
    origin = _world_matrix(obj) @ Vector((0.0, 0.0, 0.0))
    _d, q, _s, h_geo = _closest_xy(origin, poly, arc, heading, ATTACH_Z_TOL_M)
    if q is None:
        return None
    h_flow = h_geo + target.rotation_euler.z + (math.pi if flow_reversed(target) else 0.0)
    phi = math.degrees(math.acos(max(-1.0, min(1.0, _forward(obj.rotation_euler.z).dot(_forward(h_flow))))))
    return 'MERGE' if phi > 90.0 else 'DIVERTER'


def follow_target(context, obj, moved, seen=None, rigid: bool = True) -> None:
    """`moved` (a line `obj` is docked on) moved or changed shape: keep
    `obj` on its junction face. An attached origin is put back on it; a
    line docked only by its far end moves rigidly so that end stays on the
    face; a line whose origin is attached ELSEWHERE re-aims its far end.
    Lines docked on `obj` follow in turn. `rigid` False (the target was
    rebuilt in place, e.g. its Direction flipped): an attached line whose
    pose now says the other role keeps its pose and swaps role instead of
    swinging round to the mirrored junction."""
    seen = set() if seen is None else seen
    if obj.name in seen:
        return
    seen.add(obj.name)
    dock = origin_dock(context, obj)
    if dock is not None:
        target, index = dock
        if target != moved:
            sync_feeder(context, obj)
            return
        seg = target.conveyor_line.segments[index]
        if not rigid:
            role = _role_for_pose(context, obj, target, index)
            if role is not None and role != seg.module_kind:
                sync_feeder(context, obj)
                return
        role = _junction_role(seg, obj)
        center, dock_h, _geom = _module_face_world(context, target, index, _docked_side(seg, obj.name), role=role)
        placed = _place_origin(obj, center, dock_h + (math.pi if role == 'MERGE' else 0.0))
    else:
        far_kind = 'DIVERTER' if flow_reversed(obj) else 'MERGE'
        dock = docked_junction(context, obj, far_kind)
        if dock is None or dock[0] != moved:
            return
        target, index = dock
        seg = target.conveyor_line.segments[index]
        center, dock_h, _geom = _module_face_world(context, target, index, _docked_side(seg, obj.name))
        spine = _line_data(context, obj)[0]
        end = spine.pose_at(len(spine) - 1)
        # Flow heading at the far end: the end's heading, turned round when the
        # far end is where goods ENTER a reversed line.
        new_yaw = dock_h - end.heading - (math.pi if far_kind == 'DIVERTER' else 0.0)
        yaw_now = obj.rotation_euler.z
        new_yaw = yaw_now + _wrap(new_yaw - yaw_now)
        end_local = Vector((end.x, end.y, end.z))
        placed = abs(new_yaw - yaw_now) > 1e-6 or ((_world_matrix(obj) @ end_local) - center).length > 1e-6
        if placed:
            _rotate_about(obj, end_local, center, new_yaw)
    if not placed:
        return
    _remember_matrix(obj)
    _follow_dependents(context, obj, seen)


def _follow_dependents(context, obj, seen) -> None:
    """Lines hanging on `obj` keep their place on it after it moved: the
    sources of its junctions and the lines carrying its goods on."""
    from .build_line import all_lines

    for seg in obj.conveyor_line.segments:
        if _is_junction(seg):
            for name in _sources(seg):
                dependent = context.scene.objects.get(name)
                if dependent is not None:
                    follow_target(context, dependent, obj, seen)
    for other in all_lines(context.scene):
        if other != obj and other.conveyor_line.get(TAIL_KEY) == obj.name:
            follow_tail(context, other, obj, seen)


def follow_tail(context, obj, parent, seen=None) -> bool:
    """`parent`, whose goods `obj` carries on (TAIL_KEY), moved or changed
    length: keep the start of `obj` at its end. Its own heading stays (the
    user may have turned it up to TAIL_JOIN_DEG). Left behind, the start
    sat beside the parent's body and the origin attach grabbed it as a 90°
    feeder (ZZ_RAT test, 2026-10-10). Returns True when `obj` moved."""
    seen = set() if seen is None else seen
    if obj.name in seen:
        return False
    seen.add(obj.name)
    ps = parent.conveyor_line
    if not ps.segments:
        return False
    ex, ey, ez, _hd = ps.end_pose
    end_w = _world_matrix(parent) @ Vector((ex, ey, ez))
    delta = end_w - _world_matrix(obj) @ Vector((0.0, 0.0, 0.0))
    if delta.length <= 1e-6:
        return False
    obj.location = obj.location + delta
    _remember_matrix(obj)
    _follow_dependents(context, obj, seen)
    return True


def _undock(context, obj) -> None:
    """Docking off: free / remove every junction this line occupies and drop
    its stream prefix and continuation (the line stays where it is)."""
    from .ports import release_port

    release_port(context, obj)
    settings = obj.conveyor_line
    _release_source(context, obj.name)
    if settings.get(TAIL_KEY):
        del settings[TAIL_KEY]
    if _clear_branch(settings) | _clear_continuation(settings):
        _rebuild(context, obj)


def docked_junction(context, obj, kind: str = 'MERGE'):
    """(main line, module index) of the junction of `kind` `obj` is docked
    on (its end on a MERGE, its start on a DIVERTER), or None."""
    from .build_line import all_lines

    for line in all_lines(context.scene):
        if line == obj:
            continue
        for i, seg in enumerate(line.conveyor_line.segments):
            if _is_junction(seg) and obj.name in _sources(seg) and _junction_role(seg, obj) == kind:
                return line, i
    return None


def docked_diverter(context, obj):
    """(main line, diverter index) the START of `obj` is docked on, or None."""
    return docked_junction(context, obj, 'DIVERTER')


TAIL_JOIN_M = 0.08  # a line whose origin sits this close to another line's END, pointing on, continues it
TAIL_JOIN_DEG = 15.0
TAIL_KEY = "conveyor_tail_target"  # the line this one carries on from (its path is this line's item-path prefix)


def _sync_tail(context, obj) -> bool:
    """A line that starts where another ends carries that line's goods on:
    its item path gets that line's whole path in front (the branch prefix
    machinery, prefix_for with no blend), so the stream hands over where
    the first line stops drawing -- the goods used to vanish at a
    right-angle transfer's edge and pop up 0.6 m into the next line.
    Returns True when it rebuilt the line."""
    settings = obj.conveyor_line
    tail = tail_continuation(context, obj)
    if tail is None:
        if settings.get(TAIL_KEY):
            del settings[TAIL_KEY]
            if _clear_branch(settings):
                _rebuild(context, obj)
                return True
        return False
    target = tail[0]
    full = float(target.conveyor_line.get("full_length_m", 0.0))
    yaw_end = (_flow_yaw(target, full=True) or [0.0])[-1]  # sideways after a RAT: the takeaway carries them sideways on
    before = (settings.get(TAIL_KEY), tuple(settings.get(k) for k in BRANCH_KEYS))
    settings[TAIL_KEY] = target.name
    _set_branch(settings, target, full, 0.0, yaw_end)
    if (settings.get(TAIL_KEY), tuple(settings.get(k) for k in BRANCH_KEYS)) != before:
        _rebuild(context, obj)
        return True
    return False


def tail_continuation(context, obj):
    """(line, its last piece index) when `obj` starts right where that line
    ENDS and points on -- New Line from End, e.g. the takeaway conveyor
    after a right-angle transfer. Its goods are that line's goods carried on:
    the stream continues (operators/stream.py 'CONTINUE'; the goods used to
    vanish at the transfer's edge). None when `obj`
    is docked on a junction, when either line runs reversed, or when
    nothing ends there."""
    from .build_line import all_lines

    if obj is None or obj.type != 'CURVES' or not obj.conveyor_line.is_conveyor_line or not obj.conveyor_line.segments:
        return None
    if obj.conveyor_line.reverse or docked_junction(context, obj) is not None or docked_diverter(context, obj) is not None:
        return None
    from .ports import dock_at

    if dock_at(obj, "origin") is not None:  # pinned on a rack port: it continues nothing
        return None
    origin = _world_matrix(obj) @ Vector((0.0, 0.0, 0.0))
    yaw = obj.rotation_euler.z
    best = None
    for other in all_lines(context.scene):
        if other == obj:
            continue
        s = other.conveyor_line
        if not s.segments or s.reverse:
            continue
        ex, ey, ez, hd = s.end_pose
        end_w = _world_matrix(other) @ Vector((ex, ey, ez))
        d = (end_w - origin).length
        if d > TAIL_JOIN_M or (best is not None and d >= best[0]):
            continue
        if abs(_wrap(other.rotation_euler.z + math.radians(hd) - yaw)) > math.radians(TAIL_JOIN_DEG):
            continue
        if docked_junction(context, other) is not None:  # its end feeds a junction: nothing continues it
            continue
        best = (d, other)
    return None if best is None else (best[1], len(best[1].conveyor_line.segments) - 1)


def adopt_tails(context, obj, lines) -> list:
    """Lines that START where `obj` now ENDS (within TAIL_JOIN_M, pointing
    on) and carry nothing on yet take `obj`'s goods on from now on, their
    start snapped onto its end: a feeder brought up to a standalone RAT's
    start face stayed loose (2026-10-11: its end 5 cm past the
    RAT's origin, "not docked"). Called from sync_feeder for the line whose
    end moved or was built there. Returns the lines adopted."""
    settings = obj.conveyor_line
    if not settings.segments or settings.reverse:
        return []
    ex, ey, ez, _hd = settings.end_pose
    end_w = _world_matrix(obj) @ Vector((ex, ey, ez))
    adopted = []
    for other in lines:
        s = other.conveyor_line
        if other is obj or not s.dock_enabled or s.get(TAIL_KEY) or not s.segments:
            continue
        if ((_world_matrix(other) @ Vector((0.0, 0.0, 0.0))) - end_w).length > TAIL_JOIN_M:
            continue
        tail = tail_continuation(context, other)
        if tail is None or tail[0] != obj:
            continue
        _sync_tail(context, other)
        follow_tail(context, other, obj)
        adopted.append(other)
    return adopted


class CONVEYOR_OT_detach(bpy.types.Operator):
    bl_idname = "conveyor.detach"
    bl_label = "Detach"
    bl_description = "Undock this line: its junction on the main line is removed (or freed) and the line stays where it is until you dock it again"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj) and obj.type == 'CURVES' and obj.conveyor_line.is_conveyor_line

    def execute(self, context):
        global _busy
        obj = context.active_object
        obj.conveyor_line.dock_enabled = False
        _busy = True
        try:
            _undock(context, obj)
        finally:
            _busy = False
        return {'FINISHED'}


class CONVEYOR_OT_dock(bpy.types.Operator):
    bl_idname = "conveyor.dock"
    bl_label = "Dock"
    bl_description = "Allow docking again and dock now if the end points at another line within the dock distance"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj) and obj.type == 'CURVES' and obj.conveyor_line.is_conveyor_line

    def execute(self, context):
        obj = context.active_object
        obj.conveyor_line.dock_enabled = True
        sync_feeder(context, obj)
        if docked_junction(context, obj) is None and docked_diverter(context, obj) is None:
            self.report({'INFO'}, "Not docked: aim the end (or start) at another line within the dock distance")
        return {'FINISHED'}


def _sync(context, obj, pinned: bool = False) -> None:
    """Goods leaving this line: its FLOW end docks onto a MERGE junction of
    the line it aims at (auto-inserted or free/manual). `pinned`: the origin
    is attached elsewhere, so the line may not be rotated or moved -- the
    end docks only if it already arrives at a junction angle, and is fitted
    by its trailing straight."""
    from ..props.line_settings import suspended_rebuild

    scene = context.scene
    settings = obj.conveyor_line
    spine, segments, width_m, starts, frames = _line_data(context, obj)
    rev = flow_reversed(obj)
    end_world, h_f, end_local, _h_ref = _flow_end(obj, spine)
    yaw = obj.rotation_euler.z
    # (A docked line used to aim with a 3 m reach to stay docked while the
    # main line was nudged; it then grabbed other lines nearby. Docked lines
    # now follow their main line instead: follow_target.)
    hit = find_target(context, obj, end_world, h_f, reach=PINNED_REACH_M if pinned else None)
    if hit is None:
        if _clear_continuation(settings):
            _rebuild(context, obj)
    if hit is None and not rev and settings.segments[-1].kind == 'CURVE' and _refit_depth[0] == 0:
        # A curve ending alongside a line (parallel, out of the aim ray):
        # look further out for the line it was meant to join and re-aim.
        near = find_target(context, obj, end_world, h_f, reach=REFIT_REACH_M, proximity=REFIT_REACH_M)
        if near is not None and _refit_curve_ending(context, obj, segments, width_m, near[0]):
            _refit_depth[0] += 1
            try:
                _rebuild(context, obj)
                _sync(context, obj)
            finally:
                _refit_depth[0] -= 1
            return
    if hit is None:
        _release_source(context, obj.name, kinds=('MERGE',))
        return
    target, q, _d, half_w, s_at, h_t = hit
    h_t_flow = h_t + (math.pi if flow_reversed(target) else 0.0)
    delta = _wrap(h_f - h_t_flow)
    snapped = junction.snap_angle(math.degrees(abs(delta)))
    if snapped is None and _clear_continuation(settings):
        _rebuild(context, obj)
    if snapped is None:
        # A curve ending that lands parallel / too shallow: re-aim the curve
        # itself to a catalog approach angle, then dock (once).
        if not rev and _refit_depth[0] == 0 and _refit_curve_ending(context, obj, segments, width_m, target):
            _refit_depth[0] += 1
            try:
                _rebuild(context, obj)
                _sync(context, obj)
            finally:
                _refit_depth[0] -= 1
            return
        _release_source(context, obj.name, kinds=('MERGE',))
        return
    side = 'LEFT' if (end_world - q).dot(_left(h_t)) > 0.0 else 'RIGHT'
    theta = math.radians(snapped)
    infeed_m = width_m + 2.0 * RAIL_THICKNESS_M
    infeed_mm = units.bu_to_mm(infeed_m, scene)

    # 1. Snap the heading to the catalog angle, rotating about the flow end.
    desired_h_f = h_t_flow + math.copysign(theta, delta)
    rot = _wrap(desired_h_f - h_f)
    if pinned and abs(rot) > math.radians(0.5):
        _release_source(context, obj.name, kinds=('MERGE',))
        if _clear_continuation(settings):
            _rebuild(context, obj)
        return
    if abs(rot) > 1e-5 and not pinned:
        _rotate_about(obj, end_local, end_world, yaw + rot)
        h_f = desired_h_f
    forward = _forward(h_f)

    # 2. Dock onto a free junction nearby, or fit the end to the main line's edge.
    # Only FREE or MANUAL junctions attract the feeder; a junction this
    # feeder created itself follows the feeder instead (step 3).
    docked_index = None
    for i, seg in enumerate(target.conveyor_line.segments if not pinned else ()):
        if not _is_merge(seg) or int(seg.merge_angle) != snapped or not _has_side(seg, side):
            continue
        if seg.merge_source == obj.name and seg.merge_auto:
            continue
        if _source(seg, side) in ("", obj.name):
            center, feeder_heading, _geom = _module_face_world(context, target, i, side)
            if (center - end_world).length <= _reach(context) and abs(_wrap(feeder_heading - h_f)) < math.radians(1.0):
                docked_index = i
                if (center - end_world).length > POSITION_TOLERANCE_M:
                    obj.location = obj.location + (center - end_world)
                    end_world = center
                if _set_infeed(seg, side, infeed_mm):
                    _rebuild(context, target)
                if _source(seg, side) != obj.name:
                    _set_source(seg, side, obj.name)
                break
    if docked_index is not None:
        _release_source(context, obj.name, keep_target=target, kinds=('MERGE',))
        _attach_continuation(context, obj, target, docked_index, side)
        return

    t_center = (q - end_world).dot(forward)
    t_edge = t_center - half_w / math.sin(theta)
    t_end = t_edge - (infeed_m / 2.0) * math.cos(theta) / math.sin(theta)
    if abs(t_end) > POSITION_TOLERANCE_M:
        if rev:
            # The flow end is the curve's start (= the object origin): move the line.
            obj.location = obj.location + forward * t_end
            end_world = end_world + forward * t_end
        else:
            last = settings.segments[-1]
            moved = False
            with suspended_rebuild():
                if last.kind == 'STRAIGHT':
                    new_len = last.length_mm + units.bu_to_mm(t_end, scene)
                    if new_len >= MIN_PIECE_MM:
                        last["length_mm"] = new_len
                        moved = True
                elif t_end >= units.mm_to_bu(MIN_PIECE_MM, scene):
                    filler = settings.segments.add()
                    filler.kind = 'STRAIGHT'
                    filler["length_mm"] = units.bu_to_mm(t_end, scene)
                    filler.rise_mm = 0.0
                    settings.active_segment_index = len(settings.segments) - 1
                    moved = True
            if moved:
                _rebuild(context, obj)  # sync_feeder inside returns early (_busy)
                end_world = end_world + forward * t_end
    # 3. Place (or keep) the junction on the main line.
    s_end_on_target = s_at + (end_world - q).dot(_forward(h_t))
    layout = _probe_layout(context, target, 'MERGE', snapped, side, infeed_mm)
    s_module_start = s_end_on_target - layout.faces[1 if side == 'RIGHT' else -1][1]
    existing = next((i for i, s in enumerate(target.conveyor_line.segments) if _is_merge(s) and s.merge_auto and s.merge_source == obj.name), None)
    carry = {}
    if existing is not None:
        seg = target.conveyor_line.segments[existing]
        _sp, _sg, _w, t_starts, _fr = _line_data(context, target)
        same = (abs(t_starts[existing] - s_module_start) <= POSITION_TOLERANCE_M and int(seg.merge_angle) == snapped
                and seg.merge_side == side and abs(_infeed(seg, side) - infeed_mm) <= 0.5)
        if same:
            _release_source(context, obj.name, keep_target=target, kinds=('MERGE',))
            _attach_continuation(context, obj, target, existing, side)  # e.g. after a reload
            return
        carry = _choices(seg)
        _remove_junction(target, existing)
    _release_source(context, obj.name, keep_target=target, kinds=('MERGE',))
    # The junction fits on ONE straight; where the end aims at a piece joint
    # (a line built from 3 m pieces, the pieces another junction left) or a
    # wider junction no longer fits where the old one was, it slides up to
    # MAX_SLIDE_M along the main line and this line's end follows it. A
    # pinned line (its origin attached elsewhere) cannot move: no slide.
    if pinned:
        index = _insert_junction(context, target, s_module_start, snapped, side, infeed_mm, obj.name)
    else:
        index = _insert_junction_fit(context, target, s_module_start, snapped, side, infeed_mm, obj.name, 'MERGE')
    if index is None:
        _rebuild(context, target)  # folds the removed junction back in
        settings[_NOTE_KEY] = f"No room on {target.name} for the {snapped}° junction near the end of this line"
        return
    if carry:
        _apply_choices(target.conveyor_line.segments[index], carry)
    _rebuild(context, target)
    if not pinned:
        center, _fh, _geom = _module_face_world(context, target, index, side)
        shift = center - end_world
        shift.z = 0.0
        if shift.length > POSITION_TOLERANCE_M:
            obj.location = obj.location + shift
            _remember_matrix(obj)
    _attach_continuation(context, obj, target, index, side)


def _sync_branch(context, obj, pinned: bool = False) -> None:
    """Goods entering this line: its FLOW start docks onto a DIVERTER of the
    line it leaves from -- the mirror image of `_sync`. Aim backwards from
    the flow start; snap the heading to a catalog angle (rotating about it);
    dock onto a free or manual diverter whose face is near, or move the line
    so its flow start sits where a diverter's face would be and insert one
    (auto) into the main line's straight. The branch then gets the main's
    path as its stream prefix (`prefix_for`). `pinned`: see _sync (the flow
    start is then the far end, fitted by the trailing straight)."""
    from ..props.line_settings import suspended_rebuild

    scene = context.scene
    settings = obj.conveyor_line
    spine, _segments, width_m, _starts, _frames = _line_data(context, obj)
    yaw = obj.rotation_euler.z
    start_world, h_s, start_local, _h_ref = _flow_start(obj, spine)
    hit = find_target(context, obj, start_world, h_s + math.pi, reach=PINNED_REACH_M if pinned else None)
    snapped = None
    if hit is not None:
        target, q, _d, half_w, s_at, h_t = hit
        h_t_flow = h_t + (math.pi if flow_reversed(target) else 0.0)
        delta = _wrap(h_s - h_t_flow)
        snapped = junction.snap_angle(math.degrees(abs(delta)))
    if snapped is None:
        if _clear_branch(settings):
            _rebuild(context, obj)
        _release_source(context, obj.name, kinds=('DIVERTER',))
        return
    side = 'LEFT' if (start_world - q).dot(_left(h_t)) > 0.0 else 'RIGHT'
    theta = math.radians(snapped)
    infeed_m = width_m + 2.0 * RAIL_THICKNESS_M
    infeed_mm = units.bu_to_mm(infeed_m, scene)

    # 1. Snap the heading to the catalog angle (about the flow start): a
    # branch leaving to the flow-left turns left (+).
    flow_left = (side == 'LEFT') != flow_reversed(target)
    desired = h_t_flow + (theta if flow_left else -theta)
    rot = _wrap(desired - h_s)
    if pinned and abs(rot) > math.radians(0.5):
        if _clear_branch(settings):
            _rebuild(context, obj)
        _release_source(context, obj.name, kinds=('DIVERTER',))
        return
    if abs(rot) > 1e-5 and not pinned:
        _rotate_about(obj, start_local, start_world, yaw + rot)
        h_s = desired
    back = -_forward(h_s)

    # 2. A free or manual diverter with a matching face nearby.
    docked_index = None
    for i, seg in enumerate(target.conveyor_line.segments if not pinned else ()):
        if not _is_diverter(seg) or int(seg.merge_angle) != snapped or not _has_side(seg, side):
            continue
        if seg.merge_source == obj.name and seg.merge_auto:
            continue
        if _source(seg, side) in ("", obj.name):
            center, out_heading, _geom = _module_face_world(context, target, i, side)
            if (center - start_world).length <= _reach(context) and abs(_wrap(out_heading - h_s)) < math.radians(1.0):
                docked_index = i
                if (center - start_world).length > POSITION_TOLERANCE_M:
                    obj.location = obj.location + (center - start_world)
                    start_world = center
                if _set_infeed(seg, side, infeed_mm):
                    _rebuild(context, target)
                if _source(seg, side) != obj.name:
                    _set_source(seg, side, obj.name)
                break
    if docked_index is not None:
        _release_source(context, obj.name, keep_target=target, kinds=('DIVERTER',))
        _attach_branch(context, obj, target, docked_index, side)
        return

    # 3. Fit the flow start: its distance back to the main centerline is the
    # face's (mirror of the feeder end fit in _sync).
    t_center = (q - start_world).dot(back)
    t_wanted = half_w / math.sin(theta) + (infeed_m / 2.0) * math.cos(theta) / math.sin(theta)
    shift = t_center - t_wanted
    undo_stretch = None
    if abs(shift) > POSITION_TOLERANCE_M and pinned:
        # The flow start is the far end of a reversed line whose origin is
        # attached: stretch the trailing straight instead of moving the line
        # (back = the end's geometric forward, see _flow_start).
        last = settings.segments[-1]
        moved = False
        undo_stretch = (len(settings.segments), last.length_mm)
        with suspended_rebuild():
            if last.kind == 'STRAIGHT' and last.length_mm + units.bu_to_mm(shift, scene) >= MIN_PIECE_MM:
                last["length_mm"] = last.length_mm + units.bu_to_mm(shift, scene)
                moved = True
            elif last.kind != 'STRAIGHT' and shift >= units.mm_to_bu(MIN_PIECE_MM, scene):
                filler = settings.segments.add()
                filler.kind = 'STRAIGHT'
                filler["length_mm"] = units.bu_to_mm(shift, scene)
                filler.rise_mm = 0.0
                moved = True
        if not moved:
            if _clear_branch(settings):
                _rebuild(context, obj)
            _release_source(context, obj.name, kinds=('DIVERTER',))
            return
        _rebuild(context, obj)
        start_world = start_world + back * shift
    elif abs(shift) > POSITION_TOLERANCE_M:
        obj.location = obj.location + back * shift
        start_world = start_world + back * shift
    # 4. Place (or keep) the diverter on the main line.
    s_face = s_at + (start_world - q).dot(_forward(h_t))
    layout = _probe_layout(context, target, 'DIVERTER', snapped, side, infeed_mm)
    s_module_start = s_face - layout.faces[1 if side == 'RIGHT' else -1][1]
    segs = target.conveyor_line.segments
    existing = next((i for i, sg in enumerate(segs) if _is_diverter(sg) and sg.merge_auto and sg.merge_source == obj.name), None)
    carry = {}
    if existing is not None:
        seg = segs[existing]
        _sp, _sg, _w, t_starts, _fr = _line_data(context, target)
        same = (abs(t_starts[existing] - s_module_start) <= POSITION_TOLERANCE_M and int(seg.merge_angle) == snapped
                and seg.merge_side == side and abs(_infeed(seg, side) - infeed_mm) <= 0.5)
        if same:
            _release_source(context, obj.name, keep_target=target, kinds=('DIVERTER',))
            _attach_branch(context, obj, target, existing, side)
            return
        carry = _choices(seg)
        _remove_junction(target, existing)
    _release_source(context, obj.name, keep_target=target, kinds=('DIVERTER',))
    if pinned:
        index = _insert_junction(context, target, s_module_start, snapped, side, infeed_mm, obj.name, module_kind='DIVERTER')
    else:  # slides to fit on one straight, the line's flow start following (see _sync)
        index = _insert_junction_fit(context, target, s_module_start, snapped, side, infeed_mm, obj.name, 'DIVERTER')
    if index is None:
        _rebuild(context, target)
        if undo_stretch is not None:
            # No dock after all: the line keeps the length the user gave it.
            count, length_mm = undo_stretch
            with suspended_rebuild():
                while len(settings.segments) > count:
                    settings.segments.remove(len(settings.segments) - 1)
                settings.segments[-1]["length_mm"] = length_mm
            _rebuild(context, obj)
        return
    if carry:
        _apply_choices(segs[index], carry)
    _rebuild(context, target)
    if not pinned:
        center, _fh, _geom = _module_face_world(context, target, index, side)
        start_world = _flow_start(obj, _line_data(context, obj)[0])[0]
        shift = center - start_world
        shift.z = 0.0
        if shift.length > POSITION_TOLERANCE_M:
            obj.location = obj.location + shift
            _remember_matrix(obj)
    _attach_branch(context, obj, target, index, side)


def _attach_branch(context, obj, target, index: int, side: str) -> bool:
    """Records where the branch's goods leave the main line (the face
    center's arc on the main's FULL spline) and the lateral blend length,
    then rebuilds the branch so its full spline starts with the main's path.
    Returns True when it rebuilt the branch."""
    settings = obj.conveyor_line
    center, dock_h, geom = _module_face_world(context, target, index, side, role='DIVERTER')
    poly, arc, heading = _flow_spine(target, full=True)  # headings already along the FLOW (turned round on a reversed main)
    _d, _q, s_center, h_at = _closest_on_polyline(center, poly, arc, heading)
    if _junction_angle(target.conveyor_line.segments[index]) >= RIGHT_ANGLE_DEG:
        # Right-angle transfer: no blend, the goods keep the main's heading.
        # (Adding another half turn here for a reversed main put the kept
        # yaw 180° out, and the goods spun half a turn across the corner:
        # user's file, 2026-10-10.)
        h_flow_world = h_at + target.rotation_euler.z
        blend, keep = 0.0, (0.0 if side == 'END' else _wrap(h_flow_world - dock_h))  # straight through the far face: unturned
    else:
        blend, keep = max(geom.y_landing - geom.face_center[1], 0.0) + 0.3, 0.0
    keep += _yaw_at(arc, _flow_yaw(target, full=True), s_center)  # goods already riding sideways on the main stay so
    before = tuple(settings.get(k) for k in BRANCH_KEYS)
    _set_branch(settings, target, s_center, blend, keep)
    if tuple(settings.get(k) for k in BRANCH_KEYS) != before:
        _rebuild(context, obj)
        return True
    return False


def _attach_continuation(context, obj, target, index: int, side: str) -> bool:
    """Records where the feeder's goods enter the target (the face center's
    arc length) and how long the lateral blend onto the centerline is, then
    rebuilds the feeder so its full spline continues onto the target.
    Returns True when it rebuilt the feeder."""
    settings = obj.conveyor_line
    center, _fh, geom = _module_face_world(context, target, index, side, role='MERGE')
    poly, arc, heading = _flow_spine(target, full=True)  # FULL flow arcs of the target
    _d, _q, s_center, _h = _closest_on_polyline(center, poly, arc, heading)
    blend = max(geom.y_landing - geom.face_center[1], 0.0) + 0.3
    before = tuple(settings.get(k) for k in CONTINUE_KEYS)
    _set_continuation(settings, target, s_center, blend)
    linked = _link_goods_on_attach(context, obj, target, target.conveyor_line.segments[index])  # a far-end dock too
    if linked or tuple(settings.get(k) for k in CONTINUE_KEYS) != before:
        _rebuild(context, obj)
        return True
    return False


# ------------------------------------------------------------ handlers --

_MATRIX_KEY = "conveyor_last_matrix"


def _matrix_flat(obj) -> list[float]:
    # From the object's own channels: matrix_world is stale right after the
    # add-on itself moved a line, and the key must describe where it IS.
    return [round(v, 5) for row in _world_matrix(obj) for v in row]


def _remember_matrix(obj) -> None:
    """Where the add-on left `obj`: the handler treats only a DIFFERENT
    matrix as a user move. (Without this, a line the add-on had just snapped
    looked moved on the next update and re-synced against a main line that
    the user had moved meanwhile -- it came loose instead of following.)"""
    from .sync_stats import note_write

    obj[_MATRIX_KEY] = _matrix_flat(obj)
    note_write()


_MASTER_MATERIALS_KEY = "conveyor_master_materials"


def _propagate_master_materials(context, lines) -> None:
    """A material changed on a MASTER line (one that other lines dock onto,
    directly or through further docks) is pushed to every line of its
    group, so recolouring the main conveyor recolours the whole system.
    Only changes propagate: a line's own edits stay until the master
    changes again."""
    from ..geonodes import materials
    from .build_line import sync_materials
    from .stream import dock_root

    roots = {}
    for line in lines:
        root = dock_root(context, line)
        roots.setdefault(root.name, (root, []))
        if line != root:
            roots[root.name][1].append(line)
    for root, children in roots.values():
        names = [m.name if m is not None else "" for m in materials.ensure_slots(root)]
        last = root.get(_MASTER_MATERIALS_KEY)
        if children and last is not None and list(last) != names:
            for child in children:
                materials.ensure_slots(child)
                for i, mat in enumerate(root.data.materials[:len(materials.SLOT_ROLES)]):
                    if child.data.materials[i] != mat:
                        child.data.materials[i] = mat
                sync_materials(child)
        if last is None or list(last) != names:
            root[_MASTER_MATERIALS_KEY] = names


_time_scale_seen: dict = {}  # scene name -> the clock value the lines were last pushed with
_scheduled: dict = {}  # scene name -> True while a deferred pass is pending (one per burst of updates)
SYNC_BUSY_KEY = "wh_sync_busy"  # bpy.app.driver_namespace flag every warehouse add-on's pass sets (R5)
LINE_ID_TYPES = (bpy.types.Object, bpy.types.Curves)


def _sync_busy() -> bool:
    try:
        return bool(bpy.app.driver_namespace.get(SYNC_BUSY_KEY))
    except Exception:
        return False


def _relevant(scene, depsgraph, lines) -> bool:
    """Does this depsgraph update call for a sync pass? Not for a frame step
    or our own builds (our lines' geometry re-evaluating, the scene ticking);
    yes for a transform, another object (added, selected, edited, a system
    republishing its ports), a material, a collection, a mesh (a floor)."""
    if depsgraph is None:
        return True  # a direct call without a graph (scripts, tests): assume something changed
    ours = set()
    for line in lines:
        ours.add(line.as_pointer())
        try:
            ours.add(line.data.as_pointer())
        except Exception:
            pass
    for update in depsgraph.updates:
        id_ = update.id
        orig = getattr(id_, "original", None) or id_
        if isinstance(orig, bpy.types.Scene):
            continue  # the frame ticked or a scene setting changed: our own property updates cover those
        if isinstance(orig, LINE_ID_TYPES) and orig.as_pointer() in ours:
            if update.is_updated_transform:
                return True  # a line was moved
            continue  # our own line re-evaluated (a frame step, our build, a selection flag)
        return True
    return False


@bpy.app.handlers.persistent
def _on_depsgraph_update(scene, depsgraph):
    """DETECT only (contract v2.1, R5): no ID-property, modifier or operator
    work in the handler. When the update matters it schedules ONE deferred
    pass (run_sync) on a timer; while any warehouse add-on's pass runs
    (driver_namespace["wh_sync_busy"]) it returns at once, so cross-add-on
    re-entry is impossible."""
    if _busy or _sync_busy():
        return
    from .build_line import all_lines

    lines = all_lines(scene)
    if not lines:
        return
    if _scheduled.get(scene.name) or not _relevant(scene, depsgraph, lines):
        return
    _scheduled[scene.name] = True
    bpy.app.timers.register(functools.partial(_deferred_pass, scene.name), first_interval=0)


def _deferred_pass(scene_name: str):
    _scheduled.pop(scene_name, None)
    scene = bpy.data.scenes.get(scene_name)
    if scene is not None:
        run_sync(scene)
    return None  # a one-shot timer


def run_sync(scene) -> int:
    """The deferred pass: everything the depsgraph handler used to do. It
    sets driver_namespace["wh_sync_busy"] for its writes (try / finally) and
    counts passes and writes in operators/sync_stats.STATS. Callable directly
    (timers never fire in `-b` tests). Returns the writes of this pass, or 0
    when another add-on's pass holds the flag (then it tries again next tick)."""
    from .sync_stats import STATS

    ns = bpy.app.driver_namespace
    if ns.get(SYNC_BUSY_KEY):
        if not _scheduled.get(scene.name):
            _scheduled[scene.name] = True
            bpy.app.timers.register(functools.partial(_deferred_pass, scene.name), first_interval=0.05)
        return 0
    STATS["passes"] += 1
    before = STATS["writes"]
    STATS["sites"].clear()  # the call sites of this pass's writes (sync_stats.TRACE)
    ns[SYNC_BUSY_KEY] = True
    try:
        _sync_pass(scene)
    finally:
        ns[SYNC_BUSY_KEY] = False
        STATS["last_writes"] = STATS["writes"] - before
    return STATS["last_writes"]


def _sync_pass(scene) -> None:
    """Transform changes fire no property callbacks, so watch the matrices:
    a moved feeder re-docks (or leaves), a moved main line pulls its docked
    feeders along by re-syncing them."""
    if _busy:
        return
    from .build_line import all_lines, build_line, highlight_index_for, migrate_removed_type, push_highlight, sync_materials
    from .sync_stats import note_write

    lines = all_lines(scene)
    for obj in lines:
        if migrate_removed_type(obj.conveyor_line):  # a line of a removed type (the cleated belt): its replacement, before anything reads it
            build_line(bpy.context, obj)
            note_write()
    for obj in lines:
        if push_highlight(obj, highlight_index_for(bpy.context, obj)):
            note_write()
        if sync_materials(obj):  # Material panel edits reach the node tree
            note_write()
    _propagate_master_materials(bpy.context, lines)
    if lines and scene.conveyor_settings.floor_collection is None:
        from .floors import sync_auto_floors

        sync_auto_floors(scene)  # a mesh added under a line becomes a floor for its legs

    # The shared clock (scene["wh_time_scale"]) changed under us: re-push speeds.
    from ..props.scene_settings import time_scale

    scale = time_scale(scene)
    if _time_scale_seen.get(scene.name) != scale:
        _time_scale_seen[scene.name] = scale
        from .build_line import push_time_scale

        push_time_scale(bpy.context, scene)
        note_write(len(lines))
    moved = []
    for obj in lines:
        flat = _matrix_flat(obj)
        if list(obj.get(_MATRIX_KEY, [])) != flat:
            obj[_MATRIX_KEY] = flat
            note_write()
            moved.append(obj)
    for obj in moved:
        sync_feeder(bpy.context, obj)
        # Lines docked on this line follow it (moved rigidly onto their
        # junction faces; they re-sync on the next pass as moved lines).
        for seg in obj.conveyor_line.segments:
            if _is_junction(seg):
                for name in _sources(seg):
                    feeder = scene.objects.get(name)
                    if feeder is not None and feeder not in moved:
                        follow_target(bpy.context, feeder, obj)
        for other in lines:  # the line carrying this one's goods on keeps its start at this end
            if other is not obj and other not in moved and other.conveyor_line.get(TAIL_KEY) == obj.name:
                follow_tail(bpy.context, other, obj)
    # Lines docked at rack ports: a port gone or its load changed.
    from .ports import sync_links

    try:
        sync_links(bpy.context, scene)
    except Exception:
        pass
    # Obstacle alerts (R13): a building or a line moved, an obstacle list changed.
    try:
        from .obstacles import sync as sync_obstacles

        sync_obstacles(bpy.context, scene)
    except Exception:
        pass
    # Hung lines follow their hall's clear height (R17): it changed, or a line moved.
    try:
        from .ceilings import sync as sync_ceilings

        sync_ceilings(bpy.context, scene)
    except Exception:
        pass
    # A takeaway deleted: the transfer whose exit side it widened is its own width again.
    from .rat_faces import stale_exit_faces

    for obj in stale_exit_faces(scene, lines):
        build_line(bpy.context, obj)
    # A deleted feeder leaves its junction behind: drop auto junctions whose source is gone.
    names = {o.name for o in scene.objects}
    for obj in lines:
        segs = obj.conveyor_line.segments
        stale = [i for i, s in enumerate(segs) if _is_junction(s) and any(n not in names for n in _sources(s))]
        if stale:
            for i in reversed(stale):
                if segs[i].merge_auto:
                    _remove_junction(obj, i)
                else:
                    for side in ('LEFT', 'RIGHT', 'END'):
                        if (side == 'RIGHT' and not _two_sided(segs[i])) or (side == 'END' and not _has_end_face(segs[i])):
                            continue
                        name = _source(segs[i], side)
                        if not name or name in names:
                            continue
                        renamed = _renamed_source(bpy.context, obj, i, side, lines)
                        if renamed is not None:
                            _set_source(segs[i], side, renamed.name)  # renamed, not deleted: its dock holds
                        else:
                            _free_face(segs[i], side)  # deleted: the face is its own width again (RAT-7)
            build_line(bpy.context, obj)
            # A RENAMED line (not a deleted one) still points here: dock it again.
            for other in lines:
                if other != obj and obj.name in (other.conveyor_line.get("continue_target"), other.conveyor_line.get("branch_target")):
                    sync_feeder(bpy.context, other)
    # Lines from before 2.22 get their Population from what their old settings
    # showed (operators/flows.migrate), once.
    from .flows import is_migrated, migrate

    if any(not is_migrated(obj) for obj in lines):
        try:
            for obj in migrate(bpy.context, lines):
                build_line(bpy.context, obj)
        except Exception as exc:
            print(f"conveyor: migrating to Population failed: {exc!r}")
    # Buffers from before 2.24 get their Output % from their Out rate (once a line).
    from .flows import BUFFERS_MIGRATED_KEY, migrate_buffers

    if any(not obj.conveyor_line.get(BUFFERS_MIGRATED_KEY) for obj in lines):
        try:
            for obj in migrate_buffers(bpy.context, lines):
                build_line(bpy.context, obj)
        except Exception as exc:
            print(f"conveyor: migrating buffers to Output % failed: {exc!r}")
    # Lines from an older file publish this version's records once (R22.1:
    # junction ports on the main lines, edge / share links on the docked ones).
    from .junction_ports import needs_republish
    from .ports import publish_line, refresh_links

    behind = [obj for obj in lines if needs_republish(obj)]
    for obj in behind:
        try:
            publish_line(bpy.context, obj)
        except Exception as exc:
            print(f"conveyor: republishing {obj.name} failed: {exc!r}")
    for obj in behind:
        refresh_links(bpy.context, obj)


class CONVEYOR_OT_detect_junctions(bpy.types.Operator):
    bl_idname = "conveyor.detect_junctions"
    bl_label = "Detect Junctions"
    bl_description = "Dock every line whose end aims at another line onto a merge junction there, and every line whose start leaves one onto a diverter (normally automatic)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from .build_line import all_lines

        for obj in all_lines(context.scene):
            sync_feeder(context, obj)
        return {'FINISHED'}


classes = (CONVEYOR_OT_detect_junctions, CONVEYOR_OT_detach, CONVEYOR_OT_dock)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    if _on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)


def unregister():
    if _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)
    _scheduled.clear()
    try:
        if bpy.app.driver_namespace.get(SYNC_BUSY_KEY):
            bpy.app.driver_namespace[SYNC_BUSY_KEY] = False  # never leave the shared flag set behind
    except Exception:
        pass
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
