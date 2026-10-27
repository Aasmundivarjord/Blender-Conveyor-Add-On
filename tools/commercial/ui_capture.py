"""The real Conveyor panel, captured as cards for the promo edit: the sidebar of a windowed Blender
(UI scale 1.3, the default dark theme) in the states the features need, cropped to the sidebar and
framed with rounded corners and a soft shadow. Not shipped. A short windowed run, scratch config only:
  TMPDIR=<cfg>/tmp BLENDER_USER_EXTENSIONS=<ext> BLENDER_USER_CONFIG=<cfg> Blender --factory-startup \
    -p 0 0 1728 1080 --python tools/commercial/ui_capture.py -- <out dir>
Writes <out>/panel_<state>.png (the sidebar) and <out>/card_<state>.png (framed)."""
import inspect, math, os, sys, traceback
import bpy
import numpy as np
from mathutils import Vector

_CONFIG = os.environ.get("BLENDER_USER_CONFIG", "")
if not _CONFIG or not os.path.isdir(_CONFIG) or "Application Support/Blender" in _CONFIG:
    print("UI refused: run with a scratch BLENDER_USER_CONFIG (never the user's own)")
    os._exit(2)
SCRATCH_TMP = os.path.join(_CONFIG, "tmp")
os.makedirs(SCRATCH_TMP, exist_ok=True)
prefs = bpy.context.preferences
prefs.filepaths.temporary_directory = SCRATCH_TMP
prefs.use_preferences_save = False
prefs.view.show_splash = False
prefs.view.ui_scale = 1.3
prefs.system.use_region_overlap = False  # an opaque sidebar: no viewport lines through the panel
OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else os.getcwd()
os.makedirs(OUT, exist_ok=True)
PKG = "bl_ext.user_default.conveyor_system"
S = {"errors": []}
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def log(*a):
    print("UI", " ".join(str(x) for x in a))
    sys.stdout.flush()


def view3d():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == 'VIEW_3D':
            regions = {r.type: r for r in area.regions}
            return win, area, regions.get('WINDOW'), regions.get('UI')
    return win, None, None, None


def settle():
    win = view3d()[0]
    for area in win.screen.areas:
        area.tag_redraw()
    return 0.6


def tab():
    ui = view3d()[3]
    try:
        ui.active_panel_category = "Conveyor"
    except Exception:
        pass


def activate(obj, piece=None):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if piece is not None:
        obj.conveyor_line.active_segment_index = piece


def grab(name, top=0, bottom=None, right=650, left=10):
    """The sidebar region of the window as panel_<name>.png, and rows top..bottom (pixels from the
    panel's top) x 0..right (the tab strip trimmed) as a framed card_<name>.png."""
    win, area, region, ui = view3d()
    path = os.path.join(OUT, f"_window_{name}.png")
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)
    with bpy.context.temp_override(window=win, screen=win.screen):
        bpy.ops.screen.screenshot(filepath=path)
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)  # bottom-up rows
    bpy.data.images.remove(img)
    os.remove(path)
    # the sidebar's rectangle in window pixels (the screenshot is the window at its pixel size)
    sx = 1.0 if ui.x + ui.width <= w else w / win.width  # region coordinates are window pixels (Retina: physical)
    x0, y0 = int(ui.x * sx), int(ui.y * sx)
    x1, y1 = int((ui.x + ui.width) * sx), int((ui.y + ui.height) * sx)
    log("sizes", dict(shot=(w, h), win=(win.width, win.height), ui=(ui.x, ui.y, ui.width, ui.height), area=(area.x, area.y, area.width, area.height)))
    if x1 - x0 < 10 or y1 - y0 < 10:  # region coordinates relative to the area on this build
        x0, y0 = int((area.x + ui.x) * sx), int((area.y + ui.y) * sx)
        x1, y1 = x0 + int(ui.width * sx), y0 + int(ui.height * sx)
    crop = np.ascontiguousarray(px[max(y0, 0):min(y1, h), max(x0, 0):min(x1, w)])
    save(crop, os.path.join(OUT, f"panel_{name}.png"))
    ch = crop.shape[0]
    bottom = ch if bottom is None else min(bottom, ch)
    section = np.ascontiguousarray(crop[ch - bottom:ch - top, left:right])  # rows are bottom-up
    save(card(section), os.path.join(OUT, f"card_{name}.png"))
    log("grabbed", name, crop.shape[1], "x", crop.shape[0])


def save(px, path):
    h, w = px.shape[:2]
    img = bpy.data.images.new("tmp", w, h, alpha=True)
    img.pixels.foreach_set(np.ascontiguousarray(px, dtype=np.float32).ravel())
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


def card(px, radius=26, pad=48):
    """Rounded corners and a soft shadow around an RGBA panel (bottom-up rows)."""
    h, w = px.shape[:2]
    W, H = w + 2 * pad, h + 2 * pad
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32) + 0.5

    def rrect(cx, cy, hw, hh, r):
        qx = np.abs(xx - cx) - (hw - r)
        qy = np.abs(yy - cy) - (hh - r)
        return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r

    out = np.zeros((H, W, 4), np.float32)
    sd = rrect(W / 2, H / 2 - 12, w / 2, h / 2, radius)  # bottom-up: the shadow drops downwards
    out[..., 3] = np.clip(1 - (sd + 2) / 34.0, 0, 1) ** 2 * 0.5
    inside = np.clip(0.5 - rrect(W / 2, H / 2, w / 2, h / 2, radius), 0, 1)[pad:pad + h, pad:pad + w][..., None]
    region = out[pad:pad + h, pad:pad + w]
    region[..., :3] = px[..., :3] * inside + region[..., :3] * (1 - inside)
    region[..., 3:4] = inside + region[..., 3:4] * (1 - inside)
    out[pad:pad + h, pad:pad + w] = region
    return out


STEPS = []
ROW = 58  # the Build with Arrow Keys row under the piece keys (2.26), at UI scale 1.3 on Retina


def step(fn):
    STEPS.append(fn)
    return fn


@step
def s_setup():
    if PKG not in prefs.addons:
        bpy.ops.preferences.addon_enable(module=PKG)
    import studio as st

    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    win, area, region, ui = view3d()
    area.spaces.active.show_region_ui = True
    S["main"] = st.line("Main line", (0.0, 0.0, 0.8), 0,
                        (("S", 3000), ("CR", 90), ("S", 3000), ("M", "DIVERTER", {"merge_angle": '45'}), ("S", 3000),
                         ("SP", 2.0, 3000.0, "RIGHT"), ("S", 3000)), population=55.0)  # the floors shot's spiral
    st.branch(S["main"], 3, "LEFT", (("S", 3000),))
    tab()
    yield settle()


@step
def s_build():
    """The panel as it is while the arrow keys build (build mode on the line: its button lit)."""
    from bl_ext.user_default.conveyor_system.operators import build_mode

    activate(S["main"], 6)
    build_mode.RUNNING["line"] = S["main"].name
    tab()
    yield settle()
    grab("build", 0, 700 + ROW)
    build_mode.RUNNING["line"] = ""


@step
def s_diverter():
    activate(S["main"], 3)
    tab()
    yield settle()
    grab("diverter", 1110 + ROW, 1620 + ROW)


@step
def s_spiral():
    activate(S["main"], 5)
    tab()
    yield settle()
    grab("spiral", 0, 700 + ROW)


@step
def s_populate():
    import goods as gd

    S["main"].conveyor_line.populate_item = gd.tote()  # the header names the item the line carries: "Tote"
    activate(S["main"], 6)
    tab()
    yield settle()
    grab("populate", 1360 + ROW, 1588 + ROW)


@step
def s_quit():
    log("RESULT", "DONE", S["errors"])
    if os.path.realpath(prefs.filepaths.temporary_directory).startswith(os.path.realpath(SCRATCH_TMP)):
        bpy.ops.wm.quit_blender()
    else:
        os._exit(0)


RUN = {"gen": None, "name": ""}


def run_next():
    if RUN["gen"] is not None:
        try:
            return max(float(next(RUN["gen"]) or 0.0), 0.01)
        except StopIteration:
            RUN["gen"] = None
        except Exception:
            RUN["gen"] = None
            S["errors"].append(RUN["name"])
            log("ERROR in", RUN["name"], traceback.format_exc())
        return 0.3
    if not STEPS:
        return None
    fn = STEPS.pop(0)
    try:
        r = fn()
        if inspect.isgenerator(r):
            RUN["gen"], RUN["name"] = r, fn.__name__
            return 0.01
    except Exception:
        S["errors"].append(fn.__name__)
        log("ERROR in", fn.__name__, traceback.format_exc())
    return 0.3


bpy.app.timers.register(run_next, first_interval=1.5)
