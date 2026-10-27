"""2.26.1: a right-angle transfer with several lines docked on it (lines on
both sides, a corner with lines on its far face and its other side, side
feeders). One stand per joint, the transfer's own; lines on a straight
transfer's sides rest on its frame, lines on a corner's free edges carry
them; every item is drawn by one line at a time; the goods going straight
through a corner neither stop nor lift; goods leave and enter a side face
lifted only on the deck.
Blender -b --python tests/headless/test_rat_docks.py"""
import math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, stream
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
from bl_ext.user_default.conveyor_system.model import transfer_motion as TM, transfer_parts as TP
ctx = bpy.context; scene = ctx.scene; fails = []
fps = scene.render.fps


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)


def settle():
    for _ in range(5):
        ctx.view_layer.update(); dj.run_sync(scene)
    ctx.view_layer.update()


def activate(o):
    for x in ctx.view_layer.objects: x.select_set(False)
    o.select_set(True); ctx.view_layer.objects.active = o


def line(name, loc, pieces):
    o = create_line(ctx, Vector(loc), 0.0); o.name = name
    with suspended_rebuild():
        s = o.conveyor_line; s.width_preset = 'iso_500'
        for k, p in enumerate(pieces):
            seg = s.segments[0] if k == 0 else s.segments.add()
            if p[0] == 'S':
                seg.kind = 'STRAIGHT'; seg["length_mm"] = float(p[1])
            else:
                seg.kind = 'MODULE'; seg.module_kind = 'RAT'; seg.module_exit = p[1]
        s.populate = True; s.speed_m_s = 0.5
    build_line(ctx, o); settle()
    return o


def at_face(target, index, side, name, goods_in=False):
    before = set(bpy.data.objects)
    bpy.ops.conveyor.new_line_at_junction(line_name=target.name, index=index, side=side); settle()
    o = next(x for x in bpy.data.objects if x not in before and x.type == 'CURVES')
    o.name = name
    if goods_in:
        o.conveyor_line.reverse = True
    o.conveyor_line.populate = True
    settle()
    return o


def stands_near(c, r):
    out = []
    for o in bpy.data.objects:
        if o.type != 'CURVES' or not o.conveyor_line.is_conveyor_line:
            continue
        p = list(o.conveyor_line.get("stand_points", []))
        for k in range(0, len(p), 3):
            w = o.matrix_world @ Vector(p[k:k + 3])
            if (Vector((w.x, w.y)) - Vector(c)).length < r:
                out.append((o.name, w.x, w.y))
    return out


def all_goods():
    dg = ctx.evaluated_depsgraph_get(); out = []
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.object.name.startswith("Placeholder"):
            out.append((i.parent.original.name, i.matrix_world.translation.copy()))
    return out


def trace(seconds):
    rows = []
    for fr in range(1, int(seconds * fps)):
        scene.frame_set(fr)
        rows.append(all_goods())
    return rows


try:
    # ---------------- A. the legs
    m = line("Main", (0, 0, 0.8), [('S', 3000), ('R', 'STRAIGHT'), ('S', 3000)])
    bl = at_face(m, 1, 'LEFT', "Left out")
    br = at_face(m, 1, 'RIGHT', "Right out")
    rat_c = (0.0, 3.45)
    near = stands_near(rat_c, 1.0)
    mine = sorted(round(y, 3) for n, _x, y in near if n == "Main")
    check(mine == [3.03, 3.87] and not [s for s in near if s[0] != "Main"],
          f"a transfer in a line, lines on both sides: one stand at each joint, the transfer's; the side lines rest on its frame ({near})")
    ys = sorted(y for n, _x, y in [(n, x, y) for n, x, y in stands_near((0.0, 3.5), 9.0) if n == "Main"])
    check(all(b - a > 0.3 for a, b in zip(ys, ys[1:])), f"no two stands a post apart along the line ({[round(y, 2) for y in ys]})")
    check(m.conveyor_line.get("leg_free_span_m", 0.0) == 0.0, "and no span beyond the spacing: the transfer's stands carry the straights")
    for side_line, sx in ((bl, -1.0), (br, 1.0)):
        xs = sorted(abs(x) for n, x, _y in stands_near((0.0, 3.45), 9.0) if n == side_line.name)
        check(xs and xs[0] > 0.6, f"{side_line.name}: its first stand away from the transfer ({[round(x, 2) for x in xs]})")
    c = line("Corner", (20, 0, 0.8), [('S', 3000), ('R', 'LEFT')])
    activate(c); bpy.ops.conveyor.new_line_from_end(); settle()
    take = ctx.view_layer.objects.active; take.name = "Takeaway"; take.conveyor_line.populate = True
    far = at_face(c, 1, 'END', "Far out")
    other = at_face(c, 1, 'RIGHT', "Other out")
    corner = (20.0, 3.27)
    near = stands_near(corner, 0.9)
    names = sorted({n for n, _x, _y in near})
    check([round(y, 3) for n, _x, y in near if n == "Corner"] == [3.03],
          f"a corner: one stand at the joint before it, the transfer's ({near})")
    check("Far out" in names and "Other out" in names and "Takeaway" in names,
          f"the lines on a corner's far face and other side keep their stand: they carry those edges ({names})")
    plain = line("Plain", (40, 0, 0.8), [('S', 6000)])
    check(len(plain.conveyor_line.get("stand_arcs", [])) == int(6.0 / 1.5) + 2, "a line without a transfer keeps its stands")

    # ---------------- B. a corner with three ways out
    rows = trace(10.0)
    rest = 0.8
    dup = []
    for fr, goods in enumerate(rows, 1):
        for a in range(len(goods)):
            for b in range(a + 1, len(goods)):
                if (goods[a][1] - goods[b][1]).length < 0.05:
                    dup.append((fr, goods[a][0], goods[b][0]))
    check(not dup, f"every item is drawn by one line at a time (three lines drew the item standing on a corner: {dup[:4]})")
    far_z = [p.z for g in rows for n, p in g if n == "Far out"]
    check(far_z and max(far_z) < rest + 5e-4, f"the goods going straight through the corner are never lifted ({max(far_z) if far_z else None})")
    stood = 0
    for g0, g1 in zip(rows, rows[1:]):
        for n, p in g1:
            if n == "Far out" and any(n0 == "Far out" and (p0 - p).length < 1e-5 for n0, p0 in g0):
                stood += 1
    check(stood == 0, f"and never stand still ({stood} frames)")
    other_z = [p.z for g in rows for n, p in g if n == "Other out"]
    check(other_z and abs(max(other_z) - rest - TP.BELT_LIFT) < 5e-4, "the goods leaving by the other side still stop and lift")
    arr_far, arr_other = stream.arrivals_record(ctx, far), stream.arrivals_record(ctx, other)
    tree = stream.tree_for(ctx, c)
    lag = TM.lag_m(tree.transfer_ease, TM.hold_m(tree.speed, 'BELT')) / tree.speed
    if arr_far and arr_other:
        d = arr_other["delay_s"] - arr_far["delay_s"]
        check(abs(d - lag) < 2e-3, f"R22.4: the straight-through goods arrive without the corner's stand ({d:.3f} s vs {lag:.3f} s)")
    else:
        check(False, f"both ways publish arrivals ({arr_far}, {arr_other})")

    # ---------------- C. side faces: lifted only on the deck
    face = 0.25 + 0.02  # half the 500 mm deck plus the side plate
    hi = [(n, round(p.x, 3), round(p.z, 4)) for g in rows for n, p in g
          if n in ("Left out", "Right out") and abs(p.x) > face + 0.005 and p.z > rest + 5e-4]
    check(not hi, f"a branch's goods are set down by the face, not over its rollers ({hi[:4]})")
    m5 = line("Main in", (60, 0, 0.8), [('S', 3000), ('R', 'STRAIGHT'), ('S', 3000)])
    fl = at_face(m5, 1, 'LEFT', "Left in", goods_in=True)
    fr_ = at_face(m5, 1, 'RIGHT', "Right in", goods_in=True)
    rows5 = trace(10.0)
    early = [(n, round(p.x - 60.0, 3), round(p.z, 4)) for g in rows5 for n, p in g
             if n in ("Left in", "Right in") and abs(p.x - 60.0) > face + 0.005 and abs(p.y - 3.45) < 1e-3 and p.z > rest + 5e-4]
    lifted = [p.z for g in rows5 for n, p in g if n in ("Left in", "Right in")]
    check(not early and lifted and max(lifted) > rest + TP.BELT_LIFT - 5e-4,
          f"a side feeder's goods rise as they cross the face, not on the feeder ({early[:4]})")
    check(dj.run_sync(scene) == 0, "the animation writes nothing per frame (R5)")
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
