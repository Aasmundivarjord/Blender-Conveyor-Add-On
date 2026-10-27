"""The accumulation buffer, 2.24 (round 8 E, R22.6; model/buffer_fifo): it
takes what the line before brings; Output % of it leaves -- one item every
in-period / Output %, first in first out, as warehouse_common's
buffer_item_times -- the rest piles up a zone each until the buffer is full;
then the stream's root runs at what it lets out and the queue holds. Output
100 % lets the goods pass. A slug release lets a full buffer's zones go
together. The piece panel says it in Output % and time (2.24.1). Blender -b
--python tests/headless/test_buffer.py"""
import math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line, MODIFIER_NAME
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, stream
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
from bl_ext.user_default.conveyor_system._wh import simple_flow as sf
ctx = bpy.context; scene = ctx.scene; fails = []
fps = scene.render.fps / (scene.render.fps_base or 1.0)
ENTRY, EXIT = 6.0, 9.0  # the buffer piece, metres along the line
FRONT = EXIT - 0.15 - 0.3  # the front item's centre: one queue gap before the exit (photo-eye)


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)


def settle(n=4):
    for _ in range(n):
        ctx.view_layer.update(); dj.run_sync(scene)
    ctx.view_layer.update()


def inp(obj, name):
    mod = obj.modifiers[MODIFIER_NAME]
    for item in mod.node_group.interface.items_tree:
        if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == name:
            v = mod.properties.inputs[item.identifier]["value"]
            return v.name if hasattr(v, "name") else v


def ys(obj):
    dg = ctx.evaluated_depsgraph_get()
    return sorted(round(i.matrix_world.translation.y - obj.location.y, 4) for i in dg.object_instances
                  if i.is_instance and i.parent and i.parent.original == obj and "Placeholder" in i.object.name)


def make(name, x, out_pct, release='SINGULATED'):
    """6 m, a 3 m buffer (4 zones of 0.6 m totes + 0.15 m), 6 m on; Population 50 % at 0.5 m/s: 1385/h."""
    o = create_line(ctx, Vector((x, 0.0, 0.8)), 0.0); o.name = name
    with suspended_rebuild():
        s = o.conveyor_line; s.segments[0]["length_mm"] = 6000.0
        b = s.segments.add(); b.kind = 'MODULE'; b.module_kind = 'BUFFER'; b["length_mm"] = 3000.0
        b["buffer_out_pct"] = out_pct; b.buffer_release = release
        t = s.segments.add(); t.kind = 'STRAIGHT'; t["length_mm"] = 6000.0
        s.populate = True; s.speed_m_s = 0.5; s.population_pct = 50.0
    build_line(ctx, o); settle()
    return o


def exits(obj, frames):
    """Scene seconds at which goods' centres pass the buffer's exit, one per item (followed across frames)."""
    out = []
    for fr in frames:
        scene.frame_set(fr)
        t = fr / fps
        for y in ys(obj):
            if EXIT <= y < EXIT + 0.5:  # just past the exit: it left (y - EXIT) / v ago
                out.append(t - (y - EXIT) / 0.5)
    out.sort()
    merged = []
    for x in out:
        if not merged or x - merged[-1][-1] > 0.3:
            merged.append([x])
        else:
            merged[-1].append(x)
    return [sum(m) / len(m) for m in merged]


try:
    # A. Output 100 %: nothing piles up, the goods pass at the stream's pace.
    a = make("A Passes", 0.0, 100)
    scene.frame_set(200); y1 = [y for y in ys(a) if ENTRY < y < EXIT]
    scene.frame_set(212); y2 = [y for y in ys(a) if ENTRY < y < EXIT]
    check(stream.tree_for(ctx, a).members[a.name].buffers == [] and y1 and y1 != y2,
          f"A: Output 100 %: the goods roll through the buffer ({y1} -> {y2})")

    # B. Output 40 %: 1385/h in, 554/h out: one leaves every 6.5 s; the other 0.23 items/s pile up, 4 zones: full after 17.3 s.
    b = make("B Fills", 10.0, 40)
    tb = stream.tree_for(ctx, b)
    info = tb.buffer_info[(b.name, 1)]
    stop, pitch, period, start, first, mode, slug = tb.members[b.name].buffers[0]
    check(abs(period - 6.5) < 1e-6 and info["zones"] == 4 and abs(info["out"] - 0.4 * info["in"]) < 1e-6,
          f"B: one leaves every {period:.2f} s (6.5), 4 zones, out = 40 % of in ({info['in']:.0f} -> {info['out']:.0f}/h)")
    fill = sf.buffer_fill(1e6, info["in"] / 3600.0, 0.4, 4).full_at
    check(abs((info["full_s"] - start) - fill) < 1e-6, f"B: full {info['full_s'] - start:.1f} s after the first held arrives: buffer_fill's {fill:.1f}")
    counts = []
    for fr in range(1, 1201, 24):
        scene.frame_set(fr)
        counts.append(len([y for y in ys(b) if ENTRY <= y <= EXIT]))
    late = counts[len(counts) // 2:]
    check(max(counts[:3]) < 4 and all(c == 4 for c in late), f"B: it fills, then holds its 4 zones ({counts})")
    scene.frame_set(1000)
    queue = [y for y in ys(b) if ENTRY <= y <= EXIT]
    gaps = [round(q2 - q1, 4) for q1, q2 in zip(queue, queue[1:])]
    check(queue and abs(queue[-1] - FRONT) < 1e-3 and all(abs(gp - pitch) < 1e-3 for gp in gaps),
          f"B: the queue stands a zone apart, the front at the photo-eye ({queue})")
    # The departures: every 6.5 s, the times warehouse_common's buffer_item_times gives the items held.
    seen = exits(b, range(240, 1441, 2))
    gaps = [round(t2 - t1, 3) for t1, t2 in zip(seen, seen[1:])]
    check(len(gaps) >= 6 and all(abs(gp - period) < 0.05 for gp in gaps), f"B: one leaves every {period:.1f} s ({gaps[:8]})")
    v = 0.5
    # (ranked from the first held: it reaches the stop at `start`, one every 2.6 s before the switch)
    want = [sf.buffer_item_times(m, [[0.0, start, 1.3 / v]], 0.4, 4, t0=start)[1] + (EXIT - FRONT) / v for m in range(0, 40)]
    near = [min(abs(t - w) for w in want) for t in seen]
    check(max(near) < 1.3 / v, f"B: each within one in-period of buffer_item_times (worst {max(near):.3f} s of {1.3 / v:.1f})")
    # The line before runs at what the full buffer lets out: its grid thinned to 40 %.
    early, late = [], []
    for fr in range(1, 25, 4):
        scene.frame_set(fr); early.append(len([y for y in ys(b) if y < ENTRY - 0.5]))
    for fr in range(1200, 1500, 4):
        scene.frame_set(fr); late.append(len([y for y in ys(b) if y < ENTRY - 0.5]))
    ratio = (sum(late) / len(late)) / max(sum(early) / len(early), 1e-6)
    check(math.isfinite(tb.switch_time) and abs(tb.switch_fraction - 0.4) < 1e-9 and 0.25 < ratio < 0.6,
          f"B: once full the line before runs at 40 % ({sum(early) / len(early):.1f} -> {sum(late) / len(late):.1f} goods before it)")
    check(abs(stream.tree_for(ctx, b).flow.population.get(b.name, 0) - 0.5) < 1e-9,
          "B: what it publishes stays the state before full (R22.6): Population 50 %")

    # C. A slug: the full buffer's 4 zones leave together, nose to tail.
    c = make("C Slug", 20.0, 40, release='SLUG')
    sc = stream.tree_for(ctx, c).members[c.name].buffers[0]
    seen = exits(c, range(240, 1441, 2))
    gaps = [round(t2 - t1, 2) for t1, t2 in zip(seen, seen[1:])]
    short = [gp for gp in gaps if gp < 2.0]
    check(sc[6] == 4 and len(short) >= 3 and all(abs(gp - sc[1] / 0.5) < 0.05 for gp in short),
          f"C: slugs of 4 leave nose to tail, a zone apart ({gaps[:10]})")

    # D. The piece panel (2.24.1, PM): Output % and time, never items an hour, <= 36 characters a line;
    # a buffer that fills after the scene's end frame says so.
    from bl_ext.user_default.conveyor_system.ui import panels

    class Rec:
        def __init__(self, out):
            self.out, self.enabled, self.alert = out, True, False
        def row(self, **_kw):
            return Rec(self.out)
        column = box = row
        def label(self, text="", **_kw):
            self.out.append(text)
        def prop(self, *_a, **_kw):
            pass

    def drawn(obj):
        obj.conveyor_line.active_segment_index = 1
        out = []
        panels.VIEW3D_PT_conveyor_piece._buffer_numbers(Rec(out), ctx, obj, obj.conveyor_line)
        return out

    scene.frame_end = 250  # 10.4 s: B is full after it
    lines_b = drawn(b)
    check(lines_b[:2] == ["Lets out 40 % of what arrives", "Full after 17 s (after scene end)"],
          f"D: Output % and when it is full -- after the scene's end ({lines_b})")
    scene.frame_end = 1200
    lines_b2 = drawn(b)
    check(lines_b2[:2] == ["Lets out 40 % of what arrives", "Full after 17 s, then holds 4"], f"D: within the scene: then holds 4 ({lines_b2})")
    lines_a = drawn(a)
    check(lines_a[:1] == ["Lets everything through"], f"D: Output 100 % ({lines_a})")
    every = lines_b + lines_b2 + lines_a + drawn(c)
    check(all("/h" not in x and len(x) <= 36 for x in every), f"D: no items an hour, <= 36 characters ({every})")
    fill = lambda s: panels.buffer_fill_text(s, 4, 1.0, scene)
    check([fill(17.3), fill(240.0), fill(36000.0)] == ["Full after 17 s, then holds 4", "Full after 4 min, then holds 4", "Full after 10 h, then holds 4"],
          f"D: seconds, minutes, hours ({fill(17.3)}, {fill(240.0)}, {fill(36000.0)})")
    settle(2)
    dj.run_sync(scene)
    from bl_ext.user_default.conveyor_system.operators.sync_stats import STATS
    check(STATS["last_writes"] == 0, f"a settled scene: the pass writes nothing ({STATS['last_writes']})")
except Exception:
    traceback.print_exc(); fails.append("raised")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
