"""Round 6 wave 3 (interop contract v2.1, R5 handler hygiene): the depsgraph
handler only detects and schedules; the deferred pass (detect_junctions.run_sync)
does the work under the shared driver_namespace["wh_sync_busy"] flag and counts
its passes and writes (operators/sync_stats). Blender -b --python tests/headless/test_round6_w3.py"""
import json, math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line, BUILD_STATS
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
from bl_ext.user_default.conveyor_system.operators.sync_stats import STATS
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
from bl_ext.user_default.conveyor_system._wh.records import to_plain
ctx = bpy.context; scene = ctx.scene; fails = []; ns = bpy.app.driver_namespace
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
def snapshot():
    out = {}
    for o in scene.objects:
        out[o.name] = {k: repr(to_plain(o[k])) for k in o.keys()}
        out[o.name]["@matrix"] = repr([round(v, 5) for row in o.matrix_world for v in row])
    return out
def make(loc, heading, length_mm, name):
    o = create_line(ctx, Vector((100.0, 100.0, 0.0)), heading); o.name = name; o.location = Vector(loc)
    with suspended_rebuild():
        o.conveyor_line.segments[0]["length_mm"] = float(length_mm); o.conveyor_line.populate = True; o.conveyor_line.speed_m_s = 0.5
    ctx.view_layer.update(); build_line(ctx, o); ctx.view_layer.update()
    return o
class FakeUpdate:
    def __init__(self, id_, transform=False, geometry=False):
        self.id, self.is_updated_transform, self.is_updated_geometry = id_, transform, geometry
class FakeGraph:
    def __init__(self, *updates): self.updates = list(updates)
try:
    main = make((0, 0, 0), 0.0, 10000, "Main")
    feeder = make((-30.0, 2.0, 0), -math.pi / 4, 3000, "Feeder")  # built far away: nothing to dock on
    feeder.location = Vector((-2.6, 2.0, 0.0)); ctx.view_layer.update()  # the user moves it: its end now aims at the main
    check(dj.docked_junction(ctx, feeder) is None, "a moved feeder is not docked until a sync pass runs")
    # ---- A. the handler writes nothing and builds nothing: it schedules one pass per burst
    before, b0, p0 = snapshot(), BUILD_STATS["builds"], STATS["passes"]
    for _ in range(100):
        feeder.location.x += 0.001  # a burst of 100 transforms
        dj._on_depsgraph_update(scene, None)
    check(snapshot() == before or all(before[n] == snapshot()[n] for n in before if n != "Feeder"), "the handler changed no ID property of any object")
    check(BUILD_STATS["builds"] == b0 and STATS["passes"] == p0, "the handler built nothing and ran no pass")
    check(dj._scheduled.get(scene.name) is True and len(dj._scheduled) == 1, "100 updates scheduled exactly one deferred pass")
    check(dj.docked_junction(ctx, feeder) is None, "nothing docked yet (the handler does not sync)")
    # ---- B. the deferred pass does the work (what the timer calls)
    dj._deferred_pass(scene.name)
    check(not dj._scheduled and STATS["passes"] == p0 + 1, "the timer's pass ran once and cleared the schedule")
    check(dj.docked_junction(ctx, feeder) is not None, "the pass docked the feeder")
    check(STATS["last_writes"] > 0, f"the pass counted its writes ({STATS['last_writes']})")
    quiet = dj.run_sync(scene)
    check(quiet == 0, f"a pass with nothing changed makes no writes ({quiet})")
    # ---- C. the relevance filter: a frame step or our own line re-evaluating schedules nothing
    lines = [main, feeder]
    check(not dj._relevant(scene, FakeGraph(FakeUpdate(scene)), lines), "a scene update (frame step) is not relevant")
    check(not dj._relevant(scene, FakeGraph(FakeUpdate(main, geometry=True), FakeUpdate(main.data, geometry=True)), lines), "our own line's re-evaluation is not relevant")
    check(dj._relevant(scene, FakeGraph(FakeUpdate(feeder, transform=True)), lines), "a moved line is relevant")
    cube = bpy.data.objects.new("Rack mesh", bpy.data.meshes.new("Rack mesh")); scene.collection.objects.link(cube)
    check(dj._relevant(scene, FakeGraph(FakeUpdate(cube)), lines), "another object's update (added, selected, ports republished) is relevant")
    mat = bpy.data.materials.new("Paint")
    check(dj._relevant(scene, FakeGraph(FakeUpdate(mat)), lines), "a material edit is relevant")
    check(not dj._relevant(scene, FakeGraph(), lines), "no updates: nothing to schedule")
    check(dj._relevant(scene, None, lines), "a direct call without a graph assumes a change")
    ctx.view_layer.update(); dg = ctx.evaluated_depsgraph_get(); dj._scheduled.clear()
    dj._on_depsgraph_update(scene, dg)
    check(bool(dj._scheduled.get(scene.name)) == dj._relevant(scene, dg, lines), f"with a real depsgraph the handler schedules exactly when the filter says so ({len(dg.updates)} updates, relevant {dj._relevant(scene, dg, lines)})")
    dj._scheduled.clear()
    # ---- D. the shared busy flag: handlers and passes yield while another add-on's pass runs
    ns["wh_sync_busy"] = True
    p1 = STATS["passes"]
    dj._on_depsgraph_update(scene, None)
    check(not dj._scheduled, "while another add-on's pass runs the handler returns at once")
    r = dj.run_sync(scene)
    check(r == 0 and STATS["passes"] == p1 and dj._scheduled.get(scene.name) is True, "run_sync yields to the running pass and tries again later")
    ns["wh_sync_busy"] = False; dj._scheduled.clear()
    # ---- E. the flag is set during our pass, cleared after, even when the pass raises; no re-entry
    seen, orig = {}, dj._propagate_master_materials
    def spy(context, lines_):
        seen["flag"] = ns.get("wh_sync_busy"); seen["nested"] = dj.run_sync(scene); seen["handler"] = dj._scheduled.get(scene.name)
        dj._on_depsgraph_update(scene, None); seen["handler_after"] = dj._scheduled.get(scene.name)
        return orig(context, lines_)
    dj._propagate_master_materials = spy
    p2 = STATS["passes"]; dj.run_sync(scene); dj._propagate_master_materials = orig
    check(seen.get("flag") is True and ns.get("wh_sync_busy") is False, "the flag is set during the pass and cleared after")
    check(seen.get("nested") == 0 and STATS["passes"] == p2 + 1, "a nested pass is refused (no re-entry)")
    check(seen.get("handler_after") is None or seen.get("handler_after") == seen.get("handler"), "the handler schedules nothing from inside a pass")
    dj._scheduled.clear()
    def boom(context, lines_): raise RuntimeError("test")
    dj._propagate_master_materials = boom
    try:
        dj.run_sync(scene)
    except RuntimeError:
        pass
    dj._propagate_master_materials = orig
    check(ns.get("wh_sync_busy") is False, "the flag is cleared even when the pass raises")
    # ---- G. docked lines settle: 0 writes from the second pass on (the PM's joint suite found
    # a dock record rewritten on every pass while a port's load object was not in the file)
    from bl_ext.user_default.conveyor_system.operators import ports
    from bl_ext.user_default.conveyor_system._wh import ops as wh_ops
    import json
    def system(name, sid, loc, port_list):
        o = bpy.data.objects.new(name, None); scene.collection.objects.link(o); o.location = loc
        o["wh_system"] = json.dumps({"version": 2, "addon": "warehouse_racks", "kind": "crane_rack", "id": sid, "object": name, "label": name, "level": 0,
                                     "footprint": [[-1, -1], [1, -1], [1, 1], [-1, 1]], "height_m": 6.0, "clearance_m": 0.0, "zone": None})
        o["wh_ports"] = json.dumps(port_list); ctx.view_layer.update(); return o
    def settles(label, rounds=5):
        seen = []
        for _ in range(rounds):
            ctx.view_layer.update(); seen.append(dj.run_sync(scene)); ctx.view_layer.update()
        check(all(w == 0 for w in seen[1:]), f"{label}: 0 writes from the second pass on {seen} {STATS['sites'][:3]}")
    missing_load = {"kind": "pallet", "id": "pallet:EUR1:Wood:1.2", "object": "WH Load not here", "length_m": 1.2, "width_m": 0.8, "height_m": 1.2, "forward_axis": "X", "make": "warehouse.make_load"}
    door = system("Dock row", "dock-1", (60.0, 0.0, 0.0), [{"version": 2, "id": "door1", "role": "out", "kind": "point", "position": [0, 0, 0], "heading_deg": 0.0,
                                                           "width_m": 1.26, "z_free": True, "rate_ph": 16.0, "capacity_ph": 16.0, "load": missing_load}])
    crane = system("Crane rack", "rack-9", (80.0, 0.0, 0.0), [{"version": 2, "id": "aisle0_in", "role": "in", "kind": "point", "position": [0, 0, 0.6], "heading_deg": 0.0,
                                                             "width_m": 1.26, "rate_ph": 40.0, "capacity_ph": 40.0, "load": missing_load},
                                                            {"version": 2, "id": "aisle0_out", "role": "out", "kind": "point", "position": [3, 0, 0.6], "heading_deg": 0.0,
                                                             "width_m": 1.26, "rate_ph": 40.0, "capacity_ph": 40.0, "load": missing_load}])
    def line(z, name):
        bpy.ops.conveyor.new_line(kind="line", preset="chain", location=(70.0, 20.0, z), heading_deg=0.0); o = ctx.view_layer.objects.active; o.name = name; return o
    A = line(0.8, "A at the door"); rA = bpy.ops.conveyor.dock_line(line_id=json.loads(A["wh_system"])["id"], system_id="dock-1", port_id="door1", anchor="start", by="test")
    check(rA == {'FINISHED'} and ports.dock_at(A, "origin") is not None and abs(A.location.z - 0.8) < 1e-3, "A docked at the z_free door (load object not in the file)")
    settles("A start-docked at a z_free door")
    B = line(0.0, "B into the crane"); rB = bpy.ops.conveyor.dock_line(line_id=json.loads(B["wh_system"])["id"], system_id="rack-9", port_id="aisle0_in", anchor="end", by="test")
    check(rB == {'FINISHED'} and ports.dock_at(B, "origin") is not None and B.conveyor_line.reverse, "B docked by its flow end at the crane in-feed (not z_free)")
    settles("A + B docked")
    C = line(0.0, "C from the crane"); rC = bpy.ops.conveyor.dock_line(line_id=json.loads(C["wh_system"])["id"], system_id="rack-9", port_id="aisle0_out", anchor="start", by="test")
    check(rC == {'FINISHED'}, "C docked at the crane out-feed")
    settles("A + B + C docked")
    if not wh_ops.operator_exists(bpy.ops, "warehouse.make_load"):
        class WAREHOUSE_OT_make_load(bpy.types.Operator):  # a Racks that is here but whose load build is still pending
            bl_idname = "warehouse.make_load"; bl_label = "Make Load (pending stand-in)"
            load_id: bpy.props.StringProperty()
            def execute(self, context): return {'FINISHED'}
        bpy.utils.register_class(WAREHOUSE_OT_make_load)
        settles("with a make_load that has not built the load yet")
    bpy.data.objects.remove(door); ctx.view_layer.update()
    settles("the dock row deleted (A lost its port)")
    for _ in range(100):
        B.location.x += 0.001
        dj._on_depsgraph_update(scene, None)
    settles("after a 100-transform burst on B")
    # the same with the real add-ons when they can be enabled: a Floorplan building + dock row and a Racks crane rack
    real = True
    try:
        for pkg in ("bl_ext.user_default.warehouse_floorplan", "bl_ext.user_default.warehouse_racks"):
            if pkg not in bpy.context.preferences.addons:
                bpy.ops.preferences.addon_enable(module=pkg)
    except Exception as e:
        print("SKIP: the real-building cases: Floorplan/Racks not available here:", e); real = False
    if real:
        from mathutils import Vector as V
        import importlib

        def sibling(mod):
            try:
                return importlib.import_module(mod)
            except Exception:
                return None
        fsync = sibling("bl_ext.user_default.warehouse_floorplan.sync")
        rinterop = sibling("bl_ext.user_default.warehouse_racks.interop")

        def pump(rounds=6):
            """Blender's event loop, headless (the joint suite's pump): every add-on's deferred pass --
            Floorplan 0.3 builds its walls in sync.tick, so a dock row finds no wall without it."""
            for _ in range(rounds):
                ctx.view_layer.update(); dj.run_sync(scene)
                if fsync is not None and hasattr(fsync, "tick"):
                    fsync.tick()
                if rinterop is not None and hasattr(rinterop, "run_sync"):
                    rinterop.run_sync(scene)
                ctx.view_layer.update()
        def systems(addon, kind):
            out = []
            for o in scene.objects:
                raw = o.get("wh_system")
                if isinstance(raw, str):
                    d = json.loads(raw)
                    if d.get("addon") == addon and d.get("kind") == kind: out.append(o)
            return out
        bpy.ops.floorplan.add_system(kind="building", preset="EU_40x80", location=(200.0, 0.0, 0.0)); pump()
        bld = systems("warehouse_floorplan", "building")[0]; bs = json.loads(bld["wh_system"]); M = bld.matrix_world
        fp = [M @ V((p[0], p[1], 0)) for p in bs["footprint"]]; cx = sum(v.x for v in fp) / len(fp); cy = sum(v.y for v in fp) / len(fp)
        a, b = fp[0], fp[1]; mid = (a + b) * 0.5; inward = (V((cx, cy, 0)) - mid).normalized(); dock_at = mid + inward * 1.0
        bpy.ops.floorplan.add_system(kind="dock_door", preset="EU_4_DOORS", location=(dock_at.x, dock_at.y, 0.0)); pump()
        docks_found = systems("warehouse_floorplan", "dock_door")
        dock = docks_found[0] if docks_found else None
        if dock is None:  # a Floorplan that places no dock row with the joint-suite recipe
            fp_ver = bpy.context.preferences.addons.get("bl_ext.user_default.warehouse_floorplan")
            print("SKIP: the real-door cases: this Floorplan placed no dock row with the joint-suite recipe")
        dout = next(p for p in ports.ports_of(dock) if p.get("role") in ("out", "io")) if dock is not None else None
        scene.cursor.location = (cx, cy, 0.0); bpy.ops.warehouse.add_system(kind="crane_rack"); pump()
        rack = next(o for o in systems("warehouse_racks", "crane_rack") if o is not crane); rp = ports.ports_of(rack)  # the one Racks made, not the stand-in
        rin = next(p for p in rp if p.get("kind") == "point" and p.get("role") in ("in", "io")); rout = next(p for p in rp if p.get("kind") == "point" and p.get("role") in ("out", "io"))
        if dock is not None:
            bpy.ops.conveyor.new_line(kind="line", preset="chain", location=(cx, cy, 0.8), heading_deg=0.0); RA = ctx.view_layer.objects.active
            check(bpy.ops.conveyor.dock_line(line_id=json.loads(RA["wh_system"])["id"], system_id=json.loads(dock["wh_system"])["id"], port_id=dout["id"], anchor="start", by="test") == {'FINISHED'}, "real: a line docks at the Floorplan door")
            settles("real: start-docked at the Floorplan door (z_free)")
        bpy.ops.conveyor.new_line(kind="line", preset="chain", location=(cx, cy, 0.0), heading_deg=0.0); RB = ctx.view_layer.objects.active
        rB = bpy.ops.conveyor.dock_line(line_id=json.loads(RB["wh_system"])["id"], system_id=json.loads(rack["wh_system"])["id"], port_id=rin["id"], anchor="end", by="test")
        check(rB == {'FINISHED'} and ports.dock_at(RB, "origin") is not None, f"real: a line docks into the Racks crane in-feed ({rack.name} · {rin['id']})")
        bpy.ops.conveyor.new_line(kind="line", preset="chain", location=(cx, cy, 0.0), heading_deg=0.0); RC = ctx.view_layer.objects.active
        check(bpy.ops.conveyor.dock_line(line_id=json.loads(RC["wh_system"])["id"], system_id=json.loads(rack["wh_system"])["id"], port_id=rout["id"], anchor="start", by="test") == {'FINISHED'}, "real: a line docks at the crane out-feed")
        settles("real: door + crane in + crane out docked" if dock is not None else "real: crane in + crane out docked")
        if dock is not None:
            bpy.data.objects.remove(dock); ctx.view_layer.update()
            settles("real: the dock row deleted")
    # ---- F. unregister leaves no handler and no flag behind
    bpy.ops.preferences.addon_disable(module=PKG)
    check(all(getattr(h, "__name__", "") != "_on_depsgraph_update" for h in bpy.app.handlers.depsgraph_update_post) and not ns.get("wh_sync_busy"), "disable removes the handler and clears the flag")
    bpy.ops.preferences.addon_enable(module=PKG)
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
