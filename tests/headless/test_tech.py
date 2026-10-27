import math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line, MODIFIER_NAME, resolve_junction_tech
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, stream
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
from bl_ext.user_default.conveyor_system.model import spine as spine_io
ctx = bpy.context; fails = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
def insts(obj, pred, near=None, radius=1.2):
    dg = ctx.evaluated_depsgraph_get(); out = []
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.parent.original == obj:
            dims = tuple(round(c, 3) for c in i.object.dimensions)
            p = i.matrix_world.translation
            if pred(dims) and (near is None or (p - near).length < radius):
                out.append((p.copy(), i.matrix_world.to_euler().z))
    return out
def items(obj):
    dg = ctx.evaluated_depsgraph_get(); out = []
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.parent.original == obj and "Placeholder" in i.object.name:
            out.append((i.matrix_world.translation.copy(), i.matrix_world.to_euler().z))
    return out
def make(loc, heading, segs, name, ctype='gravity_roller', populate=True, reverse=False, lane_mm=0.0, tp=0):
    o = create_line(ctx, Vector((100, 100, 0)), heading); o.name = name; o.location = Vector(loc)
    with suspended_rebuild():
        s = o.conveyor_line; s.conveyor_type = ctype
        for i, spec in enumerate(segs):
            seg = s.segments[0] if i == 0 else s.segments.add()
            seg.kind = spec[0]
            if spec[0] == 'STRAIGHT': seg["length_mm"] = float(spec[1])
            elif spec[0] == 'MODULE':
                seg.module_kind = spec[1]
                if spec[1] == 'ARB':
                    seg.arb_function = spec[2]; seg.arb_pivot = spec[3]; seg["length_mm"] = 1500.0
                if spec[1] == 'BUFFER': seg["length_mm"] = 3000.0
        s.populate = populate; s.speed_m_s = 0.5; s.reverse = reverse; s.populate_lane_mm = lane_mm; s.throughput_ph = tp
    ctx.view_layer.update(); build_line(ctx, o); ctx.view_layer.update()
    return o
try:
    # ---------------- A. ARB centre + turn + pivot + buffer sensors on one line
    line = make((0, 0, 0), 0.0, [('STRAIGHT', 3000), ('MODULE', 'ARB', 'CENTER', False), ('STRAIGHT', 2000), ('MODULE', 'ARB', 'TURN_LEFT', False),
                                 ('STRAIGHT', 2000), ('MODULE', 'ARB', 'TURN_RIGHT', True), ('STRAIGHT', 1000), ('MODULE', 'BUFFER'), ('STRAIGHT', 2000)],
                "ArbLine", lane_mm=150.0)
    segs = [(s.kind, s.module_kind if s.kind == 'MODULE' else round(s.length_mm)) for s in line.conveyor_line.segments]
    print("segments:", segs)
    ls = [v.value for v in line.data.attributes["lane_scale"].data][:line.data.curves[0].points_length]
    arcs = [v.value for v in line.data.attributes["arc_len"].data][:line.data.curves[0].points_length]
    print("lane_scale by arc:", [(round(a, 2), round(v, 2)) for a, v in zip(arcs, ls)][:12])
    check(ls[0] == 1.0 and any(v == 0.0 for v in ls), "lane_scale ramps from 1 to 0 at the centre module")
    ctx.scene.frame_set(7)
    pts = items(line)
    before = [p.x for p, r in pts if 0.3 < p.y < 2.9]
    after = [p.x for p, r in pts if 4.6 < p.y < 6.4]
    print("lane x before:", [round(v, 3) for v in before], "after:", [round(v, 3) for v in after])
    check(before and all(abs(v - 0.15) < 0.01 for v in before), "goods run 150 mm off-centre before the ARB centre element")
    check(after and all(abs(v) < 0.01 for v in after), "goods are on the centre lane after it")
    yaw_before = [r for p, r in pts if 4.6 < p.y < 6.4]
    yaw_after = [r for p, r in pts if 8.1 < p.y < 9.4]
    check(yaw_before and all(abs(r) < 0.01 for r in yaw_before), "goods aligned with travel before the turn")
    check(yaw_after and all(abs(abs(r) - math.pi / 2) < 0.02 for r in yaw_after), f"goods turned 90° after the ARB turn ({[round(math.degrees(r)) for r in yaw_after][:3]})")
    inside = [(p.y, r) for p, r in pts if 6.55 < p.y < 7.95]
    check(all(0.02 < abs(r) < math.pi / 2 - 0.02 for y, r in inside) if inside else True, f"goods rotate in motion inside the turn ({[(round(y, 2), round(math.degrees(r))) for y, r in inside]})")
    yaw_end = [r for p, r in pts if 11.6 < p.y < 12.4]
    check(yaw_end and all(abs(dj._wrap(r)) < 0.02 for r in yaw_end), f"the pivot turn right brings them back in line ({[round(math.degrees(r)) for r in yaw_end][:3]})")
    arb_wheels = insts(line, lambda d: abs(d[1] - 0.024) < 0.004 and abs(d[2] - 0.024) < 0.004)
    on_center = [p for p, r in arb_wheels if 3.0 < p.y < 4.5]; on_turn = [p for p, r in arb_wheels if 6.5 < p.y < 8.0]
    check(len(on_center) > 100 and len(on_turn) > 100, f"ARB roller grids on the centre ({len(on_center)}) and turn ({len(on_turn)}) elements")
    yaws_c = sorted(set(round(math.degrees(r)) for p, r in arb_wheels if 3.0 < p.y < 4.5))
    check(yaws_c == [-30, 30], f"centre element rollers form a herringbone ({yaws_c})")
    yaws_t = sorted(set(round(math.degrees(r)) for p, r in arb_wheels if 6.5 < p.y < 8.0))
    check(yaws_t == [30], f"turn-left element rollers skewed one way ({yaws_t})")
    pin = insts(line, lambda d: abs(d[0] - 0.04) < 0.006 and abs(d[2] - 0.12) < 0.006, near=Vector((0, 9.5 + 0.35 * 1.5, 0)), radius=0.6)
    check(len(pin) == 1 and pin[0][0].x > 0.15, f"pivot pin at the right edge of the turn-right module ({len(pin)})")
    pivot_wheels = [p for p, r in arb_wheels if 9.5 < p.y < 11.0]
    check(not pivot_wheels, "no ARB deck on the fixed-pivot turn (line surface continues)")
    # 2.6 builds the buffer's zone sensors into the module's mesh (photo-eye housings in the sensor material), not as instances
    dg = ctx.evaluated_depsgraph_get(); geo = line.evaluated_get(dg).evaluated_geometry(); me = geo.mesh; mw = line.matrix_world  # keep `geo` alive
    sidx = {i for i, m in enumerate(me.materials) if m is not None and "Sensor" in m.name}
    sens_faces = [p for p in me.polygons if p.material_index in sidx and 12.0 < (mw @ p.center).y < 16.0]
    print("note: 2.6 models the buffer's zones in the stream (Buffer k Zones / Pitch / Slug), without separate ZPA sensor housings:",
          len(sens_faces), "sensor faces; materials:", [m.name if m else None for m in me.materials])
    # attribute defaults for older spines
    line.data.attributes.remove(line.data.attributes["lane_scale"])
    spine_io.ensure_attribute_defaults(line.data)
    check("lane_scale" in line.data.attributes and all(abs(v.value - 1.0) < 1e-6 for v in line.data.attributes["lane_scale"].data), "missing attributes get neutral defaults")

    # ---------------- B. junction technologies
    main = make((20, 0, 0), 0.0, [('STRAIGHT', 16000)], "Main", tp=600)
    f45 = make((20 - 2.6, 2.0, 0), -math.pi / 4, [('STRAIGHT', 3000)], "Feed45", tp=1200)
    f90 = make((20 + 1.9, 7.0, 0), math.pi / 2, [('STRAIGHT', 1200)], "Feed90", tp=600)
    out45 = make((20 + 2.5, 12.0, 0), math.radians(135), [('STRAIGHT', 3000)], "Out45", reverse=True)
    out90 = make((20 + 1.8, 14.5, 0), math.pi / 2, [('STRAIGHT', 1200)], "Out90", reverse=True)
    segsM = [(s.kind, s.module_kind if s.kind == 'MODULE' else round(s.length_mm), s.merge_angle if s.kind == 'MODULE' else '', s.merge_source if s.kind == 'MODULE' else '') for s in main.conveyor_line.segments]
    print("main:", segsM)
    idx = {s.merge_source: i for i, s in enumerate(main.conveyor_line.segments) if s.kind == 'MODULE'}
    check(all(n in idx for n in ("Feed45", "Feed90", "Out45", "Out90")), "two feeders and two outfeeds docked")
    S = main.conveyor_line.segments
    techs = {n: resolve_junction_tech(S[i]) for n, i in idx.items()}
    print("auto techs:", techs)
    check(techs == {"Feed45": "SKEW", "Feed90": "BELT", "Out45": "STRIP", "Out90": "BELT"}, "deck defaults resolved per role and angle (2.6: belt transfers at 90°)")
    def face(n):
        c, h, g = dj._module_face_world(ctx, main, idx[n], None); return c
    # the 2.6 merge deck builds its skewed landing rollers into the module mesh; the parts below are its instances
    S[idx["Feed90"]].junction_tech = 'POPUP'; ctx.view_layer.update()
    popup = insts(main, lambda d: abs(d[0] - 0.44) < 0.02 and abs(d[1] - 0.014) < 0.004, near=face("Feed90"), radius=1.2)
    check(len(popup) >= 4, f"pop-up belt strips at the 90° merge when POPUP is chosen ({len(popup)})")
    check(S[idx["Feed90"]].junction_tech == 'POPUP', "the chosen technology survives the rebuild (2.6 dropped it on every re-fit)")
    strips = insts(main, lambda d: abs(d[0] - 0.35) < 0.02 and abs(d[1] - 0.008) < 0.003, near=face("Out45"), radius=1.0)
    check(len(strips) == 2, f"two strip belts at the 45° divert (2.6 builds the angle into the module; instance yaw {[round(math.degrees(r)) for p, r in strips]})")
    # explicit choices: ARB on the 45 merge, PUSHER on the 90 divert, invalid PUSHER on a merge falls back (to the belt transfer)
    S[idx["Feed45"]].junction_tech = 'ARB'; S[idx["Out90"]].junction_tech = 'PUSHER'; S[idx["Feed90"]].junction_tech = 'PUSHER'
    ctx.view_layer.update()
    check(resolve_junction_tech(S[idx["Feed45"]]) == 'ARB' and resolve_junction_tech(S[idx["Out90"]]) == 'PUSHER' and resolve_junction_tech(S[idx["Feed90"]]) == 'BELT',
          "explicit technologies honoured, invalid one falls back")
    body = insts(main, lambda d: abs(d[0] - 0.32) < 0.01 and abs(d[1] - 0.22) < 0.01, near=face("Out90"), radius=1.2)
    check(len(body) == 1 and body[0][0].x < 20 - 0.3, f"pusher unit on the far side of the 90° divert ({len(body)}, x {body[0][0].x - 20 if body else None})")
    # loads (2.22 simple flow: every owner brings its own Population at the group's speed; a Route by
    # item class takes that class's part). The bottleneck alerts are dormant (round 8: no throughput
    # physics in the UI); the loads stay for a later "real throughput" round.
    S[idx["Out45"]].route_class = 0; S[idx["Out90"]].route_class = 1
    # (2.23: below the grid's floor -- the 90 degree stops' pitch -- or warehouse_common's resolve gives
    # the first feeder its goods and the next what is left: R22.2 caps; 3000/h was more than 100 % anyway)
    pct = lambda rate: 100.0 * rate * (0.6 + 0.05) / (3600.0 * 0.5)
    main.conveyor_line.population_pct = pct(300); f45.conveyor_line.population_pct = pct(300); f90.conveyor_line.population_pct = pct(150)
    ctx.view_layer.update()
    check(S[idx["Out45"]].route_class == 0 and S[idx["Out90"]].route_class == 1, "route classes survive the rebuild")
    loads = {n: stream.junction_load_ph(ctx, main, i) for n, i in idx.items()}
    print("loads:", loads)
    check(abs(loads["Feed45"] / loads["Feed90"] - 2.0) < 1e-3, f"merge loads: the feeders' flows, 2 : 1 ({loads['Feed45']:.1f}, {loads['Feed90']:.1f})")
    check(abs(loads["Out45"] / (loads["Out45"] + loads["Out90"]) - 0.5) < 1e-3,
          f"the two class diverts take half each, two placeholder classes ({loads['Out45']:.1f}, {loads['Out90']:.1f})")
    from bl_ext.user_default.conveyor_system.ui import panels as _panels
    check(not _panels.SHOW_THROUGHPUT_PHYSICS, "bottleneck alerts are dormant (round 8)")
    import os
    if os.environ.get("TMPDIR"):  # a look at the scene for a person: the scratch temp folder, never the project's scenes
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(os.environ["TMPDIR"], "V2.4 tech check.blend"))
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
