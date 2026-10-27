"""Shared set-up for the promo shots (tools/commercial): a clean product-studio look rendered with
EEVEE, lines built through the add-on, cameras, and a frame-by-frame renderer that lets a shot
change the scene between frames (a line growing, a height changing, the goods switching).
Not shipped in the zip. Imported by tools/commercial/shots.py (Blender -b)."""
import math, os, time
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

PKG = "bl_ext.user_default.conveyor_system"
ACCENT = (0.23, 0.51, 0.96)          # the promo's blue (titles, highlights)
TOTE = (0.03, 0.16, 0.62)            # goods: blue totes ...
CARTON = (0.55, 0.33, 0.15)          # ... and kraft cartons
FLOOR = (0.62, 0.63, 0.65)


def enable():
    if PKG not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module=PKG)


def reset():
    bpy.ops.wm.read_homefile(use_empty=True)
    enable()


# ---------------------------------------------------------------- look
def _principled(name, color, roughness=0.5, metallic=0.0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    mat.diffuse_color = (*color, 1.0)
    return mat


def studio(mode="final", floor=FLOOR, world=0.55, sun=3.6, sun_rot=(52.0, 0.0, 128.0)):
    """A seamless light floor, a soft gradient world lit by Blender's bundled studio HDRI, a soft
    key light, AgX. `mode`: final (EEVEE, 1920 x 1080), eevee_test (EEVEE 480 x 270, 12 samples),
    cpu (Cycles on the CPU, 480 x 270, 12 samples -- no GPU at all)."""
    sc = bpy.context.scene
    # floor: one big plane, matte
    bpy.ops.mesh.primitive_plane_add(size=600.0, location=(0, 0, 0))
    fl = bpy.context.view_layer.objects.active
    fl.name = "Studio floor"
    fl.data.materials.append(_principled("Studio floor", floor, roughness=0.85))
    fl.hide_select = True
    # world: the HDRI for light and reflections (every shot looks down at the floor, so the camera
    # never sees it; no Light Path trick either -- EEVEE lights the scene with that flat camera
    # background and everything goes flat)
    w = bpy.data.worlds.new("Studio")
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    hdri = os.path.join(bpy.utils.system_resource('DATAFILES'), "studiolights", "world", "studio.exr")
    bg_light = nt.nodes.new("ShaderNodeBackground")
    bg_light.inputs["Strength"].default_value = world
    bg_light.inputs["Color"].default_value = (0.8, 0.8, 0.82, 1.0)
    if os.path.isfile(hdri):  # never an Environment Texture without its image (it renders magenta)
        env.image = bpy.data.images.load(hdri, check_existing=True)
        nt.links.new(env.outputs["Color"], bg_light.inputs["Color"])
    else:
        nt.nodes.remove(env)
    nt.links.new(bg_light.outputs[0], out.inputs["Surface"])
    # key light
    ld = bpy.data.lights.new("Key", 'SUN')
    ld.energy = sun
    ld.angle = math.radians(6.0)
    key = bpy.data.objects.new("Key", ld)
    key.rotation_euler = Euler([math.radians(a) for a in sun_rot])
    sc.collection.objects.link(key)
    # render
    r = sc.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = 1920, 1080, 100
    r.fps, r.fps_base = 30, 1.0
    r.image_settings.file_format = 'PNG'
    r.film_transparent = False
    try:
        sc.view_settings.view_transform = 'AgX'
        sc.view_settings.look = 'AgX - Medium High Contrast'
    except TypeError:
        pass
    set_mode(mode)


def set_mode(mode):
    sc = bpy.context.scene
    r = sc.render
    if os.environ.get("PROMO_RES"):  # e.g. 2560x1440 for the poster
        r.resolution_x, r.resolution_y = (int(v) for v in os.environ["PROMO_RES"].lower().split("x"))
    if mode == "cpu":
        r.engine = 'CYCLES'
        sc.cycles.device = 'CPU'
        sc.cycles.samples = int(os.environ.get("PROMO_SAMPLES", "12"))  # more for a CPU still (the poster)
        sc.cycles.use_denoising = True
        r.resolution_percentage = int(os.environ.get("PROMO_PCT", "25"))  # a bigger check frame when asked
    else:
        r.engine = 'BLENDER_EEVEE'
        ee = sc.eevee
        ee.taa_render_samples = 12 if mode == "eevee_test" else 64
        ee.use_shadows = True
        ee.use_raytracing = True
        ee.use_fast_gi = True
        r.resolution_percentage = 25 if mode == "eevee_test" else 100
        sc.view_settings.exposure = -0.3  # EEVEE lights the studio floor brighter than Cycles does
        opts = set(filter(None, os.environ.get("PROMO_EEVEE", "").split(",")))  # memory experiments (shared GPU)
        if "noraytrace" in opts:
            ee.use_raytracing = False
        if "nofastgi" in opts:
            ee.use_fast_gi = False
        for o in opts:
            if o.startswith("pool"):
                ee.shadow_pool_size = o[4:]


def colour_frames():
    """Graphite frames and bright rollers: the line reads against the light studio floor."""
    for mat in bpy.data.materials:
        if mat.get("wh_material") != "conveyor_frame":
            continue
        color, rough, metal = (0.10, 0.11, 0.12), 0.45, 0.6
        if mat.use_nodes:
            bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf is not None:
                bsdf.inputs["Base Color"].default_value = (*color, 1.0)
                bsdf.inputs["Roughness"].default_value = rough
                bsdf.inputs["Metallic"].default_value = metal


def colour_goods():
    """Blue totes and kraft cartons for the placeholder goods (call after a line is populated)."""
    from bl_ext.user_default.conveyor_system.operators.populate import PLACEHOLDER_COLLECTION_NAME

    coll = bpy.data.collections.get(PLACEHOLDER_COLLECTION_NAME)
    if coll is None:
        return
    tote = _principled("Promo tote", TOTE, roughness=0.35)
    carton = _principled("Promo carton", CARTON, roughness=0.8)
    for o in coll.all_objects:
        if o.type == 'MESH':
            o.data.materials.clear()
            o.data.materials.append(tote if "Tote" in o.name else carton)
    colour_frames()


# ---------------------------------------------------------------- lines
def line(name, loc, heading_deg=0.0, pieces=(("S", 3000),), ctype=None, populate=True, population=50.0, speed=0.5,
         width_mm=None, item=None):
    """A line built through the add-on. pieces: ("S", mm), ("CL"|"CR", deg), ("SP", turns, rise_mm, "LEFT"|"RIGHT"),
    ("M", module, {prop: value}), ("UP", mm, rise_mm) for a straight that climbs. `width_mm`: a custom width
    (a pallet line); `item`: an object as the goods (what the eyedropper picks)."""
    from bl_ext.user_default.conveyor_system.operators.new_line import create_line
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line

    def fill(s):
        if ctype:
            s.conveyor_type = ctype
        for i, p in enumerate(pieces):
            seg = s.segments[0] if i == 0 and len(s.segments) else s.segments.add()
            add_piece(seg, p)
        if width_mm:
            s.width_preset = 'CUSTOM'
            s.custom_width_mm = float(width_mm)
        s.populate = populate
        s.population_pct = population
        s.speed_m_s = speed
        if item is not None:
            s.populate_item = item

    ctx = bpy.context
    o = create_line(ctx, Vector(loc), math.radians(heading_deg), conveyor_type=ctype, fill=fill)
    o.name = name
    build_line(ctx, o)
    settle()
    return o


def add_piece(seg, p):
    kind = p[0]
    if kind == "S":
        seg.kind = 'STRAIGHT'; seg["length_mm"] = float(p[1])
    elif kind == "UP":
        seg.kind = 'STRAIGHT'; seg["length_mm"] = float(p[1]); seg["rise_mm"] = float(p[2])
    elif kind in ("CL", "CR"):
        seg.kind = 'CURVE'; seg.curve_direction = 'LEFT' if kind == "CL" else 'RIGHT'; seg.curve_angle_deg = int(p[1])
    elif kind == "SP":
        seg.kind = 'SPIRAL'; seg.spiral_turns = float(p[1]); seg["rise_mm"] = float(p[2]); seg.curve_direction = p[3]
    elif kind == "M":
        seg.kind = 'MODULE'; seg.module_kind = p[1]
        for k, v in (p[2] if len(p) > 2 else {}).items():
            if k in ("length_mm", "rise_mm", "buffer_out_pct"):
                seg[k] = v
            else:
                setattr(seg, k, v)


def settle(n=4):
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj

    for _ in range(n):
        bpy.context.view_layer.update()
        dj.run_sync(bpy.context.scene)
    bpy.context.view_layer.update()


def branch(main, piece_index, side="LEFT", pieces=(("S", 3000),)):
    """A line docked on a junction face of `main` (a diverter's branch or a merge's feeder), then extended."""
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line

    before = set(bpy.data.objects)
    bpy.ops.conveyor.new_line_at_junction(line_name=main.name, index=piece_index, side=side)
    new = [o for o in bpy.data.objects if o not in before]
    o = bpy.context.view_layer.objects.active if not new else new[0]
    s = o.conveyor_line
    for p in pieces:
        add_piece(s.segments.add(), p)
    build_line(bpy.context, o)
    settle()
    return o


def box(name, size, loc, color, roughness=0.6, rot_z=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    o = bpy.context.view_layer.objects.active
    o.name, o.scale = name, size
    o.rotation_euler.z = math.radians(rot_z)
    o.data.materials.append(_principled(name, color, roughness=roughness))
    return o


def footprint(obj, indices, pad=0.2):
    """World plan rectangle (x0, y0, x1, y1) of pieces `indices` of a line: their centreline, widened by
    half the line's width plus `pad` (rails, a lift's column ...)."""
    from bl_ext.user_default.conveyor_system.operators.build_line import evaluate_line

    spine, _segs, width = evaluate_line(bpy.context, obj)
    mw = obj.matrix_world
    pts = [mw @ Vector((spine.x[k], spine.y[k], spine.z[k])) for k in range(len(spine)) if spine.segment_index[k] in indices]
    r = width / 2 + pad
    return (min(p.x for p in pts) - r, min(p.y for p in pts) - r, max(p.x for p in pts) + r, max(p.y for p in pts) + r)


def slab_avoiding(name, obj, indices, avoid=(), margin=1.3, legs=0.8, gap=0.2):
    """A mezzanine under pieces `indices` of a line, cut back along the run so it keeps clear of the
    `avoid` rectangles (a spiral, a lift column): the spiral stands beside the floor and ends on it
    instead of going through it. The floor's level is where the first piece starts (a lift among the
    pieces stands on it and climbs away)."""
    from bl_ext.user_default.conveyor_system.operators.build_line import segment_frames_for

    lo, hi = run_box(obj, indices)
    first = segment_frames_for(bpy.context, obj)[indices[0]][0]
    top = (obj.matrix_world @ Vector((first.x, first.y, first.z))).z - legs
    x0, y0, x1, y1 = lo.x - margin, lo.y - margin, hi.x + margin, hi.y + margin
    along_x = abs(hi.x - lo.x) >= abs(hi.y - lo.y)
    for ax0, ay0, ax1, ay1 in avoid:
        if ax1 + gap <= x0 or ax0 - gap >= x1 or ay1 + gap <= y0 or ay0 - gap >= y1:
            continue
        if along_x:  # keep the larger side of the run
            x0, x1 = (ax1 + gap, x1) if x1 - (ax1 + gap) >= (ax0 - gap) - x0 else (x0, ax0 - gap)
        else:
            y0, y1 = (ay1 + gap, y1) if y1 - (ay1 + gap) >= (ay0 - gap) - y0 else (y0, ay0 - gap)
    return mezzanine(name, ((x0 + x1) / 2, (y0 + y1) / 2), (x1 - x0, y1 - y0), top), top


def mezzanine(name, centre, size, top_z, columns=True):
    """A slab with columns: the legs of lines above land on it (any mesh below is a floor)."""
    slab = box(name, (size[0], size[1], 0.25), (centre[0], centre[1], top_z - 0.125), (0.80, 0.81, 0.83), roughness=0.7)
    mat = slab.data.materials[0]
    if columns:
        for sx in (-1, 1):
            for sy in (-1, 1):
                h = top_z - 0.25
                bpy.ops.mesh.primitive_cylinder_add(radius=0.14, depth=h, location=(centre[0] + sx * (size[0] / 2 - 0.4), centre[1] + sy * (size[1] / 2 - 0.4), h / 2))
                c = bpy.context.view_layer.objects.active
                c.name = f"{name} column"
                c.data.materials.append(mat)
    return slab


# ---------------------------------------------------------------- cameras
def camera(name, loc, target, lens=40.0, ortho=None):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.clip_end = 1000.0
    if ortho:
        cd.type = 'ORTHO'
        cd.ortho_scale = ortho
    cam = bpy.data.objects.new(name, cd)
    bpy.context.scene.collection.objects.link(cam)
    aim(cam, loc, target)
    bpy.context.scene.camera = cam
    return cam


def aim(cam, loc, target):
    cam.location = Vector(loc)
    d = Vector(target) - Vector(loc)
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()


def bounds(objs):
    """(lo, hi) world corners of the objects' evaluated geometry (meshes and instances)."""
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in objs:
        geo = o.evaluated_get(dg).evaluated_geometry()
        if geo.mesh is not None:
            mw = o.matrix_world
            vs = geo.mesh.vertices
            pts += [mw @ vs[i].co for i in range(0, len(vs), 3)]
        elif o.type == 'MESH':
            pts += [o.matrix_world @ Vector(c) for c in o.bound_box]
        for inst in dg.object_instances:
            if inst.is_instance and inst.parent and inst.parent.original == o:
                pts.append(inst.matrix_world.translation.copy())
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


CARD_SHIFT = 0.17  # lens shift that leaves the right third of the frame for a panel card


def card_space(cam):
    """The content to the left two thirds, the right third free for the edit's panel card."""
    cam.data.shift_x = CARD_SHIFT


def fit_top(cam, objs, margin=1.18, offset=(0.0, 0.0), card=False, band=(0.0, 1.0), extra=()):
    """An orthographic top camera that shows the objects whole (16:9), shifted by `offset` metres
    (with `card`, whole within the left two thirds; `band`, the bottom and top of the frame height
    they may use, leaves room for the edit's captions; `extra`: (x, y) points to include too, a line
    still to come)."""
    lo, hi = bounds(objs)
    for x, y in extra:
        lo.x, lo.y, hi.x, hi.y = min(lo.x, x), min(lo.y, y), max(hi.x, x), max(hi.y, y)
    c = (lo + hi) / 2
    w, h = hi.x - lo.x, hi.y - lo.y
    cam.data.type = 'ORTHO'
    usable = (1.0 - 2.0 * CARD_SHIFT) if card else 1.0
    cam.data.ortho_scale = max(w / usable, h * 16.0 / 9.0 / (band[1] - band[0])) * margin
    if card:
        card_space(cam)
    up = ((band[0] + band[1]) / 2 - 0.5) * cam.data.ortho_scale * 9.0 / 16.0  # the band's centre above the frame's
    cam.location = (c.x + offset[0], c.y + offset[1] - up, 50.0)
    cam.rotation_euler = (0.0, 0.0, 0.0)


def fit_view(cam, objs, direction, margin=1.08, lens=None, lift=0.0, objs_lo_hi=None):
    """Places a perspective camera on the line from the objects' centre along `direction` (towards
    the camera) at the distance where their bounding sphere fills the frame."""
    lo, hi = objs_lo_hi or bounds(objs)
    c = (lo + hi) / 2 + Vector((0.0, 0.0, lift))
    r = (hi - lo).length / 2
    if lens:
        cam.data.lens = lens
    hfov = 2 * math.atan(cam.data.sensor_width / 2 / cam.data.lens)
    vfov = 2 * math.atan(math.tan(hfov / 2) * 9.0 / 16.0)
    d = r / math.sin(vfov / 2) * margin
    aim(cam, c + Vector(direction).normalized() * d, c)
    return c, d


# where the content may go (u0, u1, v0, v1: fractions of the frame from the bottom-left): below
# the edit's caption (top left), and with a panel card also left of it
RECT_FULL = (0.04, 0.96, 0.06, 0.69)
RECT_CARD = (0.04, 0.63, 0.06, 0.69)


def points(objs):
    """World positions of the objects' evaluated vertices and instances, as an (n, 3) array."""
    dg = bpy.context.evaluated_depsgraph_get()
    out = []
    for o in objs:
        geo = o.evaluated_get(dg).evaluated_geometry()
        if geo.mesh is not None and len(geo.mesh.vertices):
            co = np.empty(len(geo.mesh.vertices) * 3, np.float64)
            geo.mesh.vertices.foreach_get("co", co)
            m = np.array(o.matrix_world)
            out.append(co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3])
        elif o.type == 'MESH':
            out.append(np.array([tuple(o.matrix_world @ Vector(c)) for c in o.bound_box]))
    owners = {o.name for o in objs}
    inst = [tuple(i.matrix_world.translation) for i in dg.object_instances
            if i.is_instance and i.parent and i.parent.original.name in owners]
    if inst:
        out.append(np.array(inst))
    return np.concatenate(out)


def box_points(lo, hi):
    return np.array([(x, y, z) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)])


def project(cam, pts):
    """(u, v) frame fractions of world points for the camera as posed now, without lens shift."""
    sx, sy = cam.data.shift_x, cam.data.shift_y
    cam.data.shift_x = cam.data.shift_y = 0.0
    vf = cam.data.view_frame(scene=bpy.context.scene)
    cam.data.shift_x, cam.data.shift_y = sx, sy
    inv = np.array(Matrix.LocRotScale(cam.location, cam.rotation_euler, cam.scale).inverted())
    pc = pts @ inv[:3, :3].T + inv[:3, 3]
    if cam.data.type == 'ORTHO':
        x, y = pc[:, 0], pc[:, 1]
        xs, ys = [c.x for c in vf], [c.y for c in vf]
    else:
        z = np.maximum(-pc[:, 2], 1e-3)
        x, y = pc[:, 0] / z, pc[:, 1] / z
        xs, ys = [c.x / -c.z for c in vf], [c.y / -c.z for c in vf]
    return (x - min(xs)) / (max(xs) - min(xs)), (y - min(ys)) / (max(ys) - min(ys))


def frame_in(cam, pts, rect, place, samples=(1,)):
    """The distance factor k for which `place(k, f)` (which poses the camera at frame f, k times
    as far) shows `pts` inside `rect` at every sampled frame, once centred with centre_in."""
    k = 1.0
    for _ in range(6):
        worst = 0.0
        for f in samples:
            place(k, f)
            u, v = project(cam, pts)
            worst = max(worst, (u.max() - u.min()) / (rect[1] - rect[0]), (v.max() - v.min()) / (rect[3] - rect[2]))
        k *= worst
    return k


def centre_in(cam, pts, rect):
    """Lens shift that centres the points' extent in `rect` (the shift moves the image, not the view)."""
    u, v = project(cam, pts)
    aspect = bpy.context.scene.render.resolution_y / bpy.context.scene.render.resolution_x
    cam.data.shift_x = (u.min() + u.max()) / 2 - (rect[0] + rect[1]) / 2
    cam.data.shift_y = ((v.min() + v.max()) / 2 - (rect[2] + rect[3]) / 2) * aspect


def move(cam, f, first, last, a, b):
    """Eases the camera from pose a to pose b ((location, target) each) over frames first..last."""
    u = ease((f - first) / max(last - first, 1))
    loc = Vector(a[0]).lerp(Vector(b[0]), u)
    tgt = Vector(a[1]).lerp(Vector(b[1]), u)
    aim(cam, loc, tgt)


def orbit(cam, f, first, last, centre, radius, height, deg_from, deg_to, lift=0.0):
    """Orbits the camera around `centre` (degrees about Z, eased) at `radius` and `height` above it."""
    u = ease((f - first) / max(last - first, 1))
    a = math.radians(deg_from + (deg_to - deg_from) * u)
    c = Vector(centre)
    aim(cam, c + Vector((math.cos(a) * radius, math.sin(a) * radius, height)), c + Vector((0.0, 0.0, lift)))


# orthographic shots (Åsmund, 2026-10-25): the camera stands far out along its view direction and the
# framing's size factor k is the ortho scale (10 m per unit)
FAR = 120.0
ORTHO_UNIT = 10.0


def ortho_view(cam, centre, direction, k, zoom=1.0):
    """An orthographic camera looking at `centre` from `direction`, showing k x 10 m (x zoom)."""
    c = Vector(centre)
    aim(cam, c + Vector(direction).normalized() * FAR, c)
    cam.data.type = 'ORTHO'
    cam.data.ortho_scale = ORTHO_UNIT * k * zoom


def ortho_orbit(cam, f, first, last, centre, k, elevation, deg_from, deg_to, lift=0.0):
    """orbit() for an orthographic camera: `elevation` is height over horizontal distance."""
    orbit(cam, f, first, last, centre, FAR, FAR * elevation, deg_from, deg_to, lift)
    cam.data.type = 'ORTHO'
    cam.data.ortho_scale = ORTHO_UNIT * k


def run_box(obj, indices):
    """(lo, hi) world corners of pieces `indices` of a line, from their start and end poses."""
    from bl_ext.user_default.conveyor_system.operators.build_line import segment_frames_for

    frames = segment_frames_for(bpy.context, obj)
    mw = obj.matrix_world
    pts = []
    for i in indices:
        a, b = frames[i]
        pts += [mw @ Vector((a.x, a.y, a.z)), mw @ Vector((b.x, b.y, b.z))]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def slab_under(name, obj, indices, margin=1.3, legs=0.8):
    """A mezzanine slab under pieces `indices` of a line, its top `legs` metres under the bed."""
    lo, hi = run_box(obj, indices)
    top = (lo.z + hi.z) / 2 - legs
    centre = ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2)
    size = (hi.x - lo.x + 2 * margin, hi.y - lo.y + 2 * margin)
    return mezzanine(name, centre, size, top), top


def ease(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- rendering
def render(out_dir, first, last, per_frame=None, step=1):
    """Renders frames first..last (scene frames) to out_dir/f_0001.png ..., calling per_frame(f) before each.
    Shared with another render (2026-10-25): when the file PROMO_STOP_FILE names exists it stops
    after the frame in hand; with PROMO_RESUME set a frame already on disk is kept, so a stopped shot
    carries on where it stopped (per_frame still runs for every frame: a shot's state follows the frame).
    PROMO_REST (a ratio) rests that many times a frame's render time after it, so the shared GPU gets
    its share back (1.0 = 50 % duty). Returns (frames written or kept, whether every frame is there)."""
    sc = bpy.context.scene
    os.makedirs(out_dir, exist_ok=True)
    stop, resume = os.environ.get("PROMO_STOP_FILE", ""), bool(os.environ.get("PROMO_RESUME"))
    rest = float(os.environ.get("PROMO_REST", "0") or 0)
    frames = list(range(first, last + 1, step))
    n = 0
    for f in frames:
        if stop and os.path.exists(stop):
            print("RENDER stopped before frame", f)
            return n, False
        if per_frame is not None:
            per_frame(f)
        sc.frame_set(f)
        n += 1
        sc.render.filepath = os.path.join(out_dir, f"f_{n:04d}.png")
        if resume and os.path.exists(sc.render.filepath):
            continue
        t0 = time.monotonic()
        bpy.ops.render.render(write_still=True)
        if rest > 0:
            time.sleep((time.monotonic() - t0) * rest)
    return n, True
