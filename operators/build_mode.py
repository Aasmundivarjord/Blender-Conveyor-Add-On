"""Build mode: right after New Line at Cursor, or from the panel's button, the PLAIN arrow keys build the
selected line -- up a straight, left / right a curve, down the piece library (the modules) -- Backspace
takes the last piece off again, Enter or Esc ends. Shift + arrows tune the piece just added (a
straight's length, a curve's radius and turn), Ctrl or Cmd + up / down its height. Everything else
passes through, so the view still orbits, zooms and pans, and Blender's own arrow keys (frame steps)
are back the moment it ends; Alt + arrows work as before (ui/segment_edit). The keys themselves:
model/build_keys.py.

Only the user's click starts it (New Line at Cursor, from End, at a Junction: operators/new_line
then_build; the panel button): another add-on's new_line call (R6 / R21) runs EXEC and never enters
build mode. Every key is one undo step, so Ctrl + Z (passed through) takes back one piece."""
from __future__ import annotations

import bpy

from ..config import loader
from ..model.build_keys import HINT, adjust, key_action
from ..props.line_settings import segment_curve_angle_deg, suspended_rebuild
from .segments import _active_line

RUNNING = {"line": ""}  # the line in build mode ("" = none): the panel lights its button


def do_action(context, obj, action: str) -> bool:
    """One build-mode step on `obj`, the active line (the modal's and the tests' way in): add a piece at
    the growing end, take the end piece off, or open the piece library. True when it did something."""
    settings = obj.conveyor_line
    n = len(settings.segments)
    at_start = settings.grow_at == 'START' and n > 0
    if action.startswith("add:") or action == "more":
        settings.active_segment_index = 0 if at_start else n - 1  # the keys ADD at the growing end, never replace
        if action == "more":
            return 'CANCELLED' not in bpy.ops.conveyor.piece_library('INVOKE_DEFAULT')
        return 'FINISHED' in bpy.ops.conveyor.segment_add('EXEC_DEFAULT', True, kind=action[4:])  # True: one undo step a key
    if action == "remove":
        if n <= 1 or at_start:  # a line keeps one piece; off the start the whole line would shift
            return False
        settings.active_segment_index = n - 1
        return 'FINISHED' in bpy.ops.conveyor.segment_remove('EXEC_DEFAULT', True)
    if action.startswith("adjust:") and n:
        settings.active_segment_index = 0 if at_start else n - 1  # the piece just added: the growing end
        return 'FINISHED' in bpy.ops.conveyor.adjust_piece('EXEC_DEFAULT', True, step=action[7:])  # one undo step a key
    return False


def piece_values(seg) -> dict:
    """What model/build_keys.adjust reads of a piece."""
    return {"kind": seg.kind, "module": seg.module_kind if seg.kind == 'MODULE' else "", "length_mm": float(seg.length_mm),
            "angle_deg": float(segment_curve_angle_deg(seg)) if seg.kind == 'CURVE' else 0.0, "direction": seg.curve_direction,
            "radius_id": seg.curve_radius, "custom_radius_mm": float(seg.custom_radius_mm), "rise_mm": float(seg.rise_mm)}


class CONVEYOR_OT_adjust_piece(bpy.types.Operator):
    """Build mode's Shift / Ctrl keys on the active piece (the one just added): model/build_keys.adjust."""
    bl_idname = "conveyor.adjust_piece"
    bl_label = "Adjust Piece"
    bl_description = "Lengthen or shorten, steer or raise the active piece one step"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    step: bpy.props.EnumProperty(items=[(s, s.title(), "") for s in ("longer", "shorter", "left", "right", "up", "down")],
                                 options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        obj = _active_line(context)
        return obj is not None and 0 <= obj.conveyor_line.active_segment_index < len(obj.conveyor_line.segments)

    def execute(self, context):
        from .build_line import build_line

        obj = _active_line(context)
        settings = obj.conveyor_line
        seg = settings.segments[settings.active_segment_index]
        radii = [(r.id, r.radius_mm, r.system) for r in loader.get_segment_catalog().curve_radii]
        changes, note = adjust(piece_values(seg), self.step, radii)
        if changes is None:
            if note:
                self.report({'INFO'}, note)
            return {'CANCELLED'}
        with suspended_rebuild():
            for name, value in changes.items():
                setattr(seg, name, value)
        build_line(context, obj)
        self.report({'INFO'}, f"Piece {settings.active_segment_index + 1}: {note}")
        return {'FINISHED'}


def _status(context, text) -> None:
    try:
        context.workspace.status_text_set(text)
    except Exception:
        pass


def _redraw(context) -> None:
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


class CONVEYOR_OT_build_mode(bpy.types.Operator):
    bl_idname = "conveyor.build_mode"
    bl_label = "Build with Arrow Keys"
    bl_description = ("Build the selected line with the plain arrow keys: up adds a straight, left / right a curve, "
                      "down opens the piece library. Shift + arrows adjust the piece just added, Ctrl (Cmd) + up / down "
                      "its height. Backspace takes the last piece off, Enter or Esc ends")

    line: bpy.props.StringProperty(options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return _active_line(context) is not None and context.window is not None

    def invoke(self, context, event):
        obj = _active_line(context)
        if RUNNING["line"] == obj.name:  # the button again while building: that ends it
            RUNNING["line"] = ""
            _status(context, None)
            _redraw(context)
            return {'CANCELLED'}
        self.line = obj.name
        RUNNING["line"] = obj.name
        context.window_manager.modal_handler_add(self)
        _status(context, HINT)
        _redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        obj = context.view_layer.objects.active
        if RUNNING["line"] != self.line or obj is None or obj.name != self.line or not obj.conveyor_line.is_conveyor_line:
            return self._end(context)  # ended from the panel, another object selected, or the line gone
        action = key_action(event.type, event.value, event.alt, event.ctrl, event.shift, event.oskey)
        if action is None:
            return {'PASS_THROUGH'}
        if action == "end":
            return self._end(context)
        if not do_action(context, obj, action) and action == "remove":
            self.report({'INFO'}, "Backspace takes pieces off the end of a line, and a line keeps one piece")
        _redraw(context)
        return {'RUNNING_MODAL'}

    def _end(self, context):
        if RUNNING["line"] == self.line:
            RUNNING["line"] = ""
        _status(context, None)
        _redraw(context)
        return {'FINISHED'}


classes = (CONVEYOR_OT_adjust_piece, CONVEYOR_OT_build_mode)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    RUNNING["line"] = ""
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
