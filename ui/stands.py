"""The per-stand buttons (2.14, 2.26.3): with Edit stands on (Line panel), the
active line shows a - at every stand (click: take it out; an added one goes
again), a + at every stand taken out (click: put it back), and a smaller +
in the middle of every gap between two stands (click: add a stand there).
Positions come from the build (operators/build_line: stand_points /
stand_removed_points / stand_gap_points), the same plan the node trees place
the stands from, so a button always sits on its stand."""
from __future__ import annotations

import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Matrix, Vector

from .._wh import contrast
from .theme import GLYPH_MINUS, GLYPH_PLUS

POOL = 48  # buttons made up front (a 70 m line at 1.5 m spacing); more as a longer line needs them
DROP_M = 0.35  # a floor stand's button sits this far below the conveying surface, on its posts
RISE_M = 0.7  # a hanger's this far above it, on its rods over the goods


def _line(context):
    obj = context.active_object
    try:
        if obj is not None and obj.type == 'CURVES' and obj.conveyor_line.is_conveyor_line:
            return obj
    except Exception:
        pass
    return None


def _points(settings, key):
    flat = list(settings.get(key, []) or [])
    return [Vector(flat[i:i + 3]) for i in range(0, len(flat) - 2, 3)]


class CONVEYOR_GGT_stands(bpy.types.GizmoGroup):
    bl_idname = "CONVEYOR_GGT_stands"
    bl_label = "Conveyor Stands"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'PERSISTENT', 'SCALE'}

    @classmethod
    def poll(cls, context):
        try:
            return bool(context.scene.conveyor_settings.edit_stands) and _line(context) is not None
        except Exception:
            return False

    def setup(self, context):
        self.removers, self.restorers, self.adders = [], [], []
        self.refresh(context)

    def _grow(self, pool, glyph: bytes, op: str, wanted: int, size: float = 11.0, alpha: float = 0.9) -> None:
        while len(pool) < wanted:
            gz = self.gizmos.new("GIZMO_GT_button_2d")
            gz.shape = glyph  # Blender draws it in dark ink on a light disc, white on a dark one (ui/theme.style_buttons)
            gz.draw_options = {'BACKDROP', 'OUTLINE'}
            gz.show_drag = False
            gz.alpha = alpha
            gz.alpha_highlight = 1.0
            gz.scale_basis = size
            gz.hide = True
            pool.append((gz, gz.target_set_operator(op)))

    def refresh(self, context):
        """One button per stand, per stand taken out and per gap of the active line (the pools grow, never shrink)."""
        obj = _line(context)
        settings = obj.conveyor_line if obj is not None else None

        def wanted(key, least):
            return max(least, len(settings.get(key, []) or [])) if settings is not None else least

        self._grow(self.removers, GLYPH_MINUS, "conveyor.stand_remove", wanted("stand_arcs", POOL))
        self._grow(self.restorers, GLYPH_PLUS, "conveyor.stand_restore", wanted("stand_removed_arcs", POOL // 4))
        self._grow(self.adders, GLYPH_PLUS, "conveyor.stand_add", wanted("stand_gap_arcs", POOL), size=8.5, alpha=0.6)  # quieter: between the stands

    def draw_prepare(self, context):
        from .theme import style_buttons

        pal = style_buttons(self, context, "red")
        put_back, add = contrast.accent("green", pal["light"]), contrast.accent("blue", pal["light"])
        for gz, _props in self.restorers:
            gz.color_highlight = put_back
        for gz, _props in self.adders:
            gz.color_highlight = add
        obj = _line(context)
        region, rv3d = context.region, context.region_data
        if obj is None or region is None or rv3d is None:
            for gz, _props in self.removers + self.restorers + self.adders:
                gz.hide = True
            return
        settings = obj.conveyor_line
        up = Vector((0.0, 0.0, RISE_M if settings.support_mount == 'CEILING' else -DROP_M))
        M = obj.matrix_world
        stands = list(zip(_points(settings, "stand_points"), list(settings.get("stand_arcs", []) or [])))
        refs = list(settings.get("stand_removed_refs", []) or [])
        out = list(zip(_points(settings, "stand_removed_points"), [refs[i:i + 2] for i in range(0, len(refs) - 1, 2)]))
        gaps = list(zip(_points(settings, "stand_gap_points"), list(settings.get("stand_gap_arcs", []) or [])))
        for pool, items in ((self.removers, stands), (self.restorers, out), (self.adders, gaps)):
            for k, (gz, props) in enumerate(pool):
                xy = location_3d_to_region_2d(region, rv3d, M @ (items[k][0] + up)) if k < len(items) else None
                if xy is None:
                    gz.hide = True
                    continue
                gz.hide = False
                gz.matrix_basis = Matrix.Translation((xy.x, xy.y, 0.0))
                props.line = obj.name
                if pool is not self.restorers:
                    props.arc = float(items[k][1])
                else:
                    props.piece, props.index = int(items[k][1][0]), int(items[k][1][1])


classes = (CONVEYOR_GGT_stands,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
