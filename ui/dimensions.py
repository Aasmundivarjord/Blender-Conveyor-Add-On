"""CAD-style dimensions on the active line (user request 2026-10-05: "like
a 2D CAD drawing from the top where you set the dimensions"), and the
active line's GROUP: the main line it hangs on and the lines docked on it,
each with a tinted band and a role tag ("Main line", "Feeds in", "Branch")
so the hierarchy reads at a glance (user request 2026-10-05: "visually
differentiate the main conveyor line from the smaller connected
conveyors"). Hovering a connected line lights it; a click selects it
(ui/segment_edit.py, the picker).

Every piece of the active line carries its measure in the viewport: a
straight its length (and rise), a curve its angle and radius, a spiral its
turn and height, a module its name and footprint. Straights and modules get
a proper dimension line beside the conveyor -- extension ticks, the line,
the figure centred on it -- the way a plan drawing shows them; curves and
spirals get the figure with a short leader at the outer edge.

A click on a figure opens a small popup with that value ready to type
(conveyor.set_dimension, invoke_props_popup with the field already in edit
mode): type 2.4, Enter, the line is rebuilt. Hovering a figure lights it.

Drawing happens in a POST_PIXEL draw handler (text and pixel-space lines);
a 2D gizmo covering the figures only does the hit-testing and the click, so
it wins over the piece picker (ui/segment_edit.py), which selects in the
background. The scene setting Dimensions (Scene section) switches it off.
"""
from __future__ import annotations


import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from .segment_edit import _band, _half_width, _left, _line, _pieces, group_hover, group_members

TEXT_PX = 11.0
PAD_PX = 5.0
RADIUS_PX = 4.0
DIM_OFFSET_M = 0.30  # dimension line this far outside the conveyor's edge
LEADER_M = 0.22  # curve / spiral figure this far outside the outer edge
TICK_OVER_M = 0.06  # extension lines overshoot the dimension line

LINE_PX = 1.5
# Colours come from the viewport's background (ui/theme.py, model/contrast.py):
# dimension lines in the theme's ink with a halo, labels on a box; the active
# figure and the main line of the group in the selection orange, the lines
# docked on it in steel blue, the hovered one in cyan. On a light theme the
# accents are deep and the boxes near-white with an edge.
TAG_DARK_MAIN, TAG_DARK_LINK = (0.55, 0.32, 0.06, 0.92), (0.14, 0.26, 0.38, 0.92)  # the group tags on a dark theme

_state = {"hover": -1}
_handle = None
_handle_3d = None


def overlay_shown(context) -> bool:
    """The drawing shows in Solid / Wireframe shading with overlays on and
    the Dimensions switch set -- like a CAD drawing layer, it leaves the
    picture alone in Material Preview and Rendered shading (user request
    2026-10-06)."""
    try:
        if not context.scene.conveyor_settings.show_dimensions:
            return False
    except AttributeError:
        return False
    space = context.space_data
    if space is None or space.type != 'VIEW_3D':
        return False
    return space.overlay.show_overlays and space.shading.type in {'SOLID', 'WIREFRAME'}


MIN_FIGURE_PX = 48  # a piece shorter than this on screen shows no figure (unless selected)
LABEL_OVER_CHORD = 1.3  # ...nor one whose label is wider than this times the piece's on-screen length


def _fmt_m(mm: float, scene) -> str:
    from ..config import units

    return units.format_length_mm(mm, scene)


def dimension_text(seg, scene) -> str:
    """The figure a piece shows."""
    from ..props.line_settings import segment_curve_angle_deg, segment_curve_radius_mm, segment_label, segment_rise_mm

    if seg.kind in ('STRAIGHT', 'INCLINE'):
        rise = segment_rise_mm(seg)
        text = _fmt_m(seg.length_mm, scene)
        if abs(rise) >= 0.5:
            text += f"  {'↗' if rise > 0 else '↘'} {_fmt_m(abs(rise), scene)}"
        return text
    if seg.kind == 'CURVE':
        return f"{segment_curve_angle_deg(seg)}°   R {_fmt_m(segment_curve_radius_mm(seg), scene)}"
    if seg.kind == 'SPIRAL':
        return f"{seg.spiral_turns * 360.0:.0f}°   {'↓' if seg.rise_mm < 0 else '↑'} {_fmt_m(abs(seg.rise_mm), scene)}"
    return segment_label(seg)


class _Figure:
    __slots__ = ("index", "text", "anchor", "lines", "rect", "chord")

    def __init__(self, index: int, text: str, anchor, lines):
        self.index = index
        self.text = text
        self.anchor = anchor  # region pixels, centre of the label
        self.lines = lines  # [(p0, p1), ...] region pixels
        self.rect = None  # (x0, y0, x1, y1), filled when the text is measured
        self.chord = 0.0  # the piece's own length on screen, pixels


def _project(region, rv3d, points):
    out = []
    for p in points:
        q = location_3d_to_region_2d(region, rv3d, p)
        if q is None:
            return None
        out.append(q)
    return out


def figures(context, obj) -> list:
    """Where every piece's figure and dimension lines land on screen."""
    region, rv3d = context.region, context.region_data
    if region is None or rv3d is None:
        return []
    settings = obj.conveyor_line
    scene = context.scene
    half = _half_width(obj)
    up = Vector((0.0, 0.0, 0.03))
    active = settings.active_segment_index
    min_px = MIN_FIGURE_PX * _ui_scale(context)
    out = []
    for i, pts in sorted(_pieces(obj).items()):
        if i >= len(settings.segments) or len(pts) < 2:
            continue
        seg = settings.segments[i]
        text = dimension_text(seg, scene)
        (p0, h0), (p1, h1) = pts[0], pts[-1]
        # Zoomed out, a long line's figures pile up unreadably: a piece
        # shorter than MIN_FIGURE_PX on screen, or shorter than its own
        # label, keeps its figure to itself (the selected piece always
        # shows its own) -- like a CAD drawing thinning out at scale.
        chord = _project(region, rv3d, (p0, p1))
        if chord is None:
            continue
        chord_px = (chord[1] - chord[0]).length
        if i != active and chord_px < min_px:
            continue
        if seg.kind in ('STRAIGHT', 'INCLINE', 'MODULE'):
            # Dimension line on the left of travel, a hand's width outside the edge.
            left0, left1 = _left(h0), _left(h1)
            e0, e1 = p0 + left0 * half + up, p1 + left1 * half + up
            d0, d1 = p0 + left0 * (half + DIM_OFFSET_M) + up, p1 + left1 * (half + DIM_OFFSET_M) + up
            over0, over1 = d0 + left0 * TICK_OVER_M, d1 + left1 * TICK_OVER_M
            proj = _project(region, rv3d, (e0, over0, e1, over1, d0, d1))
            if proj is None:
                continue
            lines = [(proj[0], proj[1]), (proj[2], proj[3]), (proj[4], proj[5])]
            anchor = (proj[4] + proj[5]) * 0.5
        else:
            # Curves and spirals: the figure outside the outer edge at mid-arc.
            mid = pts[len(pts) // 2]
            pm, hm = mid
            outward = -_left(hm) if seg.curve_direction == 'LEFT' else _left(hm)
            edge = pm + outward * half + up
            tip = pm + outward * (half + LEADER_M) + up
            proj = _project(region, rv3d, (edge, tip))
            if proj is None:
                continue
            lines = [(proj[0], proj[1])]
            anchor = proj[1] + (proj[1] - proj[0]).normalized() * 12.0 if (proj[1] - proj[0]).length > 1e-3 else proj[1]
        fig = _Figure(i, text, anchor, lines)
        fig.chord = chord_px
        out.append(fig)
    _measure(context, out)
    return [f for f in out if f.index == active or (f.rect[2] - f.rect[0]) <= f.chord * LABEL_OVER_CHORD]


def _ui_scale(context) -> float:
    return context.preferences.system.ui_scale


def _measure(context, figs) -> None:
    font_id = 0
    blf.size(font_id, TEXT_PX * _ui_scale(context))
    pad = PAD_PX * _ui_scale(context)
    for f in figs:
        w, h = blf.dimensions(font_id, f.text)
        h = max(h, TEXT_PX * _ui_scale(context))
        f.rect = (f.anchor.x - w / 2.0 - pad, f.anchor.y - h / 2.0 - pad * 0.7, f.anchor.x + w / 2.0 + pad, f.anchor.y + h / 2.0 + pad * 0.7)


def _draw():
    context = bpy.context
    if not overlay_shown(context):
        return
    obj = _line(context)
    if obj is None:
        return
    figs = figures(context, obj)
    _measure(context, figs)
    active = obj.conveyor_line.active_segment_index
    hover = _state["hover"]
    region = context.region
    scale = _ui_scale(context)

    from . import theme

    pal = theme.palette(context)
    gpu.state.blend_set('ALPHA')
    line_shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    line_shader.uniform_float("viewportSize", (region.width, region.height))
    for f in figs:
        coords = [(p.x, p.y) for a, b in f.lines for p in (a, b)]
        if not coords:
            continue
        rgb = pal["orange"] if f.index == active else pal["stroke"]
        alpha = 0.95 if f.index == active else (0.85 if pal["light"] else 0.60)
        theme.stroke(line_shader, 'LINES', coords, rgb, LINE_PX * scale, pal, alpha=alpha, scale=scale)

    fill = gpu.shader.from_builtin('UNIFORM_COLOR')
    font_id = 0
    blf.size(font_id, TEXT_PX * scale)
    colours = {}
    for f in figs:
        if f.index == active:
            colour = theme.rgba(pal["orange"], 0.96)
        else:
            colour = pal["box_hover"] if f.index == hover else pal["box"]
        colours[f.index] = colour
        theme.box(fill, line_shader, f.rect, RADIUS_PX * scale, colour, pal["box_edge"] if pal["light"] else None, scale)
    for f in figs:
        w, h = blf.dimensions(font_id, f.text)
        blf.position(font_id, f.anchor.x - w / 2.0, f.anchor.y - h / 2.0 + 1.0, 0.0)
        blf.color(font_id, *theme.text_colour(colours[f.index]))
        blf.draw(font_id, f.text)
    _draw_group_tags(context, font_id, scale, fill)
    gpu.state.blend_set('NONE')


# ------------------------------------------------------------ the group

def _line_edges(line):
    """Left and right edges (world) of a whole line, piece by piece."""
    half = _half_width(line)
    for _i, pts in sorted(_pieces(line).items()):
        if len(pts) >= 2:
            yield _band(pts, half)


def _draw_group_bands():
    context = bpy.context
    if not overlay_shown(context):
        return
    obj = _line(context)
    if obj is None:
        return
    members = group_members(context, obj)
    if not members:
        return
    from . import theme

    pal = theme.palette(context)
    hovered = group_hover()
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    flat = gpu.shader.from_builtin('UNIFORM_COLOR')
    line_shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    region = context.region
    line_shader.uniform_float("viewportSize", (region.width, region.height))
    for line, role in members:
        hot = line.name == hovered
        rgb = pal["cyan"] if hot else (pal["orange"] if role == 'MAIN' else pal["blue"])
        fill_a = 0.20 if hot else (0.10 if role == 'MAIN' else 0.08)
        edge_a = 1.0 if hot else (0.80 if pal["light"] else (0.70 if role == 'MAIN' else 0.65))
        for left, right in _line_edges(line):
            tris = []
            for k in range(len(left) - 1):
                tris += [left[k], right[k], left[k + 1], right[k], right[k + 1], left[k + 1]]
            flat.uniform_float("color", theme.rgba(rgb, fill_a))
            batch_for_shader(flat, 'TRIS', {"pos": tris}).draw(flat)
            theme.stroke(line_shader, 'LINE_STRIP', left, rgb, 2.0 if hot else 1.2, pal, alpha=edge_a)
            theme.stroke(line_shader, 'LINE_STRIP', right, rgb, 2.0 if hot else 1.2, pal, alpha=edge_a)
    gpu.state.blend_set('NONE')


ROLE_WORDS = {'MAIN': "Main line", 'FEEDER': "Feeds in", 'BRANCH': "Branch", 'NEXT': "Carries on"}


def group_tags(context, obj) -> list:
    """[(text, region xy, role)]: a tag at the middle of every other line of the group."""
    region, rv3d = context.region, context.region_data
    out = []
    for line, role in group_members(context, obj):
        pieces = _pieces(line)
        pts = [p for _i, seg_pts in sorted(pieces.items()) for p, _h in seg_pts]
        if not pts:
            continue
        # Two thirds along (not the middle): a short branch's middle sits on
        # top of its diverter's dimension label.
        mid = pts[min(len(pts) - 1, (2 * len(pts)) // 3)] + Vector((0.0, 0.0, 0.35))
        xy = location_3d_to_region_2d(region, rv3d, mid)
        if xy is not None:
            out.append((f"{ROLE_WORDS[role]}  ·  {line.name}", xy, role))
    return out


def _draw_group_tags(context, font_id: int, scale: float, fill) -> None:
    obj = _line(context)
    if obj is None:
        return
    from . import theme

    pal = theme.palette(context)
    region = context.region
    edge = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    edge.uniform_float("viewportSize", (region.width, region.height))
    hovered = group_hover()
    pad = PAD_PX * scale
    for text, xy, role in group_tags(context, obj):
        w, h = blf.dimensions(font_id, text)
        h = max(h, TEXT_PX * scale)
        x0, y0, x1, y1 = xy.x - w / 2.0 - pad, xy.y - h / 2.0 - pad * 0.7, xy.x + w / 2.0 + pad, xy.y + h / 2.0 + pad * 0.7
        hot = hovered is not None and text.endswith(hovered)
        if hot:
            bg = theme.rgba(pal["cyan"], 0.97)
        elif pal["light"]:
            bg = theme.rgba(pal["orange"] if role == 'MAIN' else pal["blue"], 0.94)
        else:
            bg = TAG_DARK_MAIN if role == 'MAIN' else TAG_DARK_LINK
        theme.box(fill, edge, (x0, y0, x1, y1), RADIUS_PX * scale, bg, pal["box_edge"] if pal["light"] else None, scale)
        blf.position(font_id, xy.x - w / 2.0, xy.y - h / 2.0 + 1.0, 0.0)
        blf.color(font_id, *theme.text_colour(bg))
        blf.draw(font_id, text)


def figure_under(context, obj, location) -> int:
    figs = figures(context, obj)
    _measure(context, figs)
    x, y = location
    for f in figs:
        x0, y0, x1, y1 = f.rect
        if x0 <= x <= x1 and y0 <= y <= y1:
            return f.index
    return -1


# --------------------------------------------------------------- gizmo

class CONVEYOR_GT_dimension(bpy.types.Gizmo):
    """Hit-testing for the figures; the click runs conveyor.set_dimension
    for the one under the mouse."""
    bl_idname = "CONVEYOR_GT_dimension"

    __slots__ = ("op_props",)

    def setup(self):
        self.op_props = self.target_set_operator("conveyor.set_dimension")

    def test_select(self, context, location):
        obj = _line(context)
        hit = -1 if obj is None or not overlay_shown(context) else figure_under(context, obj, location)
        if hit != _state["hover"]:
            _state["hover"] = hit
            if context.area is not None:
                context.area.tag_redraw()
        if hit < 0:
            return -1
        self.op_props.index = hit
        return 0

    def draw(self, context):
        pass


class CONVEYOR_GGT_dimensions(bpy.types.GizmoGroup):
    bl_idname = "CONVEYOR_GGT_dimensions"
    bl_label = "Conveyor Dimensions"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'PERSISTENT'}

    @classmethod
    def poll(cls, context):
        return _line(context) is not None and overlay_shown(context)

    def setup(self, context):
        gz = self.gizmos.new(CONVEYOR_GT_dimension.bl_idname)
        gz.use_draw_modal = False
        self.figure = gz


# ------------------------------------------------------------ operator

class CONVEYOR_OT_set_dimension(bpy.types.Operator):
    bl_idname = "conveyor.set_dimension"
    bl_label = "Set Dimension"
    bl_description = "Type this piece's length, angle or height"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    index: bpy.props.IntProperty(default=-1, options={'HIDDEN', 'SKIP_SAVE'})
    kind: bpy.props.StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    length_m: bpy.props.FloatProperty(name="Length", unit='LENGTH', min=0.15, soft_max=30.0, step=10, precision=2)
    rise_m: bpy.props.FloatProperty(name="Rise", description="Height gained (+) or lost (-) over the straight",
                                    unit='LENGTH', soft_min=-6.0, soft_max=6.0, step=10, precision=2)
    angle_deg: bpy.props.IntProperty(name="Angle", min=5, max=350)
    turn_deg: bpy.props.FloatProperty(name="Turn", description="360° = one full turn", min=30.0, soft_max=3600.0, step=1500, precision=0)
    height_m: bpy.props.FloatProperty(name="Height", unit='LENGTH', soft_min=-50.0, soft_max=50.0, step=10, precision=2)

    @classmethod
    def poll(cls, context):
        return _line(context) is not None

    def _segment(self, context):
        obj = _line(context)
        if obj is None:
            return None, None
        settings = obj.conveyor_line
        if not (0 <= self.index < len(settings.segments)):
            return obj, None
        return obj, settings.segments[self.index]

    def invoke(self, context, event):
        obj, seg = self._segment(context)
        if seg is None:
            return {'CANCELLED'}
        settings = obj.conveyor_line
        if settings.active_segment_index != self.index:
            settings.active_segment_index = self.index  # the click also selects the piece
        if seg.kind in ('STRAIGHT', 'INCLINE'):
            from ..props.line_settings import segment_rise_mm

            self.kind = 'STRAIGHT'
            self.length_m, self.rise_m = seg.length_mm / 1000.0, segment_rise_mm(seg) / 1000.0
        elif seg.kind == 'CURVE':
            from ..props.line_settings import segment_curve_angle_deg

            self.kind = 'CURVE'
            self.angle_deg = segment_curve_angle_deg(seg)
        elif seg.kind == 'SPIRAL':
            self.kind = 'SPIRAL'
            self.turn_deg, self.height_m = seg.spiral_turns * 360.0, seg.rise_mm / 1000.0
        elif seg.module_kind == 'LIFT':
            self.kind = 'LIFT'
            self.height_m = seg.rise_mm / 1000.0
        elif seg.module_kind in ('RAT', 'BUFFER', 'ARB'):
            self.kind = 'LENGTH'
            self.length_m = seg.length_mm / 1000.0
        else:
            return {'FINISHED'}  # junctions size themselves to the lines they join
        return context.window_manager.invoke_props_popup(self, event)

    def draw(self, context):
        from ..props.line_settings import segment_label

        _obj, seg = self._segment(context)
        layout = self.layout
        if seg is not None:
            layout.label(text=f"Piece {self.index + 1}  ·  {segment_label(seg)}")
        col = layout.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        col.activate_init = True  # the first field opens in edit mode: click, type, Enter
        if self.kind == 'STRAIGHT':
            col.prop(self, "length_m")
            col.prop(self, "rise_m")
        elif self.kind == 'CURVE':
            col.prop(self, "angle_deg")
        elif self.kind == 'SPIRAL':
            col.prop(self, "turn_deg")
            col.prop(self, "height_m")
        elif self.kind == 'LIFT':
            col.prop(self, "height_m")
        elif self.kind == 'LENGTH':
            col.prop(self, "length_m")

    def execute(self, context):
        from ..operators.build_line import build_line
        from ..props.line_settings import context_for, suspended_rebuild

        obj, seg = self._segment(context)
        if seg is None:
            return {'CANCELLED'}
        with suspended_rebuild():
            if self.kind == 'STRAIGHT':
                seg.length_mm = self.length_m * 1000.0  # snaps to the catalog step
                seg.rise_mm = self.rise_m * 1000.0
                self.length_m = seg.length_mm / 1000.0
            elif self.kind == 'CURVE':
                seg.curve_angle_deg = int(self.angle_deg)
            elif self.kind == 'SPIRAL':
                seg.spiral_turns = max(self.turn_deg, 30.0) / 360.0
                seg.rise_mm = self.height_m * 1000.0
            elif self.kind == 'LIFT':
                seg.rise_mm = self.height_m * 1000.0
            elif self.kind == 'LENGTH':
                seg.length_mm = self.length_m * 1000.0
                self.length_m = seg.length_mm / 1000.0
        build_line(context_for(context, obj), obj)
        return {'FINISHED'}


classes = (CONVEYOR_GT_dimension, CONVEYOR_GGT_dimensions, CONVEYOR_OT_set_dimension)


def register():
    global _handle, _handle_3d
    for cls in classes:
        bpy.utils.register_class(cls)
    _handle_3d = bpy.types.SpaceView3D.draw_handler_add(_draw_group_bands, (), 'WINDOW', 'POST_VIEW')
    _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _handle, _handle_3d
    for handle, kind in ((_handle, "pixel"), (_handle_3d, "view")):
        if handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
    _handle = _handle_3d = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
