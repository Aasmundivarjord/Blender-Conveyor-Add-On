"""Segment list editing: add (after the active segment), remove, move,
duplicate, set a curve's angle. Each operator batches its property edits
and rebuilds once.

The Straight / Curve L / Curve R / Module buttons act on the SELECTED
point of the path:
  - with the END selected (last row) they extend the line: a new piece is
    appended after it and becomes active, so repeated clicks steer the end
    (Curve L four times is a full circle, on purpose);
  - with a start or middle row selected they CHANGE that one piece in
    place (Curve L on a right curve flips it, Straight on a curve
    straightens it...). Nothing is inserted, so the rest of the list stays
    put -- what the user asked for after accidental circles from inserted
    curves. Duplicate is the way to insert a piece mid-line.
Angles are changed with the quick buttons below the list (30/45/60/90/180
or any typed value), not by adding more curves. Elevation is NOT a segment
kind any more: drag the arrow at a straight's end (ui/gizmos.py)."""
from __future__ import annotations

import bpy

from ..config import loader
from ..props.line_settings import CURVE_ANGLE_MAX_DEG, CURVE_ANGLE_MIN_DEG, suspended_rebuild
from .build_line import build_line


def _active_line(context):
    obj = context.active_object
    if obj is None or obj.type != 'CURVES' or not obj.conveyor_line.is_conveyor_line:
        return None
    return obj


class _LineOperator:
    @classmethod
    def poll(cls, context):
        return _active_line(context) is not None


def segment_values(src) -> dict:
    """Every writable field of a piece, read BEFORE the collection grows:
    a reference into `segments` goes stale when `add()` reallocates it, and
    the duplicate then read the fresh piece's defaults (a copied spiral came
    out as a straight, or lost its turns)."""
    late = ("rise_mm", "length_mm")
    names = [p.identifier for p in src.bl_rna.properties
             if not p.is_readonly and p.type != 'COLLECTION' and p.identifier not in ("rna_type", "kind") + late]
    return {"kind": src.kind, **{name: getattr(src, name) for name in names + list(late)}}


def apply_segment_values(dst, values: dict) -> None:
    """Kind first (its callback resets the length), the plain values last
    so the copy ends up identical to the source. Generic over the fields,
    so one added later (spiral turns, lift shape, fork pitch, junction
    technology, buffer gap...) is never left behind."""
    dst.kind = values["kind"]
    for name, value in values.items():
        if name == "kind":
            continue
        try:
            setattr(dst, name, value)
        except (TypeError, ValueError):  # a legacy enum holding a value its items no longer have
            pass


def adds_piece(settings) -> bool:
    """The keys ADD a piece (else they change the selected one): with no
    row selected (index -1, e.g. after a click on empty space in the
    picker -- that used to read as "Replace piece 0" and silently replaced
    the LAST piece through Python's negative indexing), with the last row
    selected, or -- growing backwards -- with the first row selected."""
    i = settings.active_segment_index
    if i < 0:
        return True
    return i == 0 if settings.grow_at == 'START' else i >= len(settings.segments) - 1


def is_end_selected(settings) -> bool:  # older name
    return adds_piece(settings)


def add_mode_label(settings) -> str:
    if not adds_piece(settings):
        return f"Replace piece {settings.active_segment_index + 1}"
    return "Add to the start" if settings.grow_at == 'START' else "Add to the end"


LIFT_DEFAULT_RISE_MM = 3000.0  # one floor up, like a new spiral


def _apply_kind(seg, kind: str, catalog) -> None:
    """Turns `seg` into the piece the button names, keeping what carries over."""
    if kind == 'STRAIGHT':
        was_straight = seg.kind in ('STRAIGHT', 'INCLINE')
        seg.kind = 'STRAIGHT'
        if not was_straight or seg.length_mm < catalog.straight_min_mm:
            seg.length_mm = catalog.straight_default_mm
        if not was_straight:
            seg.rise_mm = 0.0
    elif kind in ('CURVE_LEFT', 'CURVE_RIGHT'):
        was_curve = seg.kind == 'CURVE'
        seg.kind = 'CURVE'
        seg.curve_direction = 'LEFT' if kind == 'CURVE_LEFT' else 'RIGHT'
        if not was_curve:
            seg.curve_angle_deg = catalog.curve_default_angle_deg
            seg.curve_radius = catalog.curve_default_radius_id
    elif kind == 'SPIRAL':
        was_spiral = seg.kind == 'SPIRAL'
        seg.kind = 'SPIRAL'
        if not was_spiral:
            seg.spiral_turns = 1.0
            seg.rise_mm = 3000.0
            seg.curve_direction = 'LEFT'
            seg.curve_radius = catalog.curve_default_radius_id
    elif kind == 'MODULE':
        if seg.kind != 'MODULE':
            seg.kind = 'MODULE'
            seg.module_kind = 'RAT'
        seg.length_mm = catalog.modules[seg.module_kind].length_mm


class CONVEYOR_OT_segment_add(_LineOperator, bpy.types.Operator):
    bl_idname = "conveyor.segment_add"
    bl_label = "Add / Change Segment"
    bl_description = (
        "With the last row selected: extend the line with this piece (before the first one when the keys are set to Start). "
        "With any other row selected: change that piece into this kind"
    )
    bl_options = {'REGISTER', 'UNDO'}

    kind: bpy.props.EnumProperty(
        items=[
            ('STRAIGHT', "Straight", "A level straight; drag the arrow at its end to raise or lower it"),
            ('CURVE_LEFT', "Curve Left", "Turn the line 90° to the left (change the angle below the list)"),
            ('CURVE_RIGHT', "Curve Right", "Turn the line 90° to the right (change the angle below the list)"),
            ('MODULE', "Module", "Right-angle transfer, merge, diverter, buffer or lift"),
            ('SPIRAL', "Spiral", "Helical spiral: set turns, radius and height below"),
        ],
        default='STRAIGHT',
    )
    # For MODULE: which module (empty = keep / the catalog default) and, for a RAT, its exit side.
    module: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    exit_side: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})

    _WHAT = {'STRAIGHT': "a straight", 'CURVE_LEFT': "a left curve", 'CURVE_RIGHT': "a right curve", 'SPIRAL': "a spiral"}
    _MODULES = {'RAT': "a right-angle transfer", 'LIFT': "a vertical lift", 'BUFFER': "a buffer", 'ARB': "an angled-roller turn",
                'MERGE': "a merge junction", 'DIVERTER': "a diverter", 'WRAPPER': "a pallet wrapper"}

    @classmethod
    def description(cls, context, properties):
        what = cls._MODULES.get(properties.module, "a module") if properties.kind == 'MODULE' else cls._WHAT.get(properties.kind, "a piece")
        obj = _active_line(context)
        if obj is not None and not adds_piece(obj.conveyor_line):
            return f"Turn piece {obj.conveyor_line.active_segment_index + 1} into {what}"
        hint = ", then pick its angle below" if properties.kind in ('CURVE_LEFT', 'CURVE_RIGHT') else ""
        if obj is not None and obj.conveyor_line.grow_at == 'START':
            seen = " (left and right as you look back along the line)" if properties.kind in ('CURVE_LEFT', 'CURVE_RIGHT') else ""
            return f"Add {what} to the start of the line{hint}{seen}"
        return f"Add {what} to the end of the line{hint}"

    def _configure(self, seg, catalog) -> None:
        """A fresh piece into what the key names. Left / right, a RAT's exit
        side and climb / descend always mean the GOODS' left, right, up and
        down, wherever the piece is added: a piece put in front of the line
        (keys set to Start) is not mirrored. (It was, "as the user sees it
        looking back", and a prepended Curve Left turned the goods right:
        user, 2026-10-12, "when we add from the back things work opposite".)"""
        _apply_kind(seg, self.kind, catalog)
        if self.kind == 'MODULE' and self.module in catalog.modules:
            seg.module_kind = self.module
            seg.length_mm = catalog.modules[self.module].length_mm
            if self.module == 'RAT' and self.exit_side in ('STRAIGHT', 'LEFT', 'RIGHT'):
                seg.module_exit = self.exit_side
            if self.module == 'LIFT' and seg.rise_mm <= 0.0:
                seg.rise_mm = LIFT_DEFAULT_RISE_MM  # a lift of 0 m is no lift (it was built 0.3 m tall and listed as 0.00 m)

    def execute(self, context):
        obj = _active_line(context)
        settings = obj.conveyor_line
        catalog = loader.get_segment_catalog()
        adding = adds_piece(settings) or len(settings.segments) == 0
        if adding and settings.grow_at == 'START' and len(settings.segments) > 0:
            return self._prepend(context, obj, catalog)
        with suspended_rebuild():
            if adding:
                seg = settings.segments.add()
                seg.kind = 'STRAIGHT'  # neutral start so _apply_kind sees a fresh piece
                seg.length_mm = catalog.straight_default_mm
                settings.active_segment_index = len(settings.segments) - 1
            else:
                seg = settings.segments[settings.active_segment_index]
            self._configure(seg, catalog)
        build_line(context, obj)
        return {'FINISHED'}

    def _prepend(self, context, obj, catalog):
        """The piece goes in FRONT of the first one and the line grows
        backwards: the object's origin moves back so that everything already
        built stays exactly where it is (model/segments.prepend_pose). Lines
        docked on this one re-sync, since their arcs along it moved by the
        new piece's length (user request 2026-10-09: "add conveyors from the
        start too and go backwards")."""
        from .build_line import START_ANCHOR_KEY
        from .detect_junctions import origin_dock

        settings = obj.conveyor_line
        dock = origin_dock(context, obj)
        if dock is not None:
            self.report({'WARNING'}, f"{obj.name} starts on a junction of {dock[0].name}: detach it first to grow it backwards")
            return {'CANCELLED'}
        old_own = float(settings.get("own_length_m", 0.0))
        with suspended_rebuild():
            seg = settings.segments.add()
            seg.kind = 'STRAIGHT'
            seg.length_mm = catalog.straight_default_mm
            self._configure(seg, catalog)  # the goods' left / right, like at the end
            settings.segments.move(len(settings.segments) - 1, 0)
            settings.active_segment_index = 0
            # The new first piece must END where the line used to start: the
            # build's start anchor (build_line._keep_start_anchor) moves the
            # object back by the new piece and re-syncs the docked lines.
            settings[START_ANCHOR_KEY] = (0.0, 0.0, 0.0, 0.0)
        build_line(context, obj)
        # The goods stay where they were: the origin moved back by the new
        # piece, so the stream's clock is set back by that length
        # (operators/stream.py reads the shift) -- inputs only, no rebuild.
        grown = float(settings.get("own_length_m", 0.0)) - old_own
        if grown > 1e-6:
            settings["stream_shift_m"] = float(settings.get("stream_shift_m", 0.0)) + grown
            from .build_line import _push_inputs, _refresh_stream_peers

            _push_inputs(context, obj)
            _refresh_stream_peers(context, obj)
        return {'FINISHED'}


class CONVEYOR_OT_set_spiral_height(_LineOperator, bpy.types.Operator):
    bl_idname = "conveyor.set_spiral_height"
    bl_label = "Set Spiral Height"
    bl_description = "How much the active spiral climbs (or, when it winds down, descends)"
    bl_options = {'REGISTER', 'UNDO'}

    height_m: bpy.props.FloatProperty(name="Height", default=3.0, min=0.1, max=50.0)

    @classmethod
    def poll(cls, context):
        return CONVEYOR_OT_set_spiral_angle.poll(context)

    def execute(self, context):
        seg = _active_line(context).conveyor_line.segments[_active_line(context).conveyor_line.active_segment_index]
        seg.rise_mm = float(self.height_m) * 1000.0 * (-1.0 if seg.rise_mm < 0.0 else 1.0)  # keeps up / down
        return {'FINISHED'}


class CONVEYOR_OT_spiral_flip(_LineOperator, bpy.types.Operator):
    bl_idname = "conveyor.spiral_flip"
    bl_label = "Spiral Down / Up"
    bl_description = "Wind the active spiral the other way: down from an upper floor, or up again"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return CONVEYOR_OT_set_spiral_angle.poll(context)

    def execute(self, context):
        seg = _active_line(context).conveyor_line.segments[_active_line(context).conveyor_line.active_segment_index]
        seg.rise_mm = -float(seg.rise_mm) if abs(seg.rise_mm) > 1e-6 else -3000.0
        return {'FINISHED'}


class CONVEYOR_OT_set_straight_length(_LineOperator, bpy.types.Operator):
    bl_idname = "conveyor.set_straight_length"
    bl_label = "Set Straight Length"
    bl_description = "Set the active straight's length"
    bl_options = {'REGISTER', 'UNDO'}

    length_m: bpy.props.FloatProperty(name="Length", default=3.0, min=0.15, soft_max=30.0, unit='LENGTH')

    @classmethod
    def poll(cls, context):
        obj = _active_line(context)
        if obj is None:
            return False
        settings = obj.conveyor_line
        i = settings.active_segment_index
        return 0 <= i < len(settings.segments) and settings.segments[i].kind == 'STRAIGHT'

    def execute(self, context):
        obj = _active_line(context)
        settings = obj.conveyor_line
        settings.segments[settings.active_segment_index].length_mm = self.length_m * 1000.0  # snaps and rebuilds
        return {'FINISHED'}


class CONVEYOR_OT_set_spiral_angle(_LineOperator, bpy.types.Operator):
    bl_idname = "conveyor.set_spiral_angle"
    bl_label = "Set Spiral Rotation"
    bl_description = "Set how far the active spiral turns in total"
    bl_options = {'REGISTER', 'UNDO'}

    angle: bpy.props.IntProperty(name="Rotation", default=360, min=30, max=7200)

    @classmethod
    def poll(cls, context):
        obj = _active_line(context)
        if obj is None:
            return False
        settings = obj.conveyor_line
        i = settings.active_segment_index
        return 0 <= i < len(settings.segments) and settings.segments[i].kind == 'SPIRAL'

    def execute(self, context):
        obj = _active_line(context)
        settings = obj.conveyor_line
        seg = settings.segments[settings.active_segment_index]
        seg.spiral_angle_deg = float(self.angle)
        return {'FINISHED'}


class CONVEYOR_OT_set_curve_angle(_LineOperator, bpy.types.Operator):
    bl_idname = "conveyor.set_curve_angle"
    bl_label = "Set Curve Angle"
    bl_description = "Set the active curve's turn angle"
    bl_options = {'REGISTER', 'UNDO'}

    angle: bpy.props.IntProperty(name="Angle", default=90, min=CURVE_ANGLE_MIN_DEG, max=CURVE_ANGLE_MAX_DEG)

    @classmethod
    def poll(cls, context):
        obj = _active_line(context)
        if obj is None:
            return False
        settings = obj.conveyor_line
        i = settings.active_segment_index
        return 0 <= i < len(settings.segments) and settings.segments[i].kind == 'CURVE'

    def execute(self, context):
        obj = _active_line(context)
        settings = obj.conveyor_line
        seg = settings.segments[settings.active_segment_index]
        with suspended_rebuild():
            seg.curve_angle_deg = self.angle
        build_line(context, obj)
        return {'FINISHED'}


class CONVEYOR_OT_segment_remove(_LineOperator, bpy.types.Operator):
    bl_idname = "conveyor.segment_remove"
    bl_label = "Remove Segment"
    bl_description = "Remove the active segment"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = _active_line(context)
        settings = obj.conveyor_line
        if len(settings.segments) <= 1:
            self.report({'WARNING'}, "A line needs at least one segment")
            return {'CANCELLED'}
        i = settings.active_segment_index
        settings.segments.remove(i)
        settings.active_segment_index = max(0, min(i, len(settings.segments) - 1))
        build_line(context, obj)
        return {'FINISHED'}


class CONVEYOR_OT_segment_move(_LineOperator, bpy.types.Operator):
    bl_idname = "conveyor.segment_move"
    bl_label = "Move Segment"
    bl_description = "Move the active segment up or down the chain"
    bl_options = {'REGISTER', 'UNDO'}

    direction: bpy.props.EnumProperty(items=[('UP', "Up", ""), ('DOWN', "Down", "")], default='UP')

    def execute(self, context):
        obj = _active_line(context)
        settings = obj.conveyor_line
        i = settings.active_segment_index
        j = i - 1 if self.direction == 'UP' else i + 1
        if j < 0 or j >= len(settings.segments):
            return {'CANCELLED'}
        settings.segments.move(i, j)
        settings.active_segment_index = j
        build_line(context, obj)
        return {'FINISHED'}


class CONVEYOR_OT_segment_duplicate(_LineOperator, bpy.types.Operator):
    bl_idname = "conveyor.segment_duplicate"
    bl_label = "Duplicate Segment"
    bl_description = "Insert a copy of the active segment right after it"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = _active_line(context)
        settings = obj.conveyor_line
        i = settings.active_segment_index
        with suspended_rebuild():
            values = segment_values(settings.segments[i])
            apply_segment_values(settings.segments.add(), values)
            settings.segments.move(len(settings.segments) - 1, i + 1)
            settings.active_segment_index = i + 1
        build_line(context, obj)
        return {'FINISHED'}


classes = (
    CONVEYOR_OT_set_straight_length,
    CONVEYOR_OT_set_spiral_angle, CONVEYOR_OT_set_spiral_height, CONVEYOR_OT_spiral_flip,
    CONVEYOR_OT_segment_add,
    CONVEYOR_OT_set_curve_angle,
    CONVEYOR_OT_segment_remove,
    CONVEYOR_OT_segment_move,
    CONVEYOR_OT_segment_duplicate,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
