"""2.20.0 (Åsmund, 2026-10-15: a stop at EVERY sideways transfer): at a 90
degree pop-up divert, a 90 degree pop-up merge and a branch off a straight
right-angle transfer the goods stop on the centre and stand while the belts
lift them (a divert) or set them down (a merge), with the 2.18 timings;
one item, drawn once; nothing written per frame.
Blender -b --python tests/headless/test_side_transfers.py"""
import bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, stream
from bl_ext.user_default.conveyor_system.operators.populate import populate_item_footprint
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
from bl_ext.user_default.conveyor_system.model import transfer_motion as TM, transfer_parts as TP
ctx = bpy.context; scene = ctx.scene; fails = []
fps = scene.render.fps
STAND = (TM.timing('BELT')[0] + TM.timing('BELT')[1]) * fps
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
def settle():
    for _ in range(4):
        ctx.view_layer.update(); dj.run_sync(scene)
    ctx.view_layer.update()
def main_line(name, x, module, exit_='STRAIGHT'):
    o = create_line(ctx, Vector((x, 0, 0.8)), 0.0); o.name = name
    with suspended_rebuild():
        s = o.conveyor_line
        s.segments[0]["length_mm"] = 3000.0
        m = s.segments.add(); m.kind = 'MODULE'; m.module_kind = module
        if module == 'RAT':
            m.module_exit = exit_
        else:
            m.merge_angle = '90'
        t = s.segments.add(); t.kind = 'STRAIGHT'; t["length_mm"] = 3000.0
        s.populate = True; s.speed_m_s = 0.5
    build_line(ctx, o); settle()
    return o
def goods(objs):
    dg = ctx.evaluated_depsgraph_get(); out = []
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.parent.original in objs and i.object.name.startswith("Placeholder"):
            out.append(i.matrix_world.translation.copy())
    return out
def stands_at(objs, spot, frames):
    """Per frame: how many goods stand within 1 mm of `spot` (xy) and the z of the first."""
    rows = []
    for fr in frames:
        scene.frame_set(fr)
        at = [p for p in goods(objs) if (Vector((p.x, p.y)) - spot).length < 1e-3]
        rows.append((len(at), at[0].z if at else None))
    return rows
def longest_run(rows):
    best, cur, start, best_rows = 0, 0, None, []
    for k, (n, z) in enumerate(rows + [(0, None)]):
        if n:
            cur += 1
        else:
            if cur > best:
                best, best_rows = cur, rows[k - cur:k]
            cur = 0
    return best, best_rows
try:
    for label, module, x in (("pop-up divert", 'DIVERTER', 0.0), ("straight RAT branch", 'RAT', 10.0)):
        m = main_line(label, x, module)
        bpy.ops.conveyor.new_line_at_junction(line_name=m.name, index=1, side='LEFT'); settle()
        br = ctx.view_layer.objects.active
        tree = stream.tree_for(ctx, m)
        stops = [t for t in tree.transfers if t[8] > 0.0]
        check(len(stops) == 1 and stops[0][10] is False and abs(stops[0][8] - TM.hold_m(0.5, 'BELT')) < 1e-6,
              f"{label}: the diverted goods stop ({[(round(t[7], 4), round(t[8], 3), t[10]) for t in stops]})")
        need = TM.min_pitch_m(populate_item_footprint(ctx, m), tree.transfer_ease, TM.hold_m(0.5, 'BELT'))
        check(tree.actual_spacing >= need - 1e-6, f"{label}: the goods are far enough apart for it ({tree.actual_spacing:.3f} >= {need:.3f})")
        centre = m.conveyor_line.segments[1].length_mm / 2000.0 + 3.0 if module == 'RAT' else 3.0 + m.conveyor_line.segments[1].length_mm / 2000.0
        rows = stands_at({m, br}, Vector((x, centre)), range(1, int(10 * fps)))
        n, run = longest_run(rows)
        check(n >= STAND - 2, f"{label}: an item stands on the centre for {n} frames (the stand is {STAND:.0f})")
        check(run and max(r[0] for r in run) == 1, f"{label}: drawn once while it stands ({sorted({r[0] for r in run})})")
        zs = [r[1] for r in run if r[1] is not None]
        check(zs and abs((zs[-1] - zs[0]) - TP.BELT_LIFT) < 0.002, f"{label}: lifted while it stands ({(zs[-1] - zs[0]) * 1000 if zs else 0:.1f} mm)")
    # a pop-up merge: the feeder's goods come in raised and are set down standing
    m = main_line("pop-up merge", 20.0, 'MERGE')
    bpy.ops.conveyor.new_line_at_junction(line_name=m.name, index=1, side='LEFT'); settle()
    fd = ctx.view_layer.objects.active
    fd.conveyor_line.populate = True; settle()
    tree = stream.tree_for(ctx, m)
    stops = [t for t in tree.transfers if t[8] > 0.0]
    check(len(stops) == 1 and stops[0][10] is True, f"pop-up merge: the feeder's goods are set down standing ({[(round(t[7], 4), t[10]) for t in stops]})")
    centre = 3.0 + m.conveyor_line.segments[1].length_mm / 2000.0
    rows = stands_at({m, fd}, Vector((20.0, centre)), range(1, int(12 * fps)))
    n, run = longest_run(rows)
    zs = [r[1] for r in run if r[1] is not None]
    check(n >= STAND - 2 and zs and (zs[0] - zs[-1]) > TP.BELT_LIFT - 0.002,
          f"pop-up merge: stands {n} frames on the main line's centre and is set down ({(zs[0] - zs[-1]) * 1000 if zs else 0:.1f} mm)")
    check(dj.run_sync(scene) == 0, "the animation writes nothing per frame (R5)")
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
