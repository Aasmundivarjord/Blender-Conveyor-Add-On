"""Checks over the scene (R13): every line whose goods cross an obstacle of
a building, listed in a popup from the Scene section."""
from __future__ import annotations

import bpy


class CONVEYOR_OT_checks(bpy.types.Operator):
    bl_idname = "conveyor.checks"
    bl_label = "Checks"
    bl_description = "Lines whose goods cross a wall, column or other obstacle"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=320)

    def draw(self, context):
        from . import obstacles

        layout = self.layout
        checks = obstacles.scene_checks(context)
        if not checks:
            layout.label(text="No obstacle crossings", icon='CHECKMARK')
            return
        layout.label(text=f"{len(checks)} obstacle crossing{'s' if len(checks) != 1 else ''}", icon='ERROR')
        col = layout.column(align=True)
        for line, hit in checks[:12]:
            row = col.row()
            row.alert = True
            row.label(text=f"{line.name}: {obstacles.describe(hit)}")

    def execute(self, context):
        return {'FINISHED'}


classes = (CONVEYOR_OT_checks,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
