"""The featured image for extensions.blender.org, from the scene tools/showcase_capture.py saved
(<TMPDIR>/showcase_scene.blend). Not shipped in the zip.

  TMPDIR=<cfg>/tmp BLENDER_USER_EXTENSIONS=<ext> BLENDER_USER_CONFIG=<cfg> Blender --factory-startup \
    -p 0 0 1728 972 --python tools/featured_shots.py -- <out dir> ring|final [heading tilt dist lens]

ring:  eight headings around the spiral and the main line, small (960 x 540), Material Preview.
final: one 1920 x 1080 shot at the given heading / tilt / distance factor / lens (Material Preview;
       `eevee` as a third word renders with EEVEE instead -- GPU work, only when the machine is free).
"""
import math, os, sys, traceback
import bpy
from mathutils import Euler, Vector

_CONFIG = os.environ.get("BLENDER_USER_CONFIG", "")
if not _CONFIG or not os.path.isdir(_CONFIG) or "Application Support/Blender" in _CONFIG:
    print("FEATURED refused: run with a scratch BLENDER_USER_CONFIG (never the user's own)")
    os._exit(2)
SCRATCH_TMP = os.path.join(_CONFIG, "tmp")
os.makedirs(SCRATCH_TMP, exist_ok=True)
bpy.context.preferences.filepaths.temporary_directory = SCRATCH_TMP
bpy.context.preferences.use_preferences_save = False
bpy.context.preferences.view.show_splash = False
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT, MODE = ARGS[0], (ARGS[1] if len(ARGS) > 1 else "ring")
PARAMS = [float(a) for a in ARGS[2:6]] if MODE == "final" and len(ARGS) >= 6 else None
EEVEE = "eevee" in ARGS[6:]
FOCUS = os.environ.get("FOCUS", "spiral")  # spiral: the spiral and its mezzanine in front; all: every line
HDRI = os.environ.get("HDRI", "city.exr")
SCENE = os.path.join(os.environ.get("TMPDIR") or SCRATCH_TMP, "showcase_scene.blend")
os.makedirs(OUT, exist_ok=True)


def log(*a):
    print("FEATURED", " ".join(str(x) for x in a))
    sys.stdout.flush()


def view3d():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == 'VIEW_3D':
            return win, area, next(r for r in area.regions if r.type == 'WINDOW')
    return win, None, None


def bounds(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in objs:
        geo = o.evaluated_get(dg).evaluated_geometry()
        if geo.mesh is not None:
            mw = o.matrix_world
            vs = geo.mesh.vertices
            pts += [mw @ vs[i].co for i in range(0, len(vs), 5)]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return (lo + hi) / 2, (hi - lo).length


def look(sc, area):
    """Concrete floor, a studio HDRI, nothing selected or active, no overlays or gizmos."""
    floor = bpy.data.objects.get("Floor")
    if floor is not None and floor.data.materials:
        mat = floor.data.materials[0]
        mat.diffuse_color = (0.12, 0.125, 0.13, 1.0)
        bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if mat.use_nodes else None
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (0.09, 0.095, 0.10, 1.0)  # dark concrete: the line and the goods stand out
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = None
    space = area.spaces.active
    space.shading.type = 'MATERIAL'
    space.shading.use_scene_world = False
    try:
        space.shading.studio_light = HDRI
    except TypeError:
        pass
    space.shading.studiolight_rotate_z = math.radians(110)
    space.shading.studiolight_intensity = 1.1
    space.shading.studiolight_background_alpha = 0.0
    space.overlay.show_overlays = False
    space.show_gizmo = False
    space.show_region_ui = False
    from bl_ext.user_default.conveyor_system.operators import detect_junctions as dj

    bpy.context.view_layer.update()
    dj.run_sync(sc)  # the active-piece band goes with the active object


def shoot(sc, win, area, region, cam, target, size, heading, tilt, dist, lens, path, percent):
    cam.data.lens = lens
    rot = Euler((math.radians(tilt), 0.0, math.radians(heading)))
    cam.rotation_euler = rot
    cam.location = target + rot.to_matrix() @ Vector((0.0, 0.0, size * dist))
    sc.render.resolution_percentage = percent
    sc.render.filepath = path
    bpy.context.view_layer.update()
    if EEVEE:
        sc.render.engine = 'BLENDER_EEVEE'
        bpy.ops.render.render(write_still=True)
    else:
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.render.opengl(write_still=True, view_context=True)
    log("shot", os.path.basename(path), dict(heading=heading, tilt=tilt, dist=dist, lens=lens))


def run():
    try:
        if "bl_ext.user_default.conveyor_system" not in bpy.context.preferences.addons:
            bpy.ops.preferences.addon_enable(module="bl_ext.user_default.conveyor_system")
        bpy.ops.wm.open_mainfile(filepath=SCENE)
        bpy.app.timers.register(after_open, first_interval=1.0)
    except Exception:
        log("ERROR open", traceback.format_exc())
        quit_()
    return None


def after_open():
    try:
        sc = bpy.context.scene
        win, area, region = view3d()
        look(sc, area)
        cam = sc.camera or bpy.data.objects.new("Showcase camera", bpy.data.cameras.new("Showcase camera"))
        if cam.name not in sc.collection.objects:
            sc.collection.objects.link(cam)
        sc.camera = cam
        area.spaces.active.region_3d.view_perspective = 'CAMERA'
        sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
        sc.render.image_settings.file_format = 'PNG'
        sc.frame_set(600)  # goods everywhere, the buffer holding its queue
        names = ("Spiral line", "Mezzanine") if FOCUS == "spiral" else ("Spiral line", "Main line", "Mezzanine")
        focus = [o for o in (bpy.data.objects.get(n) for n in names) if o]
        target, size = bounds(focus)
        log("target", tuple(round(v, 2) for v in target), "size", round(size, 2))
        if MODE == "ring":
            for heading in range(-90, 46, 15):
                shoot(sc, win, area, region, cam, target, size, heading, 60, 1.05, 35,
                      os.path.join(OUT, f"ring_{heading + 90:03d}.png"), 50)
        else:
            heading, tilt, dist, lens = PARAMS
            shoot(sc, win, area, region, cam, target, size, heading, tilt, dist, lens, os.path.join(OUT, "featured.png"), 100)
    except Exception:
        log("ERROR", traceback.format_exc())
    quit_()
    return None


def quit_():
    tmp_base = bpy.context.preferences.filepaths.temporary_directory
    if os.path.realpath(tmp_base).startswith(os.path.realpath(SCRATCH_TMP)):
        bpy.ops.wm.quit_blender()
    else:
        os._exit(0)


bpy.app.timers.register(run, first_interval=1.5, persistent=True)
