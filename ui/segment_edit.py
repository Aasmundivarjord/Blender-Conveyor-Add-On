"""Editing a line directly in the viewport (user request 2026-09-30,
"automatic" mode): while a conveyor line is the active object in Object
Mode,

  - hovering one of its pieces outlines it (a bright band around the piece);
  - a click selects it -- the same as clicking its row in the segment list
    (the orange rail sleeves show it, the panel shows its settings);
  - a drag edits it: a straight's length (catalog steps), a curve's angle
    (15 degree steps, 1 degree with Shift); Esc / right-click cancels;
  - a + button floating past the line's end opens the piece keys and the
    value strip right there (the same ones as in the panel); a + outside a
    free junction face starts another conveyor from that junction;
  - Alt + arrow keys are the piece keys: Up = straight, Left / Right = the
    curves, Down = the piece library.

Everything is read from caches build_line writes on the line (the centerline
samples with their piece index, the per-piece start poses), so hovering
never re-evaluates the chain.

Gizmo priority: the picker is a 3D gizmo that uses test_select and draws in
the background, so the elevation arrow and the junction buttons (drawn on
top of the line) keep winning when the mouse is over them.
"""
from __future__ import annotations

import math

import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_origin_3d, region_2d_to_vector_3d
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

# Piece bands: "hover" in cyan, "select" (the selected piece, always) in the + button's orange,
# resolved for the viewport's background in ui/theme.py.
BAND_ROLES = {"hover": ("cyan", 0.16, 1.00), "select": ("orange", 0.10, 0.85)}
EDGE_WIDTH_PX = 3.0
PICK_MIN_PX = 8.0  # thin lines far away can still be hit this close
DRAG_PX = 5.0  # a press that moves further than this is a drag, not a click
OUTLINE_LIFT_M = 0.03  # the outline floats this far over the conveying surface
CURVE_STEP_DEG, CURVE_FINE_DEG = 15, 1


def _line(context):
    obj = context.active_object
    if obj is None or obj.type != 'CURVES' or obj.mode != 'OBJECT':
        return None
    settings = obj.conveyor_line
    if not settings.is_conveyor_line or not settings.get("seg_path"):
        return None
    return obj


# ------------------------------------------------------------ piece data

def _pieces(obj) -> dict:
    """{segment index: [(world point, world heading), ...]} along each piece.
    A piece's polyline starts at the previous piece's last sample."""
    s = obj.conveyor_line
    path, heads, index = s["seg_path"], s["seg_path_heading"], s["seg_path_index"]
    W = obj.matrix_world
    yaw = obj.matrix_world.to_euler().z
    out: dict = {}
    prev = None
    for k in range(len(index)):
        p = W @ Vector((path[3 * k], path[3 * k + 1], path[3 * k + 2]))
        h = heads[k] + yaw
        i = int(index[k])
        if i >= 0:
            pts = out.setdefault(i, [])
            if not pts and prev is not None:
                pts.append(prev)
            pts.append((p, h))
        prev = (p, h)
    return out


def _half_width(obj) -> float:
    return float(obj.conveyor_line.get("line_width_m", 0.5)) / 2.0 + 0.03


def _left(h: float) -> Vector:
    return Vector((-math.cos(h), -math.sin(h), 0.0))


def pick_piece(context, obj, mouse) -> int:
    """Index of the piece under the mouse (region pixels), nearest to the
    eye when several overlap (spirals), else -1."""
    region, rv3d = context.region, context.region_data
    if region is None or rv3d is None:
        return -1
    mx, my = mouse
    half = _half_width(obj)
    view = rv3d.view_matrix
    best_depth, best = math.inf, -1
    for i, pts in _pieces(obj).items():
        screen = []
        for p, h in pts:
            s = location_3d_to_region_2d(region, rv3d, p)
            e = location_3d_to_region_2d(region, rv3d, p + _left(h) * half)
            if s is None or e is None:
                screen.append(None)
                continue
            screen.append((s, max((e - s).length, PICK_MIN_PX), -(view @ p).z))
        for a, b in zip(screen, screen[1:]):
            if a is None or b is None:
                continue
            (sa, ra, da), (sb, rb, db) = a, b
            ab = sb - sa
            l2 = ab.length_squared
            t = 0.0 if l2 < 1e-9 else max(0.0, min(1.0, ((mx - sa.x) * ab.x + (my - sa.y) * ab.y) / l2))
            q = sa + ab * t
            if math.hypot(mx - q.x, my - q.y) <= ra + (rb - ra) * t:
                depth = da + (db - da) * t
                if depth < best_depth:
                    best_depth, best = depth, i
    return best


def _band(pts, half: float):
    """Left and right edges of a piece (world), lifted over the surface."""
    up = Vector((0.0, 0.0, OUTLINE_LIFT_M))
    left = [p + _left(h) * half + up for p, h in pts]
    right = [p - _left(h) * half + up for p, h in pts]
    return left, right


def _rat_square(obj, index: int):
    """The four world corners of a right-angle transfer's deck: its outline
    is the module's square, not a band along its turning centreline (user,
    2026-10-12: "the bounding box for the RATs is very strange, it should
    be just a square")."""
    s = obj.conveyor_line
    if index >= len(s.segments):
        return None
    seg = s.segments[index]
    if seg.kind != 'MODULE' or seg.module_kind != 'RAT':
        return None
    frames, heads = s.get("segment_frames"), s.get("segment_start_heading")
    if not frames or not heads or 6 * index + 3 > len(frames) or index >= len(heads):
        return None
    from ..model.transfer_parts import rat_length

    W = obj.matrix_world
    start = W @ Vector(frames[6 * index:6 * index + 3])
    h = W.to_euler().z + float(heads[index])
    fwd = Vector((-math.sin(h), math.cos(h), 0.0))
    right = Vector((math.cos(h), math.sin(h), 0.0))
    length = rat_length(seg.length_mm, seg.rat_face_left_mm, seg.rat_face_right_mm) / 1000.0
    half = _half_width(obj)
    up = Vector((0.0, 0.0, OUTLINE_LIFT_M))
    a = start - right * half + up
    b = start + right * half + up
    return [a, b, b + fwd * length, a + fwd * length]


def draw_piece_outline(context, obj, index: int, role: str = "hover", width: float = EDGE_WIDTH_PX) -> None:
    square = _rat_square(obj, index)
    if square is not None:
        a, b, c, d = square
        left, right = [a, d], [b, c]
    else:
        pts = _pieces(obj).get(index)
        if not pts or len(pts) < 2:
            return
        left, right = _band(pts, _half_width(obj))
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    tris = []
    for k in range(len(left) - 1):
        tris += [left[k], right[k], left[k + 1], right[k], right[k + 1], left[k + 1]]
    from . import theme

    pal = theme.palette(context)
    name, fill_a, edge_a = BAND_ROLES.get(role, BAND_ROLES["hover"])
    rgb = pal[name]
    flat = gpu.shader.from_builtin('UNIFORM_COLOR')
    flat.uniform_float("color", theme.rgba(rgb, fill_a + (0.06 if pal["light"] else 0.0)))
    batch_for_shader(flat, 'TRIS', {"pos": tris}).draw(flat)
    line = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    region = context.region
    line.uniform_float("viewportSize", (region.width, region.height))
    loop = left + list(reversed(right)) + [left[0]]
    theme.stroke(line, 'LINE_STRIP', loop, rgb, width, pal, alpha=max(edge_a, 0.9 if pal["light"] else edge_a))
    gpu.state.blend_set('NONE')


# ------------------------------------------------------------ the group

_group_hover = {"name": None}


def group_hover():
    """Name of the connected line under the mouse (the picker sets it), or None."""
    return _group_hover["name"]


def group_members(context, obj) -> list:
    """[(line, role)] of every OTHER line in the active line's dock group:
    'MAIN' for the line nobody docks on, 'FEEDER' for a line whose end
    feeds a merge, 'BRANCH' for one leaving a diverter."""
    from ..operators.build_line import all_lines
    from ..operators.detect_junctions import docked_diverter, docked_junction, tail_continuation
    from ..operators.stream import dock_root

    root = dock_root(context, obj)
    out = []
    for line in all_lines(context.scene):
        if line == obj or not line.conveyor_line.get("seg_path") or dock_root(context, line) != root:
            continue
        if line == root:
            role = 'MAIN'
        elif docked_junction(context, line) is not None:
            role = 'FEEDER'
        elif docked_diverter(context, line) is not None:
            role = 'BRANCH'
        elif tail_continuation(context, line) is not None:
            role = 'NEXT'
        else:
            continue
        out.append((line, role))
    return out



# ------------------------------------------------------------- dragging

def _mouse_ray(context, mouse):
    region, rv3d = context.region, context.region_data
    xy = Vector(mouse)
    return region_2d_to_origin_3d(region, rv3d, xy), region_2d_to_vector_3d(region, rv3d, xy).normalized()


def _axis_param(origin: Vector, direction: Vector, ray_o: Vector, ray_v: Vector):
    """Parameter along the axis line (origin + t direction) closest to the ray."""
    d = direction.normalized()
    w = origin - ray_o
    b = d.dot(ray_v)
    denom = 1.0 - b * b
    if denom < 1e-6:
        return None
    return (b * w.dot(ray_v) - w.dot(d)) / denom


def _plane_hit(z: float, ray_o: Vector, ray_v: Vector):
    if abs(ray_v.z) < 1e-6:
        return None
    t = (z - ray_o.z) / ray_v.z
    return ray_o + ray_v * t if t > 0.0 else None


class _Drag:
    """What a press on a piece started: the piece, its kind and the value
    being dragged (straight length in mm, curve angle in degrees)."""

    def __init__(self, context, obj, index: int, mouse):
        from ..props.line_settings import segment_curve_angle_deg, segment_curve_radius_mm

        self.obj_name = obj.name
        self.index = index
        self.press = Vector(mouse)
        self.dragged = False
        s = obj.conveyor_line
        seg = s.segments[index]
        self.kind = seg.kind
        W = obj.matrix_world
        frames = s.get("segment_frames")
        f = frames[6 * index:6 * index + 6]
        self.start = W @ Vector(f[0:3])
        self.end = W @ Vector(f[3:6])
        ray_o, ray_v = _mouse_ray(context, mouse)
        if self.kind == 'STRAIGHT':
            self.value0 = seg.length_mm
            self.t0 = _axis_param(self.start, self.end - self.start, ray_o, ray_v)
        elif self.kind == 'CURVE':
            self.value0 = segment_curve_angle_deg(seg)
            h = s["segment_start_heading"][index] + obj.matrix_world.to_euler().z
            r = (segment_curve_radius_mm(seg) / 1000.0) + float(s.get("line_width_m", 0.5)) / 2.0
            self.sign = 1.0 if seg.curve_direction == 'LEFT' else -1.0
            self.center = self.start + _left(h) * r * self.sign
            self.phi = self._angle(ray_o, ray_v)
            self.sweep = 0.0
        else:
            self.value0 = None

    def _angle(self, ray_o, ray_v):
        p = _plane_hit(self.center.z, ray_o, ray_v)
        return None if p is None else math.atan2(p.y - self.center.y, p.x - self.center.x)

    def update(self, context, mouse, precise: bool) -> None:
        if not self.dragged and (Vector(mouse) - self.press).length < DRAG_PX:
            return
        self.dragged = True
        obj = bpy.data.objects.get(self.obj_name)
        if obj is None or self.value0 is None:
            return
        seg = obj.conveyor_line.segments[self.index]
        ray_o, ray_v = _mouse_ray(context, mouse)
        if self.kind == 'STRAIGHT' and self.t0 is not None:
            t = _axis_param(self.start, self.end - self.start, ray_o, ray_v)
            if t is None:
                return
            value = max(150.0, self.value0 + (t - self.t0) * 1000.0)
            if abs(value - seg.length_mm) >= 1.0:
                seg.length_mm = value  # snaps to the catalog increment and rebuilds
        elif self.kind == 'CURVE' and self.phi is not None:
            phi = self._angle(ray_o, ray_v)
            if phi is None:
                return
            step = phi - self.phi
            step = (step + math.pi) % (2.0 * math.pi) - math.pi
            self.sweep += step
            self.phi = phi
            snap = CURVE_FINE_DEG if precise else CURVE_STEP_DEG
            value = self.value0 + math.degrees(self.sweep) * self.sign
            value = int(max(5, min(350, round(value / snap) * snap)))
            if value != seg.curve_angle_deg:
                seg.curve_angle_deg = value  # rebuilds

    def cancel(self, context) -> None:
        """Puts the value back exactly (an ID-property write skips the
        length snap, so an old unsnapped length survives a cancelled drag)."""
        from ..operators.build_line import build_line
        from ..props.line_settings import context_for

        obj = bpy.data.objects.get(self.obj_name)
        if obj is None or not self.dragged or self.value0 is None:
            return
        seg = obj.conveyor_line.segments[self.index]
        if self.kind == 'STRAIGHT':
            seg["length_mm"] = self.value0
        elif self.kind == 'CURVE':
            from ..props.line_settings import EXACT_ANGLE_KEY

            seg["curve_angle_deg"] = int(round(self.value0))
            if abs(self.value0 - round(self.value0)) > 1e-6:
                seg[EXACT_ANGLE_KEY] = float(self.value0)  # a path's exact angle survives a cancelled drag
        build_line(context_for(context, obj), obj)


# --------------------------------------------------------------- gizmos

class CONVEYOR_GT_piece_picker(bpy.types.Gizmo):
    """Covers the active line: hover outlines a piece, press selects it,
    drag edits it."""
    bl_idname = "CONVEYOR_GT_piece_picker"

    __slots__ = ("hover", "drag")

    def setup(self):
        self.hover = -1
        self.drag = None

    def test_select(self, context, location):
        obj = _line(context)
        if obj is None:
            self.hover = -1
            self._set_group_hover(context, None)
            return -1
        self.hover = pick_piece(context, obj, location)
        if self.hover >= 0:
            self._set_group_hover(context, None)
            return 0
        # Not on the active line: a connected line (its main, a feeder, a
        # branch) under the mouse lights up and a click selects it.
        for line, _role in group_members(context, obj):
            if pick_piece(context, line, location) >= 0:
                self._set_group_hover(context, line.name)
                return 0
        self._set_group_hover(context, None)
        return -1

    @staticmethod
    def _set_group_hover(context, name) -> None:
        if _group_hover["name"] != name:
            _group_hover["name"] = name
            if context.area is not None:
                context.area.tag_redraw()

    def draw(self, context):
        obj = _line(context)
        if obj is None:
            return
        # The selected piece always wears its band -- in Material Preview and
        # Rendered shading too, where the measurements (ui/dimensions.py) hide:
        # selection is feedback, not information (user, 2026-10-08).
        active = obj.conveyor_line.active_segment_index
        if 0 <= active < len(obj.conveyor_line.segments):
            draw_piece_outline(context, obj, active, "select", 2.0)
        if self.drag is not None:
            draw_piece_outline(context, obj, self.drag.index)
        elif self.is_highlight and 0 <= self.hover != active:
            draw_piece_outline(context, obj, self.hover)

    def invoke(self, context, event):
        obj = _line(context)
        if obj is None:
            return {'CANCELLED'}
        if self.hover < 0:
            other = context.scene.objects.get(_group_hover["name"] or "")
            if other is None:
                return {'CANCELLED'}
            for o in list(context.view_layer.objects.selected):
                o.select_set(False)
            other.select_set(True)
            context.view_layer.objects.active = other
            self._set_group_hover(context, None)
            return {'FINISHED'}
        if self.hover >= len(obj.conveyor_line.segments):
            return {'CANCELLED'}
        settings = obj.conveyor_line
        if settings.active_segment_index != self.hover:
            settings.active_segment_index = self.hover  # highlights it, the list follows
        self.drag = _Drag(context, obj, self.hover, (event.mouse_region_x, event.mouse_region_y))
        return {'RUNNING_MODAL'}

    def modal(self, context, event, tweak):
        if self.drag is not None and event.type == 'MOUSEMOVE':
            self.drag.update(context, (event.mouse_region_x, event.mouse_region_y), 'PRECISE' in tweak)
            context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def exit(self, context, cancel):
        drag, self.drag = self.drag, None
        if drag is None:
            return
        if cancel:
            drag.cancel(context)
        context.area.tag_redraw()


class CONVEYOR_GGT_piece_picker(bpy.types.GizmoGroup):
    bl_idname = "CONVEYOR_GGT_piece_picker"
    bl_label = "Conveyor Piece Picker"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT'}

    @classmethod
    def poll(cls, context):
        return _line(context) is not None

    def setup(self, context):
        gz = self.gizmos.new(CONVEYOR_GT_piece_picker.bl_idname)
        gz.use_select_background = True  # lets gizmos drawn on the line (elevation arrow) win
        gz.use_draw_modal = True
        gz.use_grab_cursor = False
        gz.use_undo = True  # one undo step per click / drag
        self.picker = gz


END_BUTTON_AHEAD_M, END_BUTTON_LIFT_M = 0.45, 0.25
FACE_BUTTON_OUT_M = 0.40  # a junction's + floats this far outside its free face
FACE_BUTTONS = 6  # free junction faces that can show a + at once


def _plus_button(group, operator: str):
    gz = group.gizmos.new("GIZMO_GT_button_2d")
    gz.icon = 'ADD'
    gz.draw_options = {'BACKDROP', 'OUTLINE'}
    gz.show_drag = False
    gz.color = (0.12, 0.12, 0.12)
    gz.alpha = 0.85
    gz.color_highlight = (0.95, 0.55, 0.10)
    gz.alpha_highlight = 1.0
    gz.scale_basis = 14.0
    return gz, gz.target_set_operator(operator)


def _place_2d(gz, region, rv3d, world) -> None:
    xy = location_3d_to_region_2d(region, rv3d, world)
    if xy is None:
        gz.hide = True
        return
    gz.hide = False
    gz.matrix_basis = Matrix.Translation((xy.x, xy.y, 0.0))


class CONVEYOR_GGT_line_end(bpy.types.GizmoGroup):
    """Round + buttons: one floating past the active line's end (the piece
    keys, appended at the end) and one outside every free face of a merge
    or diverter on the active line, or of the junction it hangs on -- that
    one starts another conveyor from the junction (user request
    2026-10-05: "press the same + sign on the merge to add another conveyor
    from that")."""
    bl_idname = "CONVEYOR_GGT_line_end"
    bl_label = "Conveyor Line End"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'PERSISTENT', 'SCALE'}

    @classmethod
    def poll(cls, context):
        return _line(context) is not None

    def setup(self, context):
        self.button, _props = _plus_button(self, "conveyor.piece_palette")
        self.start_button, props = _plus_button(self, "conveyor.piece_palette")
        props.at_start = True
        self.faces = [_plus_button(self, "conveyor.new_line_at_junction") for _ in range(FACE_BUTTONS)]

    def draw_prepare(self, context):
        from .theme import style_buttons

        style_buttons(self, context, "orange")
        obj = _line(context)
        region, rv3d = context.region, context.region_data
        if obj is None or rv3d is None:
            self.button.hide = self.start_button.hide = True
            for gz, _props in self.faces:
                gz.hide = True
            return
        ex, ey, ez, h_deg = obj.conveyor_line.end_pose
        h = math.radians(h_deg)
        local = Vector((ex, ey, ez)) + Vector((-math.sin(h), math.cos(h), 0.0)) * END_BUTTON_AHEAD_M
        _place_2d(self.button, region, rv3d, obj.matrix_world @ local + Vector((0.0, 0.0, END_BUTTON_LIFT_M)))

        from ..operators.detect_junctions import free_junction_faces, origin_dock

        faces = free_junction_faces(context, obj)
        dock = origin_dock(context, obj)
        # The + before the START grows the line backwards -- not on a line
        # whose origin sits on a junction (its start IS the junction face).
        if dock is None:
            _place_2d(self.start_button, region, rv3d, obj.matrix_world @ Vector((0.0, -END_BUTTON_AHEAD_M, 0.0)) + Vector((0.0, 0.0, END_BUTTON_LIFT_M)))
        else:
            self.start_button.hide = True
        if dock is not None:
            faces += free_junction_faces(context, dock[0], only=dock[1])
        for k, (gz, props) in enumerate(self.faces):
            if k >= len(faces):
                gz.hide = True
                continue
            line, index, side, centre, outward = faces[k]
            props.line_name, props.index, props.side = line.name, index, side
            _place_2d(gz, region, rv3d, centre + outward * FACE_BUTTON_OUT_M + Vector((0.0, 0.0, END_BUTTON_LIFT_M)))


# ------------------------------------------------------ piece palette

class CONVEYOR_OT_piece_palette(bpy.types.Operator):
    bl_idname = "conveyor.piece_palette"
    bl_label = "Add a Piece"
    bl_description = "Extend the line at this end: the piece keys and the value strip, right here"
    bl_options = {'INTERNAL'}

    at_start: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'},
                                     description="Grow the line backwards from its start (what is built stays where it is)")

    @classmethod
    def description(cls, context, properties):
        return "Grow the line backwards from its start: the piece keys, right here" if properties.at_start else \
            "Extend the line at its end: the piece keys and the value strip, right here"

    @classmethod
    def poll(cls, context):
        return _line(context) is not None

    def invoke(self, context, event):
        # The + sits at one end of the line: the keys grow that end (select
        # the piece there, remember the end for the panel's keys too).
        settings = _line(context).conveyor_line
        settings.grow_at = 'START' if self.at_start else 'END'
        there = 0 if self.at_start else len(settings.segments) - 1
        if settings.active_segment_index != there:
            settings.active_segment_index = there
        return context.window_manager.invoke_popup(self, width=280)

    def draw(self, context):
        from .panels import draw_pad, draw_quick_strip

        obj = _line(context)
        if obj is None:
            return
        layout = self.layout
        draw_pad(layout, context, obj)
        layout.separator(factor=0.4)
        draw_quick_strip(layout, context, obj)

    def execute(self, context):
        return {'FINISHED'}


# The piece keys from the keyboard, in the viewport: Alt + arrows (free in
# Blender's 3D View keymap). Blender shows them in the keys' tooltips.
_keymap_items: list = []
KEYS = (('UP_ARROW', 'STRAIGHT'), ('LEFT_ARROW', 'CURVE_LEFT'), ('RIGHT_ARROW', 'CURVE_RIGHT'))


def _register_keys() -> None:
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:  # background mode
        return
    km = kc.keymaps.new(name="3D View", space_type='VIEW_3D')
    for key, kind in KEYS:
        kmi = km.keymap_items.new("conveyor.segment_add", key, 'PRESS', alt=True)
        kmi.properties.kind = kind
        _keymap_items.append((km, kmi))
    _keymap_items.append((km, km.keymap_items.new("conveyor.piece_library", 'DOWN_ARROW', 'PRESS', alt=True)))


def _unregister_keys() -> None:
    for km, kmi in _keymap_items:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _keymap_items.clear()


classes = (CONVEYOR_GT_piece_picker, CONVEYOR_GGT_piece_picker, CONVEYOR_GGT_line_end, CONVEYOR_OT_piece_palette)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    _register_keys()


def unregister():
    _unregister_keys()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
