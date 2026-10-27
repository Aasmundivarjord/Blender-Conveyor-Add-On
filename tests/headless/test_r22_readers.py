"""2.19.0 (round 8, R22 readers first): racks and doors may publish population /
speed_m_s / max_population / population_in / master (and links a share)
instead of rates. The Conveyor reads them -- the same flow, the same goods
handed over -- and never requires the rate keys. No UI changes.
Blender -b --python tests/headless/test_r22_readers.py"""
import json, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, stream, ports
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
ctx = bpy.context; scene = ctx.scene; fails = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
def settle():
    for _ in range(4):
        ctx.view_layer.update(); dj.run_sync(scene)
    ctx.view_layer.update()
def pallet_object(name):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-50.0, -50.0, 0.0))
    o = ctx.view_layer.objects.active; o.name = name; o.scale = (0.8, 1.2, 0.15); ctx.view_layer.update()
    return o
def system(name, sid, loc, port_list):
    o = bpy.data.objects.new(name, None); scene.collection.objects.link(o); o.location = loc
    o["wh_system"] = json.dumps({"version": 2, "addon": "warehouse_racks", "kind": "crane_rack", "id": sid, "object": name, "label": name,
                                 "level": 0, "footprint": [[-1, -1], [1, -1], [1, 1], [-1, 1]], "height_m": 6.0, "clearance_m": 0.0, "zone": None})
    o["wh_ports"] = json.dumps(port_list); ctx.view_layer.update()
    return o
def line_at(name, loc, heading=0.0):
    o = create_line(ctx, Vector(loc), heading); o.name = name
    with suspended_rebuild():
        o.conveyor_line.segments[0]["length_mm"] = 6000.0
    build_line(ctx, o); settle()
    return o
def lid(o):
    return json.loads(o["wh_system"])["id"]
try:
    pallet_object("EUR1 pallet")
    load = {"version": 2, "kind": "pallet", "id": "pallet:EUR1:Wood:1.2", "object": "EUR1 pallet", "length_m": 1.2, "width_m": 0.8, "height_m": 0.15,
            "forward_axis": "Y"}
    # ---- an out port that publishes only R22 keys: no rate_ph, no capacity_ph
    rack = system("R22 rack", "rack-r22", (0.0, 0.0, 0.0), [
        {"version": 2, "id": "out0", "role": "out", "kind": "point", "position": [0, 0, 0], "heading_deg": 0.0, "width_m": 0.8,
         "population": 0.5, "speed_m_s": 0.2, "master": True, "load": load},
        {"version": 2, "id": "in0", "role": "in", "kind": "point", "position": [3, 0, 0], "heading_deg": 0.0, "width_m": 0.8,
         "max_population": 0.1, "speed_m_s": 0.2, "load": None},
        {"version": 2, "id": "io0", "role": "io", "kind": "point", "position": [6, 0, 0], "heading_deg": 0.0, "heading_in_deg": 180.0, "width_m": 0.8,
         "population": 0.5, "population_in": 0.25, "speed_m_s": 0.2, "load": load},
        {"version": 2, "id": "bare", "role": "out", "kind": "point", "position": [9, 0, 0], "heading_deg": 0.0, "width_m": 0.8, "load": None}])
    a = line_at("Out line", (0.0, -10.0, 0.0))
    r = bpy.ops.conveyor.dock_line(line_id=lid(a), system_id="rack-r22", port_id="out0", anchor="start", by="test"); settle()
    s = a.conveyor_line
    check(r == {'FINISHED'} and abs(s.speed_m_s - 0.2) < 1e-6, f"the line takes the goods' speed_m_s on a fresh dock ({s.speed_m_s:.2f})")
    check(abs(s.population_pct - 50.0) < 0.1, f"population 50 % of 1.2 m pallets at 0.2 m/s: the line carries the same flow, Population 50 % ({s.population_pct:.2f})")
    tree = stream.tree_for(ctx, a)
    check(abs(tree.spacing - 2.5) < 1e-3, f"so the pallets hand over 2.5 m apart, (1.2 + 0.05) / 0.5 ({tree.spacing:.3f})")
    # ---- a sink that publishes only max_population caps the line feeding it
    b = line_at("In line", (3.0, -10.0, 0.0))
    with suspended_rebuild():
        b.conveyor_line.populate = True; b.conveyor_line.speed_m_s = 0.2
        from bl_ext.user_default.conveyor_system.model.public_api import population_pct_for_rate
        from bl_ext.user_default.conveyor_system.operators.populate import populate_item_length as _pil
        b.conveyor_line.population_pct = population_pct_for_rate(200.0, _pil(ctx, b), 0.2)  # what 200/h was (2.22: Population)
    build_line(ctx, b); settle()
    r = bpy.ops.conveyor.dock_line(line_id=lid(b), system_id="rack-r22", port_id="in0", anchor="end", by="test"); settle()
    bt = stream.tree_for(ctx, b)
    from bl_ext.user_default.conveyor_system.operators.populate import populate_item_length
    want = 3600.0 * 0.1 * 0.2 / (populate_item_length(ctx, b) + 0.05)
    # (2.23: the sink's max_population caps the stream in the group's resolve -- R22.2 -- so the
    # line runs and publishes the capped population, 10 %)
    check(r == {'FINISHED'} and abs(bt.effective_ph - want) < 0.5 and abs(bt.flow.population.get(b.name, 0.0) - 0.1) < 2e-3,
          f"max_population 10 % caps the line feeding the sink at {want:.0f}/h ({bt.effective_ph:.1f}, {bt.flow.population.get(b.name, 0.0):.4f})")
    # ---- an io port: an in line reads population_in
    from bl_ext.user_default.conveyor_system.model import port_io
    io = json.loads(rack["wh_ports"])[2]
    check(abs(port_io.rate_ph(io, "in", None, 0.2) - 144.0) < 1e-6 and abs(port_io.rate_ph(io, "out", None, 0.2) - 288.0) < 1e-6,
          "an io port: population_in for its in direction, population for its out")
    # ---- a port with nothing: docks, no rate, no crash
    c = line_at("Bare line", (9.0, -10.0, 0.0))
    r = bpy.ops.conveyor.dock_line(line_id=lid(c), system_id="rack-r22", port_id="bare", anchor="start", by="test"); settle()
    check(r == {'FINISHED'} and c.conveyor_line.throughput_ph == 0, "a port with neither rates nor population: docks, no rate, no crash")
    # ---- links carrying share and ports carrying master are read without trouble
    rack["wh_port_links"] = json.dumps([{"version": 2, "system_id": "rack-r22", "port": "out0", "role": "out", "share": 0.4, "by": "warehouse_racks"}])
    settle()
    check(ports.dock_at(a, "origin") is not None and abs(a.conveyor_line.population_pct - 50.0) < 0.1,
          "a link with a share and a port with master: true are read without trouble (the dock and its Population hold)")
    check(dj.run_sync(scene) == 0, "settled: the pass writes nothing")
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
