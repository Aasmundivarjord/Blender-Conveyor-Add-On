"""Per-line settings: one PropertyGroup on every Object (meaningful once
`is_conveyor_line` is set on a CURVES spine object), holding the conveyor
type/width/speed, populate settings and the CollectionProperty of segments.

Every property that affects geometry carries `update=_rebuild`, which
re-runs operators.build_line on the OWNING object (`self.id_data`), never
on the active object -- a segment edited through the UI list while some
other object is active must still rebuild the right line.
"""
from __future__ import annotations

from contextlib import contextmanager

import bpy

from ..config import loader

_catalog = loader.get_segment_catalog()

SEGMENT_KIND_ITEMS = [
    ('STRAIGHT', "Straight", "Straight section, length snapped to catalog increments. Drag the arrow at its end to raise or lower it"),
    ('CURVE', "Curve", "Horizontal curve at a chosen angle and inside radius"),
    # Kept for files saved before 2026-09-23 (enum values are stored by index,
    # so the item must stay in place). Elevation now lives on straights as
    # `rise_mm`; build_line migrates legacy inclines on first rebuild.
    ('INCLINE', "Incline (legacy)", "Converted on rebuild to a straight with a rise; drag the arrow at its end instead"),
    ('MODULE', "Module", "Discrete inserted module: right-angle transfer, merge, diverter"),
    ('SPIRAL', "Spiral", "Helical spiral: turns, radius, direction and height"),
]
CURVE_ANGLE_MIN_DEG = 5
CURVE_ANGLE_MAX_DEG = 350
CURVE_ANGLE_ITEMS = [(str(a), f"{a}°", f"{a} degree catalog curve") for a in _catalog.curve_angles_deg]
CURVE_DIRECTION_ITEMS = [('LEFT', "Left", "Turn left (counter-clockwise from above)"), ('RIGHT', "Right", "Turn right")]
CURVE_RADIUS_ITEMS = [(r.id, r.label, f"{r.system} catalog inside radius") for r in _catalog.curve_radii] + [
    ('CUSTOM', "Custom...", "Non-standard inside radius")
]
INCLINE_ANGLE_ITEMS = [(str(a), f"{a}°", f"{a} degree incline") for a in _catalog.incline_angles_deg]
MODULE_KIND_ITEMS = [(m.id, m.label, m.note) for m in _catalog.modules.values()]
MODULE_EXIT_ITEMS = [
    ('STRAIGHT', "Straight Through", "Product continues along the same heading"),
    ('LEFT', "Exit Left", "Product is transferred out of the left side; the line continues at +90°"),
    ('RIGHT', "Exit Right", "Product is transferred out of the right side; the line continues at -90°"),
]

# Kept alive at module scope: dynamic EnumProperty item callbacks must return
# strings that outlive the call or the UI can crash.
_type_items_cache: list[tuple[str, str, str]] = []
_width_items_cache: list[tuple[str, str, str]] = []

_suspend_depth = 0


@contextmanager
def suspended_rebuild():
    """Batch several property edits into one rebuild (operators use this,
    then call build_line once)."""
    global _suspend_depth
    _suspend_depth += 1
    try:
        yield
    finally:
        _suspend_depth -= 1


def _owner_line(prop_group):
    obj = prop_group.id_data
    if not isinstance(obj, bpy.types.Object):
        return None
    if obj.type != 'CURVES' or not obj.conveyor_line.is_conveyor_line:
        return None
    return obj


def context_for(context, obj):
    """`context` when it shows the scene `obj` is in, else a stand-in for
    the object's own scene. A property edited from outside that scene (the
    Outliner, a script) used to rebuild the line against the WRONG scene's
    lines and fail on its item stream."""
    scene = getattr(context, "scene", None)
    if scene is not None and obj.name in scene.objects:
        return context
    from types import SimpleNamespace

    for other in obj.users_scene:
        return SimpleNamespace(scene=other, view_layer=other.view_layers[0] if other.view_layers else None)
    return context


def _on_merge_side(self, context):
    """A junction made two-sided gets a right face as wide as its left one
    until a line docks there (each face is as wide as its own line)."""
    if self.merge_side == 'BOTH' and self.merge_infeed_right_mm <= 0.0:
        self["merge_infeed_right_mm"] = self.merge_infeed_mm
    _rebuild(self, context)


EXACT_ANGLE_KEY = "curve_angle_exact"  # a curve laid along a path (R21) keeps its exact angle; an edit of the angle drops it


def _on_curve_angle_changed(self, context):
    if EXACT_ANGLE_KEY in self:
        del self[EXACT_ANGLE_KEY]
    _rebuild(self, context)


def _rebuild(self, context):
    if _suspend_depth:
        return
    obj = _owner_line(self)
    if obj is None:
        return
    from ..operators.build_line import build_line

    build_line(context_for(context, obj), obj)


# Multi-edit (suite UI rule, 2026-10-13): a line setting edited in the side panel
# on the ACTIVE line applies to every selected line; the panel says how many.
SHARED_SETTINGS = ('conveyor_type', 'width_preset', 'custom_width_mm', 'speed_m_s', 'population_pct', 'roller_pitch_mm', 'guide_rails', 'nose_over', 'pouch_size', 'pouch_width_mm', 'pouch_height_mm', 'pouch_depth_mm', 'pouch_pitch_mm', 'support_spacing_m', 'support_mount')
_SAME_TYPE_ONLY = {"roller_pitch_mm", "pouch_size", "pouch_width_mm", "pouch_height_mm", "pouch_depth_mm", "pouch_pitch_mm"}
_sharing = False


def selected_lines(context, obj) -> list:
    """The selected conveyor lines, `obj` first: the multi-edit set."""
    try:
        selected = list(context.view_layer.objects.selected)  # (context.selected_objects needs a screen)
    except Exception:
        selected = []
    return [obj] + [o for o in selected if o is not obj and o.type == 'CURVES' and o.conveyor_line.is_conveyor_line]


def share_setting(source, name: str, lines) -> list:
    """Copy setting `name` from `source` (a line's settings) to `lines`; their own
    updates rebuild them. A width the other line's type does not offer becomes a
    Custom width of the same size. Returns the lines that changed."""
    global _sharing
    value = getattr(source, name)
    changed = []
    _sharing = True
    try:
        for line in lines:
            s = line.conveyor_line
            if name in _SAME_TYPE_ONLY and s.conveyor_type != source.conveyor_type:
                continue
            if getattr(s, name) == value:
                continue
            try:
                setattr(s, name, value)
            except TypeError:
                if name != "width_preset":
                    continue
                from ..operators.build_line import resolve_width_mm

                with suspended_rebuild():
                    s.custom_width_mm = resolve_width_mm(source)
                s.width_preset = 'CUSTOM'
            changed.append(line)
    finally:
        _sharing = False
    return changed


def _from_side_panel(context) -> bool:
    region = getattr(context, "region", None)
    return region is not None and region.type == 'UI'


def _shared_update(name: str):
    """update= for a multi-edit setting: rebuild this line, then, when the user
    changed it on the active line in the side panel, the other selected lines.
    Never from scripts, operators or other add-ons (they edit one line on purpose)."""
    def update(self, context):
        _rebuild(self, context)
        if _sharing or _suspend_depth:
            return
        obj = _owner_line(self)
        if obj is None or not _from_side_panel(context):
            return
        try:
            if context.view_layer.objects.active is not obj:
                return
        except Exception:
            return
        others = selected_lines(context, obj)[1:]
        if others:
            share_setting(self, name, others)
    return update


def _on_active_segment_changed(self, context):
    """Clicking a row in the segment list: highlight that piece in the
    viewport (modifier input only, no rebuild)."""
    obj = _owner_line(self)
    if obj is None:
        return
    from ..operators.build_line import highlight_index_for, push_highlight

    push_highlight(obj, highlight_index_for(context, obj))


# Stable enum numbers: Blender stores dynamic enums by number, so removing a
# type (powered roller 2026-09-25, cleated belt 2.26.1) must not renumber the
# others; a saved line of a removed type becomes REPLACED_TYPES' (build_line).
_TYPE_NUMBERS = {"gravity_roller": 0, "powered_roller": 1, "belt": 2, "chain": 3, "omni": 4, "pocket": 5, "pouch_sorter": 6}
REPLACED_TYPES = {1: 0, 5: 2}  # removed type number -> the one its saved lines become: powered roller -> roller, cleated belt -> belt
from ..model import pouch as _pouch_model  # noqa: E402  (the pouch sorter's standard bag sizes)

_POUCH_SIZE_ITEMS = tuple(_pouch_model.size_items())


def _conveyor_type_items(self, context):
    global _type_items_cache
    _type_items_cache = [(t.id, t.label, t.notes, 'NONE', _TYPE_NUMBERS.get(t.id, 10 + i))
                         for i, t in enumerate(loader.get_line_types().values())]
    return _type_items_cache


def _width_preset_items(self, context):
    global _width_items_cache
    items = []
    conveyor_type = loader.get_conveyor_types().get(self.conveyor_type)
    if conveyor_type is not None:
        width_groups = loader.get_width_presets()
        for group_id in conveyor_type.width_groups:
            for width in width_groups.get(group_id, []):
                items.append((width.id, width.label, f"{width.system} standard width"))
    items.append(('CUSTOM', "Custom...", "Enter a non-standard width (flagged as non-standard)"))
    _width_items_cache = items
    return _width_items_cache


def snap_length_mm(value: float) -> float:
    inc = _catalog.straight_increment_mm
    return max(inc, round(value / inc) * inc)


MODULE_MIN_LENGTH_MM = 300.0


def _on_length_changed(self, context):
    if self.kind in ('STRAIGHT', 'INCLINE'):
        snapped = snap_length_mm(self.length_mm)
        if abs(snapped - self.length_mm) > 1e-6:
            # Direct ID-property write bypasses this update callback.
            self["length_mm"] = snapped
    elif self.kind == 'MODULE' and self.length_mm < MODULE_MIN_LENGTH_MM:
        self["length_mm"] = MODULE_MIN_LENGTH_MM
    _rebuild(self, context)


def _on_kind_changed(self, context):
    if self.kind == 'MODULE':
        self["length_mm"] = _catalog.modules[self.module_kind].length_mm
    elif self.length_mm < _catalog.straight_min_mm:
        self["length_mm"] = _catalog.straight_default_mm
    _rebuild(self, context)


_ROUTE_ITEMS: list = []  # kept alive: dynamic enum items must outlive the callback


def _route_items(self, context):
    """None + the Populate placeholders. The class index is the item's
    position in NAME order: the Collection Info node sorts a collection's
    objects by name, and the populate tree picks instances by that index."""
    from ..operators.populate import PLACEHOLDER_COLLECTION_NAME, PLACEHOLDER_ITEMS

    collection = bpy.data.collections.get(PLACEHOLDER_COLLECTION_NAME)
    names = sorted(o.name for o in collection.objects) if collection is not None else sorted(n for n, *_ in PLACEHOLDER_ITEMS)
    _ROUTE_ITEMS[:] = [('NONE', "Share", "The docked branch takes an equal share of the goods (every unrouted branch of the group does)", 'MOD_INSTANCE', 0)]
    _ROUTE_ITEMS.extend((str(i), n.replace("Placeholder ", ""), f"Route class {i} ({n}) onto the docked branch", 'MOD_INSTANCE', i + 1)
                        for i, n in enumerate(names))
    return _ROUTE_ITEMS


def _get_route_item(self):
    return int(self.route_class) + 1 if self.route_class >= 0 else 0


def _set_route_item(self, value):
    self.route_class = int(value) - 1


def _on_module_kind_changed(self, context):
    self["length_mm"] = _catalog.modules[self.module_kind].length_mm
    _rebuild(self, context)


class CONVEYOR_SegmentSettings(bpy.types.PropertyGroup):
    kind: bpy.props.EnumProperty(name="Kind", items=SEGMENT_KIND_ITEMS, default='STRAIGHT', update=_on_kind_changed)
    length_mm: bpy.props.FloatProperty(
        name="Length (mm)",
        description="Section length along the conveyor, snapped to the catalog increment (150 mm) for straights and inclines",
        default=3000.0,
        min=50.0,
        step=15000,
        precision=0,
        update=_on_length_changed,
    )
    # Metres view of the same value (shown in the panel; no upper limit).
    length_m: bpy.props.FloatProperty(
        name="Length",
        description="Section length along the conveyor, in metres (any length; straights snap to the 150 mm catalog increment)",
        subtype='DISTANCE', unit='LENGTH', min=0.05, step=10, precision=2,
        get=lambda self: self.length_mm / 1000.0,
        set=lambda self, v: setattr(self, "length_mm", v * 1000.0),
    )
    # Legacy enum (files before 2026-09-23). Read through segment_curve_angle_deg().
    curve_angle: bpy.props.EnumProperty(name="Angle (legacy)", items=CURVE_ANGLE_ITEMS, default='90', update=_rebuild)
    curve_angle_deg: bpy.props.IntProperty(
        name="Angle",
        description="Turn angle in degrees. Catalog curves come in 30/45/60/90/180; any other value is a non-standard curve",
        default=0,  # 0 = unset: fall back to the legacy enum
        min=0,
        max=CURVE_ANGLE_MAX_DEG,
        soft_min=CURVE_ANGLE_MIN_DEG,
        soft_max=180,
        subtype='NONE',
        update=_on_curve_angle_changed,
    )
    rise_mm: bpy.props.FloatProperty(
        name="Rise (mm)",
        description="Height gained (+) or lost (-) over this straight. Set by dragging the elevation arrow at the segment's end",
        default=0.0,
        soft_min=-6000.0,
        soft_max=6000.0,
        step=2500,
        precision=0,
        update=_rebuild,
    )
    curve_direction: bpy.props.EnumProperty(name="Direction", items=CURVE_DIRECTION_ITEMS, default='LEFT', update=_rebuild)
    curve_radius: bpy.props.EnumProperty(
        name="Inside Radius", items=CURVE_RADIUS_ITEMS, default=_catalog.curve_default_radius_id, update=_rebuild
    )
    custom_radius_mm: bpy.props.FloatProperty(
        name="Custom Inside Radius (mm)", default=800.0, min=100.0, soft_max=3000.0, step=5000, precision=0, update=_rebuild
    )
    incline_angle: bpy.props.EnumProperty(
        name="Angle", items=INCLINE_ANGLE_ITEMS, default=str(_catalog.incline_default_angle_deg), update=_rebuild
    )
    incline_down: bpy.props.BoolProperty(name="Decline", description="Descend instead of climb", default=False, update=_rebuild)
    module_kind: bpy.props.EnumProperty(name="Module", items=MODULE_KIND_ITEMS, default='RAT', update=_on_module_kind_changed)
    module_exit: bpy.props.EnumProperty(name="Exit", items=MODULE_EXIT_ITEMS, default='STRAIGHT', update=_rebuild)
    # A right-angle transfer's faces take the frame width of the line docked
    # there (0 = the line's own width): a 1200 mm line in on one face, an
    # 800 mm line out on the next (user, 2026-10-11). The side faces name
    # their line in merge_source / merge_source_right; the far (END) face of
    # a corner RAT -- the goods go straight through to a line docked there --
    # names its line here.
    rat_face_left_mm: bpy.props.FloatProperty(name="Left face (mm)", default=0.0, min=0.0, soft_max=2000.0, precision=0, update=_rebuild)
    rat_face_right_mm: bpy.props.FloatProperty(name="Right face (mm)", default=0.0, min=0.0, soft_max=2000.0, precision=0, update=_rebuild)
    rat_face_end_mm: bpy.props.FloatProperty(name="End face (mm)", default=0.0, min=0.0, soft_max=2000.0, precision=0, update=_rebuild)
    rat_source_end: bpy.props.StringProperty(name="End face line", description="The line docked straight through on the far face of a corner RAT", default="")
    # Merge junction (module on the MAIN line): which side other lines dock
    # on, at which catalog angle, and how wide their frame is. Feeders snap
    # onto the face; `merge_source` names the line docked right now.
    merge_side: bpy.props.EnumProperty(
        name="Infeed Side",
        items=[('LEFT', "Left", "Other lines dock on the left of travel"), ('RIGHT', "Right", "Other lines dock on the right of travel"),
               ('BOTH', "Both", "Infeed faces on both sides at the same angle (one line per side)")],
        default='LEFT', update=_on_merge_side,
    )
    # Explicit numbers: enum values are stored by number, and files saved
    # before 15/75 existed hold 0..3 for 30/45/60/90.
    merge_angle: bpy.props.EnumProperty(
        name="Infeed Angle",
        items=[('15', "15°", "", 4), ('30', "30°", "", 0), ('45', "45°", "", 1), ('60', "60°", "", 2), ('75', "75°", "", 5),
               ('90', "90°", "Perpendicular side dock (right-angle transfer style)", 3)],
        default='45', update=_rebuild,
    )
    merge_infeed_mm: bpy.props.FloatProperty(
        name="Infeed Width (mm)", description="Frame width of the line docking here (set automatically when one snaps on)",
        default=540.0, min=100.0, soft_max=1500.0, step=1000, precision=0, update=_rebuild,
    )
    merge_infeed_right_mm: bpy.props.FloatProperty(
        name="Right Infeed Width (mm)",
        description="Frame width of the line docking on the RIGHT face of a two-sided junction (set automatically when one snaps on)",
        default=0.0, min=0.0, soft_max=1500.0, step=1000, precision=0, update=_rebuild,
    )
    merge_source: bpy.props.StringProperty(name="Docked Line", description="Line currently docked on this junction (left face when the side is Both)")
    merge_source_right: bpy.props.StringProperty(name="Docked Line (Right)", description="Line docked on the right face of a two-sided junction")
    legs: bpy.props.BoolProperty(
        name="Legs",
        description="Floor stands under this piece. Off: none on it, and a stand flush with each edge of the leg-free stretch "
                    "(a tunnel or a walkway under the line)",
        default=True, update=_rebuild,
    )
    merge_auto: bpy.props.BoolProperty(name="Auto", description="Inserted automatically for a docking line; removed when it leaves", default=False)
    junction_tech: bpy.props.EnumProperty(
        name="Technology",
        description="How this merge / divert moves the goods",
        items=[('AUTO', "Auto", "Angled roller merge below 90°, strip belts for angled diverts, pop-up belt transfer (RAT) at 90°")]
              + [(t.id, t.label, t.note) for t in loader.get_technologies().values()],
        default='AUTO', update=_rebuild,
    )
    wrapper_mode: bpy.props.EnumProperty(
        name="Wrapper",
        items=[('WRAP', "Wrap", "Stretch-wraps the pallet on the turntable: film roll on the carriage"),
               ('UNWRAP', "Unwrap", "Cuts and removes the film: a knife arm on the carriage")],
        default='WRAP', update=_rebuild,
    )
    arb_function: bpy.props.EnumProperty(
        name="Function",
        items=[('CENTER', "Centre / align", "Goods drift to the centre lane over the module"),
               ('TURN_LEFT', "Turn 90° left", "Goods rotate a quarter turn counter-clockwise in motion (cross to lengthwise)"),
               ('TURN_RIGHT', "Turn 90° right", "Goods rotate a quarter turn clockwise in motion")],
        default='CENTER', update=_rebuild,
    )
    arb_pivot: bpy.props.BoolProperty(
        name="Fixed pivot (cheap)",
        description="Turn around a pin at the line edge instead of an angled-roller element: rigid loads, limited size window",
        default=False, update=_rebuild,
    )
    spiral_turns: bpy.props.FloatProperty(
        name="Turns", description="How many full turns the spiral makes", default=1.0, min=0.1, soft_max=8.0, step=25, precision=2,
        update=_rebuild,
    )
    spiral_angle_deg: bpy.props.FloatProperty(
        name="Rotation (°)", description="How far the spiral turns in total (360° = one full turn)",
        min=30.0, soft_max=3600.0, step=1500, precision=0,
        get=lambda self: self.spiral_turns * 360.0,
        set=lambda self, v: setattr(self, "spiral_turns", max(v, 30.0) / 360.0),
    )
    # Ids stay 'Z' / 'C' (files store them); the labels follow the usual
    # S- / C-conveyor vocabulary: S = out on the opposite side (through a
    # mezzanine), C = in and out on the same side.
    lift_shape: bpy.props.EnumProperty(
        name="Shape", items=[('Z', "S (through)", "Up and on in the same direction: out on the opposite side, through a mezzanine"),
                             ('C', "C (same side)", "Up and back out above the entry, in and out on the same side")],
        default='Z', update=_rebuild,
    )
    lift_side: bpy.props.EnumProperty(
        name="Column Side",
        items=[('LEFT', "Left", "The lift column stands on the left of travel; its forks reach across the line"),
               ('RIGHT', "Right", "The lift column stands on the right of travel")],
        default='LEFT', update=_rebuild,
    )
    lift_fork_pitch_mm: bpy.props.IntProperty(
        name="Fork Pitch (mm)",
        description="How far apart the forks ride round the vertical conveyor's loop (rounded so the goods land on every n-th fork)",
        default=400, min=150, max=1500, step=50, update=_rebuild,
    )
    height_m: bpy.props.FloatProperty(
        name="Height", description="Height gained over this spiral or lift. Negative on a spiral: it winds DOWN (upper floor to lower floor)",
        subtype='DISTANCE', unit='LENGTH', min=-50.0, max=50.0, step=10, precision=2,
        get=lambda self: self.rise_mm / 1000.0, set=lambda self, v: setattr(self, "rise_mm", v * 1000.0),
    )
    buffer_out_mode: bpy.props.EnumProperty(
        name="Out rate",
        items=[('AUTO', "Auto", "What the next machine downstream takes: the next junction's technology rate, the rack this line feeds, else the in rate"),
               ('MANUAL', "Set", "An out rate of your own (items/h)")],
        default='AUTO', update=_rebuild,
    )
    buffer_out_ph: bpy.props.IntProperty(
        name="Out (items/h)", description="How many items per hour the buffer releases (Out rate = Set)",
        default=600, min=1, soft_max=20000, update=_rebuild,
    )
    buffer_out_pct: bpy.props.IntProperty(
        name="Output", subtype='PERCENTAGE', min=0, max=100, default=100, step=500, update=_rebuild,
        description=("The share of what arrives that leaves: the rest piles up, filled "
                     "with the goods from the line before, until the buffer is full; then it takes only "
                     "what it lets out and the line before follows. 100 % = the goods pass through"),
    )
    buffer_release: bpy.props.EnumProperty(
        name="Release",
        items=[('SINGULATED', "Singulated", "One zone per release: the front item leaves, the queue steps up (photo-eye logic)"),
               ('SLUG', "Slug", "The whole queue leaves together nose to tail, then the buffer fills again")],
        default='SINGULATED', update=_rebuild,
    )
    buffer_gap_mm: bpy.props.FloatProperty(
        name="Queue Gap (mm)",
        description="Space between queued items in a buffer (a zone is one item plus this gap; a photo-eye at the front of each)",
        default=150.0, min=0.0, soft_max=500.0, step=1000, precision=0, update=_rebuild,
    )
    route_item: bpy.props.EnumProperty(
        name="Route",
        description="What leaves the main line here onto the docked branch: its share of the goods, or one item class",
        items=_route_items, get=_get_route_item, set=_set_route_item,
    )
    route_class: bpy.props.IntProperty(
        name="Route Class",
        description="Diverter: which item class leaves the main line here (index of the placeholder in the Populate items, in name order; -1 = the branch's share of the goods)",
        default=-1, min=-1, soft_max=8, update=_rebuild,
    )


def _fmt_m(mm: float) -> str:
    return f"{mm / 1000.0:.2f} m"


def _fmt(mm: float) -> str:
    """Length for list labels, honoring the display unit preference."""
    from ..config import units

    scene = bpy.context.scene
    if scene is not None and units.get_display_unit_system(scene) == 'IMPERIAL':
        return units.format_length_mm(mm, scene)
    return f"{mm:.0f}"


def segment_curve_angle_deg(seg: CONVEYOR_SegmentSettings) -> float:
    """Effective turn angle: a curve laid along a path keeps its exact angle
    (EXACT_ANGLE_KEY, R21); else the integer property, or the legacy enum for
    segments saved before it existed."""
    exact = seg.get(EXACT_ANGLE_KEY)
    if exact is not None:
        return float(exact)
    if seg.curve_angle_deg > 0:
        return int(seg.curve_angle_deg)
    try:
        return int(seg.curve_angle)
    except (TypeError, ValueError):
        return _catalog.curve_default_angle_deg


def segment_rise_mm(seg: CONVEYOR_SegmentSettings) -> float:
    """Elevation change over the segment: `rise_mm` on straights, derived
    from the legacy angle on not-yet-migrated inclines, 0 otherwise."""
    if seg.kind == 'STRAIGHT':
        return float(seg.rise_mm)
    if seg.kind == 'INCLINE':
        import math

        angle = float(seg.incline_angle) * (-1.0 if seg.incline_down else 1.0)
        return seg.length_mm * math.sin(math.radians(angle))
    return 0.0


def segment_label(seg: CONVEYOR_SegmentSettings) -> str:
    if seg.kind == 'STRAIGHT':
        rise = seg.rise_mm
        if abs(rise) >= 0.5:
            arrow = "↗" if rise > 0 else "↘"
            return f"Straight {_fmt_m(seg.length_mm)} {arrow} {_fmt(abs(rise))}"
        return f"Straight {_fmt_m(seg.length_mm)}"
    if seg.kind == 'CURVE':
        side = "L" if seg.curve_direction == 'LEFT' else "R"
        radius = segment_curve_radius_mm(seg)
        return f"Curve {side} {segment_curve_angle_deg(seg)}° R{_fmt(radius)}"
    if seg.kind == 'SPIRAL':
        side = "L" if seg.curve_direction == 'LEFT' else "R"
        return f"Spiral {side} {seg.spiral_turns * 360.0:.0f}° {'↓' if seg.rise_mm < 0 else '↑'} {_fmt_m(abs(seg.rise_mm))}"
    if seg.kind == 'INCLINE':
        word = "Decline" if seg.incline_down else "Incline"
        return f"{word} {seg.incline_angle}° {_fmt_m(seg.length_mm)}"
    if seg.kind == 'MODULE':
        label = _catalog.modules[seg.module_kind].label
        if seg.module_kind == 'RAT' and seg.module_exit != 'STRAIGHT':
            label += "  → " + ("Left" if seg.module_exit == 'LEFT' else "Right")
        if seg.module_kind == 'DIVERTER':
            label = f"Divert {seg.merge_angle}° {seg.merge_side[0]}" + (f" class {seg.route_class}" if seg.route_class >= 0 else "")
            if seg.merge_source:
                label += f"  → {seg.merge_source}"
        if seg.module_kind == 'BUFFER':
            label = f"Buffer {_fmt_m(seg.length_mm)}"
        if seg.module_kind == 'WRAPPER':
            label = f"Pallet {'unwrapper' if seg.wrapper_mode == 'UNWRAP' else 'wrapper'} {_fmt_m(seg.length_mm)}"
        if seg.module_kind == 'LIFT':
            label = f"Vertical {'S' if seg.lift_shape == 'Z' else 'C'} ↑ {_fmt_m(seg.rise_mm)}"
        if seg.module_kind == 'ARB':
            fn = {'CENTER': "Align centre", 'TURN_LEFT': "Turn L", 'TURN_RIGHT': "Turn R"}[seg.arb_function]
            label = fn + (" (pivot)" if seg.arb_pivot and seg.arb_function != 'CENTER' else ("" if seg.arb_function == 'CENTER' else " (rollers)"))
        if seg.module_kind == 'MERGE':
            label = f"Merge {seg.merge_angle}° {'LR' if seg.merge_side == 'BOTH' else seg.merge_side[0]}"
            docked = [n for n in (seg.merge_source, seg.merge_source_right if seg.merge_side == 'BOTH' else "") if n]
            if docked:
                label += "  ← " + ", ".join(docked)
        return label
    return seg.kind


def segment_curve_radius_mm(seg: CONVEYOR_SegmentSettings) -> float:
    if seg.curve_radius == 'CUSTOM':
        return seg.custom_radius_mm
    preset = _catalog.curve_radius_by_id(seg.curve_radius)
    return preset.radius_mm if preset else seg.custom_radius_mm


SEGMENT_ICONS = {'STRAIGHT': 'IPO_LINEAR', 'CURVE': 'FORCE_CURVE', 'INCLINE': 'IPO_EASE_IN', 'MODULE': 'MOD_BUILD', 'SPIRAL': 'MOD_SCREW'}


def _on_populate_item_changed(self, context):
    obj = _owner_line(self)
    if obj is not None and self.populate_item is not None:
        from ..operators.populate import seed_from_item

        seed_from_item(self, self.populate_item, context.scene)
    _rebuild(self, context)


def _on_populate_changed(self, context):
    """Turning Populate on IS the question "what does it carry?", so the
    checkbox goes straight into the viewport eyedropper (operators/pick_item;
    user request 2026-10-05: one click less). Esc there keeps the placeholder
    totes the rebuild just placed."""
    if _suspend_depth:
        return
    _rebuild(self, context)
    obj = _owner_line(self)
    if obj is None:
        return
    if self.populate:
        # Lines feeding INTO this one carry goods too: a feeder docked
        # before the main line was populated never joined the stream (its
        # own Populate stayed off, so its share was ignored and it stayed
        # empty).
        from ..operators.build_line import build_line
        from ..operators.detect_junctions import feeders_of

        for feeder in feeders_of(context_for(context, obj), obj):
            if not feeder.conveyor_line.populate:
                feeder.conveyor_line["populate"] = True  # ID write: no eyedropper, no recursion
                build_line(context_for(context, feeder), feeder)
    if not self.populate or self.populate_item is not None:
        return
    if getattr(context, "active_object", None) is obj:
        from ..operators.pick_item import start_picker_from_ui

        start_picker_from_ui(context)


class CONVEYOR_GuideGap(bpy.types.PropertyGroup):
    """An opening in one guide rail where another line merges in. Managed
    by operators/detect_junctions.py, keyed by the feeding line's name."""

    source: bpy.props.StringProperty(name="Source Line")
    arc_len_mm: bpy.props.FloatProperty(name="Center (mm)")
    length_mm: bpy.props.FloatProperty(name="Length (mm)")
    side: bpy.props.EnumProperty(items=[('LEFT', "Left", ""), ('RIGHT', "Right", "")], default='LEFT')


class CONVEYOR_LineSettings(bpy.types.PropertyGroup):
    is_conveyor_line: bpy.props.BoolProperty(name="Conveyor Line", default=False)
    conveyor_type: bpy.props.EnumProperty(name="Type", items=_conveyor_type_items, update=_shared_update("conveyor_type"))
    width_preset: bpy.props.EnumProperty(name="Width", items=_width_preset_items, update=_shared_update("width_preset"))
    custom_width_mm: bpy.props.FloatProperty(
        name="Custom Width (mm)",
        description="Non-standard width -- real cost/lead-time penalty",
        default=500.0,
        min=50.0,
        soft_max=2000.0,
        step=5000,
        precision=0,
        update=_shared_update("custom_width_mm"),
    )
    # The pouch sorter's bag (model/pouch.py): a standard size or a custom
    # width x height, its depth along the rail and the trolley pitch.
    pouch_size: bpy.props.EnumProperty(name="Pouch", description="The hanging pouch: a standard size (width across the rail x height) or custom",
                                       items=_POUCH_SIZE_ITEMS, update=_shared_update("pouch_size"))
    pouch_width_mm: bpy.props.FloatProperty(name="Pouch Width (mm)", description="Custom pouch width, across the rail",
                                            default=400.0, min=50.0, soft_max=800.0, step=1000, precision=0, update=_shared_update("pouch_width_mm"))
    pouch_height_mm: bpy.props.FloatProperty(name="Pouch Height (mm)", description="Custom pouch height, hanging below the trolley",
                                             default=600.0, min=50.0, soft_max=1200.0, step=1000, precision=0, update=_shared_update("pouch_height_mm"))
    pouch_depth_mm: bpy.props.FloatProperty(name="Pouch Depth (mm)", description="The loaded pouch's thickness along the rail",
                                            default=120.0, min=10.0, soft_max=400.0, step=1000, precision=0, update=_shared_update("pouch_depth_mm"))
    pouch_pitch_mm: bpy.props.FloatProperty(name="Pouch Pitch (mm)", description="Trolley spacing along the rail (never closer than the pouch depth plus 30 mm)",
                                            default=250.0, min=50.0, soft_max=1000.0, step=1000, precision=0, update=_shared_update("pouch_pitch_mm"))
    support_spacing_m: bpy.props.FloatProperty(
        name="Leg Spacing",
        description="Floor stands (a pouch sorter's portals or ceiling rods) at most this far apart; a stand stands flush with "
                    "each end of the line and with each edge of a leg-free piece (Legs off in the piece's settings)",
        default=1.5, min=0.5, soft_max=6.0, step=10, precision=2, subtype='DISTANCE', unit='LENGTH',
        update=_shared_update("support_spacing_m"),
    )
    support_mount: bpy.props.EnumProperty(
        name="Supports",
        description="How the line is carried",
        items=[('FLOOR', "Floor", "Stands on the floor (or the deck below): legs, a pouch sorter's portal frames"),
               ('CEILING', "Ceiling", "Hung from the ceiling: a cross member under the frame and drop rods up to the first surface "
                                      "above the line, else the Ceiling level (Scene panel)")],
        default='FLOOR', update=_shared_update("support_mount"),
    )
    speed_m_s: bpy.props.FloatProperty(
        name="Speed (m/s)",
        description="Surface speed of rollers, belt and transported goods",
        default=0.5,
        min=0.0,
        soft_max=3.0,
        update=_shared_update("speed_m_s"),
    )
    throughput_ph: bpy.props.IntProperty(
        name="Throughput (items/h)",
        description="The main line's throughput: how many items per hour the stream carries. Sets the item spacing at the "
                    "line's speed; 0 = from the pitch and speed in Placement. Docked lines take a share of it (Share)",
        default=0, min=0, soft_max=6000, step=100, update=_rebuild,
    )
    share_pct: bpy.props.IntProperty(
        name="Share (%)",
        description="A branch: how much of the master line's goods it takes out. 0 = an equal split with the goods "
                    "riding on and the other branches left at 0. The goods are dealt out evenly",
        default=0, min=0, max=100, step=5, subtype='PERCENTAGE', update=_rebuild,
    )
    # Simple flow: two sliders on a populated
    # line. The master of a stream sets it; the lines connected to it follow.
    population_pct: bpy.props.FloatProperty(
        name="Population",
        description="How full the stream of goods is: 100 % = goods nose to tail with a 50 mm gap, 0 % = empty. "
                    "Lines connected downstream follow the master line",
        default=50.0, min=0.0, max=100.0, step=500, precision=0, subtype='PERCENTAGE', update=_shared_update("population_pct"),
    )
    flow_master: bpy.props.BoolProperty(
        name="Master",
        description="This line sets its stream's Population: the lines connected to it follow it "
                    "(without one, the most upstream line does)",
        default=False, update=_rebuild,
    )
    reverse: bpy.props.BoolProperty(
        name="Reverse",
        description="Run the line backwards: goods travel from the end towards the start, rollers and belt spin the other way",
        default=False,
        update=_rebuild,
    )
    # Kept for files saved before 2026-09-23; no longer shown. Detail is
    # always high; roller density is `roller_pitch_mm` instead.
    high_detail: bpy.props.BoolProperty(name="High Detail (legacy)", default=True, update=_rebuild)
    roller_pitch_mm: bpy.props.FloatProperty(
        name="Roller Pitch (mm)",
        description="Center-to-center distance between rollers. The catalog pitch for this roller class is shown next to it; the geometry never lets rollers overlap",
        default=0.0,  # 0 = not set yet: build_line seeds it from the catalog
        min=0.0,
        soft_max=300.0,
        step=500,
        precision=0,
        update=_shared_update("roller_pitch_mm"),
    )
    dock_enabled: bpy.props.BoolProperty(
        name="Dock",
        description="Let this line dock onto a junction when its end points at another line",
        default=True,
    )
    guide_rails: bpy.props.BoolProperty(
        name="Fences",
        description="Side guide rails (fences) that keep goods on the conveyor. Off for lines that need open sides",
        default=True,
        update=_shared_update("guide_rails"),
    )
    nose_over: bpy.props.BoolProperty(
        name="Nose-over Transitions",
        description="Blend flat/incline pitch changes with a vertical arc instead of a hard kink",
        default=True,
        update=_shared_update("nose_over"),
    )
    segments: bpy.props.CollectionProperty(type=CONVEYOR_SegmentSettings)
    guide_gaps: bpy.props.CollectionProperty(type=CONVEYOR_GuideGap)
    active_segment_index: bpy.props.IntProperty(name="Active Segment", default=0, update=_on_active_segment_changed)
    grow_at: bpy.props.EnumProperty(
        name="Add pieces at",
        description="Which end of the line the keys extend",
        items=[('END', "End", "The keys add pieces after the last one (the line grows forwards)"),
               ('START', "Start", "The keys add pieces before the first one: the line grows backwards, what is built stays put")],
        default='END',
    )
    end_pose: bpy.props.FloatVectorProperty(
        name="End Pose", description="Local x, y, z of the line's end and its heading in degrees", size=4, default=(0, 0, 0, 0)
    )
    total_length_mm: bpy.props.FloatProperty(name="Total Length (mm)", default=0.0)

    populate: bpy.props.BoolProperty(
        name="Populate", description="Carry goods along this line. Turning it on opens the eyedropper: click the object to transport",
        default=False, update=_on_populate_changed,
    )
    populate_item: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="Item",
        description="The object this line carries (empty: the shipped placeholder totes and cartons)",
        update=_on_populate_item_changed,
    )
    populate_spacing_mm: bpy.props.FloatProperty(
        name="Spacing (mm)",
        description="Center-to-center distance between items. Seeded from the picked item's length, then yours",
        default=800.0,
        min=20.0,
        soft_max=5000.0,
        step=5000,
        precision=0,
        update=_rebuild,
    )
    populate_fill: bpy.props.FloatProperty(
        name="Fill %",
        description="Density: fewer items spread evenly over the whole line, never random gaps",
        default=1.0,
        min=0.01,
        max=1.0,
        subtype='FACTOR',
        update=_rebuild,
    )
    populate_rotation_deg: bpy.props.FloatProperty(
        name="Rotation Offset (deg)",
        description="Extra yaw on every item, on top of the auto-detected forward axis",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
        update=_rebuild,
    )
    populate_lane_mm: bpy.props.FloatProperty(
        name="Lane Offset (mm)", description="Sideways offset from the centerline (+ = right of travel)", default=0.0, soft_min=-500.0, soft_max=500.0, step=1000, precision=0, update=_rebuild
    )
    populate_forward_axis: bpy.props.EnumProperty(
        name="Forward Axis",
        description="Which local axis of the item points along travel. Auto = longest horizontal bounding-box side",
        items=[('AUTO', "Auto", ""), ('X', "+X", ""), ('Y', "+Y", ""), ('NEG_X', "-X", ""), ('NEG_Y', "-Y", "")],
        default='AUTO',
        update=_rebuild,
    )


classes = (CONVEYOR_SegmentSettings, CONVEYOR_GuideGap, CONVEYOR_LineSettings)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.conveyor_line = bpy.props.PointerProperty(type=CONVEYOR_LineSettings)


def unregister():
    del bpy.types.Object.conveyor_line
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
