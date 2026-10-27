"""Flow markers in the 3D Viewport: where the goods enter and leave every
conveyor line, drawn the way the Racks add-on marks its delivery points
(user, 2026-10-12: "I love the arrows on the rack conveyor, borrow this
for the conveyors; set throughput and direction by clicking them").

At the FLOW start and the FLOW end of every line (a reversed line's end is
its geometric start):
- a disc on the conveying surface and a fainter ring at the dock reach
  (0.6 m: a rack port or another line's junction this close snaps);
- a bar across the line's width (the join face) and a 1 m arrow along the
  goods' travel: into the line at its start, away from it at its end;
- a tag "in · 50 %" / "out · 30 %" (how full the stream is there)
with what the end is docked to.
Colours as the Racks': orange = free, blue = docked (a junction, a rack
port, a line carrying on).
A round button on each disc opens the line's flow settings (direction,
population / share, speed), so a RAT's faces are set one by one through
the lines docked on them. Shows in Solid / Wireframe shading with
overlays on while a line is selected; the Scene panel's "Flow" switch.
Snapping between these arrows and the Racks' delivery points IS the port
docking (operators/ports.py): a line's start / end within the ring of a
port docks there."""
from __future__ import annotations

import math

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

TEXT_PX = 11.0
PAD_PX = 5.0
RADIUS_PX = 4.0
TAG_RISE_PX = 22.0
TAG_STACK_PX = 20.0  # a line's tag on a rack port sits one row above the rack's own tag
LINE_PX = 1.5
DISC_M = 0.30
CAPTURE_M = 0.60  # operators/ports.MIN_REACH_M: a port this close docks the end
ARROW_M = 1.0
HEAD_M = 0.22
HEAD_HALF_M = 0.12
LIFT_M = 0.02
SEGMENTS = 32
BUTTONS = 48  # flow buttons drawn at once (two per line)

# Colours by role, resolved for the viewport's background in ui/theme.py
# (model/contrast.py): bright accents on a dark theme, deep ones on a light theme.
FREE = "orange"
LINKED = "blue"
OVER = "red"

_handle_3d = None
_handle_2d = None


def _is_line(obj) -> bool:
    try:
        return obj is not None and obj.type == 'CURVES' and bool(obj.conveyor_line.is_conveyor_line)
    except Exception:
        return False


def overlay_shown(context) -> bool:
    """Solid / Wireframe shading with overlays on and the Flow switch set."""
    try:
        if not context.scene.conveyor_settings.show_flow_markers:
            return False
        space = context.space_data
        return space is not None and space.overlay.show_overlays and space.shading.type in ('SOLID', 'WIREFRAME')
    except Exception:
        return False


def wanted(context) -> bool:
    """While a conveyor line (or a system publishing ports) is selected or active."""
    try:
        objs = list(context.selected_objects)
        if context.active_object is not None:
            objs.append(context.active_object)
    except Exception:
        return False
    return any(_is_line(o) or ("wh_ports" in o) for o in objs)


def _fwd(h: float) -> Vector:
    return Vector((-math.sin(h), math.cos(h), 0.0))


class Marker:
    __slots__ = ("line", "end", "role", "position", "travel", "width", "colour", "text", "stacked")

    def __init__(self, line, end: str, role: str, position: Vector, travel: Vector, width: float, colour, text: str, stacked: bool = False):
        self.line, self.end, self.role = line, end, role
        self.position, self.travel, self.width = position, travel, width
        self.colour, self.text, self.stacked = colour, text, stacked


def rate_text(requested: float, delivered: float) -> str:
    """One format everywhere (popup, panel, arrow tag; agreed with the Racks
    add-on, 2026-10-12): "150/h" when the flow is what the line asks for,
    "150 → 56/h" when a port's capacity caps it. (Three numbers for one
    flow -- "150 through but also 56/h" -- made no sense.)"""
    if requested <= 0.0:
        return f"{delivered:,.0f}/h" if delivered > 0.0 else ""
    if delivered + 0.5 < requested:
        return f"{requested:,.0f} → {delivered:,.0f}/h"
    return f"{requested:,.0f}/h"


def _partner(context, obj, flow_end: bool):
    """(what this end is docked to, the rack port when it is one) -- a
    line, a rack port or a line carrying on; (None, None) when free."""
    from ..operators.detect_junctions import TAIL_KEY, docked_junction, origin_dock
    from ..operators.ports import dock_at, linked_at
    from ..operators.build_line import all_lines

    s = obj.conveyor_line
    rev = bool(s.reverse)
    geometric_origin = flow_end == rev  # the flow end of a reversed line is its origin
    anchor = "origin" if geometric_origin else "end"
    hit = linked_at(context, obj, anchor)
    if hit is not None:
        system, port, _role, _a = hit
        return f"{system.name} · {port.get('id')}", port
    if dock_at(obj, anchor) is not None:
        return "a port", {}
    if geometric_origin:
        dock = origin_dock(context, obj)
        if dock is not None:
            return dock[0].name, None
        if not rev and s.get(TAIL_KEY):
            return str(s.get(TAIL_KEY)), None
    else:
        dock = docked_junction(context, obj, 'DIVERTER' if rev else 'MERGE')
        if dock is not None:
            return dock[0].name, None
        if not rev:
            child = next((o for o in all_lines(context.scene) if o != obj and o.conveyor_line.get(TAIL_KEY) == obj.name), None)
            if child is not None:
                return child.name, None
    return None, None


def markers(context) -> list:
    """Two markers per line: where its goods come in and where they go out."""
    from ..operators.build_line import all_lines, resolve_width_mm

    out = []
    for obj in all_lines(context.scene):
        s = obj.conveyor_line
        if not s.segments or not s.get("end_pose"):
            continue
        W = obj.matrix_world
        yaw = W.to_euler().z
        ex, ey, ez, hd = s.end_pose
        end_w = W @ Vector((ex, ey, ez))
        origin_w = W @ Vector((0.0, 0.0, 0.0))
        h_end = yaw + math.radians(hd)
        if s.reverse:
            start_pos, start_travel = end_w, _fwd(h_end + math.pi)
            end_pos, end_travel = origin_w, _fwd(yaw + math.pi)
        else:
            start_pos, start_travel = origin_w, _fwd(yaw)
            end_pos, end_travel = end_w, _fwd(h_end)
        width = resolve_width_mm(s) / 1000.0
        tag = list(s.get("conveyor_flow_pct", []) or [])  # the populations in effect (build_line._store_flow_tag)
        for k, (end, role, pos, travel) in enumerate((("START", "in", start_pos, start_travel), ("END", "out", end_pos, end_travel))):
            partner, port = _partner(context, obj, end == "END")
            # The tag says how full the stream is there, never a rate.
            rate = f"{float(tag[k]):.0f} %" if len(tag) == 2 and float(tag[k]) > 0.0 else ""  # wherever goods flow
            colour = LINKED if partner else FREE
            if port is not None and partner and partner != "a port":
                # The port's view, so the two add-ons' tags agree: "into Pallet Rack · aisle0_in · 150 → 56/h".
                words = [("from " if role == "in" else "into ") + partner] + ([rate] if rate else [])
            else:  # a free end or a line-to-line dock: the line's view
                words = [role] + ([rate] if rate else []) + ([("from " if role == "in" else "to ") + partner] if partner else [])
            out.append(Marker(obj, end, role, pos, travel, width, colour, " · ".join(words), stacked=port is not None))
    return out


# ------------------------------------------------------------ 3D part

def _rgba(rgb, alpha):
    return (rgb[0], rgb[1], rgb[2], alpha)


def _disc(centre, radius):
    ring = [centre + Vector((radius * math.cos(2.0 * math.pi * k / SEGMENTS), radius * math.sin(2.0 * math.pi * k / SEGMENTS), 0.0))
            for k in range(SEGMENTS)]
    tris = []
    for a, b in zip(ring, ring[1:] + ring[:1]):
        tris += [centre, a, b]
    return ring, tris


def _arrow(marker):
    """(shaft, head): an in arrow ends at the start pointing into the line, an out arrow leaves the end."""
    p = marker.position + Vector((0.0, 0.0, LIFT_M))
    d = marker.travel
    if marker.role == "in":
        tail, tip = p - d * ARROW_M, p
    else:
        tail, tip = p, p + d * ARROW_M
    side = Vector((-d.y, d.x, 0.0))
    base = tip - d * HEAD_M
    return (tail, base), (tip, base + side * HEAD_HALF_M, base - side * HEAD_HALF_M)


def _join_bar(marker):
    p = marker.position + Vector((0.0, 0.0, LIFT_M))
    d = marker.travel
    side = Vector((-d.y, d.x, 0.0))
    half = marker.width * 0.5
    return p + side * half, p - side * half


def _draw_3d():
    context = bpy.context
    if not overlay_shown(context) or not wanted(context):
        return
    items = markers(context)
    if not items:
        return
    from . import theme

    pal = theme.palette(context)
    region = context.region
    scale = context.preferences.system.ui_scale
    width = LINE_PX * scale
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    flat = gpu.shader.from_builtin('UNIFORM_COLOR')
    lines = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    lines.uniform_float("viewportSize", (region.width, region.height))
    for mk in items:
        rgb = pal[mk.colour]
        centre = mk.position + Vector((0.0, 0.0, LIFT_M))
        ring, tris = _disc(centre, DISC_M)
        flat.uniform_float("color", _rgba(rgb, 0.18 if pal["light"] else 0.14))
        batch_for_shader(flat, 'TRIS', {"pos": tris}).draw(flat)
        theme.stroke(lines, 'LINE_LOOP', ring, rgb, width, pal, alpha=0.9, scale=scale)
        outer, _t = _disc(centre, CAPTURE_M)  # the capture ring: where a line end docks
        # In the theme's ink on a light theme (a pale accent ring was the one faint mark there)
        ring_rgb, ring_alpha = (pal["stroke"], 0.8) if pal["light"] else (rgb, 0.35)
        theme.stroke(lines, 'LINE_LOOP', outer, ring_rgb, width * 0.8, pal, alpha=ring_alpha, scale=scale)
        a, b = _join_bar(mk)
        theme.stroke(lines, 'LINES', [a, b], rgb, width, pal, alpha=0.9, scale=scale)
        shaft, head = _arrow(mk)
        theme.stroke(lines, 'LINES', list(shaft), rgb, width, pal, alpha=0.9, scale=scale)
        theme.stroke(lines, 'LINE_LOOP', list(head), rgb, 1.0 * scale, pal, alpha=0.95, scale=scale)
        flat.uniform_float("color", _rgba(rgb, 0.95))
        batch_for_shader(flat, 'TRIS', {"pos": list(head)}).draw(flat)
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.blend_set('NONE')


# ------------------------------------------------------------ 2D part

def _draw_2d():
    context = bpy.context
    if not overlay_shown(context) or not wanted(context):
        return
    items = markers(context)
    if not items:
        return
    region, rv3d = context.region, context.region_data
    if region is None or rv3d is None:
        return
    from . import theme

    pal = theme.palette(context)
    scale = context.preferences.system.ui_scale
    font_id = 0
    blf.size(font_id, TEXT_PX * scale)
    pad = PAD_PX * scale
    gpu.state.blend_set('ALPHA')
    fill = gpu.shader.from_builtin('UNIFORM_COLOR')
    edge = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    edge.uniform_float("viewportSize", (region.width, region.height))
    for mk in items:
        xy = location_3d_to_region_2d(region, rv3d, mk.position)
        if xy is None:
            continue
        w, h = blf.dimensions(font_id, mk.text)
        h = max(h, TEXT_PX * scale)
        cx, cy = xy.x, xy.y + (TAG_RISE_PX + (TAG_STACK_PX if mk.stacked else 0.0)) * scale  # above the rack's own tag on a port
        x0, y0, x1, y1 = cx - w / 2.0 - pad, cy - h / 2.0 - pad * 0.7, cx + w / 2.0 + pad, cy + h / 2.0 + pad * 0.7
        rgb = pal[mk.colour]
        theme.box(fill, edge, (x0, y0, x1, y1), RADIUS_PX * scale, _rgba(rgb, 0.95), pal["box_edge"] if pal["light"] else None, scale)
        blf.position(font_id, cx - w / 2.0, cy - h / 2.0 + 1.0, 0.0)
        blf.color(font_id, *theme.text_colour(rgb))  # whichever ink reads on the tag's colour
        blf.draw(font_id, mk.text)
    gpu.state.blend_set('NONE')


# ----------------------------------------------- the buttons and the popup

class CONVEYOR_OT_flow_settings(bpy.types.Operator):
    """Direction, throughput and speed of a line, right at its arrow."""
    bl_idname = "conveyor.flow_settings"
    bl_label = "Flow"
    bl_description = "This line's flow: which way the goods go, how many an hour, how fast -- click to change"
    bl_options = {'INTERNAL'}

    line_name: bpy.props.StringProperty(options={'SKIP_SAVE'})
    end: bpy.props.EnumProperty(items=[('START', "Start", ""), ('END', "End", "")], default='START', options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if not _is_line(bpy.data.objects.get(self.line_name)):
            return {'CANCELLED'}
        return context.window_manager.invoke_popup(self, width=300)

    def draw(self, context):
        from ..operators.detect_junctions import _line_role, origin_dock, docked_junction

        obj = bpy.data.objects.get(self.line_name)
        if not _is_line(obj):
            return
        s = obj.conveyor_line
        layout = self.layout
        layout.label(text=f"{obj.name}  ·  goods {'in' if self.end == 'START' else 'out'} here", icon='EMPTY_SINGLE_ARROW')
        col = layout.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        row = col.row(align=True)
        row.label(text="Reverse  (end → start)" if s.reverse else "Forward  (start → end)", icon='LOOP_BACK' if s.reverse else 'LOOP_FORWARDS')
        row.operator("conveyor.flip_direction", text="Flip", icon='ARROW_LEFTRIGHT').line_name = obj.name
        dock = origin_dock(context, obj) or docked_junction(context, obj)
        if dock is not None:
            role = _line_role(obj)
            col.label(text=f"{'Feeds into' if role == 'MERGE' else 'Branches off'} {dock[0].name}", icon='LINKED')
            if role == 'MERGE':
                col.prop(s, "population_pct", text="Population")
            else:
                col.prop(s, "share_pct", text="Share of the master")
        else:
            col.prop(s, "population_pct", text="Population")
            col.prop(s, "speed_m_s", text="Speed (m/s)")
        col.prop(s, "populate", text="Populate", toggle=True)
        from ..operators.ports import draw_port

        draw_port(layout, context, obj)  # where it is docked, "150 → 56/h" when a port caps it, the buffer button

    def execute(self, context):
        return {'FINISHED'}


class CONVEYOR_OT_flip_direction(bpy.types.Operator):
    """Turn a line's flow round and say what that made of it."""
    bl_idname = "conveyor.flip_direction"
    bl_label = "Flip Direction"
    bl_description = "Run the goods the other way; a line docked on a junction swaps its role there (a feeder becomes a branch)"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    line_name: bpy.props.StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        from ..operators.detect_junctions import _line_role, docked_junction, origin_dock

        obj = bpy.data.objects.get(self.line_name)
        if not _is_line(obj):
            return {'CANCELLED'}
        s = obj.conveyor_line
        s.reverse = not s.reverse  # rebuilds and re-docks: the attachment takes the mirrored role
        dock = origin_dock(context, obj) or docked_junction(context, obj, 'DIVERTER' if s.reverse else 'MERGE')
        if dock is not None:
            role = _line_role(obj)
            message = f"{obj.name} now {'feeds into' if role == 'MERGE' else 'branches off'} {dock[0].name}"
        else:
            message = f"{obj.name} now runs {'end → start' if s.reverse else 'start → end'}"
        self.report({'INFO'}, message)
        try:
            context.workspace.status_text_set(message)
        except Exception:
            pass
        tag_redraw()
        return {'FINISHED'}


def _flow_button(group):
    gz = group.gizmos.new("GIZMO_GT_button_2d")
    gz.icon = 'EMPTY_SINGLE_ARROW'
    gz.draw_options = {'BACKDROP', 'OUTLINE'}
    gz.show_drag = False
    gz.color = (0.12, 0.12, 0.12)
    gz.alpha = 0.85
    gz.color_highlight = (0.45, 0.75, 1.00)
    gz.alpha_highlight = 1.0
    gz.scale_basis = 12.0
    return gz, gz.target_set_operator("conveyor.flow_settings")


class CONVEYOR_GGT_flow_markers(bpy.types.GizmoGroup):
    """A round button on every flow marker: the line's flow settings."""
    bl_idname = "CONVEYOR_GGT_flow_markers"
    bl_label = "Conveyor Flow Markers"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'PERSISTENT', 'SCALE'}

    @classmethod
    def poll(cls, context):
        return overlay_shown(context) and wanted(context)

    def setup(self, context):
        self.buttons = [_flow_button(self) for _ in range(BUTTONS)]

    def draw_prepare(self, context):
        from .theme import style_buttons

        style_buttons(self, context, "blue")
        region, rv3d = context.region, context.region_data
        items = markers(context) if (region is not None and rv3d is not None) else []
        for k, (gz, props) in enumerate(self.buttons):
            if k >= len(items):
                gz.hide = True
                continue
            mk = items[k]
            props.line_name, props.end = mk.line.name, mk.end
            xy = location_3d_to_region_2d(region, rv3d, mk.position + Vector((0.0, 0.0, LIFT_M)))
            if xy is None:
                gz.hide = True
                continue
            gz.hide = False
            gz.matrix_basis = Matrix.Translation((xy.x, xy.y, 0.0))


def tag_redraw():
    wm = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


classes = (CONVEYOR_OT_flow_settings, CONVEYOR_OT_flip_direction, CONVEYOR_GGT_flow_markers)


def register():
    global _handle_3d, _handle_2d
    for cls in classes:
        bpy.utils.register_class(cls)
    _handle_3d = bpy.types.SpaceView3D.draw_handler_add(_draw_3d, (), 'WINDOW', 'POST_VIEW')
    _handle_2d = bpy.types.SpaceView3D.draw_handler_add(_draw_2d, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _handle_3d, _handle_2d
    for handle in (_handle_3d, _handle_2d):
        if handle is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
            except Exception:
                pass
    _handle_3d = _handle_2d = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
