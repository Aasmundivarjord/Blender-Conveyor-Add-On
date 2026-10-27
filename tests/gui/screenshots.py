"""Light and dark screenshots of the overlays (suite UI rule: every UI release
puts them in previews/), plus two checks that need a real window: multi-edit
through the side panel's region, and that overlay colours reach the screen
as given (sRGB). Run with a GUI (not -b), in a sandbox:
  TMPDIR=<cfg>/tmp BLENDER_USER_EXTENSIONS=<ext> BLENDER_USER_CONFIG=<cfg> Blender --factory-startup -p 0 0 1728 1052 \
    --python tests/gui/screenshots.py -- <out dir>
(-p fixes the window at 1728 x 1052 points, 3456 x 2104 pixels on a Retina display, so the
pictures keep one shape whichever monitor Blender would open on.)
A windowed Blender writes quit.blend (and autosaves) into its temp folder on
quit, and the system temp folder's quit.blend is the user's "Recover Last
Session" (suite rule, 2026-10-13). So this script refuses to run without a
scratch BLENDER_USER_CONFIG and points the temp folder inside it first.
"""
import math, os, sys, traceback
import bpy, gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Euler, Vector

PKG = "bl_ext.user_default.conveyor_system"
_CONFIG = os.environ.get("BLENDER_USER_CONFIG", "")
if not _CONFIG or not os.path.isdir(_CONFIG) or "Application Support/Blender" in _CONFIG:
    print("SHOT refused: run with a scratch BLENDER_USER_CONFIG (never the user's own)")
    os._exit(2)  # quits without writing quit.blend anywhere
SCRATCH_TMP = os.path.join(_CONFIG, "tmp")
os.makedirs(SCRATCH_TMP, exist_ok=True)
bpy.context.preferences.filepaths.temporary_directory = SCRATCH_TMP  # quit.blend and autosaves go here, never the system temp
bpy.context.preferences.use_preferences_save = False
bpy.context.preferences.view.show_splash = False  # (runs before the splash would open; preferences are not saved)
OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else os.getcwd()
LOG = []
def log(*a):
    s = " ".join(str(x) for x in a); LOG.append(s); print("SHOT", s)

def view3d():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == 'VIEW_3D':
            regions = {r.type: r for r in area.regions}
            return win, area, regions.get('WINDOW'), regions.get('UI')
    return win, None, None, None

def build():
    bpy.context.preferences.use_preferences_save = False
    if PKG not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module=PKG)
    from bl_ext.user_default.conveyor_system.operators.new_line import create_line
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
    from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild
    ctx = bpy.context
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    main = create_line(ctx, Vector((100.0, 100.0, 0.0)), 0.0); main.name = "Main"; main.location = Vector((0.0, 0.0, 0.0))
    with suspended_rebuild():
        s = main.conveyor_line; s.segments[0]["length_mm"] = 8000.0
        c = s.segments.add(); c.kind = 'CURVE'; c.curve_direction = 'RIGHT'
        t = s.segments.add(); t.kind = 'STRAIGHT'; t["length_mm"] = 3000.0
        s.populate = True; s.speed_m_s = 0.5; s.active_segment_index = 0
    ctx.view_layer.update(); build_line(ctx, main); ctx.view_layer.update()
    feeder = create_line(ctx, Vector((100.0, 100.0, 0.0)), -math.pi / 4); feeder.name = "Feeder"; feeder.location = Vector((-2.6, 2.0, 0.0))
    with suspended_rebuild():
        feeder.conveyor_line.segments[0]["length_mm"] = 3000.0
    ctx.view_layer.update(); build_line(ctx, feeder); ctx.view_layer.update()
    other = create_line(ctx, Vector((100.0, 100.0, 0.0)), 0.0); other.name = "Second line"; other.location = Vector((-4.0, -3.5, 0.0))
    ctx.view_layer.update(); build_line(ctx, other); ctx.view_layer.update()
    for _ in range(3):
        ctx.view_layer.update(); dj.run_sync(ctx.scene)
    for o in ctx.view_layer.objects:
        o.select_set(False)
    for o in (main, feeder, other):
        o.select_set(True)
    ctx.view_layer.objects.active = main
    log("docked feeder:", dj.docked_junction(ctx, feeder) is not None)
    return main, feeder, other

def frame(area):
    space = area.spaces.active
    space.shading.type = 'SOLID'
    space.show_region_ui = True
    space.overlay.show_overlays = True
    rv3d = space.region_3d
    rv3d.view_perspective = 'PERSP'
    rv3d.view_location = Vector((1.0, 3.5, 0.0))
    rv3d.view_rotation = Euler((math.radians(50.0), 0.0, math.radians(-25.0))).to_quaternion()
    rv3d.view_distance = 15.0

def light_theme():
    th = bpy.context.preferences.themes[0]
    path = None
    for folder in bpy.utils.preset_paths("interface_theme"):
        for name in sorted(os.listdir(folder)):
            if "light" in name.lower() and name.endswith(".xml"):
                path = os.path.join(folder, name)
                break
    if path:
        bpy.ops.script.execute_preset(filepath=path, menu_idname="USERPREF_MT_interface_theme_presets")
    g = th.view_3d.space.gradients
    g.background_type = 'SINGLE_COLOR'; g.high_gradient = (0.95, 0.95, 0.95)
    log("light theme preset:", os.path.basename(path) if path else None)

def dark_theme():
    bpy.ops.preferences.reset_default_theme()

PROBE = []
def _probe_draw():
    region = bpy.context.region
    sh = gpu.shader.from_builtin('UNIFORM_COLOR')
    for (x, y, rgb) in PROBE:
        sh.uniform_float("color", (*rgb, 1.0))
        batch_for_shader(sh, 'TRIS', {"pos": [(x, y), (x + 30, y), (x + 30, y + 30), (x, y), (x + 30, y + 30), (x, y + 30)]}).draw(sh)

def shoot(name):
    win, area, region, _ui = view3d()
    path = os.path.join(OUT, name)
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)
    with bpy.context.temp_override(window=win, screen=win.screen):
        bpy.ops.screen.screenshot(filepath=path)  # the whole window: the overlays and the side panel in that theme
    log("saved", path)
    return path, area, region

def read_probe(path, area, region):
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    px = img.pixels[:]
    out = []
    for (x, y, rgb) in PROBE:
        ix, iy = int(region.x + x + 15), int(region.y + y + 15)  # window pixels
        k = 4 * (iy * w + ix)
        out.append((rgb, tuple(round(v, 3) for v in px[k:k + 3])))
    bpy.data.images.remove(img)
    return out

STEPS = []
def step(fn):
    STEPS.append(fn); return fn

@step
def s_build():
    STATE["lines"] = build()
    win, area, region, ui = view3d()
    frame(area)
    show_conveyor_panels()


def show_conveyor_panels():
    """The side panel's tab is read-only from Python: for the pictures, the
    Conveyor panels move into the open tab (Item), first (this run only)."""
    panels = [c for c in bpy.types.Panel.__subclasses__() if getattr(c, "bl_category", "") == "Conveyor" and getattr(c, "is_registered", False)]
    children = [c for c in panels if getattr(c, "bl_parent_id", "")]
    parents = [c for c in panels if c not in children]
    try:
        for c in children + parents:
            bpy.utils.unregister_class(c)
        for c in parents + children:
            c.bl_category = "Item"
        for c in parents:
            c.bl_order = -10
        for c in parents + children:
            bpy.utils.register_class(c)
        log("Conveyor panels shown in the open tab:", [c.__name__ for c in parents])
    except Exception as e:
        log("could not move the panels:", e)

@step
def s_multi_edit():
    main, feeder, other = STATE["lines"]
    win, area, region, ui = view3d()
    with bpy.context.temp_override(window=win, area=area, region=ui):
        main.conveyor_line.speed_m_s = 0.9
    log("multi-edit from the side panel: speeds", [round(o.conveyor_line.speed_m_s, 2) for o in (main, feeder, other)])
    STATE["multi_ok"] = all(abs(o.conveyor_line.speed_m_s - 0.9) < 1e-6 for o in (main, feeder, other))

@step
def s_light():
    light_theme()
    PROBE[:] = [(200, 60, (0.10, 0.10, 0.11)), (240, 60, (0.68, 0.29, 0.00)), (280, 60, (0.50, 0.50, 0.50))]
    STATE["probe_handle"] = bpy.types.SpaceView3D.draw_handler_add(_probe_draw, (), 'WINDOW', 'POST_PIXEL')

@step
def s_light_probe():
    path, area, region = shoot("_probe_light.png")
    for rgb, got in read_probe(path, area, region):
        log("probe drawn", rgb, "on screen", got)
    os.remove(path)
    bpy.types.SpaceView3D.draw_handler_remove(STATE.pop("probe_handle"), 'WINDOW')

@step
def s_light_shot():
    shoot("conveyor_overlays_light.png")

@step
def s_dark():
    dark_theme()

@step
def s_dark_shot():
    shoot("conveyor_overlays_dark.png")

def _clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)


def _view(loc, rot_deg, dist, sidebar=False):
    win, area, region, ui = view3d()
    space = area.spaces.active
    space.shading.type = 'SOLID'
    space.show_region_ui = sidebar
    rv3d = space.region_3d
    rv3d.view_perspective = 'PERSP'
    rv3d.view_location = Vector(loc)
    rv3d.view_rotation = Euler(tuple(math.radians(a) for a in rot_deg)).to_quaternion()
    rv3d.view_distance = dist
    rv3d.update()  # the view matrices now: a first shot once caught the old view in the new theme


def _line(name, loc, pieces, ctype='gravity_roller', **settings):
    from bl_ext.user_default.conveyor_system.operators.new_line import create_line
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line
    from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild

    ctx = bpy.context
    o = create_line(ctx, Vector((100.0, 100.0, 0.0)), 0.0, conveyor_type=ctype)
    o.name = name
    o.location = Vector(loc)
    with suspended_rebuild():
        s = o.conveyor_line
        for k, (length_mm, legs) in enumerate(pieces):
            seg = s.segments[0] if k == 0 else s.segments.add()
            seg.kind = 'STRAIGHT'
            seg["length_mm"] = float(length_mm)
            seg.legs = legs
        s.populate = True
        s.speed_m_s = 0.5
        for key, value in settings.items():
            setattr(s, key, value)
    ctx.view_layer.update()
    build_line(ctx, o)
    ctx.view_layer.update()
    return o


def _slab(name, loc, size, rgb):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    o = bpy.context.view_layer.objects.active
    o.name = name
    o.scale = size
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*rgb, 1.0)
    o.data.materials.append(mat)
    return o


@step
def s_pouch_build():
    """Two pouch sorters: portal frames on the floor, and hung from a ceiling slab."""
    _clear_scene()
    bpy.context.scene.conveyor_settings.ceiling_z = 4.6
    _slab("Ceiling slab", (4.2, 2.5, 4.7), (1.6, 6.5, 0.2), (0.62, 0.62, 0.64))
    _line("Pouch sorter on the floor", (0.0, 0.0, 2.6), [(5000, True)], ctype='pouch_sorter', support_mount='FLOOR')
    _line("Pouch sorter from the ceiling", (4.2, 0.0, 2.6), [(5000, True)], ctype='pouch_sorter', support_mount='CEILING')
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj

    for _ in range(2):
        bpy.context.view_layer.update()
        dj.run_sync(bpy.context.scene)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    _view((2.1, 2.5, 2.3), (82.0, 0.0, -28.0), 12.5)


@step
def s_pouch_light():
    light_theme()


@step
def s_pouch_light_shot():
    shoot("conveyor_pouch_supports_light.png")


@step
def s_pouch_dark():
    dark_theme()


@step
def s_pouch_dark_shot():
    shoot("conveyor_pouch_supports_dark.png")


@step
def s_legs_build():
    """A line over a walkway: the 3 m piece above it has no legs, a stand flush with each edge."""
    _clear_scene()
    _slab("Walkway", (0.0, 5.5, 0.004), (2.6, 2.6, 0.008), (0.95, 0.78, 0.05))
    o = _line("Line over a walkway", (0.0, 0.0, 1.0), [(4000, True), (3000, False), (4000, True)])
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    o.conveyor_line.active_segment_index = 1
    _view((0.0, 5.5, 0.7), (66.0, 0.0, -38.0), 10.0)


@step
def s_legs_light():
    light_theme()


@step
def s_legs_light_shot():
    shoot("conveyor_leg_free_light.png")


@step
def s_legs_dark():
    dark_theme()


@step
def s_legs_dark_shot():
    shoot("conveyor_leg_free_dark.png")


@step
def s_stands_build():
    """Edit stands (2.14): a roller line hung from a ceiling slab with one
    hanger taken out -- a put-back button where it was, a take-out button on
    every other -- and a line on the floor beside it."""
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj

    _clear_scene()
    scene = bpy.context.scene
    scene.conveyor_settings.ceiling_z = 6.0  # the fallback; the hall below publishes 4.6 m clear (R17)
    _slab("Ceiling slab", (-1.2, 4.0, 4.7), (4.4, 9.5, 0.2), (0.62, 0.62, 0.64))
    import json
    hall = bpy.data.objects.new("Hall", None)
    scene.collection.objects.link(hall)
    hall["wh_levels"] = json.dumps([{"version": 2, "id": 0, "label": "Ground", "z": 0.0,
                                     "footprint": [[-20, -20], [20, -20], [20, 30], [-20, 30]], "headroom_m": 4.6}])
    _line("Line on the floor", (-2.4, 0.0, 1.0), [(8000, True)])
    o = _line("Line from the ceiling", (0.0, 0.0, 2.4), [(8000, True)], support_mount='CEILING')
    for _ in range(2):
        bpy.context.view_layer.update()
        dj.run_sync(scene)
    arcs = list(o.conveyor_line["stand_arcs"])
    bpy.ops.conveyor.stand_remove(line=o.name, arc=arcs[3])
    log("stands:", len(o.conveyor_line["stand_arcs"]), "taken out:", list(o.conveyor_line["stand_removed_arcs"]))
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    scene.conveyor_settings.edit_stands = True
    _view((-1.0, 4.0, 2.6), (78.0, 0.0, -62.0), 11.5, sidebar=True)
    STATE["stand_lines"] = (o, bpy.data.objects["Line on the floor"])


@step
def s_stands_scroll():
    """The side panel scrolled down to the line's Supports rows."""
    win, area, region, ui = view3d()
    with bpy.context.temp_override(window=win, area=area, region=ui):
        for _ in range(2):
            log("scroll the side panel:", bpy.ops.view2d.scroll_down(deltax=0, deltay=0, page=True))


@step
def s_stands_light():
    light_theme()


@step
def s_stands_light_shot():
    shoot("conveyor_edit_stands_light.png")


@step
def s_stands_dark():
    dark_theme()


@step
def s_stands_dark_shot():
    shoot("conveyor_edit_stands_dark.png")


@step
def s_stands_floor():
    """A check picture (not a preview): the buttons on a line standing on the floor."""
    hung, floor_line = STATE["stand_lines"]
    hung.select_set(False)
    floor_line.select_set(True)
    bpy.context.view_layer.objects.active = floor_line


@step
def s_stands_floor_shot():
    shoot("_check_floor_stands.png")


@step
def s_laid_out_build():
    """A belt laid out along points by another add-on (R21): a climb, a right
    angle and a 37.4 degree corner; the Line panel says who laid it out."""
    import json

    _clear_scene()
    bpy.context.scene.conveyor_settings.edit_stands = False
    a = math.radians(37.4)
    pts = [[0.0, 0.0, 0.8], [0.0, 7.0, 0.8], [0.0, 13.0, 2.0], [7.0, 13.0, 2.0], [7.0 + 6.0 * math.cos(a), 13.0 + 6.0 * math.sin(a), 2.0]]
    r = bpy.ops.conveyor.new_line(kind="line", preset="belt", points=json.dumps(pts), by="warehouse_floorplan")
    obj = bpy.context.view_layer.objects.active
    log("laid out:", r, obj.name if obj else None, [s.kind for s in obj.conveyor_line.segments] if obj else None)
    _view((4.0, 7.5, 1.2), (62.0, 0.0, -38.0), 17.0, sidebar=True)
    win, area, region, ui = view3d()
    with bpy.context.temp_override(window=win, area=area, region=ui):
        for _ in range(3):
            bpy.ops.view2d.scroll_up(deltax=0, deltay=0, page=True)


@step
def s_laid_out_light():
    light_theme()


@step
def s_laid_out_light_shot():
    shoot("conveyor_laid_out_light.png")


@step
def s_laid_out_dark():
    dark_theme()


@step
def s_laid_out_dark_shot():
    shoot("conveyor_laid_out_dark.png")


@step
def s_floors_build():
    """Scene > Floors (R3.1): a line over a plain floor and a table marked Not
    a floor (the legs pass it); the table active, so the panel shows Floor /
    Not a floor / Auto and Marked only."""
    _clear_scene()
    bpy.context.scene.conveyor_settings.edit_stands = False
    _slab("Plain floor", (0.0, 4.0, 0.4), (3.0, 9.0, 0.1), (0.70, 0.70, 0.72))
    table = _slab("Table", (0.0, 4.0, 1.6), (1.6, 2.4, 0.06), (0.55, 0.40, 0.25))
    _line("Line over a table", (0.0, 0.0, 3.0), [(8000, True)])
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    table.select_set(True)
    bpy.context.view_layer.objects.active = table
    r = bpy.ops.conveyor.mark_floor(mark='NOT_FLOOR')
    log("table marked not a floor:", r)
    # The Scene panel opens closed: a copy of it without DEFAULT_CLOSED, for this picture only.
    from bl_ext.user_default.conveyor_system.ui import panels as P

    src = P.VIEW3D_PT_conveyor_scene
    shot = type("VIEW3D_PT_conveyor_scene_shot", (bpy.types.Panel,), {
        "bl_label": src.bl_label, "bl_space_type": 'VIEW_3D', "bl_region_type": 'UI', "bl_category": "Item",
        "bl_parent_id": src.bl_parent_id, "bl_order": src.bl_order, "draw": src.draw})
    try:
        bpy.utils.unregister_class(src)
    except Exception:
        pass
    bpy.utils.register_class(shot)
    _view((0.0, 4.0, 1.4), (70.0, 0.0, -42.0), 13.0, sidebar=True)
    win, area, region, ui = view3d()
    with bpy.context.temp_override(window=win, area=area, region=ui):
        for _ in range(3):
            bpy.ops.view2d.scroll_up(deltax=0, deltay=0, page=True)


@step
def s_floors_light():
    light_theme()


@step
def s_floors_light_shot():
    shoot("conveyor_floors_light.png")


@step
def s_floors_dark():
    dark_theme()


@step
def s_floors_dark_shot():
    shoot("conveyor_floors_dark.png")


@step
def s_rat_widths_build():
    """Right-angle transfers next to wider and narrower conveyors (2.18): a
    650 mm line turning on a transfer into a 1200 mm takeaway, and a 500 mm
    transfer unit between two 1000 mm lines. Shot with 2.17 too (SHOT_ONLY,
    an older add-on in the sandbox) for the before / after pair."""
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line
    from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild

    _clear_scene()
    ctx = bpy.context
    scene = ctx.scene
    scene.conveyor_settings.edit_stands = False

    def takeaway(o):
        for x in ctx.view_layer.objects:
            x.select_set(False)
        o.select_set(True)
        ctx.view_layer.objects.active = o
        bpy.ops.conveyor.new_line_from_end()
        return ctx.view_layer.objects.active

    def settle():
        for _ in range(4):
            ctx.view_layer.update()
            dj.run_sync(scene)

    narrow = _line("Narrow line", (0.0, 0.0, 0.8), [(3000, True)], width_preset='iso_650')
    with suspended_rebuild():
        r = narrow.conveyor_line.segments.add()
        r.kind = 'MODULE'
        r.module_kind = 'RAT'
        r.module_exit = 'LEFT'
        narrow.conveyor_line.populate = False
    build_line(ctx, narrow)
    settle()
    wide = takeaway(narrow)
    wide.name = "Wide takeaway"
    wide.conveyor_line.width_preset = 'iso_1200'
    settle()
    feeder = _line("Feeder 1000", (3.5, 0.0, 0.8), [(3000, True)], width_preset='iso_1000')
    feeder.conveyor_line.populate = False
    unit = takeaway(feeder)
    unit.name = "Transfer unit"
    with suspended_rebuild():
        unit.conveyor_line.width_preset = 'iso_500'
        s0 = unit.conveyor_line.segments[0]
        s0.kind = 'MODULE'
        s0.module_kind = 'RAT'
        s0.module_exit = 'STRAIGHT'
    build_line(ctx, unit)
    settle()
    out = takeaway(unit)
    out.name = "Line 1000 after it"
    out.conveyor_line.width_preset = 'iso_1000'
    settle()
    for o in ctx.view_layer.objects:
        o.select_set(False)
    ctx.view_layer.objects.active = None
    try:  # the geometry alone: no flow labels or dimensions over the joints
        scene.conveyor_settings.show_flow_markers = False
        scene.conveyor_settings.show_dimensions = False
    except AttributeError:
        pass
    _view((1.6, 3.45, 0.8), (58.0, 0.0, -18.0), 6.2)


@step
def s_rat_widths_light():
    light_theme()


@step
def s_rat_widths_light_shot():
    shoot("conveyor_rat_widths_light.png")


@step
def s_rat_widths_dark():
    dark_theme()


@step
def s_rat_widths_dark_shot():
    shoot("conveyor_rat_widths_dark.png")


@step
def s_rat_motion_build():
    """A few frames of a tote through a right-angle transfer (2.18): coming
    in, standing while the belts lift it, out sideways, set down."""
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
    from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild

    _clear_scene()
    ctx = bpy.context
    scene = ctx.scene
    o = _line("Line through a transfer", (0.0, 0.0, 0.8), [(3000, True)])
    with suspended_rebuild():
        r = o.conveyor_line.segments.add()
        r.kind = 'MODULE'
        r.module_kind = 'RAT'
        r.module_exit = 'LEFT'
        t = o.conveyor_line.segments.add()
        t.kind = 'STRAIGHT'
        t["length_mm"] = 3000.0
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line

    build_line(ctx, o)
    for _ in range(3):
        ctx.view_layer.update()
        dj.run_sync(scene)
    seg = o.conveyor_line.segments[1]
    corner = Vector((0.0, 3.0 + seg.length_mm / 2000.0))
    first = None
    for fr in range(1, 200):
        scene.frame_set(fr)
        dg = ctx.evaluated_depsgraph_get()
        at = [i for i in dg.object_instances if i.is_instance and i.parent and i.parent.original == o
              and i.object.name.startswith("Placeholder") and (i.matrix_world.translation.xy - corner).length < 1e-3]
        if at:
            first = fr
            break
    STATE["motion"] = (o, first or 30)
    log("transfer stop from frame", first)
    for x in ctx.view_layer.objects:
        x.select_set(False)
    ctx.view_layer.objects.active = None
    scene.conveyor_settings.show_flow_markers = False
    scene.conveyor_settings.show_dimensions = False
    _view((-0.15, 3.45, 0.9), (76.0, 0.0, -42.0), 2.7)
    light_theme()


def _motion_frame(offset, name):
    def shot():
        o, first = STATE["motion"]
        bpy.context.scene.frame_set(first + offset)
        shoot(name)
    shot.__name__ = f"s_rat_motion_{name}"
    return step(shot)


_motion_frame(-14, "conveyor_rat_transfer_1_arriving.png")
_motion_frame(2, "conveyor_rat_transfer_2_stopped.png")
_motion_frame(12, "conveyor_rat_transfer_3_lifted.png")
_motion_frame(26, "conveyor_rat_transfer_4_sideways.png")
_motion_frame(44, "conveyor_rat_transfer_5_set_down.png")


@step
def s_side_motion_build():
    """A few frames of a tote taken off at a 90 degree pop-up divert (2.20):
    it stops on the transfer's centre, the belts lift it, it slides out onto
    the branch."""
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line
    from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild

    _clear_scene()
    ctx = bpy.context
    scene = ctx.scene
    o = _line("Main line", (0.0, 0.0, 0.8), [(3000, True)])
    with suspended_rebuild():
        m = o.conveyor_line.segments.add()
        m.kind = 'MODULE'
        m.module_kind = 'DIVERTER'
        m.merge_angle = '90'
        t = o.conveyor_line.segments.add()
        t.kind = 'STRAIGHT'
        t["length_mm"] = 3000.0
    build_line(ctx, o)
    for _ in range(3):
        ctx.view_layer.update()
        dj.run_sync(scene)
    bpy.ops.conveyor.new_line_at_junction(line_name=o.name, index=1, side='LEFT')
    for _ in range(3):
        ctx.view_layer.update()
        dj.run_sync(scene)
    branch = ctx.view_layer.objects.active
    centre = Vector((0.0, 3.0 + o.conveyor_line.segments[1].length_mm / 2000.0))
    first = None
    for fr in range(1, 260):
        scene.frame_set(fr)
        dg = ctx.evaluated_depsgraph_get()
        at = [i for i in dg.object_instances if i.is_instance and i.parent and i.parent.original in (o, branch)
              and i.object.name.startswith("Placeholder") and (i.matrix_world.translation.xy - centre).length < 1e-3]
        if at:
            first = fr
            break
    STATE["side_motion"] = first or 30
    log("divert stop from frame", first)
    for x in ctx.view_layer.objects:
        x.select_set(False)
    ctx.view_layer.objects.active = None
    scene.conveyor_settings.show_flow_markers = False
    scene.conveyor_settings.show_dimensions = False
    _view((-0.3, 3.3, 0.9), (70.0, 0.0, -125.0), 3.2)
    light_theme()


def _side_frame(offset, name):
    def shot():
        bpy.context.scene.frame_set(STATE["side_motion"] + offset)
        shoot(name)
    shot.__name__ = f"s_side_motion_{name}"
    return step(shot)


_side_frame(2, "conveyor_divert_transfer_1_stopped.png")
_side_frame(12, "conveyor_divert_transfer_2_lifted.png")
_side_frame(30, "conveyor_divert_transfer_3_out.png")


@step
def s_overhang_build():
    """2.21.1: the default 500 mm branch off a 90 degree pop-up divert. The
    totes keep their orientation through the transfer, so their 600 mm side
    crosses it; the branch is active and its Populate panel says so."""
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line
    from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild

    _clear_scene()
    ctx = bpy.context
    scene = ctx.scene
    scene.conveyor_settings.edit_stands = False
    o = _line("Main line", (0.0, 0.0, 0.8), [(3000, True)])
    with suspended_rebuild():
        m = o.conveyor_line.segments.add()
        m.kind = 'MODULE'
        m.module_kind = 'DIVERTER'
        m.merge_angle = '90'
        t = o.conveyor_line.segments.add()
        t.kind = 'STRAIGHT'
        t["length_mm"] = 3000.0
    build_line(ctx, o)
    for _ in range(3):
        ctx.view_layer.update()
        dj.run_sync(scene)
    bpy.ops.conveyor.new_line_at_junction(line_name=o.name, index=1, side='LEFT')
    branch = ctx.view_layer.objects.active
    branch.name = "Branch"
    with suspended_rebuild():
        branch.conveyor_line.segments[0]["length_mm"] = 2400.0
    build_line(ctx, branch)
    for _ in range(3):
        ctx.view_layer.update()
        dj.run_sync(scene)
    from bl_ext.user_default.conveyor_system.operators.populate import overhang_notes

    log("overhang notes:", overhang_notes(ctx, branch))
    shown = None
    for fr in range(1, 400):  # a frame with a tote in the middle of the branch
        scene.frame_set(fr)
        dg = ctx.evaluated_depsgraph_get()
        mid = [i for i in dg.object_instances if i.is_instance and i.parent and i.parent.original == branch
               and i.object.name.startswith("Placeholder Tote") and -1.9 < i.matrix_world.translation.x < -1.1]
        if mid:
            shown = fr
            break
    log("tote on the branch at frame", shown)
    for x in ctx.view_layer.objects:
        x.select_set(False)
    branch.select_set(True)
    ctx.view_layer.objects.active = branch
    scene.conveyor_settings.show_flow_markers = False
    scene.conveyor_settings.show_dimensions = False
    _view((-1.2, 3.3, 0.9), (60.0, 0.0, -140.0), 5.0, sidebar=True)


@step
def s_overhang_scroll():
    """The side panel scrolled down to the branch's Populate panel."""
    win, area, region, ui = view3d()
    with bpy.context.temp_override(window=win, area=area, region=ui):
        for _ in range(2):
            bpy.ops.view2d.scroll_down(deltax=0, deltay=0, page=True)


@step
def s_overhang_light():
    light_theme()


@step
def s_overhang_light_shot():
    shoot("conveyor_goods_wider_light.png")


@step
def s_overhang_dark():
    dark_theme()


@step
def s_overhang_dark_shot():
    shoot("conveyor_goods_wider_dark.png")


@step
def s_flow_build():
    """2.22 simple flow: a main line (the master, Population 60 %) with a 45
    degree diverter whose branch takes 30 % of it. The branch is active: its
    Populate panel follows the master ("30 % of Main line")."""
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line
    from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild

    _clear_scene()
    ctx = bpy.context
    scene = ctx.scene
    scene.conveyor_settings.edit_stands = False
    o = _line("Main line", (0.0, 0.0, 0.8), [(3000, True)])
    with suspended_rebuild():
        o.conveyor_line.population_pct = 60.0
        m = o.conveyor_line.segments.add()
        m.kind = 'MODULE'
        m.module_kind = 'DIVERTER'
        m.merge_angle = '45'
        st = o.conveyor_line.segments.add()
        st.kind = 'STRAIGHT'
        st["length_mm"] = 4000.0
    build_line(ctx, o)
    for _ in range(3):
        ctx.view_layer.update()
        dj.run_sync(scene)
    bpy.ops.conveyor.new_line_at_junction(line_name=o.name, index=1, side='LEFT')
    branch = ctx.view_layer.objects.active
    branch.name = "Branch"
    for _ in range(3):
        ctx.view_layer.update()
        dj.run_sync(scene)
    with suspended_rebuild():
        branch.conveyor_line.segments[0]["length_mm"] = 3000.0
        branch.conveyor_line.share_pct = 30
    build_line(ctx, branch)
    for _ in range(3):
        ctx.view_layer.update()
        dj.run_sync(scene)
    scene.frame_set(40)
    for x in ctx.view_layer.objects:
        x.select_set(False)
    branch.select_set(True)
    ctx.view_layer.objects.active = branch
    scene.conveyor_settings.show_flow_markers = True
    scene.conveyor_settings.show_dimensions = False
    STATE["flow_lines"] = (o, branch)
    _view((-0.6, 4.2, 0.9), (55.0, 0.0, -150.0), 9.0, sidebar=True)


@step
def s_flow_scroll():
    """The side panel scrolled down to the branch's Populate panel."""
    win, area, region, ui = view3d()
    with bpy.context.temp_override(window=win, area=area, region=ui):
        for _ in range(2):
            bpy.ops.view2d.scroll_down(deltax=0, deltay=0, page=True)


@step
def s_flow_light():
    light_theme()


@step
def s_flow_light_shot():
    shoot("conveyor_simple_flow_branch_light.png")


@step
def s_flow_dark():
    dark_theme()


@step
def s_flow_dark_shot():
    shoot("conveyor_simple_flow_branch_dark.png")


@step
def s_flow_master():
    """The main line active: the master's Population, Speed and Master."""
    main, branch = STATE["flow_lines"]
    branch.select_set(False)
    main.select_set(True)
    bpy.context.view_layer.objects.active = main


@step
def s_flow_master_dark_shot():
    shoot("conveyor_simple_flow_master_dark.png")


@step
def s_flow_master_light():
    light_theme()


@step
def s_flow_master_light_shot():
    shoot("conveyor_simple_flow_master_light.png")


@step
def s_flow_divert_build():
    """The same items leave at a divert (simple_flow.branch_of_item): the
    branch takes 25 % of the master, so every fourth tote -- items 3, 7,
    11, ... -- turns off: a taken item turning off, two items later one
    riding straight on, four items later the next taken one."""
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
    from bl_ext.user_default.conveyor_system.operators import stream
    from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild

    main, branch = STATE["flow_lines"]
    ctx = bpy.context
    with suspended_rebuild():
        branch.conveyor_line.share_pct = 25
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line

    build_line(ctx, branch)
    for _ in range(3):
        ctx.view_layer.update()
        dj.run_sync(ctx.scene)
    for x in ctx.view_layer.objects:
        x.select_set(False)
    ctx.view_layer.objects.active = None
    ctx.scene.conveyor_settings.show_flow_markers = False
    tree = stream.tree_for(ctx, main)
    fps = ctx.scene.render.fps / (ctx.scene.render.fps_base or 1.0)
    STATE["flow_item_frames"] = max(int(round(tree.actual_spacing / max(tree.speed, 1e-6) * fps)), 1)
    log("item every", STATE["flow_item_frames"], "frames; pitch", round(tree.actual_spacing, 3))
    # The first frame where a taken item has just turned onto the branch.
    first = 60
    for fr in range(1, 600):
        ctx.scene.frame_set(fr)
        dg = ctx.evaluated_depsgraph_get()
        start = branch.matrix_world.translation
        on = [i for i in dg.object_instances if i.is_instance and i.parent and i.parent.original == branch
              and i.object.name.startswith("Placeholder") and 0.5 < (i.matrix_world.translation - start).length < 1.0]
        if on:
            first = fr
            break
    STATE["flow_first"] = first
    log("an item turns off at frame", first)
    _view((-0.7, 4.0, 0.9), (55.0, 0.0, -140.0), 5.5)
    light_theme()


def _flow_frame(n, name):
    def shot():
        bpy.context.scene.frame_set(STATE["flow_first"] + n * STATE["flow_item_frames"])
        shoot(name)
    shot.__name__ = f"s_flow_divert_{name}"
    return step(shot)


_flow_frame(0, "conveyor_divert_branch_of_item_1.png")
_flow_frame(2, "conveyor_divert_branch_of_item_2.png")
_flow_frame(4, "conveyor_divert_branch_of_item_3.png")


@step
def s_flowport_build():
    """2.23 (R22): a rack's out-feed leads the line docked at it -- 50 % of
    1.2 m pallets at 0.2 m/s; the line keeps its own 0.4 m/s and shows the
    same goods at 25 %: "100 % of Pallet rack · out0"."""
    import json

    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line
    from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild

    _clear_scene()
    ctx = bpy.context
    scene = ctx.scene
    scene.conveyor_settings.edit_stands = False
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-60.0, -60.0, 0.0))
    pallet = ctx.view_layer.objects.active
    pallet.name = "EUR1 pallet"
    pallet.scale = (0.8, 1.2, 0.15)
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, -1.6, 2.0))
    rack = ctx.view_layer.objects.active
    rack.name = "Pallet rack"
    for v in rack.data.vertices:  # sized in its mesh: ports take no docks on a scaled system (1:1 metres)
        v.co = (v.co.x * 3.0, v.co.y * 2.4, v.co.z * 4.0)
    load = {"version": 2, "kind": "pallet", "id": "pallet:EUR1:Wood:1.2", "object": "EUR1 pallet", "length_m": 1.2, "width_m": 0.8,
            "height_m": 0.15, "forward_axis": "Y"}
    rack["wh_system"] = json.dumps({"version": 2, "addon": "warehouse_racks", "kind": "crane_rack", "id": "preview-rack", "object": rack.name,
                                    "label": rack.name, "level": 0, "footprint": [[-1.5, -1.2], [1.5, -1.2], [1.5, 1.2], [-1.5, 1.2]],
                                    "height_m": 4.0, "clearance_m": 0.0, "zone": None})
    rack["wh_ports"] = json.dumps([{"version": 2, "id": "out0", "role": "out", "kind": "point", "position": [0.0, 1.2, -1.2],
                                    "heading_deg": 0.0, "width_m": 0.8, "population": 0.5, "speed_m_s": 0.2, "master": True, "load": load}])
    o = _line("Line from the rack", (0.0, 0.0, 0.8), [(6000, True)])
    with suspended_rebuild():
        o.conveyor_line.width_preset = 'iso_1000'
    build_line(ctx, o)
    for _ in range(3):
        ctx.view_layer.update()
        dj.run_sync(scene)
    sid = json.loads(o["wh_system"])["id"]
    log("dock:", bpy.ops.conveyor.dock_line(line_id=sid, system_id="preview-rack", port_id="out0", anchor="start", by="preview"))
    with suspended_rebuild():
        o.conveyor_line.speed_m_s = 0.4
    build_line(ctx, o)
    for _ in range(3):
        ctx.view_layer.update()
        dj.run_sync(scene)
    scene.frame_set(60)
    for x in ctx.view_layer.objects:
        x.select_set(False)
    o.select_set(True)
    ctx.view_layer.objects.active = o
    scene.conveyor_settings.show_flow_markers = True
    _view((0.0, 2.5, 1.0), (58.0, 0.0, -145.0), 11.0, sidebar=True)


@step
def s_flowport_scroll():
    """The side panel scrolled down to the line's Populate panel."""
    win, area, region, ui = view3d()
    with bpy.context.temp_override(window=win, area=area, region=ui):
        for _ in range(2):
            bpy.ops.view2d.scroll_down(deltax=0, deltay=0, page=True)


@step
def s_flowport_light():
    light_theme()


@step
def s_flowport_light_shot():
    shoot("conveyor_simple_flow_port_light.png")


@step
def s_flowport_dark():
    dark_theme()


@step
def s_flowport_dark_shot():
    shoot("conveyor_simple_flow_port_dark.png")


@step
def s_handover_build():
    """2.23.4: goods as they ride on each line. Racks' 60/40 in-feed layout: a
    pallet line carries EUR1 (0.8 m along travel, forward X) at 100 %; a 90
    degree pop-up divert sends 60 % sideways to a crane in-feed -- a pop-up
    transfer does not turn the pallet, so it arrives 1.2 m along. Seen from
    above at the hand-over, and at the line's free end."""
    import json

    from mathutils import Vector

    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
    from bl_ext.user_default.conveyor_system.operators import ports
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line
    from bl_ext.user_default.conveyor_system.operators.detect_junctions import _world_matrix
    from bl_ext.user_default.conveyor_system.operators.new_line import create_line
    from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild

    _clear_scene()
    ctx = bpy.context
    scene = ctx.scene
    scene.conveyor_settings.edit_stands = False
    scene.conveyor_settings.show_flow_markers = False
    scene.conveyor_settings.show_dimensions = False

    def settle():
        for _ in range(4):
            ctx.view_layer.update()
            dj.run_sync(scene)

    def box(name, sx, sy, sz, loc, z0=0.0, color=(0.6, 0.6, 0.6, 1.0)):
        mesh = bpy.data.meshes.new(name)
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = color  # the solid view's colour: the pallet stands out from the decks
        mesh.materials.append(mat)
        hx, hy = sx / 2.0, sy / 2.0
        verts = [(-hx, -hy, z0), (hx, -hy, z0), (hx, hy, z0), (-hx, hy, z0), (-hx, -hy, z0 + sz), (hx, -hy, z0 + sz), (hx, hy, z0 + sz), (-hx, hy, z0 + sz)]
        mesh.from_pydata(verts, [], [(0, 1, 2, 3), (7, 6, 5, 4), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)])
        obj = bpy.data.objects.new(name, mesh)
        scene.collection.objects.link(obj)
        obj.location = loc
        return obj

    pallet = box("EUR1 pallet", 0.8, 1.2, 0.9, (-60.0, -60.0, 0.0), color=(0.78, 0.52, 0.26, 1.0))  # its 0.8 side runs first (forward X)
    eur1 = {"version": 2, "kind": "pallet", "id": "pallet:EUR1:Wood:1.2", "object": pallet.name, "length_m": 0.8, "width_m": 1.2,
            "height_m": 0.9, "forward_axis": "X"}
    pallet["wh_load"] = json.dumps(eur1)
    main = create_line(ctx, Vector((0.0, 0.0, 0.8)), 0.0)
    main.name = "Pallet line"
    with suspended_rebuild():
        s = main.conveyor_line
        s.segments[0]["length_mm"] = 6000.0
        seg = s.segments.add(); seg.kind = 'MODULE'; seg.module_kind = 'DIVERTER'; seg.merge_angle = '90'
        seg = s.segments.add(); seg.kind = 'STRAIGHT'; seg["length_mm"] = 4000.0
        s.populate = True
        s.width_preset = 'iso_1200'  # the pallet runs 1.2 m across on it
    build_line(ctx, main)
    settle()
    mid = json.loads(main["wh_system"])["id"]
    bpy.ops.conveyor.set_line_item(line_id=mid, load_json=json.dumps(eur1), by="preview")
    bpy.ops.conveyor.set_line_flow(line_id=mid, population=1.0, speed_m_s=0.2, by="preview")
    settle()
    bpy.ops.conveyor.new_line_at_junction(line_name=main.name, index=1, side='LEFT')
    branch = ctx.view_layer.objects.active
    branch.name = "Branch to the rack"
    settle()
    bpy.ops.conveyor.set_line_flow(line_id=json.loads(branch["wh_system"])["id"], share=0.6, by="preview")
    settle()
    end, _local, end_w = ports._end_pose(ctx, branch)
    heading = _world_matrix(branch).to_euler().z + end.heading
    goods = Vector((-math.sin(heading), math.cos(heading), 0.0))
    rack = box("Crane rack", 3.0, 2.4, 4.0, end_w + goods * 1.2 - Vector((0.0, 0.0, end_w.z)), color=(0.32, 0.45, 0.68, 1.0))
    rack.rotation_euler.z = heading
    ctx.view_layer.update()
    port_local = rack.matrix_world.inverted() @ end_w
    rack["wh_system"] = json.dumps({"version": 2, "addon": "warehouse_racks", "kind": "crane_rack", "id": "preview-crane", "object": rack.name,
                                    "label": rack.name, "level": 0, "footprint": [[-1.5, -1.2], [1.5, -1.2], [1.5, 1.2], [-1.5, 1.2]],
                                    "height_m": 4.0, "clearance_m": 0.0, "zone": None})
    rack["wh_ports"] = json.dumps([{"version": 2, "id": "aisle0_in", "role": "in", "kind": "point", "position": list(port_local),
                                    "heading_deg": 0.0, "width_m": 1.0, "max_population": 0.2, "speed_m_s": 0.2, "load": eur1}])
    settle()
    log("dock:", bpy.ops.conveyor.dock_line(line_id=json.loads(branch["wh_system"])["id"], system_id="preview-crane", port_id="aisle0_in",
                                            anchor="end", by="preview"))
    settle()

    def front_at_end(line):
        """{frame: how far the leading pallet's front is from `line`'s end} (negative: before it)."""
        e, _l, w = ports._end_pose(ctx, line)
        h = _world_matrix(line).to_euler().z + e.heading
        d = Vector((-math.sin(h), math.cos(h), 0.0))
        out = {}
        for fr in range(1, 1500, 2):
            scene.frame_set(fr)
            dg = ctx.evaluated_depsgraph_get()
            fronts = [max((i.matrix_world @ Vector(v) - w).dot(d) for v in i.object.bound_box) for i in dg.object_instances
                      if i.is_instance and i.parent and i.parent.original == line and i.object.name == pallet.name]
            fronts = [f for f in fronts if f > -3.0]
            if fronts:
                out[fr] = max(fronts)
        return out, w

    at_rack, rack_point = front_at_end(branch)
    at_free, free_point = front_at_end(main)
    STATE["handover_frame"] = min(at_rack, key=lambda fr: abs(at_rack[fr] + 0.02)) if at_rack else 60
    STATE["freeend_frame"] = min(at_free, key=lambda fr: abs(at_free[fr] + 0.02)) if at_free else 60
    STATE["handover_points"] = (rack_point, free_point)
    log("hand-over frame", STATE["handover_frame"], round(at_rack.get(STATE["handover_frame"], 9.0), 4),
        "free end frame", STATE["freeend_frame"], round(at_free.get(STATE["freeend_frame"], 9.0), 4))
    for x in ctx.view_layer.objects:
        x.select_set(False)
    ctx.view_layer.objects.active = None


def _top(point, dist):
    _view((point.x, point.y, point.z), (0.0, 0.0, 0.0), dist)
    win, area, region, ui = view3d()
    area.spaces.active.region_3d.view_perspective = 'ORTHO'
    area.spaces.active.region_3d.update()


@step
def s_handover_light():
    light_theme()
    bpy.context.scene.frame_set(STATE["handover_frame"])
    _top(STATE["handover_points"][0], 7.0)


@step
def s_handover_light_shot():
    shoot("conveyor_goods_turned_handover_light.png")


@step
def s_handover_freeend_light():
    bpy.context.scene.frame_set(STATE["freeend_frame"])
    _top(STATE["handover_points"][1], 6.0)


@step
def s_handover_freeend_light_shot():
    shoot("conveyor_goods_free_end_light.png")


@step
def s_handover_dark():
    dark_theme()
    bpy.context.scene.frame_set(STATE["handover_frame"])
    _top(STATE["handover_points"][0], 7.0)


@step
def s_handover_dark_shot():
    shoot("conveyor_goods_turned_handover_dark.png")


@step
def s_handover_freeend_dark():
    bpy.context.scene.frame_set(STATE["freeend_frame"])
    _top(STATE["handover_points"][1], 6.0)


@step
def s_handover_freeend_dark_shot():
    shoot("conveyor_goods_free_end_dark.png")


@step
def s_buffer_build():
    """2.24 (round 8 E): a buffer letting out 40 % of what arrives (1385/h in,
    554/h out) fills up -- the goods roll up to the queue and stand a zone
    each, stepping up as the front one leaves -- then holds its four zones
    while the line before runs at what it lets out. The piece panel says it
    in % and time (2.24.1): "Lets out 40 % of what arrives" and -- the scene
    ending at frame 250, before it is full -- "Full after 17 s (after scene
    end)"; run to frame 1200, "Full after 17 s, then holds 4"."""
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line
    from bl_ext.user_default.conveyor_system.props.line_settings import suspended_rebuild

    _clear_scene()
    ctx = bpy.context
    scene = ctx.scene
    scene.conveyor_settings.edit_stands = False
    scene.conveyor_settings.show_flow_markers = False
    scene.conveyor_settings.show_dimensions = False
    o = _line("Line with a buffer", (0.0, 0.0, 0.8), [(6000, True)])
    with suspended_rebuild():
        s = o.conveyor_line
        b = s.segments.add(); b.kind = 'MODULE'; b.module_kind = 'BUFFER'; b["length_mm"] = 3000.0; b["buffer_out_pct"] = 40
        t = s.segments.add(); t.kind = 'STRAIGHT'; t["length_mm"] = 6000.0
        s.population_pct = 50.0
        s.speed_m_s = 0.5
        s.active_segment_index = 1
    build_line(ctx, o)
    for _ in range(3):
        ctx.view_layer.update()
        dj.run_sync(scene)
    for x in ctx.view_layer.objects:
        x.select_set(False)
    ctx.view_layer.objects.active = o  # active (its panels show), not selected (no outline over the goods)
    _view((0.0, 7.0, 1.0), (58.0, 0.0, -142.0), 8.0, sidebar=True)


def _buffer_shot(frame, end):
    scene = bpy.context.scene
    scene.frame_end = end  # 250: it fills after the scene's end; 1200: within it
    scene.frame_set(frame)
    _frame_timeline()
    _view((0.0, 7.0, 1.0), (58.0, 0.0, -142.0), 8.0, sidebar=True)  # set again right before the capture (PM, 2026-10-15)


def _frame_timeline():
    """The timeline shows the whole scene range (View > Frame All)."""
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type != 'DOPESHEET_EDITOR':
            continue
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        try:
            with bpy.context.temp_override(window=win, area=area, region=region):
                bpy.ops.action.view_all()
        except Exception as exc:
            log(f"timeline view_all: {exc!r}")


@step
def s_buffer_scroll():
    """The side panel scrolled down to the buffer piece's details."""
    win, area, region, ui = view3d()
    with bpy.context.temp_override(window=win, area=area, region=ui):
        bpy.ops.view2d.scroll_down(deltax=0, deltay=0, page=True)


@step
def s_buffer_light():
    light_theme()
    _buffer_shot(120, 250)  # 5 s: filling; the scene ends before it is full


@step
def s_buffer_light_shot():
    shoot("conveyor_buffer_filling_light.png")


@step
def s_buffer_full_light():
    _buffer_shot(960, 1200)  # 40 s: full, holding its queue


@step
def s_buffer_full_light_shot():
    shoot("conveyor_buffer_full_light.png")


@step
def s_buffer_dark():
    dark_theme()
    _buffer_shot(120, 250)


@step
def s_buffer_dark_shot():
    shoot("conveyor_buffer_filling_dark.png")


@step
def s_buffer_full_dark():
    _buffer_shot(960, 1200)


@step
def s_buffer_full_dark_shot():
    shoot("conveyor_buffer_full_dark.png")


@step
def s_quit():
    log("MULTI_EDIT", "PASS" if STATE.get("multi_ok") else "FAIL")
    tmp_base = bpy.context.preferences.filepaths.temporary_directory
    log("temp folder at quit:", tmp_base)
    with open(os.path.join(OUT, "_screenshots.log"), "w") as f:
        f.write("\n".join(LOG) + "\n")
    if os.path.realpath(tmp_base).startswith(os.path.realpath(SCRATCH_TMP)):
        bpy.ops.wm.quit_blender()  # quit.blend lands in the scratch temp folder
    else:
        os._exit(0)  # never let quit.blend reach the system temp folder

STATE = {}
def run_next():
    if not STEPS:
        return None
    fn = STEPS.pop(0)
    try:
        fn()
    except Exception:
        log("ERROR in", fn.__name__, traceback.format_exc())
        STEPS[:] = [s_quit]
    return 1.0

_ONLY = os.environ.get("SHOT_ONLY", "")
if _ONLY:  # one scene only (the before / after pairs shot with an older add-on): its steps and the quit
    def s_enable():
        bpy.context.preferences.use_preferences_save = False
        if PKG not in bpy.context.preferences.addons:
            bpy.ops.preferences.addon_enable(module=PKG)
    STEPS[:] = [s_enable] + [s for s in STEPS if s.__name__.startswith(f"s_{_ONLY}") or s.__name__ == "s_quit"]
bpy.app.timers.register(run_next, first_interval=1.5)
