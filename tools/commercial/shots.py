"""The promo's 3D shots, rendered frame by frame (EEVEE; Cycles on the CPU for layout checks).
Not shipped in the zip.

  Blender -b --factory-startup --python tools/commercial/shots.py -- <shot> <out dir> <mode> [first last step]

mode: final (EEVEE 1920 x 1080) | eevee_test (EEVEE 480 x 270) | cpu (Cycles CPU 480 x 270).
Each shot writes its frames to <out>/<shot>/f_0001.png ... and a sidecar <out>/<shot>.json with the
timings the edit needs (which key was pressed when, where the cursor should be). Every line carries
real goods (tools/commercial/goods.py) through the add-on's own Pick."""
import json, math, os, sys
import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # this tools folder only, for studio.py
import environment as env  # noqa: E402
import goods as gd  # noqa: E402
import studio as st  # noqa: E402
from bpy_extras.object_utils import world_to_camera_view  # noqa: E402

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SHOT, OUT, MODE = ARGS[0], ARGS[1], (ARGS[2] if len(ARGS) > 2 else "cpu")
RANGE = [int(a) for a in ARGS[3:6]] if len(ARGS) >= 6 else None
SHOTS = {}


def shot(fn):
    SHOTS[fn.__name__] = fn
    return fn


def label(text, loc, size=0.5, rot_z=0.0, color=(0.05, 0.06, 0.08)):
    """A flat text label on the floor plane (a CAD-style dimension in the render)."""
    cu = bpy.data.curves.new(f"Label {text}", 'FONT')
    cu.body = text
    cu.size = size
    cu.align_x, cu.align_y = 'CENTER', 'CENTER'
    o = bpy.data.objects.new(f"Label {text}", cu)
    bpy.context.scene.collection.objects.link(o)
    o.location = loc
    o.rotation_euler.z = rot_z
    o.data.materials.append(st._principled("Promo label", color, roughness=0.9))
    return o


def screen_xy(cam, world):
    v = world_to_camera_view(bpy.context.scene, cam, Vector(world))
    return [round(v.x, 4), round(v.y, 4)]


def setup(**kw):
    """The studio, its floor a concrete warehouse floor."""
    st.studio(MODE, **kw)
    env.concrete_floor(bpy.data.objects["Studio floor"])


def put(obj, loc, rot_z_deg=0.0):
    """A goods source brought into view (it stays what the lines instance)."""
    obj.location = loc
    obj.rotation_euler.z = math.radians(rot_z_deg)
    return obj


def copy_of(src, name, loc, rot_z_deg=0.0):
    """A linked duplicate (the same mesh): rack pallets, a bin on a table."""
    o = bpy.data.objects.new(name, src.data)
    bpy.context.scene.collection.objects.link(o)
    return put(o, loc, rot_z_deg)


def end_pose(line, index=-1):
    """World end point and heading vector of piece `index` of a line."""
    from bl_ext.user_default.conveyor_system.operators.build_line import segment_frames_for

    _a, b = segment_frames_for(bpy.context, line)[index]
    mw = line.matrix_world
    h = b.heading + line.rotation_euler.z
    return mw @ Vector((b.x, b.y, b.z)), Vector((-math.sin(h), math.cos(h), 0.0))  # heading 0 travels +Y


# ---------------------------------------------------------------- look test: the goods
@shot
def look():
    """The goods in the studio: a bin, a tote, a carton, a letter, a pallet load, and a line of bins."""
    setup()
    put(gd.bin_(), (-2.0, -2.0, 0.0), 20)
    put(gd.tote(), (-1.1, -2.6, 0.0), -10)
    put(gd.carton(), (-0.2, -2.2, 0.0), 30)
    put(gd.envelope(), (0.5, -2.8, 0.0), -25)
    put(gd.pallet_load(), (1.6, -1.6, 0.0), 10)
    st.line("Line", (-3.5, 0.5, 0.8), -90.0, (("S", 3000), ("S", 3000)), population=60.0, item=gd.bin_("Bin on line"))
    st.colour_frames()
    cam = st.camera("Cam", (0, 0, 0), (0, 0, 0), ortho=10.0)
    st.ortho_view(cam, (-0.6, -1.0, 0.5), (0.4, -1.0, 0.55), 0.85)
    return 1, 1, None, {}


# ---------------------------------------------------------------- build: top view, the line grows
@shot
def build():
    """Top view: New Line, then a piece every half second -- the arrow keys for straights and curves, More
    for a right-angle transfer and a spiral (a loop from above); lengths appear CAD style. Then a second
    line is drawn towards the first and snaps on: a merge appears where it docks."""
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line, segment_frames_for

    setup(sun_rot=(35.0, 0.0, 150.0))
    plan = [("S", 3000, "up"), ("S", 3000, "up"), ("M", "RAT", {"module_exit": 'LEFT'}, "down:RAT"), ("S", 1500, "up"),
            ("CR", 90, "right"), ("S", 3000, "up"), ("SP", 1.0, 1500.0, "RIGHT", "down:Spiral"), ("S", 3000, "up"),
            ("S", 3000, "up"), ("M", "RAT", {"module_exit": 'RIGHT'}, "down:RAT"), ("S", 1500, "up")]  # wide and shallow
    feed_at, feed_plan = (4.5, -3.6), [("S", 1500, "up"), ("S", 1650, "up")]  # ends 0.45 m short of the main line
    bins = gd.bin_()
    # 60 % + a 15 % feeder: the main keeps goods upstream of the merge (a heavier feeder empties it there,
    # a stream bug reported 2026-10-25, to be fixed in its own release)
    o = st.line("Line", (0.0, 0.0, 0.8), -90.0, tuple(p[:-1] for p in plan), population=60.0, item=bins)
    st.colour_frames()
    cam = st.camera("Top", (0.0, 0.0, 50.0), (0.0, 0.0, 0.0), ortho=20.0)
    # the finished layout, whole, left of the panel card, between the caption (top) and the keys (bottom)
    st.fit_top(cam, [o], margin=1.1, card=True, band=(0.2, 0.7),
               extra=[(feed_at[0] - 0.4, feed_at[1] - 0.3), (feed_at[0] + 0.4, feed_at[1])])
    s = o.conveyor_line
    while len(s.segments) > 1:
        s.segments.remove(len(s.segments) - 1)
    build_line(bpy.context, o)
    o.hide_render = True  # until New Line is clicked
    first_add, every, new2 = 24, 15, 176
    events = [[8, "new"]] + [[first_add + i * every, p[-1]] for i, p in enumerate(plan[1:])]
    events += [[new2, "new"], [new2 + 16, feed_plan[1][-1]]]
    labels = []
    state = {"n": 1, "feed": None, "fn": 0}
    snap = []

    def dims():
        for lb in labels:
            bpy.data.objects.remove(lb)
        labels.clear()
        placed = []
        for line in (o, state["feed"]):
            if line is None:
                continue
            mw = line.matrix_world
            for seg, (a, b) in zip(line.conveyor_line.segments, segment_frames_for(bpy.context, line)):
                if seg.kind != 'STRAIGHT':
                    continue
                pa, pb = mw @ Vector((a.x, a.y, 0.0)), mw @ Vector((b.x, b.y, 0.0))
                mid = (pa + pb) / 2
                d = (pb - pa).normalized()
                side = Vector((-d.y, d.x, 0.0)) * 0.95
                if any((mid + side - q).length < 1.3 for q in placed):  # another label there: the other side
                    side = -side
                placed.append(mid + side)
                rot = math.atan2(d.y, d.x)
                if abs(rot) > math.pi / 2:
                    rot += math.pi
                labels.append(label(f"{seg.length_mm / 1000:.2f} m", (mid.x + side.x, mid.y + side.y, 0.02), rot_z=rot))

    dims()

    def per_frame(f):
        o.hide_render = f < 8
        want = 1 + sum(1 for i in range(len(plan) - 1) if f >= first_add + i * every)
        changed = False
        if want != state["n"]:
            for p in plan[state["n"]:want]:
                st.add_piece(o.conveyor_line.segments.add(), p[:-1])
            state["n"] = want
            build_line(bpy.context, o)
            changed = True
        fwant = 0 if f < new2 else (1 if f < new2 + 16 else 2)
        if fwant != state["fn"]:
            if state["feed"] is None:
                state["feed"] = st.line("Feeder", (feed_at[0], feed_at[1], 0.8), 0.0, (feed_plan[0][:-1],),
                                        population=15.0, item=bins)
            for p in feed_plan[state["fn"] if state["fn"] else 1:fwant]:
                st.add_piece(state["feed"].conveyor_line.segments.add(), p[:-1])
            state["fn"] = fwant
            build_line(bpy.context, state["feed"])
            st.settle()  # its end now points at the main line: it docks, a merge goes in
            if fwant == 2:
                bpy.context.view_layer.update()
                snap.extend([f] + screen_xy(cam, end_pose(state["feed"])[0]))
            changed = True
        if changed:
            st.colour_frames()
            dims()

    return 1, 270, per_frame, {"keys": events, "snap": snap, "fps": 30}


# ---------------------------------------------------------------- height: drag the arrow, the line climbs
@shot
def height():
    """Three-quarter view: the middle straight climbs 1.2 m, nose-overs appear, the cartons ride up."""
    setup()
    o = st.line("Line", (0.0, -6.0, 0.8), 0, (("S", 3000), ("UP", 4500, 1200.0), ("S", 3000)), population=55.0,
                item=gd.carton())
    st.colour_frames()
    cam = st.camera("Cam", (0, 0, 0), (0, 0, 0), ortho=10.0)
    pts = st.points([o])  # framed at its final height, below the caption
    lo, hi = st.bounds([o])
    c, view = (lo + hi) / 2, Vector((1.0, -0.75, 0.62))

    def place(k, _f):
        st.ortho_view(cam, c, view, k)

    place(st.frame_in(cam, pts, st.RECT_FULL, place), 1)
    st.centre_in(cam, pts, st.RECT_FULL)
    bpy.context.view_layer.update()
    seg = o.conveyor_line.segments[1]
    seg.rise_mm = 0.0
    start, end, top = 25, 85, 1200.0
    cursor = []

    def per_frame(f):
        t = st.ease((f - start) / (end - start))
        rise = round(top * t / 10.0) * 10.0
        if abs(seg.rise_mm - rise) > 0.5:
            seg.rise_mm = rise  # its update rebuilds the line
            st.colour_frames()
        # where the drag handle (the end of the climbing piece) is on screen
        from bl_ext.user_default.conveyor_system.operators.build_line import segment_frames_for

        a, b = segment_frames_for(bpy.context, o)[1]
        cursor.append([f] + screen_xy(cam, o.matrix_world @ Vector((b.x, b.y, b.z))))

    return 1, 120, per_frame, {"cursor": cursor, "drag": [start, end], "fps": 30}


# ---------------------------------------------------------------- spiral + floors
@shot
def floors():
    """A two-turn spiral beside the first floor, ending on it; a vertical S-conveyor that stands on the first
    floor and comes out beside the second (neither goes through a slab); legs land on each floor."""
    setup()
    o = st.line("Line", (0.0, -6.0, 0.8), 0,
                (("S", 3000), ("SP", 2.0, 3000.0, "RIGHT"), ("S", 3000), ("S", 3000),
                 ("M", "LIFT", {"lift_shape": 'Z', "rise_mm": 3000.0}), ("S", 3000), ("S", 3000)),
                population=55.0, item=gd.tote())  # roller (MDR), as on the spiral card
    spiral = st.footprint(o, (1,), pad=0.2)
    x0, y0, x1, y1 = st.footprint(o, (4,), pad=0.1)
    lift = (x0 - 0.6, y0, x1 + 0.6, y1)  # the column stands beside the line: wider across, not along
    st.slab_avoiding("Floor 1", o, (2, 3, 4), avoid=[spiral])
    st.slab_avoiding("Floor 2", o, (5, 6), avoid=[lift])
    st.settle()
    st.colour_frames()
    lo, hi = st.bounds([o])
    centre = (lo + hi) / 2
    pts = st.points([o])
    cam = st.camera("Cam", (0, 0, 0), (0, 0, 0), ortho=10.0)

    def place(k, f):  # from the side, so the floors stack up
        st.ortho_orbit(cam, f, 1, 150, centre, k, 0.62, -28.0, 8.0, lift=-0.8)

    k = st.frame_in(cam, pts, st.RECT_CARD, place, samples=(1, 50, 100, 150))  # left of the card all the way

    def per_frame(f):
        place(k, f)
        st.centre_in(cam, pts, st.RECT_CARD)

    return 1, 150, per_frame, {"fps": 30}


# ---------------------------------------------------------------- split
@shot
def split():
    """A main line of blue bins: a 90 degree pop-up divert, a 45 degree divert (the branches on the same side,
    the 45 degree one last so they never cross), then a right-angle transfer turns the main line away."""
    setup()
    o = st.line("Main", (-9.0, 0.0, 0.8), -90.0,
                (("S", 3000), ("M", "DIVERTER", {"merge_angle": '90'}), ("S", 3000), ("S", 1500),
                 ("M", "DIVERTER", {"merge_angle": '45'}), ("S", 3000), ("M", "RAT", {"module_exit": 'RIGHT'}),
                 ("S", 3000)), population=75.0, item=gd.bin_())
    b1 = st.branch(o, 1, "LEFT", (("S", 3000), ("S", 1500)))
    b2 = st.branch(o, 4, "LEFT", (("S", 3000), ("S", 1500)))
    st.colour_frames()
    lo, hi = st.bounds([o, b1, b2])
    c = (lo + hi) / 2
    pts = st.points([o, b1, b2])
    view = Vector((0.25, -0.75, 1.35))
    cam = st.camera("Cam", (0, 0, 0), (0, 0, 0), ortho=10.0)

    def place(k, f):  # a slow push-in: the ortho scale closes in
        st.ortho_view(cam, c, view, k, zoom=1.0 - 0.12 * st.ease((f - 1) / 134))

    k = st.frame_in(cam, pts, st.RECT_CARD, place, samples=(1, 135))

    def per_frame(f):
        place(k, f)
        st.centre_in(cam, pts, st.RECT_CARD)

    return 1, 135, per_frame, {"fps": 30}


# ---------------------------------------------------------------- RAT
@shot
def rat():
    """Close up: a right-angle transfer stops each carton, lifts it on its belts and sends it out at 90 degrees --
    towards the camera, so nothing runs up into the caption."""
    setup()
    o = st.line("Line", (0.0, -4.0, 0.8), 0,
                (("S", 3000), ("M", "RAT", {"module_exit": 'RIGHT'}), ("S", 3000), ("S", 1500)), population=45.0, speed=0.4,
                item=gd.carton())
    st.colour_frames()
    lo, hi = st.run_box(o, (1,))
    c = (lo + hi) / 2
    pts = st.box_points(lo - Vector((0.9, 0.9, 0.85)), hi + Vector((0.9, 0.9, 0.45)))  # the transfer, legs to goods
    cam = st.camera("Cam", (0, 0, 0), (0, 0, 0), ortho=10.0)

    def place(k, f):
        st.ortho_orbit(cam, f, 1, 135, c, k, 0.55, -25.0, 5.0, lift=-0.1)  # from +X: the line runs across, the exit comes closer

    k = st.frame_in(cam, pts, st.RECT_FULL, place, samples=(1, 68, 135))

    def per_frame(f):
        place(k, f)
        st.centre_in(cam, pts, st.RECT_FULL)

    return 1, 135, per_frame, {"fps": 30}


# ---------------------------------------------------------------- eyedropper
@shot
def eyedropper():
    """Pick any object as the goods: the line carries totes; the eyedropper clicks the blue bin on the pallet,
    and every item on the line becomes one."""
    setup()
    o = st.line("Line", (0.0, -6.0, 0.8), 0, (("S", 3000), ("S", 3000), ("CR", 90), ("S", 3000)), population=55.0,
                item=gd.tote())
    st.colour_frames()
    pallet = put(gd.pallet(), (-1.6, -4.6, 0.0))
    carton = put(gd.carton(), (-1.92, -4.6, 0.144))
    bin_ = put(gd.bin_(), (-1.3, -4.6, 0.144), 90)
    lo, hi = st.run_box(o, (0, 1))
    pts = st.points([o, pallet, carton, bin_])  # the whole line: every item it carries left of the card
    c, view = (lo + hi) / 2, Vector((0.45, -1.0, 0.7))
    cam = st.camera("Cam", (0, 0, 0), (0, 0, 0), ortho=10.0)

    def place(k, _f):
        st.ortho_view(cam, c, view, k)

    place(st.frame_in(cam, pts, st.RECT_CARD, place), 1)
    st.centre_in(cam, pts, st.RECT_CARD)
    bpy.context.view_layer.update()
    click = 70
    state = {"done": False}

    def per_frame(f):
        if f >= click and not state["done"]:
            from bl_ext.user_default.conveyor_system.operators.build_line import build_line

            o.conveyor_line.populate_item = bin_  # the blue bin: the whole line visibly changes
            build_line(bpy.context, o)
            st.colour_frames()
            state["done"] = True

    target = screen_xy(cam, bin_.location + Vector((0.0, 0.0, 0.2)))
    return 1, 150, per_frame, {"fps": 30, "click": click, "target": target}


# ---------------------------------------------------------------- warehouse
def rack_row(name, x, y0, bays, load, bay=2.7, depth=1.1, levels=(0.0, 1.55, 3.1), skip=()):
    """A pallet rack along +Y from (x, y0): blue upright frames, orange beams, three pallet loads per bay and
    level (the load's mesh, linked); `skip`: (bay, level, slot) left empty."""
    p = gd.Parts()
    blue = gd.material("Rack upright", (0.05, 0.20, 0.50), roughness=0.5, metallic=0.3)
    orange = gd.material("Rack beam", (0.90, 0.38, 0.04), roughness=0.45, metallic=0.3)
    top = levels[-1] + 1.3
    for i in range(bays + 1):
        y = y0 + i * bay
        for sx in (-1, 1):
            p.box((x + sx * depth / 2, y, top / 2), (0.08, 0.08, top), blue, bevel=0.01)
        for z in (0.4, top / 2, top - 0.3):
            p.box((x, y, z), (depth, 0.04, 0.04), blue, bevel=0.005)
    for i in range(bays):
        yc = y0 + (i + 0.5) * bay
        for lv, z in enumerate(levels):
            if z > 0:
                for sx in (-1, 1):
                    p.box((x + sx * depth / 2, yc, z - 0.06), (0.05, bay - 0.08, 0.12), orange, bevel=0.005)
            for slot, dy in enumerate((-0.9, 0.0, 0.9)):
                if (i, lv, slot) not in skip:
                    copy_of(load, f"{name} pallet", (x, yc + dy, z))
    rack = p.build(name)
    rack.location = (0.0, 0.0, 0.0)
    return rack


def gantry(name, x0, x1, y, h=3.4, span=1.2):
    """The depalletiser: an orange gantry over the pallet line's end, its carriage over the carton line."""
    p = gd.Parts()
    orange = gd.material("Gantry", (0.95, 0.45, 0.05), roughness=0.4, metallic=0.2)
    grey = gd.material("Gantry carriage", (0.18, 0.19, 0.20), roughness=0.5, metallic=0.5)
    for x in (x0, x1):
        for sy in (-1, 1):
            p.box((x, y + sy * span, h / 2), (0.16, 0.16, h), orange, bevel=0.01)
    for sy in (-1, 1):
        p.box(((x0 + x1) / 2, y + sy * span, h), (x1 - x0 + 0.16, 0.18, 0.22), orange, bevel=0.01)
    xm = x0 + (x1 - x0) * 0.62
    p.box((xm, y, h + 0.05), (0.3, 2 * span + 0.2, 0.18), grey, bevel=0.01)  # the bridge
    p.box((xm, y, h - 0.7), (0.14, 0.14, 1.4), grey, bevel=0.01)  # the mast
    p.box((xm, y, h - 1.45), (0.55, 0.55, 0.06), grey, bevel=0.01)  # the gripper plate
    o = p.build(name)
    o.location = (0.0, 0.0, 0.0)
    return o


def station(name, at, heading, bin_, carton):
    """A pick & pack station across a branch's end: a table, a screen, a mat, a bin and a carton on it."""
    p = gd.Parts()
    top_m = gd.material("Station top", (0.85, 0.86, 0.87), roughness=0.5)
    steel = gd.material("Station steel", (0.25, 0.26, 0.28), roughness=0.4, metallic=0.6)
    mat_m = gd.material("Station mat", (0.05, 0.05, 0.06), roughness=0.9)
    screen = gd.material("Station screen", (0.02, 0.03, 0.05), roughness=0.2)
    p.box((0, 0, 0.9), (1.8, 0.8, 0.04), top_m, bevel=0.008)
    for sx in (-1, 1):
        for sy in (-1, 1):
            p.box((sx * 0.84, sy * 0.34, 0.45), (0.05, 0.05, 0.9), steel, bevel=0.005)
    p.box((0.5, 0.32, 1.15), (0.04, 0.04, 0.5), steel, bevel=0.005)
    p.box((0.5, 0.30, 1.42), (0.55, 0.03, 0.34), screen, bevel=0.006)
    p.box((0, -0.85, 0.006), (1.6, 0.8, 0.012), mat_m, bevel=0.004)
    o = p.build(name)
    rot = math.atan2(heading.y, heading.x) - math.pi / 2  # the table's long side across the branch
    centre = at + heading * 0.75
    o.location = (centre.x, centre.y, 0.0)
    o.rotation_euler.z = rot
    m = Matrix.Translation((centre.x, centre.y, 0.0)) @ Matrix.Rotation(rot, 4, 'Z')
    copy_of(bin_, f"{name} bin", m @ Vector((-0.45, 0.0, 0.92)), math.degrees(rot))
    copy_of(carton, f"{name} carton", m @ Vector((0.15, -0.05, 0.92)), math.degrees(rot) + 8)
    return o


def stripes(name, rects):
    """Yellow floor markings: (x0, y0, x1, y1) strips."""
    p = gd.Parts()
    yellow = gd.material("Floor marking", (0.95, 0.72, 0.08), roughness=0.6)
    for x0, y0, x1, y1 in rects:
        p.box(((x0 + x1) / 2, (y0 + y1) / 2, 0.002), (x1 - x0, y1 - y0, 0.004), yellow, bevel=0.0)
    o = p.build(name)
    o.location = (0.0, 0.0, 0.0)
    return o


def outline(x0, y0, x1, y1, w=0.1):
    return [(x0, y0, x1, y0 + w), (x0, y1 - w, x1, y1), (x0, y0, x0 + w, y1), (x1 - w, y0, x1, y1)]


def warehouse_scene():
    """A small warehouse: pallets leave the racks on a pallet line, are unwrapped and depalletised; their cartons
    join a loop of blue bins that climbs over a walkway, sends goods to two pick & pack stations and out
    through the dock door; a belt of letters runs in front. A slow fly-over."""
    from bl_ext.user_default.conveyor_system.operators.build_line import build_line

    st.studio(MODE)
    ctx = bpy.context
    bin_, carton, load, letter = gd.bin_(), gd.carton(), gd.pallet_load(), gd.envelope()
    # the loop: "Loop" round three sides, "Loop west" closes it; each one's end docks onto the other's body
    x_west = -1.6
    loop = st.line("Loop", (-3.0, 0.0, 0.8), -90.0,
                   (("S", 3000), ("S", 3000), ("UP", 4000, 1000.0), ("S", 3000), ("UP", 4000, -1000.0), ("S", 3000),
                    ("CL", 90), ("S", 1500), ("M", "DIVERTER", {"merge_angle": '90', "merge_side": 'RIGHT'}), ("S", 1500),
                    ("CL", 90), ("S", 3000), ("M", "DIVERTER", {"merge_angle": '90', "merge_side": 'RIGHT'}), ("S", 3000),
                    ("M", "DIVERTER", {"merge_angle": '90', "merge_side": 'RIGHT'}), ("S", 3000)),
                   population=55.0, item=bin_)
    end, _h = end_pose(loop)
    st.add_piece(loop.conveyor_line.segments.add(), ("S", round((end.x - (x_west + 0.45)) * 1000.0)))
    build_line(ctx, loop)
    y_back = end.y
    west_len = (y_back + 1.0 - 0.45) * 1000.0
    west = st.line("Loop west", (x_west, y_back + 1.0, 0.8), 180.0, (("S", 3000), ("S", west_len - 3000)),
                   population=55.0, item=bin_)
    # cartons from the depalletiser into the loop from the south
    feed = st.line("Depal out", (1.5, -7.0, 0.8), 0.0, (("S", 3000), ("S", 3550)), population=45.0, item=carton)
    # pallets out of the racks, unwrapped, to the depalletiser
    pallets = st.line("Pallets", (-13.0, -7.0, 0.5), -90.0,
                      (("S", 3000), ("M", "WRAPPER", {"wrapper_mode": 'UNWRAP'}), ("S", 3000), ("S", 3000), ("S", 1300)),
                      population=40.0, speed=0.25, width_mm=1300, item=load)
    letters = st.line("Letters", (-2.0, -10.0, 0.8), -90.0, (("S", 3000), ("S", 3000), ("S", 3000)), ctype="belt",
                      population=70.0, speed=0.6, item=letter)
    st.settle()
    # the diverters (their indices after the merges went in): the dock door east, two stations north
    segs = loop.conveyor_line.segments
    div = [i for i, s in enumerate(segs) if s.kind == 'MODULE' and s.module_kind == 'DIVERTER']
    out = st.branch(loop, div[0], "RIGHT", (("S", 3000), ("S", 2000)))
    picks = [st.branch(loop, i, "RIGHT", (("S", 2000),)) for i in div[1:]]
    st.settle()
    people = []
    for n, b in enumerate(picks):
        at, h = end_pose(b)
        tbl = station(f"Pick station {n + 1}", at, h, bin_, carton)
        m = Matrix.Translation(tbl.location) @ Matrix.Rotation(tbl.rotation_euler.z, 4, 'Z')
        people.append(env.person(f"Picker {n + 1}", m @ Vector((0.0, -0.75, 0.0)), math.degrees(tbl.rotation_euler.z)))
        env.shelving(f"Shelving {n + 1}", m @ Vector((0.0, 1.7, 0.0)), math.degrees(tbl.rotation_euler.z), bays=2, bin_=bin_)
    # pallet racks west, pallets staged at the pallet line's start, the depalletiser over its end
    racks = [rack_row("Rack A", -17.6, -9.5, 5, load, skip={(0, 1, 2), (2, 2, 0), (3, 0, 1), (4, 2, 2)}),
             rack_row("Rack B", -15.0, -9.5, 5, load, skip={(1, 1, 1), (2, 0, 0), (4, 1, 0)})]
    for k, (x, y) in enumerate(((-12.6, -9.2), (-11.2, -9.2))):
        copy_of(load, f"Staged pallet {k + 1}", (x, y, 0.0), 90)
    gantry("Depalletiser", -0.9, 2.2, -7.0)
    env.forklift("Forklift", (-12.4, 1.2, 0.0), 90.0, fork_h=1.6, load=load)  # putting a pallet away into rack B
    env.pallet_jack("Pallet jack", (-9.8, -9.4, 0.0), 180.0)
    people.append(env.person("Depal operator", (3.2, -8.6, 0.0), 120.0))
    # yellow markings: the walkway under the raised run, the pallet zone, the stations' zone
    up = next(i for i, s in enumerate(segs) if s.kind == 'STRAIGHT' and s.rise_mm > 1.0)  # the climb; then the raised run
    lift_mid = (end_pose(loop, up + 1)[0] + end_pose(loop, up)[0]) / 2
    people.append(env.person("Walker", (lift_mid.x, -3.2, 0.0), 0.0, shirt=(0.45, 0.18, 0.15)))  # on the walkway, under the run
    marks = [(lift_mid.x - 0.7, -4.5, lift_mid.x - 0.6, 3.5), (lift_mid.x + 0.6, -4.5, lift_mid.x + 0.7, 3.5)]
    marks += outline(-13.6, -10.2, -10.4, -8.2) + outline(-1.6, -8.8, 3.0, -5.2)
    stripes("Floor markings", marks)
    # the building around it all: a slab island, the back wall, a low west wall, the dock wall east
    things = [loop, west, feed, pallets, letters, out] + picks + racks + people
    lo, hi = st.bounds(things + [o for o in bpy.data.objects if o.name.startswith("Shelving")])
    at, _h = end_pose(out)
    wx = at.x + 0.9
    x0, y0, y1 = lo.x - 1.5, lo.y - 1.5, hi.y + 1.0
    env.diorama(x0, y0, wx, y1)
    bpy.data.objects["Studio floor"].location.z = -0.4  # the slab island stands on the studio floor
    door = gd.Parts()
    wall = gd.material("Wall panel", (0.80, 0.81, 0.83), roughness=0.6, metallic=0.2)
    dark = gd.material("Dock door", (0.22, 0.24, 0.27), roughness=0.5, metallic=0.4)
    rubber = gd.material("Dock seal", (0.03, 0.03, 0.03), roughness=0.9)
    door.box((wx + 0.15, (y0 + y1) / 2, 0.6), (0.3, y1 - y0, 1.2), wall, bevel=0.01)  # cut low, like the west wall ...
    door.box((wx + 0.15, at.y, 2.5), (0.3, 4.4, 5.0), wall, bevel=0.01)  # ... but for the dock door's portal
    door.box((wx - 0.02, at.y, 1.85), (0.05, 3.0, 3.6), dark, bevel=0.01)
    for k in range(1, 12):
        door.box((wx - 0.05, at.y, 0.05 + k * 0.3), (0.01, 3.0, 0.015), rubber, bevel=0.0)
    for sy in (-1, 1):
        door.box((wx - 0.08, at.y + sy * 1.6, 1.9), (0.15, 0.2, 3.7), rubber, bevel=0.01)
    door_o = door.build("Dock wall")
    door_o.location = (0.0, 0.0, 0.0)
    st.colour_frames()
    objs = things + [door_o]
    c = Vector(((x0 + wx) / 2, (y0 + y1) / 2, 1.5))
    pts = np.concatenate([st.points(objs), st.box_points(Vector((x0, y0, -0.4)), Vector((wx + 0.3, y1 + 0.3, 5.0)))])  # the whole island
    return c, pts


@shot
def warehouse():
    """The warehouse (warehouse_scene): a slow fly-over, then a zoom towards the loop."""
    c, pts = warehouse_scene()
    cam = st.camera("Cam", (0, 0, 0), (0, 0, 0), ortho=10.0)

    def place(k, f):
        st.ortho_orbit(cam, f, 1, 240, c, k, 0.75, -120.0, -62.0, lift=-1.0)

    k = st.frame_in(cam, pts, st.RECT_FULL, place, samples=(1, 60, 120, 180, 240))

    def per_frame(f):  # the whole site while the intro title stands, then a slow zoom towards the loop
        place(k * (1.0 - 0.38 * st.ease((f - 90) / 150)), f)
        st.centre_in(cam, pts, st.RECT_FULL)

    return 1, 240, per_frame, {"fps": 30}


# the listing's featured image: the whole warehouse on the right, room for the name on the left (tools/commercial/poster.py)
POSTER_RECT = (0.46, 0.98, 0.05, 0.95)  # the name takes the left 45 %


@shot
def poster():
    """One frame of the warehouse for the featured image: the site's cards show it at 640 x 360."""
    c, pts = warehouse_scene()
    cam = st.camera("Cam", (0, 0, 0), (0, 0, 0), ortho=10.0)

    def place(k, _f):
        st.ortho_view(cam, c, (math.cos(math.radians(-100.0)), math.sin(math.radians(-100.0)), 0.8), k)

    place(st.frame_in(cam, pts, POSTER_RECT, place), 1)
    st.centre_in(cam, pts, POSTER_RECT)
    return 1, 1, None, {}


def floor_dims(lines, gap=1.3, size=0.5, toward=None, off=0.95):
    """Each straight's length on the floor beside it, CAD style; a label too close to another moves to
    the other side of its line. `toward` (x, y): put every label on the side facing that way (the
    camera's, so a raised line never hides it)."""
    from bl_ext.user_default.conveyor_system.operators.build_line import segment_frames_for

    placed = []
    for line in lines:
        mw = line.matrix_world
        for seg, (a, b) in zip(line.conveyor_line.segments, segment_frames_for(bpy.context, line)):
            if seg.kind != 'STRAIGHT':
                continue
            pa, pb = mw @ Vector((a.x, a.y, 0.0)), mw @ Vector((b.x, b.y, 0.0))
            mid, d = (pa + pb) / 2, (pb - pa).normalized()
            side = Vector((-d.y, d.x, 0.0)) * off
            if toward is not None:
                if side.x * toward[0] + side.y * toward[1] < 0:
                    side = -side
            elif any((mid + side - q).length < gap for q in placed):
                side = -side
            placed.append(mid + side)
            rot = math.atan2(d.y, d.x)
            if abs(rot) > math.pi / 2:
                rot += math.pi
            label(f"{seg.length_mm / 1000:.2f} m", (mid.x + side.x, mid.y + side.y, 0.02), size=size, rot_z=rot)


# the "easy to build" featured image: the line in the right half, its top-right clear of nothing, the
# panel card over the lower right (tools/commercial/poster.py, POSTER_STYLE=build)
POSTER_BUILD_RECT = (0.45, 0.97, 0.30, 0.94)


@shot
def poster_build():
    """The featured image for "an easy way to build conveyors": one line of blue bins with two turns and a
    climb, each straight labelled with its length on the floor -- the line as the panel builds it."""
    setup()
    o = st.line("Line", (0.0, 0.0, 0.8), -90.0,
                (("S", 3000), ("CL", 90), ("UP", 3000, 1000.0), ("CR", 90), ("S", 3000)),
                population=60.0, item=gd.bin_())
    st.colour_frames()
    floor_dims([o], size=0.62, toward=(math.cos(math.radians(-55.0)), math.sin(math.radians(-55.0))), off=1.25)
    pts = st.points([o])
    lo, hi = st.bounds([o])
    c = (lo + hi) / 2
    cam = st.camera("Cam", (0, 0, 0), (0, 0, 0), ortho=10.0)

    def place(k, _f):
        st.ortho_view(cam, c, (math.cos(math.radians(-55.0)), math.sin(math.radians(-55.0)), 1.05), k)

    place(st.frame_in(cam, pts, POSTER_BUILD_RECT, place), 1)
    st.centre_in(cam, pts, POSTER_BUILD_RECT)
    return 1, 1, None, {}


def main():
    fn = SHOTS[SHOT]
    st.reset()
    first, last, per_frame, sidecar = fn()
    step = 1
    if RANGE:
        first, last, step = RANGE
    out = os.path.join(OUT, SHOT)
    n, complete = st.render(out, first, last, per_frame, step)
    with open(os.path.join(OUT, f"{SHOT}.json"), "w") as fh:
        json.dump({"shot": SHOT, "frames": n, "first": first, "last": last, "step": step, "complete": complete, **sidecar}, fh)
    print("SHOT", SHOT, "frames", n, "complete" if complete else "STOPPED", "->", out)


main()
