"""Right-Angle Transfer: a powered transfer head whose rollers run ALONG
the incoming travel direction, so spinning them pushes product sideways
off the line without turning it (see model/segments.py on yaw_offset)."""
from __future__ import annotations

import bpy

from .. import materials
from .common import build_module_tree

NODE_GROUP_NAME = "Conveyor - Module (RAT)"
TREE_VERSION = 4


def build(rebuild: bool = False) -> bpy.types.NodeTree:
    return build_module_tree(NODE_GROUP_NAME, TREE_VERSION, 90.0, None, 0.10, rebuild)
