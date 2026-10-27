"""Chain / modular plastic belt line tree: rails, guide rails, link plates
at a fixed pitch that travel with the line, sprockets at the ends, legs.

Links move like populated items: link k sits at arc length
(k * pitch + seconds * Speed) mod run length, sampled on each conveyor run,
so the surface visibly flows (a plain textured surface would not read as a
modular belt). Straight plates on curves are a visual approximation of
the wedge links a real curved modular belt uses."""
from __future__ import annotations

import bpy

from .. import materials
from ..builder_common import NodeGraph, get_or_create_tree, mark_tree_built
from ..frame import frame_rotation
from ..populate import add_populate_inputs
from . import common

NODE_GROUP_NAME = "Conveyor - Line (Chain)"
TREE_VERSION = 58  # 2.26.1: Transfer k Except (a corner's straight-through goods); 2.25.2: generic stage label (angled-roller decks); 2.24: FIFO buffer inputs (Buffer k Stop ... Rank, Switch Time); 2.22: simple flow route inputs (split edges, transfer rules)


def build(rebuild: bool = False) -> bpy.types.NodeTree:
    tree, needs_build = get_or_create_tree(NODE_GROUP_NAME, TREE_VERSION, rebuild=rebuild)
    if not needs_build:
        return tree
    g = NodeGraph(tree)

    common.declare_frame_inputs(g)
    g.input("Link Pitch", 'NodeSocketFloat', default=0.05, min_value=0.01, subtype='DISTANCE')
    g.input("Link Thickness", 'NodeSocketFloat', default=0.012, min_value=0.002, subtype='DISTANCE')
    g.input("Link Gap", 'NodeSocketFloat', default=0.004, min_value=0.0, subtype='DISTANCE')
    g.input("Sprocket Diameter", 'NodeSocketFloat', default=0.10, min_value=0.02, subtype='DISTANCE')
    add_populate_inputs(g)
    g.output("Geometry", 'NodeSocketGeometry')

    gi = g.node('NodeGroupInput')
    parts = common.split_spine(g, gi.outputs["Geometry"])
    offset = common.rail_offset(g, gi)
    rails = common.build_rails(g, gi, parts, offset)
    guides = common.build_guides(g, gi, parts, offset)
    legs = common.build_legs(g, gi, parts, offset)

    g.stage("Chain", "plate chain links along the runs with their sprockets")
    width = gi.outputs["Width"]
    pitch = gi.outputs["Link Pitch"]
    thickness = gi.outputs["Link Thickness"]
    speed = gi.outputs["Speed"]
    # Low Detail doubles the pitch (half the plates).
    effective_pitch = g.switch('FLOAT', gi.outputs["High Detail"], g.math('MULTIPLY', pitch, 2.0), pitch)

    # One point per link per run, computed while the geometry is still a
    # CURVE (Spline Parameter / Spline Length / Curve of Point have no
    # meaning on a point cloud): resample each run to `count` points, store
    # each point's flowing arc length and its run index as attributes,
    # convert to points, then sample the pose on that run at that length.
    spline_len = g.node('GeometryNodeSplineLength').outputs["Length"]
    count = g.math('MAXIMUM', g.math('FLOOR', g.math('DIVIDE', spline_len, effective_pitch)), 1.0)
    resampled = g.resample_count(parts.runs, count)
    param = g.node('GeometryNodeSplineParameter')
    link_spacing = g.math('DIVIDE', spline_len, count)
    raw = g.math('ADD', g.math('MULTIPLY', param.outputs["Index"], link_spacing), g.math('MULTIPLY', g.scene_seconds(), speed))
    wrapped = g.math('MODULO', g.math('ADD', g.math('MODULO', raw, spline_len), spline_len), spline_len)
    store_len = g.node('GeometryNodeStoreNamedAttribute', data_type='FLOAT', domain='POINT')
    g.link(resampled, store_len.inputs["Geometry"])
    store_len.inputs["Name"].default_value = "link_len"
    g.link(wrapped, store_len.inputs["Value"])
    store_run = g.node('GeometryNodeStoreNamedAttribute', data_type='INT', domain='POINT')
    g.link(store_len.outputs["Geometry"], store_run.inputs["Geometry"])
    store_run.inputs["Name"].default_value = "run_idx"
    g.link(g.node('GeometryNodeCurveOfPoint').outputs["Curve Index"], store_run.inputs["Value"])
    points = g.curve_to_points_evaluated(store_run.outputs["Geometry"])

    g.column()
    link_len = g.named_attribute("link_len")
    run_idx = g.named_attribute("run_idx", 'INT')

    def sample(name):
        n = g.node('GeometryNodeSampleCurve', mode='LENGTH', data_type='FLOAT')
        n.use_all_curves = False
        g.link(parts.runs, n.inputs["Curves"])
        g.link(g.named_attribute(name), n.inputs["Value"])
        g.link(link_len, n.inputs["Length"])
        g.link(run_idx, n.inputs["Curve Index"])
        return n

    s_heading = sample("heading")
    s_incline = sample("incline")
    link_frame = frame_rotation(g, s_heading.outputs["Value"], s_incline.outputs["Value"])
    drop = g.rotate_vector(g.combine_xyz(z=g.math('MULTIPLY', thickness, -0.5)), link_frame)
    placed = g.set_position(points, position=s_heading.outputs["Position"], offset=drop)

    plate_len = g.math('MAXIMUM', g.math('SUBTRACT', effective_pitch, gi.outputs["Link Gap"]), 0.002)
    plate = g.set_material(g.rounded_box(width, plate_len, thickness, 0.002), gi.outputs["Link Material"])
    links = g.instance_on_points(placed, plate, rotation=link_frame)

    g.column()
    sprocket_radius = g.math('DIVIDE', gi.outputs["Sprocket Diameter"], 2.0)
    sprocket = common.spinning_cylinder(g, common.detail_sides(g, gi), sprocket_radius, g.math('MULTIPLY', width, 0.9), speed, gi.outputs["Frame Material"])
    sprockets = common.end_cylinders(g, parts, parts.runs, g.math('ADD', thickness, sprocket_radius), sprocket)

    common.finish(g, gi, parts, rails, guides, legs, links, sprockets, surface="chain")
    g.guide("A chain conveyor line: the spine becomes frame rails, fences, legs, the plate chain, the modules on it and the goods riding it.")
    mark_tree_built(tree, TREE_VERSION)
    return tree
