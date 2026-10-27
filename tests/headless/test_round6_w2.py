"""Round 6 wave 2 (interop contract v2.1, R6 + R7): the public operators
conveyor.set_line_rate / set_line_item / dock_line (keyed by wh_system id,
idempotent, recording `by`), operator_exists instead of the hasattr trap, and
the Shift+D duplicate rule order. Blender -b --python tests/headless/test_round6_w2.py
(the installed add-on, or dev through BLENDER_USER_EXTENSIONS). With the Racks add-on
enabled in the config (or CONVEYOR_TEST_WITH_RACKS=1: run_all.sh runs it both ways) the
"Racks absent" checks turn into "Racks builds the item" checks."""
import json, math, os, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
if os.environ.get("CONVEYOR_TEST_WITH_RACKS") == "1" and "bl_ext.user_default.warehouse_racks" not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module="bl_ext.user_default.warehouse_racks")  # the sandbox's Racks (the joint suite's tag)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line, BUILD_STATS, resolve_width_mm
from bl_ext.user_default.conveyor_system.operators import ports, pick_item
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
from bl_ext.user_default.conveyor_system.operators.populate import wh_load
from bl_ext.user_default.conveyor_system.config import loader
from bl_ext.user_default.conveyor_system._wh import ops as wh_ops
ctx = bpy.context; scene = ctx.scene; fails = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
def rec(obj, key):
    raw = obj.get(key)
    return json.loads(raw) if isinstance(raw, str) else None
def lid(obj): return rec(obj, "wh_system")["id"]
def builds(): return BUILD_STATS["builds"]
def insts_of(line, name):
    dg = ctx.evaluated_depsgraph_get()
    return sum(1 for i in dg.object_instances if i.is_instance and i.parent and i.parent.original == line and i.object.name == name)
def empty(name, loc=(0.0, 0.0, 0.0)):
    o = bpy.data.objects.new(name, None); scene.collection.objects.link(o); o.location = loc
    return o
def system(name, sid, loc, ports_list):
    o = empty(name, loc)
    o["wh_system"] = json.dumps({"version": 2, "addon": "warehouse_racks", "kind": "crane_rack", "id": sid, "object": name, "label": name,
                                 "level": 0, "footprint": [[-1, -1], [1, -1], [1, 1], [-1, 1]], "height_m": 6.0, "clearance_m": 0.0, "zone": None})
    o["wh_ports"] = json.dumps(ports_list)
    ctx.view_layer.update()
    return o
MAKE_CALLS = []
class WAREHOUSE_OT_make_load(bpy.types.Operator):
    """A stand-in for Racks' warehouse.make_load: builds the load object in Warehouse Loads."""
    bl_idname = "warehouse.make_load"; bl_label = "Make Load (test)"
    load_id: bpy.props.StringProperty()
    def execute(self, context):
        MAKE_CALLS.append(self.load_id)
        coll = bpy.data.collections.get("Warehouse Loads")
        if coll is None:
            coll = bpy.data.collections.new("Warehouse Loads"); scene.collection.children.link(coll)
        name = "Pallet " + self.load_id.replace(":", "-")
        if bpy.data.objects.get(name) is None:
            bpy.ops.mesh.primitive_cube_add(size=1.0); obj = ctx.view_layer.objects.active; obj.name = name; obj.scale = (1.2, 0.8, 1.0)
            for c in list(obj.users_collection): c.objects.unlink(obj)
            coll.objects.link(obj)
            obj["wh_load"] = {"kind": "pallet", "id": self.load_id, "length_m": 1.2, "width_m": 0.8, "height_m": 1.0, "forward_axis": "X", "object": name}
        return {'FINISHED'}
racks_here = wh_ops.operator_exists(bpy.ops, "warehouse.make_load")
print("note: the Racks add-on is", "ENABLED in this config" if racks_here else "absent")
# rule 9 (SUITE_PLAN): each run covers one branch; run_all.sh runs both
if racks_here:
    print("SKIP: the Racks-absent checks (the hasattr trap with no make_load, our placeholder load): Racks is enabled in this run")
else:
    print("SKIP: the Racks-present checks (Racks' warehouse.make_load builds the load): Racks is not enabled in this run")
try:
    # ---- R7: the hasattr trap, with Racks absent
    check(hasattr(bpy.ops, "warehouse") and hasattr(bpy.ops.warehouse, "make_load"), "(the trap) hasattr on bpy.ops says yes for anything")
    check(racks_here or not wh_ops.operator_exists(bpy.ops, "warehouse.make_load"), "operator_exists says warehouse.make_load is NOT registered (Racks absent)")
    check(wh_ops.operator_exists(bpy.ops, "conveyor.set_line_rate") and wh_ops.operator_exists(bpy.ops, "conveyor.set_line_item") and wh_ops.operator_exists(bpy.ops, "conveyor.dock_line"), "the three R6 operators are registered")
    L = loader.get_segment_catalog().straight_default_mm / 1000.0
    pallet_load = {"kind": "pallet", "id": "pallet:EUR1:Wood:1.2", "length_m": 1.2, "width_m": 0.8, "height_m": 1.0, "forward_axis": "X"}
    rack = system("Crane rack", "rack-uuid-1", (20.0, 0.0, 0.0), [
        {"version": 2, "id": "aisle0_out", "role": "out", "kind": "point", "position": [0, 0, 0], "heading_deg": 0.0, "width_m": 0.8,
         "rate_ph": 40.0, "capacity_ph": 40.0, "load": pallet_load},
        {"version": 2, "id": "aisle0_in", "role": "in", "kind": "point", "position": [0, round(L, 3), 0], "heading_deg": 0.0, "width_m": 0.8,
         "rate_ph": 30.0, "capacity_ph": 30.0, "load": None}])
    probe = create_line(ctx, Vector((50.0, 0.0, 0.0)), 0.0); probe.name = "Probe"; ctx.view_layer.update()
    _c, done, msg = pick_item.apply_port_load(ctx, probe, rack, ports.port_by_id(rack, "aisle0_out"), "out")
    if racks_here:
        check(not done and "making" in msg, f"with Racks here a missing port load is being made: {msg}")
    else:
        check(not done and "not in the file" in msg and "making" not in msg, f"with Racks absent a port load is reported missing, not 'making': {msg}")

    # ---- R6: set_line_rate
    line = create_line(ctx, Vector((0.0, 0.0, 0.0)), 0.0); line.name = "Main"
    line.conveyor_line.populate = True
    line.conveyor_line.population_pct = 40.0
    ctx.view_layer.update()
    r = bpy.ops.conveyor.set_line_rate(line_id=lid(line), rate_ph=45.0, by="warehouse_racks")
    rate_rec = rec(line, "conveyor_rate_from")
    want_pct = 100.0 * 45.0 * (0.6 + 0.05) / (3600.0 * 0.5)  # 2.22: a shim, the Population carrying 45/h of totes at 0.5 m/s
    check(r == {'FINISHED'} and abs(line.conveyor_line.population_pct - want_pct) < 1e-3, f"set_line_rate sets the Population that carries it ({line.conveyor_line.population_pct:.3f} %)")
    check(rate_rec == {"rate_ph": 45.0, "own_pct": 40.0, "by": "warehouse_racks"}, f"and records by + the own setting {rate_rec}")
    b = builds(); r = bpy.ops.conveyor.set_line_rate(line_id=lid(line), rate_ph=45.0, by="warehouse_racks")
    check(r == {'FINISHED'} and builds() == b, "the same rate again: no rebuild")
    r = bpy.ops.conveyor.set_line_rate(line_id=lid(line), rate_ph=45.0, by="pallet_shuttle")
    check(r == {'FINISHED'} and builds() == b and rec(line, "conveyor_rate_from")["by"] == "pallet_shuttle", "another caller, same rate: only by changes")
    r = bpy.ops.conveyor.set_line_rate(line_id=lid(line), rate_ph=0.0, by="pallet_shuttle")
    check(r == {'FINISHED'} and abs(line.conveyor_line.population_pct - 40.0) < 1e-6 and rec(line, "conveyor_rate_from") is None and builds() > b, "0 releases: the own setting is back")
    b = builds(); r = bpy.ops.conveyor.set_line_rate(line_id=lid(line), rate_ph=0.0)
    check(r == {'FINISHED'} and builds() == b, "releasing again: nothing")
    check(bpy.ops.conveyor.set_line_rate(line_id="no-such-line", rate_ph=10.0) == {'CANCELLED'}, "unknown line_id cancels")
    check(bpy.ops.conveyor.set_line_rate(line_id=lid(line), rate_ph=-5.0) == {'CANCELLED'}, "a negative rate cancels")

    # ---- R6: set_line_item (placeholder, make_load, existing object)
    r = bpy.ops.conveyor.set_line_item(line_id=lid(line), load_json=json.dumps(pallet_load), by="warehouse_racks")
    item = line.conveyor_line.populate_item; ctx.view_layer.update()
    check(r == {'FINISHED'} and item is not None and (racks_here or item.name.startswith("Load ")) and wh_load(item) is not None and wh_load(item)["id"] == pallet_load["id"],
          f"{'Racks builds the load object' if racks_here else 'without Racks a placeholder load object is made'}: {item.name if item else None}")
    dims = tuple(round(v, 2) for v in item.dimensions) if item else ()
    check((racks_here or dims == (1.2, 0.8, 1.0)) and line.conveyor_line.populate_forward_axis == 'X' and line.conveyor_line.populate, f"sized from the record, axis X, populate on {dims}")
    check(insts_of(line, item.name) > 0, f"the placeholder rides the line ({insts_of(line, item.name)} instances)")
    check(rec(line, "conveyor_item_from") == {"by": "warehouse_racks", "load_id": pallet_load["id"], "object": item.name}, "item record with by")
    check(racks_here or isinstance(item.get("wh_load"), str), "our placeholder's wh_load is a JSON string (R2, 2.8.1)")
    bpy.ops.mesh.primitive_cube_add(size=0.5, location=(70.0, 0.0, 0.25)); my_tote = ctx.view_layer.objects.active; my_tote.name = "My tote"
    custom_port = {"version": 2, "id": "hand_out", "role": "out", "kind": "point", "position": [0, 0, 0], "heading_deg": 0.0, "width_m": 0.5, "rate_ph": 10.0,
                   "capacity_ph": 10.0, "load": {"kind": "custom", "id": "custom:my-tote", "object": "My tote", "length_m": 0.5, "width_m": 0.5, "height_m": 0.5, "forward_axis": "Y", "make": None}}
    hand = system("Hand station", "hand-uuid-1", (70.0, 5.0, 0.0), [custom_port])
    _c, done, msg = pick_item.apply_port_load(ctx, probe, hand, custom_port, "out")
    check(done and isinstance(my_tote.get("wh_load"), str) and wh_load(my_tote)["id"] == "custom:my-tote", f"a custom load's stamp is written as a JSON string: {msg}")
    b = builds(); r = bpy.ops.conveyor.set_line_item(line_id=lid(line), load_json=json.dumps(pallet_load), by="warehouse_racks")
    check(r == {'FINISHED'} and builds() == b and line.conveyor_line.populate_item == item, "the same load again: no rebuild")
    if not racks_here:
        bpy.utils.register_class(WAREHOUSE_OT_make_load)  # a stand-in; never over the real one
    check(wh_ops.operator_exists(bpy.ops, "warehouse.make_load"), "operator_exists sees the registered make_load")
    load2 = dict(pallet_load, id="pallet:EUR1:Plastic:1.0")
    r = bpy.ops.conveyor.set_line_item(line_id=lid(line), load_json=json.dumps(load2), by="warehouse_racks")
    item2 = line.conveyor_line.populate_item
    # With Racks: ITS object, though it records the load as warehouse_common spells it ("...:1", 2.24.2,
    # loads.same_load in WC 0.6.6) -- 2.24.1 missed it and made its own "Load pallet:EUR1:Plastic:1.0".
    from bl_ext.user_default.conveyor_system._wh import loads as wh_loads
    made = (MAKE_CALLS == [load2["id"]] and item2 is not None and item2.name == "Pallet pallet-EUR1-Plastic-1.0") if not racks_here else (
        item2 is not None and wh_load(item2) is not None and item2.name == wh_loads.object_name(load2["id"])
        and wh_loads.same_load(wh_load(item2)["id"], load2["id"]) and bpy.data.objects.get("Load " + load2["id"]) is None)
    check(r == {'FINISHED'} and made, f"make_load builds the item when Racks is here, and the line takes it ({MAKE_CALLS if not racks_here else item2.name if item2 else None}"
                                      f"{'' if not racks_here else ', ' + str(wh_load(item2).get('id') if item2 is not None and wh_load(item2) else None)})")
    b = builds(); r = bpy.ops.conveyor.set_line_item(line_id=lid(line), load_json=json.dumps(load2), by="warehouse_racks")
    check(r == {'FINISHED'} and (racks_here or MAKE_CALLS == [load2["id"]]) and builds() == b and line.conveyor_line.populate_item == item2, "an existing load object is found in Warehouse Loads, make_load not called again")
    load3 = dict(load2, id=wh_loads.canonical_load_id(load2["id"]), object="")  # the same load, spelled the other way, no object name
    b = builds(); r = bpy.ops.conveyor.set_line_item(line_id=lid(line), load_json=json.dumps(load3), by="warehouse_racks")
    check(r == {'FINISHED'} and builds() == b and line.conveyor_line.populate_item == item2 and (racks_here or MAKE_CALLS == [load2["id"]]),
          f"'{load3['id']}' is the same load as '{load2['id']}': the same object, no rebuild, make_load not called")
    check(bpy.ops.conveyor.set_line_item(line_id=lid(line), load_json="{}") == {'CANCELLED'}, "a load without an id cancels")
    check(bpy.ops.conveyor.set_line_item(line_id="nope", load_json=json.dumps(load2)) == {'CANCELLED'}, "unknown line_id cancels")

    # ---- R6: dock_line
    feeder = create_line(ctx, Vector((40.0, 0.0, 0.0)), 0.0); feeder.name = "From rack"; ctx.view_layer.update()
    r = bpy.ops.conveyor.dock_line(line_id=lid(feeder), system_id="rack-uuid-1", port_id="aisle0_out", anchor="start", by="warehouse_racks")
    d = ports.dock_at(feeder, "origin")
    check(r == {'FINISHED'} and d is not None and d["system_id"] == "rack-uuid-1" and d["port"] == "aisle0_out" and d.get("by") == "warehouse_racks", f"dock_line start: origin docked at the out port, by recorded {d}")
    check((feeder.location - Vector((20.0, 0.0, 0.0))).length < 1e-3 and not feeder.conveyor_line.reverse, "the line starts on the port, forward")
    check(abs(resolve_width_mm(feeder.conveyor_line) - 800.0) < 0.5, f"width from the port ({resolve_width_mm(feeder.conveyor_line):.0f} mm)")
    links = rec(feeder, "wh_port_links")
    check(links and links[0]["system_id"] == "rack-uuid-1" and links[0]["port"] == "aisle0_out" and links[0]["anchor"] == "start", "wh_port_links written")
    b = builds(); r = bpy.ops.conveyor.dock_line(line_id=lid(feeder), system_id="rack-uuid-1", port_id="aisle0_out", anchor="start", by="warehouse_racks")
    check(r == {'FINISHED'} and builds() == b, "docking again at the same port: no rebuild")
    dj.sync_feeder(ctx, feeder); ports.sync_links(ctx, scene)
    check(ports.dock_at(feeder, "origin").get("by") == "warehouse_racks", "by survives the sync passes")
    r = bpy.ops.conveyor.dock_line(line_id=lid(feeder), system_id="rack-uuid-1", port_id="aisle0_in", anchor="end", by="warehouse_racks")
    d_end = ports.dock_at(feeder, "end"); d_origin = ports.dock_at(feeder, "origin")
    check(r == {'FINISHED'} and d_end is not None and d_end["port"] == "aisle0_in" and d_origin is not None and d_origin["port"] == "aisle0_out",
          f"dock_line end on a line whose origin is taken: the far end docks, the origin stays {d_end}")
    check(len(rec(feeder, "wh_port_links")) == 2, "two links, one per dock")
    free = create_line(ctx, Vector((60.0, 0.0, 0.0)), 0.0); free.name = "Free"; ctx.view_layer.update()
    r = bpy.ops.conveyor.dock_line(line_id=lid(free), system_id="rack-uuid-1", port_id="aisle0_in", anchor="end", by="warehouse_racks")
    check(r == {'CANCELLED'} and ports.dock_at(free, "origin") is None, "a port another line holds cancels")
    rack_b = system("Rack B", "rack-uuid-2", (30.0, 10.0, 0.0), [
        {"version": 2, "id": "b_in", "role": "in", "kind": "point", "position": [0, 0, 0], "heading_deg": 180.0, "width_m": 0.5, "rate_ph": 20.0, "capacity_ph": 20.0, "load": None}])
    r = bpy.ops.conveyor.dock_line(line_id=lid(free), system_id="rack-uuid-2", port_id="b_in", anchor="end", by="warehouse_racks")
    d = ports.dock_at(free, "origin")
    check(r == {'FINISHED'} and d is not None and d["port"] == "b_in" and free.conveyor_line.reverse and (free.location - Vector((30.0, 10.0, 0.0))).length < 1e-3,
          f"dock_line end on a free line: reversed, its origin (flow end) on the in port {d}")
    check(bpy.ops.conveyor.dock_line(line_id=lid(free), system_id="nope", port_id="b_in", anchor="end") == {'CANCELLED'}, "unknown system_id cancels")
    check(bpy.ops.conveyor.dock_line(line_id=lid(free), system_id="rack-uuid-2", port_id="nope", anchor="end") == {'CANCELLED'}, "unknown port_id cancels")
    check(bpy.ops.conveyor.dock_line(line_id=lid(free), system_id="rack-uuid-2", port_id="b_in", anchor="middle") == {'CANCELLED'}, "a bad anchor cancels")
    check(bpy.ops.conveyor.dock_line(line_id=lid(free), system_id="rack-uuid-2", port_id="b_in", anchor="start") == {'CANCELLED'}, "start on an in port cancels")
    check(bpy.ops.conveyor.dock_line(line_id="nope", system_id="rack-uuid-2", port_id="b_in", anchor="end") == {'CANCELLED'}, "unknown line_id cancels")

    # ---- dock_line applies the port's load before it returns; set_line_rate then publishes at once (2.11.1)
    loaded_rack = system("Crane rack L", "rack-uuid-3", (120.0, 0.0, 0.0), [
        {"version": 2, "id": "aisle0_out", "role": "out", "kind": "point", "position": [0, 0, 0], "heading_deg": 0.0, "width_m": 0.8,
         "rate_ph": 40.0, "capacity_ph": 40.0, "load": dict(pallet_load, id="pallet:EUR1:Wood:1.5", object="WH Load EUR1 1.5 m")}])
    carrier2 = create_line(ctx, Vector((140.0, 0.0, 0.0)), 0.0); carrier2.name = "Carrier 2"; ctx.view_layer.update()
    check(carrier2.conveyor_line.populate_item is None and not carrier2.conveyor_line.populate, "a new line carries nothing")
    r = bpy.ops.conveyor.dock_line(line_id=lid(carrier2), system_id="rack-uuid-3", port_id="aisle0_out", anchor="start", by="warehouse_racks")
    item3 = carrier2.conveyor_line.populate_item
    check(r == {'FINISHED'} and item3 is not None and wh_load(item3) is not None and wh_load(item3)["id"] == "pallet:EUR1:Wood:1.5" and carrier2.conveyor_line.populate,
          f"right after dock_line the line carries the port's load ({item3.name if item3 else None}), no pump")
    check(ports.dock_at(carrier2, "origin").get("load_id") == "pallet:EUR1:Wood:1.5", "the dock records the load as applied (no retry on later passes)")
    pop_before = carrier2.conveyor_line.population_pct
    r = bpy.ops.conveyor.set_line_rate(line_id=lid(carrier2), rate_ph=30.0, by="warehouse_racks")
    outs = {p["id"]: p for p in rec(carrier2, "wh_ports")}; lk = rec(carrier2, "wh_port_links")
    # Since 2.23 (R22) the rack's out-feed leads the line docked at it: the line keeps the
    # Population set_line_rate gives it, and publishes the flow in effect -- the port's 40/h -- at once.
    check(r == {'FINISHED'} and carrier2.conveyor_line.population_pct != pop_before and abs(outs["line_out"]["rate_ph"] - 40.0) < 0.6
          and abs(outs["line_in"]["rate_ph"] - 40.0) < 0.6, f"set_line_rate(30) on a rack-led line: its own Population is kept, the ports publish the port's 40/h at once ({outs['line_out']['rate_ph']})")
    check(lk and abs(lk[0]["rate_ph"] - 40.0) < 0.6, f"and the link ({lk[0]['rate_ph'] if lk else None})")
    empty_line = create_line(ctx, Vector((160.0, 0.0, 0.0)), 0.0); empty_line.name = "No goods"; ctx.view_layer.update()
    r = bpy.ops.conveyor.set_line_rate(line_id=lid(empty_line), rate_ph=30.0, by="warehouse_racks")
    check(r == {'FINISHED'} and abs(empty_line.conveyor_line.population_pct - 100.0 * 30.0 * 0.65 / 1800.0) < 1e-3,
          "a rate on a line without goods is stored as its Population (FINISHED, with a warning that it is not published)")

    # ---- a 0.18-style file: link entries an older Racks wrote onto lines are dropped by their owner (R14)
    stale = create_line(ctx, Vector((180.0, 0.0, 0.0)), 0.0); stale.name = "Stale links"; ctx.view_layer.update()
    stale["wh_port_links"] = json.dumps([{"version": 2, "system_id": "rack-uuid-1", "system": "Crane rack", "port": "aisle0_in", "role": "in", "anchor": "end", "rate_ph": 12.0, "by": "warehouse_racks"}])
    stale["wh_port_link"] = {"system": "Crane rack", "port": "aisle0_in", "role": "in", "rate_ph": 12.0, "by": "warehouse_racks"}
    build_line(ctx, stale); ctx.view_layer.update()
    check(stale.get("wh_port_links") is None and stale.get("wh_port_link") is None, "an undocked line sheds the link entries an older Racks wrote on it")
    feeder["wh_port_links"] = json.dumps(json.loads(feeder["wh_port_links"]) + [{"version": 2, "system_id": "rack-uuid-1", "port": "aisle0_out", "role": "out", "anchor": "start", "by": "warehouse_racks"}])
    build_line(ctx, feeder); ctx.view_layer.update()
    lk2 = rec(feeder, "wh_port_links")
    check(lk2 and all(e.get("by") == "conveyor_system" for e in lk2) and len(lk2) == 2, f"a docked line's links are only its own after a rebuild ({[e.get('by') for e in lk2]})")

    # ---- the Shift+D duplicate rule: the copy gets a new id, the original keeps its links
    uid_before = lid(feeder); links_before = feeder["wh_port_links"]; dock_before = feeder["conveyor_port"]
    copy = feeder.copy(); copy.data = feeder.data.copy(); scene.collection.objects.link(copy)  # what Shift+D leaves: same custom properties, a new name
    ctx.view_layer.update(); dj.run_sync(scene); ctx.view_layer.update()
    if lid(copy) == uid_before:
        build_line(ctx, copy); ctx.view_layer.update()
    check(copy.name != feeder.name and lid(copy) != uid_before and copy.get("conveyor_uuid") != feeder.get("conveyor_uuid"), f"the copy has a new id ({lid(copy)[:8]} vs {uid_before[:8]})")
    check(lid(feeder) == uid_before and feeder["wh_port_links"] == links_before and feeder["conveyor_port"] == dock_before, "the original keeps its id, docks and links")
    check(ports.holder_of(scene, rack, "aisle0_out") is feeder and not ports.docks(copy) and copy.get("wh_port_links") is None, "the copy holds no port and carries no links")

    # ---- R16: a z_free port keeps the line's own height; a plain port sets z
    doors = system("Building doors", "bld-uuid-1", (80.0, 0.0, 0.0), [
        {"version": 2, "id": "door1", "role": "out", "kind": "point", "position": [0, 0, 0], "heading_deg": 0.0, "width_m": 1.26, "z_free": True,
         "rate_ph": 16.0, "capacity_ph": 16.0, "load": None},
        {"version": 2, "id": "door2", "role": "in", "kind": "point", "position": [6, 0, 0], "heading_deg": 0.0, "width_m": 1.26, "z_free": True,
         "rate_ph": 16.0, "capacity_ph": 16.0, "load": None},
        {"version": 2, "id": "lift_out", "role": "out", "kind": "point", "position": [12, 0, 0.6], "heading_deg": 0.0, "width_m": 0.8,
         "rate_ph": 16.0, "capacity_ph": 16.0, "load": None}])
    high = create_line(ctx, Vector((90.0, 5.0, 0.8)), 0.0); high.name = "Dock line"; ctx.view_layer.update()
    r = bpy.ops.conveyor.dock_line(line_id=lid(high), system_id="bld-uuid-1", port_id="door1", anchor="start", by="warehouse_floorplan")
    check(r == {'FINISHED'} and ports.dock_at(high, "origin") is not None and abs(high.location.z - 0.8) < 1e-4 and (high.location.xy - Vector((80.0, 0.0))).length < 1e-3,
          f"dock_line at a z_free door: XY from the port, the line keeps its 0.8 m (z {high.location.z:.2f})")
    high2 = create_line(ctx, Vector((100.0, 5.0, 0.8)), 0.0); high2.name = "Dock line 2"; ctx.view_layer.update()
    r = bpy.ops.conveyor.dock_line(line_id=lid(high2), system_id="bld-uuid-1", port_id="lift_out", anchor="start", by="warehouse_floorplan")
    check(r == {'FINISHED'} and abs(high2.location.z - 0.6) < 1e-4, f"a port without z_free sets the height (z {high2.location.z:.2f})")
    via_sync = create_line(ctx, Vector((86.0, 0.0, 0.8)), 0.0); via_sync.name = "To door"; ctx.view_layer.update()
    with_reverse = via_sync.conveyor_line; with_reverse.reverse = True; ctx.view_layer.update()  # its flow end is the origin: the in door
    docked = ports.sync_port(ctx, via_sync)
    check(docked and ports.dock_at(via_sync, "origin")["port"] == "door2" and abs(via_sync.location.z - 0.8) < 1e-4, f"the sync dock at a z_free door keeps the height too (z {via_sync.location.z:.2f})")
    ender = create_line(ctx, Vector((86.0, -L, 0.8)), 0.0); ender.name = "End at door"; ctx.view_layer.update()
    ports.release_port(ctx, via_sync, "origin"); via_sync.location.x = 120.0; ctx.view_layer.update()  # free the door for the next line
    r = bpy.ops.conveyor.dock_line(line_id=lid(ender), system_id="bld-uuid-1", port_id="door2", anchor="end", by="warehouse_floorplan")
    ex, ey, ez, _h = ender.conveyor_line.end_pose; end_world = ender.matrix_world @ Vector((ex, ey, ez))
    check(r == {'FINISHED'} and ports.dock_at(ender, "origin") is not None and abs(ender.location.z - 0.8) < 1e-4,
          f"a free line docked by its end at a z_free door: reversed at the door, still at 0.8 m (z {ender.location.z:.2f})")
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
