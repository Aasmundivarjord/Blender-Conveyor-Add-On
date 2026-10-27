"""Round 6 wave 5 (interop contract v2.1, R9 + D4): the frame and the rollers
are the shared WH palette materials, one datablock with Racks and Shuttle.
Lookup: the wh_material stamp > our legacy name (stamped, renamed while
unchanged, values kept) > created from the palette; a stamped material is
never cleared. Blender -b --python tests/headless/test_round6_w5.py"""
import bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line
from bl_ext.user_default.conveyor_system.geonodes import materials
from bl_ext.user_default.conveyor_system._wh import palette
ctx = bpy.context; fails = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
def fresh_file():
    bpy.ops.wm.read_homefile(use_empty=True)
    for m in list(bpy.data.materials): bpy.data.materials.remove(m)
def line(name):
    o = create_line(ctx, Vector((0, 0, 0)), 0.0); o.name = name; ctx.view_layer.update(); return o
def slots(o): return [m.name if m else None for m in o.data.materials[:5]]
def bsdf(mat): return next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
def names(prefix=""): return sorted(m.name for m in bpy.data.materials if m.name.startswith(prefix))
try:
    # ---- A. a fresh scene: the two shared materials come from the palette, the rest keep the Conveyor prefix
    fresh_file(); a = line("Fresh")
    frame, rollers = a.data.materials[0], a.data.materials[1]
    check(frame.name == "WH Conveyor Frame" and frame.get("wh_material") == "conveyor_frame", f"the frame is the shared WH Conveyor Frame ({frame.name})")
    check(rollers.name == "WH Conveyor Rollers" and rollers.get("wh_material") == "conveyor_rollers", f"the rollers are WH Conveyor Rollers ({rollers.name})")
    spec = palette.PALETTE["conveyor_frame"]; b = bsdf(frame)
    check(b is not None and all(abs(b.inputs["Base Color"].default_value[i] - spec["base_color"][i]) < 1e-6 for i in range(3))
          and abs(b.inputs["Roughness"].default_value - spec["roughness"]) < 1e-6 and abs(b.inputs["Metallic"].default_value - spec["metallic"]) < 1e-6,
          "created from the palette values (the same look as before)")
    check(all(n.startswith("Conveyor - ") for n in slots(a)[2:]), f"the other slots keep the Conveyor prefix {slots(a)}")
    check(not names("Conveyor - Steel") and not names("Conveyor - Roller") and len(names("WH Conveyor")) == 2, f"no stray legacy copies: {names('WH')} {names('Conveyor - S')} {names('Conveyor - R')}")
    # ---- B. Racks made WH Conveyor Frame first: the line reuses that datablock without touching its nodes
    fresh_file()
    racks_mat = bpy.data.materials.new("WH Conveyor Frame"); racks_mat.use_nodes = True
    racks_mat["wh_material"] = "conveyor_frame"; racks_mat["wr_material_key"] = "conveyor"
    marker = racks_mat.node_tree.nodes.new('ShaderNodeRGB'); marker.name = "RacksMarker"; racks_mat.diffuse_color = (1.0, 0.0, 0.0, 1.0)
    n_nodes = len(racks_mat.node_tree.nodes)
    b_line = line("After Racks")
    check(b_line.data.materials[0] is racks_mat or b_line.data.materials[0].as_pointer() == racks_mat.as_pointer(), "the line's frame IS Racks' datablock")
    check("RacksMarker" in racks_mat.node_tree.nodes and len(racks_mat.node_tree.nodes) == n_nodes and tuple(racks_mat.diffuse_color[:3]) == (1.0, 0.0, 0.0), "its nodes and viewport colour were not touched")
    check(len(names("WH Conveyor Frame")) == 1, f"no duplicate frame material {names('WH Conveyor Frame')}")
    build_line(ctx, b_line); ctx.view_layer.update()
    check(b_line.data.materials[0].as_pointer() == racks_mat.as_pointer() and "RacksMarker" in racks_mat.node_tree.nodes, "a rebuild keeps using it, nodes intact")
    # ---- C. a legacy 2.10 file: our old material is stamped and renamed, its edited values kept
    fresh_file()
    old = bpy.data.materials.new("Conveyor - Steel (Galvanized)"); old.use_nodes = True; old.node_tree.nodes.clear()
    materials._principled(old, (0.1, 0.2, 0.9), roughness=0.5, metallic=0.2); old["conveyor_material_version"] = materials.MATERIAL_VERSION  # the user made it blue
    ptr = old.as_pointer()
    c_line = line("Legacy file")
    frame = c_line.data.materials[0]
    check(frame.as_pointer() == ptr and frame.name == "WH Conveyor Frame" and frame.get("wh_material") == "conveyor_frame", f"the legacy material is stamped and renamed ({frame.name})")
    bb = bsdf(frame)
    check(bb is not None and abs(bb.inputs["Base Color"].default_value[2] - 0.9) < 1e-6 and abs(bb.inputs["Roughness"].default_value - 0.5) < 1e-6, "its edited values are kept (still blue)")
    check(bpy.data.materials.get("Conveyor - Steel (Galvanized)") is None, "the legacy name is gone")
    # ---- D. the user renamed the shared material: found by its stamp, name kept
    frame.name = "My Steel"
    d_line = line("Renamed by the user")
    check(d_line.data.materials[0].as_pointer() == ptr and frame.name == "My Steel" and len(names("WH Conveyor Frame")) == 0, f"a renamed stamped material is still the one used, name kept ({frame.name})")
    # ---- E. a legacy name that is NOT ours and unstamped (another add-on's old material): stamped, not cleared
    fresh_file()
    foreign = bpy.data.materials.new("Conveyor - Roller (Zinc)"); foreign.use_nodes = True
    mk = foreign.node_tree.nodes.new('ShaderNodeRGB'); mk.name = "Keep"
    e_line = line("Foreign legacy")
    r = e_line.data.materials[1]
    check(r.as_pointer() == foreign.as_pointer() and r.get("wh_material") == "conveyor_rollers" and "Keep" in r.node_tree.nodes and r.name == "WH Conveyor Rollers", "an unstamped legacy-named material is adopted and stamped, never cleared")
    # ---- F. the version guard never clears a WH material that only shares a name with one of ours
    fresh_file()
    shared_plastic = bpy.data.materials.new("Conveyor - Plastic (Neutral)"); shared_plastic.use_nodes = True
    shared_plastic["wh_material"] = "tote_plastic"; mk2 = shared_plastic.node_tree.nodes.new('ShaderNodeRGB'); mk2.name = "Keep2"
    f_line = line("Guard")
    check("Keep2" in shared_plastic.node_tree.nodes, "a wh_material stamp means shared: the node tree is left alone")
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
