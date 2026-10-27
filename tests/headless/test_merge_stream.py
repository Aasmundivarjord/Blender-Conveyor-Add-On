"""Merge stream regression: a 45 deg and a 90 deg feeder on a populated
main share one stream (no overlaps on the centerline), 45 deg goods align
with the main, 90 deg goods keep their orientation, the main has one
continuous guide spline and switches to chain. Run headless:
  Blender -b --python tests/headless/test_merge_stream.py"""
import math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line, MODIFIER_NAME
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
from bl_ext.user_default.conveyor_system.operators import stream
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
ctx = bpy.context
fails = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond: fails.append(msg)
def inp(obj, name):
    mod = obj.modifiers[MODIFIER_NAME]
    for item in mod.node_group.interface.items_tree:
        if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == name:
            v = mod.properties.inputs[item.identifier]["value"]; return v.name if hasattr(v, "name") else v
def items(obj):
    dg = ctx.evaluated_depsgraph_get(); out = []
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.parent.original == obj and "Placeholder" in i.object.name:
            out.append((i.object.name.split()[1], i.matrix_world.translation.copy(), i.matrix_world.to_euler().z))
    return out
def make(loc, heading, length_mm, name, populate=True, pop=50.0):
    o = create_line(ctx, Vector((100, 100, 0)), heading); o.name = name; o.location = Vector(loc)
    with suspended_rebuild():
        o.conveyor_line.segments[0]["length_mm"] = float(length_mm)
        o.conveyor_line.populate = populate
        o.conveyor_line.population_pct = pop
        o.conveyor_line.speed_m_s = 0.5
    ctx.view_layer.update(); build_line(ctx, o); ctx.view_layer.update()
    return o
main = make((0, 0, 0), 0.0, 10000, "Main")
# The feeders fit under the grid's floor once the 90 degree merge's stop sets it (45.7 %): at a capped
# merge warehouse_common's resolve gives the feeders their goods first, the main what is left (2.23).
f45 = make((-2.5, 3.0, 0), -math.pi / 4, 3000, "Feeder45", pop=20.0)
check(dj.docked_junction(ctx, f45) is not None, "45 feeder docked")
tree = stream.tree_for(ctx, main)
check(tree.shared and tree.sources == 1, "shared stream with one feeder source")
check(inp(main, "Owner Mask") == 1 and inp(f45, "Owner Mask") == 2, "owner masks")
check(abs(inp(main, "Stream Length") - inp(f45, "Stream Length")) < 1e-6 and inp(f45, "Use Stream Speed"), "shared length + stream speed")
check(abs(inp(main, "Spacing") - inp(f45, "Spacing")) < 1e-6, "shared spacing")
spacing = inp(main, "Spacing")
worst = 9.0
for frame in (1, 9, 17, 25, 33):
    ctx.scene.frame_set(frame)
    ys = sorted(p.y for _n, p, _r in items(main) + items(f45) if abs(p.x) < 0.05 and p.y > 3.0)
    for a, b in zip(ys, ys[1:]):
        worst = min(worst, b - a)
check(worst >= spacing - 0.02, f"min centerline gap {worst:.3f} >= spacing {spacing:.3f}")
ctx.scene.frame_set(1)
mi = items(main); fi = items(f45)
check(mi and fi, f"both draw items (main {len(mi)}, feeder {len(fi)})")
far = [r for _n, p, r in fi if abs(p.x) < 0.05 and p.y > 6.0]
check(far and all(abs(math.degrees(r)) < 1.0 for r in far), "45 feeder goods aligned with the main after the blend")
n0 = f45.data.curves[0].points_length
idx = [v.value for v in f45.data.attributes["segment_index"].data]
first_cont = next(i for i in range(n0) if idx[i] == -1)
hd = [v.value for v in f45.data.attributes["heading"].data]
check(abs(math.degrees(hd[first_cont] - hd[first_cont - 1])) < 20.0, "goods keep the feeder direction into the wedge")
f90 = make((1.8, 7.0, 0), math.pi / 2, 1200, "Feeder90", pop=15.0)
d = dj.docked_junction(ctx, f90)
check(d is not None and d[0].conveyor_line.segments[d[1]].merge_angle == '90', "90 feeder docked on a 90 junction")
yo = [v.value for v in f90.data.attributes["yaw_offset"].data]; idx = [v.value for v in f90.data.attributes["segment_index"].data]
cont = [yo[i] for i in range(f90.data.curves[0].points_length) if idx[i] == -1]
check(cont and abs(abs(math.degrees(cont[-1])) - 90) < 1.0, "yaw_offset +-90 on the main after a right-angle transfer")
check(float(f90.conveyor_line.get("continue_extra_m", 0)) > 0.05, "slide length recorded")
ri = []  # since 2.20 the goods stand on the transfer before they roll on: look over a stretch of frames
for frame in range(1, 241, 4):
    ctx.scene.frame_set(frame)
    ri += [(p, r) for _n, p, r in items(f90) if abs(p.x) < 0.05 and p.y > 7.3]
check(ri and all(abs(abs(math.degrees(r)) - 90) < 1.0 for p, r in ri), f"90 feeder goods keep their orientation on the main ({len(ri)} seen)")
tree = stream.tree_for(ctx, main)
check(tree.sources == 2 and inp(main, "Stream Sources") == 2, "two sources now")
roles = [v.value for v in main.data.attributes["role"].data]
check(roles.count(4) == 1, "main has one continuous guide spline")
try:
    main.conveyor_line.conveyor_type = 'chain'; ctx.view_layer.update()
    check(main.modifiers[MODIFIER_NAME].node_group.name.endswith("(Chain)"), "main switched to chain")
    dg = ctx.evaluated_depsgraph_get(); geo = main.evaluated_get(dg).evaluated_geometry(); me = geo.mesh
    check(me is not None and len(me.polygons) > 0, "chain main evaluates")
except Exception:
    traceback.print_exc(); fails.append("chain switch raised")
from bl_ext.user_default.conveyor_system.ui.panels import extension_version
check(extension_version() not in ("?", ""), f"version label {extension_version()}")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
