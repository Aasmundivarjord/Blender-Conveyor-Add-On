"""Round 6 wave 4 (interop contract v2.1, R13 obstacle alerts): a line whose
goods envelope crosses a wh_obstacles entry in plan and in height is flagged;
walls, a door's gap and its lintel, a moved building. Uses a real Floorplan
0.2.0 building when that add-on can be enabled (the sandbox symlinks it; the
real install has it), else a synthetic obstacle host.
Blender -b --python tests/headless/test_round6_w4.py"""
import json, math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
FLOORPLAN = "bl_ext.user_default.warehouse_floorplan"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
try:
    if FLOORPLAN not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module=FLOORPLAN)
    from bl_ext.user_default.warehouse_floorplan import building as FB, sync as FS, standards as FSt
    floorplan = True
except Exception as e:
    print("SKIP: the real-building R13 cases: Floorplan not available here (a synthetic obstacle host stands in):", e); floorplan = False
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.operators.build_line import build_line
from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj, obstacles
from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
ctx = bpy.context; scene = ctx.scene; fails = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
def make(loc, heading, length_mm, name, populate=False):
    o = create_line(ctx, Vector((100.0, 100.0, 0.0)), heading); o.name = name; o.location = Vector(loc)
    with suspended_rebuild():
        o.conveyor_line.segments[0]["length_mm"] = float(length_mm); o.conveyor_line.populate = populate
    ctx.view_layer.update(); build_line(ctx, o); ctx.view_layer.update()
    return o
def hits(o): return obstacles.hits_of(o)
try:
    print("note: Floorplan", "ENABLED (real building)" if floorplan else "absent (synthetic host)")
    if floorplan:
        hall = FB.quick_building(ctx, 20.0, 12.0, "EU", (0.0, 0.0, 0.0), "Hall"); ctx.view_layer.update()
        FS.sync_building(hall, force=True); ctx.view_layer.update()
    else:
        hall = bpy.data.objects.new("Hall", None); scene.collection.objects.link(hall)
        hall["wh_system"] = json.dumps({"version": 2, "addon": "warehouse_floorplan", "kind": "building", "id": "hall-1", "object": "Hall", "label": "Hall", "level": 0,
                                        "footprint": [[0, 0], [20, 0], [20, 12], [0, 12]], "height_m": 12.0, "clearance_m": 0.0, "zone": None, "container": True})
        hall["wh_obstacles"] = json.dumps([{"version": 2, "kind": "wall", "id": "wall0.0", "polygon": [[0, 0], [20, 0], [19.75, 0.25], [0.25, 0.25]], "z0": 0.0, "z1": 12.0, "level": 0, "label": "Exterior"},
                                           {"version": 2, "kind": "wall", "id": "wall2.0", "polygon": [[0, 11.75], [20, 11.75], [20, 12], [0, 12]], "z0": 0.0, "z1": 12.0, "level": 0, "label": "Exterior"}])
        ctx.view_layer.update()
    obs = obstacles.scene_obstacles(scene)
    check(len(obs) >= 2 and all("polygon" in o and "host" in o for o in obs), f"the building publishes {len(obs)} obstacle pieces (walls)")
    # ---- A. a line crossing the south wall is flagged; a line inside, or running along the wall, is not
    crossing = make((10.0, -3.0, 0.8), 0.0, 6000, "Through the wall")
    inside = make((5.0, 3.0, 0.8), 0.0, 5000, "Inside")
    along = make((2.0, 1.0, 0.8), math.radians(-90), 8000, "Along the wall")  # heading -90 = +X, 0.75 m in from the wall face
    h = hits(crossing)
    check(len(h) == 1 and h[0]["label"] == "Exterior" and h[0]["host"] == "Hall", f"a line through the wall is flagged: {h}")
    check(not hits(inside), "a line inside the hall is not flagged")
    check(not hits(along), f"a line running along the wall is not flagged {hits(along)}")
    text = obstacles.describe(h[0]) if h else ""
    check(text.startswith("Goods cross Exterior") and "of Hall" in text, f"panel text: {text}")
    checks = obstacles.scene_checks(ctx)
    check(len(checks) == 1 and checks[0][0] == crossing, "the scene's Checks list the one crossing line")
    # ---- B. a door: the gap lets goods through, its lintel still stops tall goods
    if floorplan:
        kinds = list(FSt.OPENING_TYPES)
        kind = next((k for k in ("SECTIONAL", "DOOR", "GATE") if k in kinds), kinds[0])
        door = FB.create_opening(ctx, hall, kind, Vector((10.0, 0.0, 0.0)), 0.0); ctx.view_layer.update()
        FS.sync_building(hall, force=True); ctx.view_layer.update()
        spec = FSt.opening_spec("EU", kind)
        print("door kind", kind, "width", spec.width, "height", spec.height)
        dj.run_sync(scene); ctx.view_layer.update()
        check(not hits(crossing), f"through the door at 0.8 m with 1 m of goods: no obstacle {hits(crossing)}")
        high = make((10.0, -3.0, spec.height + 0.3), 0.0, 6000, "Over the door")
        hh = hits(high)
        check(len(hh) == 1 and hh[0]["z0"] >= spec.height - 0.01, f"a line above the door hits its lintel (z0 {hh[0]['z0'] if hh else None}, door {spec.height} m)")
        low = make((10.0, -3.0, spec.height - 1.5), 0.0, 6000, "Just under the lintel")  # surface 1.5 m under the lintel, 1 m of goods: clears it
        check(not hits(low), f"goods that stay under the lintel pass {hits(low)}")
    # ---- C. the building moves: the sync pass recomputes every line's hits (a line away from the door)
    wall2 = make((4.0, -3.0, 0.8), 0.0, 6000, "Through the wall 2")
    check(len(hits(wall2)) == 1, "a second line through the wall (away from the door) is flagged")
    hall.location.x += 40.0; ctx.view_layer.update()
    n = dj.run_sync(scene); ctx.view_layer.update()
    check(not hits(wall2) and n > 0, f"the hall moved away: the pass cleared the alert ({n} writes)")
    hall.location.x -= 40.0; ctx.view_layer.update(); dj.run_sync(scene)
    check(len(hits(wall2)) == 1, "the hall is back: the alert is back")
    # ---- D. the line moves instead
    wall2.location.y += 4.0; ctx.view_layer.update(); dj.run_sync(scene)  # now from y 1 to 7: inside
    check(not hits(wall2), f"the line moved inside: no alert {hits(wall2)}")
    wall2.location.y -= 4.0; ctx.view_layer.update(); dj.run_sync(scene)
    check(len(hits(wall2)) == 1, "moved back: flagged again")
    # ---- E. the envelope follows the load height
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(50.0, 0.0, 0.5)); tall = ctx.view_layer.objects.active; tall.name = "Tall load"; tall.scale = (0.8, 1.2, 2.5); ctx.view_layer.update()
    loaded = make((15.0, -3.0, 0.8), 0.0, 6000, "Under a 2.5 m load")  # alone: no other line meets its ends
    with suspended_rebuild():
        loaded.conveyor_line.populate = True; loaded.conveyor_line.populate_item = tall
    build_line(ctx, loaded); ctx.view_layer.update()
    check(abs(obstacles.envelope_m(ctx, loaded) - 2.5) < 0.01, f"the envelope is the load's height ({obstacles.envelope_m(ctx, loaded):.2f} m)")
    check(abs(obstacles.envelope_m(ctx, inside) - 1.0) < 1e-6, f"1 m without a load ({obstacles.envelope_m(ctx, inside):.2f} m)")
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
