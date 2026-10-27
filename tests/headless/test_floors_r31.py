"""2.17.0 (contract R3.1, 2026-10-14): wh_floor true = always a floor, together
with the automatic candidates; false = never a floor; unmarked = the automatic
rule; Scene > Floors > Marked only (default off) = only the marked floors; the
user's Floors collection overrides everything. Mark as floor: Floor / Not a
floor / Auto, on the user's own meshes only.
Blender -b --python tests/headless/test_floors_r31.py"""
import json, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, floors
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
ctx = bpy.context; scene = ctx.scene; fails = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
def line_at(name, x, z):
    o = create_line(ctx, Vector((x, 0.0, z)), 0.0); o.name = name
    with suspended_rebuild():
        o.conveyor_line.segments[0]["length_mm"] = 6000.0
    build_line(ctx, o)
    return o
def feet(obj, x):
    dg = ctx.evaluated_depsgraph_get(); out = []
    for i in dg.object_instances:
        if i.is_instance and i.parent and i.parent.original == obj:
            d = i.object.dimensions
            if abs(d[0] - 0.144) < 0.01 and abs(d[2] - 0.012) < 0.005:
                p = i.matrix_world.translation
                if 1.0 < p.y < 5.0 and abs(p.x - x) < 0.5:
                    out.append(round(p.z, 2))
    return sorted(out)
def on(zs, z):
    return bool(zs) and all(abs(v - (z + 0.006)) < 0.04 for v in zs)
def plane(name, loc, size=4.0):
    bpy.ops.mesh.primitive_plane_add(size=size, location=loc)
    o = ctx.view_layer.objects.active; o.name = name
    return o
def select_only(obj):
    for o in ctx.view_layer.objects: o.select_set(False)
    obj.select_set(True); ctx.view_layer.objects.active = obj
def settle():
    for _ in range(2):
        ctx.view_layer.update(); dj.run_sync(scene)
    ctx.view_layer.update()
def auto():
    return {o.name for o in bpy.data.collections["Conveyor Floors (auto)"].objects}
try:
    a = line_at("Over the slab", 0.0, 4.0)
    b = line_at("Over the plain floor", 10.0, 4.0)
    slab = plane("Building Floor", (0.0, 3.0, 1.0)); slab["wh_floor"] = True  # as Floorplan marks its slab
    plain = plane("Plain floor", (10.0, 3.0, 1.5))
    settle()
    # 1. a Floorplan slab (true) and a user's plain floor: both
    check({"Building Floor", "Plain floor"} <= auto() and on(feet(a, 0.0), 1.0) and on(feet(b, 10.0), 1.5),
          f"a marked slab and an unmarked plain floor are both floors ({feet(a, 0.0)}, {feet(b, 10.0)})")
    # 2. a helper deck (true), a hidden child of a rack like Racks' walkways, and a plain floor: both
    c = line_at("Over the walkway", 20.0, 6.0)
    rack = bpy.data.objects.new("Rack", None); scene.collection.objects.link(rack); rack.location = (20.0, 3.0, 0.0)
    rack["wh_system"] = json.dumps({"version": 2, "addon": "warehouse_racks", "kind": "crane_rack", "id": "rack-r31"})
    deck = plane("Rack Walkways", (20.0, 3.0, 2.5)); deck["wh_floor"] = True
    deck.parent = rack; deck.matrix_parent_inverse = rack.matrix_world.inverted()
    under = plane("Floor under the rack", (20.0, 3.0, 0.5))
    settle()
    check({"Rack Walkways", "Floor under the rack"} <= auto() and on(feet(c, 20.0), 2.5), f"a walkway deck (true) and the plain floor: both ({feet(c, 20.0)})")
    deck.hide_set(True); settle()
    check(on(feet(c, 20.0), 2.5), f"the deck hidden in the viewport (eye) still carries the legs ({feet(c, 20.0)})")
    deck.hide_set(False); deck.hide_viewport = True; settle()
    print(f"note: the deck disabled in viewports (monitor icon): legs at {feet(c, 20.0)} (2.5 = it still carries them)")
    deck.hide_viewport = False; settle()
    # 3. a table with false: never a floor
    table = plane("Table", (10.0, 3.0, 3.0)); settle()
    check(on(feet(b, 10.0), 3.0), f"an unmarked table catches the legs (the automatic rule) {feet(b, 10.0)}")
    table["wh_floor"] = False; settle()
    check("Table" not in auto() and on(feet(b, 10.0), 1.5), f"a table with wh_floor false is never a floor {feet(b, 10.0)}")
    # 4. Marked only: only the marked floors
    scene.conveyor_settings.floors_marked_only = True; settle()
    check(auto() == {"Building Floor", "Rack Walkways"} and on(feet(a, 0.0), 1.0) and on(feet(b, 10.0), 0.0),
          f"Marked only: the slab and the walkway alone; the plain floor no longer ({sorted(auto())}, {feet(b, 10.0)})")
    scene.conveyor_settings.floors_marked_only = False; settle()
    check({"Plain floor", "Floor under the rack"} <= auto(), "Marked only off: the plain floors are back")
    # 5. the user's Floors collection wins over everything
    mine = bpy.data.collections.new("My floors"); scene.collection.children.link(mine); mine.objects.link(plain)
    scene.conveyor_settings.floor_collection = mine; settle()
    check(on(feet(a, 0.0), 0.0) and on(feet(b, 10.0), 1.5), f"the Floors collection wins: the slab is not in it ({feet(a, 0.0)})")
    scene.conveyor_settings.floor_collection = None; settle()
    # 6. Floor / Not a floor / Auto, on the user's own meshes only
    select_only(plain); r1 = bpy.ops.conveyor.mark_floor(mark='NOT_FLOOR'); settle()
    check(r1 == {'FINISHED'} and floors.floor_mark(plain) is False and floors.marked_by_us(plain) and on(feet(b, 10.0), 0.0),
          f"Not a floor on the user's plain floor: the legs go to the floor level {feet(b, 10.0)}")
    select_only(plain); r2 = bpy.ops.conveyor.mark_floor(mark='FLOOR'); settle()
    check(r2 == {'FINISHED'} and floors.floor_mark(plain) is True and on(feet(b, 10.0), 1.5), "Floor")
    select_only(plain); r3 = bpy.ops.conveyor.mark_floor(mark='AUTO'); settle()
    check(r3 == {'FINISHED'} and "wh_floor" not in plain and "conveyor_floor_mark" not in plain and on(feet(b, 10.0), 1.5), "Auto: the marker is gone")
    select_only(slab); r4 = bpy.ops.conveyor.mark_floor(mark='NOT_FLOOR')
    check(r4 == {'CANCELLED'} and floors.floor_mark(slab) is True, "another add-on's mark is never changed here")
    rack_mesh = plane("Rack mesh", (30.0, 3.0, 1.0)); rack_mesh["wh_system"] = json.dumps({"version": 2, "addon": "warehouse_racks", "id": "r2"})
    select_only(rack_mesh); r5 = bpy.ops.conveyor.mark_floor(mark='FLOOR')
    check(r5 == {'CANCELLED'} and "wh_floor" not in rack_mesh, "another add-on's object is never marked here")
    settle()
    check(dj.run_sync(scene) == 0, "a settled scene: the pass writes nothing (R5)")
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
