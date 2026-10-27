"""Elevation gizmo: a vertical arrow standing at the end of the active
straight segment. Dragging it up or down sets that straight's `rise_mm`
(it becomes an incline with nose-over transitions); the panel only shows
the result. This is the ONLY way to set elevation -- there are no incline
buttons -- because the user asked for elevation to be a direct drag.

Anchoring: the arrow's base is the segment end's x/y at the segment's START
height, so the base does not move while the rise changes and the arrow
head always sits on the actual end point (offset == rise, in Blender
units). Poses come from `settings["segment_frames"]`, cached by
operators/build_line.build_line, so a redraw never re-evaluates the chain.
"""
from __future__ import annotations

import bpy
from mathutils import Matrix, Vector

from ..config import units

RISE_SNAP_MM = 25.0
MAX_RISE_FRACTION = 0.9  # |rise| <= 0.9 * length: never steeper than ~64 deg


def _active_straight(context):
    """(object, segment, index, frame) for the active line's active straight, else None."""
    obj = context.active_object
    if obj is None or obj.type != 'CURVES' or not obj.conveyor_line.is_conveyor_line:
        return None
    if obj.mode != 'OBJECT':
        return None
    settings = obj.conveyor_line
    i = settings.active_segment_index
    if not (0 <= i < len(settings.segments)):
        return None
    seg = settings.segments[i]
    if seg.kind != 'STRAIGHT':
        return None
    frames = settings.get("segment_frames")
    if frames is None or len(frames) < 6 * (i + 1):
        return None
    return obj, seg, i, tuple(frames[6 * i:6 * i + 6])


class CONVEYOR_GGT_elevation(bpy.types.GizmoGroup):
    bl_idname = "CONVEYOR_GGT_elevation"
    bl_label = "Conveyor Elevation"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT', 'SHOW_MODAL_ALL'}

    @classmethod
    def poll(cls, context):
        return _active_straight(context) is not None

    def draw_prepare(self, context):
        """Theme-aware: a deep blue arrow on a light theme, highlighted in orange
        (white vanished on a light background)."""
        from .theme import palette

        pal = palette(context)
        for gz in self.gizmos:
            gz.color = pal["blue"]
            gz.color_highlight = pal["orange"] if pal["light"] else (1.0, 1.0, 1.0)

    def setup(self, context):
        gz = self.gizmos.new("GIZMO_GT_arrow_3d")
        gz.draw_style = 'NORMAL'
        gz.draw_options = {'STEM'}
        # Zoom-independent: `length` is in gizmo units (~75 px each). The
        # shaft rises from the anchor; the head is what the user grabs.
        gz.length = 0.9
        gz.line_width = 3.0
        gz.color = (0.25, 0.55, 1.0)
        gz.alpha = 1.0
        gz.color_highlight = (1.0, 1.0, 1.0)
        gz.alpha_highlight = 1.0
        gz.scale_basis = 1.0
        gz.use_draw_modal = True
        gz.use_draw_value = True
        gz.target_set_handler("offset", get=self._get_rise_bu, set=self._set_rise_bu)
        self._arrow = gz
        self._place(context)

    def refresh(self, context):
        self._place(context)

    def _place(self, context):
        hit = _active_straight(context)
        if hit is None:
            return
        obj, _seg, _i, (sx, sy, sz, ex, ey, ez) = hit
        base_local = Vector((ex, ey, sz))
        self._arrow.matrix_basis = Matrix.Translation(obj.matrix_world @ base_local)

    # -- target handlers (offset in Blender units along the arrow's +Z) ----

    def _get_rise_bu(self):
        hit = _active_straight(bpy.context)
        if hit is None:
            return 0.0
        _obj, seg, _i, _frame = hit
        return units.mm_to_bu(seg.rise_mm, bpy.context.scene)

    def _set_rise_bu(self, value):
        hit = _active_straight(bpy.context)
        if hit is None:
            return
        _obj, seg, _i, _frame = hit
        rise_mm = units.bu_to_mm(value, bpy.context.scene)
        rise_mm = round(rise_mm / RISE_SNAP_MM) * RISE_SNAP_MM
        limit = seg.length_mm * MAX_RISE_FRACTION
        rise_mm = max(-limit, min(limit, rise_mm))
        if abs(rise_mm) < 1e-6:
            rise_mm = 0.0
        if abs(seg.rise_mm - rise_mm) > 1e-6:
            seg.rise_mm = rise_mm  # RNA write -> update callback -> build_line


CHOOSER_LIFT_M = 0.45  # the icon floats this high above the junction (clear of the fences)


def _chooser_targets(context) -> list:
    """(line name, world point) of every junction the chooser icon shows:
    the one the ACTIVE line's origin sits on, and those on the active line
    when it is a main line that others are attached to."""
    from ..operators.detect_junctions import _world_matrix
    from ..operators.junction_edit import attached_junction

    obj = context.active_object
    if obj is None or obj.type != 'CURVES' or obj.mode != 'OBJECT' or not obj.conveyor_line.is_conveyor_line:
        return []
    names = []
    if attached_junction(context, obj) is not None:
        names.append(obj.name)
    for seg in obj.conveyor_line.segments:
        if seg.kind == 'MODULE' and seg.module_kind in ('MERGE', 'DIVERTER'):
            for name in (seg.merge_source, seg.merge_source_right):
                other = context.scene.objects.get(name) if name else None
                if other is not None and name not in names and attached_junction(context, other) is not None:
                    names.append(name)
    out = []
    for name in names:
        line = context.scene.objects[name]
        out.append((name, _world_matrix(line) @ Vector((0.0, 0.0, CHOOSER_LIFT_M))))
    return out


class CONVEYOR_GGT_junction_chooser(bpy.types.GizmoGroup):
    """A round button floating over each junction of the active line; a
    click opens the junction chooser (angle, transfer type, in/out). Screen
    space: the buttons are projected onto the junctions on every redraw, so
    they follow a line being moved and vanish when it detaches."""
    bl_idname = "CONVEYOR_GGT_junction_chooser"
    bl_label = "Conveyor Junction Chooser"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'PERSISTENT', 'SCALE'}

    @classmethod
    def poll(cls, context):
        return bool(_chooser_targets(context))

    def setup(self, context):
        self._pool = []
        self._assigned = []
        self.refresh(context)

    def refresh(self, context):
        wanted = len(_chooser_targets(context))
        while len(self._pool) < wanted:
            gz = self.gizmos.new("GIZMO_GT_button_2d")
            gz.icon = 'PREFERENCES'
            gz.draw_options = {'BACKDROP', 'OUTLINE'}
            gz.show_drag = False
            gz.color = (0.12, 0.12, 0.12)
            gz.alpha = 0.85
            gz.color_highlight = (0.28, 0.45, 0.85)
            gz.alpha_highlight = 1.0
            gz.scale_basis = 15.0
            self._pool.append(gz)
            self._assigned.append(None)

    def draw_prepare(self, context):
        from bpy_extras.view3d_utils import location_3d_to_region_2d

        from .theme import style_buttons

        style_buttons(self, context, "blue")
        targets = _chooser_targets(context)
        region, rv3d = context.region, context.region_data
        for k, gz in enumerate(self._pool):
            if k >= len(targets) or rv3d is None:
                gz.hide = True
                continue
            name, point = targets[k]
            xy = location_3d_to_region_2d(region, rv3d, point)
            if xy is None:
                gz.hide = True
                continue
            gz.hide = False
            gz.matrix_basis = Matrix.Translation((xy.x, xy.y, 0.0))
            if self._assigned[k] != name:
                props = gz.target_set_operator("conveyor.junction_popup")
                props.line = name
                self._assigned[k] = name


classes = (CONVEYOR_GGT_elevation, CONVEYOR_GGT_junction_chooser)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
