"""2.22.0, round 8 simple flow (Åsmund, 2026-10-15): Population and Speed set
a stream; the master's followers follow, a branch takes its Share of the
master, a feeder's goods add where it merges, all at the master's speed (v1).
Checks: the pitch from Population (item + 0.05 m at 100 %), the rate it
publishes, an empty stream, the SAME items leaving at a divert as
warehouse_common's simple_flow.branch_of_item deals them, the owners dealt
evenly at a merge, a master downstream, the feeder speed lock, the migration
of a pre-2.22 line, the set_line_rate shim, the silent cap, and the goods on
the very pitch the stream publishes (2.23).
Blender -b --python tests/headless/test_simple_flow.py"""
import bpy, math, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line, MODIFIER_NAME
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, stream, flows
from bl_ext.user_default.conveyor_system.operators.ports import ensure_identity
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
from bl_ext.user_default.conveyor_system._wh import simple_flow as sf
ctx = bpy.context; scene = ctx.scene; fails = []
fps = scene.render.fps / (scene.render.fps_base or 1.0)


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)


def settle(n=4):
    for _ in range(n):
        ctx.view_layer.update(); dj.run_sync(scene)
    ctx.view_layer.update()


def line(name, x, pieces=(), length_mm=6000.0, pop=50.0, speed=0.5, populate=True):
    o = create_line(ctx, Vector((x, 0.0, 0.8)), 0.0); o.name = name
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


def at_junction(main, index, name):
    bpy.ops.conveyor.new_line_at_junction(line_name=main.name, index=index, side='LEFT')
    o = ctx.view_layer.objects.active; o.name = name; settle()
    return o


def inp(obj, name):
    mod = obj.modifiers[MODIFIER_NAME]
    for item in mod.node_group.interface.items_tree:
        if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == name:
            v = mod.properties.inputs[item.identifier]["value"]
            return v
    return None


def goods(obj):
    dg = ctx.evaluated_depsgraph_get(); out = []
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.parent.original == obj and i.object.name.startswith("Placeholder"):
            out.append(i.matrix_world.translation.copy())
    return out


def item_number(obj, centre_arc, t):
    """simple_flow's k of the item whose centre is `centre_arc` along the root `obj` at scene second t."""
    tree = stream.tree_for(ctx, obj)
    v = float(inp(obj, "Speed") or 0.0)
    phase = float(inp(obj, "Stream Phase") or 0.0)
    inset = max(tree.slot_length, float(inp(obj, "Item Length"))) / 2.0
    return ((t - phase) * v - (centre_arc - inset)) / tree.actual_spacing


try:
    # A. Population sets the pitch: 0.6 m totes, 50 % -> (0.6 + 0.05) / 0.5 = 1.3 m.
    a = line("A", 0.0)
    ta = stream.tree_for(ctx, a)
    rate = stream.line_out_ph(ctx, a)
    check(abs(ta.actual_spacing - 1.3) < 2e-3 and abs(rate - 0.5 * 0.5 / 0.65 * 3600.0) < 0.5,
          f"A: 50 % of 0.6 m totes at 0.5 m/s: a 1.3 m pitch, 1385/h ({ta.actual_spacing:.4f}, {rate:.1f})")
    ys = sorted(p.y for p in goods(a))
    check(ys and all(abs((b - x) - ta.actual_spacing) < 1e-3 for x, b in zip(ys, ys[1:])), f"A: evenly spaced goods ({len(ys)})")
    # B. Speed moves the goods faster, not closer.
    a.conveyor_line.speed_m_s = 1.0; settle()
    ta = stream.tree_for(ctx, a)
    check(abs(ta.actual_spacing - 1.3) < 2e-3 and abs(stream.line_out_ph(ctx, a) - 2.0 * rate) < 1.0, "B: twice the speed, twice the rate, the same pitch")
    # C. Population 0: nothing on the line.
    a.conveyor_line.population_pct = 0.0; settle()
    check(not goods(a), "C: Population 0 % draws nothing")

    # D. The same items leave at a divert (simple_flow.branch_of_item): a 45 degree
    # diverter (no stop), the branch takes 25 % of the master: items k with
    # floor((k + 1) 0.25) > floor(k 0.25) leave, every other one rides on.
    d = line("D Main", 10.0, pieces=[('MODULE', dict(module_kind='DIVERTER', merge_angle='45')), ('STRAIGHT', dict(length_mm=4000.0))], pop=60.0)
    db = at_junction(d, 1, "D Branch")
    db.conveyor_line.share_pct = 25; settle()
    td = stream.tree_for(ctx, d)
    split = td.flow.splits.get(td.flow.split_of.get(db.name, ""))
    fractions = [f for _dst, f in split.edges] if split else []
    check(split is not None and abs(fractions[0] - 0.25) < 1e-6, f"D: the split deals 25 % to the branch first ({split.edges if split else None})")
    at = split.at_u if split else 0.0
    passed, before, wrong = set(), set(), []
    for fr in range(1, 400, 3):
        scene.frame_set(fr)
        t = fr / fps
        for p in goods(d):
            arc = p.y - d.location.y
            k = item_number(d, arc, t)
            kr = round(k)
            if abs(k - kr) > 0.02:
                wrong.append(round(k, 3))
                continue
            branch, _index = sf.branch_of_item(kr, fractions)
            if arc > at + 0.8:
                passed.add(kr)
                if branch == 0:
                    wrong.append(kr)
            elif arc < at - 0.8:
                before.add(kr)
    taken = sorted(k for k in before if sf.branch_of_item(k, fractions)[0] == 0)
    check(not wrong and passed and taken, f"D: past the divert only items simple_flow keeps on the main ({len(passed)} seen, wrong {wrong[:6]})")
    check(len(before) >= 8 and all(k not in passed for k in taken) and all(k % 4 == 3 for k in taken),
          f"D: the branch takes items 3, 7, 11, ... ({taken[:6]})")

    # E. A merge adds a feeder's goods, the owners dealt evenly: 30 % + 30 % of
    # the same totes, a 45 degree merge (no stop): the main's own goods are
    # every second slot, exactly.
    e = line("E Main", 20.0, pieces=[('MODULE', dict(module_kind='MERGE', merge_angle='45')), ('STRAIGHT', dict(length_mm=4000.0))], pop=30.0)
    ef = at_junction(e, 1, "E Feeder")
    ef.conveyor_line.populate = True; ef.conveyor_line.population_pct = 30.0; settle()
    te = stream.tree_for(ctx, e)
    check(len(te.rates) == 2 and abs(te.rates[0] - te.rates[1]) < 0.5 and abs(te.actual_spacing - 0.65 / 0.6) < 3e-3,
          f"E: two owners at the same flow, the grid at 60 % ({[round(r, 1) for r in te.rates]}, {te.actual_spacing:.4f})")
    gaps = []
    for fr in (1, 7, 13, 19):  # the main draws only its own goods: one every second slot, all along it
        scene.frame_set(fr)
        ys = sorted(p.y - e.location.y for p in goods(e) if abs(p.x - e.location.x) < 0.05)
        gaps += [b - x for x, b in zip(ys, ys[1:])]
    check(len(gaps) >= 4 and all(abs(g - 2.0 * te.actual_spacing) < 2e-3 for g in gaps), f"E: the main's goods every second slot ({[round(g, 3) for g in gaps][:8]})")

    # F. A master downstream: the branch is the master at 40 % and takes half of
    # what reaches its divert: the main runs at what keeps the branch at 40 %.
    f = line("F Main", 30.0, pieces=[('MODULE', dict(module_kind='DIVERTER', merge_angle='45')), ('STRAIGHT', dict(length_mm=4000.0))], pop=10.0)
    fb = at_junction(f, 1, "F Branch")
    with suspended_rebuild():
        fb.conveyor_line.flow_master = True
        fb.conveyor_line.population_pct = 40.0
        fb.conveyor_line.share_pct = 50
    build_line(ctx, fb); settle()
    tf = stream.tree_for(ctx, f)
    gf = tf.flow
    check(gf.master == fb.name and abs(gf.population.get(fb.name, 0.0) - 0.4) < 1e-3 and abs(gf.population.get(f.name, 0.0) - 0.8) < 1e-3,
          f"F: the branch is the master at 40 %, the main follows at 80 % ({gf.master}, {gf.population})")
    check(flows.share_text(gf, fb.name) == "Master" and flows.share_text(gf, f.name).startswith("Stream of"),
          f"F: the panels say Master / Stream of ({flows.share_text(gf, fb.name)!r}, {flows.share_text(gf, f.name)!r})")

    # G. A docked feeder runs at its main's speed (v1).
    ef.conveyor_line.speed_m_s = 0.3; settle()
    check(abs(stream.tree_for(ctx, ef).speed - 0.5) < 1e-9, "G: the feeder's goods run at the main's 0.5 m/s, its own 0.3 is not used")

    # H. A line saved before 2.22: its Population from what its old settings showed.
    h = line("H Old", 40.0)
    with suspended_rebuild():
        s = h.conveyor_line
        del s[flows.MIGRATED_KEY]
        s.throughput_ph = 1800; s.speed_m_s = 0.5; s.population_pct = 50.0
    settle()
    check(flows.is_migrated(h) and abs(h.conveyor_line.population_pct - 65.0) < 0.2,
          f"H: 1800/h at 0.5 m/s became Population 65 % ({h.conveyor_line.population_pct:.1f})")
    settle()
    from bl_ext.user_default.conveyor_system.operators.sync_stats import STATS
    dj.run_sync(scene)
    check(STATS["last_writes"] == 0, f"H: once migrated, a pass writes nothing ({STATS['last_writes']})")

    # I. set_line_rate stays as a shim: 900/h of totes at 0.5 m/s = 32.5 %; 0 gives the line its own back.
    i = line("I Rate", 50.0, pop=50.0)
    sid = ensure_identity(ctx, i)
    r = bpy.ops.conveyor.set_line_rate(line_id=sid, rate_ph=900.0, by="warehouse_racks"); settle()
    check(r == {'FINISHED'} and abs(i.conveyor_line.population_pct - 32.5) < 0.05 and abs(stream.line_out_ph(ctx, i) - 900.0) < 0.5,
          f"I: set_line_rate 900/h -> Population {i.conveyor_line.population_pct:.2f} %, publishes {stream.line_out_ph(ctx, i):.1f}/h")
    bpy.ops.conveyor.set_line_rate(line_id=sid, rate_ph=0.0, by="warehouse_racks"); settle()
    check(abs(i.conveyor_line.population_pct - 50.0) < 1e-6, f"I: 0 gives the line its own 50 % back ({i.conveyor_line.population_pct})")

    # J. The silent cap: a 90 degree pop-up divert stops the goods, so 100 % cannot run nose to tail.
    j = line("J Main", 60.0, pieces=[('MODULE', dict(module_kind='DIVERTER', merge_angle='90')), ('STRAIGHT', dict(length_mm=3000.0))], pop=100.0)
    at_junction(j, 1, "J Branch")
    tj = stream.tree_for(ctx, j)
    eff = tj.flow.population.get(j.name, 1.0)
    check(eff < 0.99 and tj.actual_spacing >= tj.min_spacing - 1e-6, f"J: 100 % runs at {eff * 100:.0f} %, the transfer's pitch ({tj.actual_spacing:.3f} m)")

    # K. A bypass (out at a divert, back into the same main downstream) is a
    # branch: it takes its Share and gives it back at the re-join (simple_flow:
    # s2 = s0), its goods keep pace over its longer path so they merge back
    # into the very slots they left -- nothing collides, nothing vanishes.
    k = line("K Main", 70.0, pieces=[('MODULE', dict(module_kind='DIVERTER', merge_angle='90')), ('STRAIGHT', dict(length_mm=9000.0))], pop=40.0)
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
    parent = stream.parent_of(ctx, kb)
    tk = stream.tree_for(ctx, k)
    gk = tk.flow
    ls = tk.members.get(kb.name)
    first, last = gk.nodes[gk.sections[k.name][0]].flow, gk.nodes[gk.sections[k.name][-1]].flow
    takes = gk.nodes[gk.sections[kb.name][0]].flow
    check(parent is not None and parent[0] == 'DIVERTER' and ls is not None and ls.stretch,
          f"K: the bypass is a branch with a stretch ({parent[0] if parent else None}, {ls.stretch if ls else None})")
    check(abs(takes / first - 0.3) < 1e-3 and abs(last - first) < 1e-9, f"K: it takes 30 % and gives it back ({takes / first:.3f}, {first:.4f} -> {last:.4f})")
    ratio = ls.stretch[2] / ls.stretch[1] if ls and ls.stretch else 0.0
    check(ratio > 1.0 and abs(stream.line_speed(ctx, kb) - 0.5 * ratio) < 1e-6, f"K: its goods keep pace, {ratio:.2f} x the main's speed")
    worst, before_n, after_n = 9.0, 0, 0
    for fr in range(1, 300, 5):
        scene.frame_set(fr)
        on_main = sorted(p.y - k.location.y for o in (k, kb) for p in goods(o) if abs(p.x - k.location.x) < 0.05)
        before_n += sum(1 for y in on_main if y < 3.0)
        after_n += sum(1 for y in on_main if 8.6 < y < 11.6)
        for y0, y1 in zip(on_main, on_main[1:]):
            if y1 > 8.0:
                worst = min(worst, y1 - y0)
    check(worst > 0.6 + 0.005, f"K: past the re-join no two goods overlap (closest {worst:.3f} m)")
    check(abs(after_n - before_n) <= max(2, 0.15 * before_n), f"K: as many goods after the re-join as before the divert ({before_n} / {after_n} over 3 m)")

    # L. The goods run at the very pitch the stream publishes, whatever the line's
    # length: the wrap holds a whole number of them in the tree's single precision
    # too (an exact multiple floored one slot short there: every pitch 1/n wider).
    bad, n_lines = [], 0
    for i, mm in enumerate(range(3000, 16001, 650)):
        for j, pop in enumerate((37.0, 52.0, 61.0)):
            o = line(f"L{i}.{j}", 100.0 + 2.5 * (3 * i + j), length_mm=float(mm), pop=pop)
            n_lines += 1
            tl = stream.tree_for(ctx, o)
            scene.frame_set(1)
            ys = sorted(p.y - o.location.y for p in goods(o))
            gaps = [b - x for x, b in zip(ys, ys[1:])]
            if not gaps or any(abs(g - tl.actual_spacing) > 1e-3 for g in gaps):
                bad.append((mm, pop, round(tl.actual_spacing, 4), sorted({round(g, 4) for g in gaps})[:3]))
    check(not bad, f"L: on {n_lines} lines the goods run at the pitch the stream publishes ({len(bad)} off: {bad[:3]})")
except Exception:
    traceback.print_exc(); fails.append("raised")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
