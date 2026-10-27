"""Merge junction: a powered roller section that receives a feeding line
on its side. Rollers across, painted deck as the safety accent."""
from __future__ import annotations

import bpy

from .. import materials
from .common import build_module_tree

NODE_GROUP_NAME = "Conveyor - Module (Merge)"
TREE_VERSION = 5


def build(rebuild: bool = False) -> bpy.types.NodeTree:
    return build_module_tree(NODE_GROUP_NAME, TREE_VERSION, 0.0, None, 0.08, rebuild, skewable=True)
