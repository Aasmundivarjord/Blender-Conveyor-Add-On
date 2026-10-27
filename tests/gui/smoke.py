"""GUI smoke test (2.25, public release): builds a line of every kind through
the user-facing operators, makes every line and every piece active in turn
and redraws the whole window -- side panel, gizmos, dimensions, flow markers
-- in Solid and Material Preview with the goods moving, then opens the
popups. Any Python error in a draw callback or an operator lands on stderr:
run it with stderr captured and grep for "Traceback". Never with the user's
own config (same guard as tests/gui/screenshots.py):
  TMPDIR=<cfg>/tmp BLENDER_USER_EXTENSIONS=<ext> BLENDER_USER_CONFIG=<cfg> Blender --factory-startup \
    --enable-event-simulate -p 0 0 1728 1052 --python tests/gui/smoke.py -- <out dir> > smoke.log 2>&1
--enable-event-simulate lets the build-mode step press the arrow keys (and keeps the real mouse and
keyboard out of the window); without it that step is listed as a SKIP.
"""
import math, os, sys, traceback
import bpy
from mathutils import Vector

PKG = "bl_ext.user_default.conveyor_system"
_CONFIG = os.environ.get("BLENDER_USER_CONFIG", "")
if not _CONFIG or not os.path.isdir(_CONFIG) or "Application Support/Blender" in _CONFIG:
    print("SMOKE refused: run with a scratch BLENDER_USER_CONFIG (never the user's own)")
    os._exit(2)
SCRATCH_TMP = os.path.join(_CONFIG, "tmp")
os.makedirs(SCRATCH_TMP, exist_ok=True)
bpy.context.preferences.filepaths.temporary_directory = SCRATCH_TMP
bpy.context.preferences.use_preferences_save = False
bpy.context.preferences.view.show_splash = False
OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else os.getcwd()
STATE = {"errors": [], "redraws": 0}


def log(*a):
    print("SMOKE", " ".join(str(x) for x in a))
    sys.stdout.flush()


def view3d():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == 'VIEW_3D':
            regions = {r.type: r for r in area.regions}
            return win, area, regions.get('WINDOW'), regions.get('UI')
    return win, None, None, None


def redraw(n=1):
    win, area, region, ui = view3d()
    if ui is not None:
        try:
            ui.active_panel_category = "Conveyor"
        except Exception as e:  # the tab exists once the add-on's panels have drawn once
            STATE.setdefault("tab", repr(e))
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=n)
    STATE["redraws"] += n


def op(name, *args, **kw):
    """Calls conveyor.<name> in the 3D view's context; returns its result (or the error)."""
    win, area, region, _ui = view3d()
    fn = getattr(bpy.ops.conveyor, name)
    try:
        with bpy.context.temp_override(window=win, area=area, region=region):
            return fn(*args, **kw)
    except Exception as e:
        STATE["errors"].append(f"conveyor.{name}: {e}")
        log("ERROR", f"conveyor.{name}", repr(e))
        return {'ERROR'}


def activate(obj):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def populate(obj):
    """Populate on as an ID write (the checkbox opens the eyedropper; a script has nobody to click)."""
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line

    obj.conveyor_line["populate"] = True
    build_line(bpy.context, obj)


STEPS = []


def step(fn):
    STEPS.append(fn)
    return fn


@step
def s_enable():
    if PKG not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module=PKG)
    win, area, region, ui = view3d()
    space = area.spaces.active
    space.show_region_ui = True
    space.shading.type = 'SOLID'
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    log("Blender", bpy.app.version_string)


@step
def s_main_line():
    """A roller line grown with the piece keys: straights, curves, a diverter, a buffer."""
    bpy.context.scene.cursor.location = (0.0, 0.0, 0.8)
    op("new_line")
    main = bpy.context.view_layer.objects.active
    main.name = "Main"
    for kind in ('STRAIGHT', 'CURVE_RIGHT', 'STRAIGHT', 'STRAIGHT'):
        op("segment_add", kind=kind)
    op("segment_add", kind='MODULE', module='DIVERTER')
    op("segment_add", kind='STRAIGHT')
    op("segment_add", kind='MODULE', module='BUFFER')
    op("segment_add", kind='STRAIGHT')
    op("segment_add", kind='CURVE_LEFT')
    op("segment_add", kind='STRAIGHT')
    populate(main)
    STATE["main"] = main
    log("main pieces:", [s.kind if s.kind != 'MODULE' else s.module_kind for s in main.conveyor_line.segments])
    redraw(2)


@step
def s_branch_and_end():
    main = STATE["main"]
    idx = next(i for i, s in enumerate(main.conveyor_line.segments) if s.kind == 'MODULE' and s.module_kind == 'DIVERTER')
    r = op("new_line_at_junction", line_name=main.name, index=idx, side='LEFT')
    branch = bpy.context.view_layer.objects.active
    branch.name = "Branch"
    op("segment_add", kind='STRAIGHT')
    op("segment_add", kind='CURVE_LEFT')
    log("branch at the diverter:", r, branch.name)
    activate(main)
    r = op("new_line_from_end")
    takeaway = bpy.context.view_layer.objects.active
    takeaway.name = "Takeaway"
    log("new line from end:", r)
    STATE["lines"] = [main, branch, takeaway]
    redraw(2)


@step
def s_other_kinds():
    """A belt line climbing a spiral, a lift, a RAT and an ARB, a pouch sorter hung from the ceiling, an omni deck."""
    sc = bpy.context.scene
    made = []
    for name, ctype, loc, pieces in (
        ("Spiral line", "belt", (0.0, -8.0, 0.8), [('STRAIGHT', ''), ('SPIRAL', ''), ('STRAIGHT', '')]),
        ("Lift line", "gravity_roller", (10.0, -8.0, 0.8), [('STRAIGHT', ''), ('MODULE', 'LIFT'), ('STRAIGHT', '')]),
        ("Transfer line", "gravity_roller", (20.0, -8.0, 0.8), [('MODULE', 'RAT'), ('STRAIGHT', ''), ('MODULE', 'ARB'), ('STRAIGHT', ''), ('MODULE', 'WRAPPER')]),
        ("Pouch line", "pouch_sorter", (0.0, -16.0, 3.0), [('STRAIGHT', ''), ('CURVE_LEFT', ''), ('STRAIGHT', '')]),
        ("Omni line", "omni", (10.0, -16.0, 0.8), [('STRAIGHT', ''), ('MODULE', 'RAT')]),
        ("Chain line", "chain", (30.0, -16.0, 0.8), [('STRAIGHT', ''), ('CURVE_RIGHT', '')]),
    ):
        sc.cursor.location = loc
        op("new_line")
        o = bpy.context.view_layer.objects.active
        o.name = name
        op("set_type", type_id=ctype)
        for kind, module in pieces:
            op("segment_add", kind=kind, module=module) if module else op("segment_add", kind=kind)
        populate(o)
        made.append(o)
    pouch = bpy.data.objects.get("Pouch line")
    if pouch is not None:
        pouch.conveyor_line.support_mount = 'CEILING'
    STATE["lines"] += made
    log("other kinds:", [(o.name, o.conveyor_line.conveyor_type, len(o.conveyor_line.segments)) for o in made])
    redraw(2)


@step
def s_every_piece_solid():
    """Every line active in turn, every piece of it active in turn: the side panel's Details for every
    piece kind, the dimensions, the gizmos."""
    n = 0
    for o in STATE["lines"]:
        activate(o)
        for i in range(len(o.conveyor_line.segments)):
            o.conveyor_line.active_segment_index = i
            redraw(1)
            n += 1
    log("solid: drew", n, "piece states")
    activate(STATE["main"])
    STATE["main"].conveyor_line.active_segment_index = 5
    redraw(2)
    win = view3d()[0]
    path = os.path.join(OUT, "smoke_solid.png")
    with bpy.context.temp_override(window=win, screen=win.screen):
        bpy.ops.screen.screenshot(filepath=path)
    log("saved", path)


@step
def s_material_preview_playing():
    win, area, region, ui = view3d()
    area.spaces.active.shading.type = 'MATERIAL'
    activate(STATE["main"])
    sc = bpy.context.scene
    for f in range(1, 240, 12):
        sc.frame_set(f)
        redraw(1)
    log("material preview: goods moving, frame", sc.frame_current)
    path = os.path.join(OUT, "smoke_material.png")
    with bpy.context.temp_override(window=win, screen=win.screen):
        bpy.ops.screen.screenshot(filepath=path)
    log("saved", path)
    area.spaces.active.shading.type = 'SOLID'


@step
def s_edit_ops():
    """The list operators and the direction flip on the main line, then undo-free rebuild of everything."""
    main = STATE["main"]
    activate(main)
    main.conveyor_line.active_segment_index = 1
    for name in ("segment_duplicate", "segment_remove"):
        log(name, op(name))
    log("flip_direction", op("flip_direction", line_name=main.name))
    log("flip back", op("flip_direction", line_name=main.name))
    log("regenerate_all", op("regenerate_all"))
    redraw(2)


KEYS = "--enable-event-simulate" in sys.argv  # the keys reach build mode as real events, and nobody else's do


def press(key, **mods):
    """`mods`: shift / ctrl / alt / oskey = True, held with the key."""
    win, area, region, _ui = view3d()
    x, y = region.x + region.width // 2, region.y + region.height // 2
    win.event_simulate(type=key, value='PRESS', x=x, y=y, **mods)
    win.event_simulate(type=key, value='RELEASE', x=x, y=y, **mods)


@step
def s_build_mode_keys():
    """New Line at Cursor as the user clicks it (INVOKE in the 3D view): build mode starts, and the plain
    arrow keys build -- up a straight, left and right a curve, Backspace the right curve off again --
    while Shift + up lengthens the straight just added, Ctrl and Cmd + up raise it, Shift + left
    turns the curve further left."""
    from bl_ext.user_default.conveyor_system.operators import build_mode

    bpy.context.scene.cursor.location = (30.0, 0.0, 0.8)
    r = op("new_line", 'INVOKE_DEFAULT')
    line = bpy.context.view_layer.objects.active
    STATE["built"] = (line.name, len(line.conveyor_line.segments))
    log("build mode:", r, "running on", repr(build_mode.RUNNING["line"]), "for", line.name)
    if build_mode.RUNNING["line"] != line.name:
        STATE["errors"].append("build mode did not start after New Line at Cursor")
    redraw(1)  # the panel's button, lit: "Building: Enter or Esc ends"
    if not KEYS:
        log("SKIP: build mode keys: run with --enable-event-simulate")
        return
    for key, mods in (('UP_ARROW', {}), ('UP_ARROW', {"shift": True}), ('UP_ARROW', {"ctrl": True}), ('UP_ARROW', {"oskey": True}),
                      ('LEFT_ARROW', {}), ('LEFT_ARROW', {"shift": True}), ('RIGHT_ARROW', {}), ('BACK_SPACE', {})):
        press(key, **mods)


@step
def s_build_mode_end():
    from bl_ext.user_default.conveyor_system.operators import build_mode

    name, n0 = STATE["built"]
    line = bpy.data.objects[name]
    segs = line.conveyor_line.segments
    if KEYS:
        kinds = [(s.kind, s.curve_direction if s.kind == 'CURVE' else '') for s in segs]
        log("build mode keys:", kinds)
        if len(segs) != n0 + 2 or kinds[-2:] != [('STRAIGHT', ''), ('CURVE', 'LEFT')]:
            STATE["errors"].append(f"build mode keys built {kinds}")
        else:
            tuned = (round(segs[-2].length_mm), round(segs[-2].rise_mm), segs[-1].curve_angle_deg)
            log("build mode Shift / Ctrl / Cmd keys:", tuned)
            if tuned != (3150, 200, 105):
                STATE["errors"].append(f"Shift / Ctrl / Cmd + arrows tuned {tuned}, not (3150, 200, 105)")
        redraw(1)
        win = view3d()[0]
        path = os.path.join(OUT, "smoke_build_mode.png")  # the status bar's key hint
        with bpy.context.temp_override(window=win, screen=win.screen):
            bpy.ops.screen.screenshot(filepath=path)
        log("saved", path)
        press('RET')
    else:  # the button again ends it
        op("build_mode", 'INVOKE_DEFAULT')
    STATE["build_end"] = True


@step
def s_build_mode_ended():
    from bl_ext.user_default.conveyor_system.operators import build_mode

    log("build mode after Enter:", repr(build_mode.RUNNING["line"]))
    if build_mode.RUNNING["line"]:
        STATE["errors"].append("build mode still running after Enter")
    redraw(1)


@step
def s_popups():
    """The popups open (and draw) from the 3D view."""
    activate(STATE["main"])
    win, area, region, ui = view3d()
    for name in ("piece_library", "type_library", "checks"):
        try:
            with bpy.context.temp_override(window=win, area=area, region=region):
                r = getattr(bpy.ops.conveyor, name)('INVOKE_DEFAULT')
            log("popup", name, r)
        except Exception as e:
            STATE["errors"].append(f"popup {name}: {e}")
            log("ERROR popup", name, repr(e))
        redraw(1)


@step
def s_save_reload():
    """Save to the scratch folder and open it again: the lines come back and draw."""
    path = os.path.join(os.environ.get("TMPDIR") or SCRATCH_TMP, "smoke_scene.blend")  # the scratch TMPDIR, never a project folder
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
    bpy.ops.wm.open_mainfile(filepath=path)
    lines = [o for o in bpy.data.objects if o.type == 'CURVES' and o.conveyor_line.is_conveyor_line]
    log("reloaded lines:", len(lines))
    STATE["reloaded"] = len(lines)


@step
def s_after_reload():
    win, area, region, ui = view3d()
    area.spaces.active.show_region_ui = True
    for o in bpy.data.objects:
        if o.type == 'CURVES' and o.conveyor_line.is_conveyor_line:
            activate(o)
            redraw(1)
    ui = view3d()[3]
    log("sidebar tab:", ui.active_panel_category if ui else None, STATE.get("tab", ""))
    log("redraws", STATE["redraws"], "errors", STATE["errors"])


@step
def s_quit():
    log("RESULT", "DONE", "errors:", len(STATE["errors"]))
    tmp_base = bpy.context.preferences.filepaths.temporary_directory
    if os.path.realpath(tmp_base).startswith(os.path.realpath(SCRATCH_TMP)):
        bpy.ops.wm.quit_blender()
    else:
        os._exit(0)


def run_next():
    if not STEPS:
        return None
    fn = STEPS.pop(0)
    try:
        fn()
    except Exception:
        STATE["errors"].append(f"{fn.__name__}: {traceback.format_exc().splitlines()[-1]}")
        log("ERROR in", fn.__name__, traceback.format_exc())
    return 0.4


bpy.app.timers.register(run_next, first_interval=1.5, persistent=True)
