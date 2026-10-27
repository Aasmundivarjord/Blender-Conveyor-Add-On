"""2.21.0, contract R22.1 (the stream graph is published): every TAKEN
junction face is a port on its main line (`j:<uuid>`, or a right-angle
transfer's face with `u_m`), the docked lines link it with `edge` and a
divert's local `share`, a takeaway links the line it carries on from; and
warehouse_common's simple_flow.build_graph, fed with exactly these records,
makes the intended sections and edges (the PM's six cases: a divert, a
merge, a RAT with a branch on one face and a feeder on the other, a bypass,
a tail-to-head pair, a free face). Plus: ids kept through rebuilds and a
feeder sliding along, gone with the docked line, older files republished
once, 0 writes at rest.
Blender -b --python tests/headless/test_r22_1_junctions.py"""
import bpy, math, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, junction_ports as jp
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


def add(s, kind, **kw):
    seg = s.segments.add(); seg.kind = kind
    for k, v in kw.items():
        if k.endswith("_mm"):
            seg[k] = float(v)
        else:
            setattr(seg, k, v)
    return seg


def main_line(name, x, pieces):
    """A populated line along +Y at x: pieces after a 3 m straight."""
    o = create_line(ctx, Vector((x, 0.0, 0.8)), 0.0); o.name = name
    with suspended_rebuild():
        s = o.conveyor_line
        s.segments[0]["length_mm"] = 3000.0
        for kind, kw in pieces:
            add(s, kind, **kw)
        s.populate = True; s.speed_m_s = 0.5
    build_line(ctx, o); settle()
    return o


def at_junction(main, index, side, name, role=None):
    bpy.ops.conveyor.new_line_at_junction(line_name=main.name, index=index, side=side); settle()
    o = ctx.view_layer.objects.active; o.name = name
    settle()  # the main line follows the rename before the next new line takes the default name
    if role is not None:
        bpy.ops.conveyor.junction_set(line=o.name, role=role); settle()
    return o


def ports(o):
    return rec.read_record(o.get("wh_ports"), [])


def links(o):
    return rec.read_record(o.get("wh_port_links"), [])


def sid(o):
    return rec.read_record(o.get("wh_system"), {}).get("id")


def jports(o):
    return [p for p in ports(o) if str(p.get("id", "")).startswith("j:")]


def graph():
    records = [{"system": rec.read_record(o.get("wh_system"), {}), "ports": ports(o), "links": links(o),
                "load": rec.read_record(o.get("wh_load"), None)} for o in scene.objects if "wh_system" in o]
    nodes, edges = sf.build_graph(records)
    names = {sid(o): o.name for o in scene.objects if "wh_system" in o}

    def nm(nid):
        s, _, port = nid.partition("/")
        return names.get(s, s) + "/" + port
    return {nm(n) for n in nodes}, [(nm(e.src), nm(e.dst), e.kind, e.share) for e in edges]


def has_edge(edges, src, dst, kind, share="any"):
    return any(e[0] == src and e[1] == dst and e[2] == kind and (share == "any" or (e[3] is None if share is None else e[3] is not None and abs(e[3] - share) < 1e-3))
               for e in edges)


def line_nodes(nodes, name):
    return sorted(n for n in nodes if n.split("/", 1)[0] == name)


def world_end(o, start=True):
    s = o.conveyor_line
    if start:
        return o.matrix_world.translation.copy()
    ex, ey, ez, _hd = s.end_pose
    return o.matrix_world @ Vector((ex, ey, ez))


try:
    # A. a divert ------------------------------------------------------------
    A = main_line("A Main", 0.0, [('MODULE', dict(module_kind='DIVERTER', merge_angle='90')), ('STRAIGHT', dict(length_mm=3000.0))])
    BA = at_junction(A, 1, 'LEFT', "A Branch")
    ja = jports(A)
    check(len(ja) == 1 and ja[0]["role"] == "out" and ja[0]["taken"] is True and ja[0]["exclusive"] is True and ja[0]["kind"] == "point",
          f"A: the taken divert face is a port j:<uuid>, out, taken, exclusive ({ja})")
    pa = ja[0] if ja else {}
    pw = A.matrix_world @ Vector(pa.get("position", (0, 0, 0)))
    check(pa and (pw - world_end(BA)).length < 0.05, f"A: at the branch's start ({(pw - world_end(BA)).length if pa else -1:.3f} m)")
    seg_a = A.conveyor_line.segments[1]
    check(pa and abs(pa.get("u_m", -1) - (3.0 + seg_a.length_mm / 2000.0)) < 0.01, f"A: u_m at the junction's centre ({pa.get('u_m')})")
    la = links(BA)
    check(len(la) == 1 and la[0]["port"] == pa.get("id") and la[0]["system_id"] == sid(A) and la[0]["edge"] == "divert"
          and la[0]["anchor"] == "start" and la[0]["role"] == "out" and abs(la[0].get("share", -1) - 0.5) < 1e-3,
          f"A: the branch links it: divert, start, its local share 0.5 ({la})")
    check(BA.get("wh_port_link") is None, "A: no v1 entry for a junction link")

    # B. a merge -------------------------------------------------------------
    B = main_line("B Main", 10.0, [('MODULE', dict(module_kind='MERGE', merge_angle='90')), ('STRAIGHT', dict(length_mm=3000.0))])
    FB = at_junction(B, 1, 'LEFT', "B Feeder")
    jb = jports(B)
    check(dj.docked_junction(ctx, FB, 'MERGE') is not None and len(jb) == 1 and jb[0]["role"] == "in", f"B: the merge face is an 'in' port ({jb})")
    lb = links(FB)
    check(len(lb) == 1 and lb[0]["edge"] == "merge" and lb[0]["anchor"] == "end" and lb[0]["role"] == "in" and "share" not in lb[0]
          and lb[0]["port"] == (jb[0]["id"] if jb else None), f"B: the feeder links it: merge, end, no share ({lb})")

    # C. a RAT: a branch on one face, a feeder on the other --------------------
    C = main_line("C Main", 20.0, [('MODULE', dict(module_kind='RAT', module_exit='STRAIGHT')), ('STRAIGHT', dict(length_mm=3000.0))])
    BC = at_junction(C, 1, 'LEFT', "C Branch")
    FC = at_junction(C, 1, 'RIGHT', "C Feeder", role='MERGE')
    faces = {p["id"]: p for p in ports(C) if str(p["id"]).startswith("rat")}
    lf, rf = faces.get("rat2_left", {}), faces.get("rat2_right", {})
    check(lf.get("taken") is True and rf.get("taken") is True and lf.get("role") == "io" and rf.get("role") == "io"
          and lf.get("u_m") is not None and lf.get("u_m") == rf.get("u_m"),
          f"C: both faces taken, io, the same u_m ({lf.get('u_m')}, {rf.get('u_m')})")
    check(not jports(C), "C: a RAT's faces are its own ports, no j: ports")
    lbc, lfc = links(BC), links(FC)
    check(len(lbc) == 1 and lbc[0]["port"] == "rat2_left" and lbc[0]["edge"] == "divert" and lbc[0]["role"] == "io",
          f"C: the branch links rat2_left as a divert ({lbc})")
    check(len(lfc) == 1 and lfc[0]["port"] == "rat2_right" and lfc[0]["edge"] == "merge" and lfc[0]["anchor"] == "end",
          f"C: the feeder links rat2_right as a merge ({lfc})")

    # D. a bypass: out at a divert, back in by a merge of its own --------------
    D = main_line("D Main", 30.0, [('MODULE', dict(module_kind='DIVERTER', merge_angle='90')), ('STRAIGHT', dict(length_mm=7000.0))])
    P = at_junction(D, 1, 'LEFT', "D Bypass")

    def shape(b_mm):
        with suspended_rebuild():
            bs = P.conveyor_line
            while len(bs.segments) > 1:
                bs.segments.remove(len(bs.segments) - 1)
            bs.segments[0]["length_mm"] = 600.0
            add(bs, 'CURVE', curve_direction='RIGHT', curve_angle_deg=90)
            add(bs, 'STRAIGHT', length_mm=b_mm)
            add(bs, 'CURVE', curve_direction='RIGHT', curve_angle_deg=90)
            add(bs, 'STRAIGHT', length_mm=600.0)
        build_line(ctx, P); ctx.view_layer.update()
        return world_end(P, start=False)
    end = shape(2000.0)
    shape(2000.0 + (7.8 - end.y) * 1000.0)
    settle(6)
    check(dj.docked_diverter(ctx, P) is not None and dj.docked_junction(ctx, P, 'MERGE') is not None, "D: the bypass leaves at the divert and merges back")
    jd = sorted(jports(D), key=lambda p: p["u_m"])
    lp = {l["edge"]: l for l in links(P)}
    check(len(jd) == 2 and [p["role"] for p in jd] == ["out", "in"] and set(lp) == {"divert", "merge"}
          and lp["divert"]["port"] == jd[0]["id"] and lp["merge"]["port"] == jd[1]["id"],
          f"D: two j: ports (out, then in) and both links on the bypass ({[(p['id'][:10], p['role'], p['u_m']) for p in jd]})")

    # E. tail to head ----------------------------------------------------------
    E1 = main_line("E First", 40.0, [])
    for o in list(ctx.view_layer.objects.selected):
        o.select_set(False)
    ctx.view_layer.objects.active = E1; E1.select_set(True)
    bpy.ops.conveyor.new_line_from_end(); settle()
    E2 = ctx.view_layer.objects.active; E2.name = "E Takeaway"; settle()
    le = links(E2)
    check(len(le) == 1 and le[0]["port"] == "line_out" and le[0]["edge"] == "continue" and le[0]["anchor"] == "start" and le[0]["system_id"] == sid(E1),
          f"E: the takeaway links line_out with edge continue ({le})")

    # F. a free face -------------------------------------------------------------
    F = main_line("F Main", 50.0, [('MODULE', dict(module_kind='RAT', module_exit='STRAIGHT')), ('STRAIGHT', dict(length_mm=1500.0)),
                                   ('MODULE', dict(module_kind='DIVERTER', merge_angle='90')), ('STRAIGHT', dict(length_mm=1500.0))])
    ff = [p for p in ports(F) if str(p["id"]).startswith("rat")]
    check(ff and all(p.get("taken") is False and "u_m" not in p for p in ff) and not jports(F) and not links(F),
          "F: free faces are no boundaries (no u_m, no j: port for a free junction, no links)")

    # The graph, from exactly these records ---------------------------------------
    nodes, edges = graph()
    ida = "A Main/" + pa.get("id", "?")
    check(line_nodes(nodes, "A Main") == sorted(["A Main/line_in", ida]), f"graph A: two sections ({line_nodes(nodes, 'A Main')})")
    check(has_edge(edges, "A Main/line_in", ida, sf.CONTINUE, None) and has_edge(edges, "A Main/line_in", "A Branch/line_in", sf.DIVERT, 0.5),
          "graph A: the section before the divert splits: continue + divert 0.5")
    idb = "B Main/" + (jb[0]["id"] if jb else "?")
    check(line_nodes(nodes, "B Main") == sorted(["B Main/line_in", idb]) and has_edge(edges, "B Feeder/line_in", idb, sf.MERGE, None)
          and has_edge(edges, "B Main/line_in", idb, sf.CONTINUE, None), "graph B: the feeder merges into the section from the junction on")
    check(line_nodes(nodes, "C Main") == ["C Main/line_in", "C Main/rat2_left"], f"graph C: one boundary for both faces ({line_nodes(nodes, 'C Main')})")
    check(has_edge(edges, "C Main/line_in", "C Branch/line_in", sf.DIVERT) and has_edge(edges, "C Feeder/line_in", "C Main/rat2_left", sf.MERGE)
          and has_edge(edges, "C Main/line_in", "C Main/rat2_left", sf.CONTINUE, None),
          "graph C: the branch leaves the section before, the feeder lands on the section after")
    idd0, idd1 = ("D Main/" + jd[0]["id"], "D Main/" + jd[1]["id"]) if len(jd) == 2 else ("?", "?")
    check(line_nodes(nodes, "D Main") == sorted(["D Main/line_in", idd0, idd1]), f"graph D: three sections ({line_nodes(nodes, 'D Main')})")
    check(has_edge(edges, "D Main/line_in", "D Bypass/line_in", sf.DIVERT) and has_edge(edges, "D Bypass/line_in", idd1, sf.MERGE)
          and has_edge(edges, "D Main/line_in", idd0, sf.CONTINUE) and has_edge(edges, idd0, idd1, sf.CONTINUE),
          "graph D: out at the divert, back in at the merge, the main runs on")
    check(has_edge(edges, "E First/line_in", "E Takeaway/line_in", sf.CONTINUE), "graph E: the first line continues into the takeaway")
    check(line_nodes(nodes, "F Main") == ["F Main/line_in"] and not any("F Main" in e[0] or "F Main" in e[1] for e in edges),
          f"graph F: a line with only free faces is one node ({line_nodes(nodes, 'F Main')})")
    res = sf.resolve(*sf.build_graph([{"system": rec.read_record(o.get("wh_system"), {}), "ports": ports(o), "links": links(o),
                                       "load": rec.read_record(o.get("wh_load"), None)} for o in scene.objects if "wh_system" in o]))
    check(not res.cycles and not res.stream_cycles and not res.oversplit, f"resolve: no cycles, no oversplit ({res.cycles}, {res.stream_cycles}, {res.oversplit})")

    # Shares: a second branch takes its share of what the first left -----------------
    G = main_line("G Main", 60.0, [('MODULE', dict(module_kind='DIVERTER', merge_angle='90')), ('STRAIGHT', dict(length_mm=3000.0)),
                                   ('MODULE', dict(module_kind='DIVERTER', merge_angle='90')), ('STRAIGHT', dict(length_mm=3000.0))])
    G1 = at_junction(G, 1, 'LEFT', "G Branch 1")
    G2 = at_junction(G, 3, 'LEFT', "G Branch 2")
    G1.conveyor_line.share_pct = 30; G2.conveyor_line.share_pct = 20; settle()
    s1, s2 = links(G1)[0].get("share"), links(G2)[0].get("share")
    check(s1 is not None and s2 is not None and abs(s1 - 0.3) < 2e-3 and abs(s2 - 0.2 / 0.7) < 2e-3,
          f"G: 30 % then 20 % of the main are local shares 0.3 and 0.2 / 0.7 ({s1}, {s2})")

    # Ids: kept through a rebuild and a feeder sliding along; gone with the docked line ----
    before = pa.get("id")
    build_line(ctx, A); settle()
    check([p["id"] for p in jports(A)] == [before] and links(BA)[0]["port"] == before, "A: a rebuild keeps the port id")
    H = main_line("H Main", 70.0, [('STRAIGHT', dict(length_mm=5000.0))])
    FH = create_line(ctx, Vector((70.0 - 2.0, 4.0, 0.8)), -math.pi / 2.0); FH.name = "H Feeder"
    with suspended_rebuild():
        FH.conveyor_line.segments[0]["length_mm"] = 1750.0
        FH.conveyor_line.populate = True
    build_line(ctx, FH); settle(6)
    jh = jports(H)
    check(len(jh) == 1 and links(FH) and links(FH)[0]["port"] == jh[0]["id"], f"H: a feeder aimed at the main docks with a port ({jh})")
    if jh:
        hid, hu = jh[0]["id"], jh[0]["u_m"]
        FH.location.y += 0.6; settle(6)
        jh2 = jports(H)
        check(len(jh2) == 1 and jh2[0]["id"] == hid and abs(jh2[0]["u_m"] - hu - 0.6) < 0.05 and links(FH)[0]["port"] == hid,
              f"H: the feeder slid 0.6 m along: same port, u_m {hu} -> {jh2[0]['u_m'] if jh2 else None}")
    bpy.data.objects.remove(BA, do_unlink=True); settle(6)
    check(not jports(A), "A: the branch deleted, the port goes with it")

    # Older files: the records are published once, then the pass is quiet ----------------
    jg = jports(G)
    for o in (G, G1, G2):
        del o[jp.RECORDS_REV_KEY]
    G["wh_ports"] = rec.dumps([p for p in ports(G) if not str(p["id"]).startswith("j:")])
    for o in (G1, G2):
        del o["wh_port_links"]
    settle(2)
    check(sorted(p["id"] for p in jports(G)) == sorted(p["id"] for p in jg) and links(G1) and links(G2)
          and all(o.get(jp.RECORDS_REV_KEY) == jp.RECORDS_REV for o in (G, G1, G2)), "an older file's lines publish the junction records once")
    settle(2)
    dj.run_sync(scene)
    check(STATS["last_writes"] == 0, f"a settled scene: the pass writes nothing ({STATS['last_writes']}, {STATS['sites'][-5:]})")
except Exception:
    traceback.print_exc(); fails.append("raised")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
