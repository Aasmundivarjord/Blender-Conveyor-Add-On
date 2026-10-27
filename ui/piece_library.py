"""The piece library: every piece type as a small transparent render with
its name, three to a row, behind the More key (and Alt + Down in the
viewport). The arrow keys stay the fast path for straights and curves; the
library is where you SEE what a right-angle transfer or an angled-roller
turn is before you add one: a picture of every type of piece behind the
plus sign.

The renders live in icons/pieces/<KEY>.png (256 px, transparent, rendered
in Blender from the plugin's own geometry) and
are loaded once into a preview collection; a missing file falls back to the
schematic pictogram (ui/line_map.picto).
"""
from __future__ import annotations

from pathlib import Path

import bpy
import bpy.utils.previews

ICON_DIR = Path(__file__).resolve().parents[1] / "icons" / "pieces"

# (label, pictogram key, segment_add kind, module kind, RAT exit, what it does)
PIECES = (
    ("Straight", 'STRAIGHT', 'STRAIGHT', "", "", "A level run; drag the arrow at its end to raise or lower it"),
    ("Curve left", 'CURVE_LEFT', 'CURVE_LEFT', "", "", "Turns the line left; pick the angle under the keys"),
    ("Curve right", 'CURVE_RIGHT', 'CURVE_RIGHT', "", "", "Turns the line right; pick the angle under the keys"),
    ("Spiral", 'SPIRAL', 'SPIRAL', "", "", "Helical climb or descent between floors on a centre drum"),
    ("Right-angle transfer", 'RAT', 'MODULE', "RAT", "LEFT", "Pop-up belts lift the goods and carry them out sideways"),
    ("Vertical lift", 'LIFT', 'MODULE', "LIFT", "", "Fork column: forks rise through the roller combs with the goods"),
    ("Buffer", 'BUFFER', 'MODULE', "BUFFER", "", "Accumulation zone: goods queue against its end, a photo-eye per zone"),
    ("Angled-roller turn", 'ARB', 'MODULE', "ARB", "", "Angled-roller belt: centres the goods or turns them 90° in motion"),
    ("Merge junction", 'MERGE', 'MODULE', "MERGE", "", "Other lines dock on its face and feed goods in"),
    ("Diverter", 'DIVERTER', 'MODULE', "DIVERTER", "", "Sends one item class out onto a branch line"),
    ("Pallet wrapper", 'WRAPPER', 'MODULE', "WRAPPER", "", "Turntable stretch wrapper in the line: wraps (or unwraps) the pallet on its way through"),
)

_previews = None
_loaded: set = set()


def _collection():
    global _previews
    if _previews is None:
        _previews = bpy.utils.previews.new()
    return _previews


def icon(key: str) -> int:
    """icon_value of the piece's render, or of its pictogram when the render
    is missing."""
    pcoll = _collection()
    if key not in _loaded:
        _loaded.add(key)
        path = ICON_DIR / f"{key}.png"
        if path.is_file():
            pv = pcoll.load(key, str(path), 'IMAGE')
            # A file preview loads lazily (the grid would show spinners on its
            # first draw); touching the sizes loads it now.
            _ = pv.image_size[:], pv.icon_size[:]
    if key in pcoll:
        return pcoll[key].icon_id
    from . import line_map

    return line_map.picto(key)


def draw_gallery(layout, entries, columns: int = 3, scale: float = 4.0, current: str = "") -> None:
    """A grid of pictures with a labelled button under each: `entries` =
    [(label, picture key, operator idname, {property: value})]. The entry
    whose key equals `current` is drawn pressed."""
    grid = layout.grid_flow(row_major=True, columns=columns, even_columns=True, even_rows=True, align=False)
    for label, key, idname, props in entries:
        cell = grid.column(align=True)
        picture = cell.row()
        picture.alignment = 'CENTER'
        picture.template_icon(icon_value=icon(key), scale=scale)
        op = cell.operator(idname, text=label, depress=(key == current))
        for name, value in props.items():
            setattr(op, name, value)


def draw_library(layout, context, obj, columns: int = 3, scale: float = 4.0) -> None:
    from ..operators.segments import add_mode_label, adds_piece

    settings = obj.conveyor_line
    layout.label(text=add_mode_label(settings), icon='ADD' if adds_piece(settings) else 'FILE_REFRESH')
    draw_gallery(layout, [(label, key, "conveyor.segment_add", {"kind": kind, "module": module, "exit_side": exit_side})
                          for label, key, kind, module, exit_side, _blurb in PIECES], columns, scale)


def _line(context):
    obj = context.active_object
    return obj if obj is not None and obj.type == 'CURVES' and obj.conveyor_line.is_conveyor_line else None


class CONVEYOR_OT_piece_library(bpy.types.Operator):
    bl_idname = "conveyor.piece_library"
    bl_label = "Piece Library"
    bl_description = "Every piece type with a picture: spiral, transfer, lift, buffer, angled-roller turn, merge junction, diverter"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _line(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=330)

    def draw(self, context):
        draw_library(self.layout, context, context.active_object)

    def execute(self, context):
        return {'FINISHED'}


class CONVEYOR_OT_set_type(bpy.types.Operator):
    bl_idname = "conveyor.set_type"
    bl_label = "Set Conveyor Type"
    bl_description = "Make the active line this type of conveyor"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    type_id: bpy.props.StringProperty()

    @classmethod
    def poll(cls, context):
        return _line(context) is not None

    def execute(self, context):
        settings = _line(context).conveyor_line
        if settings.conveyor_type != self.type_id:
            settings.conveyor_type = self.type_id  # rebuilds
        return {'FINISHED'}


class CONVEYOR_MT_conveyor_types(bpy.types.Menu):
    """The panel's Type row: the offered types (the enum itself keeps every
    type, so a saved line or a script may still use a hidden one)."""
    bl_idname = "CONVEYOR_MT_conveyor_types"
    bl_label = "Conveyor Type"

    def draw(self, context):
        from ..config import loader

        line = _line(context)
        current = line.conveyor_line.conveyor_type if line is not None else ""
        for t in loader.get_offered_types(current).values():
            self.layout.operator("conveyor.set_type", text=t.label, icon='CHECKMARK' if t.id == current else 'NONE').type_id = t.id


class CONVEYOR_OT_type_library(bpy.types.Operator):
    """The conveyor types as pictures (the same gallery as the pieces),
    for the Type row of the panel."""
    bl_idname = "conveyor.type_library"
    bl_label = "Conveyor Types"
    bl_description = "Roller, belt, modular belt or pouch sorter: pick the type from a picture"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _line(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=330)

    def draw(self, context):
        from ..config import loader

        settings = _line(context).conveyor_line
        self.layout.label(text="Conveyor type", icon='OUTLINER_OB_CURVES')
        draw_gallery(self.layout, [(t.label, f"TYPE_{t.id}", "conveyor.set_type", {"type_id": t.id})
                                   for t in loader.get_offered_types(settings.conveyor_type).values()],
                     current=f"TYPE_{settings.conveyor_type}")

    def execute(self, context):
        return {'FINISHED'}


class CONVEYOR_OT_transfer_library(bpy.types.Operator):
    """The transfer technologies of the active line's junction as pictures."""
    bl_idname = "conveyor.transfer_library"
    bl_label = "Transfer Types"
    bl_description = "Angled roller merge, pop-up wheels / belts / chain, high-performance divert, angled-roller belt, pusher: pick the transfer from a picture"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        from ..operators.junction_edit import attached_junction

        obj = _line(context)
        return obj is not None and attached_junction(context, obj) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=330)

    def draw(self, context):
        from ..config import loader
        from ..operators.build_line import resolve_junction_tech
        from ..operators.junction_edit import attached_junction

        obj = _line(context)
        hit = attached_junction(context, obj) if obj is not None else None
        if hit is None:
            return
        main, _index, jseg, _side = hit
        angle, used = int(jseg.merge_angle), resolve_junction_tech(jseg)
        self.layout.label(text=f"Transfer at the {angle}° {'merge' if jseg.module_kind == 'MERGE' else 'divert'} on {main.name}", icon='LINKED')
        entries = []
        for tid, spec in loader.get_technologies().items():
            if jseg.module_kind not in spec.roles:
                continue
            label = spec.label if angle in spec.angles else f"{spec.label} ({min(spec.angles)}–{max(spec.angles)}°)"
            entries.append((label, f"TECH_{tid}", "conveyor.junction_set", {"line": obj.name, "tech": tid}))
        draw_gallery(self.layout, entries, current=f"TECH_{used}")

    def execute(self, context):
        return {'FINISHED'}


classes = (CONVEYOR_OT_piece_library, CONVEYOR_OT_set_type, CONVEYOR_MT_conveyor_types, CONVEYOR_OT_type_library, CONVEYOR_OT_transfer_library)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    global _previews
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
    _loaded.clear()
