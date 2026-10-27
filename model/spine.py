"""Writes a model.segments.Spine into a Blender `Curves` datablock.

The spine is the ONLY thing Geometry Nodes ever reads about a line's shape.
It is stored as a `Curves` (new curves type, object type 'CURVES') because
legacy `Curve` datablocks in Blender 5.3 expose no custom attributes, and
the whole v2 design rests on per-point `heading` / `incline` attributes.

Layout of the written datablock:
  - spline 0 (curve-domain `role` == ROLE_FULL): the whole spine as one
    continuous polyline. Populate and module placement sample this one
    by arc length.
  - splines 1..N (`role` == ROLE_RUN): one polyline per model.segments.Run.
    The cross-section sweeps the conveyor runs (`run_kind` == RUN_CONVEYOR)
    and skips module runs (`run_kind` == RUN_MODULE), whose footprint the
    module's own node group covers. Neighbouring runs share their boundary
    point (each gets its own copy) so rails meet the module face exactly.
Every point attribute is written identically on the full spline and on the
run copies, so any tree may read whichever spline suits it. The splines are
stored with Blender's default (Catmull-Rom) type and converted to Poly
inside the node trees -- see the note above _CRASHING_CURVE_TYPE_ATTRIBUTE.
"""
from __future__ import annotations

import bpy

from .segments import EXIT_IDS, KIND_LIFT, KIND_SPIRAL, MODULE_KIND_IDS, TECH_IDS, Module, Segment, Spine, insert_sample_at, runs

ROLE_FULL = 0
ROLE_RUN = 1
ROLE_FENCE = 2  # extra guide-rail paths (merge taper fences), see model/junction.py
ROLE_OUTLINE = 3  # closed deck outlines of merge junctions (filled by the tree)
GAP_EDGE_M = 0.005  # extra spine samples this far outside a fence opening
ROLE_GUIDE = 4  # continuous guide-rail / leg paths: consecutive runs joined, RAT and lift modules excluded
ROLE_COLUMN = 5  # support columns (spiral center, lift tower): 2-point splines, top point first
ROLE_ARM = 6  # spiral support arms: 2-point splines from the centre drum out under the track
# Transfer-section parts (model/transfer_parts.py), swept / instanced by the
# trees with the curve attributes part_r / part_h / part_mat:
ROLE_PART_ROLLER = 7  # roller axis (2 points), radius part_r
ROLE_PART_BELT = 8  # pop-up belt strip centreline
ROLE_PART_CHAIN = 9  # chain strand centreline
ROLE_PART_WHEEL = 10  # wheel / pulley axle (2 points), radius part_r
ROLE_PART_BOX = 11  # box centreline (2 points), width part_r, height part_h, part_mat
ROLE_PART_RAIL = 12  # frame rail polyline (rail profile centred on it)
ROLE_PART_PLATE = 13  # flat plate: closed level outline at its underside
ROLE_LIFT_LOOP = 14  # fork-column lift: the forks' path once round the loop (closed polyline), lift_index = which lift
PART_ROLES = {"ROLLER": ROLE_PART_ROLLER, "BELT": ROLE_PART_BELT, "CHAIN": ROLE_PART_CHAIN, "WHEEL": ROLE_PART_WHEEL,
              "BOX": ROLE_PART_BOX, "RAIL": ROLE_PART_RAIL, "PLATE": ROLE_PART_PLATE, "FENCE": ROLE_FENCE}
DRUM_RADIUS_M = 0.22  # a spiral's centre drum / a lift's tower post
RUN_CONVEYOR = 0
RUN_MODULE = 1

POINT_ATTRIBUTES = {
    "heading": 'FLOAT',
    "incline": 'FLOAT',
    "yaw_offset": 'FLOAT',
    "arc_len": 'FLOAT',
    "segment_index": 'INT',
    "kind": 'INT',
    "guide_gap": 'INT',  # bitmask: 1 = left guide rail open here, 2 = right
}
GAP_LEFT, GAP_RIGHT = 1, 2
CURVE_ATTRIBUTES = {
    "role": 'INT',
    "run_kind": 'INT',
    "module_kind": 'INT',
    "module_exit": 'INT',
    "module_length": 'FLOAT',
    "run_index": 'INT',
}

# The spine must be sampled as a POLY curve: `Curves` default to
# CATMULL_ROM, which smooths every kink, overshoots the pitch attribute
# (15 deg read as 15.23) and loops back where sample spacing changes.
# BUT writing `curve_type` = POLY (1) on the datablock itself corrupts
# memory in Blender 5.3.0 Alpha (hash 29ccd5e2e824, 2026-08-04): every
# evaluation of such a Curves ID overruns a BLI Vector and Blender crashes
# shortly after (viewport draw, undo, edit mode...), even with no modifier
# and no add-on. Reproduced 2026-09-23 with a 2-curve datablock. So the
# datablock stays Catmull-Rom (the harmless default) and every node tree
# converts it with a Set Spline Type (Poly) node as its FIRST step
# (see geonodes/cross_sections/common.split_spine). Blender's enum for
# reference: CATMULL_ROM = 0, POLY = 1, BEZIER = 2, NURBS = 3.
_CRASHING_CURVE_TYPE_ATTRIBUTE = "curve_type"


def _ensure_attribute(curves: bpy.types.Curves, name: str, data_type: str, domain: str):
    attr = curves.attributes.get(name)
    if attr is not None and (attr.data_type != data_type or attr.domain != domain):
        curves.attributes.remove(attr)
        attr = None
    if attr is None:
        attr = curves.attributes.new(name, data_type, domain)
    return attr


def _stand_ranges(spine: Spine, segments: list[Segment], run_list, no_stand_ends, no_stand=(),
                  line_ends=(False, False)) -> list[tuple[float, float, bool, bool]]:
    """The arc ranges that carry stands, as the node trees always placed them:
    the fence paths (consecutive runs joined, right-angle transfers and lifts
    left out) and each right-angle transfer on its own (a docked end flagged
    by `no_stand_ends`). Lifts stand on their own columns. Where a transfer
    meets the run beside it they share one stand, the transfer's
    (legs.share_joints; `no_stand`: the stretches without stands);
    `line_ends`: (start, end) of the line rest on another frame (a line
    docked on a transfer's face), no stand there."""
    from .legs import share_joints

    out: list[tuple[float, float, bool, bool]] = []
    carriers: list[bool] = []
    group = None
    for r in run_list:
        seg = segments[r.segment_indices[0]]
        a, b = spine.s[r.first_index], spine.s[r.last_index]
        if isinstance(seg, Module) and seg.kind in ("RAT", "LIFT"):
            if group is not None:
                out.append(tuple(group))
                carriers.append(False)
                group = None
            if seg.kind == "RAT":
                flags = (no_stand_ends or {}).get(r.segment_indices[0]) or (False, False)
                out.append((a, b, bool(flags[0]), bool(flags[1])))
                carriers.append(True)
        elif group is None:
            group = [a, b, False, False]
        else:
            group[1] = b
    if group is not None:
        out.append(tuple(group))
        carriers.append(False)
    out = share_joints(out, carriers, no_stand)
    if out and len(spine.s):
        if line_ends[0] and abs(out[0][0] - spine.s[0]) < 1e-6:
            out[0] = (out[0][0], out[0][1], True, out[0][3])
        if line_ends[1] and abs(out[-1][1] - spine.s[-1]) < 1e-6:
            out[-1] = (out[-1][0], out[-1][1], out[-1][2], True)
    return out


def write_spine(curves: bpy.types.Curves, spine: Spine, segments: list[Segment],
                guide_gaps: list[tuple[float, float, int]] = (), extras: list[tuple[int, list[tuple]]] = (),
                before: list[tuple] = (), after: list[tuple] = (), own_shift: float = 0.0,
                bracket_skips: list[tuple[float, float]] = (), reverse: bool = False,
                no_stand_ends: dict | None = None, leg_gaps: list[tuple[float, float]] = (),
                stand_plan: dict | None = None, rests_on=(False, False)) -> dict:
    """Replaces the contents of `curves` with `spine` (see module docstring).
    `no_stand_ends`: {segment index: (start, end)} -- True where a module
    run's first / last point gets no floor stand (the frame it docks on
    carries that end; the leg stage reads `no_legs`).
    `leg_gaps` are (start_s, end_s) leg-free stretches (pieces with Legs off,
    model/legs.py): `no_legs` is 1 inside them. `rests_on`: (start, end) of
    the line sit on another frame (a right-angle transfer's face): no stand there.
    `stand_plan` ({"spacing", "size", "carried": [(a, b)], "removed": [arcs], "added": [arcs]})
    plans the stands along the runs that carry them (model/legs.plan_stands):
    each gets an exact sample marked `stand` = 1, each stand the user took out
    one marked -1; the node trees place stands at the marked samples only
    (geonodes/cross_sections/common.support_stations). Returns the plan:
    {"stands": [arcs], "removed": [arcs], "added": [(arc, k)], "gaps": [arcs], "longest_span": metres,
    "path_length": the full spline's length, metres}.
    `guide_gaps` are (start_s, end_s, bit) ranges in meters where a guide
    rail is open; exact samples are inserted at their boundaries.
    `extras` are (role, polyline) pairs of (x, y, z, heading) points in local
    space: ROLE_FENCE splines are swept with the guide-rail profile
    (centered, no lateral offset), ROLE_OUTLINE closed polygons are filled
    into merge-junction decks. Nothing else reads them.
    `continuation` extends the FULL spline (only) past the line's end with
    (x, y, z, heading, incline, arc_len) points in local space: the path a
    docked feeder's goods follow onto the main line, so the populate
    stream flows from one conveyor to the next (segment_index -1, so no
    run, highlight or leg is built on it). `prefix` is the same kind of
    list PREPENDED to the full spline (segment_index -2): the main line's
    path a branch's routed goods travel before they leave onto the branch;
    the line's own arc lengths on the full spline are shifted by the
    prefix's length so the populate stream matches the main line's."""
    leg_gaps = [(float(a), float(b)) for a, b in leg_gaps if float(b) > float(a)]
    plan = {"stands": [], "removed": [], "removed_sources": [], "added": [], "gaps": [], "longest_span": 0.0}
    if stand_plan is not None:
        from .legs import plan_stands

        carried = [(float(a), float(b)) for a, b in stand_plan.get("carried", ())]
        ranges = _stand_ranges(spine, segments, runs(spine, segments), no_stand_ends, leg_gaps + carried, rests_on)
        sources: list[int] = []
        added: list = []
        gaps: list = []
        stands, removed_at, longest = plan_stands(ranges, stand_plan.get("spacing", 1.5), stand_plan.get("size", 0.06),
                                                  leg_gaps, stand_plan.get("removed", ()), sources, carried,
                                                  stand_plan.get("added", ()), added, gaps)
        for s_val in stands + removed_at:
            insert_sample_at(spine, s_val)
        plan = {"stands": stands, "removed": removed_at, "removed_sources": sources, "added": added, "gaps": gaps,
                "longest_span": longest}
    bracket_skips = list(bracket_skips)
    for start_s, end_s in bracket_skips:
        for s_val in (start_s, end_s, start_s - GAP_EDGE_M, end_s + GAP_EDGE_M):
            insert_sample_at(spine, s_val)
    for start_s, end_s, _bit in guide_gaps:
        # Boundary samples inside the opening, plus samples 5 mm OUTSIDE it:
        # attributes interpolate linearly between spine points, so without
        # them a resampled bracket point metres upstream still read "open".
        insert_sample_at(spine, start_s)
        insert_sample_at(spine, end_s)
        insert_sample_at(spine, start_s - GAP_EDGE_M)
        insert_sample_at(spine, end_s + GAP_EDGE_M)
    # Stretches where no guide bracket is placed: a docked end (the merge
    # face) or a docked start (a diverter face). Resample Curve always keeps
    # the curve's end points, so without this a bracket pair stood in the
    # middle of every merge wedge.
    skip_flags = [1.0 if any(a - 1e-9 <= s_val <= b + 1e-9 for a, b in bracket_skips) else 0.0 for s_val in spine.s]
    # Lane scale: 1 where goods keep their Lane Offset, ramping to 0 over an
    # angled-roller centre / align module and 0 after it (in FLOW order: mirrored on
    # a reversed line). Interpolated linearly along the spline.
    ramps = []
    for i, seg in enumerate(segments):
        if isinstance(seg, Module) and seg.center:
            idx = [k for k, si in enumerate(spine.segment_index) if si == i]
            if idx:
                s0 = spine.s[idx[0] - 1] if idx[0] > 0 else spine.s[idx[0]]
                s1 = spine.s[idx[-1]]
                ramps.append((s0, s1))

    def lane_scale_at(s_val: float) -> float:
        scale = 1.0
        for s0, s1 in ramps:
            span = max(s1 - s0, 1e-9)
            t = min(1.0, max(0.0, (s_val - s0) / span))
            scale = min(scale, (t if reverse else 1.0 - t))
        return scale

    lane_scales = [lane_scale_at(s_val) for s_val in spine.s]
    gap_bits = []
    for s_val in spine.s:
        bits = 0
        for start_s, end_s, bit in guide_gaps:
            if start_s - 1e-6 <= s_val <= end_s + 1e-6:
                bits |= bit
        gap_bits.append(bits)
    leg_free = [any(a - 1e-6 <= s_val <= b + 1e-6 for a, b in leg_gaps) for s_val in spine.s]
    stand_marks = []
    for s_val in spine.s:
        mark = 0.0
        if any(abs(s_val - x) < 2e-6 for x in plan["stands"]):
            mark = 1.0
        elif any(abs(s_val - x) < 2e-6 for x in plan["removed"]):
            mark = -1.0
        stand_marks.append(mark)
    run_list = runs(spine, segments)
    n_full = len(spine)
    no_stand: set[int] = set()
    for r in run_list:
        flags = (no_stand_ends or {}).get(r.segment_indices[0])
        if flags:
            if flags[0]:
                no_stand.add(r.first_index)
            if flags[1]:
                no_stand.add(r.last_index)
    # `before` / `after` extend the FULL spline in GEOMETRIC order with
    # (x, y, z, heading, incline, arc[, yaw_offset]) points carrying absolute
    # arc lengths; the line's own arcs are shifted by `own_shift`. They hold
    # the docked main line's path (operators/build_line.py composes them
    # from the flow-wise prefix / continuation, mirrored for reversed lines).
    before = list(before)
    after = list(after)
    prefix_len = float(own_shift)
    extras = [(e[0], e[1], (e[2] if len(e) > 2 else {})) for e in extras if len(e[1]) >= 2]
    # Guide paths: fences and legs are swept over ONE spline per stretch
    # between RAT modules (junctions included), so there are no seams,
    # open rail ends or doubled legs at module boundaries.
    guide_groups: list[list] = []
    for r in run_list:
        seg = segments[r.segment_indices[0]]
        is_rat = isinstance(seg, Module) and seg.kind in ("RAT", "LIFT")
        if is_rat:
            guide_groups.append([r.first_index, r.last_index, True])
        elif not guide_groups or guide_groups[-1][2]:
            guide_groups.append([r.first_index, r.last_index, False])
        else:
            guide_groups[-1][1] = r.last_index
    guide_groups = [(a, b) for a, b, rat in guide_groups if not rat and b > a]
    sizes = ([len(before) + n_full + len(after)] + [r.last_index - r.first_index + 1 for r in run_list]
             + [b - a + 1 for a, b in guide_groups] + [len(pts) for _r, pts, _a in extras])

    if len(curves.curves) > 0:
        curves.remove_curves()
    curves.add_curves(sizes)

    positions: list[float] = []
    heading: list[float] = []
    incline: list[float] = []
    yaw_offset: list[float] = []
    arc_len: list[float] = []
    segment_index: list[int] = []
    kind: list[int] = []
    guide_gap: list[int] = []
    bracket_skip: list[float] = []
    item_level: list[float] = []  # 1 where goods stay level (vertical lifts)
    lane_scale: list[float] = []  # Lane Offset multiplier (angled-roller centre modules)
    no_legs: list[float] = []  # 1 where no floor stand is placed (spirals hang on their drum, leg-free pieces)
    stand: list[float] = []  # 1 at a planned stand, -1 where the user took one out (model/legs.plan_stands)

    def emit(i: int, arc_shift: float = 0.0) -> None:
        guide_gap.append(gap_bits[i])
        bracket_skip.append(skip_flags[i])
        item_level.append(1.0 if spine.kind[i] == KIND_LIFT else 0.0)
        lane_scale.append(lane_scales[i])
        no_legs.append(1.0 if spine.kind[i] == KIND_SPIRAL or i in no_stand or leg_free[i] else 0.0)
        stand.append(stand_marks[i])
        positions.extend((spine.x[i], spine.y[i], spine.z[i]))
        heading.append(spine.heading[i])
        incline.append(spine.incline[i])
        yaw_offset.append(spine.yaw_offset[i])
        arc_len.append(spine.s[i] + arc_shift)
        segment_index.append(spine.segment_index[i])
        kind.append(spine.kind[i])

    def emit_extra(pt, seg_i: int) -> None:
        cx, cy, cz, ch, ci, cs = pt[:6]
        guide_gap.append(0)
        bracket_skip.append(0.0)
        item_level.append(0.0)
        lane_scale.append(lane_scales[-1] if (seg_i == -1) != reverse else lane_scales[0])
        no_legs.append(0.0)
        stand.append(0.0)
        positions.extend((cx, cy, cz))
        heading.append(ch)
        incline.append(ci)
        yaw_offset.append(pt[6] if len(pt) > 6 else 0.0)
        arc_len.append(cs)
        segment_index.append(seg_i)
        kind.append(0)

    for pt in before:
        emit_extra(pt, -2)
    for i in range(n_full):
        emit(i, prefix_len)
    for pt in after:
        emit_extra(pt, -1)
    for r in run_list:
        for i in range(r.first_index, r.last_index + 1):
            emit(i)
    for a, b in guide_groups:
        for i in range(a, b + 1):
            emit(i)
    for _role_id, pts, _attrs in extras:
        for fx, fy, fz, fh in pts:
            guide_gap.append(0)
            bracket_skip.append(0.0)
            item_level.append(0.0)
            lane_scale.append(1.0)
            no_legs.append(0.0)
            stand.append(0.0)
            positions.extend((fx, fy, fz))
            heading.append(fh)
            incline.append(0.0)
            yaw_offset.append(0.0)
            arc_len.append(0.0)
            segment_index.append(-1)
            kind.append(0)

    curves.attributes["position"].data.foreach_set("vector", positions)
    for name, values in (
        ("heading", heading),
        ("incline", incline),
        ("yaw_offset", yaw_offset),
        ("arc_len", arc_len),
    ):
        _ensure_attribute(curves, name, 'FLOAT', 'POINT').data.foreach_set("value", values)
    _ensure_attribute(curves, "segment_index", 'INT', 'POINT').data.foreach_set("value", segment_index)
    _ensure_attribute(curves, "kind", 'INT', 'POINT').data.foreach_set("value", kind)
    _ensure_attribute(curves, "guide_gap", 'INT', 'POINT').data.foreach_set("value", guide_gap)
    _ensure_attribute(curves, "bracket_skip", 'FLOAT', 'POINT').data.foreach_set("value", bracket_skip)
    _ensure_attribute(curves, "item_level", 'FLOAT', 'POINT').data.foreach_set("value", item_level)
    _ensure_attribute(curves, "lane_scale", 'FLOAT', 'POINT').data.foreach_set("value", lane_scale)
    _ensure_attribute(curves, "no_legs", 'FLOAT', 'POINT').data.foreach_set("value", no_legs)
    _ensure_attribute(curves, "stand", 'FLOAT', 'POINT').data.foreach_set("value", stand)

    n_fence = len(extras) + len(guide_groups)  # extra splines carrying default curve attributes
    role = [ROLE_FULL] + [ROLE_RUN] * len(run_list) + [ROLE_GUIDE] * len(guide_groups) + [role_id for role_id, _pts, _a in extras]
    run_kind = [RUN_CONVEYOR] + [RUN_MODULE if r.is_module else RUN_CONVEYOR for r in run_list] + [RUN_CONVEYOR] * n_fence
    module_kind = [0]
    module_exit = [0]
    module_length = [0.0]
    module_tech = [0]
    module_skew = [0.0]
    module_side = [0]
    module_center = [0]
    module_flip = [0]
    for r in run_list:
        seg = segments[r.segment_indices[0]]
        if isinstance(seg, Module):
            module_kind.append(MODULE_KIND_IDS.get(seg.kind, 0))
            module_exit.append(EXIT_IDS.get(seg.exit, 0))
            module_length.append(seg.length_m)
            module_tech.append(TECH_IDS.get(seg.tech, 0))
            module_skew.append(seg.skew)
            module_side.append(seg.side)
            module_center.append(1 if seg.center else 0)
            module_flip.append(1 if seg.flip else 0)
        else:
            module_kind.append(0)
            module_exit.append(0)
            module_length.append(0.0)
            module_tech.append(0)
            module_skew.append(0.0)
            module_side.append(0)
            module_center.append(0)
            module_flip.append(0)
    n_guides = len(guide_groups)
    module_kind += [0] * n_fence
    module_exit += [0] * n_fence
    module_length += [0.0] * n_fence
    # Extras (outlines, fences, columns) may name the junction they belong to.
    module_tech += [0] * n_guides + [int(a.get("module_tech", 0)) for _r, _p, a in extras]
    module_skew += [0.0] * n_guides + [float(a.get("module_skew", 0.0)) for _r, _p, a in extras]
    module_side += [0] * n_guides + [int(a.get("module_side", 0)) for _r, _p, a in extras]
    module_center += [0] * n_fence
    module_flip += [0] * n_guides + [int(a.get("module_flip", 0)) for _r, _p, a in extras]
    n_head = 1 + len(run_list) + n_guides  # splines before the extras
    part_r = [0.0] * n_head + [float(a.get("part_r", 0.0)) for _r, _p, a in extras]
    part_h = [0.0] * n_head + [float(a.get("part_h", 0.0)) for _r, _p, a in extras]
    part_mat = [0] * n_head + [int(a.get("part_mat", 0)) for _r, _p, a in extras]
    part_lift = [0.0] * n_head + [float(a.get("part_lift", 0.0)) for _r, _p, a in extras]
    part_tr = [0] * n_head + [int(a.get("part_tr", 0)) for _r, _p, a in extras]
    lift_index = [0] * n_head + [int(a.get("lift_index", 0)) for _r, _p, a in extras]
    run_index = [-1] + list(range(len(run_list))) + [-1] * n_fence

    _ensure_attribute(curves, "role", 'INT', 'CURVE').data.foreach_set("value", role)
    _ensure_attribute(curves, "run_kind", 'INT', 'CURVE').data.foreach_set("value", run_kind)
    _ensure_attribute(curves, "module_kind", 'INT', 'CURVE').data.foreach_set("value", module_kind)
    _ensure_attribute(curves, "module_exit", 'INT', 'CURVE').data.foreach_set("value", module_exit)
    _ensure_attribute(curves, "module_length", 'FLOAT', 'CURVE').data.foreach_set("value", module_length)
    _ensure_attribute(curves, "module_tech", 'INT', 'CURVE').data.foreach_set("value", module_tech)
    _ensure_attribute(curves, "module_skew", 'FLOAT', 'CURVE').data.foreach_set("value", module_skew)
    _ensure_attribute(curves, "module_side", 'INT', 'CURVE').data.foreach_set("value", module_side)
    _ensure_attribute(curves, "module_center", 'INT', 'CURVE').data.foreach_set("value", module_center)
    _ensure_attribute(curves, "module_flip", 'INT', 'CURVE').data.foreach_set("value", module_flip)
    _ensure_attribute(curves, "part_r", 'FLOAT', 'CURVE').data.foreach_set("value", part_r)
    _ensure_attribute(curves, "part_h", 'FLOAT', 'CURVE').data.foreach_set("value", part_h)
    _ensure_attribute(curves, "part_mat", 'INT', 'CURVE').data.foreach_set("value", part_mat)
    _ensure_attribute(curves, "part_lift", 'FLOAT', 'CURVE').data.foreach_set("value", part_lift)
    _ensure_attribute(curves, "part_tr", 'INT', 'CURVE').data.foreach_set("value", part_tr)
    _ensure_attribute(curves, "lift_index", 'INT', 'CURVE').data.foreach_set("value", lift_index)
    _ensure_attribute(curves, "run_index", 'INT', 'CURVE').data.foreach_set("value", run_index)
    # Lines written by earlier builds carry the crashing attribute: drop it.
    stale = curves.attributes.get(_CRASHING_CURVE_TYPE_ATTRIBUTE)
    if stale is not None:
        curves.attributes.remove(stale)

    curves.update_tag()
    plan["path_length"] = full_path_length(positions, len(before) + n_full + len(after))
    return plan


def full_path_length(positions: list[float], n: int) -> float:
    """Length of the polyline through the first `n` points of a flat xyz list:
    the full spline (spline 0) as the node trees draw goods on it, by length
    (a branch's blend off the main runs a little longer than its arcs say)."""
    total = 0.0
    for k in range(3, 3 * n, 3):
        dx = positions[k] - positions[k - 3]
        dy = positions[k + 1] - positions[k - 2]
        dz = positions[k + 2] - positions[k - 1]
        total += (dx * dx + dy * dy + dz * dz) ** 0.5
    return total


POINT_ATTRIBUTE_DEFAULTS = {"item_level": ('FLOAT', 0.0), "lane_scale": ('FLOAT', 1.0), "bracket_skip": ('FLOAT', 0.0),
                            "no_legs": ('FLOAT', 0.0), "stand": ('FLOAT', 0.0)}
CURVE_ATTRIBUTE_DEFAULTS = {"module_tech": ('INT', 0), "module_side": ('INT', 0), "module_center": ('INT', 0),
                            "module_flip": ('INT', 0), "module_skew": ('FLOAT', 0.0),
                            "part_r": ('FLOAT', 0.0), "part_h": ('FLOAT', 0.0), "part_mat": ('INT', 0),
                            "part_lift": ('FLOAT', 0.0), "part_tr": ('INT', 0), "lift_index": ('INT', 0)}


def ensure_attribute_defaults(curves: bpy.types.Curves) -> None:
    """Adds attributes a newer tree samples to a spine written by an older
    build (with their neutral values), so lines that have not been rebuilt
    yet keep working after an update (a missing attribute samples as 0)."""
    for domain, table in (('POINT', POINT_ATTRIBUTE_DEFAULTS), ('CURVE', CURVE_ATTRIBUTE_DEFAULTS)):
        for name, (data_type, default) in table.items():
            if name in curves.attributes:
                continue
            attr = curves.attributes.new(name, data_type, domain)
            attr.data.foreach_set("value", [default] * len(attr.data))
