"""2.23.4 (PM, from Racks' 60/40 in-feed render): goods are sized and
published as they ride on each line. A pallet line carries Racks' EUR1
(wh_load: 0.8 m along travel, 1.2 m across, forward axis X) at 100 % and
0.2 m/s; a 90 degree pop-up divert sends 60 % to a branch docked at a crane
in-feed. A pop-up transfer does not turn the goods ("1200 in, 800 out"), so
on the branch the pallet runs 1.2 m along travel. Checked: the length each
line publishes (line_in load: the branch 1.2 m, forward axis Y), every
published population against warehouse_common's build_graph + resolve over
the scene's records (joint check 11), the length the populate tree uses at
each line's end (Item Length), and that no pallet's drawn front passes the
end of either line -- the free end of the main, the hand-over at the in-feed.
Blender -b --python tests/headless/test_goods_turned.py"""
import json, math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line, MODIFIER_NAME
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, stream, ports
from bl_ext.user_default.conveyor_system.operators.detect_junctions import _world_matrix
from bl_ext.user_default.conveyor_system.operators.sync_stats import STATS
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
from bl_ext.user_default.conveyor_system._wh import simple_flow as sf, records as rec
ctx = bpy.context; scene = ctx.scene; fails = []


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)


def settle(n=4):
    for _ in range(n):
        ctx.view_layer.update(); dj.run_sync(scene)
    ctx.view_layer.update()


def sysrec(o):
    return rec.read_record(o.get("wh_system"), {})


def ports_of(o):
    return rec.read_record(o.get("wh_ports"), []) or []


def inp(obj, name):
    mod = obj.modifiers[MODIFIER_NAME]
    for item in mod.node_group.interface.items_tree:
        if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == name:
            return mod.properties.inputs[item.identifier]["value"]
    return None


def resolved():
    records = [{"system": sysrec(o), "ports": ports_of(o), "links": rec.read_record(o.get("wh_port_links"), []),
                "load": rec.read_record(o.get("wh_load"), None)} for o in scene.objects if "wh_system" in o]
    nodes, edges = sf.build_graph(records)
    return sf.resolve(nodes, edges, default_speed=sf.DEFAULT_SPEED)


def compare(objs, tol=5e-4):
    """Joint check 11's way: a follower publishes what resolve gives, a master its slider (at or above)."""
    res = resolved()
    rows, bad = [], []
    for o in objs:
        s = sysrec(o)
        nid = f"{s.get('id')}/line_in"
        if "population" not in s or nid not in res.nodes:
            bad.append((o.name, "not published" if "population" not in s else "no node"))
            continue
        nf = res.nodes[nid]
        pub = float(s["population"])
        rows.append((o.name, round(pub, 5), round(nf.population, 5), nf.is_master))
        if nf.is_master:
            if pub < nf.population - tol:
                bad.append((o.name, "master below resolve", pub, nf.population))
        elif abs(pub - nf.population) > tol:
            bad.append((o.name, "follower differs", pub, nf.population))
    return rows, bad


def end_frame(o):
    """(world position, unit direction of the goods) at `o`'s flow end."""
    end, _local, world = ports._end_pose(ctx, o)
    heading = _world_matrix(o).to_euler().z + end.heading  # 0 = +Y, counter-clockwise
    return world, Vector((-math.sin(heading), math.cos(heading), 0.0)), heading


def overhang(o, item, frames):
    """(the furthest any pallet's drawn front gets past `o`'s end, its drawn length along travel there,
    how many sightings within 2 m of the end) over the frames."""
    world, dirv, _h = end_frame(o)
    worst, along, seen = -9.0, 0.0, 0
    for fr in frames:
        scene.frame_set(fr)
        dg = ctx.evaluated_depsgraph_get()
        for i in dg.object_instances:
            if not (i.is_instance and i.parent and i.parent.original == o and i.object.name == item.name):
                continue
            corners = [i.matrix_world @ Vector(v) for v in i.object.bound_box]
            front = max((p - world).dot(dirv) for p in corners)
            if front > -2.0:
                seen += 1
                if front > worst:
                    worst = front
                    along = front - min((p - world).dot(dirv) for p in corners)
    return worst, along, seen


try:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-60.0, -60.0, 0.0))
    pal = ctx.view_layer.objects.active; pal.name = "EUR1 pallet"; pal.scale = (0.8, 1.2, 0.15); ctx.view_layer.update()
    eur1 = {"version": 2, "kind": "pallet", "id": "pallet:EUR1:Wood:1.2", "object": "EUR1 pallet", "length_m": 0.8, "width_m": 1.2,
            "height_m": 0.15, "forward_axis": "X"}
    pal["wh_load"] = json.dumps(eur1)

    # Racks' render scene (Rack Plugin dev/render_infeed_sequence.py), with a synthetic crane in-feed.
    main = create_line(ctx, Vector((-14.0, -20.0, 0.8)), 0.0); main.name = "Pallet line"
    with suspended_rebuild():
        s = main.conveyor_line
        s.segments[0]["length_mm"] = 6000.0
        seg = s.segments.add(); seg.kind = 'MODULE'; seg.module_kind = 'DIVERTER'; seg.merge_angle = '90'
        seg = s.segments.add(); seg.kind = 'STRAIGHT'; seg["length_mm"] = 4000.0
        s.populate = True
    build_line(ctx, main); settle()
    mid = sysrec(main)["id"]
    check(bpy.ops.conveyor.set_line_item(line_id=mid, load_json=json.dumps(eur1), by="test") == {'FINISHED'}, "the main carries the rack's EUR1")
    check(bpy.ops.conveyor.set_line_flow(line_id=mid, population=1.0, speed_m_s=0.2, by="test") == {'FINISHED'}, "at 100 %, 0.2 m/s"); settle()
    bpy.ops.conveyor.new_line_at_junction(line_name=main.name, index=1, side='LEFT')
    br = ctx.view_layer.objects.active; br.name = "Branch to the rack"; settle()
    check(bpy.ops.conveyor.set_line_flow(line_id=sysrec(br)["id"], share=0.6, by="test") == {'FINISHED'}, "the branch takes 60 %"); settle()

    world, _dirv, heading = end_frame(br)
    rack = bpy.data.objects.new("Crane rack", None); scene.collection.objects.link(rack); rack.location = (0.0, 40.0, 0.8)
    rack["wh_system"] = json.dumps({"version": 2, "addon": "warehouse_racks", "kind": "crane_rack", "id": "rack-turned", "object": rack.name,
                                    "label": rack.name, "level": 0, "footprint": [[-1, -1], [1, -1], [1, 1], [-1, 1]], "height_m": 6.0,
                                    "clearance_m": 0.0, "zone": None})
    rack["wh_ports"] = json.dumps([{"version": 2, "id": "aisle0_in", "role": "in", "kind": "point", "position": list(world - rack.location),
                                    "heading_deg": math.degrees(heading), "max_population": 0.2, "speed_m_s": 0.2, "load": eur1}])
    ctx.view_layer.update(); settle()
    r = bpy.ops.conveyor.dock_line(line_id=sysrec(br)["id"], system_id="rack-turned", port_id="aisle0_in", anchor="end", by="test"); settle(6)
    check(r == {'FINISHED'} and ports.dock_at(br, "end") is not None, f"the branch docks at the crane in-feed by its end ({r})")

    # The length each line publishes: as the goods ride on it.
    load_of = lambda o: next((p.get("load") or {} for p in ports_of(o) if p.get("id") == "line_in"), {})
    lm, lb = load_of(main), load_of(br)
    check(lm.get("length_m") == 0.8 and lm.get("forward_axis") == "X",
          f"the main publishes the pallet as it runs there: 0.8 m along, forward X ({lm.get('length_m')}, {lm.get('forward_axis')})")
    check(lb.get("length_m") == 1.2 and lb.get("width_m") == 0.8 and lb.get("forward_axis") == "Y" and lb.get("id") == eur1["id"],
          f"the branch publishes it sideways, as the pop-up divert hands it on: 1.2 m along, forward Y ({lb.get('length_m')}, {lb.get('forward_axis')})")
    # One number everywhere (joint check 11): the branch at the crane's cap included.
    rows, bad = compare([main, br])
    print("rows:", rows)
    check(not bad, f"every published population is warehouse_common's resolve over the published records {bad}")
    # The length the populate tree uses where the goods leave each line.
    check(abs(inp(main, "Item Length") - 0.8) < 1e-4 and abs(inp(br, "Item Length") - 1.2) < 1e-4,
          f"Item Length: 0.8 on the main, 1.2 on the branch ({inp(main, 'Item Length'):.3f}, {inp(br, 'Item Length'):.3f})")
    frames = list(range(1, 1201, 2))
    for o, want, label in ((main, 0.8, "the main's free end"), (br, 1.2, "the branch at the in-feed")):
        worst, along, seen = overhang(o, pal, frames)
        check(seen > 20 and worst <= 1e-3 and abs(along - want) < 1e-3,
              f"{label}: no pallet's front passes the end (furthest {worst * 1000:.1f} mm past it, {along:.2f} m along travel, {seen} sightings)")
    dj.run_sync(scene)
    check(STATS["last_writes"] == 0, f"a settled scene: the pass writes nothing ({STATS['last_writes']})")
except Exception:
    traceback.print_exc(); fails.append("raised")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
