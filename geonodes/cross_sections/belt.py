"""Belt line tree: rails, guide rails, a continuous rubber belt surface,
idler rollers beneath it, end pulleys, legs.

Belt scroll: the belt mesh inherits the spine's `arc_len` point attribute
through Curve to Mesh; `belt_scroll` = arc_len - seconds * Speed is stored
on it and the shared rubber material reads that attribute for its texture
coordinate, so ONE material scrolls at each line's own speed. Pulley
diameter and idler pitch are engineering estimates (roller_specs.json)."""
from __future__ import annotations

import bpy

from .. import materials
from ..builder_common import NodeGraph, get_or_create_tree, mark_tree_built
from ..populate import add_populate_inputs
from . import common

NODE_GROUP_NAME = "Conveyor - Line (Belt)"
TREE_VERSION = 58  # 2.26.1: Transfer k Except (a corner's straight-through goods); 2.25.2: generic stage label (angled-roller decks); 2.24: FIFO buffer inputs (Buffer k Stop ... Rank, Switch Time); 2.22: simple flow route inputs (split edges, transfer rules)


def build(rebuild: bool = False) -> bpy.types.NodeTree:
    tree, needs_build = get_or_create_tree(NODE_GROUP_NAME, TREE_VERSION, rebuild=rebuild)
    if not needs_build:
        return tree
    g = NodeGraph(tree)

    common.declare_frame_inputs(g)
    g.input("Belt Thickness", 'NodeSocketFloat', default=0.01, min_value=0.002, subtype='DISTANCE')
    g.input("Pulley Diameter", 'NodeSocketFloat', default=0.08, min_value=0.02, subtype='DISTANCE')
    g.input("Idler Diameter", 'NodeSocketFloat', default=0.0483, min_value=0.005, subtype='DISTANCE')
    g.input("Idler Pitch", 'NodeSocketFloat', default=0.3, min_value=0.02, subtype='DISTANCE')
    add_populate_inputs(g)
    g.output("Geometry", 'NodeSocketGeometry')

    gi = g.node('NodeGroupInput')
    parts = common.split_spine(g, gi.outputs["Geometry"])
    offset = common.rail_offset(g, gi)
    rails = common.build_rails(g, gi, parts, offset)
    guides = common.build_guides(g, gi, parts, offset)
    legs = common.build_legs(g, gi, parts, offset)

    g.stage("Belt", "the belt top and return run swept along the runs, with its scrolling texture coordinate")
    width = gi.outputs["Width"]
    thickness = gi.outputs["Belt Thickness"]
    speed = gi.outputs["Speed"]
    # Belt top at the surface: profile centered at -thickness/2 (profile Y = up).
    belt_profile = g.transform(g.filleted_rectangle(width, thickness, 0.003), translation=g.combine_xyz(y=g.math('MULTIPLY', thickness, -0.5)))
    belt_mesh = g.curve_to_mesh(parts.oriented_runs, belt_profile, fill_caps=True)
    scroll = g.math('SUBTRACT', g.named_attribute("arc_len"), g.math('MULTIPLY', g.scene_seconds(), speed))
    store = g.node('GeometryNodeStoreNamedAttribute', data_type='FLOAT', domain='POINT')
    g.link(belt_mesh, store.inputs["Geometry"])
    store.inputs["Name"].default_value = "belt_scroll"
    g.link(scroll, store.inputs["Value"])
    belt = g.set_material(store.outputs["Geometry"], gi.outputs["Belt Material"])

    g.column()
    sides = common.detail_sides(g, gi)
    idler_radius = g.math('DIVIDE', gi.outputs["Idler Diameter"], 2.0)
    idler_pitch = common.overlap_safe_pitch(g, gi, gi.outputs["Idler Pitch"], gi.outputs["Idler Diameter"], 1.0, 2.0)
    idler = common.spinning_cylinder(g, sides, idler_radius, width, speed, gi.outputs["Roller Material"])
    idlers = common.cylinders_along(g, parts, parts.runs, idler_pitch, g.math('ADD', thickness, idler_radius), idler)

    g.column()
    pulley_radius = g.math('DIVIDE', gi.outputs["Pulley Diameter"], 2.0)
    pulley = common.spinning_cylinder(g, sides, pulley_radius, width, speed, gi.outputs["Frame Material"])
    pulleys = common.end_cylinders(g, parts, parts.runs, g.math('ADD', thickness, pulley_radius), pulley)

    common.finish(g, gi, parts, rails, guides, legs, belt, idlers, pulleys, surface="belt")
    g.guide("A belt conveyor line: the spine becomes frame rails, fences, legs, the belt with its pulleys, the modules on it and the goods riding it.")
    mark_tree_built(tree, TREE_VERSION)
    return tree
