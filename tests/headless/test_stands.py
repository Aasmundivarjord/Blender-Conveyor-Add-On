"""2.14.0 (round 7): every line type can hang from the ceiling (a trapeze
hanger at each stand); stands placed from one plan (model/legs.plan_stands)
that the viewport buttons share; a stand taken out stays out (kept on its
piece, re-found after re-spacing) until it is put back; 2.13 files keep their
pouch Supports.
Blender -b --python tests/headless/test_stands.py"""
import math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, stands as stands_op
from bl_ext.user_default.conveyor_system.props import line_settings as LS
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
from bl_ext.user_default.conveyor_system.model import legs as legs_model
ctx = bpy.context; scene = ctx.scene; fails = []
SIZE = 0.06
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
def insts(obj, pred):
    """(position, dims) of the instances under `obj`, read DURING the iteration."""
    dg = ctx.evaluated_depsgraph_get(); out = []
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.parent.original == obj:
            d = tuple(round(c, 3) for c in i.object.dimensions)
            if pred(d, i.object.name):
                out.append((i.matrix_world.translation.copy(), d))
    return out
def feet(obj):
    return [p for p, d in insts(obj, lambda d, n: abs(d[0] - 0.144) < 0.01 and abs(d[1] - 0.144) < 0.01 and abs(d[2] - 0.012) < 0.005)]
def rods(obj):
    return insts(obj, lambda d, n: abs(d[0] - 0.016) < 0.003 and abs(d[1] - 0.016) < 0.003 and d[2] > 0.05)
def stand_ys(obj):
    return sorted({round(p.y, 3) for p in feet(obj)})
def make(name, loc, pieces, ctype='gravity_roller'):
    o = create_line(ctx, Vector((100.0, 100.0, 0.0)), 0.0, conveyor_type=ctype); o.name = name; o.location = Vector(loc)
    with suspended_rebuild():
        s = o.conveyor_line
        for k, piece in enumerate(pieces):
            kind, length_mm = piece if isinstance(piece, tuple) else ('STRAIGHT', piece)
            seg = s.segments[0] if k == 0 else s.segments.add()
            seg.kind = kind
            if kind == 'STRAIGHT':
                seg["length_mm"] = float(length_mm)
    ctx.view_layer.update(); build_line(ctx, o); ctx.view_layer.update()
    return o
def rebuild(o):
    build_line(ctx, o); ctx.view_layer.update()
def arcs(o, key="stand_arcs"):
    return [float(v) for v in (o.conveyor_line.get(key, []) or [])]
try:
    # ---- A. one plan: the stored stands are where the trees put them
    a = make("Plan", (0.0, 0.0, 1.0), [12000])
    sa = arcs(a); pts = [float(v) for v in a.conveyor_line.get("stand_points", [])]
    check(len(sa) == math.floor(12.0 / 1.5) + 2 and abs(sa[0] - SIZE / 2) < 1e-6 and abs(sa[-1] - (12.0 - SIZE / 2)) < 1e-6 and len(pts) == 3 * len(sa),
          f"12 m: {len(sa)} stands flush with both ends, a point for each")
    ys = stand_ys(a); planned = sorted(round(a.location.y + pts[3 * k + 1], 3) for k in range(len(sa)))
    check(len(feet(a)) == 2 * len(sa) and ys == planned, "the trees put a stand at every planned point and nowhere else")
    # ---- B. take one out: it goes, nothing else moves, the span is reported
    target = sa[4]
    r = bpy.ops.conveyor.stand_remove(line=a.name, arc=target); ctx.view_layer.update()
    sb = arcs(a); out = arcs(a, "stand_removed_arcs")
    check(r == {'FINISHED'} and len(sb) == len(sa) - 1 and out == [target] and sorted(sb + out) == sa, f"one stand out, the rest where they were ({out})")
    check(len(feet(a)) == 2 * len(sb) and round(a.location.y + target, 3) not in stand_ys(a), "the trees drop it too")
    check(list(a.conveyor_line.segments[0].get(stands_op.SEG_KEY, [])) == [round(target, 4)] and len(stands_op.stand_records(a)) == 1,
          "kept on its piece, metres from the piece's start")
    check(abs(float(a.conveyor_line["leg_free_span_m"]) - (sa[5] - sa[3] - SIZE)) < 1e-6, f"the clear span is reported ({float(a.conveyor_line['leg_free_span_m']):.2f} m)")
    # ---- C. new spacing: the spot stays clear
    a.conveyor_line.support_spacing_m = 1.2; ctx.view_layer.update()
    fresh = legs_model.plan_stands([(0.0, 12.0, False, False)], a.conveyor_line.support_spacing_m, SIZE)[0]
    check(len(fresh) == math.floor(12.0 / 1.2) + 2, f"1.2 m as typed: {len(fresh)} stands (single precision does not drop one)")
    nearest = min(fresh, key=lambda s: abs(s - target)); out = arcs(a, "stand_removed_arcs")
    check(len(out) == 1 and abs(out[0] - nearest) < 1e-6 and len(arcs(a)) == len(fresh) - 1, f"spaced at 1.2 m the stand nearest the spot is out ({out}, spot {target:.2f})")
    # ---- D. put it back
    refs = list(a.conveyor_line.get("stand_removed_refs", []))
    r = bpy.ops.conveyor.stand_restore(line=a.name, piece=refs[0], index=refs[1]); ctx.view_layer.update()
    check(r == {'FINISHED'} and not arcs(a, "stand_removed_arcs") and len(arcs(a)) == len(fresh) and not stands_op.stand_records(a)
          and stands_op.SEG_KEY not in a.conveyor_line.segments[0], "restored: every stand back, nothing kept")
    bpy.ops.conveyor.stand_remove(line=a.name, arc=arcs(a)[2]); bpy.ops.conveyor.stand_remove(line=a.name, arc=arcs(a)[6])
    r = bpy.ops.conveyor.stands_restore_all(line=a.name); ctx.view_layer.update()
    check(r == {'FINISHED'} and len(arcs(a)) == len(fresh) and not stands_op.stand_records(a), "Restore all puts back every stand")
    # ---- D2. a + in a gap adds a stand there; its - takes it away again (2.26.3)
    gaps = arcs(a, "stand_gap_arcs")
    check(len(gaps) == len(fresh) - 1 and len(a.conveyor_line.get("stand_gap_points", [])) == 3 * len(gaps),
          f"a + in every gap between two stands ({len(gaps)} gaps, {len(fresh)} stands)")
    spot = gaps[3]
    r = bpy.ops.conveyor.stand_add(line=a.name, arc=spot); ctx.view_layer.update()
    now = arcs(a)
    check(r == {'FINISHED'} and len(now) == len(fresh) + 1 and min(abs(s - spot) for s in now) < 1e-4
          and len(stand_ys(a)) == len(now), f"added: a stand at {spot:.2f} m, feet and all ({len(now)} stands)")
    from bl_ext.user_default.conveyor_system.model.legs import ADD_GAP_M
    want = sum(1 for x, y in zip(now, now[1:]) if y - x >= ADD_GAP_M - 1e-9)
    check(len(arcs(a, "stand_gap_arcs")) == want and min(abs(g - spot) for g in arcs(a, "stand_gap_arcs")) > 0.1,
          f"the old gap's + is gone; a half gets one only when it is at least {ADD_GAP_M} m long")
    r = bpy.ops.conveyor.stand_remove(line=a.name, arc=spot); ctx.view_layer.update()
    check(r == {'FINISHED'} and len(arcs(a)) == len(fresh) and not stands_op.stand_records(a)
          and not stands_op.stand_records(a, stands_op.ADD_KEY), "its - drops the added stand: no record of either kind left")
    bpy.ops.conveyor.stand_add(line=a.name, arc=gaps[0]); bpy.ops.conveyor.stand_remove(line=a.name, arc=arcs(a)[5])
    r = bpy.ops.conveyor.stands_restore_all(line=a.name); ctx.view_layer.update()
    check(r == {'FINISHED'} and len(arcs(a)) == len(fresh) and not stands_op.stand_records(a) and not stands_op.stand_records(a, stands_op.ADD_KEY),
          "Reset: the plan again, nothing added, nothing taken out")
    # ---- E. the removal travels with its piece
    e = make("Pieces", (10.0, 0.0, 1.0), [6000, 6000])
    se = arcs(e); target = min(se, key=lambda s: abs(s - 9.0))
    bpy.ops.conveyor.stand_remove(line=e.name, arc=target); ctx.view_layer.update()
    off = list(e.conveyor_line.segments[1].get(stands_op.SEG_KEY, []))
    check(len(off) == 1 and abs(off[0] - (target - 6.0)) < 1e-3, f"on the second piece, {off} m from its start")
    with suspended_rebuild():
        seg = e.conveyor_line.segments.add(); seg.kind = 'STRAIGHT'; seg["length_mm"] = 2000.0
        e.conveyor_line.segments.move(len(e.conveyor_line.segments) - 1, 0)
    rebuild(e)
    out = arcs(e, "stand_removed_arcs"); spot = 2.0 + 6.0 + off[0]
    check(list(e.conveyor_line.segments[2].get(stands_op.SEG_KEY, [])) == off and len(out) == 1 and abs(out[0] - spot) <= 0.75 + 1e-6,
          f"a piece put in front: the record moved with its piece, the stand nearest its spot is out ({out}, spot {spot:.2f})")
    with suspended_rebuild():
        e.conveyor_line.segments.remove(2)
    rebuild(e)
    check(not arcs(e, "stand_removed_arcs") and not stands_op.stand_records(e), "its piece deleted: the record goes with it")
    # ---- F. spirals carry no stands; leg-free pieces none either
    f = make("Spiral", (20.0, 0.0, 1.0), [3000, ('SPIRAL', 0), 3000])
    starts = [float(v) for v in f.conveyor_line.get("piece_starts", [])]
    inside = [s for s in arcs(f) if starts[1] + 1e-6 < s < starts[2] - 1e-6]
    check(len(starts) == 3 and not inside and arcs(f), f"no stands on the spiral ({len(arcs(f))} elsewhere)")
    check(float(f.conveyor_line.get("leg_free_span_m", 0.0)) == 0.0, "the spiral's drum carries it: no span-without-support alert")
    # ---- G. Ceiling: every line type hangs from the ceiling
    scene.conveyor_settings.ceiling_z = 5.0
    for k, ctype in enumerate(("gravity_roller", "belt", "chain", "omni")):
        g = make(f"Hung {ctype}", (40.0 + 6.0 * k, 0.0, 2.0), [4000], ctype=ctype)
        n_floor = len(feet(g)); n_stands = len(arcs(g))
        g.conveyor_line.support_mount = 'CEILING'; ctx.view_layer.update()
        hung = rods(g); tops = sorted({round(p.z + d[2] / 2.0, 2) for p, d in hung})
        check(n_floor == 2 * n_stands and not feet(g) and len(hung) == 2 * n_stands and tops == [5.0],
              f"{ctype}: {n_stands} stands on the floor, then {len(hung)} drop rods up to the Ceiling level ({tops})")
        bottoms = sorted({round(p.z - d[2] / 2.0, 2) for p, d in hung})
        check(len(bottoms) == 1 and 1.6 < bottoms[0] < 2.0, f"{ctype}: the rods come down to the cross member under the frame (z {bottoms})")
    h = bpy.data.objects["Hung gravity_roller"]
    bpy.ops.mesh.primitive_plane_add(size=6.0, location=(40.0, 2.0, 4.0)); ctx.view_layer.objects.active.name = "Deck over the line"
    ctx.view_layer.update(); dj.run_sync(scene); rebuild(h)
    tops = sorted({round(p.z + d[2] / 2.0, 2) for p, d in rods(h)})
    check(tops == [4.0], f"a surface above the line is the ceiling there (rods end at the deck: {tops})")
    bpy.ops.conveyor.stand_remove(line=h.name, arc=arcs(h)[1]); ctx.view_layer.update()
    check(len(rods(h)) == 2 * len(arcs(h)) and len(arcs(h, "stand_removed_arcs")) == 1, "a hanger can be taken out like a stand")
    # ---- H. the pouch sorter's portals come from the same plan
    p = make("Pouches", (80.0, 0.0, 2.5), [5000], ctype='pouch_sorter')
    n0 = len(feet(p)); bpy.ops.conveyor.stand_remove(line=p.name, arc=arcs(p)[2]); ctx.view_layer.update()
    check(n0 == 2 * (len(arcs(p)) + 1) and len(feet(p)) == n0 - 2, f"a pouch portal taken out ({n0 // 2} -> {len(feet(p)) // 2})")
    # ---- I. a 2.13 file: the pouch sorter's Supports carry over
    m = make("Migrated", (90.0, 0.0, 2.5), [3000], ctype='pouch_sorter')
    with suspended_rebuild():
        m.conveyor_line["pouch_mount"] = 1
        if "support_mount" in m.conveyor_line:
            del m.conveyor_line["support_mount"]
    rebuild(m)
    check(m.conveyor_line.support_mount == 'CEILING' and rods(m), "pouch_mount = Ceiling from 2.13 reads as Supports: Ceiling")
    check("support_mount" in LS.SHARED_SETTINGS and "support_mount" not in LS._SAME_TYPE_ONLY, "Supports is a multi-edit setting across line types")
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
