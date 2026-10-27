"""Builds every shipped node tree with the Python builders and writes the
node library of this Blender series (geonodes/library/conveyor_nodes-<major>.<minor>.blend + .json),
so the first New Line appends trees instead of building them node by node
(geonodes/library.py). Run after changing any builder or TREE_VERSION, in the
sandbox, then commit the two files with the code:

  TMPDIR=<scratch>/tmp BLENDER_USER_EXTENSIONS=<ext> BLENDER_USER_CONFIG=<scratch config> \\
    Blender -b --factory-startup --python tools/build_tree_library.py

(<ext>/user_default/conveyor_system is this dev tree.) Run it once in EVERY
supported Blender series (5.2 and 5.3 today): each series appends from the
newest library written by itself or an older series, never a newer one
(geonodes/library.index). Not shipped in the zip."""
import json
import sys

import bpy

PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)

from bl_ext.user_default.conveyor_system.geonodes import frame, library, populate  # noqa: E402
from bl_ext.user_default.conveyor_system.geonodes.cross_sections import belt, chain, omni, pouch, roller  # noqa: E402

library._index_cache["data"] = {}  # build everything from the code: never append from the old library
for ng in list(bpy.data.node_groups):
    bpy.data.node_groups.remove(ng)
trees = {}
for module in (frame, populate, roller, belt, chain, omni, pouch):
    tree = module.build(rebuild=True)
    trees[module.NODE_GROUP_NAME] = (tree, module.TREE_VERSION)
    print("BUILT", module.NODE_GROUP_NAME, module.TREE_VERSION, len(tree.nodes), "nodes")
for tree, _version in trees.values():
    tree.use_fake_user = True
blend_path, index_path = library.library_paths()
bpy.data.libraries.write(str(blend_path), {tree for tree, _v in trees.values()}, fake_user=True, compress=True)
index_path.write_text(json.dumps({
    "blender": bpy.app.version_string,
    "blender_version": list(bpy.app.version),
    "trees": {name: version for name, (_tree, version) in trees.items()},
}, indent=1) + "\n", encoding="utf-8")
print("WROTE", blend_path, index_path)
sys.stdout.flush()
