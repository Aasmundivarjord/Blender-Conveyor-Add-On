"""The hub: turns a line's settings into its spine (and, from build step 2
on, its Geometry Nodes modifier). Every property update callback and every
operator that changes a line ends up here.
"""
from __future__ import annotations

import math

import bpy

from ..config import loader, units
from ..geonodes import builder_common as bc
from ..geonodes.cross_sections import belt as belt_tree
from ..geonodes.cross_sections import chain as chain_tree
from ..geonodes.cross_sections import omni as omni_tree
from ..geonodes.cross_sections import pouch as pouch_tree
from ..geonodes.cross_sections import roller as roller_tree
from ..model import segments as seg_model
from ..model import spine as spine_io
from ..model import lift_parts, transfer_parts

MODIFIER_NAME = "Conveyor"

# Frame figures shared by every cross-section. Re-pushed on EVERY build:
# a modifier's cached input values are keyed by socket identifier, and a
# rebuilt tree orphans them -- v1 lost its legs and rails to exactly that.
_FRAME_DEFAULTS = {
    "Roller Overhang": 0.006,
    "Rail Height": 0.10,
    "Rail Thickness": 0.02,
    "Rail Top Drop": 0.015,
    "Support Spacing": 1.5,
    "Support Size": 0.06,
    "Floor Z": 0.0,
    "Guide Rails": True,
    "Guide Rail Rise": 0.12,
    "Guide Rail Height": 0.06,
    "Guide Rail Thickness": 0.008,
    "Guide Bracket Pitch": 1.0,
}

# ConveyorTypeSpec.cross_section -> line-tree builder. belt/chain land in
# build step 4 and fall back to the roller tree until then.
_LINE_TREE_BUILDERS = {
    "roller": roller_tree.build,
    "belt": belt_tree.build,
    "chain": chain_tree.build,
    "omni": omni_tree.build,
    "pouch": pouch_tree.build,
}
_LINE_TREE_MODULES = (roller_tree, belt_tree, chain_tree, omni_tree, pouch_tree)
_TREE_NAMES = {"roller": roller_tree.NODE_GROUP_NAME, "belt": belt_tree.NODE_GROUP_NAME, "chain": chain_tree.NODE_GROUP_NAME,
               "omni": omni_tree.NODE_GROUP_NAME, "pouch": pouch_tree.NODE_GROUP_NAME}
BRACKET_FREE_M = 0.2  # no guide brackets this close to a docked end/start (they would stand in the junction)
SPIRAL_ARM_H = 0.08  # height of a spiral's cantilever arms

# Belt / chain figures (engineering estimates, see roller_specs.json notes).
_BELT_DEFAULTS = {"Belt Thickness": 0.01, "Idler Pitch": 0.3}
_CHAIN_DEFAULTS = {"Link Pitch": 0.0508, "Link Thickness": 0.012, "Link Gap": 0.004, "Sprocket Diameter": 0.10}


def resolve_high_detail(context, settings) -> bool:
    """Always full detail since 2026-09-23: the user replaced the High/Low
    switch (and the scene-wide override) with a direct roller pitch. The
    node input stays so older trees keep working."""
    return True


# The catalog quotes the real roller pitch; the user asked twice for
# visibly tighter rollers, so a new line starts at this fraction of it.
DEFAULT_PITCH_FACTOR = 0.5


def _duty(settings):
    conveyor_type = loader.get_conveyor_types()[settings.conveyor_type]
    return loader.get_roller_duty_classes().get(conveyor_type.default_duty_class or "standard")


def catalog_roller_pitch_mm(settings) -> float:
    duty = _duty(settings)
    return duty.pitch_mm if duty else 76.2


def min_roller_pitch_mm(settings) -> float:
    """Rollers may not overlap: diameter plus the small gap the tree enforces."""
    duty = _duty(settings)
    return (duty.diameter_mm if duty else 48.3) + bc_min_gap_mm()


def bc_min_gap_mm() -> float:
    from ..geonodes.cross_sections.common import MIN_CYLINDER_GAP

    return MIN_CYLINDER_GAP * 1000.0


def effective_roller_pitch_mm(settings) -> float:
    if settings.roller_pitch_mm > 0.0:
        return max(settings.roller_pitch_mm, min_roller_pitch_mm(settings))
    return max(catalog_roller_pitch_mm(settings) * DEFAULT_PITCH_FACTOR, min_roller_pitch_mm(settings))


def resolve_width_mm(settings) -> float:
    ctype = loader.get_conveyor_types().get(settings.conveyor_type)
    if ctype is not None and ctype.cross_section == "pouch":
        # A pouch sorter is as wide as its pouches (its footprint, ports and switches).
        from ..model import pouch as pouch_model

        return pouch_model.pouch_dims_mm(settings.pouch_size, settings.pouch_width_mm, settings.pouch_height_mm, settings.pouch_depth_mm)[0]
    if settings.width_preset == 'CUSTOM':
        return settings.custom_width_mm
    preset = loader.get_width_preset_by_id(settings.width_preset)
    return preset.width_mm if preset else settings.custom_width_mm


def migrate_removed_type(settings) -> bool:
    """A line saved with a type since removed takes its replacement
    (props.line_settings.REPLACED_TYPES: the cleated belt a belt, the
    powered roller a roller). True when it changed; the caller rebuilds."""
    if settings.conveyor_type in loader.get_conveyor_types():
        return False
    from ..props.line_settings import REPLACED_TYPES

    settings["conveyor_type"] = REPLACED_TYPES.get(settings.get("conveyor_type"), 0)
    return True


def migrate_legacy_segments(settings) -> None:
    """Files saved before 2026-09-23 store curve angles in an enum and
    elevation as a separate INCLINE kind. Fold both into the current
    properties (integer angle, `rise_mm` on straights) without triggering
    rebuild callbacks; the caller rebuilds once."""
    from ..props.line_settings import segment_rise_mm, suspended_rebuild

    with suspended_rebuild():
        if settings.roller_pitch_mm <= 0.0:
            settings["roller_pitch_mm"] = effective_roller_pitch_mm(settings)
        for seg in settings.segments:
            if seg.kind == 'CURVE' and seg.curve_angle_deg == 0:
                try:
                    seg["curve_angle_deg"] = int(seg.curve_angle)
                except (TypeError, ValueError):
                    pass
            elif seg.kind == 'INCLINE':
                rise = segment_rise_mm(seg)
                seg.kind = 'STRAIGHT'
                seg["rise_mm"] = rise


def junction_sides(seg) -> tuple[int, ...]:
    return {'LEFT': (-1,), 'RIGHT': (1,), 'BOTH': (1, -1)}[seg.merge_side]


def infeed_for_side(seg, side: int) -> float:
    """Infeed width (mm) of a junction's face: the right face of a
    two-sided junction has its own (0 = as wide as the left one)."""
    if side > 0 and seg.merge_side == 'BOTH' and seg.merge_infeed_right_mm > 0.0:
        return float(seg.merge_infeed_right_mm)
    return float(seg.merge_infeed_mm)


def merge_layout_for(seg, settings, scene):
    """Junction layout of a MERGE or DIVERTER module segment (model/junction.py)
    in the module's local frame; the footprint length is derived from it."""
    from ..geonodes.modules.common import SIDE_PLATE
    from ..model import junction

    width_m = units.mm_to_bu(resolve_width_mm(settings), scene)
    infeeds = {sd: units.mm_to_bu(infeed_for_side(seg, sd), scene) for sd in junction_sides(seg)}
    fence_offset = width_m / 2.0 + _FRAME_DEFAULTS["Rail Thickness"] / 2.0  # = geonodes rail_offset: fences sit over the frame rails
    layout = junction.junction_layout(float(seg.merge_angle), infeeds, width_m / 2.0 + SIDE_PLATE, junction_sides(seg),
                                      fence_offset_m=fence_offset, fence_inset_m=_FRAME_DEFAULTS["Rail Thickness"] / 2.0)
    # The wedge opens along the FLOW: downstream for a merge, upstream for a
    # diverter. On a reversed line the flow runs against the geometry, so
    # the roles swap.
    if (seg.module_kind == 'DIVERTER') != bool(settings.reverse):
        layout = junction.mirror_layout(layout)
    return layout


def merge_geometry_for(seg, settings, scene, side: int | None = None):
    """Single-side geometry of a junction (its first side when `side` is None)."""
    layout = merge_layout_for(seg, settings, scene)
    if side is None:
        side = junction_sides(seg)[0]
    return layout.sides[side]


def resolve_junction_tech(seg) -> str:
    """The technology a MERGE / DIVERTER is built with: the user's choice
    when it exists for that role and angle, else the default: an angled
    roller merge below 90 deg, the high-performance divert (HPD) for angled
    diverts, and the pop-up belt right-angle transfer at 90 deg."""
    techs = loader.get_technologies()
    role = seg.module_kind
    angle = int(seg.merge_angle)
    choice = getattr(seg, "junction_tech", 'AUTO')
    if choice in techs and role in techs[choice].roles and angle in techs[choice].angles:
        return choice
    if angle >= 90:
        return 'BELT'
    return 'SKEW' if role == 'MERGE' else 'STRIP'


def junction_module_fields(seg, settings) -> dict:
    """Module fields describing a junction to the node trees: technology,
    the transfer direction relative to the heading (skew), the geometric
    side of the face and whether the layout is mirrored."""
    theta = math.radians(float(seg.merge_angle))
    sd = junction_sides(seg)[0]
    flow_right = (sd > 0) != bool(settings.reverse)
    turn = theta if flow_right else -theta
    sign = -1.0 if seg.module_kind == 'DIVERTER' else 1.0
    return {"tech": resolve_junction_tech(seg), "skew": sign * turn, "side": int(sd),
            "flip": (seg.module_kind == 'DIVERTER') != bool(settings.reverse)}


def _transfer_frame(settings, width_m: float, scene) -> "transfer_parts.Frame":
    """The line's frame / roller figures for its transfer sections."""
    duty = _duty(settings)
    roller_r = units.mm_to_bu((duty.diameter_mm if duty else 48.3) / 2.0, scene)
    return transfer_parts.Frame(width=width_m, roller_r=roller_r, pitch=units.mm_to_bu(effective_roller_pitch_mm(settings), scene),
                                rail_t=_FRAME_DEFAULTS["Rail Thickness"], rail_h=_FRAME_DEFAULTS["Rail Height"],
                                rail_drop=_FRAME_DEFAULTS["Rail Top Drop"])


def _fence_points(line_pts, to_local) -> list:
    """A transfer's fence polyline as spine points, each with the heading of
    the polyline's own direction. The tree sweeps a fence with its normal
    LEFT of the point heading; a guard ACROSS the line (an end stop) given
    the module's heading had its normal along itself and swept flat -- a
    standalone transfer's start and end faces looked open."""
    out = []
    n = len(line_pts)
    for k, (px, py, pz) in enumerate(line_pts):
        a, b = line_pts[max(k - 1, 0)], line_pts[min(k + 1, n - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        mh = math.atan2(-dx, dy) if (abs(dx) > 1e-9 or abs(dy) > 1e-9) else 0.0  # frame: heading 0 = +Y, left = -X
        out.append(to_local(px, py, mh, pz))
    return out


def _add_parts(extras: list, parts, to_local) -> None:
    """Transfer parts (module frame) -> spine extras (line frame)."""
    for p in parts:
        role = spine_io.PART_ROLES[p.kind]
        pts = [to_local(x, y, 0.0, z) for x, y, z in p.points]
        extras.append((role, pts, {"part_r": p.r, "part_h": p.h, "part_mat": p.mat, "part_lift": p.lift, "part_tr": p.tr}))


POPUP_TECHS = ('BELT', 'CHAIN', 'POPUP')  # transfers whose belts / chains / wheels pop up (animated at 90 degrees)


def transfer_id(line_name: str, index: int) -> int:
    """Stable id of the pop-up transfer in segment `index` of a line: its
    moving parts carry it (spine attribute part_tr) and operators/stream.py
    pushes the times it works under the same id."""
    import zlib

    return 1 + zlib.crc32(f"{line_name}|{index}".encode()) % 2_000_000_000


def animated_transfer(seg, settings) -> bool:
    """A junction whose transfer pops up to carry goods at a right angle."""
    return (seg.kind == 'MODULE' and seg.module_kind in ('MERGE', 'DIVERTER') and int(seg.merge_angle) == 90
            and resolve_junction_tech(seg) in POPUP_TECHS)


def segments_from_settings(settings, scene: bpy.types.Scene) -> list[seg_model.Segment]:
    from ..props.line_settings import segment_curve_angle_deg, segment_curve_radius_mm, segment_rise_mm

    catalog = loader.get_segment_catalog()
    out: list[seg_model.Segment] = []
    for seg in settings.segments:
        if seg.kind in ('STRAIGHT', 'INCLINE'):
            length_m = units.mm_to_bu(seg.length_mm, scene)
            rise_m = units.mm_to_bu(segment_rise_mm(seg), scene)
            if abs(rise_m) > 1e-6:
                out.append(seg_model.Incline(seg_model.incline_from_rise(rise_m, length_m), length_m))
            else:
                out.append(seg_model.Straight(length_m))
        elif seg.kind == 'CURVE':
            out.append(
                seg_model.Curve(
                    float(segment_curve_angle_deg(seg)),
                    units.mm_to_bu(segment_curve_radius_mm(seg), scene),
                    seg.curve_direction,
                )
            )
        elif seg.kind == 'SPIRAL':
            out.append(seg_model.Spiral(360.0 * max(seg.spiral_turns, 0.05), units.mm_to_bu(segment_curve_radius_mm(seg), scene),
                                        seg.curve_direction, units.mm_to_bu(seg.rise_mm, scene)))
        elif seg.kind == 'MODULE':
            spec = catalog.modules[seg.module_kind]
            exit_side = seg.module_exit if spec.allows_exit else 'STRAIGHT'
            # Footprint: the segment's own length (RAT: user-editable so other
            # lines can dock along it; MERGE: fitted to the target by
            # detect_junctions), never below the module minimum.
            from ..props.line_settings import MODULE_MIN_LENGTH_MM

            if seg.module_kind == 'ARB':
                fn = seg.arb_function
                turn = 0.0 if fn == 'CENTER' else (math.pi / 2.0 if fn == 'TURN_LEFT' else -math.pi / 2.0)
                kind = 'PIVOT' if (seg.arb_pivot and fn != 'CENTER') else 'ARB'
                length_mm = max(seg.length_mm, MODULE_MIN_LENGTH_MM) if seg.length_mm > 0 else spec.length_mm
                out.append(seg_model.Module(kind, units.mm_to_bu(length_mm, scene), 'STRAIGHT', tech=kind,
                                            skew=math.radians(30.0) * (1.0 if fn != 'TURN_RIGHT' else -1.0), turn=turn,
                                            center=(fn == 'CENTER'), side=(0 if fn == 'CENTER' else (-1 if fn == 'TURN_LEFT' else 1))))
                continue
            if seg.module_kind == 'LIFT':
                height = max(units.mm_to_bu(seg.rise_mm, scene), 0.3)
                lift = seg_model.lift_module(height, seg.lift_shape, seg_model.lift_apex(height))
                _store_length(seg, units.bu_to_mm(lift.length_m, scene))
                out.append(lift)
                continue
            if seg.module_kind in ('MERGE', 'DIVERTER'):
                layout = merge_layout_for(seg, settings, scene)
                _store_length(seg, units.bu_to_mm(layout.length_m, scene))
                out.append(seg_model.Module(seg.module_kind, layout.length_m, 'STRAIGHT', **junction_module_fields(seg, settings)))
                continue
            length_mm = max(seg.length_mm, MODULE_MIN_LENGTH_MM) if seg.length_mm > 0 else spec.length_mm
            if seg.module_kind == 'RAT':
                length_mm = rat_footprint_mm(seg, settings, scene)
            out.append(seg_model.Module(seg.module_kind, units.mm_to_bu(length_mm, scene), exit_side))
    return out


def rat_footprint_mm(seg, settings, scene) -> float:
    """A right-angle transfer's length along its line (mm). Where the line
    turns on it (exit LEFT / RIGHT) it is square to the line it turns onto:
    the line's frame width, so its far end lines up with that line's frame
    (at its own 900 mm a corner stuck out past the line leaving it, user
    2026-10-25). Otherwise its own length. Either way a wider line docked
    on a side face stretches it (transfer_parts.rat_length)."""
    from ..props.line_settings import MODULE_MIN_LENGTH_MM

    spec = loader.get_segment_catalog().modules[seg.module_kind]
    if spec.allows_exit and seg.module_exit in ('LEFT', 'RIGHT'):
        from .rat_faces import frame_width_mm

        own = frame_width_mm(settings.id_data, scene)
    else:
        own = max(seg.length_mm, MODULE_MIN_LENGTH_MM) if seg.length_mm > 0 else spec.length_mm
    return transfer_parts.rat_length(own, seg.rat_face_left_mm, seg.rat_face_right_mm)


def _store_length(seg, length_mm: float) -> None:
    """Keep a fitted module's stored footprint (lift, junction) in step
    with the model: the list, the strip and the dimensions read it. Skipped
    when it is already right, and when the caller is a panel or overlay
    draw -- ID writes are not allowed there, and every readout that
    evaluates the line (rates, fork count) used to fail silently
    on any line with a lift or a junction until something rebuilt it."""
    if abs(float(seg.length_mm) - length_mm) < 1e-6:
        return
    try:
        seg["length_mm"] = length_mm
    except AttributeError:  # draw context; the next build writes it
        pass


def _nose_over_radius(settings, scene) -> float:
    if not settings.nose_over:
        return 0.0
    conveyor_type = loader.get_conveyor_types()[settings.conveyor_type]
    return units.mm_to_bu(loader.get_segment_catalog().nose_over_radius_for(conveyor_type.cross_section), scene)


def evaluate_line(context, obj) -> tuple[seg_model.Spine, list[seg_model.Segment], float]:
    """Returns (spine, segments, width_m) for a line object, in local
    space: the object's own transform is the line's start pose."""
    scene = context.scene
    settings = obj.conveyor_line
    width_m = units.mm_to_bu(resolve_width_mm(settings), scene)
    segments = segments_from_settings(settings, scene)
    radius_m = _nose_over_radius(settings, scene)
    # A branch off a right-angle divert carries its goods sideways: the turn
    # they did not make rides along as the line's starting yaw offset
    # (operators/detect_junctions._attach_branch).
    start = seg_model.Pose(0, 0, 0, 0, 0, float(settings.get("branch_keep_yaw", 0.0)))
    spine = seg_model.evaluate_chain(segments, start, width_m, transition_radius_m=radius_m)
    return spine, segments, width_m


def segment_starts_for(context, obj) -> tuple[list, list[float], float]:
    """(segments, the arc each segment starts at, width_m), laid out exactly
    as build_line lays the line out (nose-over transitions included)."""
    _spine, segments, width_m = evaluate_line(context, obj)
    radius_m = _nose_over_radius(obj.conveyor_line, context.scene)
    return segments, seg_model.segment_starts(segments, width_m, radius_m), width_m


def segment_frames_for(context, obj) -> list:
    """(start pose, end pose) of every segment, object-local, as built."""
    _spine, segments, width_m = evaluate_line(context, obj)
    radius_m = _nose_over_radius(obj.conveyor_line, context.scene)
    return seg_model.segment_frames(segments, seg_model.Pose(0, 0, 0, 0, 0), width_m, transition_radius_m=radius_m)


START_ANCHOR_KEY = "conveyor_start_anchor"  # local end pose of piece 0 at the last build (x, y, z, heading)


def _keep_start_anchor(obj, settings, frames) -> bool:
    """Growing backwards (keys set to Start), the END of the first piece is
    the anchor, not the origin: when that piece changes -- a new one put in
    front of it, its length or angle edited -- the object moves so that
    everything from the second piece on stays exactly where it is
    (model/segments.reanchor_pose). Returns True when the object moved."""
    anchor = settings.get(START_ANCHOR_KEY)
    if settings.grow_at != 'START' or anchor is None or len(frames) < 2:
        return False
    e = frames[0][1]
    new_end = (e.x, e.y, e.z, e.heading)
    old_end = tuple(float(v) for v in anchor)
    if all(abs(a - b) < 1e-6 for a, b in zip(old_end, new_end)):
        return False
    from .detect_junctions import _remember_matrix

    x, y, z, yaw = seg_model.reanchor_pose(obj.location.x, obj.location.y, obj.location.z, obj.rotation_euler.z, old_end, new_end)
    obj.location = (x, y, z)
    obj.rotation_euler.z = yaw
    _remember_matrix(obj)  # not a user move: nothing docked here follows the origin
    return True


def _resync_docked(context, obj) -> None:
    """Lines docked on `obj` re-sync (their arcs along it moved)."""
    from .detect_junctions import _is_junction, _remember_matrix, _sources, sync_feeder

    for jseg in obj.conveyor_line.segments:
        if _is_junction(jseg):
            for name in _sources(jseg):
                other = context.scene.objects.get(name)
                if other is not None:
                    sync_feeder(context, other)
    _remember_matrix(obj)


BUILD_STATS = {"builds": 0}  # how many line builds happened: the tests' idempotency check (R6: no rebuild when nothing changes)


def build_line(context, obj) -> None:
    from .sync_stats import note_write

    BUILD_STATS["builds"] += 1
    note_write()  # a build writes the spine and the modifier inputs
    settings = obj.conveyor_line
    if not settings.get("conveyor_flow_migrated"):
        # A line from before 2.22: its group's Population from what its old
        # settings showed (operators/flows.migrate), once, before anything is pushed.
        from .flows import migrate

        try:
            migrate(context, [obj])
        except Exception as exc:
            print(f"conveyor: migrating {obj.name} to Population failed: {exc!r}")
    migrate_removed_type(settings)
    migrate_legacy_segments(settings)
    if "pouch_mount" in settings and "support_mount" not in settings:
        settings["support_mount"] = settings["pouch_mount"]  # 2.13 kept the pouch sorter's Supports under this name
    from . import rat_faces

    rat_faces.apply(context, obj)  # a transfer's sides take the attached lines' widths (2.18)
    _shed_borrowed_docks(context, obj)
    spine, segments, width_m = evaluate_line(context, obj)
    gaps = []
    for gap in settings.guide_gaps:
        center = units.mm_to_bu(gap.arc_len_mm, context.scene)
        half = units.mm_to_bu(gap.length_mm, context.scene) / 2.0
        gaps.append((center - half, center + half, spine_io.GAP_LEFT if gap.side == 'LEFT' else spine_io.GAP_RIGHT))
    # Merge junctions on THIS line: fence taper + deck outline splines in
    # local space, and the fence opening on the infeed side.
    extras: list = []
    radius_m = 0.0
    if settings.nose_over:
        conveyor_type = loader.get_conveyor_types()[settings.conveyor_type]
        radius_m = units.mm_to_bu(loader.get_segment_catalog().nose_over_radius_for(conveyor_type.cross_section), context.scene)
    frames = seg_model.segment_frames(segments, seg_model.Pose(0, 0, 0, 0, 0), width_m, transition_radius_m=radius_m)
    starts = seg_model.segment_starts(segments, width_m, radius_m)
    shifted = _keep_start_anchor(obj, settings, frames)
    # Support columns: a spiral's centre drum, a lift's tower (both sides).
    for i, seg in enumerate(settings.segments):
        if i >= len(segments):
            break
        if seg.kind == 'SPIRAL':
            start, end = frames[i]
            sp = segments[i]
            cx, cy = seg_model.spiral_center(start, sp, width_m)
            extras.append((spine_io.ROLE_COLUMN, [(cx, cy, max(start.z, end.z), start.heading), (cx, cy, max(start.z, end.z) - 0.01, start.heading)]))
            # Cantilever arms from the drum out under the track every ~45 deg
            # of plan angle: a spiral hangs on its drum, it has no floor stands.
            radius = seg_model.spiral_plan_radius(sp, width_m)
            sign = 1.0 if sp.direction == "LEFT" else -1.0
            total = math.radians(abs(sp.angle_deg))
            n_arms = max(2, int(round(total / math.radians(45.0))))
            arm_drop = _FRAME_DEFAULTS["Rail Top Drop"] + _FRAME_DEFAULTS["Rail Height"] + SPIRAL_ARM_H / 2.0
            for k in range(n_arms + 1):
                phi = total * k / n_arms
                h = start.heading + sign * phi
                lx, ly = seg_model.left_of(h)
                px, py = cx - sign * lx * radius, cy - sign * ly * radius
                z = start.z + sp.rise_m * k / n_arms - arm_drop
                ux, uy = (px - cx) / radius, (py - cy) / radius
                reach = width_m / 2.0 + 0.02
                extras.append((spine_io.ROLE_ARM, [(cx + ux * spine_io.DRUM_RADIUS_M * 0.8, cy + uy * spine_io.DRUM_RADIUS_M * 0.8, z, h),
                                                    (px + ux * reach, py + uy * reach, z, h)]))
    conveyor_type = loader.get_conveyor_types()[settings.conveyor_type]
    transfer_frame = _transfer_frame(settings, width_m, context.scene)
    lift_data: list = []  # per lift, 10 numbers (operators/populate.route_values -> Lift k inputs)
    no_stand_ends: dict = {}  # RAT ends another frame carries: no floor stand there (model/spine.write_spine)
    for i, seg in enumerate(settings.segments):
        if i >= len(segments) or seg.kind != 'MODULE' or seg.module_kind not in ('MERGE', 'DIVERTER', 'RAT', 'LIFT', 'WRAPPER'):
            continue
        start = frames[i][0]
        h = start.heading
        fwd = (-math.sin(h), math.cos(h))
        right = (math.cos(h), math.sin(h))

        def to_local(mx, my, mh=0.0, mz=0.0):
            return (start.x + right[0] * mx + fwd[0] * my, start.y + right[1] * mx + fwd[1] * my, start.z + mz, h + mh)

        if seg.module_kind == 'LIFT':
            # Fork-column lift (model/lift_parts.py): combs, column and the
            # forks' loop; the forks themselves are instanced by the tree in
            # step with the item slots (build_lift_forks).
            module = segments[i]
            layout = lift_parts.lift_layout(module.height_m, module.shape)
            side = seg.lift_side
            _add_parts(extras, lift_parts.lift_parts(layout, transfer_frame, side), to_local)
            cx, cy, ctop = lift_parts.column_centre(layout, transfer_frame, side)
            extras.append((spine_io.ROLE_COLUMN, [to_local(cx, cy, 0.0, ctop), to_local(cx, cy, 0.0, ctop - 0.01)],
                           {"part_r": lift_parts.COLUMN_W, "part_h": lift_parts.COLUMN_D}))
            k = len(lift_data) // 10 + 1
            if k <= 2:
                rev = bool(settings.reverse)
                up_y, down_y = (layout.y_drop, layout.y_pick) if rev else (layout.y_pick, layout.y_drop)
                loop = lift_parts.fork_loop(layout, up_y, down_y)
                extras.append((spine_io.ROLE_LIFT_LOOP, [to_local(0.0, y, 0.0, z) for y, z in loop], {"lift_index": k}))
                face, reach = lift_parts.fork_offsets(width_m, side)
                # Geometric arcs of the pick / drop corners, the loop coordinate
                # of the pick corner for either flow, the fork offsets.
                lift_data += [float(k), starts[i] + layout.arc_pick, starts[i] + layout.arc_drop,
                              lift_parts.pick_loop_coord(layout, 0.0), lift_parts.pick_loop_coord(layout, module.height_m),
                              lift_parts.drop_loop_coord(layout, module.height_m), lift_parts.drop_loop_coord(layout, 0.0), face, reach,
                              units.mm_to_bu(float(seg.lift_fork_pitch_mm), context.scene)]
            continue
        if seg.module_kind == 'WRAPPER':
            from ..model import wrapper_parts

            parts, _fences = wrapper_parts.wrapper_parts(segments[i].length_m, transfer_frame, seg.wrapper_mode)
            _add_parts(extras, parts, to_local)
            continue
        if seg.module_kind == 'RAT':
            start_free, end_free = _rat_free_ends(context, obj, settings, i)
            # A docked RAT end stands on the frame it docks on: no stand of its
            # own there. Two end stands met at a RAT-to-RAT face, posts and
            # 144 mm foot plates through each other.
            carried = (i == 0 and not start_free, i == len(settings.segments) - 1 and not end_free)
            if any(carried):
                no_stand_ends[i] = carried
            if conveyor_type.cross_section not in ("omni", "pouch"):
                open_sides = tuple(s for s, n in (('LEFT', seg.merge_source), ('RIGHT', seg.merge_source_right),
                                                  ('END', getattr(seg, "rat_source_end", ""))) if n)  # lines docked on its faces
                face_widths = {side: units.mm_to_bu(mm, context.scene)  # the docked line's frame width (rails included)
                               for side, mm in (('LEFT', seg.rat_face_left_mm), ('RIGHT', seg.rat_face_right_mm),
                                                ('END', getattr(seg, "rat_face_end_mm", 0.0))) if mm > 0}
                # Its stands are the line's planned ones at both ends (model/spine
                # _stand_ranges): the posts it added under its free faces stood
                # beside them, and went to the floor under a ceiling-hung line.
                parts, fence_lines = transfer_parts.rat_parts(segments[i].length_m, segments[i].exit, transfer_frame, open_sides=open_sides,
                                                              face_widths=face_widths, closed_start=start_free, closed_end=end_free)
                if segments[i].exit != 'STRAIGHT' or open_sides:
                    transfer_parts.tag_transfer(parts, transfer_id(obj.name, i))
                _add_parts(extras, parts, to_local)
                for line_pts in fence_lines:
                    extras.append((spine_io.ROLE_FENCE, _fence_points(line_pts, to_local)))
            continue
        layout = merge_layout_for(seg, settings, context.scene)
        fields = junction_module_fields(seg, settings)
        if conveyor_type.cross_section != "pouch":  # a pouch sorter's switch is the rail itself: no fences, no deck
            for fence in layout.fences:
                extras.append((spine_io.ROLE_FENCE, [to_local(px, py, ph) for px, py, ph in fence]))
            extras.append((spine_io.ROLE_OUTLINE, [to_local(px, py) for px, py in layout.outline],
                           {"module_tech": seg_model.TECH_IDS.get(fields["tech"], 0), "module_skew": fields["skew"],
                            "module_side": fields["side"], "module_flip": 1 if fields["flip"] else 0}))
        if conveyor_type.cross_section not in ("omni", "pouch"):
            surface = "rollers" if conveyor_type.cross_section == "roller" else "plate"
            parts = transfer_parts.junction_parts(layout, junction_sides(seg), fields["tech"], fields["flip"], transfer_frame, surface)
            if animated_transfer(seg, settings):
                transfer_parts.tag_transfer(parts, transfer_id(obj.name, i))
            _add_parts(extras, parts, to_local)
        for y0, y1, sd in layout.gaps:
            gaps.append((starts[i] + y0, starts[i] + y1, spine_io.GAP_LEFT if sd < 0 else spine_io.GAP_RIGHT))
    settings["lift_data"] = lift_data
    from .detect_junctions import continuation_for, prefix_for

    # Flow-wise paths of the docked main lines (operators/detect_junctions.py):
    # the prefix before this line's flow start, the continuation after its
    # flow end. Composed here into GEOMETRIC lists: a reversed line runs its
    # flow from the curve's end to its start, so they swap ends and order.
    flow_cont = continuation_for(context, obj, spine, spine.length)
    flow_prefix, prefix_len = prefix_for(context, obj, spine)
    own_len = spine.length
    cont_len = (flow_cont[-1][5] - own_len) if flow_cont else 0.0
    total = prefix_len + own_len + cont_len
    rev = bool(settings.reverse)
    if not rev:
        before = [tuple(pt) for pt in flow_prefix]
        after = [(pt[0], pt[1], pt[2], pt[3], pt[4], pt[5] + prefix_len, *pt[6:]) for pt in flow_cont]
        own_shift = prefix_len
    else:
        before = [(pt[0], pt[1], pt[2], pt[3] + math.pi, -pt[4], cont_len - (pt[5] - own_len), *pt[6:]) for pt in reversed(flow_cont)]
        after = [(pt[0], pt[1], pt[2], pt[3] + math.pi, -pt[4], total - pt[5], *pt[6:]) for pt in reversed(flow_prefix)]
        own_shift = cont_len
    before = _unwrap_headings(before, spine.heading[0] if len(spine) else 0.0, from_end=True)
    after = _unwrap_headings(after, spine.heading[-1] if len(spine) else 0.0, from_end=False)
    # No guide brackets on a docked flow end (merge face) or flow start (diverter face).
    bracket_skips = []
    end_range = (max(own_len - BRACKET_FREE_M, 0.0), own_len)
    start_range = (0.0, min(BRACKET_FREE_M, own_len))
    if settings.get("continue_target"):
        bracket_skips.append(start_range if rev else end_range)
    if settings.get("branch_target"):
        bracket_skips.append(end_range if rev else start_range)
    # Leg-free pieces (Legs off): no stands on them, one flush with each edge (model/legs.py).
    from ..model import legs as legs_model

    from bisect import bisect_left

    from .stands import ADD_KEY, removed_spots

    piece_ends = [starts[k + 1] if k + 1 < len(starts) else spine.length for k in range(len(starts))]
    leg_gaps = legs_model.free_intervals(starts, piece_ends, [bool(getattr(s, "legs", True)) for s in settings.segments][:len(starts)])
    carried = [(starts[k], piece_ends[k]) for k, s in enumerate(settings.segments[:len(starts)]) if s.kind == 'SPIRAL']  # they hang on their drum
    spots, spot_refs = removed_spots(obj, starts)  # stands the user took out (operators/stands.py)
    added_spots, _added_refs = removed_spots(obj, starts, ADD_KEY)  # and the ones added
    # Around a spiral the line runs over its lower turns: no stand within its
    # footprint, widened by a stand's half width and a clearance.
    zones = []
    for k, seg_m in enumerate(segments[:len(starts)]):
        if isinstance(seg_m, seg_model.Spiral):
            i = min(bisect_left(spine.s, starts[k] - 1e-6), len(spine.s) - 1)
            cx, cy = seg_model.spiral_center(spine.pose_at(i), seg_m, width_m)
            zones.append((cx, cy, seg_model.spiral_plan_radius(seg_m, width_m) + width_m + _FRAME_DEFAULTS["Support Size"]
                          + legs_model.SPIRAL_CLEARANCE_M))
    carried += legs_model.zone_intervals(spine.s, spine.x, spine.y, zones)
    plan = spine_io.write_spine(obj.data, spine, segments, gaps, extras=extras,
                                before=before, after=after, own_shift=own_shift, bracket_skips=bracket_skips, reverse=rev,
                                no_stand_ends=no_stand_ends, leg_gaps=leg_gaps,
                                stand_plan={"spacing": max(float(settings.support_spacing_m), 0.5), "size": _FRAME_DEFAULTS["Support Size"],
                                            "carried": carried, "removed": spots, "added": added_spots},
                                rests_on=_ends_on_rat_faces(context, obj, spine))
    # Where the stands are, for the per-stand buttons (ui/stands.py): the same plan the trees place them from.
    def _at(arc):
        i = bisect_left(spine.s, arc - 2e-6)
        if i < len(spine.s) and abs(spine.s[i] - arc) < 2e-6:
            return (spine.x[i], spine.y[i], spine.z[i])
        return None
    def _put(key, value):  # only when changed: a rebuild that moves nothing writes nothing
        old = settings.get(key)
        if (old.to_list() if hasattr(old, "to_list") else old) != value:
            settings[key] = value
    _put("leg_free_span_m", float(plan["longest_span"]))
    _put("piece_starts", [float(s) for s in starts])
    stand_rows = [(a, _at(a)) for a in plan["stands"]]
    stand_rows = [(a, p) for a, p in stand_rows if p is not None]
    _put("stand_arcs", [float(a) for a, _p in stand_rows])
    _put("stand_points", [float(v) for _a, p in stand_rows for v in p])
    out_rows = [(a, _at(a), spot_refs[k]) for a, k in zip(plan["removed"], plan["removed_sources"])]
    out_rows = [(a, p, ref) for a, p, ref in out_rows if p is not None]
    _put("stand_removed_arcs", [float(a) for a, _p, _r in out_rows])
    _put("stand_removed_points", [float(v) for _a, p, _r in out_rows for v in p])
    _put("stand_removed_refs", [int(v) for _a, _p, ref in out_rows for v in ref])  # (piece, index) per removed stand
    # The middle of every gap a stand can be added in (its + button), on the spine between its samples.
    def _between(arc):
        i = min(max(bisect_left(spine.s, arc), 1), len(spine.s) - 1)
        s0, s1 = spine.s[i - 1], spine.s[i]
        t = 0.0 if s1 - s0 < 1e-9 else (arc - s0) / (s1 - s0)
        return tuple(a + (b - a) * t for a, b in ((spine.x[i - 1], spine.x[i]), (spine.y[i - 1], spine.y[i]), (spine.z[i - 1], spine.z[i])))
    gap_rows = [(a, _between(a)) for a in plan["gaps"]] if len(spine.s) > 1 else []
    _put("stand_gap_arcs", [float(a) for a, _p in gap_rows])
    _put("stand_gap_points", [float(v) for _a, p in gap_rows for v in p])
    # How wide the goods run across the line (populate.overhang_notes): on its
    # own pieces (a transfer's own deck is as wide as its faces: skipped), and
    # where a feeder's goods ride on the line they merge onto.
    try:
        from .populate import OVERHANG_KEY, across_mm, goods_sizes_mm

        sizes = goods_sizes_mm(context, obj)
        own, own_turned = 0.0, False
        for k in range(len(spine)):
            idx = spine.segment_index[k]
            if idx < 0 or idx >= len(settings.segments) or settings.segments[idx].kind == 'MODULE':
                continue
            a = across_mm(sizes, spine.yaw_offset[k])
            if a > own + 1e-6:
                own, own_turned = a, abs(math.sin(spine.yaw_offset[k])) > 0.5
        onto_yaw = float(flow_cont[-1][6]) if flow_cont and len(flow_cont[-1]) > 6 else None
        onto = across_mm(sizes, onto_yaw) if onto_yaw is not None else 0.0
        _put(OVERHANG_KEY, [round(own, 1), 1.0 if own_turned else 0.0, round(onto, 1),
                            1.0 if onto_yaw is not None and abs(math.sin(onto_yaw)) > 0.5 else 0.0])
    except Exception as exc:
        print(f"conveyor: goods width of {obj.name}: {exc!r}")
    # Flow-wise bookkeeping for the shared item streams (operators/stream.py).
    settings["prefix_length_m"] = prefix_len
    settings["own_length_m"] = own_len
    settings["full_length_m"] = total
    # The path the goods are drawn on, by length (populate samples spline 0 by
    # length): a 45 degree divert's blend makes it longer than the arcs above.
    settings["path_length_m"] = float(plan.get("path_length", total))

    end = spine.pose_at(len(spine) - 1)
    settings["end_pose"] = (end.x, end.y, end.z, math.degrees(end.heading))
    settings["total_length_mm"] = units.bu_to_mm(spine.length, context.scene)
    if frames:
        e = frames[0][1]
        settings[START_ANCHOR_KEY] = (e.x, e.y, e.z, e.heading)
    # Per-segment (start, end) footprint poses, flattened [sx, sy, sz, ex, ey, ez] *
    # n, in the object's local space. The elevation gizmo (ui/gizmos.py)
    # anchors on these, so it never re-evaluates the chain on redraw.
    settings["segment_frames"] = [v for a, b in frames for v in (a.x, a.y, a.z, b.x, b.y, b.z)]
    settings["segment_start_heading"] = [a.heading for a, _b in frames]
    # The centerline samples with the piece each belongs to, for picking and
    # outlining pieces in the viewport (ui/segment_edit.py).
    settings["seg_path"] = [v for k in range(len(spine)) for v in (spine.x[k], spine.y[k], spine.z[k])]
    settings["seg_path_heading"] = list(spine.heading)
    settings["seg_path_index"] = list(spine.segment_index)
    settings["line_width_m"] = width_m

    _apply_modifier(context, obj, width_m)

    from .detect_junctions import sync_feeder

    sync_feeder(context, obj)
    _refresh_docked_feeders(context, obj)
    for other in rat_faces.neighbours_to_refresh(context, obj):
        if other.name not in _refreshing:  # a transfer whose side follows this line (compare first: no loop)
            build_line(context, other)
    from .ports import publish_line, refresh_links

    try:
        refresh_links(context, obj)  # the rates a rack reads follow the line
        publish_line(context, obj)  # the line's own descriptor, ports and path for other add-ons
    except Exception as exc:  # publishing must never break a build
        print(f"conveyor: publish of {obj.name} failed: {exc!r}")
    _refresh_stream_peers(context, obj)
    if shifted:
        _resync_docked(context, obj)  # growing backwards moved the object: the docked lines' arcs along it changed


_refreshing = set()


def _unwrap_headings(points: list, neighbour_heading: float, from_end: bool) -> list:
    """Shifts a point list's headings by whole turns so the point adjacent
    to the line's own spline is within half a turn of it (headings are
    sampled linearly along the full spline: a 2*pi jump would spin items)."""
    if not points:
        return points
    ref = points[-1][3] if from_end else points[0][3]
    turns = round((ref - neighbour_heading) / (2.0 * math.pi))
    if turns == 0:
        return points
    shift = turns * 2.0 * math.pi
    return [(p[0], p[1], p[2], p[3] - shift, *p[4:]) for p in points]


def push_time_scale(context, scene) -> None:
    """The scene's clock changed (our field or the Racks add-on): every
    line re-reads its on-screen speed (inputs only). A line whose speed
    changed is tagged, so its goods take it at once (input writes alone
    left them at the old clock until the next rebuild), and the operation
    seconds it publishes -- its ports' and links' crossings, R22.4
    arrivals -- follow the new clock."""
    from .ports import publish_line, refresh_links

    changed = []
    for line in all_lines(scene):
        with context.temp_override(scene=scene) if context.scene != scene else _nullcontext():
            before = _speed_input(line)
            _push_inputs(context, line)
            if _speed_input(line) != before:
                line.update_tag()
                changed.append(line)
    for line in changed:
        try:
            with context.temp_override(scene=scene) if context.scene != scene else _nullcontext():
                refresh_links(context, line)
                publish_line(context, line)
        except Exception as exc:  # publishing must never break the clock
            print(f"conveyor: republishing {line.name} on the new clock failed: {exc!r}")


def _speed_input(obj):
    modifier = obj.modifiers.get(MODIFIER_NAME)
    if modifier is None or modifier.node_group is None:
        return None
    try:
        socket = bc.find_input_socket(modifier.node_group, "Speed")
    except KeyError:
        return None
    inputs = modifier.properties.inputs
    return inputs[socket.identifier].get("value") if socket.identifier in inputs else None


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


RAT_FACE_REACH_M = 0.08  # a line end this close to a right-angle transfer's face it docks on rests on its frame


def _ends_on_rat_faces(context, obj, spine) -> tuple[bool, bool]:
    """(start, end): the line's geometric start / end sits on a side face of
    a straight-through right-angle transfer it docks on, so it rests on the
    transfer's frame, as a transfer's docked end rests on its line: no stand
    of its own there (a stand beside every face crowded the transfer with
    legs, 2.26.1). That frame stands at both its ends; a corner's stand only
    under its start and its exit, so a line on its far face or other side
    keeps its stand: it carries that edge."""
    from mathutils import Vector

    from .detect_junctions import _docked_side, _module_face_world, _sources

    if not len(spine.s):
        return (False, False)
    ends = [obj.matrix_world @ Vector((spine.x[k], spine.y[k], spine.z[k])) for k in (0, -1)]
    out = [False, False]
    for line in all_lines(context.scene):
        if line == obj:
            continue
        for i, seg in enumerate(line.conveyor_line.segments):
            if seg.kind != 'MODULE' or seg.module_kind != 'RAT' or seg.module_exit != 'STRAIGHT' or obj.name not in _sources(seg):
                continue
            side = _docked_side(seg, obj.name)
            if side not in ('LEFT', 'RIGHT'):
                continue
            try:
                face = _module_face_world(context, line, i, side)[0]
            except Exception:
                continue
            for k, p in enumerate(ends):
                if (Vector((p.x, p.y)) - Vector((face.x, face.y))).length < RAT_FACE_REACH_M and abs(p.z - face.z) < RAT_FACE_REACH_M:
                    out[k] = True
    return (out[0], out[1])


def _rat_free_ends(context, obj, settings, index: int) -> tuple[bool, bool]:
    """(start face free, end face free) of the RAT at `index`: a standalone
    transfer's start is free when it is the first piece and nothing meets
    the line's origin; its end when it is the last piece, runs straight
    through and nothing meets the line's end."""
    from .detect_junctions import TAIL_KEY, docked_junction, origin_dock
    from .ports import dock_at

    segs = settings.segments
    start_free = index == 0 and origin_dock(context, obj) is None and not settings.get(TAIL_KEY) and dock_at(obj, "origin") is None
    end_free = (index == len(segs) - 1 and segs[index].module_exit == 'STRAIGHT' and docked_junction(context, obj) is None
                and dock_at(obj, "end") is None
                and not any(o != obj and o.conveyor_line.get(TAIL_KEY) == obj.name for o in all_lines(context.scene)))
    if settings.reverse:  # the flow runs the other way: the geometric start is the flow end
        start_free, end_free = (index == 0 and docked_junction(context, obj) is None and dock_at(obj, "origin") is None), (
            index == len(segs) - 1 and segs[index].module_exit == 'STRAIGHT' and origin_dock(context, obj) is None and dock_at(obj, "end") is None)
    return start_free, end_free


def _shed_borrowed_docks(context, obj) -> None:
    """A duplicated line (Shift+D) carries the original's dock keys and
    port docks: it would draw its goods along the original's main line and
    collide with them (user, 2026-10-11: "objects interfere with each
    other at merges"). A copy sheds them before its first build; any line
    sheds junction keys whose junction no longer names it."""
    from .detect_junctions import ROLE_KEY, TAIL_KEY, _clear_branch, _clear_continuation, _drop_stale_docks
    from .ports import is_copy, release_port

    settings = obj.conveyor_line
    if is_copy(context, obj):
        _clear_continuation(settings)
        _clear_branch(settings)
        for key in (TAIL_KEY, ROLE_KEY):
            if key in settings:
                del settings[key]
        release_port(context, obj)
    else:
        _drop_stale_docks(context, obj)


def _refresh_stream_peers(context, obj) -> None:
    """Lines sharing an item stream with `obj` (docked feeders, routed
    branches, their main lines; operators/stream.py) re-read the group's
    stream: inputs only, no rebuild -- and their links, whose divert shares
    follow the group (R22.1; written only when they change)."""
    from .ports import refresh_links
    from .stream import stream_root

    root = stream_root(context, obj)
    for line in all_lines(context.scene):
        if line != obj and stream_root(context, line) == root:
            _push_inputs(context, line)
            refresh_links(context, line)


def _refresh_docked_feeders(context, obj) -> None:
    """A main line changed: the lines docked on its junctions move with
    their junction (a segment edited upstream shifts it) and re-read its
    centerline for their onward item path."""
    from .detect_junctions import follow_target

    if obj.name in _refreshing:
        return
    _refreshing.add(obj.name)
    try:
        # Collected first: a feeder that swaps role re-syncs and edits this
        # line's segment list.
        docked = [name for seg in obj.conveyor_line.segments
                  if seg.kind == 'MODULE' and seg.module_kind in ('MERGE', 'DIVERTER', 'RAT')
                  for name in (seg.merge_source, seg.merge_source_right, getattr(seg, "rat_source_end", "")) if name]
        from .detect_junctions import _attach_branch, _attach_continuation, _docked_side

        for name in docked:
            feeder = context.scene.objects.get(name)
            if feeder is None:
                continue
            # Which way the goods go is the docked line's own (a RAT hosts both).
            key = next((k for k in ("continue_target", "branch_target") if feeder.conveyor_line.get(k) == obj.name), None)
            if key is not None:
                follow_target(context, feeder, obj, rigid=False)
                if feeder.conveyor_line.get(key) != obj.name:
                    continue
                # The dock's arc on this line's FLOW path moves whenever this
                # line's length changes upstream of it (a junction widening,
                # a piece edited; on a reversed line anything after it):
                # recompute it, or the branch's slide starts where the
                # divert used to be (user's file, 2026-10-10: 0.85 m early,
                # a diagonal slide).
                index = next((i for i, seg in enumerate(obj.conveyor_line.segments)
                              if seg.kind == 'MODULE' and name in (seg.merge_source, seg.merge_source_right, getattr(seg, "rat_source_end", ""))), None)
                rebuilt = False
                if index is not None:
                    seg = obj.conveyor_line.segments[index]
                    side = _docked_side(seg, name)
                    attach = _attach_continuation if key == "continue_target" else _attach_branch
                    rebuilt = attach(context, feeder, obj, index, side)
                if not rebuilt:
                    build_line(context, feeder)
        # Lines carrying this one's goods on from its end: their item path
        # starts with this line's path, so they rebuild with it.
        from .detect_junctions import TAIL_KEY, _sync_tail, follow_tail

        for other in all_lines(context.scene):
            if other != obj and other.conveyor_line.get(TAIL_KEY) == obj.name:
                # This line's end moved (a piece edited): the takeaway moves
                # with it, and re-reads the handover arc (this line's full
                # length).
                follow_tail(context, other, obj)
                if not _sync_tail(context, other):
                    build_line(context, other)
    finally:
        _refreshing.discard(obj.name)


def _apply_modifier(context, obj, width_m: float) -> None:
    scene = context.scene
    settings = obj.conveyor_line
    conveyor_type = loader.get_conveyor_types()[settings.conveyor_type]
    # A shared sub-tree (frame, populate, modules) rebuilt in place loses the
    # links from every line tree that references it (its interface sockets
    # are recreated), so when any of them is stale ALL line trees are
    # rebuilt with it -- otherwise Populate silently produced nothing.
    from ..geonodes import frame as frame_tree
    from ..geonodes import populate as populate_tree

    # (The merge and diverter module groups are no longer used: junctions are
    # built from the spine outline. They must not be in this list or every
    # build would rebuild.)
    # Only line trees that already exist (plus the one this line needs) are
    # built: building one takes ~1.2 s, and a fresh file used to build all
    # three on the first "New Line".
    needed = conveyor_type.cross_section
    present = [m for m in _LINE_TREE_MODULES if bpy.data.node_groups.get(m.NODE_GROUP_NAME) is not None]
    stale = any(bc.tree_is_stale(m.NODE_GROUP_NAME, m.TREE_VERSION)
                for m in (frame_tree, populate_tree, *present))
    if stale:
        # The shipped set first (geonodes/library.py: a fraction of a second
        # for all of them), the builders only when it does not match.
        from ..geonodes import library

        wanted = [(frame_tree.NODE_GROUP_NAME, frame_tree.TREE_VERSION), (populate_tree.NODE_GROUP_NAME, populate_tree.TREE_VERSION)]
        wanted += [(m.NODE_GROUP_NAME, m.TREE_VERSION) for m in _LINE_TREE_MODULES
                   if m.NODE_GROUP_NAME == _TREE_NAMES[needed] or bpy.data.node_groups.get(m.NODE_GROUP_NAME) is not None]
        if not library.append(wanted):
            for cs, builder in _LINE_TREE_BUILDERS.items():
                if cs == needed or bpy.data.node_groups.get(_TREE_NAMES[cs]) is not None:
                    builder(rebuild=True)
        # A rebuilt tree gets new socket identifiers, orphaning the stored
        # inputs of EVERY modifier that uses it: re-push them on all lines,
        # and give their (older) spines any attribute the new trees sample.
        # Node trees are shared by the whole file, so lines in OTHER scenes
        # lost their legs and rails too until rebuilt: push those as well.
        from types import SimpleNamespace

        for other_scene in bpy.data.scenes:
            ctx = context if other_scene == scene else SimpleNamespace(
                scene=other_scene, view_layer=other_scene.view_layers[0] if other_scene.view_layers else None)
            for other in all_lines(other_scene):
                if other != obj:
                    spine_io.ensure_attribute_defaults(other.data)
                    _push_inputs(ctx, other)
    tree = _LINE_TREE_BUILDERS[conveyor_type.cross_section]()
    _push_inputs(context, obj, tree)


FLOW_TAG_KEY = "conveyor_flow_pct"  # [population % at the flow start, at the flow end] in effect, for the flow markers


def _store_flow_tag(context, obj) -> None:
    """The populations a line's flow markers show (ui/flow_markers.py draws
    every redraw: no stream maths there). Written only when they change."""
    try:
        from .stream import tree_for

        gf = tree_for(context, obj).flow
        ids = gf.sections.get(obj.name) if gf is not None else None
        if not ids:
            return
        first, last = gf.nodes.get(ids[0]), gf.nodes.get(ids[-1])
        pct = [round(min(n.population * gf.scale, 1.0) * 100.0, 1) if n is not None else 0.0 for n in (first, last)]
        settings = obj.conveyor_line
        old = settings.get(FLOW_TAG_KEY)
        if old is None or [round(float(v), 1) for v in old] != pct:
            settings[FLOW_TAG_KEY] = pct
    except Exception:
        pass


def _push_inputs(context, obj, tree=None) -> None:
    """(Re)writes every modifier input of `obj` from its settings."""
    scene = context.scene
    settings = obj.conveyor_line
    conveyor_type = loader.get_conveyor_types()[settings.conveyor_type]
    if tree is None:
        tree = _LINE_TREE_BUILDERS[conveyor_type.cross_section]()
    width_m = units.mm_to_bu(resolve_width_mm(settings), scene)
    modifier = obj.modifiers.get(MODIFIER_NAME)
    if modifier is None:
        modifier = obj.modifiers.new(MODIFIER_NAME, 'NODES')
    if modifier.node_group != tree:
        modifier.node_group = tree

    values = dict(_FRAME_DEFAULTS)
    values["Support Spacing"] = max(float(settings.support_spacing_m), 0.5)  # the line's own leg spacing (user, 2026-10-13)
    values["Ceiling Mount"] = settings.support_mount == 'CEILING'  # every line type can hang from the ceiling (2.14)
    from .ceilings import line_ceiling, store as store_ceiling

    values["Ceiling Z"], ceiling_from = line_ceiling(scene, obj)  # the hall's clear height (R17), else the Scene setting
    store_ceiling(settings, values["Ceiling Z"], ceiling_from)
    values["Width"] = width_m
    values["High Detail"] = resolve_high_detail(context, settings)
    # A docked line runs at its main line's speed, rollers and goods alike
    # (its own Speed field is shown dim with that value).
    from .stream import group_speed

    from ..props.scene_settings import time_scale

    # On screen the goods, belts and rollers move Speed x the scene's clock
    # (props/scene_settings.time_scale); the Speed field stays the real speed.
    from .stream import line_speed

    values["Speed"] = line_speed(context, obj) * (-1.0 if settings.reverse else 1.0) * time_scale(context.scene)
    values["Show Spine"] = scene.conveyor_settings.show_spine
    values["Floor Z"] = float(scene.conveyor_settings.floor_z)
    from .floors import sync_auto_floors

    # Legs and columns stand on the first surface below them: the Floors
    # collection when set, else every mesh in the scene (a ground plane, a
    # mezzanine deck placed under a line...).
    values["Floors"] = scene.conveyor_settings.floor_collection or sync_auto_floors(scene)
    values["Guide Rails"] = settings.guide_rails
    values["Highlight Segment"] = highlight_index_for(context, obj)
    values["Stream Flip"] = bool(settings.reverse)
    from ..geonodes import materials

    for role, mat in zip(materials.SLOT_ROLES, materials.ensure_slots(obj)):
        values[materials.SLOT_INPUTS[role]] = mat
    duty = loader.get_roller_duty_classes().get(conveyor_type.default_duty_class or "standard")
    if duty is not None:
        values["Roller Diameter"] = units.mm_to_bu(duty.diameter_mm, scene)
        values["Idler Diameter"] = units.mm_to_bu(duty.diameter_mm, scene)
    values["Roller Pitch"] = units.mm_to_bu(effective_roller_pitch_mm(settings), scene)
    values["Pulley Diameter"] = units.mm_to_bu(80.0, scene)
    values.update(_BELT_DEFAULTS)
    values.update(_CHAIN_DEFAULTS)
    catalog = loader.get_segment_catalog()
    values["Module Roller Diameter"] = units.mm_to_bu(50.0, scene)
    values["RAT Length"] = units.mm_to_bu(catalog.modules["RAT"].length_mm, scene)  # catalog base; per-RAT length scales it
    values["Merge Length"] = units.mm_to_bu(catalog.modules["MERGE"].length_mm, scene)  # unused: junction decks come from the spine outlines
    values["Diverter Length"] = units.mm_to_bu(catalog.modules["DIVERTER"].length_mm, scene)

    from .populate import populate_values

    values.update(populate_values(context, obj, settings))
    _store_flow_tag(context, obj)
    if conveyor_type.cross_section == "pouch":
        # The pouch sorter: the bag's figures, the overhead rail's section,
        # no fences, the goods dropped into the pouches and turned across the rail.
        from ..model import pouch as pouch_model

        values.update(pouch_model.line_values(settings.pouch_size, settings.pouch_width_mm, settings.pouch_height_mm,
                                              settings.pouch_depth_mm, settings.pouch_pitch_mm, lambda mm: units.mm_to_bu(mm, scene)))
        values["Item Yaw"] = float(values.get("Item Yaw", 0.0)) + math.pi / 2.0
        if values.get("Placeholders") is not None and not values.get("Use Item"):
            # No item picked: goods that fit a pouch, in the placeholders' class order (model/pouch.POUCH_ITEMS).
            from .populate import ensure_pouch_items

            pouch_items = ensure_pouch_items(scene)
            values["Placeholders"] = pouch_items
            values["Placeholder Count"] = len(pouch_items.objects)

    available = set(bc.input_socket_names(tree))
    for name, value in values.items():
        if name in available:
            bc.set_modifier_input(modifier, tree, name, value)


def highlight_index_for(context, obj) -> int:
    """The segment to highlight in the viewport: the active segment of the
    ACTIVE line object, -1 (nothing) on every other line."""
    view_layer = getattr(context, "view_layer", None)
    if view_layer is None or view_layer.objects.active != obj:
        return -1
    settings = obj.conveyor_line
    i = settings.active_segment_index
    return i if 0 <= i < len(settings.segments) else -1


def push_input(obj, name: str, value) -> bool:
    """Writes one modifier input when its value differs (no spine rebuild);
    True when it changed. The same route as push_highlight."""
    modifier = obj.modifiers.get(MODIFIER_NAME)
    if modifier is None or modifier.node_group is None:
        return False
    try:
        socket = bc.find_input_socket(modifier.node_group, name)
    except KeyError:
        return False
    inputs = modifier.properties.inputs
    if socket.identifier not in inputs:
        return False
    old = inputs[socket.identifier].get("value")
    if old is not None and (old == value or (isinstance(value, float) and abs(float(old) - value) < 1e-6)):
        return False
    inputs[socket.identifier]["value"] = value
    obj.update_tag()  # never node_group.interface_update() (see push_highlight)
    return True


def push_highlight(obj, index: int) -> bool:
    """Writes only the Highlight Segment modifier input (no spine rebuild),
    so clicking a row in the segment list is instant. Returns True when the
    value changed."""
    modifier = obj.modifiers.get(MODIFIER_NAME)
    if modifier is None or modifier.node_group is None:
        return False
    try:
        socket = bc.find_input_socket(modifier.node_group, "Highlight Segment")
    except KeyError:
        return False
    inputs = modifier.properties.inputs
    if socket.identifier not in inputs:
        return False
    if inputs[socket.identifier].get("value") == index:
        return False
    inputs[socket.identifier]["value"] = index
    # NOTE: never call node_group.interface_update() here -- on 5.3 it reset
    # every modifier input of OTHER objects using the same tree to zero.
    obj.update_tag()
    return True


def sync_materials(obj) -> bool:
    """Pushes the object's material slots into the modifier when they
    differ (the user edited them in the Material panel). No rebuild."""
    from ..geonodes import materials

    modifier = obj.modifiers.get(MODIFIER_NAME)
    if modifier is None or modifier.node_group is None:
        return False
    changed = False
    inputs = modifier.properties.inputs
    for role, mat in zip(materials.SLOT_ROLES, materials.ensure_slots(obj)):
        try:
            socket = bc.find_input_socket(modifier.node_group, materials.SLOT_INPUTS[role])
        except KeyError:
            continue
        if socket.identifier in inputs and inputs[socket.identifier].get("value") != mat:
            inputs[socket.identifier]["value"] = mat
            changed = True
    if changed:
        obj.update_tag()
    return changed


def all_lines(scene: bpy.types.Scene):
    return [o for o in scene.objects if o.type == 'CURVES' and o.conveyor_line.is_conveyor_line]


class CONVEYOR_OT_build_line(bpy.types.Operator):
    bl_idname = "conveyor.build_line"
    bl_label = "Refresh Line"
    bl_description = "Rebuild this line's spine and geometry from its segment list (normally automatic)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj) and obj.type == 'CURVES' and obj.conveyor_line.is_conveyor_line

    def execute(self, context):
        build_line(context, context.active_object)
        return {'FINISHED'}


class CONVEYOR_OT_regenerate_all(bpy.types.Operator):
    bl_idname = "conveyor.regenerate_all"
    bl_label = "Rebuild All Lines"
    bl_description = "Rebuild every conveyor line in the scene (also applies the scene LOD override)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        lines = all_lines(context.scene)
        for obj in lines:
            build_line(context, obj)
        self.report({'INFO'}, f"Rebuilt {len(lines)} line(s)")
        return {'FINISHED'}


classes = (CONVEYOR_OT_build_line, CONVEYOR_OT_regenerate_all)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
