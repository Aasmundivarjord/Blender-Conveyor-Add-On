"""Module node groups share one recipe: a deck (frame) the size of the
footprint with its top just under the conveying surface, and a bed of
rollers whose axes are yawed by `roller_yaw` (0 = across the belt like a
normal section; 90 deg = along travel, i.e. a right-angle transfer pushing
product sideways; 30 deg = skewed diverter rollers). Built at the origin,
travel = +Y, footprint centered, conveying surface at z = 0; the line tree
instances the group at each module run's center with the frame's heading.
"""
from __future__ import annotations

import math

import bpy

from .. import materials
from ..builder_common import NodeGraph, get_or_create_tree, mark_tree_built

DECK_THICKNESS = 0.08
DECK_DROP = 0.012  # deck top sits this far below the roller tops
SIDE_PLATE = 0.02


MIN_SKEW_SIN = math.sin(math.radians(12.0))


def build_module_tree(name: str, version: int, roller_yaw_deg: float, deck_material_fn, roller_pitch: float,
                      rebuild: bool = False, skewable: bool = False) -> bpy.types.NodeTree:
    tree, needs_build = get_or_create_tree(name, version, rebuild=rebuild)
    if not needs_build:
        return tree
    g = NodeGraph(tree)
    g.input("Width", 'NodeSocketFloat', default=0.5, min_value=0.05, subtype='DISTANCE')
    g.input("Length", 'NodeSocketFloat', default=0.9, min_value=0.1, subtype='DISTANCE')
    g.input("Roller Diameter", 'NodeSocketFloat', default=0.05, min_value=0.005, subtype='DISTANCE')
    g.input("Sides", 'NodeSocketInt', default=32, min_value=3)
    g.input("Speed", 'NodeSocketFloat', default=0.0)
    g.input("Deck Material", 'NodeSocketMaterial')
    g.input("Roller Material", 'NodeSocketMaterial')
    if skewable:
        g.input("Exit Skew", 'NodeSocketFloat', default=0.0, subtype='ANGLE')
    g.output("Geometry", 'NodeSocketGeometry')

    gi = g.node('NodeGroupInput')
    width = gi.outputs["Width"]
    length = gi.outputs["Length"]
    diameter = gi.outputs["Roller Diameter"]
    sides = gi.outputs["Sides"]
    speed = gi.outputs["Speed"]
    radius = g.math('DIVIDE', diameter, 2.0)

    if skewable:
        return _finish_skewed_merge(g, gi, tree, version, width, length, radius, sides, speed, deck_material_fn, roller_pitch)

    # Deck: full footprint, top at -DECK_DROP.
    g.column()
    deck = g.transform(g.rounded_box(g.math('ADD', width, 2 * SIDE_PLATE), length, DECK_THICKNESS, 0.005),
                       translation=g.combine_xyz(z=-(DECK_DROP + DECK_THICKNESS / 2.0)))
    deck = g.set_material(deck, gi.outputs["Deck Material"])

    # Roller bed. Roller axis a = (cos yaw, sin yaw); rows step along
    # n = (-sin yaw, cos yaw). A roller must fit inside the footprint along
    # its axis: length = min(width/|cos yaw|, length/|sin yaw|) - margin.
    # Rows span the footprint side that n mostly follows, shortened by the
    # rollers' own projection so skewed end rollers stay inside the corners.
    g.column()
    yaw = math.radians(roller_yaw_deg)
    ax, ay = math.cos(yaw), math.sin(yaw)
    nx, ny = -math.sin(yaw), math.cos(yaw)
    margin = 0.03
    candidates = []
    if abs(ax) > 1e-6:
        candidates.append(g.math('DIVIDE', width, abs(ax)))
    if abs(ay) > 1e-6:
        candidates.append(g.math('DIVIDE', length, abs(ay)))
    fit = candidates[0] if len(candidates) == 1 else g.math('MINIMUM', candidates[0], candidates[1])
    roller_len = g.math('SUBTRACT', fit, margin)
    rows_along_travel = abs(ny) >= abs(nx)
    side = length if rows_along_travel else width
    projection = abs(ay) if rows_along_travel else abs(ax)  # roller half-extent along n direction's axis
    row_span = g.math('SUBTRACT', g.math('SUBTRACT', side, g.math('MULTIPLY', roller_len, projection)), margin)
    row_span = g.math('MAXIMUM', row_span, 0.05)
    count = g.math('MAXIMUM', g.math('FLOOR', g.math('DIVIDE', row_span, roller_pitch)), 1.0)
    half = g.math('MULTIPLY', row_span, 0.5)
    start = g.combine_xyz(x=g.math('MULTIPLY', half, -nx), y=g.math('MULTIPLY', half, -ny), z=g.math('MULTIPLY', radius, -1.0))
    end = g.combine_xyz(x=g.math('MULTIPLY', half, nx), y=g.math('MULTIPLY', half, ny), z=g.math('MULTIPLY', radius, -1.0))
    line = g.node('GeometryNodeCurvePrimitiveLine', mode='POINTS')
    g.link(start, line.inputs["Start"])
    g.link(end, line.inputs["End"])
    pts = g.curve_to_points_evaluated(g.resample_count(line.outputs["Curve"], g.math('ADD', count, 1.0)))

    spin = g.math('MULTIPLY', g.scene_seconds(), g.math('DIVIDE', speed, radius))
    cyl = g.node('GeometryNodeMeshCylinder')
    g.link(sides, cyl.inputs["Vertices"])
    g.link(radius, cyl.inputs["Radius"])
    g.link(roller_len, cyl.inputs["Depth"])
    rounded = g.bevel_caps(cyl.outputs["Mesh"], g.boolean('OR', cyl.outputs["Top"], cyl.outputs["Bottom"]), 0.002,
                           [(None, g.math('MULTIPLY', radius, 2.0))])
    roller = g.set_material(g.shade_smooth(rounded), gi.outputs["Roller Material"])
    roller = g.transform(roller, rotation=g.combine_xyz(y=math.pi / 2.0))  # axis Z -> X
    roller = g.transform(roller, rotation=g.combine_xyz(x=spin))
    roller = g.transform(roller, rotation=g.combine_xyz(z=yaw))  # yaw the axis
    rollers = g.instance_on_points(pts, roller)

    g.column()
    go = g.node('NodeGroupOutput')
    g.link(g.join(deck, rollers), go.inputs["Geometry"])
    mark_tree_built(tree, version)
    return tree


def _finish_skewed_merge(g, gi, tree, version, width, length, radius, sides, speed, deck_material_fn, roller_pitch):
    """Merge junction deck whose downstream edge runs PARALLEL to the target
    line it joins (`Exit Skew` = feeder heading minus target heading), so
    the deck meets the target's edge instead of poking into its roller bed.
    The rollers lie along that edge, all the same length, which also reads
    as the skewed rollers real merge sections use to push goods over.
    Local axes: travel +Y, X = right of travel, conveying surface z = 0."""
    skew = gi.outputs["Exit Skew"]
    sin_s = g.math('SINE', skew)
    cos_s = g.math('COSINE', skew)
    # |sin| floor keeps cot finite for near-parallel approaches (no blend happens there anyway).
    safe_sin = g.math('MAXIMUM', g.math('ABSOLUTE', sin_s), MIN_SKEW_SIN)
    cot = g.math('DIVIDE', cos_s, g.math('MULTIPLY', safe_sin, g.math('SIGN', g.math('ADD', sin_s, 1e-9))))
    deck_w = g.math('ADD', width, 2 * SIDE_PLATE)
    half_w = g.math('DIVIDE', deck_w, 2.0)
    half_l = g.math('DIVIDE', length, 2.0)
    # End edge through (0, L/2) with direction (sin skew, cos skew): corner at x=+half_w sits at y = L/2 + half_w*cot.
    shift = g.math('MULTIPLY', half_w, cot)
    quad = g.node('GeometryNodeCurvePrimitiveQuadrilateral', mode='POINTS')
    neg_half_w = g.math('MULTIPLY', half_w, -1.0)
    neg_half_l = g.math('MULTIPLY', half_l, -1.0)
    g.link(g.combine_xyz(x=neg_half_w, y=neg_half_l), quad.inputs["Point 1"])
    g.link(g.combine_xyz(x=half_w, y=neg_half_l), quad.inputs["Point 2"])
    g.link(g.combine_xyz(x=half_w, y=g.math('ADD', half_l, shift)), quad.inputs["Point 3"])
    g.link(g.combine_xyz(x=neg_half_w, y=g.math('SUBTRACT', half_l, shift)), quad.inputs["Point 4"])
    outline = g.node('GeometryNodeFilletCurve')
    g.link(quad.outputs["Curve"], outline.inputs["Curve"])
    outline.inputs["Mode"].default_value = "Poly"
    outline.inputs["Count"].default_value = 3
    outline.inputs["Radius"].default_value = 0.02
    outline.inputs["Limit Radius"].default_value = True
    fill = g.node('GeometryNodeFillCurve')
    g.link(outline.outputs["Curve"], fill.inputs["Curve"])
    bottom = g.transform(fill.outputs["Mesh"], translation=g.combine_xyz(z=-(DECK_DROP + DECK_THICKNESS)))
    ext = g.node('GeometryNodeExtrudeMesh', mode='FACES')
    g.link(bottom, ext.inputs["Mesh"])
    ext.inputs["Offset Scale"].default_value = DECK_THICKNESS
    ext.inputs["Individual"].default_value = True
    slab = g.bevel_caps(ext.outputs["Mesh"], ext.outputs["Top"], 0.005, [(None, deck_w)])
    # Extrude leaves the original face as the open bottom: close it with a flipped copy.
    flip = g.node('GeometryNodeFlipFaces')
    g.link(bottom, flip.inputs["Mesh"])
    deck = g.set_material(g.join(slab, flip.outputs["Mesh"]), gi.outputs["Deck Material"])

    # Rollers along the skewed edge: axis direction (sin skew, cos skew) = yaw (90deg - skew) from +X.
    g.column()
    margin = 0.03
    inner_w = g.math('SUBTRACT', width, 2.0 * margin)
    roller_len = g.math('DIVIDE', inner_w, safe_sin)
    half_span_y = g.math('MULTIPLY', g.math('DIVIDE', inner_w, 2.0), g.math('ABSOLUTE', cot))
    c_min = g.math('ADD', g.math('ADD', neg_half_l, half_span_y), margin)
    c_max = g.math('SUBTRACT', half_l, margin)
    row_span = g.math('MAXIMUM', g.math('SUBTRACT', c_max, c_min), 0.0)
    count = g.math('MAXIMUM', g.math('FLOOR', g.math('DIVIDE', row_span, roller_pitch)), 1.0)
    line = g.node('GeometryNodeCurvePrimitiveLine', mode='POINTS')
    g.link(g.combine_xyz(y=c_min, z=g.math('MULTIPLY', radius, -1.0)), line.inputs["Start"])
    g.link(g.combine_xyz(y=c_max, z=g.math('MULTIPLY', radius, -1.0)), line.inputs["End"])
    pts = g.curve_to_points_evaluated(g.resample_count(line.outputs["Curve"], g.math('ADD', count, 1.0)))
    spin = g.math('MULTIPLY', g.scene_seconds(), g.math('DIVIDE', speed, radius))
    cyl = g.node('GeometryNodeMeshCylinder')
    g.link(sides, cyl.inputs["Vertices"])
    g.link(radius, cyl.inputs["Radius"])
    g.link(roller_len, cyl.inputs["Depth"])
    rounded = g.bevel_caps(cyl.outputs["Mesh"], g.boolean('OR', cyl.outputs["Top"], cyl.outputs["Bottom"]), 0.002,
                           [(None, g.math('MULTIPLY', radius, 2.0))])
    roller = g.set_material(g.shade_smooth(rounded), gi.outputs["Roller Material"])
    roller = g.transform(roller, rotation=g.combine_xyz(y=math.pi / 2.0))  # axis Z -> X
    roller = g.transform(roller, rotation=g.combine_xyz(x=spin))
    yaw = g.math('SUBTRACT', math.pi / 2.0, skew)
    roller = g.transform(roller, rotation=g.combine_xyz(z=yaw))
    rollers = g.instance_on_points(pts, roller)

    g.column()
    go = g.node('NodeGroupOutput')
    g.link(g.join(deck, rollers), go.inputs["Geometry"])
    mark_tree_built(tree, version)
    return tree
