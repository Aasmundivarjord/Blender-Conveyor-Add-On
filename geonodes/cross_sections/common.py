"""Pieces shared by every line tree (roller / belt / chain): the frame
inputs, the spine split, rails, guide rails, legs and spinning cylinders.

Geometry conventions (the same as model/segments.py):
  - the spine's z IS the conveying surface. Items sit on it with zero
    height offset; rails hang below it by `Rail Top Drop`.
  - every orientation comes from geonodes/frame.py. Instanced parts take
    the Rotation directly; swept parts get it through Set Curve Normal in
    Free mode with the frame's LEFT vector, because Curve to Mesh maps the
    profile's X onto the curve normal and its Y onto tangent x normal --
    with a left-pointing normal that Y is exactly the frame's up (probed
    live on 5.3: normal (1,0,0) along a +Y curve sent profile +Y to -Z).
  - legs are vertical (heading-only rotation) and reach the world floor
    (`Floor Z`) via the object's own Z from Object Info (Self), so moving a
    line up onto a mezzanine lengthens its legs without a rebuild.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .. import materials
from ..builder_common import HIGH_DETAIL_SIDES, LOW_DETAIL_SIDES, NodeGraph
from ..frame import frame_rotation

ROLE_FULL, ROLE_RUN, ROLE_FENCE, ROLE_OUTLINE, RUN_CONVEYOR, RUN_MODULE = 0, 1, 2, 3, 0, 1
ROLE_GUIDE = 4  # continuous fence / leg paths (model/spine.py)
ROLE_COLUMN = 5  # support columns: spiral centers and lift towers
ROLE_ARM = 6  # spiral cantilever arms (drum -> under the track)
# Transfer-section parts (model/spine.py ROLE_PART_*, model/transfer_parts.py).
ROLE_PART_ROLLER, ROLE_PART_BELT, ROLE_PART_CHAIN, ROLE_PART_WHEEL, ROLE_PART_BOX, ROLE_PART_RAIL, ROLE_PART_PLATE = 7, 8, 9, 10, 11, 12, 13
ROLE_LIFT_LOOP = 14  # a fork-column lift's fork path (model/lift_parts.py)
# Fork of a lift (model/lift_parts.py): 8 tines 10 x 20 mm at 75 mm, on a crossbar hung from a leveller trolley.
# 6 tines: the real unit's 8 overhang its column by 70 mm each side, which read as blocks beside the posts.
LIFT_TINE_N, LIFT_TINE_PITCH, LIFT_TINE_W, LIFT_TINE_H, LIFT_TINE_ROOT = 6, 0.075, 0.010, 0.020, 0.03
LIFT_CROSSBAR_W, LIFT_CROSSBAR_H = 0.04, 0.05
# Material of a wheel / box part (transfer_parts.MAT_*): boxes FRAME, BELT,
# ACCENT (module colour) or LINKS; wheels BELT, ACCENT or LINKS (the default).
PART_MAT_FRAME, PART_MAT_BELT, PART_MAT_ACCENT, PART_MAT_LINKS = 0, 2, 3, 4
PART_BELT_W, PART_BELT_T = 0.016, 0.006  # = transfer_parts.BELT_W / BELT_T
PART_CHAIN_W, PART_CHAIN_T = 0.03, 0.02  # = transfer_parts.CHAIN_W / CHAIN_T
PART_PLATE_T = 0.003  # = transfer_parts.PLATE_T
MODULE_KIND_MERGE = 2
MODULE_KIND_DIVERTER = 3  # outbound twin of a merge junction (routing)
MODULE_KIND_BUFFER = 4  # accumulation zone: swept like the conveyor, goods queue at its end
MODULE_KIND_LIFT = 5  # vertical lift: a fork column (parts + instanced forks), no fences / legs, its own combs
MODULE_KIND_ARB = 6  # inline angled-roller element: belt deck with angled rollers (centre / turn goods)
MODULE_KIND_PIVOT = 7  # fixed-pivot turn: swept like the conveyor, a pin at the line edge
# Junction technologies (model/segments.TECH_IDS, config/presets/technologies.json).
TECH_SKEW, TECH_POPUP, TECH_STRIP, TECH_ARB, TECH_PUSHER, TECH_BELT, TECH_CHAIN = 1, 2, 3, 4, 5, 6, 7
ARB_WHEEL_RADIUS = 0.012
ARB_WHEEL_PITCH = 0.06
MIN_CYLINDER_GAP = 0.004

# Bevel radii per part (see builder_common.BEVEL_SEGMENTS for the count).
RAIL_BEVEL = 0.003
GUIDE_BEVEL = 0.0025
LEG_BEVEL = 0.004
BRACKET_BEVEL = 0.0015
CYLINDER_CAP_BEVEL = 0.002


def declare_frame_inputs(g: NodeGraph) -> None:
    g.input("Geometry", 'NodeSocketGeometry')
    g.input("Width", 'NodeSocketFloat', default=0.5, min_value=0.05, subtype='DISTANCE')
    g.input("Rail Height", 'NodeSocketFloat', default=0.10, min_value=0.01, subtype='DISTANCE')
    g.input("Rail Thickness", 'NodeSocketFloat', default=0.02, min_value=0.002, subtype='DISTANCE')
    g.input("Rail Top Drop", 'NodeSocketFloat', default=0.015, min_value=0.0, subtype='DISTANCE')
    g.input("Support Spacing", 'NodeSocketFloat', default=1.5, min_value=0.1, subtype='DISTANCE')
    g.input("Support Size", 'NodeSocketFloat', default=0.06, min_value=0.005, subtype='DISTANCE')
    g.input("Floor Z", 'NodeSocketFloat', default=0.0, subtype='DISTANCE')
    g.input("Floors", 'NodeSocketCollection')  # mezzanines etc.: legs and columns land on the first surface below them
    g.input("Ceiling Mount", 'NodeSocketBool', default=False)  # hung from the ceiling instead of standing on the floor (2.14)
    g.input("Ceiling Z", 'NodeSocketFloat', default=6.0, subtype='DISTANCE')  # world z of the ceiling where no surface is found above
    g.input("Guide Rails", 'NodeSocketBool', default=True)
    g.input("Guide Rail Rise", 'NodeSocketFloat', default=0.12, min_value=0.0, subtype='DISTANCE')
    g.input("Guide Rail Height", 'NodeSocketFloat', default=0.06, min_value=0.005, subtype='DISTANCE')
    g.input("Guide Rail Thickness", 'NodeSocketFloat', default=0.008, min_value=0.001, subtype='DISTANCE')
    g.input("Guide Bracket Pitch", 'NodeSocketFloat', default=1.0, min_value=0.1, subtype='DISTANCE')
    g.input("Highlight Segment", 'NodeSocketInt', default=-1, min_value=-1)
    g.input("Merge Skew", 'NodeSocketFloat', default=0.0, subtype='ANGLE')  # legacy, unused
    # Materials come from the object's material slots (materials.SLOT_ROLES).
    for name in ("Frame Material", "Roller Material", "Belt Material", "Module Material", "Link Material"):
        g.input(name, 'NodeSocketMaterial')
    g.input("High Detail", 'NodeSocketBool', default=True)
    g.input("Speed", 'NodeSocketFloat', default=0.0)  # no min: negative = reverse
    # Routing: a branch line's item stream runs at its main line's speed.
    g.input("Use Stream Speed", 'NodeSocketBool', default=False)
    g.input("Stream Speed", 'NodeSocketFloat', default=0.0)
    # Buffer zones: the queue pitch (item length + gap) sizes the zones and their photo-eyes.
    g.input("Queue Pitch", 'NodeSocketFloat', default=0.65, min_value=0.02, subtype='DISTANCE')
    g.input("Show Spine", 'NodeSocketBool', default=False)
    g.input("Module Roller Diameter", 'NodeSocketFloat', default=0.05, min_value=0.005, subtype='DISTANCE')
    g.input("RAT Length", 'NodeSocketFloat', default=0.9, min_value=0.1, subtype='DISTANCE')
    g.input("Merge Length", 'NodeSocketFloat', default=1.2, min_value=0.1, subtype='DISTANCE')
    g.input("Diverter Length", 'NodeSocketFloat', default=1.5, min_value=0.1, subtype='DISTANCE')


@dataclass
class SpineParts:
    runs: object  # conveyor runs (curves)
    all_runs: object  # conveyor + module runs
    module_runs: object  # module footprints only
    full: object  # the single continuous spline
    frame: object  # Rotation field
    heading_only: object  # Rotation field (yaw only)
    oriented_runs: object  # conveyor runs with Free normals = frame left
    left: object
    oriented_fences: object  # merge fence paths (role 2), oriented like the runs
    oriented_guide_runs: object  # conveyor runs + merge-junction runs: where fences are swept
    outlines: object  # closed merge-junction deck outlines (role 3)
    leg_runs: object = None  # guide paths + RAT module runs: where floor stands go
    columns: object = None  # support column splines (role 5)
    arms: object = None  # spiral support arm splines (role 6)
    part_curves: object = None  # transfer-section parts (roles 7-13, model/transfer_parts.py)
    rail_runs: object = None  # conveyor runs + junction runs, oriented: the frame rails run straight through junctions
    lift_loops: object = None  # fork-column lifts' fork paths (role 14)


def split_spine(g: NodeGraph, geometry) -> SpineParts:
    g.stage("Spine", "the stored centreline split by role: conveyor runs, module runs, the full spline, fences, deck outlines, columns, arms, transfer parts, lift loops; then oriented with the frame's left vector")
    # The spine datablock is stored Catmull-Rom (writing curve_type = POLY
    # on a Curves ID crashes Blender 5.3.0 Alpha, see model/spine.py) and
    # made linear HERE, before anything samples it: every consumer of the
    # spine (runs, full spline, populate, Show Spine) hangs off this node.
    as_poly = g.node('GeometryNodeCurveSplineType', spline_type='POLY')
    g.link(geometry, as_poly.inputs["Curve"])
    geometry = as_poly.outputs["Curve"]
    role = g.named_attribute("role", 'INT')
    run_kind = g.named_attribute("run_kind", 'INT')
    is_run = g.compare('INT', 'EQUAL', role, ROLE_RUN)
    module_kind_c = g.named_attribute("module_kind", 'INT')
    # A buffer module is swept like the conveyor itself (rollers/belt/chain
    # continue through it); only its end stop is a module piece.
    swept_module = g.boolean('OR', g.compare('INT', 'EQUAL', module_kind_c, MODULE_KIND_BUFFER),
                             g.compare('INT', 'EQUAL', module_kind_c, MODULE_KIND_PIVOT))
    is_conveyor_run = g.boolean('AND', is_run, g.boolean('OR', g.compare('INT', 'EQUAL', run_kind, RUN_CONVEYOR), swept_module))
    runs, _ = g.separate_geometry(geometry, is_conveyor_run, 'CURVE')
    all_runs, _ = g.separate_geometry(geometry, is_run, 'CURVE')
    module_runs, _ = g.separate_geometry(all_runs, g.compare('INT', 'EQUAL', run_kind, RUN_MODULE), 'CURVE')
    full, _ = g.separate_geometry(geometry, g.compare('INT', 'EQUAL', role, ROLE_FULL), 'CURVE')
    fences, _ = g.separate_geometry(geometry, g.compare('INT', 'EQUAL', role, ROLE_FENCE), 'CURVE')
    outlines, _ = g.separate_geometry(geometry, g.compare('INT', 'EQUAL', role, ROLE_OUTLINE), 'CURVE')
    columns, _ = g.separate_geometry(geometry, g.compare('INT', 'EQUAL', role, ROLE_COLUMN), 'CURVE')
    arms, _ = g.separate_geometry(geometry, g.compare('INT', 'EQUAL', role, ROLE_ARM), 'CURVE')
    part_curves, _ = g.separate_geometry(geometry, g.boolean('AND', g.compare('INT', 'GREATER_EQUAL', role, ROLE_PART_ROLLER),
                                                             g.compare('INT', 'LESS_EQUAL', role, ROLE_PART_PLATE)), 'CURVE')
    is_rail_run = g.boolean('OR', is_conveyor_run, g.boolean('AND', is_run, is_junction_kind(g, module_kind_c)))
    rail_runs, _ = g.separate_geometry(geometry, is_rail_run, 'CURVE')
    lift_loops, _ = g.separate_geometry(geometry, g.compare('INT', 'EQUAL', role, ROLE_LIFT_LOOP), 'CURVE')
    module_kind = g.named_attribute("module_kind", 'INT')
    # Fences and legs follow the continuous guide paths (role 4: runs joined
    # across junctions, RAT modules left out); RATs get their own legs.
    guide_runs, _ = g.separate_geometry(geometry, g.compare('INT', 'EQUAL', role, ROLE_GUIDE), 'CURVE')
    rat_runs, _ = g.separate_geometry(module_runs, g.compare('INT', 'EQUAL', module_kind, 1), 'CURVE')
    leg_runs = g.join(guide_runs, rat_runs)

    g.column()
    heading = g.named_attribute("heading")
    incline = g.named_attribute("incline")
    frame = frame_rotation(g, heading, incline)
    heading_only = g.euler_to_rotation(g.combine_xyz(z=heading))
    left = g.rotate_vector(g.combine_xyz(x=-1.0), frame)
    normal_node = g.node('GeometryNodeSetCurveNormal')
    g.link(runs, normal_node.inputs["Curve"])
    normal_node.inputs["Mode"].default_value = "Free"
    g.link(left, normal_node.inputs["Normal"])
    fence_normal = g.node('GeometryNodeSetCurveNormal')
    g.link(fences, fence_normal.inputs["Curve"])
    fence_normal.inputs["Mode"].default_value = "Free"
    g.link(left, fence_normal.inputs["Normal"])
    guide_normal = g.node('GeometryNodeSetCurveNormal')
    g.link(guide_runs, guide_normal.inputs["Curve"])
    guide_normal.inputs["Mode"].default_value = "Free"
    g.link(left, guide_normal.inputs["Normal"])
    rail_normal = g.node('GeometryNodeSetCurveNormal')
    g.link(rail_runs, rail_normal.inputs["Curve"])
    rail_normal.inputs["Mode"].default_value = "Free"
    g.link(left, rail_normal.inputs["Normal"])
    return SpineParts(runs, all_runs, module_runs, full, frame, heading_only, normal_node.outputs["Curve"], left,
                      fence_normal.outputs["Curve"], guide_normal.outputs["Curve"], outlines, leg_runs, columns, arms,
                      part_curves, rail_normal.outputs["Curve"], lift_loops)


def is_junction_kind(g: NodeGraph, module_kind):
    """Merge junctions and diverters share one construction (spine outline + rollers)."""
    return g.boolean('OR', g.compare('INT', 'EQUAL', module_kind, MODULE_KIND_MERGE),
                     g.compare('INT', 'EQUAL', module_kind, MODULE_KIND_DIVERTER))


def rail_offset(g: NodeGraph, gi):
    return g.math('ADD', g.math('DIVIDE', gi.outputs["Width"], 2.0), g.math('DIVIDE', gi.outputs["Rail Thickness"], 2.0))


def build_rails(g: NodeGraph, gi, parts: SpineParts, offset):
    """Two frame rails; profile X = left of travel, Y = up."""
    g.stage("Frame rails", "the two side rails, a filleted profile swept along the runs (straight through junctions)")
    rail_height = gi.outputs["Rail Height"]
    center_y = g.math('MULTIPLY', g.math('ADD', gi.outputs["Rail Top Drop"], g.math('DIVIDE', rail_height, 2.0)), -1.0)
    profile = g.filleted_rectangle(gi.outputs["Rail Thickness"], rail_height, RAIL_BEVEL)
    pair = g.join(
        g.transform(profile, translation=g.combine_xyz(x=offset, y=center_y)),
        g.transform(profile, translation=g.combine_xyz(x=g.math('MULTIPLY', offset, -1.0), y=center_y)),
    )
    # Straight through junctions too: a real merge / transfer keeps the main
    # line's side frames (the roller tops sit above them, goods pass over).
    runs = parts.rail_runs if parts.rail_runs is not None else parts.oriented_runs
    return g.set_material(g.curve_to_mesh(runs, pair, fill_caps=True), gi.outputs["Frame Material"])


def build_guides(g: NodeGraph, gi, parts: SpineParts, offset):
    """Guide rails, one sweep per side so each can be opened where another
    line merges in: the spine's `guide_gap` bitmask reaches the swept mesh
    through Curve to Mesh, and faces whose corners all sit inside the gap
    are deleted (boundary samples are exact, see model/spine.py).

    Each rail is held by L-brackets every `Guide Bracket Pitch`: a vertical
    plate on the OUTSIDE of the guide rail (goods never touch it) running
    from the frame rail's top up to the guide rail's top, with a foot tab
    resting on the frame rail. Brackets are skipped inside merge openings."""
    g.stage("Fences", "guide rails on their brackets along the continuous guide paths, opened where lines merge")
    height = gi.outputs["Guide Rail Height"]
    rise = gi.outputs["Guide Rail Rise"]
    guide_thickness = gi.outputs["Guide Rail Thickness"]
    rail_top_drop = gi.outputs["Rail Top Drop"]
    center_y = g.math('ADD', rise, g.math('DIVIDE', height, 2.0))
    profile = g.filleted_rectangle(guide_thickness, height, GUIDE_BEVEL)
    steel = gi.outputs["Frame Material"]

    # Bracket mesh, built once per side in the frame's local axes
    # (X = left of travel, Y = along travel, Z = up), then instanced.
    plate_t, plate_w, foot_t = 0.006, 0.04, 0.006
    plate_h = g.math('ADD', g.math('ADD', rise, height), rail_top_drop)
    plate_z = g.math('DIVIDE', g.math('SUBTRACT', g.math('ADD', rise, height), rail_top_drop), 2.0)
    plate_x_mag = g.math('ADD', offset, g.math('ADD', g.math('DIVIDE', guide_thickness, 2.0), plate_t / 2.0))
    foot_z = g.math('ADD', g.math('MULTIPLY', rail_top_drop, -1.0), foot_t / 2.0)
    foot_w = g.math('ADD', gi.outputs["Rail Thickness"], 2.0 * plate_t)
    # Per-side 0/1 opening flags on the guide curve, stored BEFORE resampling
    # so the resampled points interpolate a flag, never the bitmask (an
    # interpolated bitmask read as the wrong side and left brackets standing
    # inside the openings).
    flagged_runs = parts.oriented_guide_runs
    gap_bits_pt = g.named_attribute("guide_gap", 'INT')
    for _sign, bit in ((1.0, 1), (-1.0, 2)):
        st = g.node('GeometryNodeStoreNamedAttribute', data_type='FLOAT', domain='POINT')
        g.link(flagged_runs, st.inputs["Geometry"])
        st.inputs["Name"].default_value = f"guide_open_{bit}"
        g.link(g.math('DIVIDE', _bit_and(g, gap_bits_pt, bit), float(bit)), st.inputs["Value"])
        flagged_runs = st.outputs["Geometry"]
    bracket_points = g.curve_to_points_evaluated(g.resample_length(flagged_runs, gi.outputs["Guide Bracket Pitch"]))

    # Profile X = left of travel: +offset is the LEFT guide (bit 1), -offset the RIGHT (bit 2).
    sides = ((1.0, 1), (-1.0, 2))
    meshes = []
    for sign, bit in sides:
        x_offset = g.math('MULTIPLY', offset, sign)
        # This side's opening as a 0/1 POINT attribute on the curve BEFORE the
        # sweep. The bitmask itself must never be interpolated: a face at the
        # start of a RIGHT opening averages corners 0 and 2 to 1 = "LEFT open"
        # and deleted the far fence along the whole neighbouring straight
        # (the "fences bug at merges", 2026-09-24).
        mesh = g.curve_to_mesh(flagged_runs, g.transform(profile, translation=g.combine_xyz(x=x_offset, y=center_y)), fill_caps=True)
        # Face-domain evaluation averages the corner flags: only faces with EVERY corner inside the opening reach 1.
        delete = g.node('GeometryNodeDeleteGeometry', domain='FACE', mode='ALL')
        g.link(mesh, delete.inputs["Geometry"])
        g.link(g.compare('FLOAT', 'GREATER_THAN', g.named_attribute(f"guide_open_{bit}"), 0.999), delete.inputs["Selection"])
        meshes.append(delete.outputs["Geometry"])

        plate = g.transform(g.rounded_box(plate_t, plate_w, plate_h, BRACKET_BEVEL),
                            translation=g.combine_xyz(x=g.math('MULTIPLY', plate_x_mag, sign), z=plate_z))
        foot = g.transform(g.rounded_box(foot_w, plate_w, foot_t, BRACKET_BEVEL),
                           translation=g.combine_xyz(x=x_offset, z=foot_z))
        bracket = g.join(plate, foot)
        # Point-domain test on the resampled points via this side's flag, plus
        # the docked-end exclusion (spine attribute `bracket_skip`). NOTE the
        # bracket is rotated by the spine FRAME, whose X axis is RIGHT of
        # travel (the rail profile's X is LEFT, via the Free normal), so the
        # bracket at +plate_x_mag stands on the RIGHT rail: test the other
        # side's flag. (Kept the far bracket and dropped the near one before.)
        bracket_bit = 3 - bit
        point_in_gap = g.compare('FLOAT', 'GREATER_THAN', g.named_attribute(f"guide_open_{bracket_bit}"), 0.5)
        point_skip = g.compare('FLOAT', 'GREATER_THAN', g.named_attribute("bracket_skip"), 0.5)
        meshes.append(g.instance_on_points(bracket_points, bracket, rotation=parts.frame,
                                           selection=g.boolean('NOT', g.boolean('OR', point_in_gap, point_skip))))
    # Merge fences: already at their lateral position, so the profile is centered.
    meshes.append(g.curve_to_mesh(parts.oriented_fences, g.transform(profile, translation=g.combine_xyz(y=center_y)), fill_caps=True))
    guides = g.set_material(g.join(*meshes), steel)
    return g.switch('GEOMETRY', gi.outputs["Guide Rails"], None, guides)


def _bit_and(g: NodeGraph, value, bit: int):
    """value & bit for small positive ints without a bitwise node:
    floor(value / bit) is odd  <=>  the bit is set."""
    quotient = g.math('FLOOR', g.math('DIVIDE', value, float(bit)))
    return g.math('MULTIPLY', g.math('MODULO', quotient, 2.0), float(bit))


def floor_below(g: NodeGraph, gi):
    """Per-point field: the local z of the floor under the point -- the first
    surface of the `Floors` collection hit by a ray cast straight down (a
    mezzanine deck), else the world `Floor Z`. Object-relative like the
    spine, so moving a line up lengthens its legs unless a floor is under it."""
    self_info = g.node('GeometryNodeObjectInfo')
    g.link(g.node('GeometryNodeSelfObject').outputs["Self Object"], self_info.inputs["Object"])
    _, _, object_z = g.separate_xyz(self_info.outputs["Location"])
    floor_local = g.math('SUBTRACT', gi.outputs["Floor Z"], object_z)
    floors = g.node('GeometryNodeCollectionInfo', transform_space='RELATIVE')
    g.link(gi.outputs["Floors"], floors.inputs["Collection"])
    floors.inputs["Separate Children"].default_value = False
    target = g.realize(floors.outputs["Instances"])
    ray = g.node('GeometryNodeRaycast')
    g.link(target, ray.inputs["Target Geometry"])
    g.link(g.vmath('ADD', g.position(), g.combine_xyz(z=-0.001)), ray.inputs["Source Position"])
    ray.inputs["Ray Direction"].default_value = (0.0, 0.0, -1.0)
    ray.inputs["Ray Length"].default_value = 500.0
    _, _, hit_z = g.separate_xyz(ray.outputs["Hit Position"])
    return g.switch('FLOAT', ray.outputs["Is Hit"], floor_local, hit_z)


def ceiling_above(g: NodeGraph, gi):
    """Per-point field: the local z of the ceiling over the point -- the first
    surface of the `Floors` collection hit by a ray cast straight up (a
    mezzanine deck's underside, a roof slab), else the world `Ceiling Z`
    (lines hung from the ceiling: pouch sorters)."""
    self_info = g.node('GeometryNodeObjectInfo')
    g.link(g.node('GeometryNodeSelfObject').outputs["Self Object"], self_info.inputs["Object"])
    _, _, object_z = g.separate_xyz(self_info.outputs["Location"])
    ceiling_local = g.math('SUBTRACT', gi.outputs["Ceiling Z"], object_z)
    floors = g.node('GeometryNodeCollectionInfo', transform_space='RELATIVE')
    g.link(gi.outputs["Floors"], floors.inputs["Collection"])
    floors.inputs["Separate Children"].default_value = False
    target = g.realize(floors.outputs["Instances"])
    ray = g.node('GeometryNodeRaycast')
    g.link(target, ray.inputs["Target Geometry"])
    g.link(g.vmath('ADD', g.position(), g.combine_xyz(z=0.001)), ray.inputs["Source Position"])
    ray.inputs["Ray Direction"].default_value = (0.0, 0.0, 1.0)
    ray.inputs["Ray Length"].default_value = 500.0
    _, _, hit_z = g.separate_xyz(ray.outputs["Hit Position"])
    return g.switch('FLOAT', ray.outputs["Is Hit"], ceiling_local, hit_z)


def support_stations(g: NodeGraph, gi, source):
    """The stands' places along `source` curves: the spine samples marked
    `stand` (model/legs.plan_stands, through model/spine.write_spine): a stand
    flush with each end of every supported stretch and evenly between, at
    most Support Spacing apart, none on leg-free pieces or spirals, none that
    the user took out. A sample shared by two curves counts once."""
    g.stage("Stations", "the planned stands: spine samples marked stand = 1 (flush ends, even spacing, none on leg-free pieces)")
    points = g.curve_to_points_evaluated(source)
    keep = g.node('GeometryNodeDeleteGeometry', domain='POINT')
    g.link(points, keep.inputs["Geometry"])
    g.link(g.boolean('NOT', g.compare('FLOAT', 'GREATER_THAN', g.named_attribute("stand"), 0.5)), keep.inputs["Selection"])
    merged = g.node('GeometryNodeMergeByDistance')
    g.link(keep.outputs["Geometry"], merged.inputs["Geometry"])
    merged.inputs["Distance"].default_value = 0.01
    return merged.outputs["Geometry"]


def build_columns(g: NodeGraph, gi, parts: SpineParts):
    """Support columns from each column spline's first point down to the
    floor below it: round drums (a spiral's centre) or, when the spline
    carries part_r / part_h, a box that wide along the heading and that
    deep (a fork lift's column body)."""
    g.stage("Columns", "spiral drums and lift towers, from the track down to the floor")
    tops = g.node('GeometryNodeCurveToPoints', mode='COUNT')
    g.link(parts.columns, tops.inputs["Curve"])
    tops.inputs["Count"].default_value = 1
    _, _, point_z = g.separate_xyz(g.position())
    length_field = g.math('MAXIMUM', g.math('SUBTRACT', point_z, floor_below(g, gi)), 0.05)
    store = g.node('GeometryNodeStoreNamedAttribute', data_type='FLOAT', domain='POINT')
    g.link(tops.outputs["Points"], store.inputs["Geometry"])
    store.inputs["Name"].default_value = "column_height"
    g.link(length_field, store.inputs["Value"])
    height = g.named_attribute("column_height")
    is_box = g.compare('FLOAT', 'GREATER_THAN', g.named_attribute("part_r"), 0.001)
    box_points, round_points = g.separate_geometry(store.outputs["Geometry"], is_box, 'POINT')
    unit_line = g.line((0.0, 0.0, 0.0), (0.0, 0.0, -1.0))
    lines = g.realize(g.instance_on_points(round_points, unit_line, scale=g.combine_xyz(x=1.0, y=1.0, z=height)))
    circle = g.node('GeometryNodeCurvePrimitiveCircle')
    circle.inputs["Resolution"].default_value = 24
    circle.inputs["Radius"].default_value = 0.22  # = model/spine.DRUM_RADIUS_M
    drums = g.set_material(g.curve_to_mesh(lines, circle.outputs["Curve"], fill_caps=True), gi.outputs["Frame Material"])
    cube = g.set_material(g.cube((1.0, 1.0, 1.0)), gi.outputs["Frame Material"])
    centred = g.set_position(box_points, offset=g.combine_xyz(z=g.math('MULTIPLY', height, -0.5)))
    boxes = g.instance_on_points(centred, cube, rotation=g.euler_to_rotation(g.combine_xyz(z=g.named_attribute("heading"))),
                                 scale=g.combine_xyz(x=g.named_attribute("part_h"), y=g.named_attribute("part_r"), z=height))
    return g.join(drums, boxes)


def build_lift_forks(g: NodeGraph, gi, parts: SpineParts, speed):
    """The forks of the fork-column lifts (model/lift_parts.py), riding
    round each lift's loop curve (role 14) at the stream speed.

    Fork pitch = the item slot pitch (populate.slot_pitch: the pitch the
    goods really sit on) divided by m = floor(slot / `Lift k Fork Pitch`),
    so the forks are about as far apart as the user asked (segment Fork
    Pitch, 400 mm by default) and the goods land on every m-th (user
    request 2026-10-08: "more forks", and control over how many). Phased
    by `Lift k Phase` so a fork is under every load.

    The loop's length is not a multiple of the pitch, and forks used to be
    laid out from the seam and dropped past the end -- one popped in and
    out at the bottom apex every slot. Now ALL n = round(loop / pitch)
    forks live on a uniform grid of n * pitch that is mapped onto the
    loop: identity between the pick and the drop corner (margins of half a
    slot either side, so the forks there are exactly on the goods), and a
    uniform stretch (a few percent) over the empty return leg that absorbs
    the remainder. Continuous round the seam, so nothing spawns.

    Only the fork shows: tines on a crossbar coming out of the column's
    opening. The leveller trolley rides inside the column, so none is
    drawn (the blocks that used to sit on the face at every fork read as
    "cubes"). Forks under the floor are hidden (a line laid on the floor
    has the bottom turn 0.36 m below it; the panel asks to raise it)."""
    from ..populate import slot_pitch

    if parts.lift_loops is None:
        return None
    g.stage("Lift forks", "fork carriers instanced round each lift's loop, ~0.4 m apart on the slot grid and phased onto the goods")
    pitch, inset = slot_pitch(g, gi, parts.full)
    lift_index = g.named_attribute("lift_index", 'INT')
    steel = gi.outputs["Frame Material"]
    tines = g.join(*[g.transform(g.cube((1.0, LIFT_TINE_W, LIFT_TINE_H)),
                                 translation=(0.5, (k - (LIFT_TINE_N - 1) / 2.0) * LIFT_TINE_PITCH, -LIFT_TINE_H / 2.0))
                     for k in range(LIFT_TINE_N)])
    tines = g.set_material(tines, steel)
    crossbar = g.set_material(g.transform(g.cube((LIFT_CROSSBAR_W, LIFT_TINE_N * LIFT_TINE_PITCH - 0.07, LIFT_CROSSBAR_H)),
                                          translation=(0.0, 0.0, -LIFT_CROSSBAR_H / 2.0 + 0.005)), steel)
    seconds = g.scene_seconds()
    floor = floor_below(g, gi)
    pieces = []
    for k in (1, 2):
        g.column()
        loop, _ = g.separate_geometry(parts.lift_loops, g.compare('INT', 'EQUAL', lift_index, k), 'CURVE')
        active, phase = gi.outputs[f"Lift {k} Active"], gi.outputs[f"Lift {k} Phase"]
        face, reach = gi.outputs[f"Lift {k} Face"], gi.outputs[f"Lift {k} Reach"]
        # The user's fork pitch, rounded down to a divisor of the slot so the goods land on forks.
        forks_per_slot = g.math('MAXIMUM', g.math('FLOOR', g.math('DIVIDE', pitch, g.math('MAXIMUM', gi.outputs[f"Lift {k} Fork Pitch"], 0.05))), 1.0)
        fork_pitch = g.math('DIVIDE', pitch, forks_per_slot)
        length_node = g.node('GeometryNodeCurveLength')
        g.link(loop, length_node.inputs["Curve"])
        total = g.math('MAXIMUM', length_node.outputs["Length"], 0.001)
        # The uniform grid: n forks, n * fork_pitch long (close to the loop).
        count = g.math('MAXIMUM', g.math('ROUND', g.math('DIVIDE', total, fork_pitch)), 1.0)
        total_u = g.math('MULTIPLY', count, fork_pitch)
        # Fork j sits at j * fork_pitch + shift on the grid; the shift walks with the goods.
        shift = g.math('ADD', g.math('ADD', phase, g.math('SUBTRACT', inset, gi.outputs["Stream Offset"])), g.math('MULTIPLY', seconds, speed))
        shift = g.math('MODULO', g.math('ADD', g.math('MODULO', shift, fork_pitch), fork_pitch), fork_pitch)
        u = g.math('MODULO', g.math('ADD', g.math('MULTIPLY', g.index(), fork_pitch), shift), total_u)
        # Grid -> loop: identity on [a, b] (pick - half a slot .. drop + half a
        # slot), the rest stretched by k so the seam closes (see docstring).
        pick, drop = gi.outputs[f"Lift {k} Pick"], gi.outputs[f"Lift {k} Drop"]
        # Margins of up to half a slot either side, trimmed so that at least
        # one fork pitch of the return leg is left to absorb the remainder
        # (a low lift with a long slot used to leave none: the stretch went
        # to infinity and the forks jumped the seam).
        room = g.math('SUBTRACT', g.math('SUBTRACT', total_u, fork_pitch), g.math('SUBTRACT', drop, pick))
        margin = g.math('MINIMUM', g.math('MAXIMUM', g.math('MULTIPLY', room, 0.5), 0.0), g.math('MULTIPLY', pitch, 0.5))
        a = g.math('MAXIMUM', g.math('SUBTRACT', pick, margin), 0.0)
        b = g.math('MINIMUM', g.math('ADD', drop, margin), g.math('MINIMUM', total, total_u))
        loaded = g.math('SUBTRACT', b, a)
        stretch = g.math('DIVIDE', g.math('SUBTRACT', total, loaded),
                         g.math('MAXIMUM', g.math('SUBTRACT', total_u, loaded), g.math('MULTIPLY', fork_pitch, 0.5)))
        before = g.math('SUBTRACT', a, g.math('MULTIPLY', g.math('SUBTRACT', a, u), stretch))  # u < a
        after = g.math('ADD', b, g.math('MULTIPLY', g.math('SUBTRACT', u, b), stretch))  # u > b
        along = g.switch('FLOAT', g.compare('FLOAT', 'LESS_THAN', u, a), g.switch('FLOAT', g.compare('FLOAT', 'GREATER_THAN', u, b), u, after), before)
        along = g.math('MODULO', g.math('ADD', g.math('MODULO', along, total), total), total)
        sample = g.node('GeometryNodeSampleCurve', mode='LENGTH', data_type='FLOAT')
        sample.use_all_curves = True
        g.link(loop, sample.inputs["Curves"])
        g.link(g.named_attribute("heading"), sample.inputs["Value"])
        g.link(along, sample.inputs["Length"])
        pts = g.node('GeometryNodePoints')
        g.link(count, pts.inputs["Count"])
        g.link(sample.outputs["Position"], pts.inputs["Position"])
        store = g.node('GeometryNodeStoreNamedAttribute', data_type='FLOAT', domain='POINT')
        g.link(pts.outputs["Points"], store.inputs["Geometry"])
        store.inputs["Name"].default_value = "fork_heading"
        g.link(sample.outputs["Value"], store.inputs["Value"])
        points = store.outputs["Geometry"]
        _, _, point_z = g.separate_xyz(g.position())
        points, _ = g.separate_geometry(points, g.compare('FLOAT', 'GREATER_THAN', point_z, g.math('ADD', floor, 0.03)), 'POINT')
        heading = g.named_attribute("fork_heading")
        frame_rot = g.euler_to_rotation(g.combine_xyz(z=heading))
        # Tines point from the face across the line: mirrored (a right-hand
        # column) by a half turn, never by a negative scale.
        toward = g.math('SIGN', reach)
        tine_rot = g.euler_to_rotation(g.combine_xyz(z=g.math('ADD', heading, g.switch('FLOAT', g.compare('FLOAT', 'LESS_THAN', reach, 0.0), 0.0, math.pi))))
        root = g.math('ADD', face, g.math('MULTIPLY', toward, LIFT_TINE_ROOT))
        at_root = g.set_position(points, offset=g.rotate_vector(g.combine_xyz(x=root), frame_rot))
        at_bar = g.set_position(points, offset=g.rotate_vector(g.combine_xyz(x=g.math('ADD', face, g.math('MULTIPLY', toward, LIFT_CROSSBAR_W / 2.0 - 0.005))), frame_rot))
        forks = g.join(g.instance_on_points(at_root, tines, rotation=tine_rot, scale=g.combine_xyz(x=g.math('ABSOLUTE', reach), y=1.0, z=1.0)),
                       g.instance_on_points(at_bar, crossbar, rotation=frame_rot))
        pieces.append(g.switch('GEOMETRY', active, None, forks))
    return g.join(*pieces)


def build_arms(g: NodeGraph, gi, parts: SpineParts):
    """Spiral cantilever arms: role-6 splines swept with a rectangular tube."""
    g.stage("Spiral arms", "cantilever arms from the drum out under the spiral's track")
    normal = g.node('GeometryNodeSetCurveNormal')
    g.link(parts.arms, normal.inputs["Curve"])
    normal.inputs["Mode"].default_value = "Free"
    normal.inputs["Normal"].default_value = (0.0, 0.0, 1.0)
    profile = g.filleted_rectangle(0.08, 0.05, 0.004)
    return g.set_material(g.curve_to_mesh(normal.outputs["Curve"], profile, fill_caps=True), gi.outputs["Frame Material"])


def swept_posts(g: NodeGraph, post_points: list, length, size, material, rotation):
    """Square-tube posts `length` (a field on the points) down from every
    point of the `post_points` geometries (stand stations carrying the
    spine's `heading`). Every post has its own height, so a scaled box would
    stretch its bevel: a unit line is instanced with the length as Z scale,
    realized, and swept with a filleted square profile oriented by the
    heading carried over as an instance attribute."""
    unit_line = g.line((0.0, 0.0, 0.0), (0.0, 0.0, -1.0))
    post_scale = g.combine_xyz(x=1.0, y=1.0, z=length)
    post_lines = [g.instance_on_points(pts, unit_line, rotation=rotation, scale=post_scale) for pts in post_points]
    carry = g.node('GeometryNodeStoreNamedAttribute', data_type='FLOAT', domain='INSTANCE')
    g.link(g.join(*post_lines), carry.inputs["Geometry"])
    carry.inputs["Name"].default_value = "post_heading"
    g.link(g.named_attribute("heading"), carry.inputs["Value"])
    post_curves = g.node('GeometryNodeSetCurveNormal')
    g.link(g.realize(carry.outputs["Geometry"]), post_curves.inputs["Curve"])
    post_curves.inputs["Mode"].default_value = "Free"
    g.link(g.rotate_vector(g.combine_xyz(x=-1.0), g.euler_to_rotation(g.combine_xyz(z=g.named_attribute("post_heading")))),
           post_curves.inputs["Normal"])
    return g.set_material(g.curve_to_mesh(post_curves.outputs["Curve"], g.filleted_rectangle(size, size, LEG_BEVEL), fill_caps=True), material)


def build_legs(g: NodeGraph, gi, parts: SpineParts, offset, curves=None):
    """H-frame floor stands every `Support Spacing` along `curves`
    (default: all runs incl. modules), like a real roller-conveyor support:
    two square-tube posts under the frame rails, a top cross member the
    frame sits on, a lower cross brace, and square foot plates on the
    world floor (`Floor Z`). Post length is a per-point field (surface
    height minus rail depth minus floor), so an incline's stands grow
    with it and lifting the object onto a mezzanine lengthens them."""
    g.stage("Legs", "a stand flush with each end of every run, the rest spaced evenly (at most Support Spacing apart), each reaching the floor or the mezzanine below it")
    source = curves if curves is not None else (parts.leg_runs if parts.leg_runs is not None else parts.all_runs)
    # Stands at BOTH ends of every run and evenly in between, the end stands
    # flush with the conveyor's end face (user request 2026-10-06), none on
    # spirals (they hang on their drum) or leg-free pieces, one flush with
    # each edge of a leg-free stretch (support_stations).
    size = gi.outputs["Support Size"]
    points = support_stations(g, gi, source)
    _, _, point_z = g.separate_xyz(g.position())
    rail_bottom_drop = g.math('ADD', gi.outputs["Rail Top Drop"], gi.outputs["Rail Height"])
    leg_length_field = g.math('MAXIMUM', g.math('SUBTRACT', g.math('SUBTRACT', point_z, rail_bottom_drop), floor_below(g, gi)), 0.01)
    # Freeze the stand height on the points: fields are evaluated on the
    # geometry they are plugged into, and the post scale is evaluated on
    # points already shifted down to the rail bottom -- reading Position
    # there made every post 115 mm too short and left the feet floating.
    store_len = g.node('GeometryNodeStoreNamedAttribute', data_type='FLOAT', domain='POINT')
    g.link(points, store_len.inputs["Geometry"])
    store_len.inputs["Name"].default_value = "stand_height"
    g.link(leg_length_field, store_len.inputs["Value"])
    points = store_len.outputs["Geometry"]
    leg_length = g.named_attribute("stand_height")
    steel = gi.outputs["Frame Material"]

    rail_bottom = g.math('MULTIPLY', rail_bottom_drop, -1.0)  # z of the rail underside, relative to the surface point
    floor_z = g.math('SUBTRACT', rail_bottom, leg_length)  # z of the floor, relative to the surface point
    span = g.math('MULTIPLY', offset, 2.0)  # rail center to rail center
    pieces = []
    foot = g.set_material(g.transform(g.rounded_box(g.math('MULTIPLY', size, 2.4), g.math('MULTIPLY', size, 2.4), 0.012, LEG_BEVEL),
                                      translation=g.combine_xyz(z=0.006)), steel)
    post_points = []
    for sign in (1.0, -1.0):
        lateral = g.rotate_vector(g.combine_xyz(x=g.math('MULTIPLY', offset, sign)), parts.heading_only)
        lx, ly, _ = g.separate_xyz(lateral)
        post_points.append(g.set_position(points, offset=g.combine_xyz(x=lx, y=ly, z=rail_bottom)))
        foot_points = g.set_position(points, offset=g.combine_xyz(x=lx, y=ly, z=floor_z))
        pieces.append(g.instance_on_points(foot_points, foot, rotation=parts.heading_only))
    pieces.append(swept_posts(g, post_points, leg_length, size, steel, parts.heading_only))
    # Top cross member the frame rests on, spanning both posts.
    top_h = g.math('MULTIPLY', size, 0.8)
    top = g.set_material(g.rounded_box(g.math('ADD', span, size), size, top_h, LEG_BEVEL), steel)
    top_points = g.set_position(points, offset=g.combine_xyz(z=g.math('SUBTRACT', rail_bottom, g.math('DIVIDE', top_h, 2.0))))
    pieces.append(g.instance_on_points(top_points, top, rotation=parts.heading_only))
    # Lower cross brace 300 mm above the floor (or mid-post on short stands).
    brace_h = g.math('MINIMUM', 0.30, g.math('MULTIPLY', leg_length, 0.5))
    brace_t = g.math('MULTIPLY', size, 0.6)
    brace = g.set_material(g.rounded_box(g.math('SUBTRACT', span, size), brace_t, brace_t, LEG_BEVEL), steel)
    brace_points = g.set_position(points, offset=g.combine_xyz(z=g.math('ADD', floor_z, brace_h)))
    pieces.append(g.instance_on_points(brace_points, brace, rotation=parts.heading_only))
    floor_parts = g.join(*pieces)
    # Hung from the ceiling (2.14): a trapeze hanger at every stand -- a cross
    # member under the frame and a drop rod beside each rail up to the ceiling
    # (the first surface above, else the Ceiling level), a plate on each.
    rod_x = g.math('ADD', offset, g.math('ADD', g.math('MULTIPLY', size, 0.5), 0.04))
    cross_bottom = g.math('SUBTRACT', rail_bottom, top_h)  # z of the cross member's underside, relative to the surface point
    _, _, surface_z = g.separate_xyz(g.position())
    rod_field = g.math('MAXIMUM', g.math('SUBTRACT', g.math('SUBTRACT', ceiling_above(g, gi), surface_z), cross_bottom), 0.05)
    store_rod = g.node('GeometryNodeStoreNamedAttribute', data_type='FLOAT', domain='POINT')
    g.link(points, store_rod.inputs["Geometry"])
    store_rod.inputs["Name"].default_value = "hanger_rod"
    g.link(rod_field, store_rod.inputs["Value"])
    cpoints = store_rod.outputs["Geometry"]
    rod_len = g.named_attribute("hanger_rod")
    cross = g.set_material(g.rounded_box(g.math('ADD', g.math('MULTIPLY', rod_x, 2.0), 0.05), size, top_h, LEG_BEVEL), steel)
    ceiling_pieces = [g.instance_on_points(g.set_position(cpoints, offset=g.combine_xyz(z=g.math('SUBTRACT', rail_bottom, g.math('DIVIDE', top_h, 2.0)))),
                                           cross, rotation=parts.heading_only)]
    rod = g.set_material(g.cube((1.0, 1.0, 1.0)), steel)
    plate = g.set_material(g.rounded_box(0.12, 0.12, 0.012, LEG_BEVEL), steel)
    for sign in (1.0, -1.0):
        lateral = g.rotate_vector(g.combine_xyz(x=g.math('MULTIPLY', rod_x, sign)), parts.heading_only)
        lx, ly, _ = g.separate_xyz(lateral)
        rod_points = g.set_position(cpoints, offset=g.combine_xyz(x=lx, y=ly, z=g.math('ADD', cross_bottom, g.math('DIVIDE', rod_len, 2.0))))
        ceiling_pieces.append(g.instance_on_points(rod_points, rod, rotation=parts.heading_only, scale=g.combine_xyz(x=0.016, y=0.016, z=rod_len)))
        plate_points = g.set_position(cpoints, offset=g.combine_xyz(x=lx, y=ly, z=g.math('SUBTRACT', g.math('ADD', cross_bottom, rod_len), 0.006)))
        ceiling_pieces.append(g.instance_on_points(plate_points, plate, rotation=parts.heading_only))
    return g.switch('GEOMETRY', gi.outputs["Ceiling Mount"], floor_parts, g.join(*ceiling_pieces))


# Omni-wheel deck (see cross_sections/omni.py).
OMNI_WHEEL_RADIUS = 0.02
OMNI_WHEEL_WIDTH = 0.016
OMNI_ROW_PITCH = 0.09  # rows along travel
OMNI_WHEEL_PITCH = 0.09  # wheels across a row
OMNI_DECK_T = 0.02


def omni_wheel(g: NodeGraph, gi, radius_m: float = OMNI_WHEEL_RADIUS, width_m: float = OMNI_WHEEL_WIDTH):
    """One omni / pop-up / angled-roller wheel: a small cylinder across the flow (axle = frame X), spinning at the line's speed."""
    radius = g.math('ADD', radius_m, 0.0)  # sockets: spinning_cylinder links them
    width = g.math('ADD', width_m, 0.0)
    return spinning_cylinder(g, g.switch('INT', gi.outputs["High Detail"], 10, 16), radius, width,
                             gi.outputs["Speed"], gi.outputs["Roller Material"])


def wheel_row(g: NodeGraph, gi, count, pitch: float, radius_m: float, width_m: float, yaw=None, herringbone_rad: float = 0.0):
    """`count` wheels across the flow (local X), `pitch` apart, centred on
    the origin. `yaw` (a constant) or `herringbone_rad` (left half +, right
    half -) angles the wheels about Z."""
    line = g.node('GeometryNodeMeshLine', mode='OFFSET')
    g.link(count, line.inputs["Count"])
    start_x = g.math('MULTIPLY', g.math('MULTIPLY', g.math('SUBTRACT', count, 1.0), pitch), -0.5)
    g.link(g.combine_xyz(x=start_x), line.inputs["Start Location"])
    line.inputs["Offset"].default_value = (pitch, 0.0, 0.0)
    to_points = g.node('GeometryNodeMeshToPoints')
    g.link(line.outputs["Mesh"], to_points.inputs["Mesh"])
    wheel = omni_wheel(g, gi, radius_m, width_m)
    if herringbone_rad:
        px, _py, _pz = g.separate_xyz(g.position())
        rotation = g.euler_to_rotation(g.combine_xyz(z=g.math('MULTIPLY', g.math('SIGN', g.math('ADD', px, 1e-4)), -herringbone_rad)))
        return g.instance_on_points(to_points.outputs["Points"], wheel, rotation=rotation)
    if yaw:
        return g.instance_on_points(to_points.outputs["Points"], wheel, rotation=g.euler_to_rotation(g.combine_xyz(z=yaw)))
    return g.instance_on_points(to_points.outputs["Points"], wheel)


def build_omni_deck(g: NodeGraph, gi, oriented_curves):
    """Flat deck plate under the wheels along the given oriented runs."""
    profile = g.transform(g.filleted_rectangle(gi.outputs["Width"], OMNI_DECK_T, 0.003),
                          translation=g.combine_xyz(y=-(OMNI_WHEEL_RADIUS + OMNI_DECK_T / 2.0)))
    return g.set_material(g.curve_to_mesh(oriented_curves, profile, fill_caps=True), gi.outputs["Module Material"])


def build_omni_wheels(g: NodeGraph, gi, parts: SpineParts, curves):
    """Staggered rows of omni wheels along `curves`: one row every
    OMNI_ROW_PITCH, wheels every OMNI_WHEEL_PITCH across the width, every
    second row shifted half a pitch. Wheel tops sit on the conveying surface."""
    g.stage("Omni wheels", "the omni-wheel deck")
    width = gi.outputs["Width"]
    wheel = omni_wheel(g, gi)
    count = g.math('MAXIMUM', g.math('FLOOR', g.math('DIVIDE', g.math('SUBTRACT', width, 0.05), OMNI_WHEEL_PITCH)), 1.0)
    line = g.node('GeometryNodeMeshLine', mode='OFFSET')
    g.link(count, line.inputs["Count"])
    start_x = g.math('MULTIPLY', g.math('MULTIPLY', g.math('SUBTRACT', count, 1.0), OMNI_WHEEL_PITCH), -0.5)
    g.link(g.combine_xyz(x=start_x), line.inputs["Start Location"])
    line.inputs["Offset"].default_value = (OMNI_WHEEL_PITCH, 0.0, 0.0)
    to_points = g.node('GeometryNodeMeshToPoints')
    g.link(line.outputs["Mesh"], to_points.inputs["Mesh"])
    row = g.instance_on_points(to_points.outputs["Points"], wheel)
    # Row points along the runs, one wheel radius below the surface, alternate rows staggered.
    points = g.curve_to_points_evaluated(g.resample_length(curves, OMNI_ROW_PITCH))
    stagger = g.math('MULTIPLY', g.math('MODULO', g.index(), 2.0), OMNI_WHEEL_PITCH / 2.0)
    local_offset = g.combine_xyz(x=stagger, z=-OMNI_WHEEL_RADIUS)
    points = g.set_position(points, offset=g.rotate_vector(local_offset, parts.frame))
    return g.instance_on_points(points, row, rotation=parts.frame)


def omni_wheels_on_slab(g: NodeGraph, gi, parts: SpineParts, module_runs, slab, radius_m: float = OMNI_WHEEL_RADIUS,
                        width_m: float = OMNI_WHEEL_WIDTH, pitch: float = OMNI_WHEEL_PITCH, skewed: bool = False):
    """Wheel grid covering a junction deck of any outline: a large local grid
    of wheel points is instanced at each module run (rotated to its heading),
    realized, and only the points above the slab (raycast down) keep a wheel.
    With `skewed` the wheels are turned by the module's `module_skew` (an
    angled-roller element: rollers angled along the transfer direction)."""
    g.stage("Omni junction wheels", "wheels on the junction slabs")
    size = 3.2
    n = int(size / pitch) + 1
    grid = g.node('GeometryNodeMeshGrid')
    grid.inputs["Size X"].default_value = size
    grid.inputs["Size Y"].default_value = size
    grid.inputs["Vertices X"].default_value = n
    grid.inputs["Vertices Y"].default_value = n
    to_points = g.node('GeometryNodeMeshToPoints')
    g.link(grid.outputs["Mesh"], to_points.inputs["Mesh"])
    row_parity = g.math('MODULO', g.math('FLOOR', g.math('DIVIDE', g.index(), float(n))), 2.0)
    stagger = g.math('MULTIPLY', row_parity, pitch / 2.0)
    grid_pts = g.set_position(to_points.outputs["Points"], offset=g.combine_xyz(x=stagger, z=-radius_m))
    start_node = g.node('GeometryNodeCurveToPoints', mode='COUNT')
    g.link(module_runs, start_node.inputs["Curve"])
    start_node.inputs["Count"].default_value = 1
    run_length = g.named_attribute("module_length")
    centers = g.set_position(start_node.outputs["Points"], offset=g.rotate_vector(g.combine_xyz(y=g.math('MULTIPLY', run_length, 0.5)), parts.heading_only))
    placed = g.instance_on_points(centers, grid_pts, rotation=parts.heading_only)
    carry = g.node('GeometryNodeStoreNamedAttribute', data_type='FLOAT', domain='INSTANCE')
    g.link(placed, carry.inputs["Geometry"])
    carry.inputs["Name"].default_value = "wheel_heading"
    yaw = g.named_attribute("heading")
    if skewed:
        yaw = g.math('ADD', yaw, g.named_attribute("module_skew"))
    g.link(yaw, carry.inputs["Value"])
    points = g.realize(carry.outputs["Geometry"])
    ray = g.node('GeometryNodeRaycast')
    g.link(slab, ray.inputs["Target Geometry"])
    g.link(g.vmath('ADD', g.position(), g.combine_xyz(z=0.5)), ray.inputs["Source Position"])
    ray.inputs["Ray Direction"].default_value = (0.0, 0.0, -1.0)
    ray.inputs["Ray Length"].default_value = 1.0
    delete = g.node('GeometryNodeDeleteGeometry', domain='POINT')
    g.link(points, delete.inputs["Geometry"])
    g.link(g.boolean('NOT', ray.outputs["Is Hit"]), delete.inputs["Selection"])
    rotation = g.euler_to_rotation(g.combine_xyz(z=g.named_attribute("wheel_heading")))
    return g.instance_on_points(delete.outputs["Geometry"], omni_wheel(g, gi, radius_m, width_m), rotation=rotation)


def detail_sides(g: NodeGraph, gi):
    return g.switch('INT', gi.outputs["High Detail"], LOW_DETAIL_SIDES, HIGH_DETAIL_SIDES)


def spinning_cylinder(g: NodeGraph, sides, radius, length, speed, material):
    """A cylinder lying across the belt (axis = frame X) spinning at surface
    speed `speed` about that axis. Cylinder axis is Z: lay it onto X first,
    THEN spin about X (two transforms so the spin composes after the remap)."""
    spin = g.math('MULTIPLY', g.scene_seconds(), g.math('DIVIDE', speed, radius))
    cyl = g.node('GeometryNodeMeshCylinder')
    g.link(sides, cyl.inputs["Vertices"])
    g.link(radius, cyl.inputs["Radius"])
    g.link(length, cyl.inputs["Depth"])
    caps = g.boolean('OR', cyl.outputs["Top"], cyl.outputs["Bottom"])
    rounded = g.bevel_caps(cyl.outputs["Mesh"], caps, CYLINDER_CAP_BEVEL, [(None, g.math('MULTIPLY', radius, 2.0))])
    mesh = g.set_material(g.shade_smooth(rounded), material)
    mesh = g.transform(mesh, rotation=g.combine_xyz(y=math.pi / 2.0))
    return g.transform(mesh, rotation=g.combine_xyz(x=spin))


def cylinders_along(g: NodeGraph, parts: SpineParts, curves, pitch, drop, mesh):
    """Instances `mesh` at `pitch` along `curves`, one radius (`drop`) below
    the surface along the frame's own down, oriented by the frame."""
    points = g.curve_to_points_evaluated(g.resample_length(curves, pitch))
    points = g.set_position(points, offset=g.rotate_vector(g.combine_xyz(z=g.math('MULTIPLY', drop, -1.0)), parts.frame))
    return g.instance_on_points(points, mesh, rotation=parts.frame)


def end_cylinders(g: NodeGraph, parts: SpineParts, curves, drop, mesh):
    """One instance at each end of every curve (belt pulleys, sprockets)."""
    points = g.curve_to_points_evaluated(g.resample_count(curves, 2))
    points = g.set_position(points, offset=g.rotate_vector(g.combine_xyz(z=g.math('MULTIPLY', drop, -1.0)), parts.frame))
    return g.instance_on_points(points, mesh, rotation=parts.frame)


def overlap_safe_pitch(g: NodeGraph, gi, catalog_pitch, diameter, high_factor: float, low_factor: float):
    requested = g.switch('FLOAT', gi.outputs["High Detail"], g.math('MULTIPLY', catalog_pitch, low_factor), g.math('MULTIPLY', catalog_pitch, high_factor))
    return g.math('MAXIMUM', requested, g.math('ADD', diameter, MIN_CYLINDER_GAP))


def build_modules(g: NodeGraph, gi, parts: SpineParts, surface: str = "rollers"):
    """Instances the module node groups at each module run's footprint
    center (start point + half the footprint length along the incoming
    heading), yaw = heading. Module lengths are fixed per kind (catalog),
    fed through the line tree's inputs so one group node per kind serves
    every instance of that kind."""
    g.stage("Modules", "right-angle transfers and the other inserted modules")
    # RATs are transfer parts now (model/transfer_parts.rat_parts: rollers,
    # pop-up belts, frame, end stop, guards); the old prefab group (a slab
    # with rollers turned along travel) is no longer instanced. Merge
    # junctions and diverters are built in build_merge_junctions / parts.
    kinds = ()
    module_kind = g.named_attribute("module_kind", 'INT')
    pieces = []
    if surface == "omni":
        # RAT on an omni line: a deck box plus the wheel rows along its run
        # (the wheels steer the goods through the exit turn).
        from ..modules.common import DECK_DROP, DECK_THICKNESS, SIDE_PLATE

        rat_runs, _ = g.separate_geometry(parts.module_runs, g.compare('INT', 'EQUAL', module_kind, 1), 'CURVE')
        start_node = g.node('GeometryNodeCurveToPoints', mode='COUNT')
        g.link(rat_runs, start_node.inputs["Curve"])
        start_node.inputs["Count"].default_value = 1
        run_length = g.named_attribute("module_length")
        centers = g.set_position(start_node.outputs["Points"], offset=g.rotate_vector(g.combine_xyz(y=g.math('MULTIPLY', run_length, 0.5)), parts.heading_only))
        box = g.set_material(g.transform(g.rounded_box(g.math('ADD', gi.outputs["Width"], 2 * SIDE_PLATE), gi.outputs["RAT Length"], DECK_THICKNESS, 0.005),
                                         translation=g.combine_xyz(z=-(DECK_DROP + DECK_THICKNESS / 2.0))), gi.outputs["Module Material"])
        stretch = g.math('MAXIMUM', g.math('DIVIDE', run_length, gi.outputs["RAT Length"]), 0.1)
        pieces.append(g.instance_on_points(centers, box, rotation=parts.heading_only, scale=g.combine_xyz(x=1.0, y=stretch, z=1.0)))
        pieces.append(build_omni_wheels(g, gi, parts, rat_runs))
    # Each module run carries its own footprint length (spine attribute);
    # the group is built at the line-level length and, for RATs, stretched
    # along travel to the run's length (their rollers run along travel, so
    # the stretch only lengthens them -- exactly what a longer RAT is).
    run_length = g.named_attribute("module_length")
    for kind_id, tree, length in kinds:
        of_kind, _ = g.separate_geometry(parts.module_runs, g.compare('INT', 'EQUAL', module_kind, kind_id), 'CURVE')
        start_node = g.node('GeometryNodeCurveToPoints', mode='COUNT')
        g.link(of_kind, start_node.inputs["Curve"])
        start_node.inputs["Count"].default_value = 1
        forward = g.rotate_vector(g.combine_xyz(y=g.math('MULTIPLY', run_length, 0.5)), parts.heading_only)
        centers = g.set_position(start_node.outputs["Points"], offset=forward)
        group = g.node('GeometryNodeGroup')
        group.node_tree = tree
        g.link(gi.outputs["Width"], group.inputs["Width"])
        g.link(length, group.inputs["Length"])
        g.link(gi.outputs["Module Roller Diameter"], group.inputs["Roller Diameter"])
        g.link(detail_sides(g, gi), group.inputs["Sides"])
        g.link(gi.outputs["Speed"], group.inputs["Speed"])
        g.link(gi.outputs["Module Material"], group.inputs["Deck Material"])
        g.link(gi.outputs["Roller Material"], group.inputs["Roller Material"])
        if "Exit Skew" in group.inputs:
            g.link(gi.outputs["Merge Skew"], group.inputs["Exit Skew"])
        stretch = g.math('MAXIMUM', g.math('DIVIDE', run_length, length), 0.1) if kind_id == 1 else 1.0
        pieces.append(g.instance_on_points(centers, group.outputs["Geometry"], rotation=parts.heading_only,
                                           scale=g.combine_xyz(x=1.0, y=stretch, z=1.0)))
    pieces.append(build_merge_junctions(g, gi, parts, surface))
    pieces.append(build_buffer_stops(g, gi, parts))
    pieces.append(build_arb_modules(g, gi, parts))
    return g.join(*pieces)


def module_centers(g: NodeGraph, parts: SpineParts, runs, fraction: float = 0.5):
    """One point per module run at `fraction` of its footprint length along
    the heading (curve attributes such as module_length / module_skew ride
    along as point attributes)."""
    start_node = g.node('GeometryNodeCurveToPoints', mode='COUNT')
    g.link(runs, start_node.inputs["Curve"])
    start_node.inputs["Count"].default_value = 1
    run_length = g.named_attribute("module_length")
    forward = g.rotate_vector(g.combine_xyz(y=g.math('MULTIPLY', run_length, fraction)), parts.heading_only)
    return g.set_position(start_node.outputs["Points"], offset=forward)


def build_arb_modules(g: NodeGraph, gi, parts: SpineParts):
    """Inline angled-roller elements (module_kind 6): a belt deck with rows of small
    angled rollers -- herringbone for a centre / align element, uniformly
    skewed for a turn -- and the fixed-pivot turn (kind 7): the line's own
    surface plus a pin at the line edge the load turns around."""
    from ..modules.common import DECK_DROP, DECK_THICKNESS, SIDE_PLATE

    g.stage("Angled-roller decks", "angled-roller belts: the belt plate with its small angled rollers")
    module_kind = g.named_attribute("module_kind", 'INT')
    width = gi.outputs["Width"]
    arb_runs, _ = g.separate_geometry(parts.module_runs, g.compare('INT', 'EQUAL', module_kind, MODULE_KIND_ARB), 'CURVE')
    centers = module_centers(g, parts, arb_runs)
    run_length = g.named_attribute("module_length")
    stretch = g.combine_xyz(x=1.0, y=run_length, z=1.0)
    deck = g.set_material(g.transform(g.rounded_box(g.math('ADD', width, 2 * SIDE_PLATE), 1.0, DECK_THICKNESS, 0.005),
                                      translation=g.combine_xyz(z=-(DECK_DROP + DECK_THICKNESS / 2.0))), gi.outputs["Module Material"])
    belt = g.set_material(g.transform(g.rounded_box(width, 1.0, 0.012, 0.002), translation=g.combine_xyz(z=-0.008)), gi.outputs["Belt Material"])
    pieces = [g.instance_on_points(centers, deck, rotation=parts.heading_only, scale=stretch),
              g.instance_on_points(centers, belt, rotation=parts.heading_only, scale=stretch)]
    # Roller rows along the element, one wheel radius below the surface.
    g.column()
    count = g.math('MAXIMUM', g.math('FLOOR', g.math('DIVIDE', g.math('SUBTRACT', width, 0.05), ARB_WHEEL_PITCH)), 1.0)
    rows_points = g.curve_to_points_evaluated(g.resample_length(arb_runs, ARB_WHEEL_PITCH))
    rows_points = g.set_position(rows_points, offset=g.rotate_vector(g.combine_xyz(z=-ARB_WHEEL_RADIUS), parts.frame))
    center_flag = g.compare('INT', 'EQUAL', g.named_attribute("module_center", 'INT'), 1)
    skew_pos = g.compare('FLOAT', 'GREATER_THAN', g.named_attribute("module_skew"), 0.0)
    herring = wheel_row(g, gi, count, ARB_WHEEL_PITCH, ARB_WHEEL_RADIUS, ARB_WHEEL_RADIUS, herringbone_rad=0.52)
    left = wheel_row(g, gi, count, ARB_WHEEL_PITCH, ARB_WHEEL_RADIUS, ARB_WHEEL_RADIUS, yaw=0.52)
    right = wheel_row(g, gi, count, ARB_WHEEL_PITCH, ARB_WHEEL_RADIUS, ARB_WHEEL_RADIUS, yaw=-0.52)
    pieces.append(g.instance_on_points(rows_points, herring, rotation=parts.frame, selection=center_flag))
    pieces.append(g.instance_on_points(rows_points, left, rotation=parts.frame, selection=g.boolean('AND', g.boolean('NOT', center_flag), skew_pos)))
    pieces.append(g.instance_on_points(rows_points, right, rotation=parts.frame, selection=g.boolean('AND', g.boolean('NOT', center_flag), g.boolean('NOT', skew_pos))))
    # Fixed-pivot turns: a pin at the line edge, a third of the way in.
    g.column()
    pivot_runs, _ = g.separate_geometry(parts.module_runs, g.compare('INT', 'EQUAL', module_kind, MODULE_KIND_PIVOT), 'CURVE')
    pins = module_centers(g, parts, pivot_runs, 0.35)
    side = g.math('MULTIPLY', g.named_attribute("module_side", 'INT'), 1.0)
    lateral = g.math('MULTIPLY', side, g.math('SUBTRACT', g.math('DIVIDE', width, 2.0), 0.03))
    pins = g.set_position(pins, offset=g.rotate_vector(g.combine_xyz(x=lateral, z=0.06), parts.heading_only))
    pin = g.set_material(g.shade_smooth(g.cylinder(16, 0.02, 0.12)), gi.outputs["Frame Material"])
    pieces.append(g.instance_on_points(pins, pin, rotation=parts.heading_only))
    return g.join(*pieces)


def build_buffer_stops(g: NodeGraph, gi, parts: SpineParts):
    """What makes a buffer module (kind 4) a zero-pressure accumulation
    zone: a blade stop across the deck at its end, and a PHOTO-EYE at the
    FRONT of every zone -- a small black sensor housing on a bracket on the
    right frame rail, looking across the bed just above the rollers, with a
    reflector plate on the left rail -- so a tote stops when its leading
    edge blocks the beam (real ZPA, user request 2026-10-05). The zones are
    one queue pitch long (item length + Queue Gap); the queued goods stand
    with their fronts at the sensors, one gap apart. The conveying surface
    itself is swept by the line."""
    from ..materials import sensor as sensor_material

    g.stage("Buffer stops", "a blade stop at each buffer's end and a photo-eye at the front of every zone")
    module_kind = g.named_attribute("module_kind", 'INT')
    buffers, _ = g.separate_geometry(parts.module_runs, g.compare('INT', 'EQUAL', module_kind, MODULE_KIND_BUFFER), 'CURVE')
    ends = g.node('GeometryNodeCurveToPoints', mode='COUNT')
    g.link(buffers, ends.inputs["Curve"])
    ends.inputs["Count"].default_value = 1
    run_length = g.named_attribute("module_length")
    forward = g.rotate_vector(g.combine_xyz(y=g.math('SUBTRACT', run_length, 0.03)), parts.heading_only)
    end_points = g.set_position(ends.outputs["Points"], offset=forward)
    width = gi.outputs["Width"]
    half_w = g.math('DIVIDE', width, 2.0)
    blade = g.set_material(g.transform(g.rounded_box(g.math('SUBTRACT', width, 0.04), 0.02, 0.08, 0.003), translation=g.combine_xyz(z=0.04)),
                           gi.outputs["Module Material"])
    # Zone sensors: the FRONT of every queued item, i.e. one gap before the
    # end stop and then every pitch upstream (the queue is packed against
    # the stop with the gap AFTER each item: model/buffer_fifo, the queue).
    g.column()
    rev = g.node('GeometryNodeReverseCurve')
    g.link(buffers, rev.inputs["Curve"])
    pitch_q = gi.outputs["Queue Pitch"]
    gap = g.math('MAXIMUM', g.math('SUBTRACT', pitch_q, gi.outputs["Item Length"]), 0.0)
    zones = g.math('MAXIMUM', g.math('FLOOR', g.math('DIVIDE', g.named_attribute("module_length"), pitch_q)), 1.0)
    trim = g.node('GeometryNodeTrimCurve', mode='LENGTH')
    g.link(rev.outputs["Curve"], trim.inputs["Curve"])
    start_len = next((sock for sock in trim.inputs if sock.identifier == "Start_001"), trim.inputs[4])  # Start (length)
    end_len = next((sock for sock in trim.inputs if sock.identifier == "End_001"), trim.inputs[5])  # End (length)
    g.link(gap, start_len)
    g.link(g.math('ADD', gap, g.math('ADD', g.math('MULTIPLY', g.math('SUBTRACT', zones, 1.0), pitch_q), 0.001)), end_len)
    zone_points = g.curve_to_points_evaluated(g.resample_count(trim.outputs["Curve"], zones))
    # Photo-eye: 20 x 30 x 45 mm black housing on a bracket from the right
    # frame rail, lens 60 mm above the rollers; a 40 x 40 reflector opposite.
    sensor_z = 0.06
    black = sensor_material()
    housing = g.set_material(g.transform(g.rounded_box(0.020, 0.030, 0.045, 0.002),
                                         translation=g.combine_xyz(x=g.math('ADD', half_w, 0.012), z=sensor_z)), black)
    bracket_h = sensor_z + 0.03  # from the rail top (15 mm under the surface) up behind the housing
    bracket = g.set_material(g.transform(g.rounded_box(0.004, 0.025, bracket_h, 0.001),
                                         translation=g.combine_xyz(x=g.math('ADD', half_w, 0.024), z=bracket_h / 2.0 - 0.015)),
                             gi.outputs["Frame Material"])
    reflector = g.set_material(g.transform(g.rounded_box(0.003, 0.040, 0.040, 0.001),
                                           translation=g.combine_xyz(x=g.math('MULTIPLY', g.math('ADD', half_w, 0.012), -1.0), z=sensor_z)),
                               gi.outputs["Belt Material"])
    photo_eye = g.join(housing, bracket, reflector)
    sensors = g.instance_on_points(zone_points, photo_eye, rotation=parts.heading_only)
    return g.join(g.instance_on_points(end_points, blade, rotation=parts.heading_only), sensors)


def _slab_from_outlines(g: NodeGraph, outlines, drop: float, thickness: float):
    """(slab mesh, fill mesh) of closed outlines extruded `thickness` up from `drop` below the surface."""
    fill = g.node('GeometryNodeFillCurve')
    g.link(outlines, fill.inputs["Curve"])
    bottom = g.transform(fill.outputs["Mesh"], translation=g.combine_xyz(z=-drop))
    ext = g.node('GeometryNodeExtrudeMesh', mode='FACES')
    g.link(bottom, ext.inputs["Mesh"])
    ext.inputs["Offset Scale"].default_value = thickness
    ext.inputs["Individual"].default_value = True
    flip = g.node('GeometryNodeFlipFaces')
    g.link(bottom, flip.inputs["Mesh"])
    return ext.outputs["Mesh"], ext.outputs["Top"], flip.outputs["Mesh"], fill.outputs["Mesh"]


def build_merge_junctions(g: NodeGraph, gi, parts: SpineParts, surface: str = "rollers"):
    """Merge junction and diverter sections (module_kind 2 / 3) on THIS
    line. Their rollers, the feeder end's rollers and dead plate, pop-up
    belts / wheels / chains, HPD cassettes, the frames and the drive units
    are transfer parts (model/transfer_parts.py, swept by build_parts).
    What is left here:

    - belt / chain lines: the belt or plate-chain top over the junction's
      closed outline (role 3);
    - angled-roller elements: the belt plate (its small angled rollers are parts);
    - omni lines: a wheel deck on a slab.
    (The solid yellow slab every junction used to sit on is gone: real
    transfers are open frames.)"""
    from ..modules.common import DECK_DROP, DECK_THICKNESS, SIDE_PLATE

    g.stage("Junction decks", "merge and diverter decks on the spine's closed outlines")
    width = gi.outputs["Width"]
    module_kind = g.named_attribute("module_kind", 'INT')
    module_tech = g.named_attribute("module_tech", 'INT')
    junction_runs, _ = g.separate_geometry(parts.module_runs, is_junction_kind(g, module_kind), 'CURVE')

    if surface == "pouch":  # a pouch sorter's switch is the rail itself (cross_sections/pouch.py)
        return g.join()
    if surface == "omni":
        slab, top_faces, bottom_flipped, _fill = _slab_from_outlines(g, parts.outlines, DECK_DROP + DECK_THICKNESS, DECK_THICKNESS)
        rounded = g.bevel_caps(slab, top_faces, 0.005, [(None, g.math('ADD', width, 2.0 * SIDE_PLATE))])
        deck = g.set_material(g.join(rounded, bottom_flipped), gi.outputs["Module Material"])
        return g.join(deck, omni_wheels_on_slab(g, gi, parts, junction_runs, slab))

    pieces = []
    is_arb = g.compare('INT', 'EQUAL', module_tech, TECH_ARB)

    def thin_plate(outlines, thickness: float, material):
        plate, _top, flipped, _f = _slab_from_outlines(g, outlines, thickness, thickness)
        return g.set_material(g.join(plate, flipped), material)

    # ---- Belt / chain lines: their own top over the junction (never under an angled-roller belt).
    if surface != "rollers":
        g.column()
        plain_outlines, _ = g.separate_geometry(parts.outlines, g.boolean('NOT', is_arb), 'CURVE')
        thickness = 0.012 if surface == "chain" else 0.01
        material = gi.outputs["Link Material"] if surface == "chain" else gi.outputs["Belt Material"]
        pieces.append(thin_plate(plain_outlines, thickness, material))

    # ---- Angled-roller junctions: the belt plate over their outline (its angled
    # rollers are transfer parts).
    g.column()
    arb_outlines, _ = g.separate_geometry(parts.outlines, is_arb, 'CURVE')
    pieces.append(thin_plate(arb_outlines, 0.012, gi.outputs["Belt Material"]))

    return g.join(*pieces)


def build_parts(g: NodeGraph, gi, parts: SpineParts, lifts=None):
    """Transfer-section parts laid out in Python (model/transfer_parts.py)
    and written as spline extras: rollers and wheels are swept circles
    scaled by `part_r`, belts and chain strands flat profiles, frame rails
    the frame profile, boxes instanced unit cubes (width `part_r`, height
    `part_h`). Wheels and boxes take the material slot `part_mat` names.

    Pop-up transfers: parts with `part_lift` > 0 belong to transfer
    `part_tr` and rise by part_lift x that transfer's current lift (0..1,
    `lifts` from the populate group, matched through the line's
    `Transfer k Id` inputs) -- belts, blades and pulleys go up while goods
    are carried across and down again after."""
    if parts.part_curves is None:
        return None
    g.stage("Transfer parts", "rollers, pop-up belts, chains, wheels, boxes and plates of the transfers (model/transfer_parts.py), lifted by the goods' stream")
    curves = parts.part_curves
    if lifts:
        tr = g.named_attribute("part_tr", 'INT')
        up = 0.0
        for k, lift in enumerate(lifts, start=1):
            mine = g.boolean('AND', g.compare('INT', 'EQUAL', tr, gi.outputs[f"Transfer {k} Id"]), g.compare('INT', 'GREATER_THAN', tr, 0))
            up = g.math('ADD', up, g.switch('FLOAT', mine, 0.0, lift))
        rise = g.math('MULTIPLY', g.math('MINIMUM', up, 1.0), g.named_attribute("part_lift"))
        curves = g.set_position(curves, offset=g.combine_xyz(z=rise))
    role = g.named_attribute("role", 'INT')

    def of_role(rid):
        sel, _ = g.separate_geometry(curves, g.compare('INT', 'EQUAL', role, rid), 'CURVE')
        return sel

    def level(curves):
        """Profile X across, Y up: the normal is the horizontal left of each part."""
        node = g.node('GeometryNodeSetCurveNormal')
        g.link(curves, node.inputs["Curve"])
        node.inputs["Mode"].default_value = "Free"
        tangent = g.node('GeometryNodeInputTangent').outputs["Tangent"]
        g.link(g.vmath('NORMALIZE', g.vmath('CROSS_PRODUCT', g.combine_xyz(z=1.0), tangent)), node.inputs["Normal"])
        return node.outputs["Curve"]

    def sweep(curves, profile, scale=None, caps=True):
        node = g.node('GeometryNodeCurveToMesh')
        g.link(curves, node.inputs["Curve"])
        g.link(profile, node.inputs["Profile Curve"])
        if scale is not None:
            g.link(scale, node.inputs["Scale"])
        node.inputs["Fill Caps"].default_value = caps
        return node.outputs["Mesh"]

    def circle(resolution):
        node = g.node('GeometryNodeCurvePrimitiveCircle', mode='RADIUS')
        if isinstance(resolution, int):
            node.inputs["Resolution"].default_value = resolution
        else:
            g.link(resolution, node.inputs["Resolution"])
        node.inputs["Radius"].default_value = 1.0
        return node.outputs["Curve"]

    radius = g.named_attribute("part_r")
    pieces = []
    rollers = sweep(of_role(ROLE_PART_ROLLER), circle(detail_sides(g, gi)), radius)
    pieces.append(g.set_material(g.shade_smooth(rollers), gi.outputs["Roller Material"]))
    part_mat = g.named_attribute("part_mat", 'INT')

    def mat_is(value):
        return g.compare('INT', 'EQUAL', part_mat, value)

    wheel_curves = of_role(ROLE_PART_WHEEL)
    for material, sel in ((gi.outputs["Belt Material"], mat_is(PART_MAT_BELT)),
                          (gi.outputs["Module Material"], mat_is(PART_MAT_ACCENT)),
                          (gi.outputs["Link Material"], g.boolean('NOT', g.boolean('OR', mat_is(PART_MAT_BELT), mat_is(PART_MAT_ACCENT))))):
        picked, _ = g.separate_geometry(wheel_curves, sel, 'CURVE')
        pieces.append(g.set_material(g.shade_smooth(sweep(picked, circle(16), radius)), material))
    belts = sweep(level(of_role(ROLE_PART_BELT)), g.filleted_rectangle(PART_BELT_W, PART_BELT_T, 0.002))
    pieces.append(g.set_material(belts, gi.outputs["Belt Material"]))
    chains = sweep(level(of_role(ROLE_PART_CHAIN)), g.filleted_rectangle(PART_CHAIN_W, PART_CHAIN_T, 0.003))
    pieces.append(g.set_material(chains, gi.outputs["Link Material"]))
    rails = sweep(level(of_role(ROLE_PART_RAIL)), g.filleted_rectangle(gi.outputs["Rail Thickness"], gi.outputs["Rail Height"], RAIL_BEVEL))
    pieces.append(g.set_material(rails, gi.outputs["Frame Material"]))

    # Plates: level polygons. Fill Curve works in the XY plane (its mesh lies
    # at z = 0) and keeps the outline points as its vertices, so each vertex
    # is lifted back to the height of the outline point it lies on; faces are
    # turned up (a mirrored junction reverses the winding) and extruded up.
    g.column()
    plates = of_role(ROLE_PART_PLATE)
    px, py, _pz = g.separate_xyz(g.position())
    flat = g.set_position(plates, position=g.combine_xyz(x=px, y=py))
    fill = g.node('GeometryNodeFillCurve')
    g.link(flat, fill.inputs["Curve"])
    nearest = g.node('GeometryNodeSampleNearest', domain='POINT')
    g.link(g.curve_to_points_evaluated(flat), nearest.inputs["Geometry"])
    g.link(g.position(), nearest.inputs["Sample Position"])
    height = g.node('GeometryNodeSampleIndex', data_type='FLOAT', domain='POINT')
    g.link(g.curve_to_points_evaluated(plates), height.inputs["Geometry"])
    g.link(g.separate_xyz(g.position())[2], height.inputs["Value"])
    g.link(nearest.outputs["Index"], height.inputs["Index"])
    lifted = g.set_position(fill.outputs["Mesh"], offset=g.combine_xyz(z=height.outputs["Value"]))
    turn_up = g.node('GeometryNodeFlipFaces')
    g.link(lifted, turn_up.inputs["Mesh"])
    g.link(g.compare('FLOAT', 'LESS_THAN', g.separate_xyz(g.normal())[2], 0.0), turn_up.inputs["Selection"])
    extrude = g.node('GeometryNodeExtrudeMesh', mode='FACES')
    g.link(turn_up.outputs["Mesh"], extrude.inputs["Mesh"])
    extrude.inputs["Offset Scale"].default_value = PART_PLATE_T
    extrude.inputs["Individual"].default_value = False
    underside = g.node('GeometryNodeFlipFaces')
    g.link(turn_up.outputs["Mesh"], underside.inputs["Mesh"])
    pieces.append(g.set_material(g.join(extrude.outputs["Mesh"], underside.outputs["Mesh"]), gi.outputs["Frame Material"]))

    # Boxes: a unit cube per 2-point spline at its middle, turned along it.
    g.column()
    boxes = of_role(ROLE_PART_BOX)
    store_len = g.node('GeometryNodeStoreNamedAttribute', data_type='FLOAT', domain='POINT')
    g.link(boxes, store_len.inputs["Geometry"])
    store_len.inputs["Name"].default_value = "part_len"
    g.link(g.node('GeometryNodeSplineLength').outputs["Length"], store_len.inputs["Value"])
    mids = g.node('GeometryNodeCurveToPoints', mode='COUNT')
    g.link(g.resample_count(store_len.outputs["Geometry"], 3), mids.inputs["Curve"])
    mids.inputs["Count"].default_value = 3
    middle = g.compare('INT', 'EQUAL', g.math('MODULO', g.index(), 3.0), 1)
    align = g.node('FunctionNodeAlignRotationToVector')
    align.axis = 'X'
    align.pivot_axis = 'Z'
    g.link(mids.outputs["Tangent"], align.inputs["Vector"])
    size = g.combine_xyz(x=g.named_attribute("part_len"), y=g.named_attribute("part_r"), z=g.named_attribute("part_h"))
    cube = g.node('GeometryNodeMeshCube')
    cube.inputs["Size"].default_value = (1.0, 1.0, 1.0)
    others = g.boolean('NOT', g.boolean('OR', g.boolean('OR', mat_is(PART_MAT_ACCENT), mat_is(PART_MAT_BELT)), mat_is(PART_MAT_LINKS)))
    for material, sel in ((gi.outputs["Module Material"], mat_is(PART_MAT_ACCENT)), (gi.outputs["Belt Material"], mat_is(PART_MAT_BELT)),
                          (gi.outputs["Link Material"], mat_is(PART_MAT_LINKS)), (gi.outputs["Frame Material"], others)):
        inst = g.instance_on_points(mids.outputs["Points"], g.set_material(cube.outputs["Mesh"], material),
                                    rotation=align.outputs["Rotation"], scale=size, selection=g.boolean('AND', middle, sel))
        pieces.append(inst)
    return g.join(*pieces)


def build_highlight(g: NodeGraph, gi, parts: SpineParts, single_rail: bool = False):
    """Orange sleeves over both frame rails of the segment whose index
    equals `Highlight Segment` (-1 = none), so clicking a row in the segment
    list shows which piece of the line it is -- opaque and on the rails, so
    it reads in Solid shading and never hides rollers or goods. A segment's
    polyline starts at the previous segment's end sample, so a point is
    kept when it OR the next point carries the active index."""
    g.stage("Highlight", "orange sleeves on the selected piece (viewport only)")
    active = gi.outputs["Highlight Segment"]
    seg_idx = g.named_attribute("segment_index", 'INT')
    next_index = g.math('ADD', g.index(), 1.0)
    at_next = g.node('GeometryNodeFieldAtIndex', data_type='INT', domain='POINT')
    g.link(next_index, at_next.inputs["Index"])
    g.link(seg_idx, at_next.inputs["Value"])
    size_node = g.node('GeometryNodeAttributeDomainSize', component='CURVE')
    g.link(parts.full, size_node.inputs["Geometry"])
    has_next = g.compare('INT', 'LESS_THAN', next_index, size_node.outputs["Point Count"])
    own = g.compare('INT', 'EQUAL', seg_idx, active)
    next_is_active = g.boolean('AND', g.compare('INT', 'EQUAL', at_next.outputs["Value"], active), has_next)
    part, _ = g.separate_geometry(parts.full, g.boolean('OR', own, next_is_active), 'POINT')
    normal_node = g.node('GeometryNodeSetCurveNormal')
    g.link(part, normal_node.inputs["Curve"])
    normal_node.inputs["Mode"].default_value = "Free"
    g.link(parts.left, normal_node.inputs["Normal"])
    grow = 0.012
    offset = rail_offset(g, gi)
    rail_height = gi.outputs["Rail Height"]
    center_y = g.math('MULTIPLY', g.math('ADD', gi.outputs["Rail Top Drop"], g.math('DIVIDE', rail_height, 2.0)), -1.0)
    profile = g.filleted_rectangle(g.math('ADD', gi.outputs["Rail Thickness"], grow), g.math('ADD', rail_height, grow), RAIL_BEVEL)
    if single_rail:  # one overhead rail on the centreline (the pouch sorter)
        pair = g.transform(profile, translation=g.combine_xyz(y=center_y))
    else:
        pair = g.join(
            g.transform(profile, translation=g.combine_xyz(x=offset, y=center_y)),
            g.transform(profile, translation=g.combine_xyz(x=g.math('MULTIPLY', offset, -1.0), y=center_y)),
        )
    sleeves = g.set_material(g.curve_to_mesh(normal_node.outputs["Curve"], pair), materials.highlight())
    # Viewport aid only: Is Viewport is False in final renders (F12 and
    # animation renders), so the orange never reaches an image.
    is_viewport = g.node('GeometryNodeIsViewport').outputs["Is Viewport"]
    enabled = g.boolean('AND', g.compare('INT', 'GREATER_EQUAL', active, 0), is_viewport)
    return g.switch('GEOMETRY', enabled, None, sleeves)


def finish(g: NodeGraph, gi, parts: SpineParts, *geometries, surface: str = "rollers"):
    """Modules, populate branch, active-segment highlight, debug spine, output."""
    from ..populate import populate_branch

    modules = build_modules(g, gi, parts, surface)
    g.stage("Goods", "the item stream (Conveyor - Populate): moving goods, stepping through the buffers' queues")
    # The item stream always runs forward along the FLOW (Stream Flip mirrors
    # a reversed line), so its speed is the magnitude; rollers keep the sign.
    stream_speed = g.switch('FLOAT', gi.outputs["Use Stream Speed"], g.math('ABSOLUTE', gi.outputs["Speed"]), gi.outputs["Stream Speed"])
    items, lifts = populate_branch(g, gi, parts.full, stream_speed)
    highlight = build_highlight(g, gi, parts, single_rail=(surface == "pouch"))
    geometries = (*geometries, modules, build_parts(g, gi, parts, lifts), build_columns(g, gi, parts), build_arms(g, gi, parts),
                  build_lift_forks(g, gi, parts, stream_speed))
    g.stage("Output", "everything joined, plus the spine for debugging")
    spine_display = g.switch('GEOMETRY', gi.outputs["Show Spine"], None, parts.full)
    go = g.node('NodeGroupOutput')
    g.link(g.join(*geometries, items, highlight, spine_display), go.inputs["Geometry"])
