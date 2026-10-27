"""2.16.0 (round 7, R21): bpy.ops.conveyor.new_line(kind="line", preset, points="<JSON [[x, y, z], ...]>", by)
lays a line along points -- exactly from the first to the last, standard curves at the corners,
inclines where the height changes -- leaves it active with its wh_system id readable, records the
caller, and refuses a path it cannot follow with nothing left behind.
Blender -b --python tests/headless/test_new_line_points.py"""
import json, math, bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.props.line_settings import EXACT_ANGLE_KEY, segment_curve_angle_deg
from bl_ext.user_default.conveyor_system.model.public_api import LAYOUT_KEY
from bl_ext.user_default.conveyor_system.operators import ports
ctx = bpy.context; scene = ctx.scene; fails = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
def new_line(points, preset="belt", by="warehouse_floorplan", **kw):
    before = set(scene.objects)
    r = bpy.ops.conveyor.new_line(kind="line", preset=preset, points=points if isinstance(points, str) else json.dumps(points), by=by, **kw)
    ctx.view_layer.update()
    added = [o for o in scene.objects if o not in before]
    return r, added
def world_end(obj):
    ex, ey, ez, _h = obj.conveyor_line.end_pose
    return obj.matrix_world @ Vector((ex, ey, ez))
def miss(obj, point):
    return (world_end(obj) - Vector(point)).length
try:
    # ---- A. two points: one straight, active, id readable, caller recorded
    pts = [[2.0, 3.0, 0.8], [2.0, 15.0, 0.8]]
    r, added = new_line(pts, preset="gravity_roller")
    a = added[0] if len(added) == 1 else None
    check(r == {'FINISHED'} and a is not None and ctx.view_layer.objects.active == a and a.select_get(), "FINISHED, one new line, active and selected")
    check(a is not None and json.loads(a["wh_system"]).get("id"), "its wh_system id is readable at once")
    check(a is not None and (a.location - Vector(pts[0])).length < 1e-6 and miss(a, pts[-1]) < 0.001, f"from the first point to the last ({miss(a, pts[-1]) * 1000:.2f} mm)")
    rec = json.loads(a[LAYOUT_KEY]) if a is not None else {}
    check(rec.get("by") == "warehouse_floorplan" and rec.get("points") == 2, f"the caller is recorded ({rec})")
    # ---- B. corners: a fractional one and a right angle, on a belt at 0.8 m
    t = math.radians(37.4)
    p2 = [0.0, 10.0, 0.8]; p3 = [p2[0] + 9.0 * math.sin(t), p2[1] + 9.0 * math.cos(t), 0.8]
    h = math.radians(37.4); p4 = [p3[0] + 8.0 * math.cos(h), p3[1] - 8.0 * math.sin(h), 0.8]  # then 90 deg right
    route = [[0.0, 0.0, 0.8], p2, p3, p4]
    r, added = new_line(route, preset="belt")
    b = added[0] if added else None
    curves = [s for s in b.conveyor_line.segments if s.kind == 'CURVE'] if b else []
    angles = sorted(round(segment_curve_angle_deg(s), 3) for s in curves)
    check(r == {'FINISHED'} and angles == [37.4, 90.0] and EXACT_ANGLE_KEY in curves[0], f"curves at the corners keep their angles ({angles})")
    check(b is not None and miss(b, route[-1]) < 0.001, f"ends on the last point ({miss(b, route[-1]) * 1000:.2f} mm)")
    # ---- C. a climb on a belt: incline between the curves, corner heights met
    climb = [[0.0, -20.0, 0.8], [0.0, -10.0, 0.8], [0.0, -2.0, 2.0], [8.0, -2.0, 2.0]]
    r, added = new_line(climb, preset="belt")
    c = added[0] if added else None
    rises = [s.rise_mm for s in c.conveyor_line.segments if s.kind == 'STRAIGHT'] if c else []
    check(r == {'FINISHED'} and c is not None and miss(c, climb[-1]) < 0.001 and any(v > 100 for v in rises),
          f"a climb: inclines where the height changes, ends on the last point ({miss(c, climb[-1]) * 1000:.2f} mm)")
    # ---- D. location / heading are ignored with points
    r, added = new_line([[30.0, 0.0, 0.0], [40.0, 0.0, 0.0]], preset="belt", location=(-50.0, -50.0, 0.0), heading_deg=90.0)
    d = added[0] if added else None
    check(d is not None and (d.location - Vector((30.0, 0.0, 0.0))).length < 1e-6 and miss(d, (40.0, 0.0, 0.0)) < 0.001, "location and heading_deg are ignored")
    # ---- E. refusals leave nothing behind
    for label, bad, preset in (("one point", [[0, 0, 0]], "belt"), ("straight up", [[0, 0, 0], [0, 0, 3]], "belt"),
                               ("a gravity roller climbing", [[0, 0, 0], [0, 10, 1]], "gravity_roller"),
                               ("steeper than the belt's limit", [[0, 0, 0], [0, 6, 3]], "belt"),
                               ("a leg too short for its curves", [[0, 0, 0], [0, 5, 0], [1.2, 5, 0], [1.2, 10, 0]], "belt"),
                               ("not JSON", "[[0, 0, 0], [0, 5", "belt")):
        r, added = new_line(bad, preset=preset)
        check(r == {'CANCELLED'} and not added, f"refused, nothing created: {label}")
    # ---- F. an edit of a laid-out curve's angle drops its exact angle
    s = curves[0]
    s.curve_angle_deg = 40; ctx.view_layer.update()
    check(EXACT_ANGLE_KEY not in s and segment_curve_angle_deg(s) == 40, "editing the angle by hand drops the exact angle")
    # ---- G. a guaranteed dock afterwards goes through dock_line (R6)
    rack = bpy.data.objects.new("Rack", None); scene.collection.objects.link(rack); rack.location = (60.0, 12.0, 0.8)
    rack["wh_system"] = json.dumps({"version": 2, "addon": "warehouse_racks", "kind": "crane_rack", "id": "rack-r21", "object": "Rack", "label": "Rack",
                                    "level": 0, "footprint": [[-1, -1], [1, -1], [1, 1], [-1, 1]], "height_m": 6.0, "clearance_m": 0.0, "zone": None})
    rack["wh_ports"] = json.dumps([{"version": 2, "id": "in0", "role": "in", "kind": "point", "position": [0, 0, 0], "heading_deg": 0.0,
                                    "width_m": 0.8, "rate_ph": 30.0, "capacity_ph": 30.0, "load": None}])
    ctx.view_layer.update()
    r, added = new_line([[60.0, 0.0, 0.8], [60.0, 12.0, 0.8]], preset="belt")
    g = added[0]
    r2 = bpy.ops.conveyor.dock_line(line_id=json.loads(g["wh_system"])["id"], system_id="rack-r21", port_id="in0", anchor="end", by="warehouse_floorplan")
    check(r2 == {'FINISHED'} and ports.dock_at(g, "end") is not None, f"dock_line docks the new line's end on a port ({r2})")
except Exception:
    traceback.print_exc(); fails.append("exception")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
