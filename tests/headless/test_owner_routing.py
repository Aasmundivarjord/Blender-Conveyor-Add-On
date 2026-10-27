import math, bpy
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line, MODIFIER_NAME
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, stream
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
        if i.is_instance and i.parent and i.parent.original == obj and i.object.name in ("Cone", "Cyl", "Cube") :
            out.append((i.object.name, i.matrix_world.translation.copy()))
    return out
def prim(kind, name, loc):
    if kind == "cone": bpy.ops.mesh.primitive_cone_add(radius1=0.15, depth=0.3, location=loc)
    elif kind == "cyl": bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=0.3, location=loc)
    else: bpy.ops.mesh.primitive_cube_add(size=0.3, location=loc)
    o = ctx.active_object; o.name = name; return o
cone = prim("cone", "Cone", (50, 50, 0)); cyl = prim("cyl", "Cyl", (52, 50, 0)); cube = prim("cube", "Cube", (54, 50, 0))
def make(loc, heading, length_mm, name, item=None, reverse=False, tp=0):
    o = create_line(ctx, Vector((100, 100, 0)), heading); o.name = name; o.location = Vector(loc)
    with suspended_rebuild():
        o.conveyor_line.segments[0]["length_mm"] = length_mm
        o.conveyor_line.populate = True
        o.conveyor_line.speed_m_s = 0.5
        o.conveyor_line.reverse = reverse
        o.conveyor_line.throughput_ph = tp
        if item: o.conveyor_line.populate_item = item
    ctx.view_layer.update(); build_line(ctx, o); ctx.view_layer.update()
    return o
main = make((0, 0, 0), 0.0, 12000, "Main", cube)
fa = make((-2.6, 2.0, 0), -math.pi / 4, 3000, "FeedCones", cone)   # merges from the left at ~4.1
fb = make((2.6, 4.0, 0), math.pi / 4, 3000, "FeedCyls", cyl)       # merges from the right at ~6.1
out = make((2.5, 10.5, 0), math.radians(135), 3000, "OutCones", cone, reverse=True)  # takes cones out at ~8.4
print("main:", [(s.kind, s.module_kind if s.kind == 'MODULE' else round(s.length_mm), s.merge_source if s.kind == 'MODULE' else '') for s in main.conveyor_line.segments])
check(dj.docked_junction(ctx, fa) and dj.docked_junction(ctx, fb) and dj.docked_diverter(ctx, out), "two feeders and one outfeed docked")
tree = stream.tree_for(ctx, main)
print("tree:", {n: (round(m.offset, 2), m.owner, m.mask, round(m.prefix_u, 2)) for n, m in tree.members.items()}, "routes", tree.routes, "splits", [round(s, 2) for s in tree.splits[:4]])
oc = tree.members["OutCones"]
cone_owner = tree.members["FeedCones"].owner
check(oc.mask == (1 << cone_owner), f"outfeed takes only the cone feeder's slots (mask {oc.mask}, cone owner {cone_owner})")
check(inp(out, "Owner Mask") == oc.mask and inp(out, "Route Mask 1") == oc.mask and abs(inp(out, "Route Share 1") - 1.0) < 1e-6
      and inp(out, "Route Take 1") and inp(out, "Route Class 1") == -1, "outfeed inputs: owner mask, all of its item's goods, no class filter")
switch_u = oc.prefix_u
found_cone_on_out = found_cone_after = found_cyl_after = False
for f in (5, 15, 25, 35, 45, 55):
    ctx.scene.frame_set(f)
    for n, p in items(out):
        if p.x > 0.4: found_cone_on_out = True
        if n != "Cone": fails.append(f"non-cone {n} on the outfeed")
    for n, p in items(main) + items(fa) + items(fb):
        if abs(p.x) < 0.05 and p.y > switch_u + 0.6:
            if n == "Cone": found_cone_after = True
            if n == "Cyl": found_cyl_after = True
check(found_cone_on_out, "cones ride the outfeed")
check(not found_cone_after, "no cones on the main past the outfeed")
check(found_cyl_after, "cylinders continue on the main past the outfeed")
# simple flow (2.22): every owner brings its own Population at the group's speed, the flows add: 600/h of
# cubes, 1200/h of cones, 600/h of cylinders (0.3 m goods, 0.35 m at 100 %) = 2400/h at 0.5 m/s -> a 0.75 m
# grid, the slots dealt 1/4, 1/2, 1/4
pct = lambda rate: 100.0 * rate * (0.3 + 0.05) / (3600.0 * 0.5)
main.conveyor_line.population_pct = pct(600); fa.conveyor_line.population_pct = pct(1200); fb.conveyor_line.population_pct = pct(600)
ctx.view_layer.update()
tree = stream.tree_for(ctx, main)
print("throughput", tree.throughput_ph, "spacing", round(tree.spacing, 3), "splits", [round(s, 3) for s in tree.splits[:4]])
check(abs(tree.spacing - 0.75) < 1e-6, f"spacing from throughput {tree.spacing:.3f} == 0.75")
check(abs(inp(main, "Spacing") - 0.75) < 1e-6 and abs(inp(fa, "Spacing") - 0.75) < 1e-6, "spacing pushed to the group")
# shares: a 120 m main gives ~150 slots past the merges (each slot has one fixed owner)
def segs(o): return [(s.kind, s.module_kind if s.kind == 'MODULE' else round(s.length_mm)) for s in o.conveyor_line.segments]
print("S0", segs(main))
with suspended_rebuild():
    main.conveyor_line.segments[-1]["length_mm"] = 120000.0
print("S1", segs(main))
build_line(ctx, main); ctx.view_layer.update()
print("S2", segs(main), "full", main.conveyor_line.get("full_length_m"))
out.conveyor_line.dock_enabled = False; ctx.view_layer.update()
print("S3", segs(main), "full", main.conveyor_line.get("full_length_m"))
dj.sync_feeder(ctx, out); ctx.view_layer.update()  # no outfeed: count all owners
print("S4", segs(main), "full", main.conveyor_line.get("full_length_m"))
ctx.scene.frame_set(1)
print("after lengthening: main inputs", {k: inp(main, k) for k in ("Stream Length", "Spacing", "Populate", "Owner Mask", "Stream Sources", "Fill", "Item Length")}, "full", main.conveyor_line.get("full_length_m"), "docks", dj.docked_junction(ctx, fa) is not None, dj.docked_junction(ctx, fb) is not None)
dg = ctx.evaluated_depsgraph_get(); names = {}
for i in dg.object_instances:
    if i.is_instance and i.parent and i.parent.original == main: names[i.object.name] = names.get(i.object.name, 0) + 1
print("instances on main by object:", {k: v for k, v in names.items() if k in ("Cube", "Cone", "Cyl")}, "cube ys:", sorted(round(p.y, 1) for n, p in items(main))[:20])
counts = {"Cube": 0, "Cone": 0, "Cyl": 0}
for n, p in items(main) + items(fa) + items(fb):
    if abs(p.x) < 0.05 and p.y > 8.0: counts[n] += 1
tot = sum(counts.values())
print("slot owners on the main past the merges:", counts, "of", tot, "->", {k: round(v / tot, 2) for k, v in counts.items()})
check(tot > 100, f"enough slots to judge ({tot})")
check(abs(counts["Cone"] / tot - 0.5) < 0.1 and abs(counts["Cube"] / tot - 0.25) < 0.1, "owner shares follow the Populations (cube 25%, cone 50%, cyl 25%)")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
