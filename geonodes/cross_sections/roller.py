"""Roller line tree: rails, guide rails, rollers and support legs. Shared by
gravity_roller and powered_roller (MDR drive housings are a later addition).
All inputs are Blender units; operators/build_line.py converts from mm."""
from __future__ import annotations

import bpy

from .. import materials
from ..builder_common import NodeGraph, get_or_create_tree, mark_tree_built
from ..populate import add_populate_inputs
from . import common

NODE_GROUP_NAME = "Conveyor - Line (Roller)"
TREE_VERSION = 61  # 2.26.1: Transfer k Except (a corner's straight-through goods); 2.25.2: generic stage label (angled-roller decks); 2.24: FIFO buffer inputs (Buffer k Stop ... Rank, Switch Time); 2.22: simple flow route inputs (split edges, transfer rules)

# The line's own Roller Pitch input is used as-is (the user sets it in the
# panel); only overlap is prevented.


def build(rebuild: bool = False) -> bpy.types.NodeTree:
    tree, needs_build = get_or_create_tree(NODE_GROUP_NAME, TREE_VERSION, rebuild=rebuild)
    if not needs_build:
        return tree
    g = NodeGraph(tree)

    common.declare_frame_inputs(g)
    g.input("Roller Diameter", 'NodeSocketFloat', default=0.0483, min_value=0.005, subtype='DISTANCE')
    g.input("Roller Pitch", 'NodeSocketFloat', default=0.0762, min_value=0.005, subtype='DISTANCE')
    g.input("Roller Overhang", 'NodeSocketFloat', default=0.006, min_value=0.0, subtype='DISTANCE')
    add_populate_inputs(g)
    g.output("Geometry", 'NodeSocketGeometry')

    gi = g.node('NodeGroupInput')
    parts = common.split_spine(g, gi.outputs["Geometry"])
    offset = common.rail_offset(g, gi)
    rails = common.build_rails(g, gi, parts, offset)
    guides = common.build_guides(g, gi, parts, offset)
    legs = common.build_legs(g, gi, parts, offset)

    g.stage("Rollers", "spinning cylinders along the conveyor runs at the roller pitch, ends inside the rails")
    width = gi.outputs["Width"]
    diameter = gi.outputs["Roller Diameter"]
    # Roller ends stay inside the rail: overhang capped below the rail's outer face.
    safe_overhang = g.math('MINIMUM', gi.outputs["Roller Overhang"], g.math('MULTIPLY', gi.outputs["Rail Thickness"], 0.6))
    length = g.math('ADD', width, g.math('MULTIPLY', safe_overhang, 2.0))
    radius = g.math('DIVIDE', diameter, 2.0)
    pitch = g.math('MAXIMUM', gi.outputs["Roller Pitch"], g.math('ADD', diameter, common.MIN_CYLINDER_GAP))
    roller = common.spinning_cylinder(g, common.detail_sides(g, gi), radius, length, gi.outputs["Speed"], gi.outputs["Roller Material"])
    rollers = common.cylinders_along(g, parts, parts.runs, pitch, radius, roller)

    common.finish(g, gi, parts, rails, guides, legs, rollers)
    g.guide("A roller conveyor line: the spine (a Curves object written by the plugin) becomes frame rails, fences, legs, rollers, the modules on it and the goods riding it.")
    mark_tree_built(tree, TREE_VERSION)
    return tree
