"""Diverter / sorter: skewed-roller style visual module (rollers yawed 30
degrees push product toward one side). Full sortation logic out of scope."""
from __future__ import annotations

import bpy

from .. import materials
from .common import build_module_tree

NODE_GROUP_NAME = "Conveyor - Module (Diverter)"
TREE_VERSION = 4


def build(rebuild: bool = False) -> bpy.types.NodeTree:
    return build_module_tree(NODE_GROUP_NAME, TREE_VERSION, 30.0, None, 0.09, rebuild)
