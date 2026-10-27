"""2.23.0, round 8 D (R22.4): a line whose flow END is docked at a system's
port publishes `arrivals` on that link -- the stream's crossings of its
origin, the splits on the way (each split's fractions in
simple_flow.split_order and the edge toward the port) and the travel to the
port -- and warehouse_common's branch_arrivals over them gives the very times
the populate tree delivers goods there, item by item: a 30 % branch gets
items 3, 6, 9, 13 ... (uneven: an averaged period cannot give a crane that).
Checked against the animation at both ends of a 45 degree divert, behind a
90 degree pop-up divert (the goods stop on the way), on a shared grid (a
feeder merging downstream), on a line the API turned about to dock its end,
behind a 60/40 divert whose branch is docked at a loaded crane in-feed
(2.23.2 / 2.23.3: it keeps carrying its main's goods and its Share),
after the share changes and on a faster clock; no arrivals where they cannot
be exact (a merge or a bypass on the way, a stopped stream).
Blender -b --python tests/headless/test_arrivals_r22_4.py"""
import json, math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, stream, ports
from bl_ext.user_default.conveyor_system.operators.detect_junctions import _world_matrix
from bl_ext.user_default.conveyor_system.operators.sync_stats import STATS
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
from bl_ext.user_default.conveyor_system._wh import simple_flow as sf, records as rec
ctx = bpy.context; scene = ctx.scene; fails = []
fps = scene.render.fps / (scene.render.fps_base or 1.0)
RACK_AT = Vector((0.0, 40.0, 0.8))
REACH = 1.0   # metres before the end an item is followed to it
TOL = 0.01    # seconds


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)


def settle(n=4):
    for _ in range(n):
        ctx.view_layer.update(); dj.run_sync(scene)
    ctx.view_layer.update()


def line(name, x, pieces=(), pop=50.0, speed=0.5):
    o = create_line(ctx, Vector((x, 0.0, 0.8)), 0.0); o.name = name
    with suspended_rebuild():
        s = o.conveyor_line
        s.segments[0]["length_mm"] = 3000.0
        for kind, kw in pieces:
            seg = s.segments.add(); seg.kind = kind
            for k, v in kw.items():
                if k.endswith("_mm"):
                    seg[k] = float(v)
                else:
                    setattr(seg, k, v)
        s.populate = True; s.speed_m_s = speed; s.population_pct = pop
    build_line(ctx, o); settle()
    return o


def at_junction(main, index, name, side='LEFT'):
    bpy.ops.conveyor.new_line_at_junction(line_name=main.name, index=index, side=side)
    o = ctx.view_layer.objects.active; o.name = name; settle()
    return o


def sysrec(o):
    return rec.read_record(o.get("wh_system"), {})


def end_frame(o):
    """(world position, unit direction of the goods, heading) at `o`'s FLOW end: a reversed line's origin."""
    if o.conveyor_line.reverse:
        p0 = dj._line_data(ctx, o)[0].pose_at(0)
        world = _world_matrix(o) @ Vector((p0.x, p0.y, p0.z))
        heading = _world_matrix(o).to_euler().z + p0.heading + math.pi  # the goods run back to the origin
    else:
        end, _local, world = ports._end_pose(ctx, o)
        heading = _world_matrix(o).to_euler().z + end.heading  # 0 = +Y, counter-clockwise
    return world, Vector((-math.sin(heading), math.cos(heading), 0.0)), heading


def end_port(o, pid):
    """An "in" port right at `o`'s end, facing the goods' way: docking moves nothing."""
    world, _dirv, heading = end_frame(o)
    return {"version": 2, "id": pid, "role": "in", "kind": "point", "position": list(world - RACK_AT), "heading_deg": math.degrees(heading)}


def link_to(o, pid):
    for e in rec.read_record(o.get("wh_port_links"), []) or []:
        if e.get("port") == pid and "edge" not in e:
            return e
    return None


def goods(o):
    item = stream.effective_item(ctx, o)  # a real load (EUR1), else the placeholder totes
    name = item.name if item is not None else None
    dg = ctx.evaluated_depsgraph_get()
    return [i.matrix_world.translation.copy() for i in dg.object_instances
            if i.is_instance and i.parent and i.parent.original == o
            and (i.object.name.startswith("Placeholder") or (name is not None and i.object.name == name))]


def measure(objs, frames):
    """Operation seconds at which goods' centres reach each line's flow end in the animation, one per
    item: from every sampled frame, an item d metres short of the end (on its last straight) is there
    d / (speed x clock) later. Returns {name: (times, the widest spread within one item)}."""
    t_start, scale = ports._clock(scene)
    ends = {o.name: end_frame(o) + (stream.tree_for(ctx, o).speed * scale,) for o in objs}
    est = {o.name: [] for o in objs}
    for fr in frames:
        scene.frame_set(fr)
        t = fr / fps
        for o in objs:
            world, dirv, _h, v = ends[o.name]
            for p in goods(o):
                rel = world - p
                d = rel.x * dirv.x + rel.y * dirv.y
                if -1e-4 <= d <= REACH and abs(rel.x * dirv.y - rel.y * dirv.x) < 0.02:
                    est[o.name].append((t + d / v - t_start) * scale)
    out = {}
    for name, xs in est.items():
        xs.sort()
        clusters = []
        for x in xs:
            if clusters and x - clusters[-1][-1] < 0.3:
                clusters[-1].append(x)
            else:
                clusters.append([x])
        out[name] = ([sum(c) / len(c) for c in clusters], max((c[-1] - c[0] for c in clusters), default=0.0))
    return out


def window(frames, speed):
    t_start, scale = ports._clock(scene)
    s0, s1 = (frames[0] / fps - t_start) * scale, (frames[-1] / fps - t_start) * scale
    return s0 + REACH / speed + 0.3, s1 - 0.3


def same(want, got, lo, hi):
    """Every published arrival inside (lo, hi) is in the animation and the other way round."""
    inner = lambda xs: [x for x in xs if lo + TOL < x < hi - TOL]
    miss = [round(a, 4) for a in inner(want) if not any(abs(a - b) < TOL for b in got)]
    extra = [round(b, 4) for b in inner(got) if not any(abs(a - b) < TOL for a in want)]
    worst = max((min(abs(a - b) for b in got) for a in inner(want)), default=0.0) if got else 9.0
    return miss, extra, worst


def compare(o, pid, frames, measured, label, minimum):
    e = link_to(o, pid)
    arr = (e or {}).get("arrivals")
    if arr is None:
        check(False, f"{label}: the link carries arrivals ({e})")
        return None
    speed = stream.tree_for(ctx, o).speed
    lo, hi = window(frames, speed)
    want = sf.branch_arrivals(arr["schedule"], arr["path"], lo, hi, arr["delay_s"])
    got, spread = measured[o.name]
    miss, extra, worst = same(want, got, lo, hi)
    check(len(want) >= minimum and not miss and not extra and spread < 2e-3,
          f"{label}: branch_arrivals over the published arrivals = the animation, {len(want)} items in {hi - lo:.0f} s "
          f"(worst {worst * 1000:.2f} ms, spread {spread * 1000:.2f} ms, missing {miss[:4]}, extra {extra[:4]})")
    return arr, want


try:
    # A. A 45 degree divert (no stop), the branch takes 30 % of the master's 60 %; both
    # the branch's end and the main's end are docked at a rack's in-feeds.
    a = line("A Main", 0.0, pieces=[('MODULE', dict(module_kind='DIVERTER', merge_angle='45')), ('STRAIGHT', dict(length_mm=4000.0))], pop=60.0)
    ab = at_junction(a, 1, "A Branch")
    ab.conveyor_line.share_pct = 30; settle()
    # C. A merge on the way: the main's end gets the feeder's goods too.
    c = line("C Main", 20.0, pieces=[('MODULE', dict(module_kind='MERGE', merge_angle='45')), ('STRAIGHT', dict(length_mm=4000.0))], pop=30.0)
    cf = at_junction(c, 1, "C Feeder")
    cf.conveyor_line.populate = True; cf.conveyor_line.population_pct = 30.0; settle()
    # D. A 90 degree pop-up divert: its goods stop on the transfer before they turn onto the branch.
    d = line("D Main", -20.0, pieces=[('MODULE', dict(module_kind='DIVERTER', merge_angle='90')), ('STRAIGHT', dict(length_mm=3000.0))], pop=40.0)
    db = at_junction(d, 1, "D Branch")
    db.conveyor_line.share_pct = 50; settle()

    # H. A feeder merges downstream of the divert: the slot grid is shared, the
    # branch gets only the root's goods -- the owners' deal comes first on its path.
    h = line("H Main", 40.0, pieces=[('MODULE', dict(module_kind='DIVERTER', merge_angle='45')), ('STRAIGHT', dict(length_mm=2000.0)),
                                     ('MODULE', dict(module_kind='MERGE', merge_angle='45')), ('STRAIGHT', dict(length_mm=3000.0))], pop=40.0)
    hb = at_junction(h, 1, "H Branch")
    hb.conveyor_line.share_pct = 30; settle()
    hf = at_junction(h, 3, "H Feeder", side='RIGHT')
    hf.conveyor_line.populate = True; hf.conveyor_line.population_pct = 20.0; settle()
    # K. A bypass (out at a divert, back into the same main): its goods re-join on the way to the main's end.
    k = line("K Main", 60.0, pieces=[('MODULE', dict(module_kind='DIVERTER', merge_angle='90')), ('STRAIGHT', dict(length_mm=9000.0))], pop=40.0)
    kb = at_junction(k, 1, "K Bypass")

    def shape(b_mm):
        with suspended_rebuild():
            bs = kb.conveyor_line
            while len(bs.segments) > 1:
                bs.segments.remove(len(bs.segments) - 1)
            bs.segments[0]["length_mm"] = 600.0
            for kind, kw in (('CURVE', dict(curve_direction='RIGHT', curve_angle_deg=90)), ('STRAIGHT', dict(length_mm=b_mm)),
                             ('CURVE', dict(curve_direction='RIGHT', curve_angle_deg=90)), ('STRAIGHT', dict(length_mm=600.0))):
                seg = bs.segments.add(); seg.kind = kind
                for key, v in kw.items():
                    if key.endswith("_mm"):
                        seg[key] = float(v)
                    else:
                        setattr(seg, key, v)
        build_line(ctx, kb); ctx.view_layer.update()
        ex, ey, ez, _hd = kb.conveyor_line.end_pose
        return kb.matrix_world @ Vector((ex, ey, ez))
    end = shape(2000.0)
    shape(2000.0 + (7.8 - end.y) * 1000.0)
    settle(6)
    kb.conveyor_line.share_pct = 30; settle()

    # P. Racks' 60/40 in-feed (PM, 2026-10-15): a main carrying a real load (EUR1, its wh_load), a 60/40
    # divert, the branch docked at a crane in-port by dock_line(anchor="end"). The in-feed receives
    # what the branch brings (2.23.3: it no longer hands the branch its load): a 60 % share, arrivals.
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-60.0, -60.0, 0.0))
    pal = ctx.view_layer.objects.active; pal.name = "EUR1 pallet"; pal.scale = (0.8, 1.2, 0.15); ctx.view_layer.update()
    eur1 = {"version": 2, "kind": "pallet", "id": "pallet:EUR1:Wood:1.2", "object": "EUR1 pallet", "length_m": 1.2, "width_m": 0.8,
            "height_m": 0.15, "forward_axis": "Y"}
    pal["wh_load"] = json.dumps(eur1)
    pm = line("P Main", -40.0, pieces=[('MODULE', dict(module_kind='DIVERTER', merge_angle='45')), ('STRAIGHT', dict(length_mm=4000.0))], pop=60.0)
    with suspended_rebuild():
        pm.conveyor_line.populate_item = pal
    build_line(ctx, pm); settle()
    pb = at_junction(pm, 1, "P Branch")
    pb.conveyor_line.share_pct = 60; settle()
    # Q. The joint suite's check 12: the same with a main carrying the placeholder totes -- the branch
    # used to take the in-feed's EUR1 and then sorted for an item nothing brought: it took nothing.
    qm = line("Q Main", -60.0, pieces=[('MODULE', dict(module_kind='DIVERTER', merge_angle='45')), ('STRAIGHT', dict(length_mm=4000.0))], pop=60.0)
    qb = at_junction(qm, 1, "Q Branch")
    qb.conveyor_line.share_pct = 60; settle()

    rack = bpy.data.objects.new("R rack", None); scene.collection.objects.link(rack); rack.location = RACK_AT
    rack["wh_system"] = json.dumps({"version": 2, "addon": "warehouse_racks", "kind": "crane_rack", "id": "rack-a", "object": rack.name,
                                    "label": rack.name, "level": 0, "footprint": [[-1, -1], [1, -1], [1, 1], [-1, 1]], "height_m": 6.0,
                                    "clearance_m": 0.0, "zone": None})
    # R. A free line docked by its END through the API turns about: its origin goes to the port, reversed.
    rl = line("R Free", 80.0, pop=45.0)
    docked = [(ab, "in0"), (a, "in1"), (c, "in2"), (db, "in3"), (hb, "in4"), (k, "in5")]
    free_port = {"version": 2, "id": "in6", "role": "in", "kind": "point", "position": [40.0, 0.0, 0.0], "heading_deg": 90.0}
    p_port = dict(end_port(pb, "in7"), load=eur1)
    q_port = dict(end_port(qb, "in8"), load=eur1)
    rack["wh_ports"] = json.dumps([end_port(o, pid) for o, pid in docked] + [free_port, p_port, q_port]); ctx.view_layer.update(); settle()
    for o, _pid in docked:  # each end lands on its port, as a drag would leave it: the pass docks it there
        ports.sync_port_end(ctx, o); settle()
    for o, pid in docked:  # (a free line's end docked by the API turns the line about: its origin goes to the port)
        r = bpy.ops.conveyor.dock_line(line_id=sysrec(o)["id"], system_id="rack-a", port_id=pid, anchor="end", by="test"); settle()
        check(r == {'FINISHED'} and link_to(o, pid) is not None and not o.conveyor_line.reverse, f"{o.name} docks its end at {pid} ({r})")

    r = bpy.ops.conveyor.dock_line(line_id=sysrec(pb)["id"], system_id="rack-a", port_id="in7", anchor="end", by="test"); settle()
    check(r == {'FINISHED'} and link_to(pb, "in7") is not None and pb.conveyor_line.populate_item is None
          and stream.same_item(stream.effective_item(ctx, pb), pal),
          f"P: dock_line docks the branch's end at the in-feed; it carries its main's EUR1 ({r}, {pb.conveyor_line.populate_item})")
    r = bpy.ops.conveyor.dock_line(line_id=sysrec(qb)["id"], system_id="rack-a", port_id="in8", anchor="end", by="test"); settle()
    check(r == {'FINISHED'} and link_to(qb, "in8") is not None and qb.conveyor_line.populate_item is None,
          f"Q: the in-feed's EUR1 does not change what the branch carries -- its main's totes ({r}, {qb.conveyor_line.populate_item})")
    r = bpy.ops.conveyor.dock_line(line_id=sysrec(rl)["id"], system_id="rack-a", port_id="in6", anchor="end", by="test"); settle()
    check(r == {'FINISHED'} and rl.conveyor_line.reverse and link_to(rl, "in6") is not None, f"R: the free line docks reversed, its origin at in6 ({r})")

    ta = stream.tree_for(ctx, a)
    arr_b = (link_to(ab, "in0") or {}).get("arrivals") or {}
    check(arr_b.get("path") == [[[0.3, 0.7], 0]] and len(arr_b.get("schedule", [])) == 1,
          f"A: the branch's path is the split's [30 %, 70 %] and its edge 0 ({arr_b.get('path')})")
    sched = arr_b.get("schedule", [[0, 0, 0]])[0]
    check(abs(sched[2] - ta.actual_spacing / ta.speed) < 1e-6 and sched[1] is not None,
          f"A: the schedule is the stream's slot period at the origin ({sched})")
    link_b = link_to(ab, "in0") or {}
    check("phase_s" in link_b and "period_s" in link_b, "A: the averaged phase_s / period_s stay for older readers")

    frames = list(range(1, 1441, 3))
    m = measure([ab, a, db, hb, rl, pb, qb], frames)
    res = compare(ab, "in0", frames, m, "A branch (45 degree divert, 30 %)", 6)
    extra = stream.path_length_m(ab) - float(ab.conveyor_line["full_length_m"])
    check(extra > 0.02, f"A: (the goods ride the divert's blend: the branch's path is {extra * 1000:.0f} mm longer than its arcs; the end counts it)")
    if res:
        gaps = [y - x for x, y in zip(res[1], res[1][1:])]
        check(gaps and max(gaps) - min(gaps) > 0.5 * sched[2], f"A: the branch's arrivals are uneven ({[round(g, 3) for g in gaps][:6]})")
    arr_a = (link_to(a, "in1") or {}).get("arrivals") or {}
    check(arr_a.get("path") == [[[0.3, 0.7], 1]], f"A: the main's end takes what the branch leaves, edge 1 ({arr_a.get('path')})")
    compare(a, "in1", frames, m, "A main end (the items the branch leaves)", 12)
    compare(db, "in3", frames, m, "D branch (90 degree pop-up: the stop on the way)", 4)

    check("arrivals" not in (link_to(c, "in2") or {"arrivals": 1}) and "period_s" in (link_to(c, "in2") or {}),
          "C: a merge on the way: no arrivals, the averaged period stands")
    th = stream.tree_for(ctx, h)
    arr_h = (link_to(hb, "in4") or {}).get("arrivals") or {}
    deal = [round(r / sum(th.rates), 9) for r in th.rates]
    check(len(th.rates) == 2 and arr_h.get("path") == [[deal, 0], [[0.3, 0.7], 0]],
          f"H: a shared grid: the owners' deal {deal}, then the split ({arr_h.get('path')})")
    compare(hb, "in4", frames, m, "H branch on a shared grid (the root's goods, then 30 %)", 3)
    tp = stream.tree_for(ctx, pm)
    arr_p = (link_to(pb, "in7") or {}).get("arrivals") or {}
    check(abs(tp.flow.population.get(pb.name, 0.0) - 0.36) < 1e-3 and arr_p.get("path") == [[[0.6, 0.4], 0]],
          f"P: still 60 % of the master's 60 % (0.36: {tp.flow.population.get(pb.name, 0.0):.4f}), the link carries arrivals ({arr_p.get('path')})")
    compare(pb, "in7", frames, m, "P branch at the EUR1 in-feed, its main's EUR1 (60/40)", 6)
    tq = stream.tree_for(ctx, qm)
    arr_q = (link_to(qb, "in8") or {}).get("arrivals") or {}
    check(abs(tq.flow.population.get(qb.name, 0.0) - 0.36) < 1e-3 and arr_q.get("path") == [[[0.6, 0.4], 0]],
          f"Q: still 60 % of 60 % (0.36: {tq.flow.population.get(qb.name, 0.0):.4f}), the link carries arrivals ({arr_q.get('path')})")
    compare(qb, "in8", frames, m, "Q branch of a placeholder main at an EUR1 in-feed (60/40)", 6)
    twin = pal.copy(); twin.data = pal.data.copy(); twin.name = "EUR1 pallet (Racks)"; scene.collection.objects.link(twin)
    other = pal.copy(); other.name = "CHEP pallet"; other["wh_load"] = json.dumps(dict(eur1, id="pallet:CHEP:Wood:1.2"))
    check(stream.same_item(pal, twin) and not stream.same_item(pal, other) and not stream.same_item(pal, None),
          "P: one load is one item: the same object, or objects with the same wh_load id")
    arr_r = (link_to(rl, "in6") or {}).get("arrivals") or {}
    check(arr_r.get("path") == [], f"R: a lone line: every item arrives ({arr_r.get('path')})")
    compare(rl, "in6", frames, m, "R reversed line (its origin at the port)", 12)
    ks = stream.tree_for(ctx, k).members.get(kb.name)
    check(ks is not None and ks.stretch and "arrivals" not in (link_to(k, "in5") or {"arrivals": 1}),
          "K: a bypass re-joins on the way: no arrivals at the main's end")

    # E. The share changes: the branch's arrivals follow at once.
    ab.conveyor_line.share_pct = 25; settle()
    arr_b = (link_to(ab, "in0") or {}).get("arrivals") or {}
    check(arr_b.get("path") == [[[0.25, 0.75], 0]], f"E: share 25 %: the published path follows ({arr_b.get('path')})")
    frames = list(range(1, 961, 3))
    m = measure([ab], frames)
    compare(ab, "in0", frames, m, "E branch at 25 %", 3)

    # F. A faster clock (2 operation seconds per scene second): operation-second arrivals still meet the goods.
    phase_1x = ((link_to(a, "in1") or {}).get("arrivals") or {}).get("schedule")
    scene["wh_time_scale"] = 2.0; settle()
    check(((link_to(a, "in1") or {}).get("arrivals") or {}).get("schedule") != phase_1x, "F: the clock changed: the published arrivals follow")
    frames = list(range(1, 721, 2))
    m = measure([ab, a], frames)
    compare(ab, "in0", frames, m, "F branch on a 2x clock", 5)
    compare(a, "in1", frames, m, "F main end on a 2x clock", 12)
    scene["wh_time_scale"] = 1.0; settle()

    # G. A stopped stream publishes no arrivals.
    a.conveyor_line.population_pct = 0.0; settle()
    check("arrivals" not in (link_to(ab, "in0") or {"arrivals": 1}), "G: Population 0 %: no arrivals")
    a.conveyor_line.population_pct = 60.0; settle(6)
    dj.run_sync(scene)
    check(STATS["last_writes"] == 0, f"a settled scene: the pass writes nothing ({STATS['last_writes']})")
except Exception:
    traceback.print_exc(); fails.append("raised")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
