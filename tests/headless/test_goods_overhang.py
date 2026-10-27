"""2.21.1 (PM, 2026-10-15): a quiet note when the goods are wider than the
line they ride on. A 90 degree transfer keeps their orientation, so the
default 600 x 400 tote, long side first on a 500 mm main, crosses a 500 mm
branch with its 600 mm side; a feeder's goods do the same on the main after
a 90 degree merge; an item can simply be wider than its line.
Blender -b --python tests/headless/test_goods_overhang.py"""
import bpy, math, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line, resolve_width_mm
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
from bl_ext.user_default.conveyor_system.operators.populate import overhang_notes, TURNED_NOTE
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
ctx = bpy.context; scene = ctx.scene; fails = []


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)


def settle(n=4):
    for _ in range(n):
        ctx.view_layer.update(); dj.run_sync(scene)
    ctx.view_layer.update()


def main_line(name, x, module=None, angle='90', populate=True):
    o = create_line(ctx, Vector((x, 0.0, 0.8)), 0.0); o.name = name
    with suspended_rebuild():
        s = o.conveyor_line
        s.segments[0]["length_mm"] = 3000.0
        if module:
            m = s.segments.add(); m.kind = 'MODULE'; m.module_kind = module; m.merge_angle = angle
            t = s.segments.add(); t.kind = 'STRAIGHT'; t["length_mm"] = 3000.0
        s.populate = populate; s.speed_m_s = 0.5
    build_line(ctx, o); settle()
    return o


def at_junction(main, name):
    bpy.ops.conveyor.new_line_at_junction(line_name=main.name, index=1, side='LEFT')
    o = ctx.view_layer.objects.active; o.name = name; settle()
    return o


def texts(o):
    return [t for t, _dim in overhang_notes(ctx, o)]


try:
    main = main_line("Main", 0.0, 'DIVERTER')
    branch = at_junction(main, "Branch")
    w = resolve_width_mm(main.conveyor_line)
    check(abs(w - 500.0) < 1e-6 and abs(resolve_width_mm(branch.conveyor_line) - 500.0) < 1e-6, f"default lines are 500 mm ({w})")
    check(texts(main) == [], f"main: 400 mm totes on 500 mm, no note ({texts(main)})")
    check(texts(branch) == ["Goods 600 mm across, line 500 mm", TURNED_NOTE],
          f"branch after the 90° divert: the tote's 600 mm side across ({texts(branch)})")
    branch.conveyor_line.width_preset = 'iso_650'; settle()
    check(texts(branch) == [], f"a 650 mm branch fits ({texts(branch)})")

    wide = bpy.data.objects.new("Wide crate", bpy.data.meshes.new("Wide crate"))
    scene.collection.objects.link(wide)
    import bmesh
    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0); bm.to_mesh(wide.data); bm.free()
    wide.scale = (0.6, 0.6, 0.3); wide.location = (-20.0, -20.0, 0.0)
    crate = main_line("Crate line", 10.0)
    crate.conveyor_line.populate_item = wide; settle()
    check(texts(crate) == ["Goods 600 mm across, line 500 mm"], f"an item wider than its line ({texts(crate)})")

    m90 = main_line("Main 90", 20.0, 'MERGE', '90')
    f90 = at_junction(m90, "Feeder 90")
    check(dj.docked_junction(ctx, f90, 'MERGE') is not None, "the 90° feeder docks")
    check(texts(f90) == ["Goods 600 mm across on Main 90", "It is 500 mm; goods ride sideways"],
          f"90° merge: the feeder's totes ride across the main ({texts(f90)})")
    m45 = main_line("Main 45", 30.0, 'MERGE', '45')
    f45 = at_junction(m45, "Feeder 45")
    check(dj.docked_junction(ctx, f45, 'MERGE') is not None and texts(f45) == [], f"45° merge: aligned with the main, no note ({texts(f45)})")
    empty = main_line("Empty", 40.0, populate=False)
    empty.conveyor_line.custom_width_mm = 300.0
    check(texts(empty) == [], "no goods, no note")
except Exception:
    traceback.print_exc(); fails.append("raised")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
