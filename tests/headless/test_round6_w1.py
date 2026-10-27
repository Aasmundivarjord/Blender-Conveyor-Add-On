"""Round 6 wave 1 (interop contract v2.1): R11 add operator and registry,
R3 floors, R15 links from any system, R2 records in both forms, R10 levels.
Blender -b --python tests/headless/test_round6_w1.py -- imports the installed
add-on, or the dev copy through BLENDER_USER_EXTENSIONS (see run_all.sh)."""
import json, math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line
from bl_ext.user_default.conveyor_system.operators import ports, floors
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
from bl_ext.user_default.conveyor_system.operators.populate import wh_load
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
from bl_ext.user_default.conveyor_system._wh import records as wh_records
ctx = bpy.context; scene = ctx.scene; fails = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
def rec(obj, key):
    raw = obj.get(key)
    return json.loads(raw) if isinstance(raw, str) else None
def feet(obj, y0=1.0, y1=5.0):
    dg = ctx.evaluated_depsgraph_get(); out = []
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.parent.original == obj:
            d = tuple(round(c, 3) for c in i.object.dimensions)
            if abs(d[0] - 0.144) < 0.01 and abs(d[2] - 0.012) < 0.005:
                p = i.matrix_world.translation
                if y0 < p.y < y1 and abs(p.x) < 0.5: out.append(round(p.z, 2))
    return sorted(out)
def on(zs, floor_z):
    return bool(zs) and all(abs(z - (floor_z + 0.006)) < 0.04 for z in zs)
def plane(name, loc, size=4.0):
    bpy.ops.mesh.primitive_plane_add(size=size, location=loc)
    o = ctx.view_layer.objects.active; o.name = name
    return o
def empty(name, loc=(0.0, 0.0, 0.0)):
    o = bpy.data.objects.new(name, None); scene.collection.objects.link(o); o.location = loc
    return o
def select_only(obj):
    for o in ctx.view_layer.objects: o.select_set(False)
    obj.select_set(True); ctx.view_layer.objects.active = obj
def settle():
    ctx.view_layer.update(); dj.run_sync(scene); ctx.view_layer.update()
def auto_floors():
    return {o.name for o in bpy.data.collections["Conveyor Floors (auto)"].objects}
try:
    # ---- R11: the add operator and the registry
    ports.register_addon_entry()
    reg = json.loads(ctx.window_manager["wh_addons"])["conveyor_system"]
    check(reg.get("contract") == "2.1" and reg.get("add") == "conveyor.new_line", "wh_addons entry says contract 2.1")
    presets = reg["kinds"][0]["presets"]
    check("belt" in presets and "merge_junction" not in presets and reg["kinds"][0]["kind"] == "line", f"presets are the line types {presets}")
    r = bpy.ops.conveyor.new_line(kind="line", preset="belt", location=(3.0, 4.0, 0.0), heading_deg=90.0)
    placed = ctx.view_layer.objects.active
    check(r == {'FINISHED'} and placed is not None and placed.conveyor_line.is_conveyor_line, "new_line(kind, preset, location, heading_deg) makes a line")
    check((placed.location - Vector((3, 4, 0))).length < 1e-4 and abs(math.degrees(placed.rotation_euler.z) - 90) < 1e-3, "at the given pose")  # (float32 channels)
    check(placed.conveyor_line.conveyor_type == 'belt', "of the preset's type")
    check(rec(placed, "wh_system")["kind"] == "line" and rec(placed, "wh_system")["addon"] == "conveyor_system", "and it publishes wh_system")
    r = bpy.ops.conveyor.new_line(kind="rack", location=(0.0, 0.0, 0.0))
    check(r == {'CANCELLED'}, "an unknown kind cancels")
    r = bpy.ops.conveyor.new_line(preset="hovercraft", location=(6.0, 0.0, 0.0))
    fallback = ctx.view_layer.objects.active
    check(r == {'FINISHED'} and fallback is not placed and fallback.conveyor_line.conveyor_type == 'gravity_roller', "an unknown preset falls back to the default type")
    scene.cursor.location = (10.0, 10.0, 2.0)
    r = bpy.ops.conveyor.new_line()
    at_cursor = ctx.view_layer.objects.active
    check(r == {'FINISHED'} and (at_cursor.location - Vector((10, 10, 2.0))).length < 1e-6, "without arguments the line starts at the 3D cursor")
    scene.cursor.location = (14.0, 10.0, 0.0)  # a new scene's cursor: on the floor
    r = bpy.ops.conveyor.new_line()
    on_floor = ctx.view_layer.objects.active
    check(r == {'FINISHED'} and (on_floor.location - Vector((14, 10, 0.8))).length < 1e-6,
          f"a cursor on the floor starts the line at a 0.8 m bed height, not on the ground ({tuple(round(v, 3) for v in on_floor.location)})")
    for o in (placed, fallback, at_cursor, on_floor): bpy.data.objects.remove(o)

    # ---- R3: floors
    line = create_line(ctx, Vector((0.0, 0.0, 4.0)), 0.0); line.name = "High"
    with suspended_rebuild():
        line.conveyor_line.segments[0]["length_mm"] = 6000.0
    build_line(ctx, line); settle()
    check(on(feet(line), 0.0), f"no floors: feet on the ground {feet(line)}")
    deck = plane("Deck", (0, 3, 2.0)); settle()
    check(on(feet(line), 2.0), f"a plain mesh under the line is a floor: feet {feet(line)}")
    rack = plane("Rack mesh", (0, 3, 3.0)); rack["wh_system"] = json.dumps({"version": 2, "addon": "warehouse_racks", "kind": "crane_rack", "id": "rack-0"})
    bld = plane("Building mesh", (0, 3, 3.2)); bld["wh_obstacles"] = "[]"
    loads = bpy.data.collections.new("Warehouse Loads"); scene.collection.children.link(loads)
    pallet_mesh = plane("Pallet mesh", (0, 3, 3.4)); loads.objects.link(pallet_mesh)
    settle()
    check("Deck" in auto_floors() and not ({"Rack mesh", "Building mesh", "Pallet mesh"} & auto_floors()), f"systems, buildings and loads are never floors {sorted(auto_floors())}")
    check(on(feet(line), 2.0), f"feet still on the deck {feet(line)}")
    table = plane("Table", (0, 3, 3.6)); settle()
    check(on(feet(line), 3.6), f"a plain table above the deck takes the legs {feet(line)}")
    select_only(rack); r = bpy.ops.conveyor.mark_floor(mark='FLOOR')
    check(r == {'CANCELLED'} and "wh_floor" not in rack, "Mark as floor leaves another add-on's object alone")
    select_only(deck); r = bpy.ops.conveyor.mark_floor(mark='FLOOR'); settle()
    check(r == {'FINISHED'} and floors.floor_mark(deck) is True and floors.marked_by_us(deck), "Mark as floor writes wh_floor on the user's own deck")
    check({"Deck", "Table"} <= auto_floors(), f"R3.1: a marked floor joins the automatic ones {sorted(auto_floors())}")
    check(on(feet(line), 3.6), f"the legs land on the first surface below: the plain table {feet(line)}")
    select_only(table); r = bpy.ops.conveyor.mark_floor(mark='NOT_FLOOR'); settle()
    check(r == {'FINISHED'} and floors.floor_mark(table) is False and "Table" not in auto_floors() and on(feet(line), 2.0),
          f"Not a floor: the legs pass the table and land on the deck {feet(line)}")
    select_only(table); bpy.ops.conveyor.mark_floor(mark='AUTO'); select_only(deck); r = bpy.ops.conveyor.mark_floor(mark='AUTO'); settle()
    check(r == {'FINISHED'} and "wh_floor" not in deck and "wh_floor" not in table and on(feet(line), 3.6), f"Auto: back to the automatic rule {feet(line)}")
    table["wh_floor"] = True  # as the Floorplan add-on marks its slabs
    settle()
    check(on(feet(line), 3.6) and {"Table", "Deck"} <= auto_floors(), "another add-on's wh_floor joins the automatic floors (R3.1)")
    select_only(table); r = bpy.ops.conveyor.mark_floor(mark='AUTO')
    check(r == {'CANCELLED'} and bool(table.get("wh_floor")), "another add-on's mark is never cleared here")
    scene.conveyor_settings.floors_marked_only = True; settle()
    check(auto_floors() == {"Table"} and on(feet(line), 3.6), f"Marked only: the marked table alone {sorted(auto_floors())}")
    scene.conveyor_settings.floors_marked_only = False; settle()
    mine = bpy.data.collections.new("My floors"); scene.collection.children.link(mine); mine.objects.link(deck)
    scene.conveyor_settings.floor_collection = mine; ctx.view_layer.update()
    check(on(feet(line), 2.0), f"the user's Floors collection wins over the marks {feet(line)}")
    scene.conveyor_settings.floor_collection = None; ctx.view_layer.update()
    del table["wh_floor"]; settle()

    # ---- R15: a port held by a route (any object carrying wh_port_links)
    rack_sys = empty("Crane rack", (20.0, 0.0, 0.0))
    rack_sys["wh_system"] = json.dumps({"version": 2, "addon": "warehouse_racks", "kind": "crane_rack", "id": "rack-uuid-1", "object": "Crane rack",
                                        "label": "Crane rack", "level": 0, "footprint": [[-1, -1], [1, -1], [1, 1], [-1, 1]], "height_m": 6.0, "clearance_m": 0.0, "zone": None})
    rack_sys["wh_ports"] = json.dumps([{"version": 2, "id": "aisle0_out", "role": "out", "kind": "point", "position": [0, 0, 0], "heading_deg": 0.0,
                                        "width_m": 0.5, "rate_ph": 40.0, "capacity_ph": 40.0, "load": None}])
    route = empty("Route", (25.0, 0.0, 0.0))
    route["wh_system"] = json.dumps({"version": 2, "addon": "warehouse_floorplan", "kind": "route", "id": "route-uuid-2", "object": "Route", "label": "Route AMR-2",
                                     "level": 0, "footprint": [], "height_m": 0.0, "clearance_m": 0.0, "zone": None})
    route["wh_port_links"] = json.dumps([{"version": 2, "system_id": "rack-uuid-1", "system": "Crane rack", "port": "aisle0_out", "role": "out", "anchor": "start", "by": "warehouse_floorplan"}])
    ctx.view_layer.update()
    holder = ports.holder_of(scene, rack_sys, "aisle0_out")
    check(holder is route and ports.holder_name(holder) == "Route AMR-2", "a route's wh_port_links holds the port, named by its label")
    feeder = create_line(ctx, Vector((20.0, 0.0, 0.0)), 0.0); feeder.name = "From rack"; ctx.view_layer.update()
    docked = ports.sync_port(ctx, feeder)
    n = ports.note(feeder)
    check(not docked and ports.dock_at(feeder, "origin") is None, "a line cannot dock on a port a route holds")
    check(n is not None and n.get("kind") == "taken" and "Route AMR-2" in n.get("text", "") and n.get("foreign") is True, f"the line says who holds it: {n}")
    r = bpy.ops.conveyor.port_take_over(line=feeder.name, system="Crane rack", port="aisle0_out")
    check(r == {'CANCELLED'} and json.loads(route["wh_port_links"])[0]["port"] == "aisle0_out", "no take-over from another add-on's record")
    route["wh_port_links"] = "[]"
    docked = ports.sync_port(ctx, feeder); ctx.view_layer.update()
    check(docked and ports.dock_at(feeder, "origin") is not None and ports.holder_of(scene, rack_sys, "aisle0_out") is feeder, "the route let go: the line docks and holds the port")
    links = feeder.get("wh_port_links"); v1 = feeder.get("wh_port_link")
    check(isinstance(links, str) and json.loads(links)[0]["system_id"] == "rack-uuid-1" and json.loads(links)[0]["port"] == "aisle0_out", "the line's links name system_id + port")
    check(v1 is not None and hasattr(v1, "to_dict") and v1.to_dict().get("port") == "aisle0_out", "the v1 wh_port_link stays a dict")

    # ---- R2: records in both forms; our writes compact JSON, written once
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(30.0, 0.0, 0.5)); pallet = ctx.view_layer.objects.active; pallet.name = "Pallet"; pallet.scale = (1.2, 0.8, 1.0)
    load = {"kind": "pallet", "id": "EUR1", "length_m": 1.2, "width_m": 0.8, "height_m": 1.0, "forward_axis": "X", "object": "Pallet"}
    pallet["wh_load"] = load
    as_dict = wh_load(pallet)
    pallet["wh_load"] = json.dumps(load)
    as_str = wh_load(pallet)
    check(as_dict == load and as_str == load, "wh_load reads the same as a dict and as a JSON string")
    carrier = create_line(ctx, Vector((30.0, 5.0, 0.0)), 0.0); carrier.name = "Carrier"
    with suspended_rebuild():
        carrier.conveyor_line.populate = True
        carrier.conveyor_line.populate_item = pallet
    build_line(ctx, carrier); ctx.view_layer.update()
    desc_str = ports._load_descriptor(ctx, carrier)
    pallet["wh_load"] = load
    build_line(ctx, carrier); ctx.view_layer.update()
    desc_dict = ports._load_descriptor(ctx, carrier)
    check(desc_str == desc_dict and desc_str.get("forward_axis") == "X" and abs(float(desc_str.get("length_m", 0)) - 1.2) < 0.05,
          f"the line's published load is the same from both forms: {desc_str}")
    s = carrier["wh_system"]
    check(isinstance(s, str) and s == json.dumps(json.loads(s), separators=(",", ":")), "wh_system is compact JSON")
    check(all(isinstance(carrier.get(k), str) for k in ("wh_system", "wh_ports", "wh_path")), "wh_ports and wh_path are JSON strings")
    check(wh_records.write_record(carrier, "wh_system", json.loads(s)) is False, "an unchanged record is not rewritten")
    old = empty("Old rack", (40.0, 0.0, 0.0))
    try:
        old["wh_ports"] = [{"version": 2, "id": "p_out", "role": "out", "kind": "point", "position": [0.0, 0.0, 0.0], "heading_deg": 0.0, "width_m": 0.5}]
        got = ports.ports_of(old)
        check(len(got) == 1 and got[0]["id"] == "p_out", "wh_ports as an IDProperty list (a pre-v2.1 file) still reads")
    except Exception as e:
        print("note: an IDProperty list of dicts is not assignable here:", e)

    # ---- R10: levels per origin and per port
    host = empty("Building", (0.0, 0.0, 0.0))
    host["wh_levels"] = json.dumps([{"version": 2, "id": "mezz1", "label": "Mezzanine 1", "z": 4.2, "footprint": [[-10, -10], [60, -10], [60, 40], [-10, 40]]}])
    ctx.view_layer.update()
    on_mezz = create_line(ctx, Vector((5.0, 20.0, 4.2)), 0.0); on_mezz.name = "On mezz"; ctx.view_layer.update()
    sys_rec = rec(on_mezz, "wh_system"); port_recs = rec(on_mezz, "wh_ports")
    check(sys_rec["level"] == "mezz1" and all(p["level"] == "mezz1" for p in port_recs), f"a line on the mezzanine: level mezz1 on wh_system and both ports {[p['level'] for p in port_recs]}")
    ground = create_line(ctx, Vector((5.0, 25.0, 0.0)), 0.0); ground.name = "Ground"; ctx.view_layer.update()
    check(rec(ground, "wh_system")["level"] == 0 and all(p["level"] == 0 for p in rec(ground, "wh_ports")), "a line on the ground: level 0")
    outside = create_line(ctx, Vector((80.0, 20.0, 4.2)), 0.0); outside.name = "Outside"; ctx.view_layer.update()
    check(rec(outside, "wh_system")["level"] == 0, "outside the footprint at that height: level 0")
    incline = create_line(ctx, Vector((15.0, -5.0, 0.0)), 0.0); incline.name = "Incline"
    with suspended_rebuild():
        seg = incline.conveyor_line.segments[0]; seg["length_mm"] = 20000.0; seg["rise_mm"] = 4300.0
    build_line(ctx, incline); ctx.view_layer.update()
    ex, ey, ez, _h = incline.conveyor_line.end_pose
    prts = {p["id"]: p for p in rec(incline, "wh_ports")}
    check(ez > 4.15 and rec(incline, "wh_system")["level"] == 0 and prts["line_in"]["level"] == 0 and prts["line_out"]["level"] == "mezz1",
          f"an incline: in on the ground, out on the mezzanine (end z {ez:.2f}, levels {prts['line_in']['level']} -> {prts['line_out']['level']})")
    host.location.z = 1.0; ctx.view_layer.update(); build_line(ctx, on_mezz); ctx.view_layer.update()
    check(rec(on_mezz, "wh_system")["level"] == 0, "the building raised 1 m: its mezzanine is above the line now (host pose counts)")
    host.location.z = 0.0; ctx.view_layer.update()

    # ---- R11: the registry entry leaves on unregister
    bpy.ops.preferences.addon_disable(module=PKG)
    reg = json.loads(ctx.window_manager.get("wh_addons", "{}") or "{}")
    check("conveyor_system" not in reg, f"wh_addons entry removed on unregister {list(reg)}")
    bpy.ops.preferences.addon_enable(module=PKG)
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
