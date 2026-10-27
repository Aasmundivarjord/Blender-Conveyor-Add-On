import math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line, MODIFIER_NAME
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
ctx = bpy.context; fails = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
def insts(obj, pred):
    dg = ctx.evaluated_depsgraph_get(); out = []
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.parent.original == obj:
            dims = tuple(round(c, 3) for c in i.object.dimensions)
            if pred(dims): out.append(i.matrix_world.translation.copy())
    return out
def items(obj):
    dg = ctx.evaluated_depsgraph_get(); out = []
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.parent.original == obj and "Placeholder" in i.object.name:
            out.append((i.matrix_world.translation.copy(), i.matrix_world.to_euler()))
    return out
def make(loc, heading, segs, name, ctype='gravity_roller', populate=False):
    o = create_line(ctx, Vector((100, 100, 0)), heading); o.name = name; o.location = Vector(loc)
    with suspended_rebuild():
        s = o.conveyor_line; s.conveyor_type = ctype
        for i, spec in enumerate(segs):
            seg = s.segments[0] if i == 0 else s.segments.add()
            seg.kind = spec[0]
            if spec[0] == 'STRAIGHT': seg["length_mm"] = float(spec[1])
            elif spec[0] == 'SPIRAL': seg.spiral_turns = spec[1]; seg["rise_mm"] = float(spec[2]); seg.curve_direction = spec[3]
            elif spec[0] == 'MODULE':
                seg.module_kind = spec[1]
                if spec[1] == 'LIFT': seg.lift_shape = spec[2]; seg["rise_mm"] = float(spec[3])
        s.populate = populate; s.speed_m_s = 0.5
    ctx.view_layer.update(); build_line(ctx, o); ctx.view_layer.update()
    return o
try:
    # ---- A. floors: a plain mesh plane at z=2 under a line raised to z=4, no setup at all
    line = make((0, 0, 4.0), 0.0, [('STRAIGHT', 6000)], "High")
    feet = insts(line, lambda d: abs(d[0] - 0.144) < 0.01 and abs(d[2] - 0.012) < 0.005)
    check(feet and all(abs(p.z - 0.006) < 0.03 for p in feet), "no floors yet: legs reach Floor Level 0")
    bpy.ops.mesh.primitive_plane_add(size=4, location=(0, 3, 2.0)); plane = ctx.view_layer.objects.active; plane.name = "Mezzanine"
    ctx.view_layer.update()
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
    dj.run_sync(ctx.scene)  # what Blender does after the plane was added
    ctx.view_layer.update()
    feet = insts(line, lambda d: abs(d[0] - 0.144) < 0.01 and abs(d[2] - 0.012) < 0.005)
    on_mezz = [p for p in feet if 1.0 < p.y < 5.0 and abs(p.x) < 0.5]
    zs = sorted(round(p.z, 2) for p in on_mezz)
    print("foot z over the plane:", zs)
    check(on_mezz and all(abs(z - 2.006) < 0.03 for z in zs), "legs land on a plane simply placed under the line (feet at z~2)")
    check(plane.name in {o.name for o in bpy.data.collections["Conveyor Floors (auto)"].objects}, "the plane joined the automatic floors")
    plane.location.z = 1.0; ctx.view_layer.update()
    feet = insts(line, lambda d: abs(d[0] - 0.144) < 0.01 and abs(d[2] - 0.012) < 0.005)
    check(feet and all(abs(p.z - 1.006) < 0.03 for p in feet if 1.0 < p.y < 5.0 and abs(p.x) < 0.5), "moving the plane moves the feet with it")
    # an explicit Floors collection still takes precedence
    coll = bpy.data.collections.new("Floors"); ctx.scene.collection.children.link(coll); coll.objects.link(plane)
    ctx.scene.conveyor_settings.floor_collection = coll; ctx.view_layer.update()
    feet = insts(line, lambda d: abs(d[0] - 0.144) < 0.01 and abs(d[2] - 0.012) < 0.005)
    check(feet and all(abs(p.z - 1.006) < 0.03 for p in feet if 1.0 < p.y < 5.0 and abs(p.x) < 0.5), "explicit Floors collection works too")
    ctx.scene.conveyor_settings.floor_collection = None
    plane.location.z = 2.0; ctx.view_layer.update()
    ctx.scene.conveyor_settings.floor_collection = None; ctx.view_layer.update()
    feet = insts(line, lambda d: abs(d[0] - 0.144) < 0.01 and abs(d[2] - 0.012) < 0.005)
    zs2 = sorted(round(p.z, 2) for p in feet if p.y > 5.5 or p.y < 0.5)
    check(zs2 and all(abs(z - 0.006) < 0.03 for z in zs2), f"legs beyond the plane still reach Floor Level 0 ({zs2[:3]})")
    ctx.scene.conveyor_settings.floor_z = -1.0; ctx.view_layer.update()
    feet = insts(line, lambda d: abs(d[0] - 0.144) < 0.01 and abs(d[2] - 0.012) < 0.005)
    beyond = [p for p in feet if p.y > 5.5 or p.y < 0.5]
    check(beyond and all(abs(p.z + 0.994) < 0.03 for p in beyond), "Floor Level -1 lengthens the legs beyond the plane")
    ctx.scene.conveyor_settings.floor_z = 0.0
    # ---- B. spiral
    sp = make((10, 0, 0), 0.0, [('STRAIGHT', 2000), ('SPIRAL', 2.0, 4000.0, 'LEFT'), ('STRAIGHT', 2000)], "Spiral", populate=True)
    ex, ey, ez, eh = sp.conveyor_line.end_pose
    check(abs(ez - 4.0) < 1e-3 and abs(eh % 360) < 1e-3, f"spiral end at z {ez:.2f}, heading {eh:.0f}")
    dg = ctx.evaluated_depsgraph_get(); geo = sp.evaluated_get(dg).evaluated_geometry(); me = geo.mesh
    mw = sp.matrix_world
    col = [mw @ v.co for v in me.vertices if abs((mw @ v.co).x - (10 - 1.05)) < 0.25 and abs((mw @ v.co).y - 2.0) < 0.25]
    czs = [p.z for p in col]
    check(col and min(czs) < 0.05 and max(czs) > 3.9, f"centre drum from the floor to the top (z {min(czs) if czs else None:.2f}..{max(czs) if czs else None:.2f})")
    feet = insts(sp, lambda d: abs(d[0] - 0.144) < 0.01 and abs(d[2] - 0.012) < 0.005)
    in_spiral = [p for p in feet if (Vector((p.x, p.y, 0)) - Vector((10 - 1.05, 2.0, 0))).length < 1.05 + 0.6 and p.y > 2.05]
    check(not in_spiral, f"no floor stands around the spiral ({len(in_spiral)} found)")
    dg = ctx.evaluated_depsgraph_get(); geo = sp.evaluated_get(dg).evaluated_geometry(); me = geo.mesh; mw = sp.matrix_world
    arm_verts = [mw @ v.co for v in me.vertices if 0.5 < (Vector(((mw @ v.co).x, (mw @ v.co).y, 0)) - Vector((10 - 1.05, 2.0, 0))).length < 1.3 and 0.3 < (mw @ v.co).z < 3.7 and abs(((mw @ v.co).z - 0.0) % 0.5) > -1]
    check(len(arm_verts) > 100, f"cantilever arms between the drum and the track ({len(arm_verts)} verts)")
    ctx.scene.frame_set(1); a = items(sp); ctx.scene.frame_set(25); b = items(sp)
    check(len(a) > 5 and len(b) > 5, f"goods populate the spiral ({len(a)})")
    on_helix = [p.z for p, r in b if 0.2 < p.z < 3.8]
    check(len(on_helix) > 2, "goods ride the helix at intermediate heights")
    # ---- C. lifts on a belt line: Z and C
    lz = make((20, 0, 0), 0.0, [('STRAIGHT', 2000), ('MODULE', 'LIFT', 'Z', 5000.0), ('STRAIGHT', 2000)], "LiftZ", ctype='belt', populate=True)
    ex, ey, ez, eh = lz.conveyor_line.end_pose
    check(abs(ez - 5.0) < 1e-3 and abs(eh) < 1e-3, f"Z lift ends 5 m up, same heading (z {ez:.2f}, h {eh:.0f})")
    ctx.scene.frame_set(9)
    vert = [(p, r) for p, r in items(lz) if 1.0 < p.z < 4.0]
    check(vert and all(abs(r.x) < 0.02 and abs(r.y) < 0.02 for p, r in vert), f"goods stay level on the vertical part ({len(vert)} checked)")
    # 2.6: the fork-column lift stands on two 60 mm square columns (instances) taller than its rise
    cols = insts(lz, lambda d: abs(d[0] - 0.06) < 0.01 and abs(d[1] - 0.06) < 0.01 and d[2] > 5.0)
    check(len(cols) == 2 and all(abs(p.x - 20) < 1.0 for p in cols), f"lift columns from the floor past the top ({len(cols)} columns)")
    lc = make((30, 0, 0), 0.0, [('STRAIGHT', 2000), ('MODULE', 'LIFT', 'C', 4000.0), ('STRAIGHT', 2000)], "LiftC", ctype='belt', populate=True)
    ex, ey, ez, eh = lc.conveyor_line.end_pose
    check(abs(ez - 4.0) < 1e-3 and abs(abs(eh) - 180) < 1e-3 and abs(ey) < 1e-3, f"C lift ends 4 m up, back over the entry (y {ey:.2f}, h {eh:.0f})")
    # ---- D. the cleated belt is gone (2.26.1): a saved line of it opens as a belt
    from bl_ext.user_default.conveyor_system.config import loader
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj

    check("pocket" not in loader.get_conveyor_types(), "the cleated belt is not offered")
    pk = make((40, 0, 0), 0.0, [('STRAIGHT', 5000)], "Was cleated", ctype='belt', populate=True)
    pk.conveyor_line["conveyor_type"] = 5  # what a 2.26.0 file stored for "Cleated belt (steep)"
    build_line(ctx, pk)
    check(pk.conveyor_line.conveyor_type == 'belt' and pk.modifiers[MODIFIER_NAME].node_group.name.endswith("(Belt)"),
          f"a cleated-belt line becomes a belt when it is built ({pk.conveyor_line.conveyor_type!r})")
    pk.conveyor_line["conveyor_type"] = 5
    dj.run_sync(ctx.scene); ctx.view_layer.update()
    check(pk.conveyor_line.conveyor_type == 'belt', "and when a file with one is opened (the sync pass)")
    # the omni deck is hidden until its redesign (2.26.1): not offered, a saved one still builds
    check("omni" not in loader.get_offered_types() and "omni" in loader.get_offered_types("omni"),
          "the omni deck is not offered; a line saved with it still shows its type")
    om = make((50, 0, 0), 0.0, [('STRAIGHT', 3000)], "Saved omni", ctype='omni', populate=True)
    check(om.conveyor_line.conveyor_type == 'omni' and om.modifiers[MODIFIER_NAME].node_group.name.endswith("(Omni)"), "a saved omni line still builds")
    import os
    if os.environ.get("TMPDIR"):  # a look at the scene for a person: the scratch temp folder, never the project's scenes (rule §2.10)
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(os.environ["TMPDIR"], "V2.4 check.blend"))
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
