"""2.13.0 (Åsmund, 2026-10-13): leg spacing per line; leg-free pieces with a
stand flush at each edge (tunnels, walkways); the pouch sorter as open bags
carrying goods that fit; pouch supports Floor or Ceiling; the R19 load-kind
check; catalogue sizes for stand-in loads.
Blender -b --python tests/headless/test_legs_pouch.py"""
import json, math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, ports, pick_item
from bl_ext.user_default.conveyor_system.props import line_settings as LS
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
from bl_ext.user_default.conveyor_system.model import legs as legs_model, pouch as pouch_model
from bl_ext.user_default.conveyor_system._wh import ops as wh_ops
ctx = bpy.context; scene = ctx.scene; fails = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
def insts(obj, pred):
    """(position, dims, name, faces) of the instances under `obj`, read DURING the
    iteration (depsgraph instance objects are reused once the loop moves on)."""
    dg = ctx.evaluated_depsgraph_get(); out = []
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.parent.original == obj:
            d = tuple(round(c, 3) for c in i.object.dimensions)
            if pred(d, i.object.name):
                faces = len(i.object.data.polygons) if i.object.type == 'MESH' else -1
                out.append((i.matrix_world.translation.copy(), d, i.object.name, faces))
    return out
def feet(obj):
    return [p for p, d, n, f in insts(obj, lambda d, n: abs(d[0] - 0.144) < 0.01 and abs(d[1] - 0.144) < 0.01 and abs(d[2] - 0.012) < 0.005)]
def make(name, loc, pieces, ctype='gravity_roller', populate=False):
    o = create_line(ctx, Vector((100.0, 100.0, 0.0)), 0.0, conveyor_type=ctype); o.name = name; o.location = Vector(loc)
    with suspended_rebuild():
        s = o.conveyor_line
        for k, (length_mm, legs) in enumerate(pieces):
            seg = s.segments[0] if k == 0 else s.segments.add()
            seg.kind = 'STRAIGHT'; seg["length_mm"] = float(length_mm); seg.legs = legs
        s.populate = populate
    ctx.view_layer.update(); build_line(ctx, o); ctx.view_layer.update()
    return o
def system(name, sid, loc, port_list):
    o = bpy.data.objects.new(name, None); scene.collection.objects.link(o); o.location = loc
    o["wh_system"] = json.dumps({"version": 2, "addon": "warehouse_racks", "kind": "cantilever", "id": sid, "object": name, "label": name, "level": 0,
                                 "footprint": [[-1, -1], [1, -1], [1, 1], [-1, 1]], "height_m": 6.0, "clearance_m": 0.0, "zone": None})
    o["wh_ports"] = json.dumps(port_list); ctx.view_layer.update(); return o
try:
    # ---- A. leg spacing per line
    a = make("Spacing", (0.0, 0.0, 1.0), [(12000, True)])
    n15 = len(feet(a))
    a.conveyor_line.support_spacing_m = 3.0; ctx.view_layer.update()
    n30 = len(feet(a))
    check(n15 == 2 * (math.floor(12.0 / 1.5) + 2) and n30 == 2 * (math.floor(12.0 / 3.0) + 2), f"12 m: {n15 // 2} stands at 1.5 m, {n30 // 2} at 3.0 m")
    check("support_spacing_m" in LS.SHARED_SETTINGS, "leg spacing is a multi-edit setting")
    # ---- B. a leg-free piece: none on it, a stand flush with each edge
    b = make("Tunnel", (10.0, 0.0, 1.0), [(4000, True), (3000, False), (4000, True)])
    f = feet(b); ys = sorted(round(p.y, 3) for p in f)
    check(not [y for y in ys if 4.0 + 0.05 < y < 7.0 - 0.05], f"no stands on the leg-free piece ({ys})")
    before = [y for y in ys if y < 4.0]; after = [y for y in ys if y > 7.0]
    check(before and abs(max(before) - (4.0 - 0.035)) < 0.006 and after and abs(min(after) - (7.0 + 0.035)) < 0.006,
          f"a stand flush with each edge (post faces at the gap: {max(before) if before else None}, {min(after) if after else None})")
    gaps = sorted(y2 - y1 for y1, y2 in zip(ys, ys[1:]) if y2 - y1 > 0.2)
    check(all(g <= 1.5 + 0.01 or abs(g - 3.07) < 0.02 for g in gaps), f"elsewhere at most the spacing apart ({gaps})")
    check(abs(float(b.conveyor_line.get("leg_free_span_m", 0)) - 3.0) < 1e-6, "the leg-free span is recorded (3.0 m)")
    c = make("Long span", (20.0, 0.0, 1.0), [(4000, True), (2000, False), (2500, False), (4000, True)])
    yc = sorted(round(p.y, 3) for p in feet(c))
    check(not [y for y in yc if 4.05 < y < 8.45] and abs(float(c.conveyor_line.get("leg_free_span_m")) - 4.5) < 1e-6
          and float(c.conveyor_line.get("leg_free_span_m")) > legs_model.MAX_FREE_SPAN_M, f"neighbouring leg-free pieces form one 4.5 m span (over the {legs_model.MAX_FREE_SPAN_M} m limit)")
    d = make("Free start", (30.0, 0.0, 1.0), [(3000, False), (4000, True)])
    yd = sorted(round(p.y, 3) for p in feet(d))
    check(yd and min(yd) > 3.0 and abs(min(yd) - 3.035) < 0.006, f"a leg-free first piece: the first stand flush after it ({yd[:2]})")
    b.conveyor_line.segments[1].legs = True; ctx.view_layer.update()
    check([y for y in sorted(round(p.y, 3) for p in feet(b)) if 4.05 < y < 6.95] and float(b.conveyor_line.get("leg_free_span_m", 0)) == 0.0, "legs back on: stands on the piece again")
    # ---- C. the pouch sorter: open bags, goods that fit, supports Floor / Ceiling
    scene.conveyor_settings.ceiling_z = 5.0
    p = make("Pouches", (40.0, 0.0, 2.5), [(5000, True)], ctype='pouch_sorter', populate=True)
    pw, ph, pd = (v / 1000.0 for v in pouch_model.pouch_dims_mm(p.conveyor_line.pouch_size, 0, 0, p.conveyor_line.pouch_depth_mm))
    bags = insts(p, lambda d, n: abs(d[0] - pw) < 0.01 and abs(d[1] - pd) < 0.01 and abs(d[2] - ph) < 0.01)
    lids = []
    for i in ctx.evaluated_depsgraph_get().object_instances:  # read during the iteration (instance meshes are reused)
        if i.is_instance and i.parent and i.parent.original == p and i.object.type == 'MESH':
            d = i.object.dimensions
            if abs(d.x - pw) < 0.01 and abs(d.y - pd) < 0.01 and abs(d.z - ph) < 0.01:
                me = i.object.data
                top = max(v.co.z for v in me.vertices)
                lids.append(len([f for f in me.polygons if f.normal.z > 0.5 and f.center.z > top - 1e-4]))
                break
    check(bags and all(f > 5 for _q, _d, _n, f in bags) and lids == [0],
          f"the pouch is an open bag, smooth and rounded (no lid {lids}, {sorted({f for _q, _d, _n, f in bags})} faces)")
    items = insts(p, lambda d, n: n.startswith("Pouch Item") or n.startswith("Placeholder"))
    names = sorted({n for _q, _d, n, _f in items})
    check(items and all(n.startswith("Pouch Item") for n in names), f"goods are the pouch stand-ins ({names})")
    pouch_mm = pouch_model.pouch_dims_mm(p.conveyor_line.pouch_size, 0, 0, p.conveyor_line.pouch_depth_mm)
    check(items and all(pouch_model.fits(tuple(v * 1000 for v in d), pouch_mm) for _q, d, _n, _f in items), "every stand-in fits the pouch")
    floor_feet = [q for q in feet(p) if q.z < 0.1]
    check(len(floor_feet) >= 4, f"Floor supports: portal feet on the floor ({len(floor_feet)})")
    p.conveyor_line.support_mount = 'CEILING'; ctx.view_layer.update()
    rods = insts(p, lambda d, n: abs(d[0] - 0.016) < 0.003 and abs(d[1] - 0.016) < 0.003 and d[2] > 0.5)
    tops = sorted({round(q.z + d[2] / 2.0, 2) for q, d, _n, _f in rods})
    check(not [q for q in feet(p) if q.z < 0.1] and rods and tops == [5.0], f"Ceiling supports: no feet, drop rods up to the Ceiling level ({len(rods)} rods, tops {tops})")
    bpy.ops.mesh.primitive_plane_add(size=20.0, location=(40.0, 2.5, 4.0)); deck = ctx.view_layer.objects.active; deck.name = "Deck above"
    ctx.view_layer.update(); dj.run_sync(scene); ctx.view_layer.update()
    tops = sorted({round(q.z + d[2] / 2.0, 2) for q, d, _n, _f in insts(p, lambda d, n: abs(d[0] - 0.016) < 0.003 and abs(d[1] - 0.016) < 0.003 and d[2] > 0.3)})
    check(tops == [4.0], f"a surface above the rail is the ceiling (rods end at the deck: {tops})")
    check("support_mount" in LS.SHARED_SETTINGS, "pouch supports are a multi-edit setting")
    # ---- D. R19: a load kind a conveyor does not carry is refused, never a crash
    long_load = {"version": 2, "kind": "long", "id": "long:pipe:6000", "length_m": 6.0, "width_m": 0.3, "height_m": 0.3}
    rack = system("Cantilever", "cant-1", (60.0, 0.0, 0.0), [{"version": 2, "id": "arm_out", "role": "out", "kind": "point", "position": [0, 0, 0],
                                                             "heading_deg": 0.0, "width_m": 0.6, "rate_ph": 5.0, "capacity_ph": 5.0, "load": long_load}])
    e = make("Near the cantilever", (60.0, 0.0, 0.0), [(3000, True)])
    docked = ports.sync_port(ctx, e); n = ports.note(e)
    check(not docked and ports.dock_at(e, "origin") is None and n is not None and n.get("kind") == "refused" and "long" in n.get("text", ""),
          f"a port with long loads: no dock, the usual note ({n.get('text') if n else None})")
    r = bpy.ops.conveyor.dock_line(line_id=json.loads(e["wh_system"])["id"], system_id="cant-1", port_id="arm_out", anchor="start", by="test")
    check(r == {'CANCELLED'}, "dock_line refuses it")
    r = bpy.ops.conveyor.set_line_item(line_id=json.loads(e["wh_system"])["id"], load_json=json.dumps(long_load), by="test")
    check(r == {'CANCELLED'} and e.conveyor_line.populate_item is None, "set_line_item refuses a long load")
    applied, done, msg = pick_item.apply_port_load(ctx, e, rack, json.loads(rack["wh_ports"])[0], "out")
    check(not applied and done and "not carried" in msg, f"the eyedropper says so ({msg})")
    accepts = [q.get("accepts") for q in json.loads(e["wh_ports"])]
    check(all(isinstance(x, list) and "long" not in x and "pallet" in x for x in accepts), "the line's own ports publish accepts without long")
    # ---- E. catalogue sizes for a stand-in load (warehouse_common 0.4), when Racks is not here
    if not wh_ops.operator_exists(bpy.ops, "warehouse.make_load"):
        g = make("Catalogue", (70.0, 0.0, 0.0), [(3000, True)])
        r = bpy.ops.conveyor.set_line_item(line_id=json.loads(g["wh_system"])["id"], load_json=json.dumps({"kind": "pallet", "id": "pallet:EUR1:Wood:1.2"}), by="test")
        item = g.conveyor_line.populate_item
        dims = sorted(round(v, 2) for v in item.dimensions) if item else []
        check(r == {'FINISHED'} and dims == [0.8, 1.2, 1.2], f"a pallet id without sizes gets the catalogue's EUR1 box ({dims})")
    else:
        print("note: Racks is here: its make_load builds the pallet (the catalogue fallback is for when it is absent)")
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
