"""Listing content for extensions.blender.org: a short "screen recording" of the
add-on (captured from a real Blender window, step by step, with captions),
the preview stills and the featured image. Not shipped in the zip.

Run with a GUI, in a sandbox (never the user's own config; same guard as
tests/gui/smoke.py), with the window at 16:9 so the frames scale straight to
1920 x 1080:
  TMPDIR=<cfg>/tmp BLENDER_USER_EXTENSIONS=<ext> BLENDER_USER_CONFIG=<cfg> Blender --factory-startup \
    -p 0 0 1728 972 --python tools/showcase_capture.py -- <out dir> [trial]
then encode the frames headless: Blender -b --python tools/encode_video.py -- <out dir>

Writes <out>/frames/f_00001.png ... (24 fps, holds as hard links),
<out>/stills/*.png and <out>/featured.png. "trial" captures every step
but only a few frames of each animation stretch.
"""
import inspect, math, os, sys, traceback
import blf, bpy, gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Euler, Vector

PKG = "bl_ext.user_default.conveyor_system"
_CONFIG = os.environ.get("BLENDER_USER_CONFIG", "")
if not _CONFIG or not os.path.isdir(_CONFIG) or "Application Support/Blender" in _CONFIG:
    print("CAPTURE refused: run with a scratch BLENDER_USER_CONFIG (never the user's own)")
    os._exit(2)
SCRATCH_TMP = os.path.join(_CONFIG, "tmp")
os.makedirs(SCRATCH_TMP, exist_ok=True)
bpy.context.preferences.filepaths.temporary_directory = SCRATCH_TMP
bpy.context.preferences.use_preferences_save = False
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.view.smooth_view = 0
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = ARGS[0] if ARGS else os.getcwd()
TRIAL = "trial" in ARGS[1:]
FRAMES = os.path.join(OUT, "frames")
STILLS = os.path.join(OUT, "stills")
os.makedirs(FRAMES, exist_ok=True)
os.makedirs(STILLS, exist_ok=True)
FPS = 24
SETTLE = 0.45  # seconds the window gets after a UI change before a frame is held (panel animation)
S = {"n": 0, "caption": "", "sub": "", "errors": [], "lines": {}}


def log(*a):
    print("CAPTURE", " ".join(str(x) for x in a))
    sys.stdout.flush()


# ---------------------------------------------------------------- window
def view3d():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == 'VIEW_3D':
            regions = {r.type: r for r in area.regions}
            return win, area, regions.get('WINDOW'), regions.get('UI')
    return win, None, None, None


def redraw(n=2):
    win, area, region, ui = view3d()
    if ui is not None:
        try:
            ui.active_panel_category = "Conveyor"
        except Exception:
            pass
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=n)


def shot(path):
    win = view3d()[0]
    with bpy.context.temp_override(window=win, screen=win.screen):
        bpy.ops.screen.screenshot(filepath=path)


def capture(frames=1):
    """The window as the next video frame, held for `frames` frames (hard links)."""
    redraw(2)
    S["n"] += 1
    first = os.path.join(FRAMES, f"f_{S['n']:05d}.png")
    shot(first)
    for _ in range(frames - 1):
        S["n"] += 1
        os.link(first, os.path.join(FRAMES, f"f_{S['n']:05d}.png"))


def settle():
    """Tags every area for redraw and returns the wait: yield it from a step (`yield settle()`), so
    the window redraws for real and the side panel's animation finishes before frames are held."""
    win = view3d()[0]
    for area in win.screen.areas:
        area.tag_redraw()
    return SETTLE


def hold(seconds):
    capture(max(1, int(round(seconds * FPS))))


def still(name):
    redraw(4)
    shot(os.path.join(STILLS, name))
    log("still", name)


def play(seconds, step=1, orbit_deg=0.0):
    """Goods moving: every captured frame advances the scene `step` frames (a time-lapse when > 1)."""
    sc = bpy.context.scene
    n = int(round(seconds * FPS))
    if TRIAL:
        n = min(n, 6)
    rv3d = view3d()[1].spaces.active.region_3d
    start = rv3d.view_rotation.to_euler()
    for i in range(n):
        sc.frame_set(sc.frame_current + step)
        if orbit_deg:
            e = start.copy()
            e.z += math.radians(orbit_deg) * (i + 1) / n
            rv3d.view_rotation = e.to_quaternion()
        capture(1)


# ---------------------------------------------------------------- captions
def _caption_draw():
    text, sub = S["caption"], S["sub"]
    if not text:
        return
    region = bpy.context.region
    scale = bpy.context.preferences.system.ui_scale
    size = int(20 * scale)
    blf.size(0, size)
    w, h = blf.dimensions(0, text)
    sw = 0
    if sub:
        blf.size(0, int(14 * scale))
        sw, _sh = blf.dimensions(0, sub)
    pad = int(14 * scale)
    box_w = max(w, sw) + 2 * pad
    box_h = h + 2 * pad + (int(24 * scale) if sub else 0)
    x0 = int(24 * scale)
    y0 = int(26 * scale)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    shader.uniform_float("color", (0.07, 0.08, 0.10, 0.82))
    verts = [(x0, y0), (x0 + box_w, y0), (x0 + box_w, y0 + box_h), (x0, y0 + box_h)]
    batch_for_shader(shader, 'TRI_FAN', {"pos": verts}).draw(shader)
    shader.uniform_float("color", (0.31, 0.76, 0.97, 1.0))
    bar = [(x0, y0), (x0 + int(4 * scale), y0), (x0 + int(4 * scale), y0 + box_h), (x0, y0 + box_h)]
    batch_for_shader(shader, 'TRI_FAN', {"pos": bar}).draw(shader)
    gpu.state.blend_set('NONE')
    blf.size(0, size)
    blf.color(0, 1.0, 1.0, 1.0, 1.0)
    blf.position(0, x0 + pad, y0 + box_h - pad - h, 0)
    blf.draw(0, text)
    if sub:
        blf.size(0, int(14 * scale))
        blf.color(0, 0.78, 0.82, 0.88, 1.0)
        blf.position(0, x0 + pad, y0 + pad, 0)
        blf.draw(0, sub)


def caption(text, sub=""):
    S["caption"], S["sub"] = text, sub


# ---------------------------------------------------------------- scene helpers
def op(name, **kw):
    win, area, region, _ui = view3d()
    try:
        with bpy.context.temp_override(window=win, area=area, region=region):
            return getattr(bpy.ops.conveyor, name)(**kw)
    except Exception as e:
        S["errors"].append(f"{name}: {e}")
        log("ERROR", name, repr(e))
        return {'ERROR'}


def activate(obj):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def populate(obj):
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line

    obj.conveyor_line["populate"] = True
    build_line(bpy.context, obj)


def colour_goods():
    """Blue totes and brown cartons instead of the neutral grey placeholders."""
    from bl_ext.user_default.conveyor_system.operators.populate import PLACEHOLDER_COLLECTION_NAME

    coll = bpy.data.collections.get(PLACEHOLDER_COLLECTION_NAME)
    if coll is None:
        return
    for o in coll.all_objects:
        if o.type != 'MESH':
            continue
        tote = "Tote" in o.name
        name = "Showcase Tote" if tote else "Showcase Carton"
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (0.05, 0.22, 0.62, 1.0) if tote else (0.62, 0.40, 0.20, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.45 if tote else 0.8
        mat.diffuse_color = (0.08, 0.30, 0.75, 1.0) if tote else (0.66, 0.45, 0.25, 1.0)
        o.data.materials.clear()
        o.data.materials.append(mat)


def bounds(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in objs:
        geo = o.evaluated_get(dg).evaluated_geometry()
        if geo.mesh is not None:
            mw = o.matrix_world
            vs = geo.mesh.vertices
            pts += [mw @ vs[i].co for i in range(0, len(vs), 7)]
        for inst in dg.object_instances:
            if inst.is_instance and inst.parent and inst.parent.original == o:
                pts.append(inst.matrix_world.translation.copy())
    if not pts:
        return Vector((0, 0, 0)), 5.0
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return (lo + hi) / 2, max((hi - lo).length, 3.0)


def piece_box(obj, index):
    """(lo, hi) world corners of piece `index` of a line: the faces wearing the active-piece highlight
    while it is the active piece."""
    obj.conveyor_line.active_segment_index = index
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    geo = obj.evaluated_get(dg).evaluated_geometry()
    mesh = geo.mesh
    slot = next((i for i, m in enumerate(mesh.materials) if m and m.name.startswith("Conveyor - Active Segment")), None)
    mw = obj.matrix_world
    pts = [mw @ mesh.vertices[v].co for poly in mesh.polygons if poly.material_index == slot for v in poly.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def piece_bounds(obj):
    """(centre, size) of the line's active piece: the faces wearing the active-piece highlight."""
    dg = bpy.context.evaluated_depsgraph_get()
    geo = obj.evaluated_get(dg).evaluated_geometry()  # kept: the mesh lives as long as the geometry does
    mesh = geo.mesh
    slot = next((i for i, m in enumerate(mesh.materials) if m and m.name.startswith("Conveyor - Active Segment")), None) if mesh else None
    if slot is None:
        return bounds([obj])
    mw = obj.matrix_world
    vids = {v for poly in mesh.polygons if poly.material_index == slot for v in poly.vertices}
    pts = [mw @ mesh.vertices[i].co for i in vids]
    if not pts:
        return bounds([obj])
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return (lo + hi) / 2, max((hi - lo).length, 2.0)


def frame_on(objs, seconds=0.6, distance=1.15, rot=None, box=None):
    """Eases the view onto the objects (or a (centre, size) box) over `seconds` (captured), the rotation optionally too."""
    rv3d = view3d()[1].spaces.active.region_3d
    centre, size = box if box is not None else bounds(objs)
    goal_loc, goal_dist = centre, size * distance
    a_loc, a_dist = rv3d.view_location.copy(), rv3d.view_distance
    a_rot = rv3d.view_rotation.copy()
    b_rot = Euler([math.radians(v) for v in rot]).to_quaternion() if rot else a_rot
    n = max(1, int(round(seconds * FPS))) if not TRIAL else 2
    for i in range(1, n + 1):
        t = i / n
        t = t * t * (3 - 2 * t)
        rv3d.view_location = a_loc.lerp(goal_loc, t)
        rv3d.view_distance = a_dist + (goal_dist - a_dist) * t
        rv3d.view_rotation = a_rot.slerp(b_rot, t)
        capture(1)


def shading(kind, overlays=True, sidebar=True):
    space = view3d()[1].spaces.active
    space.shading.type = kind
    if kind == 'MATERIAL':
        space.shading.use_scene_world = False
        try:
            space.shading.studio_light = "city.exr"  # neutral light, as the featured image
        except TypeError:
            pass
        space.shading.studiolight_rotate_z = math.radians(110)
    space.overlay.show_overlays = overlays
    space.show_region_ui = sidebar


# ---------------------------------------------------------------- the storyboard
STEPS = []


def step(fn):
    STEPS.append(fn)
    return fn


@step
def s_setup():
    if PKG not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module=PKG)
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    win, area, region, ui = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.screen.screen_full_area()  # the 3D view fills the window: viewport, toolbar, sidebar
    win, area, region, ui = view3d()
    space = area.spaces.active
    space.show_region_ui = True
    space.shading.type = 'SOLID'
    space.overlay.show_cursor = False
    space.overlay.show_outline_selected = False  # the conveyor reads, not Blender's orange outline
    rv3d = space.region_3d
    rv3d.view_perspective = 'PERSP'
    rv3d.view_rotation = Euler((math.radians(58), 0, math.radians(-38))).to_quaternion()
    rv3d.view_location = Vector((2.0, 4.0, 0.5))
    rv3d.view_distance = 14.0
    S["handler"] = bpy.types.SpaceView3D.draw_handler_add(_caption_draw, (), 'WINDOW', 'POST_PIXEL')
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, 100000
    sc.frame_set(1)
    bpy.ops.mesh.primitive_plane_add(size=400, location=(0, 0, 0))
    floor = bpy.context.view_layer.objects.active
    floor.name = "Floor"
    mat = bpy.data.materials.new("Showcase Floor")
    mat.diffuse_color = (0.42, 0.43, 0.45, 1.0)  # Solid shading: light grey, the line stands out (Material Preview: dark concrete)
    mat.use_nodes = True
    bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.09, 0.095, 0.10, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.85
    floor.data.materials.append(mat)
    floor.hide_select = True
    log("window", region.width, "x", region.height, "Blender", bpy.app.version_string)


@step
def s_title():
    caption("Path-Driven Conveyor System", "Conveyor lines in Blender, piece by piece")
    hold(2.0)


@step
def s_new_line():
    caption("New Line at Cursor", "Sidebar (N) > Conveyor")
    bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)
    op("new_line")
    main = bpy.context.view_layer.objects.active
    main.name = "Main line"
    S["lines"]["main"] = main
    yield settle()
    hold(1.6)


@step
def s_pieces():
    caption("Add pieces with the arrow keys", "Straight, Curve L / R – or Alt + arrows over the viewport")
    for kind in ('STRAIGHT', 'CURVE_RIGHT', 'STRAIGHT', 'STRAIGHT', 'CURVE_LEFT', 'STRAIGHT'):
        op("segment_add", kind=kind)
        yield settle()
        hold(0.55)
    frame_on([S["lines"]["main"]], 0.8)
    hold(0.8)
    yield settle()
    still("01_build_with_dimensions.png")


@step
def s_dimensions():
    caption("The viewport is the drawing", "Lengths, angles and radii on every piece – click one to type a value")
    main = S["lines"]["main"]
    main.conveyor_line.active_segment_index = 3
    yield settle()
    hold(1.0)
    seg = main.conveyor_line.segments[3]
    seg.length_mm = 4500.0
    yield settle()
    hold(1.4)


@step
def s_types():
    caption("Pick a type and width", "Roller (MDR), belt, modular belt, omni-wheel, pouch sorter")
    main = S["lines"]["main"]
    activate(main)
    for ctype in ("belt", "chain", "gravity_roller"):
        op("set_type", type_id=ctype)
        yield settle()
        hold(0.8)


@step
def s_populate():
    caption("Populate: goods flow along the line", "Placeholder totes, or any object you pick")
    main = S["lines"]["main"]
    populate(main)
    colour_goods()
    shading('MATERIAL')
    yield settle()
    hold(0.4)
    play(3.0)
    yield settle()
    still("02_goods_flowing.png")


@step
def s_branch():
    caption("Divert to a branch, merge from a feeder", "Pop-up belt transfers, angled merges, angled-roller belts, pushers ...")
    main = S["lines"]["main"]
    activate(main)
    main.conveyor_line.active_segment_index = len(main.conveyor_line.segments) - 1
    op("segment_add", kind='MODULE', module='DIVERTER')
    op("segment_add", kind='STRAIGHT')
    op("segment_add", kind='MODULE', module='MERGE')
    op("segment_add", kind='STRAIGHT')
    segs = main.conveyor_line.segments
    idx = next(i for i, s in enumerate(segs) if s.kind == 'MODULE' and s.module_kind == 'DIVERTER')
    op("new_line_at_junction", line_name=main.name, index=idx, side='LEFT')
    branch = bpy.context.view_layer.objects.active
    branch.name = "Branch"
    op("segment_add", kind='STRAIGHT')
    op("segment_add", kind='CURVE_LEFT')
    op("segment_add", kind='STRAIGHT')
    S["lines"]["branch"] = branch
    midx = next(i for i, s in enumerate(segs) if s.kind == 'MODULE' and s.module_kind == 'MERGE')
    op("new_line_at_junction", line_name=main.name, index=midx, side='RIGHT')
    feeder = bpy.context.view_layer.objects.active
    feeder.name = "Feeder"
    op("segment_add", kind='STRAIGHT')
    op("segment_add", kind='STRAIGHT')
    populate(feeder)
    colour_goods()
    S["lines"]["feeder"] = feeder
    log("branch", branch.name, "feeder", feeder.name, "main pieces", len(segs))
    activate(main)
    yield settle()
    frame_on([main, branch, feeder], 0.8)
    play(3.5)
    yield settle()
    still("03_divert_to_branch.png")


@step
def s_buffer():
    caption("Buffers queue goods, first in, first out", "Output %: what leaves – the rest piles up until it is full (time-lapse)")
    main = S["lines"]["main"]
    activate(main)
    main.conveyor_line.active_segment_index = len(main.conveyor_line.segments) - 1
    op("segment_add", kind='MODULE', module='BUFFER')
    buf = main.conveyor_line.segments[main.conveyor_line.active_segment_index]
    buf["buffer_out_pct"] = 40
    op("segment_add", kind='STRAIGHT')
    main.conveyor_line.active_segment_index = len(main.conveyor_line.segments) - 2
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line

    build_line(bpy.context, main)
    colour_goods()
    yield settle()
    frame_on([main], 0.8, box=piece_bounds(main), distance=2.2)
    play(4.0, step=10)
    yield settle()
    still("04_buffer_filling.png")


def mezzanine(line):
    """A slab on four columns under the line's upper run: the legs land on it (Floors: any mesh below)."""
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj

    n = len(line.conveyor_line.segments)
    boxes = [piece_box(line, i) for i in (n - 2, n - 1)]  # the two straights after the spiral
    lo = Vector((min(b[0].x for b in boxes), min(b[0].y for b in boxes), 0))
    hi = Vector((max(b[1].x for b in boxes), max(b[1].y for b in boxes), 0))
    top = max(b[1].z for b in boxes)
    z = top - 0.95  # the slab's top, under the bed
    size = Vector((hi.x - lo.x + 1.4, hi.y - lo.y + 1.4, 0.2))
    centre = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, z - 0.1))
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=centre)
    slab = bpy.context.view_layer.objects.active
    slab.name, slab.scale = "Mezzanine", size
    mat = bpy.data.materials.new("Showcase Mezzanine")
    mat.diffuse_color = (0.55, 0.57, 0.60, 1.0)
    slab.data.materials.append(mat)
    for sx in (-1, 1):
        for sy in (-1, 1):
            h = z - 0.2
            bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=h, location=(centre.x + sx * (size.x / 2 - 0.3), centre.y + sy * (size.y / 2 - 0.3), h / 2))
            col = bpy.context.view_layer.objects.active
            col.name = "Mezzanine column"
            col.data.materials.append(mat)
    for _ in range(3):
        bpy.context.view_layer.update()
        dj.run_sync(bpy.context.scene)
    activate(line)
    log("mezzanine at", round(z, 2), "m")


@step
def s_spiral():
    caption("Spirals and vertical conveyors", "Up to a mezzanine, legs land on whatever floor is below")
    bpy.context.scene.cursor.location = (-6.0, -2.0, 0.0)  # on the floor: the line starts at 0.8 m
    op("new_line")
    sp = bpy.context.view_layer.objects.active
    sp.name = "Spiral line"
    op("set_type", type_id="belt")
    op("segment_add", kind='SPIRAL')
    seg = sp.conveyor_line.segments[sp.conveyor_line.active_segment_index]
    seg["rise_mm"] = 3000.0
    op("segment_add", kind='STRAIGHT')
    op("segment_add", kind='STRAIGHT')
    populate(sp)
    colour_goods()
    S["lines"]["spiral"] = sp
    yield settle()
    frame_on([sp], 0.8)
    play(1.5)
    mezzanine(sp)
    yield settle()
    play(2.0)
    yield settle()
    still("05_spiral.png")


@step
def s_finale():
    caption("Path-Driven Conveyor System", "Blender 5.2+  ·  free and open source (GPL)")
    lines = [o for o in S["lines"].values()]
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = None
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj

    bpy.context.view_layer.update()
    dj.run_sync(bpy.context.scene)  # the active-piece band goes with the active object (as the next pass would)
    view3d()[1].spaces.active.show_gizmo = False
    shading('MATERIAL', overlays=False, sidebar=False)
    yield settle()
    # an orbit around the spiral and its mezzanine, the main line behind (ends near the featured image's angle)
    hero = [o for o in (S["lines"].get("spiral"), bpy.data.objects.get("Mezzanine")) if o]
    frame_on(lines, 1.2, distance=1.3, rot=(62, 0, -80), box=bounds(hero))
    play(5.0, orbit_deg=45.0)
    caption("")
    yield settle()
    still("06_layout.png")


FEATURED = (  # (name, camera tilt from straight down, heading, distance / layout size, lens)
    ("featured_a.png", 62, -50, 0.95, 35),
    ("featured_b.png", 66, -125, 0.85, 35),
    ("featured_c.png", 58, 35, 0.95, 35),
)


@step
def s_featured():
    """The featured image: a camera on the layout, rendered through the viewport (Material Preview,
    no overlays), 1920 x 1080. A few framings to choose from."""
    lines = [o for o in S["lines"].values()]
    centre, size = bounds(lines)
    sc = bpy.context.scene
    cam_data = bpy.data.cameras.new("Showcase camera")
    cam = bpy.data.objects.new("Showcase camera", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1920, 1080, 100
    sc.render.image_settings.file_format = 'PNG'
    win, area, region, _ui = view3d()
    rv3d = area.spaces.active.region_3d
    rv3d.view_perspective = 'CAMERA'
    for name, tilt, heading, dist, lens in FEATURED:
        cam_data.lens = lens
        rot = Euler((math.radians(tilt), 0.0, math.radians(heading)))
        cam.rotation_euler = rot
        cam.location = centre + rot.to_matrix() @ Vector((0.0, 0.0, size * dist))
        bpy.context.view_layer.update()
        sc.render.filepath = os.path.join(OUT, name)
        try:
            with bpy.context.temp_override(window=win, area=area, region=region):
                bpy.ops.render.opengl(write_still=True, view_context=True)
            log("featured", name)
        except Exception as e:
            S["errors"].append(f"featured {name}: {e}")
            log("ERROR featured", name, repr(e))


@step
def s_save():
    """The finished scene, for re-shooting the featured image (tools/featured_shots.py)."""
    path = os.path.join(os.environ.get("TMPDIR") or SCRATCH_TMP, "showcase_scene.blend")  # the scratch TMPDIR, never a project folder
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
    log("saved scene", path)


@step
def s_quit():
    log("frames", S["n"], "errors", S["errors"])
    log("RESULT", "DONE")
    tmp_base = bpy.context.preferences.filepaths.temporary_directory
    if os.path.realpath(tmp_base).startswith(os.path.realpath(SCRATCH_TMP)):
        bpy.ops.wm.quit_blender()
    else:
        os._exit(0)


RUNNING = {"gen": None, "name": ""}


def run_next():
    """Runs the steps in order; a step that yields gets the window back for that many seconds (the
    side panel's animation settles) and resumes after."""
    gen = RUNNING["gen"]
    if gen is not None:
        try:
            return max(float(next(gen) or 0.0), 0.01)
        except StopIteration:
            RUNNING["gen"] = None
        except Exception:
            RUNNING["gen"] = None
            S["errors"].append(f"{RUNNING['name']}: {traceback.format_exc().splitlines()[-1]}")
            log("ERROR in", RUNNING["name"], traceback.format_exc())
        return 0.3
    if not STEPS:
        return None
    fn = STEPS.pop(0)
    try:
        result = fn()
        if inspect.isgenerator(result):
            RUNNING["gen"], RUNNING["name"] = result, fn.__name__
            return 0.01
    except Exception:
        S["errors"].append(f"{fn.__name__}: {traceback.format_exc().splitlines()[-1]}")
        log("ERROR in", fn.__name__, traceback.format_exc())
    return 0.3


bpy.app.timers.register(run_next, first_interval=1.5)
