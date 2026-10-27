"""Per-stand editing (2.14: "delete certain feet"; 2.26.3: and add them).
Stands are planned in model/legs.plan_stands. A stand the user takes out is
kept on its piece, as metres from the piece's start (the piece's own
`removed_stands` list), so adding, deleting or reordering pieces and growing
the line backwards carry it along; on every build each spot takes out the
stand nearest to it (model/legs: within half the spacing), so the spot stays
clear when the stands are spaced anew. A stand the user adds (a + in the
middle of a gap between two stands) is kept the same way, in the piece's
`added_stands` list, and stands exactly there. The buttons in the viewport
(ui/stands.py) call the operators here: a - on every stand takes it out (an
added one is simply dropped again), a + on a stand taken out puts it back."""
from __future__ import annotations

import bpy

SEG_KEY = "removed_stands"  # on each piece: metres from the piece's start of each stand taken out
ADD_KEY = "added_stands"  # on each piece: metres from the piece's start of each stand the user added
ADDED_REACH_M = 0.06  # a - on a stand this close to an added record drops it (a post: the plan may move one that far inside a piece's end)


def stand_records(obj, key: str = SEG_KEY) -> list[tuple[int, int, float]]:
    """(piece index, index in that piece's list, metres from the piece's start)
    of the stands taken out (`key` ADD_KEY: of the stands added)."""
    out = []
    for p, seg in enumerate(obj.conveyor_line.segments):
        for i, off in enumerate(list(seg.get(key, []) or [])):
            out.append((p, i, float(off)))
    return out


def removed_spots(obj, starts, key: str = SEG_KEY) -> tuple[list[float], list[tuple[int, int]]]:
    """The spots as arc lengths along the line, and (piece, index) for each."""
    arcs, refs = [], []
    for p, i, off in stand_records(obj, key):
        if 0 <= p < len(starts):
            arcs.append(float(starts[p]) + off)
            refs.append((p, i))
    return arcs, refs


def _set(seg, values, key: str = SEG_KEY) -> None:
    if values:
        seg[key] = [round(float(v), 4) for v in values]
    elif key in seg:
        del seg[key]


def _starts(obj) -> list[float]:
    settings = obj.conveyor_line
    return [float(s) for s in (settings.get("piece_starts", []) or [])][:len(settings.segments)]


def _piece_at(starts, arc: float) -> int:
    return max(k for k, s in enumerate(starts) if s <= arc + 1e-9) if arc >= starts[0] else 0


def _line(context, name: str):
    obj = context.scene.objects.get(name) if name else context.active_object
    try:
        if obj is not None and obj.type == 'CURVES' and obj.conveyor_line.is_conveyor_line:
            return obj
    except Exception:
        pass
    return None


class CONVEYOR_OT_stand_remove(bpy.types.Operator):
    bl_idname = "conveyor.stand_remove"
    bl_label = "Remove Stand"
    bl_description = "Take this stand out (a walkway, a machine under the line). It stays out when the line changes; the Line panel puts it back"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    line: bpy.props.StringProperty(options={'SKIP_SAVE'})
    arc: bpy.props.FloatProperty(options={'SKIP_SAVE'})  # metres along the line

    def execute(self, context):
        from .build_line import build_line

        obj = _line(context, self.line)
        if obj is None:
            return {'CANCELLED'}
        settings = obj.conveyor_line
        starts = _starts(obj)
        if not starts:
            return {'CANCELLED'}
        arcs, refs = removed_spots(obj, starts, ADD_KEY)
        near = min(((abs(a - self.arc), p, i) for a, (p, i) in zip(arcs, refs)), default=None)
        if near is not None and near[0] < ADDED_REACH_M:  # a stand the user added: drop its record
            _d, p, i = near
            seg = settings.segments[p]
            values = list(seg.get(ADD_KEY, []) or [])
            values.pop(i)
            _set(seg, values, ADD_KEY)
            build_line(context, obj)
            return {'FINISHED'}
        p = _piece_at(starts, self.arc)
        seg = settings.segments[p]
        _set(seg, list(seg.get(SEG_KEY, []) or []) + [self.arc - starts[p]])
        build_line(context, obj)
        return {'FINISHED'}


class CONVEYOR_OT_stand_add(bpy.types.Operator):
    bl_idname = "conveyor.stand_add"
    bl_label = "Add Stand"
    bl_description = "Add a stand here (under a heavy load, a joint, a long span). It stays when the line changes; its - takes it away again"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    line: bpy.props.StringProperty(options={'SKIP_SAVE'})
    arc: bpy.props.FloatProperty(options={'SKIP_SAVE'})  # metres along the line

    def execute(self, context):
        from .build_line import build_line

        obj = _line(context, self.line)
        starts = _starts(obj) if obj is not None else []
        if not starts:
            return {'CANCELLED'}
        p = _piece_at(starts, self.arc)
        seg = obj.conveyor_line.segments[p]
        _set(seg, list(seg.get(ADD_KEY, []) or []) + [self.arc - starts[p]], ADD_KEY)
        build_line(context, obj)
        return {'FINISHED'}


class CONVEYOR_OT_stand_restore(bpy.types.Operator):
    bl_idname = "conveyor.stand_restore"
    bl_label = "Restore Stand"
    bl_description = "Put this stand back"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    line: bpy.props.StringProperty(options={'SKIP_SAVE'})
    piece: bpy.props.IntProperty(default=-1, options={'SKIP_SAVE'})
    index: bpy.props.IntProperty(default=-1, options={'SKIP_SAVE'})

    def execute(self, context):
        from .build_line import build_line

        obj = _line(context, self.line)
        if obj is None or not 0 <= self.piece < len(obj.conveyor_line.segments):
            return {'CANCELLED'}
        seg = obj.conveyor_line.segments[self.piece]
        values = list(seg.get(SEG_KEY, []) or [])
        if not 0 <= self.index < len(values):
            return {'CANCELLED'}
        values.pop(self.index)
        _set(seg, values)
        build_line(context, obj)
        return {'FINISHED'}


class CONVEYOR_OT_stands_restore_all(bpy.types.Operator):
    bl_idname = "conveyor.stands_restore_all"
    bl_label = "Reset Stands"
    bl_description = "Put back every stand taken out of this line and drop the ones added: the stands follow Legs every again"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    line: bpy.props.StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        from .build_line import build_line

        obj = _line(context, self.line)
        if obj is None or not (stand_records(obj) or stand_records(obj, ADD_KEY)):
            return {'CANCELLED'}
        for seg in obj.conveyor_line.segments:
            _set(seg, [])
            _set(seg, [], ADD_KEY)
        build_line(context, obj)
        return {'FINISHED'}


classes = (CONVEYOR_OT_stand_remove, CONVEYOR_OT_stand_add, CONVEYOR_OT_stand_restore, CONVEYOR_OT_stands_restore_all)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
