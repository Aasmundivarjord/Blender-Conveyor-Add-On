"""2.23.0, round 8 D (R22 / R22.2 / R22.3): every line publishes its population
(a master its slider, every other line the population it animates), the
speed in use and its master pick; the slot grid's floor goes out as
max_population; a rack's out-feed leads the line docked at it and an in-feed
caps the line feeding it; a port's population wins over a stale rate (R22.5,
2.23.1); another add-on changing a port's population re-resolves the lines
docked there (2.23.2); conveyor.set_line_flow sets the sliders. Checked the
way the PM's joint suite (check 11) does: warehouse_common's build_graph +
resolve over the scene's published records give the numbers every line
publishes -- one number everywhere.
Blender -b --python tests/headless/test_flow_publish.py"""
import json, math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, stream
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


def line(name, x, pieces=(), length_mm=6000.0, pop=50.0, speed=0.5, populate=True, y=0.0):
    o = create_line(ctx, Vector((x, y, 0.8)), 0.0); o.name = name
    with suspended_rebuild():
        s = o.conveyor_line
        s.segments[0]["length_mm"] = 3000.0 if pieces else float(length_mm)
        for kind, kw in pieces:
            seg = s.segments.add(); seg.kind = kind
            for k, v in kw.items():
                if k.endswith("_mm"):
                    seg[k] = float(v)
                else:
                    setattr(seg, k, v)
        s.populate = populate; s.speed_m_s = speed; s.population_pct = pop
    build_line(ctx, o); settle()
    return o


def at_junction(main, index, name, side='LEFT'):
    bpy.ops.conveyor.new_line_at_junction(line_name=main.name, index=index, side=side)
    o = ctx.view_layer.objects.active; o.name = name; settle()
    return o


def system(name, sid, loc, port_list):
    o = bpy.data.objects.new(name, None); scene.collection.objects.link(o); o.location = loc
    o["wh_system"] = json.dumps({"version": 2, "addon": "warehouse_racks", "kind": "crane_rack", "id": sid, "object": name, "label": name,
                                 "level": 0, "footprint": [[-1, -1], [1, -1], [1, 1], [-1, 1]], "height_m": 6.0, "clearance_m": 0.0, "zone": None})
    o["wh_ports"] = json.dumps(port_list); ctx.view_layer.update()
    return o


def sysrec(o):
    return rec.read_record(o.get("wh_system"), {})


def resolved():
    """Check 11's way: build_graph + resolve over every published record in the scene."""
    records = [{"system": sysrec(o), "ports": rec.read_record(o.get("wh_ports"), []), "links": rec.read_record(o.get("wh_port_links"), []),
                "load": rec.read_record(o.get("wh_load"), None)} for o in scene.objects if "wh_system" in o]
    nodes, edges = sf.build_graph(records)
    return sf.resolve(nodes, edges, default_speed=sf.DEFAULT_SPEED)


def compare(objs, tol=5e-4):
    """[(name, published, resolved, is master)] of these lines, and the problems: a follower must equal
    resolve; a master (R22.3) publishes its slider, at or above resolve."""
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
        rows.append((o.name, round(pub, 4), round(nf.population, 4), nf.is_master))
        if nf.is_master:
            if pub < nf.population - tol:
                bad.append((o.name, "master below resolve", pub, nf.population))
        elif abs(pub - nf.population) > tol:
            bad.append((o.name, "follower differs", pub, nf.population))
    return rows, bad


try:
    # A. A lone line publishes its slider (it is its stream's master), the speed in use, no floor cap.
    a = line("A", 0.0, pop=40.0)
    sa = sysrec(a)
    check(abs(sa.get("population", -1) - 0.4) < 1e-6 and abs(sa.get("speed_m_s", -1) - 0.5) < 1e-6 and "master" not in sa,
          f"A: a lone line: population 0.4, speed 0.5, no master pick ({sa.get('population')}, {sa.get('speed_m_s')})")
    li = next(p for p in rec.read_record(a.get("wh_ports"), []) if p["id"] == "line_in")
    check("max_population" not in li, "A: its grid floor does not bind: no max_population")

    # B. A divert (45 degrees, no stop): the branch publishes the 30 % of the master it animates.
    b = line("B Main", 10.0, pieces=[('MODULE', dict(module_kind='DIVERTER', merge_angle='45')), ('STRAIGHT', dict(length_mm=4000.0))], pop=60.0)
    bb = at_junction(b, 1, "B Branch")
    bb.conveyor_line.share_pct = 30; settle()
    check(abs(sysrec(bb).get("population", -1) - 0.18) < 1e-3, f"B: the branch publishes 30 % of 60 % ({sysrec(bb).get('population')})")

    # C. A merge: the feeder is its own stream's master and publishes its slider.
    c = line("C Main", 20.0, pieces=[('MODULE', dict(module_kind='MERGE', merge_angle='45')), ('STRAIGHT', dict(length_mm=4000.0))], pop=30.0)
    cf = at_junction(c, 1, "C Feeder")
    cf.conveyor_line.populate = True; cf.conveyor_line.population_pct = 25.0; settle()
    check(abs(sysrec(cf).get("population", -1) - 0.25) < 1e-6, f"C: the feeder publishes its 25 % ({sysrec(cf).get('population')})")

    # D. A capped master: 100 % behind a right-angle stop publishes its slider and
    # the floor as max_population; its follower publishes what it animates.
    d = line("D Main", 30.0, pieces=[('MODULE', dict(module_kind='DIVERTER', merge_angle='90')), ('STRAIGHT', dict(length_mm=3000.0))], pop=100.0)
    db = at_junction(d, 1, "D Branch")
    sd = sysrec(d)
    dli = next(p for p in rec.read_record(d.get("wh_ports"), []) if p["id"] == "line_in")
    gd = stream.tree_for(ctx, d).flow
    check(abs(sd.get("population", -1) - 1.0) < 1e-6 and dli.get("max_population", 2.0) < 0.99,
          f"D: the master publishes its 100 % and the grid floor {dli.get('max_population')} (it runs at {gd.population.get(d.name, 0):.3f})")

    # E. A pinned master downstream: the branch is pinned at 40 % and takes half of what reaches it.
    e = line("E Main", 40.0, pieces=[('MODULE', dict(module_kind='DIVERTER', merge_angle='45')), ('STRAIGHT', dict(length_mm=4000.0))], pop=10.0)
    eb = at_junction(e, 1, "E Branch")
    with suspended_rebuild():
        eb.conveyor_line.flow_master = True; eb.conveyor_line.population_pct = 40.0; eb.conveyor_line.share_pct = 50
    build_line(ctx, eb); settle()
    check(sysrec(eb).get("master") is True and abs(sysrec(eb).get("population", -1) - 0.4) < 1e-6 and abs(sysrec(e).get("population", -1) - 0.8) < 1e-3,
          f"E: the pinned branch publishes master and its 40 %, the main 80 % ({sysrec(e).get('population')})")

    # F. A rack leads the line docked at its out-feed: 50 % of 1.2 m pallets at 0.2 m/s is
    # 0.08 items/s; the line keeps its own 0.4 m/s, so it shows 25 %.
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-50.0, -50.0, 0.0))
    pal = ctx.view_layer.objects.active; pal.name = "EUR1 pallet"; pal.scale = (0.8, 1.2, 0.15); ctx.view_layer.update()
    load = {"version": 2, "kind": "pallet", "id": "pallet:EUR1:Wood:1.2", "object": "EUR1 pallet", "length_m": 1.2, "width_m": 0.8,
            "height_m": 0.15, "forward_axis": "Y"}
    system("R rack", "rack-d", (50.0, 0.0, 0.8), [
        {"version": 2, "id": "out0", "role": "out", "kind": "point", "position": [0, 0, 0], "heading_deg": 0.0, "width_m": 0.8,
         "population": 0.5, "speed_m_s": 0.2, "master": True, "load": load},
        {"version": 2, "id": "in0", "role": "in", "kind": "point", "position": [3, 0, 0], "heading_deg": 0.0, "width_m": 0.8,
         "max_population": 0.1, "speed_m_s": 0.2, "load": load}])
    f = line("F Fed", 50.0, y=-10.0, pop=90.0, speed=0.4)
    sid = sysrec(f)["id"]
    r = bpy.ops.conveyor.dock_line(line_id=sid, system_id="rack-d", port_id="out0", anchor="start", by="test"); settle()
    with suspended_rebuild():
        f.conveyor_line.speed_m_s = 0.4
    build_line(ctx, f); settle()
    gf = stream.tree_for(ctx, f).flow
    check(r == {'FINISHED'} and abs(gf.population.get(f.name, 0) - 0.25) < 1e-3 and f.name in gf.own_speed,
          f"F: the rack leads: the line runs at its own 0.4 m/s and shows 25 % ({gf.population.get(f.name, 0):.4f}, master {gf.master})")
    check(abs(sysrec(f).get("population", -1) - 0.25) < 1e-3, f"F: and publishes it ({sysrec(f).get('population')})")

    # G. A line feeding a crane in-feed that takes 10 % (at 0.2 m/s, 1.2 m pallets): it is held there.
    g = line("G Feeding", 53.0, y=-10.0, pop=80.0, speed=0.2)
    with suspended_rebuild():
        g.conveyor_line.populate_item = pal
    build_line(ctx, g); settle()
    r = bpy.ops.conveyor.dock_line(line_id=sysrec(g)["id"], system_id="rack-d", port_id="in0", anchor="end", by="test"); settle()
    gg = stream.tree_for(ctx, g).flow
    check(r == {'FINISHED'} and abs(gg.population.get(g.name, 0) - 0.1) < 2e-3, f"G: the in-feed holds the line at 10 % ({gg.population.get(g.name, 0):.4f})")

    # I. R22.5 (2.23.1): a port's published population wins over a stale legacy rate (Floorplan's door
    # published 0.5 at 0.2 m/s and an old rate_ph 16.5); a rate stands in only where no population is
    # published, as warehouse_common 0.6.3's build_graph does; a line a port leads says so to callers.
    system("S door", "door-r225", (70.0, 0.0, 0.8), [
        {"version": 2, "id": "out_pop", "role": "out", "kind": "point", "position": [0, 0, 0], "heading_deg": 0.0, "width_m": 0.8,
         "population": 0.5, "speed_m_s": 0.2, "rate_ph": 16.5, "load": load},
        {"version": 2, "id": "out_rate", "role": "out", "kind": "point", "position": [4, 0, 0], "heading_deg": 0.0, "width_m": 0.8,
         "rate_ph": 16.5, "speed_m_s": 0.2, "load": load}])
    i1 = line("I Population", 70.0, y=-10.0, pop=90.0, speed=0.5)
    i2 = line("I Rate", 74.0, y=-10.0, pop=90.0, speed=0.5)
    for o, pid in ((i1, "out_pop"), (i2, "out_rate")):
        r = bpy.ops.conveyor.dock_line(line_id=sysrec(o)["id"], system_id="door-r225", port_id=pid, anchor="start", by="test"); settle()
        check(r == {'FINISHED'}, f"I: {o.name} docks at {pid} ({r})")
    p1, p2 = sysrec(i1).get("population", -1), sysrec(i2).get("population", -1)
    stand_in = 16.5 * (1.2 + 0.05) / (3600.0 * 0.2)
    check(abs(p1 - 0.5) < 1e-3, f"I: the published population wins over a stale rate_ph 16.5: the line runs and publishes 0.5 ({p1})")
    check(abs(p2 - stand_in) < 1e-4, f"I: a port with only a rate: it stands in, {stand_in:.4f} at 0.2 m/s ({p2})")
    from bl_ext.user_default.conveyor_system.operators.public_api import follows_note
    note = follows_note(ctx, i1)
    check(note == f"{i1.name} follows S door · out_pop", f"I: a line its port leads says whom it follows ({note!r})")
    r = bpy.ops.conveyor.set_line_flow(line_id=sysrec(i1)["id"], population=0.3, by="warehouse_floorplan"); settle()
    check(r == {'FINISHED'} and abs(i1.conveyor_line.population_pct - 30.0) < 1e-6 and abs(sysrec(i1).get("population", -1) - 0.5) < 1e-3,
          f"I: set_line_flow on it: FINISHED, its own 30 % kept, the port's 0.5 runs ({sysrec(i1).get('population')})")
    i1.conveyor_line.flow_master = True; settle()
    check(follows_note(ctx, i1) is None and abs(sysrec(i1).get("population", -1) - 0.3) < 1e-3,
          f"I: pinned as master, it leads with its own 30 % and says nothing ({sysrec(i1).get('population')})")
    i1.conveyor_line.flow_master = False; settle()

    # J. 2.23.2 (PM, Floorplan's "All Half Full"): another add-on changes the population of the port a
    # line is docked at, 0 -> 0.5 at 0.2 m/s: the line and its branch follow on the next pass.
    system("J door", "door-j", (90.0, 0.0, 0.8), [
        {"version": 2, "id": "door1", "role": "out", "kind": "point", "position": [0, 0, 0], "heading_deg": 0.0, "width_m": 0.8,
         "population": 0.0, "speed_m_s": 0.2, "load": load}])
    j = line("J Door line", 90.0, y=-10.0, pieces=[('MODULE', dict(module_kind='DIVERTER', merge_angle='45')), ('STRAIGHT', dict(length_mm=4000.0))],
             pop=40.0, speed=0.5)
    jb = at_junction(j, 1, "J Branch")
    jb.conveyor_line.share_pct = 50; settle()
    r = bpy.ops.conveyor.dock_line(line_id=sysrec(j)["id"], system_id="door-j", port_id="door1", anchor="start", by="test"); settle()
    check(r == {'FINISHED'} and abs(sysrec(j).get("population", -1)) < 1e-6 and abs(sysrec(jb).get("population", -1)) < 1e-6,
          f"J: a door at population 0 stops the line docked at it and its branch ({sysrec(j).get('population')}, {sysrec(jb).get('population')})")
    door = scene.objects["J door"]
    door_ports = json.loads(door["wh_ports"])
    door_ports[0].update(population=0.5, rate_ph=round(3600.0 * 0.5 * 0.2 / 1.25, 2))
    door["wh_ports"] = json.dumps(door_ports); ctx.view_layer.update(); settle()
    check(abs(sysrec(j).get("population", -1) - 0.5) < 1e-3 and abs(sysrec(jb).get("population", -1) - 0.25) < 1e-3,
          f"J: the door goes to 0.5: the line and its branch follow ({sysrec(j).get('population')}, {sysrec(jb).get('population')})")
    rows_j, bad_j = compare([j, jb])
    check(not bad_j, f"J: what they publish is what warehouse_common resolves {bad_j[:3]}")
    settle(2)
    dj.run_sync(scene)
    check(STATS["last_writes"] == 0, f"J: then the pass writes nothing ({STATS['last_writes']})")

    # K. 2.24 (R22.6, PM): a buffer letting out 40 % with a divert after it. Its exit is a published
    # boundary (b:<uuid>, out_fraction 0.4, its zones as capacity_items); every population published -- the
    # branch past the buffer too -- is warehouse_common's resolve, the state before the buffer is full.
    kl = line("K Buffered", 110.0, pieces=[('MODULE', dict(module_kind='BUFFER', length_mm=3000.0)), ('STRAIGHT', dict(length_mm=2000.0)),
                                           ('MODULE', dict(module_kind='DIVERTER', merge_angle='45')), ('STRAIGHT', dict(length_mm=3000.0))], pop=50.0)
    kl.conveyor_line.segments[1].buffer_out_pct = 40; settle()
    kb = at_junction(kl, 3, "K Branch")
    kb.conveyor_line.share_pct = 20; settle()  # 20 % of the master: half of the 40 % the buffer lets out
    bport = next((p for p in rec.read_record(kl.get("wh_ports"), []) or [] if str(p.get("id", "")).startswith("b:")), {})
    check(bport.get("role") == "buffer" and bport.get("out_fraction") == 0.4 and bport.get("taken") is True and bport.get("exclusive") is True
          and abs(float(bport.get("u_m", 0)) - 6.0) < 1e-3 and int(bport.get("capacity_items", 0)) == 4,
          f"K: the buffer's exit is a port: out_fraction 0.4, at 6.0 m, holds 4 ({ {k2: bport.get(k2) for k2 in ('id', 'u_m', 'out_fraction', 'capacity_items')} })")
    rows_k, bad_k = compare([kl, kb])
    check(not bad_k and abs(sysrec(kb).get("population", -1) - 0.1) < 1e-3,
          f"K: past the 40 % buffer the branch takes half of what leaves it: 0.5 x 0.4 x 0.5 = 0.1, warehouse_common's resolve ({rows_k}, {bad_k})")
    res_k = resolved()
    check(any(abs(rest - 0.6) < 1e-6 for _node, rest in res_k.buffered), f"K: and it keeps the other 60 % (Resolution.buffered {res_k.buffered})")

    # L. A buffer saved before 2.24 with an Out rate of its own: its Output % is that over what arrives (once).
    ll = line("L Old buffer", 120.0, pieces=[('MODULE', dict(module_kind='BUFFER', length_mm=3000.0)), ('STRAIGHT', dict(length_mm=2000.0))], pop=50.0)
    from bl_ext.user_default.conveyor_system.operators import flows
    arriving = flows.buffer_in_ph(ctx, ll).get(1, 0.0)
    with suspended_rebuild():
        del ll.conveyor_line[flows.BUFFERS_MIGRATED_KEY]
        bseg = ll.conveyor_line.segments[1]
        bseg.buffer_out_mode = 'MANUAL'; bseg.buffer_out_ph = 300
        bseg["buffer_out_pct"] = 100
    settle()
    want = round(100.0 * 300.0 / arriving) if arriving else -1
    check(ll.conveyor_line.get(flows.BUFFERS_MIGRATED_KEY) and int(bseg.buffer_out_pct) == want,
          f"L: Out 300/h of {arriving:.0f}/h arriving became Output {bseg.buffer_out_pct} % ({want} %)")

    # One number everywhere: build_graph + resolve over the published records.
    rows, bad = compare([a, b, bb, c, cf, d, db, e, eb, f, g, i1, i2, j, jb, kl, kb, ll])
    print("rows:", rows)
    check(not bad, f"every line's published population is what warehouse_common resolves (masters: their slider) {bad[:3]}")

    # H. set_line_flow: Population, Speed, a branch's Share of the master; negatives leave; repeats write nothing.
    hid = sysrec(bb)["id"]
    r = bpy.ops.conveyor.set_line_flow(line_id=sysrec(b)["id"], population=0.4, speed_m_s=0.6, share=-1.0, by="warehouse_floorplan"); settle()
    check(r == {'FINISHED'} and abs(b.conveyor_line.population_pct - 40.0) < 1e-6 and abs(b.conveyor_line.speed_m_s - 0.6) < 1e-6,
          f"H: set_line_flow sets Population 40 % and 0.6 m/s ({b.conveyor_line.population_pct}, {b.conveyor_line.speed_m_s})")
    r = bpy.ops.conveyor.set_line_flow(line_id=hid, population=-1.0, speed_m_s=-1.0, share=0.25, by="warehouse_floorplan"); settle()
    check(r == {'FINISHED'} and bb.conveyor_line.share_pct == 25 and abs(sysrec(bb).get("population", -1) - 0.1) < 1e-3,
          f"H: a branch's share of the master: 25 % of 40 % ({sysrec(bb).get('population')})")
    flow_rec = rec.read_record(b.get("conveyor_flow_from"), None)
    check(flow_rec == {"population": 0.4, "speed_m_s": 0.6, "by": "warehouse_floorplan"}, f"H: recorded who set what ({flow_rec})")
    from bl_ext.user_default.conveyor_system.operators.build_line import BUILD_STATS
    builds = BUILD_STATS["builds"]
    r = bpy.ops.conveyor.set_line_flow(line_id=sysrec(b)["id"], population=0.4, speed_m_s=0.6, share=-1.0, by="warehouse_floorplan")
    check(r == {'FINISHED'} and BUILD_STATS["builds"] == builds, "H: the same again rebuilds nothing")
    check(bpy.ops.conveyor.set_line_flow(line_id="no-such-line", population=0.5) == {'CANCELLED'}, "H: an unknown line cancels")
    check(bpy.ops.conveyor.set_line_flow(line_id=sysrec(b)["id"], population=1.5) == {'CANCELLED'}, "H: a population above 1 cancels")
    rows, bad = compare([b, bb])
    check(not bad, f"after set_line_flow, one number everywhere {bad[:3]}")
    settle(2)
    dj.run_sync(scene)
    check(STATS["last_writes"] == 0, f"a settled scene: the pass writes nothing ({STATS['last_writes']})")
except Exception:
    traceback.print_exc(); fails.append("raised")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
