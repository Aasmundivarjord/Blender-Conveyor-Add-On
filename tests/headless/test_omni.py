import math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line, MODIFIER_NAME
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
ctx = bpy.context; fails = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
def wheels(obj, region=None):
    dg = ctx.evaluated_depsgraph_get(); n = 0
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.parent.original == obj:
            dims = tuple(round(c, 3) for c in i.object.dimensions)
            if abs(dims[0] - 0.02) < 0.006 and abs(dims[1] - 0.04) < 0.005 and abs(dims[2] - 0.04) < 0.005:
                p = i.matrix_world.translation
                if region is None or region(p): n += 1
    return n
try:
    main = create_line(ctx, Vector((100, 100, 0)), 0.0); main.name = "Omni"; main.location = Vector((0, 0, 0))
    with suspended_rebuild():
        s = main.conveyor_line
        s.conveyor_type = 'omni'
        s.segments[0]["length_mm"] = 4000.0
        r = s.segments.add(); r.kind = 'MODULE'; r.module_kind = 'RAT'; r.module_exit = 'LEFT'
        t = s.segments.add(); t.kind = 'STRAIGHT'; t["length_mm"] = 3000.0
        s.populate = True
    ctx.view_layer.update(); build_line(ctx, main); ctx.view_layer.update()
    check(main.modifiers[MODIFIER_NAME].node_group.name.endswith("(Omni)"), "omni line tree built")
    n_run = wheels(main, lambda p: 0.2 < p.y < 3.8 and abs(p.x) < 0.3)
    check(n_run > 150, f"wheel rows along the straight ({n_run})")
    n_rat = wheels(main, lambda p: 4.0 < p.y < 5.0 or (p.y > 4.3 and p.x < -0.3))
    check(n_rat > 20, f"wheels on the RAT module ({n_rat})")
    dg = ctx.evaluated_depsgraph_get(); geo = main.evaluated_get(dg).evaluated_geometry(); me = geo.mesh
    check(me is not None and len(me.polygons) > 100, "deck plate and frame evaluate")
    # a roller feeder merging onto the omni line: junction gets a wheel deck
    f = create_line(ctx, Vector((100, 100, 0)), -math.pi / 4); f.name = "Feeder"; f.location = Vector((-2.6, -0.3, 0))
    with suspended_rebuild():
        f.conveyor_line.segments[0]["length_mm"] = 3000.0
    ctx.view_layer.update(); build_line(ctx, f); ctx.view_layer.update()
    j = dj.docked_junction(ctx, f)
    check(j is not None, "roller feeder docks onto the omni line")
    if j:
        center, fh, geom = dj._module_face_world(ctx, main, j[1], None)
        n_j = wheels(main, lambda p: (p - center).length < 0.8 and p.x < -0.26)
        check(n_j > 5, f"wheels cover the merge wedge ({n_j})")
    import os
    if os.environ.get("TMPDIR"):  # a look at the scene for a person: the scratch temp folder, never the project's scenes (rule §2.10)
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(os.environ["TMPDIR"], "Omni check.blend"))
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
