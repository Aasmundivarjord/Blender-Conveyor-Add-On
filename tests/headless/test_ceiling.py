"""2.15.0 (round 7, R17): a line hung from the ceiling hangs from its hall's
clear height -- its level's z + `headroom_m` in the Building's `wh_levels` --
else the Scene panel's Ceiling level; the sync pass follows changes and
writes nothing once settled. With Floorplan >= 0.3.0-dev.2 in the sandbox the
real Building is used too.
Blender -b --python tests/headless/test_ceiling.py"""
import json, math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
try:  # the real Building when the sandbox has Floorplan (git archive of a tag)
    bpy.ops.preferences.addon_enable(module="bl_ext.user_default.warehouse_floorplan")
except Exception as e:
    print("note: Floorplan not enabled:", e)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, ceilings
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
from bl_ext.user_default.conveyor_system._wh import ops as wh_ops
ctx = bpy.context; scene = ctx.scene; fails = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
def rods(obj):
    dg = ctx.evaluated_depsgraph_get(); out = []
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.parent.original == obj:
            d = i.object.dimensions
            if abs(d[0] - 0.016) < 0.003 and abs(d[1] - 0.016) < 0.003 and d[2] > 0.05:
                out.append(round(i.matrix_world.translation.z + d[2] / 2.0, 2))
    return sorted(set(out))
def hung(name, loc, length_mm=4000):
    o = create_line(ctx, Vector((300.0, 300.0, 0.0)), 0.0); o.name = name; o.location = Vector(loc)
    with suspended_rebuild():
        o.conveyor_line.segments[0]["length_mm"] = float(length_mm)
        o.conveyor_line.support_mount = 'CEILING'
    ctx.view_layer.update(); build_line(ctx, o); ctx.view_layer.update()
    return o
def settle():
    for _ in range(3):
        ctx.view_layer.update(); dj.run_sync(scene)
    ctx.view_layer.update()
def levels(headroom=10.5):
    return json.dumps([{"version": 2, "id": 0, "label": "Ground", "z": 0.0, "footprint": [[0, 0], [40, 0], [40, 80], [0, 80]], "headroom_m": headroom},
                       {"version": 2, "id": "mezz1", "label": "Mezzanine 1", "z": 4.2, "footprint": [[0, 0], [30, 0], [30, 12], [0, 12]], "headroom_m": 3.4}],
                      separators=(",", ":"))
try:
    scene.conveyor_settings.ceiling_z = 6.0
    # A hall 40 x 80 m, moved and turned 90 degrees: local (x, y) -> world (100 - y, x).
    hall = bpy.data.objects.new("Hall", None); scene.collection.objects.link(hall)
    hall.location = (100.0, 0.0, 0.0); hall.rotation_euler = (0.0, 0.0, math.radians(90.0))
    hall["wh_levels"] = levels(); ctx.view_layer.update()
    inside = hung("Inside", (60.0, 20.0, 2.4))
    outside = hung("Outside", (0.0, -10.0, 2.4))
    on_mezz = hung("On the mezzanine", (94.0, 10.0, 5.2))
    settle()
    s = inside.conveyor_line
    check(rods(inside) == [10.5] and abs(float(s["ceiling_z_m"]) - 10.5) < 1e-6 and s["ceiling_from"] == "Hall clear height",
          f"inside the hall: rods up to its clear height ({rods(inside)}, {s.get('ceiling_from')!r})")
    check(rods(outside) == [6.0] and outside.conveyor_line.get("ceiling_from", "") == "", f"outside every hall: the Scene ceiling level ({rods(outside)})")
    check(rods(on_mezz) == [7.6] and on_mezz.conveyor_line.get("ceiling_from") == "Hall · Mezzanine 1",
          f"on the mezzanine: its z + its headroom ({rods(on_mezz)}, {on_mezz.conveyor_line.get('ceiling_from')!r})")
    # The hall's clear height changes (Floorplan's panel): the pass follows, then settles.
    hall["wh_levels"] = levels(9.25)
    w1 = dj.run_sync(scene); ctx.view_layer.update()
    w2 = dj.run_sync(scene)
    check(rods(inside) == [9.25] and w1 > 0 and w2 == 0, f"9.25 m clear: the pass follows ({w1} writes), then writes nothing ({w2})")
    # A line moved into the hall picks the hall's ceiling up.
    outside.location = (60.0, 30.0, 2.4); ctx.view_layer.update(); settle()
    check(rods(outside) == [9.25], f"moved into the hall: {rods(outside)}")
    # The Scene setting no longer moves a line inside a hall, still moves one outside.
    out2 = hung("Outside again", (-20.0, -10.0, 2.4)); settle()
    scene.conveyor_settings.ceiling_z = 7.0; ctx.view_layer.update(); settle()
    check(rods(inside) == [9.25] and rods(out2) == [7.0], f"Scene ceiling level 7 m: inside stays {rods(inside)}, outside {rods(out2)}")
    # A floor line is left alone; a settled scene makes no writes.
    floor_line = create_line(ctx, Vector((300.0, 300.0, 0.0)), 0.0); floor_line.location = (60.0, 50.0, 1.0)
    ctx.view_layer.update(); build_line(ctx, floor_line); settle()
    check(dj.run_sync(scene) == 0, "settled: 0 writes (a floor line keeps the value from its build)")
    # The real Building (Floorplan publishes the ground level's clear height from 0.3.0-dev.2).
    if wh_ops.operator_exists(bpy.ops, "floorplan.add_system"):
        r = bpy.ops.floorplan.add_system(kind="building", preset="EU_40x80", location=(-200.0, 0.0, 0.0))
        settle()
        b = next((o for o in scene.objects if o.get("wh_levels") and o is not hall), None)
        ground = None
        if b is not None:
            raw = b["wh_levels"]
            data = json.loads(raw) if isinstance(raw, str) else raw.to_list() if hasattr(raw, "to_list") else list(raw)
            ground = next((lv for lv in data if isinstance(lv, dict) and str(lv.get("id")) == "0" and lv.get("headroom_m")), None)
        if ground is not None:
            fp = ground["footprint"]; cx = sum(p[0] for p in fp) / len(fp); cy = sum(p[1] for p in fp) / len(fp)
            M = b.matrix_world; centre = M @ Vector((cx, cy, 0.0))
            real = hung("In the real building", (centre.x, centre.y, 2.4)); settle()
            want = round(b.matrix_world.translation.z + float(ground["headroom_m"]), 2)
            check(rods(real) == [want] and real.conveyor_line.get("ceiling_from", "").endswith("clear height"),
                  f"Floorplan's Building ({b.name}): rods up to its {float(ground['headroom_m']):g} m clear height ({rods(real)})")
        else:
            print(f"SKIP: the real-building R17 case: this Floorplan publishes no ground clear height (R17 from 0.3.0-dev.2); add_system {r}")
    else:
        print("SKIP: the real-building R17 case: no Floorplan in this sandbox (the synthetic hall covers R17)")
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
