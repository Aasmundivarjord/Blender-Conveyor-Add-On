"""Populate: turns the line's Populate settings into node-group input
values (build_line pushes them) and owns the shipped placeholder items.

The item's forward axis is auto-detected as its longest horizontal
bounding-box side (a 600x400 tote travels long side first); the manual
Rotation Offset stays as an override. Height is derived from the bounding
box's lowest local z (pre-scale, so scaled by the object's own scale) so
the item's bottom sits on the conveying surface wherever its origin is.
"""
from __future__ import annotations

import math

import bpy

from ..config import loader, units

PLACEHOLDER_COLLECTION_NAME = "Conveyor Item Placeholders"

# (name, across_mm, along_mm, height_mm): Y-forward boxes with base origin.
PLACEHOLDER_ITEMS = [
    ("Placeholder Tote 600x400", 400.0, 600.0, 280.0),
    ("Placeholder Carton 500x350", 350.0, 500.0, 300.0),
]

_FORWARD_YAW = {'Y': 0.0, 'X': math.pi / 2.0, 'NEG_Y': math.pi, 'NEG_X': -math.pi / 2.0}


def item_extents(obj: bpy.types.Object) -> tuple[float, float, float]:
    """(size_x, size_y, min_z) with the object's own scale applied.
    `bound_box` is local space BEFORE scale; `.dimensions` bakes scale in
    but hides where the origin sits inside the box."""
    xs = [c[0] for c in obj.bound_box]
    ys = [c[1] for c in obj.bound_box]
    zs = [c[2] for c in obj.bound_box]
    return (
        (max(xs) - min(xs)) * abs(obj.scale.x),
        (max(ys) - min(ys)) * abs(obj.scale.y),
        min(zs) * obj.scale.z,
    )


def wh_load(obj) -> dict | None:
    """The load description another warehouse add-on put on `obj` (Racks:
    kind, id, length_m along travel, width_m, height_m, forward_axis,
    object; as the Racks add-on writes it), or None."""
    if obj is None:
        return None
    try:
        raw = obj.get("wh_load")
    except Exception:
        return None
    if raw is None:
        return None
    try:
        from .._wh import records as wh_records

        data = wh_records.read_record(raw, None)  # a JSON string (contract v2.1 R2) or the IDProperty dict older files carry
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def detect_forward_axis(obj: bpy.types.Object) -> str:
    load = wh_load(obj)
    if load and load.get("forward_axis") in ('X', 'Y'):
        return str(load["forward_axis"])  # a EUR pallet travels on its 0.8 m side: the longest side would turn it
    sx, sy, _ = item_extents(obj)
    return 'X' if sx > sy else 'Y'


def item_length_along(settings, item) -> float:
    """The item's length along travel (m): what a warehouse add-on
    published for it, else its bounding box along the forward axis."""
    axis = resolve_forward_axis(settings, item)
    load = wh_load(item)
    if load and load.get("length_m") and load.get("width_m"):
        along = axis in ('X', 'NEG_X')
        published = load.get("forward_axis") == 'X'
        return float(load["length_m"] if along == published else load["width_m"])
    sx, sy, _ = item_extents(item)
    return sx if axis in ('X', 'NEG_X') else sy


def resolve_forward_axis(settings, obj) -> str:
    return detect_forward_axis(obj) if settings.populate_forward_axis == 'AUTO' else settings.populate_forward_axis


def seed_from_item(settings, item: bpy.types.Object, scene: bpy.types.Scene) -> None:
    """Called once when 'Pick Item' changes: seeds Spacing from the item's
    length along travel. Never again, so it never fights the user's value."""
    length_m = item_length_along(settings, item)
    if length_m > 0.0:
        settings["populate_spacing_mm"] = round(units.bu_to_mm(length_m, scene) * 1.3 / 10.0) * 10.0


def _build_box_mesh(mesh: bpy.types.Mesh, sx: float, sy: float, sz: float) -> None:
    hx, hy = sx / 2.0, sy / 2.0
    verts = [(-hx, -hy, 0.0), (hx, -hy, 0.0), (hx, hy, 0.0), (-hx, hy, 0.0),
             (-hx, -hy, sz), (hx, -hy, sz), (hx, hy, sz), (-hx, hy, sz)]
    faces = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()


POUCH_COLLECTION_NAME = "Conveyor Pouch Items"


def ensure_pouch_items(scene: bpy.types.Scene) -> bpy.types.Collection:
    """The stand-in goods of a pouch line without a picked item (model/pouch.POUCH_ITEMS):
    like the placeholders, in an unlinked collection, the same count and name order."""
    from ..model import pouch as pouch_model

    collection = bpy.data.collections.get(POUCH_COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(POUCH_COLLECTION_NAME)
    collection.use_fake_user = True
    if collection.name in scene.collection.children:
        scene.collection.children.unlink(collection)
    if len(collection.objects) == 0:
        from ..geonodes import materials

        looks = (materials.cardboard_box, materials.plastic)
        for k, (name, across_mm, along_mm, height_mm) in enumerate(pouch_model.POUCH_ITEMS):
            mesh = bpy.data.meshes.new(name)
            _build_box_mesh(mesh, units.mm_to_bu(across_mm, scene), units.mm_to_bu(along_mm, scene), units.mm_to_bu(height_mm, scene))
            mesh.materials.append(looks[min(k, len(looks) - 1)]())
            obj = bpy.data.objects.new(name, mesh)
            collection.objects.link(obj)
    return collection


def ensure_placeholders(scene: bpy.types.Scene) -> bpy.types.Collection:
    """The placeholder items live in a collection that is NOT linked to the
    scene: Collection Info still evaluates it, the items never show up at
    the origin and the outliner stays clean. (Earlier builds linked it and
    disabled the objects in viewports -- instances of a viewport-disabled
    object evaluate but draw nothing, so Populate looked broken. Files from
    those builds are migrated here.)"""
    collection = bpy.data.collections.get(PLACEHOLDER_COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(PLACEHOLDER_COLLECTION_NAME)
    collection.use_fake_user = True  # survives a save with Populate off everywhere
    if collection.name in scene.collection.children:
        scene.collection.children.unlink(collection)
    for obj in collection.objects:
        obj.hide_viewport = False
        obj.hide_render = False
    if len(collection.objects) == 0:
        from ..geonodes import materials

        plastic = materials.plastic()
        for name, across_mm, along_mm, height_mm in PLACEHOLDER_ITEMS:
            mesh = bpy.data.meshes.new(name)
            _build_box_mesh(
                mesh,
                units.mm_to_bu(across_mm, scene),
                units.mm_to_bu(along_mm, scene),
                units.mm_to_bu(height_mm, scene),
            )
            mesh.materials.append(plastic)
            obj = bpy.data.objects.new(name, mesh)
            collection.objects.link(obj)
    return collection


def populate_values(context, obj, settings) -> dict:
    values = _own_populate_values(context, obj, settings)
    values.update(route_values(context, obj, settings))
    if values.get("Use Item"):
        # The item's length along THIS line's travel, as the pitch and every reader size it: its
        # wh_load length_m with its forward axis, the larger side where the goods ride sideways
        # (a branch off a 90 degree pop-up divert: a pallet 0.8 along the main is 1.2 along it).
        # A follower copied the main's 0.8 and its pallets overhung its end by 0.2 m (2.23.4).
        values["Item Length"] = max(populate_item_length(context, obj), 0.02)
    return values


def _own_populate_values(context, obj, settings) -> dict:
    scene = context.scene
    values = {
        "Populate": settings.populate,
        "Spacing": units.mm_to_bu(settings.populate_spacing_mm, scene),
        "Fill": settings.populate_fill,
        "Lane Offset": units.mm_to_bu(settings.populate_lane_mm, scene),
        "Height Offset": 0.0,
        "Seed": 0,
    }
    if not settings.populate:
        # Keep the tree happy with valid defaults without creating placeholders.
        values.update({"Use Item": False, "Item": None, "Placeholders": None, "Placeholder Count": 1,
                       "Item Length": 0.6, "Item Bottom": 0.0, "Item Yaw": 0.0})
        return values

    item = settings.populate_item
    if item is not None and item != obj:
        sx, sy, min_z = item_extents(item)
        axis = resolve_forward_axis(settings, item)
        values.update({
            "Use Item": True,
            "Item": item,
            "Placeholders": None,
            "Placeholder Count": 1,
            "Item Length": max(sx if axis in ('X', 'NEG_X') else sy, 0.02),
            "Item Bottom": min_z,
            "Item Yaw": _FORWARD_YAW[axis] + math.radians(settings.populate_rotation_deg),
        })
    else:
        collection = ensure_placeholders(scene)
        values.update({
            "Use Item": False,
            "Item": None,
            "Placeholders": collection,
            "Placeholder Count": len(collection.objects),
            "Item Length": units.mm_to_bu(max(a for _, _, a, _ in PLACEHOLDER_ITEMS), scene),
            "Item Bottom": 0.0,
            "Item Yaw": math.radians(settings.populate_rotation_deg),
        })
    return values


# ------------------------------------------------------- shared streams --
#
# Lines docked onto each other share one item stream with slot ownership
# (operators/stream.py). A single line is a group of one and behaves as
# before (Stream Length 0 = own length, no ownership).

ROUTE_KEYS = ("Populate", "Use Item", "Item", "Placeholders", "Placeholder Count", "Item Length", "Item Bottom",
              "Item Yaw")
_depth = [0]


def routed_from(context, obj):
    """(main line, diverter index, segment) when `obj` is a branch that
    receives a routed item class, else None."""
    from .stream import parent_of

    parent = parent_of(context, obj)
    if parent is None or parent[0] != 'DIVERTER':
        return None
    main, index = parent[1], parent[2]
    return main, index, main.conveyor_line.segments[index]


def item_width_across(settings, item) -> float:
    """The item's extent ACROSS travel (m): its published width, else its
    bounding box across the forward axis."""
    axis = resolve_forward_axis(settings, item)
    load = wh_load(item)
    if load and load.get("length_m") and load.get("width_m"):
        along = axis in ('X', 'NEG_X')
        published = load.get("forward_axis") == 'X'
        return float(load["width_m"] if along == published else load["length_m"])
    sx, sy, _ = item_extents(item)
    return sy if axis in ('X', 'NEG_X') else sx


def goods_turned(context, obj) -> bool:
    """True when goods ride part of this line SIDEWAYS: a right-angle
    transfer corner on it, or the line hangs on a right-angle face /
    carries on from a line that ends sideways (the yaw it keeps is about
    90 degrees). After the transfer the item's long side runs along the
    line, so the pitch floor must use it (user, 2026-10-11: 1200 in, 800
    out)."""
    settings = obj.conveyor_line
    if any(sg.kind == 'MODULE' and sg.module_kind == 'RAT' and sg.module_exit != 'STRAIGHT' for sg in settings.segments):
        return True
    keep = settings.get("branch_keep_yaw")
    return keep is not None and abs(abs(float(keep)) - math.pi / 2.0) < 0.35


def populate_item_length(context, obj) -> float:
    """Along-travel length of the item this line transports (m): its own,
    or the main line's when it is docked without one -- the larger of its
    two sides where the goods ride sideways somewhere on the line."""
    from .stream import effective_item

    settings = obj.conveyor_line
    item = effective_item(context, obj)
    if item is not None and item != obj:
        along = item_length_along(settings, item)
        if goods_turned(context, obj):
            along = max(along, item_width_across(settings, item))
        return max(along, 0.02)
    longest = units.mm_to_bu(max(a for _, _, a, _ in PLACEHOLDER_ITEMS), context.scene)
    return longest


OVERHANG_KEY = "goods_across_mm"  # [own path, turned there, on the line it merges onto, turned there] (build_line)
OVERHANG_TOL_MM = 5.0
TURNED_NOTE = "Sideways after the 90° transfer"  # the panel's width: about 36 characters a line


def goods_sizes_mm(context, obj) -> list:
    """(across, along) in mm of each kind of goods `obj` carries, the way
    they travel before a transfer turns them: its item (laid as on the line
    it comes from), else the placeholder totes and cartons."""
    from .stream import effective_item, stream_root

    item = effective_item(context, obj)
    if item is not None and item != obj:
        src = obj if obj.conveyor_line.populate_item == item else stream_root(context, obj)
        s, scene = src.conveyor_line, context.scene
        return [(units.bu_to_mm(item_width_across(s, item), scene), units.bu_to_mm(item_length_along(s, item), scene))]
    return [(w, a) for _n, w, a, _h in PLACEHOLDER_ITEMS]


def across_mm(sizes: list, yaw_offset: float) -> float:
    """How wide the goods run across their path, turned by `yaw_offset` on it."""
    c, s = abs(math.cos(yaw_offset)), abs(math.sin(yaw_offset))
    return max((w * c + a * s for w, a in sizes), default=0.0)


def overhang_notes(context, obj) -> list:
    """[(text, dim)]: goods wider than the line they ride on (
    a 90 degree transfer keeps the goods' orientation, so a 600 x 400 tote
    travelling long side first crosses a 500 mm branch with its 600 mm
    side). From what build_line measured; the widths are read now."""
    from .build_line import resolve_width_mm
    from .detect_junctions import docked_junction
    from .stream import parent_of

    settings = obj.conveyor_line
    data = settings.get(OVERHANG_KEY)
    ctype = loader.get_conveyor_types().get(settings.conveyor_type)
    if data is None or len(data) < 4 or (ctype is not None and ctype.cross_section == "pouch"):
        return []
    if not settings.populate and parent_of(context, obj) is None:
        return []  # no goods on it
    own, own_turned, onto, onto_turned = (float(v) for v in data[:4])
    out = []
    width = resolve_width_mm(settings)
    if own > width + OVERHANG_TOL_MM:
        out.append((f"Goods {own:.0f} mm across, line {width:.0f} mm", False))
        if own_turned:
            out.append((TURNED_NOTE, True))
    dock = docked_junction(context, obj, 'MERGE')
    if dock is not None and onto > 0.0:
        main_width = resolve_width_mm(dock[0].conveyor_line)
        if onto > main_width + OVERHANG_TOL_MM:
            out.append((f"Goods {onto:.0f} mm across on {dock[0].name}", False))
            out.append((f"It is {main_width:.0f} mm" + ("; goods ride sideways" if onto_turned else " wide"), True))
    return out


def populate_item_footprint(context, obj) -> float:
    """Length along travel plus width across (m) of the item this line
    transports, the placeholders' largest without one: how far the goods
    must be apart through a right-angle transfer where they stop
    (model/transfer_motion.min_pitch_m)."""
    from .stream import effective_item

    settings = obj.conveyor_line
    item = effective_item(context, obj)
    if item is not None and item != obj:
        return max(item_length_along(settings, item), 0.02) + max(item_width_across(settings, item), 0.02)
    return units.mm_to_bu(max(w + a for _, w, a, _ in PLACEHOLDER_ITEMS), context.scene)


def route_values(context, obj, settings) -> dict:
    from ..geonodes.populate import ROUTE_SLOTS, TRANSFER_SLOTS
    from .stream import tree_for

    from .ports import start_offset_m

    # The goods start at the line's own start -- or at a rack port's handover
    # point when the line starts on one (the rack's conveyor end holds the
    # first slot otherwise).
    values = {"Stream Length": 0.0, "Stream Offset": 0.0, "Owner Mask": 0, "Stream Sources": 0, "Slot Length": 0.0,
              "Prefix": max(float(settings.get("prefix_length_m", 0.0)), start_offset_m(context, obj)),
              "Use Stream Speed": False, "Stream Speed": 0.0, "Stretch From": 0.0, "Stretch Span": 0.0, "Stretch Length": 0.0}
    for k in range(1, 9):
        values[f"Owner Split {k}"] = 1.0
    values["Stream Extra Slots"] = 0
    values["Identity Shift"] = 0
    values["Stream Phase"] = 0.0
    for k in (1, 2):
        values.update({f"Buffer {k} Stop": -1.0, f"Buffer {k} Pitch": 0.75, f"Buffer {k} Period": 0.0, f"Buffer {k} Start": 0.0,
                       f"Buffer {k} First": 0.0, f"Buffer {k} Rank": -1, f"Buffer {k} Slug": 0})
    values["Switch Time"] = 1.0e9
    values["Switch Fraction"] = 1.0
    values["Queue Pitch"] = 0.65
    for k in range(1, ROUTE_SLOTS + 1):
        values.update({f"Route At {k}": 0.0, f"Route Mask {k}": 0, f"Route Share {k}": -1.0, f"Route Class {k}": -1,
                       f"Route Hi {k}": -1, f"Route Take {k}": False, f"Route First {k}": False})
    for k in range(1, TRANSFER_SLOTS + 1):
        values.update({f"Transfer {k} Id": 0, f"Transfer {k} From": 0.0, f"Transfer {k} To": -1.0,
                       f"Transfer {k} Mask": 0, f"Transfer {k} Class": -1, f"Transfer {k} Rule": -1, f"Transfer {k} Hi": -1, f"Transfer {k} Height": 0.0,
                       f"Transfer {k} Stop": 0.0, f"Transfer {k} Hold": 0.0, f"Transfer {k} Turn": 0.0, f"Transfer {k} Inbound": False})
    values["Transfer Ramp"] = 0.05
    for k in (1, 2):
        values.update({f"Lift {k} Active": False, f"Lift {k} Phase": 0.0, f"Lift {k} Pick": 0.0, f"Lift {k} Drop": 0.0,
                       f"Lift {k} Face": 0.0, f"Lift {k} Reach": 0.0, f"Lift {k} Fork Pitch": 0.4})
    if _depth[0] > 4:
        return values
    _depth[0] += 1
    try:
        tree = tree_for(context, obj)
    finally:
        _depth[0] -= 1
    me = tree.members.get(obj.name)
    if me is None:
        return values
    # The wrap and the pitch for EVERY populated line, shared or not: without
    # a Stream Length the tree wraps over the curve's own length and widens
    # the pitch to fit it (an 18 m line at a 16.2 m pitch drew 17.6 m slots:
    # the hand-over lock with a rack drifted 13 frames per pallet and the
    # slug phasing was off). The wrap is
    # a whole number of pitches (operators/stream.py), the extra slots are
    # never drawn.
    # A docked line's goods run at the group's speed -- ON SCREEN, i.e. the
    # real speed times the scene's clock, exactly as the root's own Speed
    # input is pushed (build_line._push_inputs). Pushed unscaled, a branch
    # at time scale 10 reached the transfer's hand-over ten times later
    # than its main line dropped the pallet, so the pallet vanished at the
    # RAT and the branch stayed empty; at time scale 3 the branch goods
    # crawled at a third of the main's.
    from ..props.scene_settings import time_scale

    values.update({
        "Stream Length": tree.length, "Stream Offset": me.offset, "Spacing": tree.spacing, "Fill": tree.fill, "Seed": tree.seed,
        "Use Stream Speed": obj != tree.root, "Stream Speed": tree.speed * time_scale(context.scene), "Slot Length": tree.slot_length,
    })
    if tree.shared:
        values.update({"Owner Mask": me.mask, "Stream Sources": tree.sources})
        for k, split in enumerate(tree.splits, start=1):
            values[f"Owner Split {k}"] = float(split)
    elif tree.targeted:
        values["Spacing"] = tree.spacing
    values["Prefix"] = me.prefix_u if (tree.shared and me.parent is not None and me.parent[0] in ('DIVERTER', 'CONTINUE')) else values["Prefix"]
    values["Stream Extra Slots"] = int(tree.extra_slots)
    values["Identity Shift"] = int(me.identity_shift)
    values["Stream Phase"] = float(tree.phase_s)
    for k, (stop, pitch_q, period, start, first, mode, slug) in enumerate(me.buffers[:2], start=1):
        # (model/buffer_fifo: the FIFO this line's goods pass, in flow order)
        values.update({f"Buffer {k} Stop": float(stop), f"Buffer {k} Pitch": float(pitch_q), f"Buffer {k} Period": float(period),
                       f"Buffer {k} Start": float(start), f"Buffer {k} First": float(first), f"Buffer {k} Rank": int(mode),
                       f"Buffer {k} Slug": int(slug)})
    if math.isfinite(tree.switch_time):
        values["Switch Time"] = float(tree.switch_time)  # a full buffer: the root's slots thin to what it lets out
        values["Switch Fraction"] = float(tree.switch_fraction)
    gap = 0.05
    for seg in settings.segments:
        if seg.kind == 'MODULE' and seg.module_kind == 'BUFFER':
            gap = units.mm_to_bu(seg.buffer_gap_mm, context.scene)
            break
    values["Queue Pitch"] = populate_item_length(context, obj) + gap  # sizes the zones and their photo-eyes
    # The splits its goods pass, edge by edge (operators/stream.py chain; the
    # populate tree deals them as simple_flow.branch_of_item).
    if len(me.chain) > ROUTE_SLOTS:
        print(f"conveyor: {obj.name}'s goods pass {len(me.chain)} split edges; the first {ROUTE_SLOTS} are dealt")
    for k, (at, mask, q, lo, hi, take, first, _dst) in enumerate(me.chain[:ROUTE_SLOTS], start=1):
        values.update({f"Route At {k}": float(at), f"Route Mask {k}": int(mask), f"Route Share {k}": float(q),
                       f"Route Class {k}": int(lo), f"Route Hi {k}": int(hi), f"Route Take {k}": bool(take), f"Route First {k}": bool(first)})
    if me.stretch:
        values.update({"Stretch From": float(me.stretch[0]), "Stretch Span": float(me.stretch[1]), "Stretch Length": float(me.stretch[2])})
    edge_of = {}
    for r, entry in enumerate(me.chain[:ROUTE_SLOTS]):
        edge_of.setdefault(entry[7], r)
    # Pop-up transfers of the whole group: every line lifts its goods where
    # they cross one, and raises the moving parts of its own. A transfer on a
    # branch's way lifts the goods that branch's edge takes (none, on a line
    # whose goods never pass that edge).
    for k, (tid, c0, c1, mask, lo, hi, height, stop, hold, turn, inbound, branch, _line, through) in enumerate(tree.transfers[:TRANSFER_SLOTS], start=1):
        rule = -1 if branch is None else edge_of.get(branch, ROUTE_SLOTS)
        values.update({f"Transfer {k} Id": int(tid), f"Transfer {k} From": float(c0), f"Transfer {k} To": float(c1),
                       f"Transfer {k} Mask": int(mask), f"Transfer {k} Class": int(lo), f"Transfer {k} Rule": int(rule), f"Transfer {k} Hi": int(hi), f"Transfer {k} Height": float(height),
                       f"Transfer {k} Stop": float(stop), f"Transfer {k} Hold": float(hold), f"Transfer {k} Turn": float(turn),
                       f"Transfer {k} Inbound": bool(inbound),
                       f"Transfer {k} Except": int(edge_of.get(through, -1)) if through is not None else -1})
    values["Transfer Ramp"] = float(tree.ramp)
    values["Transfer Ease"] = float(tree.transfer_ease)
    # Fork-column lifts: the tree spaces the forks by the slot pitch and
    # phases them onto the slot grid (build_line caches the loop): Phase =
    # the pick corner's loop coordinate minus its full flow arc.
    data = list(settings.get("lift_data", []) or [])
    rev = bool(settings.reverse)
    pre, own = float(settings.get("prefix_length_m", 0.0)), float(settings.get("own_length_m", 0.0))
    for j in range(0, len(data) - 9, 10):
        k, a_pick, a_drop, l_fwd, l_rev, d_fwd, d_rev, face, reach, fork_pitch = data[j:j + 10]
        f_pick = pre + ((own - a_drop) if rev else a_pick)
        l_pick, l_drop = (l_rev, d_rev) if rev else (l_fwd, d_fwd)
        values.update({f"Lift {int(k)} Active": True, f"Lift {int(k)} Phase": float(l_pick - f_pick),
                       f"Lift {int(k)} Pick": float(l_pick), f"Lift {int(k)} Drop": float(l_drop),
                       f"Lift {int(k)} Face": float(face), f"Lift {int(k)} Reach": float(reach),
                       f"Lift {int(k)} Fork Pitch": float(fork_pitch)})
    if me.parent is not None:
        item = settings.populate_item
        if item is None or item == obj:
            # No item of its own: a docked line shows the MAIN line's goods --
            # a branch the class picked on its diverter, a feeder the same
            # item the main carries (its slots used to turn from totes into
            # the main's item at the junction).
            base = _own_populate_values(context, tree.root, tree.root.conveyor_line)
            keys = ROUTE_KEYS[1:] if me.parent[0] == 'MERGE' else ROUTE_KEYS  # a feeder keeps its own Populate
            values.update({k: base[k] for k in keys})
        elif me.parent[0] in ('DIVERTER', 'CONTINUE'):
            # Its own eyedropped item: it takes the slots of the lines carrying that item.
            values["Populate"] = bool(tree.root.conveyor_line.populate)
    if tree.throughput_ph <= 0.0:
        values["Populate"] = False  # nothing flows (Population 0, or the master carries nothing)
    return values


def stream_speed(obj) -> float:
    settings = obj.conveyor_line
    return abs(settings.speed_m_s)
