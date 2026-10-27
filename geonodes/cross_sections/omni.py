"""Omni-wheel line tree: rails, guide rails, legs, a deck plate and rows of
small powered omni wheels (staggered grid) spinning along the flow. Merges,
diverters and RATs on this line get the wheel deck too (common.finish with
surface="omni"). All inputs are Blender units."""
from __future__ import annotations

import bpy

from ..builder_common import NodeGraph, get_or_create_tree, mark_tree_built
from ..populate import add_populate_inputs
from . import common

NODE_GROUP_NAME = "Conveyor - Line (Omni)"
TREE_VERSION = 31  # 2.26.1: Transfer k Except (a corner's straight-through goods); 2.25.2: generic stage label (angled-roller decks); 2.24: FIFO buffer inputs (Buffer k Stop ... Rank, Switch Time); 2.22: simple flow route inputs (split edges, transfer rules)


def build(rebuild: bool = False) -> bpy.types.NodeTree:
    tree, needs_build = get_or_create_tree(NODE_GROUP_NAME, TREE_VERSION, rebuild=rebuild)
    if not needs_build:
        return tree
    g = NodeGraph(tree)

    common.declare_frame_inputs(g)
    add_populate_inputs(g)
    g.output("Geometry", 'NodeSocketGeometry')

    gi = g.node('NodeGroupInput')
    parts = common.split_spine(g, gi.outputs["Geometry"])
    offset = common.rail_offset(g, gi)
    rails = common.build_rails(g, gi, parts, offset)
    guides = common.build_guides(g, gi, parts, offset)
    legs = common.build_legs(g, gi, parts, offset)

    g.stage("Omni deck", "the omni-wheel deck slab")
    deck = common.build_omni_deck(g, gi, parts.oriented_runs)
    wheels = common.build_omni_wheels(g, gi, parts, parts.runs)

    common.finish(g, gi, parts, rails, guides, legs, deck, wheels, surface="omni")
    g.guide("An omni-wheel conveyor line: the spine becomes a wheel deck, fences, legs, the modules on it and the goods riding it.")
    mark_tree_built(tree, TREE_VERSION)
    return tree
