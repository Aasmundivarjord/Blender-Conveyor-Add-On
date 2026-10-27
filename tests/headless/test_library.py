"""The shipped node libraries (geonodes/library, 2.25): one per supported
Blender series, each matching the code's TREE_VERSIONs, and the running
Blender appends from its own series' library -- a 5.2 user got no library
at all before (the only one was written by 5.3) and waited 21 s for the
first line. Blender -b --python tests/headless/test_library.py"""
import json, time, traceback, bpy
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.geonodes import frame, library, populate
from bl_ext.user_default.conveyor_system.geonodes.cross_sections import belt, chain, omni, pouch, roller
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line
ctx = bpy.context; fails = []


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)


try:
    code = {m.NODE_GROUP_NAME: m.TREE_VERSION for m in (frame, populate, roller, belt, chain, omni, pouch)}
    shipped = sorted(library.LIBRARY_DIR.glob("conveyor_nodes-*.json"))
    names = [p.name for p in shipped]
    check({"conveyor_nodes-5.2.json", "conveyor_nodes-5.3.json"} <= set(names), f"a library per supported series ({names})")
    for p in shipped:
        trees = json.loads(p.read_text(encoding="utf-8")).get("trees", {})
        blend = p.with_name(p.name[: -len(".json")] + ".blend")
        check(trees == code and blend.is_file(),
              f"{p.name} matches the code's tree versions and has its .blend (regenerate with tools/build_tree_library.py in that series)")
    series = f"{bpy.app.version[0]}.{bpy.app.version[1]}"
    check(bool(library.index()) and library._index_cache["blend"].name == f"conveyor_nodes-{series}.blend",
          f"Blender {bpy.app.version_string} appends from its own series' library ({library._index_cache.get('blend')})")
    t = time.perf_counter()
    o = create_line(ctx, Vector((0.0, 0.0, 0.8)), 0.0)
    build_line(ctx, o)
    dt = time.perf_counter() - t
    check(dt < 3.0, f"the first line builds from the library in {dt:.2f} s (built node by node it takes ~20 s on 5.2)")
except Exception:
    traceback.print_exc(); fails.append("raised")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
