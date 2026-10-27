"""Build mode (2.26): the plain arrow keys build the active line -- a straight, a curve each way, the
piece library -- Backspace takes the end piece off, and only the user's click starts it: another
add-on's new_line (R6 location, R21 points; EXEC) returns as before with no build mode running, and so do
new_line_at_junction / new_line_from_end; each key is one undo step.
Plus the merge rule (decision 2026-10-26): at a capped 90 degree merge the main gives way, and its
panel says why. Blender -b --python tests/headless/test_build_mode.py"""
import json, traceback, bpy
from mathutils import Vector

PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
fails = []


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)


try:
    if PKG not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module=PKG)
    from bl_ext.user_default.conveyor_system.operators import build_mode
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
    from bl_ext.user_default.conveyor_system.operators import stream
    from bl_ext.user_default.conveyor_system.operators.new_line import create_line
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line
    from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild

    ctx, scene = bpy.context, bpy.context.scene

    # ---------------- A. other add-ons' calls never enter build mode (R6 / R21)
    r = bpy.ops.conveyor.new_line(kind="line", location=(0.0, 0.0, 0.8), heading_deg=0.0)
    check(r == {'FINISHED'} and build_mode.RUNNING["line"] == "", f"new_line(location=...) finishes, no build mode ({r})")
    r = bpy.ops.conveyor.new_line(points=json.dumps([[10.0, 0.0, 0.8], [10.0, 6.0, 0.8], [14.0, 6.0, 0.8]]), by="test")
    check(r == {'FINISHED'} and build_mode.RUNNING["line"] == "", f"new_line(points=...) finishes, no build mode ({r})")
    r = bpy.ops.conveyor.new_line()  # EXEC from a script, the cursor's pose
    check(r == {'FINISHED'} and build_mode.RUNNING["line"] == "", "new_line() from a script finishes, no build mode")

    # ---------------- B. the steps the keys take
    line = create_line(ctx, Vector((0.0, 20.0, 0.8)), 0.0)
    build_line(ctx, line)
    for o in ctx.view_layer.objects:
        o.select_set(False)
    line.select_set(True)
    ctx.view_layer.objects.active = line
    segs = line.conveyor_line.segments
    n0 = len(segs)
    line.conveyor_line.active_segment_index = 0  # a middle row selected: the keys still ADD at the end
    check(build_mode.do_action(ctx, line, "add:STRAIGHT") and len(segs) == n0 + 1 and segs[-1].kind == 'STRAIGHT',
          f"up adds a straight at the end ({len(segs)} pieces)")
    check(build_mode.do_action(ctx, line, "add:CURVE_LEFT") and segs[-1].kind == 'CURVE' and segs[-1].curve_direction == 'LEFT',
          "left adds a left curve")
    check(build_mode.do_action(ctx, line, "add:CURVE_RIGHT") and segs[-1].kind == 'CURVE' and segs[-1].curve_direction == 'RIGHT',
          "right adds a right curve")
    n = len(segs)
    check(build_mode.do_action(ctx, line, "remove") and len(segs) == n - 1 and segs[-1].curve_direction == 'LEFT',
          "Backspace takes the end piece off")
    while len(segs) > 1:
        build_mode.do_action(ctx, line, "remove")
    check(not build_mode.do_action(ctx, line, "remove") and len(segs) == 1, "a line keeps its last piece")
    line.conveyor_line.grow_at = 'START'
    build_mode.do_action(ctx, line, "add:STRAIGHT")
    check(len(segs) == 2 and not build_mode.do_action(ctx, line, "remove"), "growing at the start: added in front, Backspace leaves it")
    line.conveyor_line.grow_at = 'END'

    # ---------------- B2. Shift + arrows tune the piece just added, Ctrl / Cmd + up / down its height
    build_mode.do_action(ctx, line, "add:STRAIGHT")
    line.conveyor_line.active_segment_index = 0  # another row selected: the keys still tune the end piece
    before = segs[0].length_mm
    check(build_mode.do_action(ctx, line, "adjust:longer") and abs(segs[-1].length_mm - 3150.0) < 0.5 and segs[0].length_mm == before,
          f"Shift+up lengthens the piece just added by 150 mm ({segs[-1].length_mm:.0f})")
    build_mode.do_action(ctx, line, "adjust:shorter"); build_mode.do_action(ctx, line, "adjust:shorter")
    check(abs(segs[-1].length_mm - 2850.0) < 0.5, f"Shift+down shortens it ({segs[-1].length_mm:.0f})")
    z0 = line.conveyor_line.end_pose[2]
    check(build_mode.do_action(ctx, line, "adjust:up") and build_mode.do_action(ctx, line, "adjust:up")
          and abs(segs[-1].rise_mm - 200.0) < 0.5 and abs(line.conveyor_line.end_pose[2] - z0 - 0.2) < 0.01,
          f"Ctrl+up twice raises its end 200 mm (rise {segs[-1].rise_mm:.0f}, end +{(line.conveyor_line.end_pose[2] - z0) * 1000:.0f} mm)")
    check(not build_mode.do_action(ctx, line, "adjust:left") and segs[-1].kind == 'STRAIGHT', "Shift+left on a straight does nothing (it steers curves)")
    build_mode.do_action(ctx, line, "add:CURVE_LEFT")
    a0 = segs[-1].curve_angle_deg or 90
    check(build_mode.do_action(ctx, line, "adjust:left") and segs[-1].curve_angle_deg == a0 + 15 and segs[-1].curve_direction == 'LEFT',
          f"Shift+left turns the curve further left ({segs[-1].curve_angle_deg} deg)")
    for _ in range(7):
        build_mode.do_action(ctx, line, "adjust:right")
    check(segs[-1].curve_direction == 'RIGHT' and segs[-1].curve_angle_deg == 15, f"steered through straight it turns right ({segs[-1].curve_direction} {segs[-1].curve_angle_deg})")
    r0 = segs[-1].curve_radius
    check(build_mode.do_action(ctx, line, "adjust:longer") and segs[-1].curve_radius != r0, f"Shift+up widens a curve's radius ({r0} -> {segs[-1].curve_radius})")
    check(len(segs) == 4 and segs[-1].kind == 'CURVE', "and no key added or removed a piece")

    # ---------------- C. the merge rule: the main gives way at a capped 90 degree merge, and says why
    def settle(n=4):
        for _ in range(n):
            ctx.view_layer.update(); dj.run_sync(scene)
        ctx.view_layer.update()

    def merge_pair(y, main_pct, feed_pct):
        main = create_line(ctx, Vector((0.0, y, 0.8)), 0.0)
        with suspended_rebuild():
            s = main.conveyor_line
            s.segments[0]["length_mm"] = 3000.0
            m = s.segments.add(); m.kind = 'MODULE'; m.module_kind = 'MERGE'; m.merge_angle = '90'
            t = s.segments.add(); t.kind = 'STRAIGHT'; t["length_mm"] = 3000.0
            s.populate = True; s.speed_m_s = 0.5; s.population_pct = main_pct
        build_line(ctx, main); settle()
        bpy.ops.conveyor.new_line_at_junction(line_name=main.name, index=1, side='LEFT')
        feed = ctx.view_layer.objects.active
        feed.conveyor_line.populate = True; feed.conveyor_line.population_pct = feed_pct; settle()
        tree = stream.tree_for(ctx, main)
        return main, (tree.flow.population.get(main.name) if tree is not None and tree.flow is not None else None)

    main, eff = merge_pair(40.0, 55.0, 55.0)
    check(build_mode.RUNNING["line"] == "", "new_line_at_junction from a script: no build mode")
    r = bpy.ops.conveyor.new_line_from_end()
    check(r == {'FINISHED'} and build_mode.RUNNING["line"] == "", "new_line_from_end from a script: no build mode")
    check(eff is not None and eff < 0.005, f"55 % + 55 % at a 90 degree merge: the main gives way to 0 % ({eff})")
    _main2, eff2 = merge_pair(60.0, 60.0, 15.0)
    check(eff2 is not None and abs(eff2 - 0.307) < 0.01, f"60 % + 15 %: the main runs at the cap less the feeder, 31 % ({eff2})")
    ms = main.conveyor_line
    check(any(s.kind == 'MODULE' and s.module_kind == 'MERGE' and (s.merge_source or s.merge_source_right) for s in ms.segments),
          "the merge names its feeder: the panel says 'capped by the merge'")
    check(len("Runs at 100 % (capped by the merge)") <= 36, "the note fits the panel (36 characters)")
except Exception:
    traceback.print_exc()
    fails.append("raised")
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
