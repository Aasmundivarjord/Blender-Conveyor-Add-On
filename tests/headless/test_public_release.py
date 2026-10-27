"""What a new user meets first (2.25, extensions.blender.org): the add-on
enables and disables cleanly again and again (no handler left behind), a
line builds in a millimetre-scaled scene and in imperial units, and a line of
every type evaluates to real geometry. Blender -b --python tests/headless/test_public_release.py"""
import math, traceback, bpy
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
fails = []


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)


def ours(handlers):
    return [h for h in handlers if getattr(h, "__module__", "").startswith(PKG)]


def all_handlers():
    out = []
    for name in dir(bpy.app.handlers):
        lst = getattr(bpy.app.handlers, name)
        if isinstance(lst, list):
            out += [(name, h) for h in ours(lst)]
    return out


def extent(obj):
    """Length of the evaluated line along Y, its heading (Blender units): its mesh and its instances."""
    dg = bpy.context.evaluated_depsgraph_get()
    geo = obj.evaluated_get(dg).evaluated_geometry()
    xs = []
    if geo.mesh is not None and len(geo.mesh.vertices):
        mw = obj.matrix_world
        xs = [(mw @ v.co).y for v in geo.mesh.vertices]
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.parent.original == obj:
            xs.append(i.matrix_world.translation.y)
    return (max(xs) - min(xs)) if xs else 0.0


def verts(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    geo = ev.evaluated_geometry()
    n = len(geo.mesh.vertices) if geo.mesh else 0
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.parent.original == obj:
            n += 1
    return n


try:
    # A. enable / disable / enable: nothing left behind
    for cycle in range(3):
        bpy.ops.preferences.addon_enable(module=PKG)
        check(PKG in bpy.context.preferences.addons and len(all_handlers()) > 0, f"enable #{cycle + 1}: handlers {sorted({n for n, _h in all_handlers()})}")
        bpy.ops.preferences.addon_disable(module=PKG)
        check(PKG not in bpy.context.preferences.addons and not all_handlers(), f"disable #{cycle + 1}: no handler left {all_handlers()}")
    bpy.ops.preferences.addon_enable(module=PKG)
    from bl_ext.user_default.conveyor_system.operators.new_line import create_line
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line
    from bl_ext.user_default.conveyor_system.config import loader
    ctx = bpy.context; scene = ctx.scene

    # B. a millimetre-scaled scene (unit scale 0.001): a line L metres long is L x 1000 units long
    scene.unit_settings.system = 'METRIC'; scene.unit_settings.scale_length = 0.001; scene.unit_settings.length_unit = 'MILLIMETERS'
    mm = create_line(ctx, Vector((0.0, 0.0, 800.0)), 0.0); mm.name = "Millimetres"
    build_line(ctx, mm); ctx.view_layer.update()
    ext, want = extent(mm), sum(s.length_mm for s in mm.conveyor_line.segments)  # mm = units at scale 0.001
    check(verts(mm) > 0 and abs(ext - want) < 0.02 * want, f"unit scale 0.001: a {want / 1000:g} m line is {want:g} units long ({ext:.1f})")
    bpy.data.objects.remove(mm)

    # C. imperial units, unit scale 1
    scene.unit_settings.system = 'IMPERIAL'; scene.unit_settings.scale_length = 1.0; scene.unit_settings.length_unit = 'FEET'
    imp = create_line(ctx, Vector((0.0, 0.0, 0.8)), 0.0); imp.name = "Imperial"
    build_line(ctx, imp); ctx.view_layer.update()
    ext, want = extent(imp), sum(s.length_mm for s in imp.conveyor_line.segments) / 1000.0
    check(verts(imp) > 0 and abs(ext - want) < 0.02 * want, f"imperial units: a {want:g} m line is {want:g} Blender units long ({ext:.3f})")
    scene.unit_settings.system = 'METRIC'; scene.unit_settings.length_unit = 'METERS'

    # D. every conveyor type builds and draws, populated
    x = 0.0
    for tid, spec in loader.get_conveyor_types().items():
        if spec.category not in ("line", "conveyor") and spec.cross_section in ("", None):
            continue
        o = create_line(ctx, Vector((x, 10.0, 0.8 if tid != "pouch_sorter" else 3.0)), 0.0); o.name = f"Type {tid}"
        try:
            o.conveyor_line.conveyor_type = tid
        except TypeError:
            bpy.data.objects.remove(o)
            continue
        o.conveyor_line["populate"] = True
        build_line(ctx, o); ctx.view_layer.update()
        check(verts(o) > 0, f"type {tid} ({spec.label}) builds and evaluates")
        x += 4.0
except Exception:
    traceback.print_exc(); fails.append("raised")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
