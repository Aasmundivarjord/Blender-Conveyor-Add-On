import math, bpy, traceback
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
        if i.is_instance and i.parent and i.parent.original == obj and "Placeholder" in i.object.name:
            out.append((i.object.name.split()[1], i.matrix_world.translation.copy(), i.matrix_world.to_euler().z))
    return out
def make(loc, heading, length_mm, name, populate=True, reverse=False):
    o = create_line(ctx, Vector((100, 100, 0)), heading); o.name = name; o.location = Vector(loc)
    with suspended_rebuild():
        o.conveyor_line.segments[0]["length_mm"] = length_mm
        o.conveyor_line.populate = populate
        o.conveyor_line.speed_m_s = 0.5
        o.conveyor_line.reverse = reverse
    ctx.view_layer.update(); build_line(ctx, o); ctx.view_layer.update()
    return o
def segs(o): return [(s.kind, s.module_kind if s.kind == 'MODULE' else round(s.length_mm), s.merge_angle if s.kind == 'MODULE' else '', s.merge_side if s.kind == 'MODULE' else '') for s in o.conveyor_line.segments]
def tags(o):
    n0 = o.data.curves[0].points_length; idx = [v.value for v in o.data.attributes["segment_index"].data][:n0]
    return sum(1 for v in idx if v == -2), sum(1 for v in idx if v >= 0), sum(1 for v in idx if v == -1)

# ---------- A. outfeed: reversed line whose curve END touches the main -> DIVERTER, goods leave with the flow
main = make((0, 0, 0), 0.0, 10000, "Main")
out = make((2.5, 7.0, 0), math.radians(135), 3000, "Out", reverse=True)
d = dj.docked_diverter(ctx, out)
check(d is not None, "reversed line docked by its end as an OUTFEED (diverter)")
print("main:", segs(main)); print("out tags (before, own, after):", tags(out), "keys", {k: out.conveyor_line.get(k) for k in ("branch_target", "branch_from", "prefix_length_m", "full_length_m")})
if d:
    seg = main.conveyor_line.segments[d[1]]
    check(seg.merge_angle == '45' and seg.merge_side == 'RIGHT', f"diverter 45 RIGHT ({seg.merge_angle} {seg.merge_side})")
    check(tags(out)[2] > 5 and tags(out)[0] == 0, "main path appended AFTER the reversed branch's own points")
    seg.route_class = 0
    ctx.view_layer.update()
    ctx.scene.frame_set(1); a = [(n, p) for n, p, r in items(out)]
    ctx.scene.frame_set(9); b = [(n, p) for n, p, r in items(out)]
    print("out items f1:", [(n[:4], tuple(round(c, 2) for c in p)) for n, p in a][:4]); print("out items f9:", [(n[:4], tuple(round(c, 2) for c in p)) for n, p in b][:4])
    on_line = [p for n, p in b if p.x > 0.5]
    check(len(on_line) > 0, f"routed goods ride the outfeed line ({len(on_line)} on it)")
    # goods on the outfeed move AWAY from the main (toward the line's start at (2.5,7)): x increases over time
    def far(lst): return sorted(p.x for n, p in lst if p.x > 0.4)
    check(far(b) and far(a) and max(far(b)) >= max(far(a)) - 1e-6, "outfeed goods travel away from the main (reversed flow)")
    check(all(n.startswith("Cart") for n, p in b if p.x > 0.5) , "only the routed class rides the outfeed")

# ---------- B. reversed feeder: curve START at the main, goods leave at the start -> MERGE
fin = make((0.5, 2.0, 0), math.radians(-135), 3000, "In", reverse=True)
j = dj.docked_junction(ctx, fin)
check(j is not None, "reversed line docked by its start as a FEEDER (merge)")
print("main:", segs(main)); print("in tags:", tags(fin), "keys", {k: fin.conveyor_line.get(k) for k in ("continue_target", "continue_from", "continue_extra_m", "own_length_m", "full_length_m")})
if j:
    seg = main.conveyor_line.segments[j[1]]
    check(seg.merge_angle == '45' and seg.merge_side == 'RIGHT', f"merge 45 RIGHT ({seg.merge_angle} {seg.merge_side})")
    check(tags(fin)[0] > 5 and tags(fin)[2] == 0, "main path prepended BEFORE the reversed feeder's own points")
    tree = stream.tree_for(ctx, main)
    print("tree:", {n: (round(m.offset, 3), m.owner, m.mask) for n, m in tree.members.items()}, "K", tree.sources, "T", round(tree.length, 2))
    check(tree.members["In"].owner >= 1 and inp(fin, "Stream Flip") and not inp(main, "Stream Flip"), "feeder owns slots, stream flipped on the reversed line")
    worst = 9.0
    for f in (1, 9, 17, 25, 33):
        ctx.scene.frame_set(f)
        ys = sorted(p.y for n, p, r in items(main) + items(fin) + items(out) if abs(p.x) < 0.05 and 3.0 < p.y < 9.5)
        for y0, y1 in zip(ys, ys[1:]): worst = min(worst, y1 - y0)
    check(worst >= inp(main, "Spacing") - 0.02, f"no overlap on the main with a reversed feeder (min gap {worst:.3f} vs spacing {inp(main, 'Spacing'):.3f})")
    ctx.scene.frame_set(1); a = [p for n, p, r in items(fin) if p.x > 0.3]
    ctx.scene.frame_set(9); b = [p for n, p, r in items(fin) if p.x > 0.3]
    check(a and b and min(p.x for p in b) <= min(p.x for p in a) + 1e-6, "feeder goods travel toward the main (reversed flow)")
    yaws = [math.degrees(r) for n, p, r in items(fin) if p.x > 0.6]
    check(yaws and all(abs(dj._wrap(math.radians(y) - math.radians(45))) < math.radians(2) for y in yaws), f"items face their travel direction on the reversed feeder ({[round(y) for y in yaws][:3]})")
    # toggling reverse off: the goods now LEAVE the main at this line's start -> the dock is re-evaluated flow-wise
    # (2.6): the merge junction goes and a diverter takes its place
    fin.conveyor_line.reverse = False; ctx.view_layer.update()
    check(dj.docked_junction(ctx, fin) is None and dj.docked_diverter(ctx, fin) is not None, "flipping direction re-evaluates the dock (the merge becomes a diverter)")
    check(all(s.kind != 'MODULE' or s.module_kind != 'MERGE' or s.merge_source != "In" for s in main.conveyor_line.segments), "old merge junction removed")
    fin.conveyor_line.reverse = True; ctx.view_layer.update()
    check(dj.docked_junction(ctx, fin) is not None, "flipping back re-docks as a feeder")

# ---------- C. reversed MAIN with a forward feeder: wedge and continuation follow the main's flow (-y)
main2 = make((20, 0, 0), 0.0, 10000, "Main2", reverse=True)
f2 = make((22.5, 8.0, 0), math.radians(135), 3000, "F2")
j2 = dj.docked_junction(ctx, f2)
check(j2 is not None, "forward feeder docks onto a REVERSED main")
print("main2:", segs(main2))
if j2:
    seg = main2.conveyor_line.segments[j2[1]]
    from bl_ext.user_default.conveyor_system.operators.build_line import merge_layout_for
    lay = merge_layout_for(seg, main2.conveyor_line, ctx.scene)
    fy = list(lay.faces.values())[0][1]
    check(fy > lay.length_m / 2.0 - 1e-6, f"merge wedge on a reversed main opens upstream in geometry (face y {fy:.2f} of {lay.length_m:.2f})")
    ctx.scene.frame_set(1); a = [p for n, p, r in items(f2) if abs(p.x - 20) < 0.05]
    ctx.scene.frame_set(9); b = [p for n, p, r in items(f2) if abs(p.x - 20) < 0.05]
    check(a and b and min(p.y for p in b) <= min(p.y for p in a) + 1e-6, "feeder goods continue down the reversed main toward -y")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
