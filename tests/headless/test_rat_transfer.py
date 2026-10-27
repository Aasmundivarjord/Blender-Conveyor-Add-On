"""2.18.0 (Åsmund, 2026-10-15): a right-angle transfer takes the width of the
conveyor on each side (a takeaway after a transfer that turns, a standalone
transfer unit) and the goods stop on it: arrive, stop, lift, out sideways,
set down, carry on -- the same on every line of the stream, nothing written
per frame.
Blender -b --python tests/headless/test_rat_transfer.py"""
import math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line, resolve_width_mm
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, stream
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
from bl_ext.user_default.conveyor_system.model import transfer_motion as TM, transfer_parts as TP
ctx = bpy.context; scene = ctx.scene; fails = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
def settle():
    for _ in range(4):
        ctx.view_layer.update(); dj.run_sync(scene)
    ctx.view_layer.update()
def activate(o):
    for x in ctx.view_layer.objects: x.select_set(False)
    o.select_set(True); ctx.view_layer.objects.active = o
def line(name, loc, pieces, width='iso_500', populate=False, reverse=False):
    o = create_line(ctx, Vector(loc), 0.0); o.name = name
    with suspended_rebuild():
        s = o.conveyor_line; s.width_preset = width
        for k, p in enumerate(pieces):
            seg = s.segments[0] if k == 0 else s.segments.add()
            if p[0] == 'S':
                seg.kind = 'STRAIGHT'; seg["length_mm"] = float(p[1])
            else:
                seg.kind = 'MODULE'; seg.module_kind = 'RAT'; seg.module_exit = p[1]
        s.populate = populate; s.speed_m_s = 0.5; s.reverse = reverse
    build_line(ctx, o); settle()
    return o
def takeaway(o):
    activate(o); bpy.ops.conveyor.new_line_from_end(); settle()
    return ctx.view_layer.objects.active
def goods(o):
    dg = ctx.evaluated_depsgraph_get(); out = []
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.parent.original == o and i.object.name.startswith("Placeholder"):
            out.append(i.matrix_world.translation.copy())
    return out
try:
    # ---------------- A. widths
    n = line("Narrow", (0, 0, 0.8), [('S', 3000), ('R', 'LEFT')], width='iso_650')
    tk = takeaway(n); seg = n.conveyor_line.segments[1]
    tk.conveyor_line.width_preset = 'iso_1200'; settle()
    ex, ey, ez, _h = n.conveyor_line.end_pose
    check(abs(seg.rat_face_left_mm - 1240.0) < 0.6 and (tk.location - n.matrix_world @ Vector((ex, ey, ez))).length < 1e-4,
          f"a takeaway after a turning transfer: its exit side takes the takeaway's 1200 mm frame ({seg.rat_face_left_mm}) and stays joined")
    tk.conveyor_line.width_preset = 'iso_800'; settle()
    check(abs(seg.rat_face_left_mm - 840.0) < 0.6, f"and follows it to 800 mm ({seg.rat_face_left_mm})")
    bpy.data.objects.remove(tk); settle()
    check(seg.rat_face_left_mm == 0.0 and "rat_exit_from_tail" not in seg, "the takeaway deleted: the exit side is the line's own width again")
    f = line("Wide feeder", (10, 0, 0.8), [('S', 3000)], width='iso_1000')
    u = takeaway(f); u.name = "Unit"
    with suspended_rebuild():
        u.conveyor_line.width_preset = 'iso_500'
        s0 = u.conveyor_line.segments[0]; s0.kind = 'MODULE'; s0.module_kind = 'RAT'; s0.module_exit = 'STRAIGHT'
    build_line(ctx, u); settle()
    check(resolve_width_mm(u.conveyor_line) == 1000.0, f"a standalone transfer unit takes its feeder's width ({resolve_width_mm(u.conveyor_line)})")
    f.conveyor_line.width_preset = 'iso_1200'; settle()
    check(resolve_width_mm(u.conveyor_line) == 1200.0, "and follows it")
    lone = line("Lone unit", (20, 0, 0.8), [('R', 'STRAIGHT')], width='iso_500')
    t3 = takeaway(lone); t3.conveyor_line.width_preset = 'iso_800'; settle()
    check(resolve_width_mm(lone.conveyor_line) == 800.0, "a unit nothing feeds takes its takeaway's width")
    m = line("Main", (30, 0, 0.8), [('S', 3000), ('R', 'STRAIGHT'), ('S', 3000)], width='iso_500')
    r = bpy.ops.conveyor.new_line_at_junction(line_name=m.name, index=1, side='LEFT'); settle()
    br = ctx.view_layer.objects.active; br.conveyor_line.width_preset = 'iso_800'; settle()
    check(abs(m.conveyor_line.segments[1].rat_face_left_mm - 840.0) < 0.6, "a branch on a side still sets that side")
    m.conveyor_line.width_preset = 'iso_650'; settle()
    check(resolve_width_mm(m.conveyor_line) == 650.0 and abs(m.conveyor_line.segments[1].rat_face_left_mm - 840.0) < 0.6,
          "a transfer inside a longer line keeps the line's width on its own sides")
    check(dj.run_sync(scene) == 0, "settled: the pass writes nothing")
    # ---------------- B. the stop
    fps = scene.render.fps
    t = line("Turning", (0, 20, 0.8), [('S', 3000), ('R', 'LEFT'), ('S', 3000)], populate=True)
    tree = stream.tree_for(ctx, t)
    tech_hold = TM.hold_m(0.5, 'BELT')
    check(tree.transfers and abs(tree.transfers[0][8] - tech_hold) < 1e-6 and tree.transfers[0][10] is False,
          f"the transfer stops its goods ({tree.transfers[0][7:] if tree.transfers else None})")
    from bl_ext.user_default.conveyor_system.operators.populate import populate_item_footprint
    need = TM.min_pitch_m(populate_item_footprint(ctx, t), tree.transfer_ease, tech_hold)
    check(tree.actual_spacing >= need - 1e-6 and tree.extra_slots >= 1, f"the goods are far enough apart for the stop ({tree.actual_spacing:.3f} >= {need:.3f}), the stream runs on {tree.extra_slots} slot(s)")
    from bl_ext.user_default.conveyor_system.operators.build_line import rat_footprint_mm
    L = rat_footprint_mm(t.conveyor_line.segments[1], t.conveyor_line, scene) / 1000.0  # a corner: square to the line
    check(abs(L - 0.54) < 1e-6, f"a turning transfer is square to its 500 mm line: the frame width, 0.54 m ({L:.3f})")
    corner = Vector((0.0, 20.0 + 3.0 + L / 2.0))
    trace = []
    for fr in range(1, int(8 * fps)):
        scene.frame_set(fr)
        near = [p for p in goods(t) if (Vector((p.x, p.y)) - corner).length < 0.45]
        trace.append(min(near, key=lambda p: (Vector((p.x, p.y)) - corner).length) if near else None)
    standing = [fr for fr, p in enumerate(trace) if p is not None and (Vector((p.x, p.y)) - corner).length < 1e-3]
    runs, cur = [], []
    for fr in standing:
        if cur and fr != cur[-1] + 1:
            runs.append(cur); cur = []
        cur.append(fr)
    if cur: runs.append(cur)
    longest = max((len(r_) for r_ in runs), default=0)
    want = (TM.timing('BELT')[0] + TM.timing('BELT')[1]) * fps
    check(longest >= want - 2, f"an item stands on the transfer's centre for {longest} frames (the stand is {want:.1f})")
    if runs:
        run = max(runs, key=len)
        z0, z1 = trace[run[0]].z, trace[run[-1]].z
        check(abs((z1 - z0) - TP.BELT_LIFT) < 0.002, f"the belts lift it while it stands ({(z1 - z0) * 1000:.1f} mm)")
        after = [trace[k] for k in range(run[-1] + 1, min(run[-1] + 8, len(trace))) if trace[k] is not None]
        check(after and all(abs(p.y - corner.y) < 1e-3 and p.x < -1e-4 for p in after) and abs(after[0].z - z1) < 1e-3,
              "then it goes out sideways, still up, without turning back into the line")
    # reversed: comes in sideways on raised belts, set down standing
    rv = line("Reversed", (10, 20, 0.8), [('S', 3000), ('R', 'LEFT'), ('S', 3000)], populate=True, reverse=True)
    rt = stream.tree_for(ctx, rv)
    check(rt.transfers and rt.transfers[0][10] is True, "on a reversed line the goods come in on raised belts and are set down standing")
    corner_r = Vector((10.0, 20.0 + 3.0 + L / 2.0))
    zs = []
    for fr in range(1, int(8 * fps)):
        scene.frame_set(fr)
        at = [p for p in goods(rv) if (Vector((p.x, p.y)) - corner_r).length < 1e-3]
        if at:
            zs.append(at[0].z)
    check(len(zs) >= want - 2 and zs[0] - zs[-1] > TP.BELT_LIFT - 0.002, f"standing on the centre it is set down ({(zs[0] - zs[-1]) * 1000 if zs else 0:.1f} mm over {len(zs)} frames)")
    # a line without a transfer keeps its pitch
    plain = line("Plain", (20, 20, 0.8), [('S', 6000)], populate=True)
    pt = stream.tree_for(ctx, plain)
    check(not pt.transfers and pt.extra_slots == 0 and pt.actual_spacing < need, f"a line without a transfer keeps its pitch ({pt.actual_spacing:.3f})")
    check(dj.run_sync(scene) == 0, "the animation writes nothing per frame (R5)")
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
