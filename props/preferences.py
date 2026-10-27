"""Add-on preferences."""
import bpy

from .. import ADDON_PACKAGE


class CONVEYOR_Preferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_PACKAGE

    unit_override: bpy.props.EnumProperty(
        name="Display Units",
        description="How lengths are shown in the Conveyor panels (values are always stored in mm)",
        items=[
            ('AUTO', "Follow Scene", "Use the scene's unit system"),
            ('METRIC', "Metric", "Always show mm / m"),
            ('IMPERIAL', "Imperial", "Always show in / ft"),
        ],
        default='AUTO',
    )

    def draw(self, context):
        self.layout.prop(self, "unit_override")


classes = (CONVEYOR_Preferences,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
