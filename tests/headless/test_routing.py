"""Routing regression: a line whose start leaves a main line docks onto an
auto diverter, gets the main's path as its stream prefix, takes one item
class, follows when moved and folds away on detach. Run headless:
  Blender -b --python tests/headless/test_routing.py"""
import math, bpy
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line, MODIFIER_NAME
from bl_ext.user_default.conveyor_system.operators.detect_junctions import sync_feeder, docked_diverter, docked_junction
from bl_ext.user_default.conveyor_system.operators.populate import PLACEHOLDER_COLLECTION_NAME
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
            v = mod.properties.inputs[item.identifier]["value"]
            return v.name if hasattr(v, "name") else v
    raise KeyError(name)
def instances(obj):
    dg = ctx.evaluated_depsgraph_get(); out = []
    for inst in dg.object_instances:
        if inst.is_instance and inst.parent is not None and inst.parent.original == obj and "Placeholder" in inst.object.name:
            out.append((inst.object.name, inst.matrix_world.translation.copy()))
    return out
def make(loc, heading, length_mm, name, populate=False):
    o = create_line(ctx, Vector((100, 100, 0)), heading); o.name = name; o.location = Vector(loc)
    with suspended_rebuild():
        o.conveyor_line.segments[0]["length_mm"] = float(length_mm)
        o.conveyor_line.populate = populate
        o.conveyor_line.speed_m_s = 0.5
    ctx.view_layer.update(); build_line(ctx, o); ctx.view_layer.update()
    return o
main = make((0, 0, 0), 0.0, 8000, "Main", populate=True)
branch = make((0.5, 3.0, 0), -math.pi / 4, 3000, "Branch")
dock = docked_diverter(ctx, branch)
check(dock is not None, "branch start docked on a diverter")
segs = main.conveyor_line.segments
print("main segments:", [(s.kind, s.module_kind if s.kind == 'MODULE' else round(s.length_mm)) for s in segs])
if dock:
    line, i = dock
    seg = segs[i]
    check(seg.module_kind == 'DIVERTER' and seg.merge_side == 'RIGHT' and seg.merge_angle == '45' and seg.merge_auto, "auto diverter RIGHT 45")
    check(seg.merge_source == branch.name, "diverter source is the branch")
    bs = branch.conveyor_line
    check(bs.get("branch_target") == main.name, "branch_target recorded")
    n0 = branch.data.curves[0].points_length
    idx = [v.value for v in branch.data.attributes["segment_index"].data][:n0]
    n_prefix = sum(1 for v in idx if v == -2)
    check(n_prefix > 5, f"prefix points on the branch spline: {n_prefix}")
    arcs = [v.value for v in branch.data.attributes["arc_len"].data]
    check(abs(arcs[n_prefix] - float(bs.get("branch_from"))) < 1e-4, "own start arc == branch_from")
    pos = [Vector(v.vector) for v in branch.data.attributes["position"].data]
    check((branch.matrix_world @ pos[0]).length < 0.05, "prefix starts at the main's start")
    check(abs(math.degrees(branch.rotation_euler.z) + 45) < 0.01, "branch heading snapped to -45")
    names = sorted(o.name for o in bpy.data.collections[PLACEHOLDER_COLLECTION_NAME].objects)
    carton = next(k for k, n in enumerate(names) if "Carton" in n)
    seg.route_item = str(carton)
    check(seg.route_class == carton, "route_item enum sets route_class")
    ctx.view_layer.update()
    s_switch = float(bs.get("branch_from")) - float(bs.get("branch_blend"))
    check(inp(main, "Route Class 1") == carton and abs(inp(main, "Route At 1") - s_switch) < 1e-4, "main hides the routed class from the switch arc")
    check(inp(branch, "Route Class 1") == carton and inp(branch, "Route Take 1") and inp(branch, "Route Share 1") < 0.0
          and abs(inp(branch, "Prefix") - s_switch) < 1e-4 and inp(branch, "Populate"), "branch shows the routed class from the switch arc (its own class edge, 2.22)")
    check(inp(branch, "Use Stream Speed") and abs(inp(branch, "Stream Speed") - 0.5) < 1e-6, "branch stream runs at the main's speed")
    check(abs(inp(main, "Stream Length") - inp(branch, "Stream Length")) < 1e-6 and inp(main, "Stream Length") > 7.99, "shared stream length")
    ctx.scene.frame_set(12)
    mi = instances(main); bi = instances(branch)
    cartons_after = [p for n, p in mi if "Carton" in n and p.y > s_switch + 0.01]
    check(not cartons_after, f"no cartons on the main past the switch ({len(cartons_after)})")
    check(bi and all("Carton" in n for n, _p in bi), f"branch carries only cartons ({len(bi)} items)")
    check(not [p for _n, p in bi if p.x < 0.2 and p.y < s_switch - 0.01], "branch draws nothing on the main before the switch")
    totes_main = [p for n, p in mi if "Tote" in n]
    check(totes_main and any(p.y > 5 for p in totes_main), "totes stay on the main to the end")
    from_before = float(bs.get("branch_from"))
    branch.location.y += 0.8
    ctx.view_layer.update(); sync_feeder(ctx, branch); ctx.view_layer.update()
    check(docked_diverter(ctx, branch) is not None, "still docked after moving")
    check(abs(float(branch.conveyor_line.get("branch_from")) - from_before - 0.8) < 0.02, "diverter followed the branch by 0.8 m")
    branch.conveyor_line.dock_enabled = False
    sync_feeder(ctx, branch); ctx.view_layer.update()
    check(docked_diverter(ctx, branch) is None, "detached")
    check(all(s.kind != 'MODULE' for s in main.conveyor_line.segments), "auto diverter removed on detach")
    build_line(ctx, branch)
    idx = [v.value for v in branch.data.attributes["segment_index"].data]
    check(all(v >= 0 for v in idx[:branch.data.curves[0].points_length]), "prefix cleared")
feeder = make((-2.5, 3.0, 0), -math.pi / 4, 3000, "Feeder")
check(docked_junction(ctx, feeder) is not None, "feeder end still docks on a merge junction")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
