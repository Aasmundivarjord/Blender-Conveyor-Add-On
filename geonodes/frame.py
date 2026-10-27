"""THE frame: (heading, incline) -> Rotation. Nothing else in v2 computes an
orientation. Euler XYZ (incline, 0, heading) == Rz(heading) * Rx(incline):
forward = +Y rotated, right = (cos h, sin h, 0) stays horizontal, so roll is
zero by construction (see model/segments.py)."""
from __future__ import annotations

import bpy

from .builder_common import NodeGraph, get_or_create_tree, mark_tree_built

NODE_GROUP_NAME = "Conveyor - Frame"
TREE_VERSION = 1


def build(rebuild: bool = False) -> bpy.types.NodeTree:
    tree, needs_build = get_or_create_tree(NODE_GROUP_NAME, TREE_VERSION, rebuild=rebuild)
    if not needs_build:
        return tree
    g = NodeGraph(tree)
    g.input("Heading", 'NodeSocketFloat', default=0.0, subtype='ANGLE')
    g.input("Incline", 'NodeSocketFloat', default=0.0, subtype='ANGLE')
    g.output("Rotation", 'NodeSocketRotation')

    gi = g.node('NodeGroupInput')
    g.column()
    rotation = g.euler_to_rotation(g.combine_xyz(x=gi.outputs["Incline"], y=0.0, z=gi.outputs["Heading"]))
    g.column()
    go = g.node('NodeGroupOutput')
    g.link(rotation, go.inputs["Rotation"])
    mark_tree_built(tree, TREE_VERSION)
    return tree


def frame_rotation(g: NodeGraph, heading, incline):
    """Adds a Frame group node to `g` and returns its Rotation output."""
    n = g.group(build(), Heading=heading, Incline=incline)
    return n.outputs["Rotation"]


def spine_frame(g: NodeGraph):
    """Rotation field from the spine's own `heading`/`incline` attributes
    (valid wherever the field is evaluated on spine-derived geometry, e.g.
    after Resample Curve / Curve to Points, which interpolate them)."""
    return frame_rotation(g, g.named_attribute("heading"), g.named_attribute("incline"))
