"""The junction chooser: angle, transfer type, in/out and detach for the
junction a line's ORIGIN sits on (detect_junctions._sync_origin). Reached
from the icon floating over the junction (ui/gizmos.py) and from the
Builder panel.

Angle buttons SWING the attached line about its origin (the junction) to
exactly the chosen angle, like R with typed degrees: the line is straight
at that angle, the junction stays put. (Until 2026-09-30 they kept the
line's direction and added a lead-in curve; a 15 degree lead-in on a 75
degree line read as "says 90, isn't 90". Lead-ins left by that version are
removed and their length given back to the first straight.)
"""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

from ..config import loader, units

LEAD_KEY = "conveyor_lead_in"  # on the lead-in curve segment the chooser manages
ANGLES = (15, 30, 45, 60, 75, 90)
TECH_ICONS = {"SKEW": 'MOD_ARRAY', "BELT": 'ALIGN_JUSTIFY', "POPUP": 'MOD_PARTICLE_INSTANCE', "CHAIN": 'LINKED',
              "STRIP": 'SORT_DESC', "ARB": 'MOD_WIREFRAME', "PUSHER": 'FORWARD'}


def attached_junction(context, obj):
    """(main line, module index, junction segment, side) of the junction the
    origin of `obj` sits on, or None."""
    from .detect_junctions import _docked_side, origin_dock

    if obj is None or obj.type != 'CURVES' or not obj.conveyor_line.is_conveyor_line:
        return None
    dock = origin_dock(context, obj)
    if dock is None:
        return None
    main, index = dock
    seg = main.conveyor_line.segments[index]
    return main, index, seg, _docked_side(seg, obj.name)


def _lead_in(settings):
    segs = settings.segments
    return segs[0] if len(segs) > 1 and segs[0].kind == 'CURVE' and segs[0].get(LEAD_KEY) else None


def _flow_heading_at(context, main, index) -> float:
    """World FLOW heading of `main` at the start of junction `index`."""
    from .detect_junctions import _line_data, flow_reversed

    frames = _line_data(context, main)[4]
    return main.rotation_euler.z + frames[index][0].heading + (math.pi if flow_reversed(main) else 0.0)


def origin_heading(flow_h: float, side: str, main_reversed: bool, role: str, angle_deg: float) -> float:
    """World heading the attached line must LEAVE its origin with for a
    junction of `role` / `angle_deg` on `side` of a main line flowing at
    `flow_h` (the frame conventions of detect_junctions._module_face_world)."""
    theta = math.radians(angle_deg)
    flow_right = (side == 'RIGHT') != main_reversed
    turn = theta if flow_right else -theta
    dock_h = flow_h + (turn if role == 'MERGE' else -turn)  # the docked line's FLOW heading at the face
    return dock_h + (math.pi if role == 'MERGE' else 0.0)  # a merge flows INTO the face: its body points back


def set_junction(context, obj, angle: int | None = None, tech: str | None = None, role: str | None = None) -> str:
    """Applies the chooser: swings the line about its origin to the angle
    (and role), then sets the transfer type. Returns '' or a message."""
    from ..props.line_settings import segment_curve_radius_mm, snap_length_mm, suspended_rebuild
    from . import detect_junctions as dj
    from .build_line import build_line, resolve_width_mm

    hit = attached_junction(context, obj)
    if hit is None:
        return "The line's origin is not attached to another line"
    main, index, jseg, side = hit
    scene = context.scene
    settings = obj.conveyor_line
    techs = loader.get_technologies()
    old_role = jseg.module_kind
    role = role or old_role
    if tech and tech in techs:
        spec = techs[tech]
        if role not in spec.roles:
            role = spec.roles[0]
        if angle is None and int(jseg.merge_angle) not in spec.angles:
            angle = min(spec.angles, key=lambda a: abs(a - int(jseg.merge_angle)))
    angle = int(angle if angle else int(jseg.merge_angle))
    if tech and tech in techs and angle not in techs[tech].angles:
        angle = min(techs[tech].angles, key=lambda a: abs(a - angle))

    origin_before = dj._world_matrix(obj) @ Vector((0.0, 0.0, 0.0))
    yaw_now = obj.rotation_euler.z
    yaw_target = origin_heading(_flow_heading_at(context, main, index), side, dj.flow_reversed(main), role, angle)
    with suspended_rebuild():
        lead = _lead_in(settings)
        if lead is not None:
            # A lead-in from the old chooser: the straight after it gets its
            # length back (the line keeps its reach), then it goes.
            width_m = units.mm_to_bu(resolve_width_mm(settings), scene)
            arc_mm = (segment_curve_radius_mm(lead) + units.bu_to_mm(width_m, scene) / 2.0) * math.radians(lead.curve_angle_deg)
            body = settings.segments[1]
            if body.kind == 'STRAIGHT':
                body["length_mm"] = snap_length_mm(body.length_mm + arc_mm)
            settings.segments.remove(0)
            settings.active_segment_index = max(0, settings.active_segment_index - 1)
        if role != old_role:
            # The flow flips: everything this line docked in its old role goes.
            dj._release_source(context, obj.name)
            dj._clear_branch(settings)
            dj._clear_continuation(settings)
        settings["reverse"] = role == 'MERGE'
        settings[dj._REVERSE_KEY] = role == 'MERGE'
        settings[dj._ROLE_KEY] = role
    obj.rotation_euler.z = yaw_now + dj._wrap(yaw_target - yaw_now)
    build_line(context, obj)
    hit = attached_junction(context, obj)
    if hit is None:
        return dj.attach_note(obj) or "The junction did not fit here"
    main, index, jseg, _side = hit
    if tech and jseg.junction_tech != tech:
        jseg.junction_tech = tech  # update callback rebuilds the main line
    # The junction slides when the main line has no room for it right there
    # (neighbouring junctions, a curve): the line moves with it. (Across the
    # main line the origin always moves a little: an angled face sits
    # further out than a square one.)
    along = dj._forward(_flow_heading_at(context, main, index))
    slid = abs((dj._world_matrix(obj) @ Vector((0.0, 0.0, 0.0)) - origin_before).dot(along))
    if slid > 0.05:
        return f"No room on {main.name} right there: the junction slid {slid:.2f} m along it (and the line with it)"
    return ""


def _far_end(context, obj) -> Vector:
    from . import detect_junctions as dj

    spine = dj._line_data(context, obj)[0]
    end = spine.pose_at(len(spine) - 1)
    return dj._world_matrix(obj) @ Vector((end.x, end.y, end.z))


class CONVEYOR_OT_junction_set(bpy.types.Operator):
    bl_idname = "conveyor.junction_set"
    bl_label = "Set Junction"
    bl_description = "Change the junction this line's origin sits on"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    line: bpy.props.StringProperty()
    angle: bpy.props.IntProperty(default=0, min=0, max=90)
    tech: bpy.props.StringProperty(default="")
    action: bpy.props.EnumProperty(items=[('NONE', "None", ""), ('SWAP', "Swap in / out", ""), ('DETACH', "Detach", "")],
                                   default='NONE')
    role: bpy.props.EnumProperty(items=[('KEEP', "Keep", ""), ('MERGE', "Goods in", ""), ('DIVERTER', "Goods out", "")], default='KEEP')

    @classmethod
    def description(cls, context, properties):
        if properties.role == 'MERGE':
            return "This line feeds INTO the main line: its goods merge onto it (the line swings to the mirrored angle if needed)"
        if properties.role == 'DIVERTER':
            return "This line takes goods OUT of the main line: its share of the main line's throughput (the line swings to the mirrored angle if needed)"
        if properties.action == 'SWAP':
            return "Turn a merge into an outfeed or back: the line swings to the mirrored angle"
        if properties.action == 'DETACH':
            return "Undock this line; it stays where it is"
        if properties.tech:
            spec = loader.get_technologies().get(properties.tech)
            return spec.note if spec else "Transfer type"
        if properties.angle:
            return f"Swing this line about its junction to exactly {properties.angle}° (like R)"
        return cls.bl_description

    def execute(self, context):
        obj = bpy.data.objects.get(self.line) or context.active_object
        if obj is None:
            return {'CANCELLED'}
        if self.action == 'DETACH':
            from .detect_junctions import _undock

            obj.conveyor_line.dock_enabled = False
            _undock(context, obj)
            return {'FINISHED'}
        role = None if self.role == 'KEEP' else self.role
        if self.action == 'SWAP':
            hit = attached_junction(context, obj)
            if hit is None:
                return {'CANCELLED'}
            role = 'DIVERTER' if hit[2].module_kind == 'MERGE' else 'MERGE'
        if role is not None:
            hit = attached_junction(context, obj)
            if hit is not None and hit[2].module_kind == role and not (self.angle or self.tech):
                return {'FINISHED'}  # already so
        message = set_junction(context, obj, self.angle or None, self.tech or None, role)
        if message:
            self.report({'INFO'} if attached_junction(context, obj) is not None else {'WARNING'}, message)
        return {'FINISHED'}


def draw_chooser(layout, context, obj, compact: bool = False) -> None:
    """Angle buttons, transfer types and in/out for the junction under the
    origin of `obj` (shared by the popup and the Builder panel)."""
    from .build_line import resolve_junction_tech

    hit = attached_junction(context, obj)
    if hit is None:
        layout.label(text="Not attached: move the origin onto a line", icon='UNLINKED')
        return
    main, _index, jseg, _side = hit
    if jseg.module_kind == 'RAT':
        # A RAT's side face: no angle, no transfer type -- just which way the goods go.
        from .detect_junctions import _line_role

        role = _line_role(obj)
        col = layout.column(align=True)
        col.label(text=f"{'Feeds' if role == 'MERGE' else 'Branches off'} the RAT on {main.name} ({_side.lower()} face)", icon='LINKED')
        row = col.row(align=True)
        op = row.operator("conveyor.junction_set", text="Goods OUT" if role == 'MERGE' else "Goods IN", icon='ARROW_LEFTRIGHT')
        op.line, op.action = obj.name, 'SWAP'
        op = row.operator("conveyor.junction_set", text="", icon='UNLINKED')
        op.line, op.action = obj.name, 'DETACH'
        return
    role = jseg.module_kind
    angle = int(jseg.merge_angle)
    used = resolve_junction_tech(jseg)
    techs = loader.get_technologies()
    col = layout.column(align=True)
    col.label(text=f"{'Merge into' if role == 'MERGE' else 'Outfeed from'} {main.name}", icon='LINKED')
    row = col.row(align=True)
    for a in ANGLES:
        op = row.operator("conveyor.junction_set", text=f"{a}°", depress=(a == angle))
        op.line, op.angle = obj.name, a
    if compact:
        # The panel: the transfer as one pull-down (the gear's popup lists them all).
        row = col.row(align=True)
        row.menu("CONVEYOR_MT_junction_tech", text=techs[used].label, icon=TECH_ICONS.get(used, 'DOT'))
        row.operator("conveyor.transfer_library", text="", icon='IMAGE_DATA')  # the transfers as pictures
        op = row.operator("conveyor.junction_set", text="", icon='ARROW_LEFTRIGHT')
        op.line, op.action = obj.name, 'SWAP'
        op = row.operator("conveyor.junction_set", text="", icon='UNLINKED')
        op.line, op.action = obj.name, 'DETACH'
        return
    col.separator()
    col.label(text="Transfer:")
    for tid, spec in techs.items():
        if role not in spec.roles:
            continue
        label = spec.label if angle in spec.angles else f"{spec.label}  ({'/'.join(str(a) for a in spec.angles) if len(spec.angles) < 3 else str(min(spec.angles)) + '–' + str(max(spec.angles))}°)"
        op = col.operator("conveyor.junction_set", text=label, icon=TECH_ICONS.get(tid, 'DOT'), depress=(tid == used))
        op.line, op.tech = obj.name, tid
    col.separator()
    row = col.row(align=True)
    op = row.operator("conveyor.junction_set", text="Goods OUT" if role == 'MERGE' else "Goods IN", icon='ARROW_LEFTRIGHT')
    op.line, op.action = obj.name, 'SWAP'
    op = row.operator("conveyor.junction_set", text="Detach", icon='UNLINKED')
    op.line, op.action = obj.name, 'DETACH'


class CONVEYOR_MT_junction_tech(bpy.types.Menu):
    """The transfer technologies of the active line's junction (the compact chooser's pull-down)."""
    bl_idname = "CONVEYOR_MT_junction_tech"
    bl_label = "Transfer"

    def draw(self, context):
        from .build_line import resolve_junction_tech

        obj = context.active_object
        hit = attached_junction(context, obj) if obj is not None else None
        if hit is None:
            return
        _main, _index, jseg, _side = hit
        angle, used = int(jseg.merge_angle), resolve_junction_tech(jseg)
        for tid, spec in loader.get_technologies().items():
            if jseg.module_kind not in spec.roles:
                continue
            label = spec.label if angle in spec.angles else f"{spec.label}  ({'/'.join(str(a) for a in spec.angles) if len(spec.angles) < 3 else str(min(spec.angles)) + '–' + str(max(spec.angles))}°)"
            op = self.layout.operator("conveyor.junction_set", text=label, icon='RADIOBUT_ON' if tid == used else TECH_ICONS.get(tid, 'DOT'))
            op.line, op.tech = obj.name, tid


class CONVEYOR_OT_junction_popup(bpy.types.Operator):
    bl_idname = "conveyor.junction_popup"
    bl_label = "Junction"
    bl_description = "Choose the merge angle and transfer type of this junction"
    bl_options = {'INTERNAL'}

    line: bpy.props.StringProperty()

    def invoke(self, context, event):
        obj = bpy.data.objects.get(self.line)
        if obj is None or attached_junction(context, obj) is None:
            return {'CANCELLED'}
        return context.window_manager.invoke_popup(self, width=280)

    def draw(self, context):
        obj = bpy.data.objects.get(self.line)
        if obj is not None:
            draw_chooser(self.layout, context, obj)

    def execute(self, context):
        return {'FINISHED'}


classes = (CONVEYOR_OT_junction_set, CONVEYOR_MT_junction_tech, CONVEYOR_OT_junction_popup)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
