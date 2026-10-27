"""The 'Conveyor' tab in the 3D viewport sidebar (N-panel).

Layout (Apple HIG applied to a
narrow pointer sidebar: most-used first, disclosure for the rest, no
decoration):

    Conveyor                                  v2.6.0   version in the header
    [ New line at cursor ] [from end]
    Add to the end                                     THE thing people do all
            [ ^ Straight ]                             day: the piece keys,
    [ < Curve L ] [ v More ] [ > Curve R ]             More = the piece library
    Piece 3 . Curve L 90                               the value for the piece
    [30][45][60][90][180]  [Left|Right] [R]            they just made
    Type   [ Belt            v ]                       the two line settings
    Width  [ 600 mm          v ]                       everyone sets
    > Line       Forward . fences . 75 mm rollers      the rest of the line
    > Details    exact values of the selected piece
    > Populate   [x] item, speed, throughput           one click: the eyedropper
    > Pieces     9 . 16.69 m            (closed)       the list, reorder, remove
    > Scene      floor, docking, play   (closed)

No pictures: the map and the close-up of the two earlier rounds read as
decoration in a 280 px panel and pushed the controls down. The viewport is
the drawing now -- ui/dimensions.py writes every piece's dimension on the
line itself, CAD style, and a click on one sets it.
"""
from __future__ import annotations

import math

import bpy

from ..config import loader, units
from ..model.segments import incline_from_rise
from ..props.line_settings import SEGMENT_ICONS, segment_curve_angle_deg, segment_label, segment_rise_mm


def _active_line(context):
    obj = context.active_object
    if obj is None or obj.type != 'CURVES' or not obj.conveyor_line.is_conveyor_line:
        return None
    return obj


class CONVEYOR_UL_segments(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        from . import line_map

        try:
            layout.label(text=segment_label(item), icon_value=line_map.picto_for_segment(item))
        except Exception:
            layout.label(text=segment_label(item), icon=SEGMENT_ICONS.get(item.kind, 'DOT'))


QUICK_LENGTHS_M = (1.0, 1.5, 2.0, 3.0, 5.0)
SPIRAL_TURNS_DEG = (90, 180, 360, 720, 1080)


# The piece keys are laid out like a keyboard's arrow cluster (an inverted
# T) at normal button height: forward = Straight, left / right = the curves,
# down = More (the piece library, ui/piece_library.py). Labelled keys: an
# arrow alone could mean "move up"; no boxes, grouping by spacing; the value
# to set next sits right under them; Alt + arrows in the viewport press the
# same keys (ui/segment_edit.py; Blender shows the shortcut in the tooltips).
def draw_pad(layout, context, obj) -> None:
    from ..operators.segments import adds_piece

    settings = obj.conveyor_line
    col = layout.column(align=True)
    if adds_piece(settings):
        # Which end grows: the keys add after the last piece, or -- Start --
        # before the first one, the line growing backwards from where it is.
        row = col.row(align=True)
        row.label(text="Add at", icon='ADD')
        row.prop(settings, "grow_at", expand=True)
    else:
        col.label(text=f"Replace piece {settings.active_segment_index + 1}", icon='FILE_REFRESH')
    pad = col.grid_flow(row_major=True, columns=3, even_columns=True, even_rows=True, align=True)
    pad.scale_y = 1.3
    pad.label(text="")
    pad.operator("conveyor.segment_add", text="Straight", icon='TRIA_UP').kind = 'STRAIGHT'
    pad.label(text="")
    pad.operator("conveyor.segment_add", text="Curve L", icon='TRIA_LEFT').kind = 'CURVE_LEFT'
    pad.operator("conveyor.piece_library", text="More", icon='TRIA_DOWN')
    pad.operator("conveyor.segment_add", text="Curve R", icon='TRIA_RIGHT').kind = 'CURVE_RIGHT'
    # Build mode: the plain arrow keys press these keys (operators/build_mode); lit while it runs
    from ..operators.build_mode import RUNNING

    building = RUNNING["line"] == obj.name
    col.separator(factor=0.5)
    col.operator("conveyor.build_mode", text="Building: Enter or Esc ends" if building else "Build with Arrow Keys",
                 icon='EMPTY_ARROWS', depress=building)


def draw_quick_strip(layout, context, obj) -> None:
    """Right under the keys: the value to set next for the selected piece
    (the one just added) -- presets as a segmented row with the current one
    lit, the companions beside it. Click Curve L, then 45 right below."""
    from . import line_map

    settings = obj.conveyor_line
    i = settings.active_segment_index
    if not (0 <= i < len(settings.segments)):
        return
    seg = settings.segments[i]
    col = layout.column(align=True)
    col.label(text=f"Piece {i + 1}  ·  {segment_label(seg)}", icon_value=line_map.picto_for_segment(seg))
    row = col.row(align=True)
    row.scale_y = 1.15
    if seg.kind == 'CURVE':
        current = segment_curve_angle_deg(seg)
        for a in loader.get_segment_catalog().curve_angles_deg:
            row.operator("conveyor.set_curve_angle", text=f"{a}°", depress=(current == a)).angle = a
        row = col.row(align=True)
        row.prop(seg, "curve_direction", expand=True)
        row.prop(seg, "curve_radius", text="")
    elif seg.kind == 'STRAIGHT':
        row.prop(seg, "length_m", text="Length")
        row = col.row(align=True)
        for m in QUICK_LENGTHS_M:
            row.operator("conveyor.set_straight_length", text=f"{m:g} m", depress=(abs(seg.length_mm - m * 1000.0) < 1.0)).length_m = m
    elif seg.kind == 'SPIRAL':
        current = int(round(seg.spiral_turns * 360.0))
        for a in SPIRAL_TURNS_DEG:
            row.operator("conveyor.set_spiral_angle", text=f"{a}°", depress=(current == a)).angle = a
        row = col.row(align=True)
        row.prop(seg, "curve_direction", expand=True)
        row.prop(seg, "height_m", text="")
    elif seg.kind == 'MODULE' and seg.module_kind == 'RAT':
        row.prop(seg, "module_exit", expand=True)
        VIEW3D_PT_conveyor_piece._rat_width_alert(layout, context, obj, settings)
    elif seg.kind == 'MODULE' and seg.module_kind == 'LIFT':
        row.prop(seg, "lift_shape", expand=True)
        row = col.row(align=True)
        row.prop(seg, "height_m", text="Height")
        row.prop(seg, "lift_fork_pitch_mm", text="Pitch")
        VIEW3D_PT_conveyor_piece._lift_floor_alert(layout, context, obj, settings)
    elif seg.kind == 'MODULE' and seg.module_kind == 'BUFFER':
        row.prop(seg, "length_m", text="Length")
        row.prop(seg, "buffer_out_pct", text="Out")
    elif seg.kind == 'MODULE':
        row.prop(seg, "module_kind", text="")
    else:
        row.label(text="")


_VERSION: list = []


def extension_version() -> str:
    """The version from blender_manifest.toml (what is actually installed)."""
    if not _VERSION:
        import tomllib
        from pathlib import Path

        try:
            manifest = Path(__file__).resolve().parents[1] / "blender_manifest.toml"
            _VERSION.append(str(tomllib.loads(manifest.read_text(encoding="utf-8")).get("version", "?")))
        except Exception:
            _VERSION.append("?")
    return _VERSION[0]


LINE_CHARS = 40  # what fits the default sidebar width: longer messages wrap instead of being cut with "..."


def _lines(text: str) -> list:
    import textwrap

    return textwrap.wrap(text, LINE_CHARS, break_long_words=False, break_on_hyphens=False) or [text]


def _dim_label(layout, text: str) -> None:
    """Secondary text (a summary in a section header); a long one wraps onto more lines."""
    lines = _lines(text)
    if len(lines) == 1:
        row = layout.row()
        row.enabled = False
        row.label(text=text)
        return
    col = layout.column(align=True)
    col.enabled = False
    for line in lines:
        col.label(text=line)


class VIEW3D_PT_conveyor_builder(bpy.types.Panel):
    bl_label = "Conveyor"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Conveyor"

    def draw_header_preset(self, context):
        row = self.layout.row(align=True)
        row.prop(context.scene.conveyor_settings, "show_dimensions", text="", icon='DRIVER_DISTANCE')  # the drawing layer, like a CAD layer switch
        _dim_label(row, f"v{extension_version()}")

    def draw(self, context):
        layout = self.layout
        obj = _active_line(context)

        row = layout.row(align=True)
        row.scale_y = 1.2
        row.operator("conveyor.new_line", text="New Line at Cursor", icon='ADD')
        if obj is not None:
            row.operator("conveyor.new_line_from_end", text="", icon='TRACKING_FORWARDS')
        if obj is None:
            _dim_label(layout, "Select a line, or start one at the 3D cursor")
            return

        settings = obj.conveyor_line
        layout.separator(factor=0.5)
        draw_pad(layout, context, obj)
        layout.separator(factor=0.4)
        draw_quick_strip(layout, context, obj)
        layout.separator(factor=0.6)

        from ..props.line_settings import selected_lines

        same = selected_lines(context, obj)
        if len(same) > 1:  # multi-edit: type, width, speed, roller pitch, fences, nose-over apply to all of them
            row = layout.row()
            row.label(text=f"Editing {len(same)} selected lines", icon='RESTRICT_SELECT_OFF')
        # The two line settings everyone sets, right under the keys.
        col = layout.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        # A menu of the offered types, laid out like the property rows (a
        # hidden type stays in the enum for saved lines and scripts).
        ctype = loader.get_conveyor_types().get(settings.conveyor_type)
        split = col.split(factor=0.4, align=True)
        split.alignment = 'RIGHT'
        split.label(text="Type")
        row = split.row(align=True)
        row.menu("CONVEYOR_MT_conveyor_types", text=ctype.label if ctype is not None else "Choose a type")
        row.operator("conveyor.type_library", text="", icon='IMAGE_DATA')  # the types as pictures
        if ctype is not None and ctype.cross_section == "pouch":
            # The pouch sorter's bag instead of a frame width (model/pouch.py).
            col.prop(settings, "pouch_size", text="Pouch")
            if settings.pouch_size == 'CUSTOM':
                col.prop(settings, "pouch_width_mm", text="Width")
                col.prop(settings, "pouch_height_mm", text="Height")
            col.prop(settings, "pouch_depth_mm", text="Depth")
            col.prop(settings, "pouch_pitch_mm", text="Pitch")
            item = settings.populate_item
            if item is not None and item != obj and item.type == 'MESH':
                from ..model import pouch as pouch_model

                dims = tuple(v * 1000.0 for v in item.dimensions)
                pouch = pouch_model.pouch_dims_mm(settings.pouch_size, settings.pouch_width_mm, settings.pouch_height_mm, settings.pouch_depth_mm)
                if not pouch_model.fits(dims, pouch):
                    _alert(layout, f"{item.name} ({dims[0]:.0f} × {dims[1]:.0f} × {dims[2]:.0f} mm) does not fit "
                                   f"the {pouch[0]:.0f} × {pouch[1]:.0f} × {pouch[2]:.0f} mm pouch")
        else:
            col.prop(settings, "width_preset", text="Width")
            if settings.width_preset == 'CUSTOM':
                col.prop(settings, "custom_width_mm", text="Custom")


class _LinePanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Conveyor"
    bl_parent_id = "VIEW3D_PT_conveyor_builder"

    @classmethod
    def poll(cls, context):
        return _active_line(context) is not None


class VIEW3D_PT_conveyor_line(_LinePanel, bpy.types.Panel):
    """The rest of the line: direction, rollers, fences, and how it is
    docked onto other lines."""
    bl_label = "Line"
    bl_order = 1

    def draw_header_preset(self, context):
        settings = _active_line(context).conveyor_line
        words = ["Reverse" if settings.reverse else "Forward"]
        if settings.guide_rails:
            words.append("fences")
        _dim_label(self.layout, "  ·  ".join(words))

    def draw(self, context):
        layout = self.layout
        obj = _active_line(context)
        settings = obj.conveyor_line
        from ..model.public_api import LAYOUT_KEY, addon_name
        from ..operators.detect_junctions import origin_dock
        from ..operators.public_api import record

        laid_out = record(obj, LAYOUT_KEY)
        if laid_out is not None:  # R21: another add-on laid the line out along its points
            _dim_label(layout, f"Laid out by {addon_name(laid_out.get('by'))} along {laid_out.get('points', 0)} points")
        # The flow (direction, goods in / out) lives under Populate with the
        # throughput and the percentages (user request 2026-10-09).
        conveyor_type = loader.get_conveyor_types().get(settings.conveyor_type)
        if conveyor_type is not None and conveyor_type.cross_section == "roller":
            from ..operators.build_line import catalog_roller_pitch_mm

            row = layout.row(align=True)
            row.prop(settings, "roller_pitch_mm", text="Roller pitch")
            _dim_label(row, f"cat. {catalog_roller_pitch_mm(settings):.0f}")
        if conveyor_type is None or conveyor_type.cross_section != "pouch":  # an overhead rail has no fences or nose-overs
            row = layout.row(align=True)
            row.prop(settings, "guide_rails", toggle=True, text="Fences", icon='MOD_LATTICE')
            row.prop(settings, "nose_over", toggle=True, text="Nose-over")
        from ..model import legs as legs_model

        is_pouch = conveyor_type is not None and conveyor_type.cross_section == "pouch"
        hung = settings.support_mount == 'CEILING'
        col = layout.column(align=True)
        col.row(align=True).prop(settings, "support_mount", expand=True)
        if hung:  # where it hangs from: the hall's clear height (R17), else the Scene setting
            from ..operators.ceilings import FROM_KEY, Z_KEY

            z = float(settings.get(Z_KEY, context.scene.conveyor_settings.ceiling_z))
            _dim_label(col, f"Hangs from {z:.2f} m · {settings.get(FROM_KEY, '') or 'Scene ceiling level'}")
        col.prop(settings, "support_spacing_m", text="Supports every" if (is_pouch or hung) else "Legs every")
        col.prop(context.scene.conveyor_settings, "edit_stands", text="Edit stands", icon='TOOL_SETTINGS', toggle=True)
        from ..operators.stands import ADD_KEY, stand_records

        taken_out, added = len(stand_records(obj)), len(stand_records(obj, ADD_KEY))
        if context.scene.conveyor_settings.edit_stands:
            _dim_label(col, "− takes a stand out, + adds one")
        if taken_out or added:
            row = col.row(align=True)
            _dim_label(row, " · ".join(t for t in (f"{taken_out} taken out" if taken_out else "", f"{added} added" if added else "") if t))
            row.operator("conveyor.stands_restore_all", text="Reset", icon='LOOP_BACK').line = obj.name
        span = float(settings.get("leg_free_span_m", 0.0) or 0.0)
        if span > legs_model.MAX_FREE_SPAN_M + 1e-6:
            _alert(layout, f"{span:.1f} m without a support: a span this long needs a bridge frame or more supports")
        self._draw_docking(layout, context, obj, settings)

    @staticmethod
    def _draw_docking(layout, context, obj, settings):
        from ..operators.detect_junctions import attach_note, docked_diverter, docked_junction, origin_dock
        from ..operators.ports import draw_port

        draw_port(layout, context, obj)  # a rack's port, when the line starts or ends on one
        from ..operators import obstacles

        for hit in obstacles.hits_of(obj)[:4]:  # R13: the goods envelope crosses a wall, column, stair, shaft or keep-out
            _alert(layout, obstacles.describe(hit))
        if origin_dock(context, obj) is not None:
            from ..operators.junction_edit import draw_chooser

            layout.separator(factor=0.5)
            draw_chooser(layout, context, obj, compact=True)
        elif attach_note(obj):
            layout.label(text=attach_note(obj), icon='ERROR')
        branch = docked_diverter(context, obj)
        if branch is not None:
            line, i = branch
            seg = line.conveyor_line.segments[i]
            row = layout.row(align=True)
            row.label(text=f"Branch of {line.name}  ({'RAT side' if seg.module_kind == 'RAT' else seg.merge_angle + '°'})", icon='LINKED')
            row.operator("conveyor.detach", text="", icon='UNLINKED')
        dock = docked_junction(context, obj)
        if dock is not None:
            line, i = dock
            seg = line.conveyor_line.segments[i]
            row = layout.row(align=True)
            row.label(text=f"Feeds {line.name}  ({'RAT side' if seg.module_kind == 'RAT' else seg.merge_angle + '°'})", icon='LINKED')
            row.operator("conveyor.detach", text="", icon='UNLINKED')
        elif not settings.dock_enabled:
            row = layout.row(align=True)
            row.label(text="Docking off", icon='UNLINKED')
            row.operator("conveyor.dock", text="Dock", icon='LINKED')


class VIEW3D_PT_conveyor_piece(_LinePanel, bpy.types.Panel):
    """The selected piece: its exact values and everything the strip under
    the keys does not show."""
    bl_label = "Details"
    bl_order = 2

    def draw_header_preset(self, context):
        settings = _active_line(context).conveyor_line
        i = settings.active_segment_index
        if 0 <= i < len(settings.segments):
            _dim_label(self.layout, f"Piece {i + 1}")

    def draw(self, context):
        layout = self.layout
        obj = _active_line(context)
        settings = obj.conveyor_line
        scene = context.scene
        i = settings.active_segment_index
        if not (0 <= i < len(settings.segments)):
            _dim_label(layout, "No piece selected")
            return
        seg = settings.segments[i]
        col = layout.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(seg, "kind", text="Kind")
        if seg.kind == 'CURVE':
            col.prop(seg, "curve_angle_deg", text="Angle")
            if seg.curve_radius == 'CUSTOM':
                col.prop(seg, "custom_radius_mm", text="Radius (mm)")
        elif seg.kind == 'SPIRAL':
            col.prop(seg, "spiral_angle_deg", text="Turn")
            col.prop(seg, "height_m", text="Height")  # negative: it winds down (user, 2026-10-12: "control the height easily in Details")
            row = col.row(align=True)
            for m in (1, 2, 3, 4):
                row.operator("conveyor.set_spiral_height", text=f"{m} m", depress=(abs(abs(seg.rise_mm) - m * 1000.0) < 1.0)).height_m = float(m)
            row.operator("conveyor.spiral_flip", text="Down", icon='SORT_DESC', depress=(seg.rise_mm < 0.0))
            col.prop(seg, "curve_radius", text="Inside radius")
            if seg.curve_radius == 'CUSTOM':
                col.prop(seg, "custom_radius_mm", text="Radius (mm)")
        elif seg.kind == 'MODULE':
            col.prop(seg, "module_kind", text="Module")
        if seg.kind != 'SPIRAL':  # a spiral hangs on its drum
            col.prop(seg, "legs", text="Hangers" if settings.support_mount == 'CEILING' else "Legs")  # off: a tunnel or a walkway under this piece
        self._draw_piece(layout, context, obj, settings, seg, scene)

    def _draw_piece(self, box, context, obj, settings, seg, scene):
        if seg.kind in ('STRAIGHT', 'INCLINE'):
            self._draw_straight(box, settings, seg, scene)
        elif seg.kind == 'SPIRAL':
            self._rate_alert(box, context, obj, 'SPIRAL')
        elif seg.kind == 'MODULE':
            self._draw_module(box, context, obj, settings, seg, scene)

    @staticmethod
    def _fork_count(box, context, obj, seg) -> None:
        """How many forks ride the loop at this pitch (the tree's own math)."""
        from ..model import lift_parts, segments as seg_model
        from ..operators.stream import tree_for

        try:
            slot = tree_for(context, obj).spacing
        except Exception:
            return
        scene = context.scene
        height = max(units.mm_to_bu(seg.rise_mm, scene), 0.3)
        layout = lift_parts.lift_layout(height, seg.lift_shape)
        wanted = max(units.mm_to_bu(float(seg.lift_fork_pitch_mm), scene), 0.05)
        m = max(int(slot // wanted), 1)
        fork_pitch = slot / m
        n = max(int(round(layout.loop_length / fork_pitch)), 1)
        _dim_label(box, f"{n} forks, {fork_pitch * 1000.0:.0f} mm apart; goods on every {'fork' if m == 1 else f'{m}. fork'}")

    @staticmethod
    def _rat_width_alert(box, context, obj, settings) -> None:
        """A right-angle transfer does not turn the goods: after it they run
        with their long side ACROSS the line. A 600 mm tote on a 500 mm line
        overhangs the fences."""
        if not settings.populate:
            return
        from ..operators.build_line import resolve_width_mm
        from ..operators.populate import populate_item_length

        across_mm = units.bu_to_mm(populate_item_length(context, obj), context.scene)
        width_mm = float(resolve_width_mm(settings))
        if across_mm > width_mm + 1.0:
            _alert(box, f"Goods run {across_mm:.0f} mm across after the transfer: widen the line ({width_mm:.0f} mm)")

    @staticmethod
    def _lift_floor_alert(box, context, obj, settings) -> None:
        """The column and the forks' bottom turn reach UNDER_BED below the
        infeed: on a line laid on the floor they would be underground (the
        tree hides those forks), so ask for the line to be raised."""
        from ..model import lift_parts
        from ..operators.build_line import segment_frames_for

        i = settings.active_segment_index
        try:
            frames = segment_frames_for(context, obj)
        except Exception:
            return
        if not (0 <= i < len(frames)):
            return
        clearance = obj.matrix_world.translation[2] + frames[i][0].z - float(context.scene.conveyor_settings.floor_z)
        short = lift_parts.UNDER_BED - clearance
        if short > 0.005:
            _alert(box, f"Raise the line {short:.2f} m: the column reaches {lift_parts.UNDER_BED:.2f} m under the bed")

    @staticmethod
    def _buffer_numbers(box, context, obj, settings) -> None:
        """What leaves (Output % of what the line before brings) and when the
        buffer is full -- in % and time, never items an hour (no
        physics in the UI). A buffer that fills after the scene's
        end frame says so: playback never shows it full."""
        from ..operators.buffers import merge_downstream
        from ..operators.flows import buffer_in_ph
        from ..operators.junction_ports import buffer_capacity
        from ..operators.stream import tree_for

        index = settings.active_segment_index
        seg = settings.segments[index]
        try:
            in_ph = buffer_in_ph(context, obj).get(index, 0.0)
            tree = tree_for(context, obj)
        except Exception:
            return
        if in_ph <= 0.0:
            _dim_label(box, "Populate the line before it")
            return
        info = tree.buffer_info.get((obj.name, index)) or {"slug": 0, "full_s": math.inf}
        f = int(seg.buffer_out_pct) / 100.0
        held = buffer_capacity(context, obj, index)
        if f >= 1.0 - 1e-9:
            _dim_label(box, "Lets everything through")
        elif held <= 0:
            _dim_label(box, "Too short to hold an item: passes")
        else:
            _dim_label(box, f"Lets out {f * 100.0:.0f} % of what arrives")
            _dim_label(box, buffer_fill_text(held / ((1.0 - f) * in_ph) * 3600.0, held,
                                             info.get("full_s", math.inf), context.scene))
        if SHOW_THROUGHPUT_PHYSICS:  # dormant since 2.22
            _dim_label(box, f"In {in_ph:,.0f}/h, out {in_ph * f:,.0f}/h")
        if info["slug"]:
            _dim_label(box, f"Slug of {info['slug']} items")
        elif settings.segments[index].buffer_release == 'SLUG':
            _dim_label(box, "Too short for a slug: releases one by one")
        if settings.segments[index].buffer_release == 'SLUG':
            other = merge_downstream(context, obj, index)
            if other:
                _alert(box, f"Slug release leaves the slot grid: {other} merging in downstream will collide")

    @staticmethod
    def _rate_alert(box, context, obj, key: str) -> None:
        """The chain rule: the slowest element sets the system rate -- flag
        an element whose practical rate is below the group's throughput.
        Dormant since 2.22 (no throughput physics in the UI)."""
        if not SHOW_THROUGHPUT_PHYSICS:
            return
        info = loader.get_inline_module_info().get(key, {})
        rate = info.get("rate_per_h")
        if not rate:
            return
        from ..operators.stream import line_load_ph

        try:
            load = line_load_ph(context, obj)
        except Exception:
            return
        if load and load > rate:
            _alert(box, f"Bottleneck: {load:,.0f}/h through a {rate:,.0f}/h {info.get('label', key).lower()}")

    def _draw_module(self, box, context, obj, settings, seg, scene):
        col = box.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        if seg.module_kind == 'RAT':
            col.prop(seg, "module_exit", text="Exit")
            self._rat_width_alert(box, context, obj, settings)
            if seg.module_exit in ('LEFT', 'RIGHT'):  # a corner is square to the line (build_line.rat_footprint_mm)
                from ..operators.build_line import rat_footprint_mm

                _dim_label(col, f"Square to the line: {rat_footprint_mm(seg, settings, scene) / 1000.0:.2f} m")
            else:
                col.prop(seg, "length_m", text="Length")
            from ..operators.build_line import resolve_width_mm as _rw
            from ..operators.detect_junctions import _line_role

            for side, name, face_mm in (("Left", seg.merge_source, seg.rat_face_left_mm), ("Right", seg.merge_source_right, seg.rat_face_right_mm),
                                        ("End", getattr(seg, "rat_source_end", ""), getattr(seg, "rat_face_end_mm", 0.0))):
                if not name:
                    continue
                line = context.scene.objects.get(name)
                if line is None:
                    continue
                ls = line.conveyor_line
                ctype_l = loader.get_conveyor_types().get(ls.conveyor_type)
                kind = ctype_l.label.lower() if ctype_l is not None else ls.conveyor_type
                _dim_label(box, f"{side}: {name} · {_rw(ls):.0f} mm {kind} · {'in' if _line_role(line) == 'MERGE' else 'out'}")
        elif seg.module_kind in ('MERGE', 'DIVERTER'):
            col.prop(seg, "merge_side", text="Infeed side" if seg.module_kind == 'MERGE' else "Outfeed side")
            col.prop(seg, "merge_angle", text="Angle")
            if seg.merge_side == 'BOTH':
                col.prop(seg, "merge_infeed_mm", text="Left face")
                col.prop(seg, "merge_infeed_right_mm", text="Right face")
            else:
                col.prop(seg, "merge_infeed_mm", text="Infeed width" if seg.module_kind == 'MERGE' else "Branch width")
            self._draw_junction_tech(col, context, obj, seg, settings.active_segment_index)
            if seg.module_kind == 'DIVERTER':
                col.prop(seg, "route_item", text="Route")
                if seg.route_class >= 0 and not settings.populate:
                    _alert(box, "Turn on Populate for routing")
                elif seg.route_class >= 0 and settings.populate_item is not None:
                    _alert(box, "Routing needs the placeholder items (clear the item)")
                if int(seg.merge_angle) >= 90 and settings.populate:
                    from ..operators.populate import populate_item_length

                    from ..operators.build_line import infeed_for_side, junction_sides

                    item_mm = units.bu_to_mm(populate_item_length(context, obj), scene)
                    narrow = min(infeed_for_side(seg, sd) for sd in junction_sides(seg))
                    if narrow < item_mm - 1.0:
                        _alert(box, f"Branch {narrow:.0f} mm narrower than the item is long ({item_mm:.0f} mm): it turns on the way out")
            docked = [n for n in (seg.merge_source, seg.merge_source_right if seg.merge_side == 'BOTH' else "") if n]
            if docked:
                _dim_label(box, ("Docked: " if seg.module_kind == 'MERGE' else "Branches: ") + ", ".join(docked))
        elif seg.module_kind == 'WRAPPER':
            col.prop(seg, "wrapper_mode", text="Mode")
            col.prop(seg, "length_m", text="Length")
        elif seg.module_kind == 'ARB':
            col.prop(seg, "arb_function", text="Function")
            if seg.arb_function != 'CENTER':
                col.prop(seg, "arb_pivot", text="Fixed pivot")
            col.prop(seg, "length_m", text="Length")
        elif seg.module_kind == 'LIFT':
            col.prop(seg, "lift_shape", text="Shape")
            col.prop(seg, "lift_side", text="Column")
            col.prop(seg, "height_m", text="Height")
            col.prop(seg, "lift_fork_pitch_mm", text="Fork pitch")
            self._fork_count(box, context, obj, seg)
            self._lift_floor_alert(box, context, obj, settings)
            if seg.rise_mm < 0.0:
                _alert(box, "Lifts only climb: draw it from the lower floor, then Reverse")
        elif seg.module_kind == 'BUFFER':
            col.prop(seg, "length_m", text="Length")
            col.prop(seg, "buffer_gap_mm", text="Queue gap")
            col.prop(seg, "buffer_out_pct", text="Output")
            col.prop(seg, "buffer_release", text="Release")
            from ..operators.populate import populate_item_length

            pitch_m = populate_item_length(context, obj) + units.mm_to_bu(seg.buffer_gap_mm, scene)
            _dim_label(box, f"{int(units.mm_to_bu(seg.length_mm, scene) // pitch_m)} zones of {pitch_m:.2f} m")
            self._buffer_numbers(box, context, obj, settings)
            ctype = loader.get_conveyor_types().get(settings.conveyor_type)
            if ctype is not None and ctype.cross_section != "roller":
                _alert(box, "A plain belt cannot accumulate: buffer on a roller (MDR) line")
        if seg.module_kind in ('LIFT', 'SPIRAL', 'RAT', 'ARB', 'WRAPPER'):
            self._rate_alert(box, context, obj, seg.module_kind)

    def _draw_straight(self, box, settings, seg, scene):
        rise = segment_rise_mm(seg)
        if abs(rise) < 0.5:
            return
        angle = incline_from_rise(rise, seg.length_mm)
        _dim_label(box, f"Rise {'+' if rise > 0 else '-'}{units.format_length_mm(abs(rise), scene)}  ({abs(angle):.1f}° {'up' if rise > 0 else 'down'})")
        self._incline_warning(box, settings, abs(angle))

    @staticmethod
    def _incline_warning(layout, settings, angle: float):
        if angle < 0.05:
            return
        ctype = loader.get_conveyor_types().get(settings.conveyor_type)
        limit = loader.incline_limit_deg(settings.conveyor_type)
        if ctype is None or limit is None:
            return
        if angle > limit:
            _alert(layout, f"{ctype.label}: no incline" if limit <= 0.0 else f"Over the {limit:.0f}° limit for {ctype.label}")
        else:
            totes = loader.get_incline_rules().get("plastic_totes_max_deg")
            if totes and angle > float(totes) and settings.conveyor_type == 'belt':
                _dim_label(layout, f"Totes slip above {float(totes):.0f}°; cartons OK to {limit:.0f}°")

    @staticmethod
    def _draw_junction_tech(col, context, obj, seg, index: int):
        """The technology, and a bottleneck warning when the lines' throughput exceeds its rate."""
        from ..operators.build_line import resolve_junction_tech
        from ..operators.stream import junction_load_ph

        col.prop(seg, "junction_tech", text="Transfer")
        techs = loader.get_technologies()
        used = resolve_junction_tech(seg)
        tech = techs[used]
        if seg.junction_tech not in ('AUTO', used):
            _alert(col, f"{techs[seg.junction_tech].label} not available at this angle: {tech.label}")
        if not SHOW_THROUGHPUT_PHYSICS:
            return  # no bottleneck alerts (dormant)
        try:
            load = junction_load_ph(context, obj, index)
        except Exception:
            load = None
        if load is not None and tech.rate_per_h and load > tech.rate_per_h:
            _alert(col, f"Bottleneck: {load:,.0f}/h through a {tech.rate_per_h:,.0f}/h unit")


def buffer_fill_text(seconds: float, held: int, full_s: float, scene) -> str:
    """"Full after 17 s, then holds 4", or "Full after 4 min (after scene
    end)" when the scene time it is full at (operators/stream buffer_info
    full_s) is past the scene's end frame. At most ~36 characters."""
    if seconds < 59.5:
        when = f"{seconds:.0f} s"
    elif seconds < 599.5 * 60.0:
        when = f"{seconds / 60.0:.0f} min"
    else:
        when = f"{seconds / 3600.0:.0f} h"
    fps = scene.render.fps / (scene.render.fps_base or 1.0)
    if math.isfinite(full_s) and full_s * fps > scene.frame_end:
        return f"Full after {when} (after scene end)"
    return f"Full after {when}, then holds {held}"


SHOW_THROUGHPUT_PHYSICS = False  # rates, capacities and bottlenecks stay out of the UI; the code stays for later


def _alert(layout, text: str) -> None:
    """A warning: the icon on the first line, a long message wrapped under it (never cut with "...")."""
    col = layout.column(align=True)
    col.alert = True
    for i, line in enumerate(_lines(text)):
        col.label(text=line, icon='ERROR' if i == 0 else 'BLANK1')


class VIEW3D_PT_conveyor_populate(_LinePanel, bpy.types.Panel):
    """Goods on the line. The checkbox in the header turns it on AND opens
    the eyedropper (props/line_settings._on_populate_changed)."""
    bl_label = "Populate"
    bl_order = 3

    def draw_header(self, context):
        from ..operators.stream import parent_of

        obj = _active_line(context)
        parent = parent_of(context, obj)
        if parent is not None and parent[0] in ('DIVERTER', 'CONTINUE'):
            # It carries its master's goods whatever its own box says (UI rule: the state
            # in effect): a ticked box that cannot be changed here.
            row = self.layout.row()
            row.enabled = False
            row.label(text="", icon='CHECKBOX_HLT')
            return
        self.layout.prop(obj.conveyor_line, "populate", text="")

    def draw_header_preset(self, context):
        from ..operators.stream import effective_item, parent_of, stream_root

        obj = _active_line(context)
        settings = obj.conveyor_line
        parent = parent_of(context, obj)
        if parent is not None and parent[0] in ('DIVERTER', 'CONTINUE'):
            _dim_label(self.layout, f"goods from {stream_root(context, obj).name}")
            return
        if settings.populate or parent is not None:
            item = effective_item(context, obj)  # a docked line carries the main line's item
            from ..model.public_api import ITEM_KEY
            from ..operators.public_api import record

            set_from = record(obj, ITEM_KEY)
            suffix = f" (from {set_from['by']})" if set_from and item is not None and set_from.get("object") == item.name else ""
            _dim_label(self.layout, (item.name + suffix) if item is not None else "placeholder totes")

    def draw(self, context):
        layout = self.layout
        obj = _active_line(context)
        settings = obj.conveyor_line
        from ..operators.populate import routed_from

        from ..operators.detect_junctions import origin_dock
        from ..operators.stream import parent_of, stream_root, tree_for

        docked = parent_of(context, obj)
        # 1. The flow. Everything about the goods lives here (user request
        # 2026-10-09): on a free line its direction; on a line attached by
        # its origin whether it brings goods INTO the main line or takes them
        # OUT (the pose only decides the first attach; below 90° the line
        # swings to the mirrored angle, at 90° only the flow flips).
        row = layout.row(align=True)
        row.scale_y = 1.15
        if origin_dock(context, obj) is not None:
            for role, text, icon in (('MERGE', "Goods in", 'IMPORT'), ('DIVERTER', "Goods out", 'EXPORT')):
                op = row.operator("conveyor.junction_set", text=text, icon=icon, depress=(settings.reverse == (role == 'MERGE')))
                op.line, op.role = obj.name, role
        else:
            row.prop(settings, "reverse", text="Reverse  (end → start)" if settings.reverse else "Forward  (start → end)",
                     toggle=True, icon='LOOP_BACK' if settings.reverse else 'LOOP_FORWARDS')
        # 2. The item.
        source = routed_from(context, obj)
        item = settings.populate_item
        row = layout.row(align=True)
        row.scale_y = 1.2
        row.operator("conveyor.pick_item", text=f"Carrying {item.name}" if item is not None else "Pick the item to carry",
                     icon='EYEDROPPER')
        if item is not None:
            row.operator("conveyor.clear_item", text="", icon='X')
        col = layout.column(align=True)
        col.enabled = settings.populate and source is None
        col.prop(settings, "populate_item", text="")
        if source is not None and source[2].route_class >= 0:
            main, _i, seg = source
            _dim_label(layout, f"Takes {seg.route_item.replace('Placeholder ', '')} from {main.name}")
        elif docked is not None and item is None and source is None:
            _dim_label(layout, f"Carries what {stream_root(context, obj).name} carries")
        # Goods wider than the line they ride on (a 90° transfer keeps their orientation).
        from ..operators.populate import overhang_notes

        for text, dim in overhang_notes(context, obj):
            if dim:
                _dim_label(layout, text)
            else:
                layout.label(text=text, icon='INFO')
        # 3. The flow (simple flow): the master sets the stream with
        # Population and Speed, the lines connected to it follow; a branch
        # takes its Share of the master, a feeder brings its own Population
        # at the master's speed. Every number is the one in effect
        # (operators/flows.py; panel text within the sidebar's width).
        try:
            tree = tree_for(context, obj)  # the group's numbers, once per draw
        except Exception:
            tree = None
        self._flow(layout, context, obj, settings, docked, tree)
        ctype = loader.get_conveyor_types().get(settings.conveyor_type)
        speed = tree.speed if tree is not None else abs(float(settings.speed_m_s))
        if ctype is not None and ctype.speed_m_s[1] > 0 and speed > ctype.speed_m_s[1] + 1e-6:
            _alert(layout, f"Typical {ctype.label.lower()}: {ctype.speed_m_s[1]:g} m/s")
        if settings.populate and ctype is not None and ctype.cross_section == "roller":
            self._three_rollers(layout, context, obj, settings)

    @staticmethod
    def _flow(layout, context, obj, settings, docked, tree) -> None:
        """Population and Speed where this line sets them, else what it
        follows: "Master", "30 % of Main", "Stream of Main"."""
        from ..operators import flows

        gf = tree.flow if tree is not None else None
        col = layout.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        master = gf.master if gf is not None else obj.name
        is_master = master == obj.name
        own_goods = docked is None or docked[0] == 'MERGE'  # the root, or a feeder bringing its own
        if gf is not None and not is_master:
            text = flows.share_text(gf, obj.name)
            if text:
                _dim_label(col, text)
        elif tree is not None and tree.shared:
            # Why it is the master: pinned, or simply the first line of the stream.
            _dim_label(col, "Master (pinned)" if settings.flow_master else "Master (first on the stream)")
        if is_master or (own_goods and docked is not None):
            sub = col.column(align=True)
            sub.enabled = settings.populate or docked is not None
            sub.prop(settings, "population_pct", text="Population")
            from ..model.public_api import FLOW_KEY, RATE_KEY, addon_name
            from ..operators.public_api import record

            set_from = record(obj, FLOW_KEY) or record(obj, RATE_KEY)
            if set_from is not None:  # R22 set_line_flow, R6 set_line_rate (a shim): another add-on set it
                _dim_label(col, f"Set by {addon_name(set_from.get('by'))}")
            effective = gf.population.get(obj.name) if gf is not None else None
            carries = settings.populate or docked is not None  # Populate off is not a cap: nothing runs
            if carries and effective is not None and effective * 100.0 < float(settings.population_pct) - 0.5:
                # A capped merge on this line: the main gives way, feeders first (the merge rule, 2026-10-26)
                by_merge = any(s.kind == 'MODULE' and s.module_kind == 'MERGE' and (s.merge_source or s.merge_source_right)
                               for s in settings.segments)
                _dim_label(col, f"Runs at {effective * 100.0:.0f} % (capped{' by the merge' if by_merge else ''})")
        elif gf is not None and obj.name in gf.population:
            _dim_label(col, f"Population {gf.population[obj.name] * 100.0:.0f} %")
        if docked is not None and docked[0] == 'DIVERTER':
            col.prop(settings, "share_pct", text="Share")  # of the master (the line above names it)
        if is_master or (gf is not None and obj.name in gf.own_speed):
            col.prop(settings, "speed_m_s", text="Speed")  # its own: the master's, or a line a port leads (it keeps its Speed)
        else:
            speed = tree.speed if tree is not None else abs(float(settings.speed_m_s))
            _dim_label(col, f"Speed {speed:.2f} m/s, from {master}")
        if tree is not None and tree.shared:  # on a lone line pinning changes nothing
            row = layout.row(align=True)
            row.use_property_split = False  # the words on the button: "Pin as master" / "Pinned"
            row.prop(settings, "flow_master", text="Pinned" if settings.flow_master else "Pin as master", toggle=True,
                     icon='PINNED' if settings.flow_master else 'UNPINNED')

    @staticmethod
    def _three_rollers(layout, context, obj, settings) -> None:
        """The roller-conveyor rule of thumb: the smallest item must rest on at
        least three rollers -- and after a right-angle transfer its SHORT side
        is the one along the rollers."""
        from ..operators.build_line import effective_roller_pitch_mm
        from ..operators.populate import item_extents, resolve_forward_axis

        item = settings.populate_item
        if item is None or item == obj:
            return  # the placeholder totes (600 x 400) sit on five rollers at any catalog pitch
        sx, sy, _z = item_extents(item)
        along = sx if resolve_forward_axis(settings, item) in ('X', 'NEG_X') else sy
        across = sy if along == sx else sx
        turns = any(seg.kind == 'MODULE' and (seg.module_kind == 'RAT' or (seg.module_kind in ('MERGE', 'DIVERTER') and int(seg.merge_angle) >= 90))
                    for seg in settings.segments)
        side_mm = units.bu_to_mm(min(along, across) if turns else along, context.scene)
        pitch = effective_roller_pitch_mm(settings)
        if pitch > 0 and side_mm / pitch < 3.0:
            _alert(layout, f"On {side_mm / pitch:.1f} rollers: needs 3")
            _dim_label(layout, f"Closer than {pitch:.0f} mm, or a belt")


class VIEW3D_PT_conveyor_placement(_LinePanel, bpy.types.Panel):
    """How the goods sit on the line (rarely changed)."""
    bl_label = "Placement"
    bl_parent_id = "VIEW3D_PT_conveyor_populate"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        obj = _active_line(context)
        settings = obj.conveyor_line
        from ..operators.populate import routed_from

        col = layout.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        col.enabled = settings.populate and routed_from(context, obj) is None
        # (Spacing and Fill set the density before 2.22; Population does now.)
        col.prop(settings, "populate_forward_axis", text="Forward axis")
        col.prop(settings, "populate_rotation_deg", text="Rotation")
        col.prop(settings, "populate_lane_mm", text="Lane offset")


class VIEW3D_PT_conveyor_pieces(_LinePanel, bpy.types.Panel):
    """The pieces in order: select, reorder, duplicate, remove."""
    bl_label = "Pieces"
    bl_order = 0  # right under the keys (user, 2026-10-10)
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header_preset(self, context):
        settings = _active_line(context).conveyor_line
        _dim_label(self.layout, f"{len(settings.segments)}  ·  {units.format_length_mm(settings.total_length_mm, context.scene)}")

    def draw(self, context):
        layout = self.layout
        obj = _active_line(context)
        settings = obj.conveyor_line
        row = layout.row()
        row.template_list("CONVEYOR_UL_segments", "", settings, "segments", settings, "active_segment_index", rows=5)
        side = row.column(align=True)
        side.operator("conveyor.segment_duplicate", text="", icon='DUPLICATE')
        side.operator("conveyor.segment_remove", text="", icon='X')
        side.separator()
        side.operator("conveyor.segment_move", text="", icon='TRIA_UP').direction = 'UP'
        side.operator("conveyor.segment_move", text="", icon='TRIA_DOWN').direction = 'DOWN'
        ex, ey, ez, heading = settings.end_pose
        _dim_label(layout, f"Ends at x {ex:.2f}  y {ey:.2f}  z {ez:.2f} m, heading {heading:.0f}°")
        row = layout.row(align=True)
        row.operator("conveyor.build_line", text="Rebuild", icon='FILE_REFRESH')
        row.operator("conveyor.detect_junctions", text="", icon='SNAP_MIDPOINT')


def _draw_floor_marks(layout, context) -> None:
    """Where the legs land (contract v2.1 R3, amended R3.1): the Floors
    collection, else the marked floors (`wh_floor` true: Floorplan's slabs,
    Racks' walkway decks, the user's own) with every other mesh below them
    unless it is marked Not a floor -- or, with Marked only, the marked floors
    alone. The active mesh gets Floor / Not a floor / Auto: our own marks
    only, never another add-on's."""
    from ..operators import floors

    cs = context.scene.conveyor_settings
    scene = context.scene
    marked, excluded = floors.marked_floors(scene), floors.excluded_floors(scene)
    if cs.floor_collection is not None:
        _dim_label(layout, f"Legs land on the {cs.floor_collection.name} collection")
    elif cs.floors_marked_only:
        _dim_label(layout, f"Legs land on {len(marked)} marked floor{'s' if len(marked) != 1 else ''} only")
    else:
        _dim_label(layout, "Legs land on any mesh below them")
        words = []
        if marked:
            words.append(f"{len(marked)} marked floor{'s' if len(marked) != 1 else ''}")
        if excluded:
            words.append(f"{len(excluded)} not a floor")
        if words:
            _dim_label(layout, "  ·  ".join(words))
    obj = context.active_object
    if obj is None or obj.type != 'MESH' or floors.is_foreign(obj):
        return
    state = floors.floor_mark(obj)
    if state is not None and not floors.marked_by_us(obj):
        _dim_label(layout, f"{obj.name}: {'a floor' if state else 'not a floor'} (marked by another add-on)")
        return
    _dim_label(layout, obj.name)
    row = layout.row(align=True)
    for mark, label, current in (('FLOOR', "Floor", state is True), ('NOT_FLOOR', "Not a floor", state is False), ('AUTO', "Auto", state is None)):
        row.operator("conveyor.mark_floor", text=label, depress=current).mark = mark


class VIEW3D_PT_conveyor_scene(bpy.types.Panel):
    bl_label = "Scene"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Conveyor"
    bl_parent_id = "VIEW3D_PT_conveyor_builder"
    bl_order = 5
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        cs = context.scene.conveyor_settings
        col = layout.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(cs, "floor_z", text="Floor level")
        col.prop(cs, "ceiling_z", text="Ceiling level")
        col.prop(cs, "floor_collection", text="Floors")
        sub = col.row()
        sub.enabled = cs.floor_collection is None  # the collection overrides it
        sub.prop(cs, "floors_marked_only", text="Marked only")
        col.prop(cs, "dock_distance_m", text="Dock within")
        col.prop(cs, "time_scale", text="Time scale ×")
        _draw_floor_marks(layout, context)
        row = layout.row(align=True)
        row.prop(cs, "show_dimensions", toggle=True, text="Dimensions", icon='DRIVER_DISTANCE')
        row.prop(cs, "show_flow_markers", toggle=True, text="Flow", icon='EMPTY_SINGLE_ARROW')
        row.prop(cs, "show_spine", toggle=True, text="Spine", icon='CURVE_PATH')
        layout.separator(factor=0.5)
        is_playing = context.screen.is_animation_playing
        row = layout.row(align=True)
        row.operator("screen.animation_play", text="Pause" if is_playing else "Play", icon='PAUSE' if is_playing else 'PLAY')
        row.operator("conveyor.regenerate_all", text="Rebuild all", icon='FILE_REFRESH')
        from ..operators.obstacles import scene_checks

        crossings = len(scene_checks(context))
        if crossings:
            row = layout.row(align=True)
            row.alert = True
            row.label(text=f"{crossings} obstacle crossing{'s' if crossings != 1 else ''}", icon='ERROR')
            row.operator("conveyor.checks", text="", icon='INFO')


classes = (
    CONVEYOR_UL_segments,
    VIEW3D_PT_conveyor_builder,
    VIEW3D_PT_conveyor_line,
    VIEW3D_PT_conveyor_piece,
    VIEW3D_PT_conveyor_populate,
    VIEW3D_PT_conveyor_placement,
    VIEW3D_PT_conveyor_pieces,
    VIEW3D_PT_conveyor_scene,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
