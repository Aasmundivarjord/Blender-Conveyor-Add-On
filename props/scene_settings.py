"""Scene-level conveyor settings. Every change rebuilds all lines at once
(no separate Rebuild step), so what the panel shows is what the viewport
shows."""
import bpy


def _rebuild_all(self, context):
    from ..operators.build_line import all_lines, build_line

    for obj in all_lines(context.scene):
        build_line(context, obj)


TIME_SCALE_KEY = "wh_time_scale"  # shared with the Racks add-on: operation seconds per scene second (1 = real time)


def time_scale(scene) -> float:
    """The scene's clock: how many operation seconds pass per scene
    second. Goods, belts and rollers move Speed x this on screen; the
    Speed field and every rate stay real (one clock for both add-ons,
    agreed 2026-10-11: a crane running 3-4x and a real-time stream showed
    150-200 pallets per scene hour against the rack's 50)."""
    try:
        value = float(scene.get(TIME_SCALE_KEY, 1.0))
    except Exception:
        value = 1.0
    return value if value > 0.0 else 1.0


def _get_time_scale(self):
    return time_scale(self.id_data)


def _set_time_scale(self, value):
    self.id_data[TIME_SCALE_KEY] = float(max(value, 0.01))


def _on_time_scale(self, context):
    from ..operators.build_line import push_time_scale

    push_time_scale(context, self.id_data)


class CONVEYOR_SceneSettings(bpy.types.PropertyGroup):
    lod_override: bpy.props.EnumProperty(
        name="Detail",
        description="Level of detail for EVERY line in the scene. 'Per Line' uses each line's own High Detail switch",
        items=[
            ('PER_LINE', "Per Line", "Each line uses its own High Detail switch (Conveyor Builder panel)"),
            ('LOW', "All Low", "Fast preview: 12-sided rollers and coarse pitch on every line, whatever the line says"),
            ('HIGH', "All High", "Render quality on every line, whatever the line says"),
        ],
        default='PER_LINE',
        update=_rebuild_all,
    )
    time_scale: bpy.props.FloatProperty(
        name="Time scale", description="Operation seconds per scene second: goods, belts and rollers move this much faster on screen; "
                                       "speeds and rates stay real. Shared with the Racks add-on (its crane runs on the same clock)",
        default=1.0, min=0.01, soft_max=10.0, precision=2, get=_get_time_scale, set=_set_time_scale, update=_on_time_scale,
    )
    dock_distance_m: bpy.props.FloatProperty(
        name="Dock Distance",
        description="A line docks onto another line when its end points at it from closer than this",
        default=0.6,
        min=0.1,
        soft_max=2.0,
        subtype='DISTANCE',
    )
    floors_marked_only: bpy.props.BoolProperty(
        name="Marked Only",
        description="Legs and columns land only on objects marked as floors (wh_floor: Floorplan's slabs, Racks' walkway "
                    "decks, your own Mark as floor), not on any other mesh below them. A Floors collection overrides it",
        default=False, update=_rebuild_all,
    )
    floor_collection: bpy.props.PointerProperty(
        type=bpy.types.Collection, name="Floors",
        description="Mezzanine decks and other floors: legs and columns land on the first surface of this collection below them",
        update=_rebuild_all,
    )
    edit_stands: bpy.props.BoolProperty(
        name="Edit Stands",
        description="Show a button on every stand of the active line: click to take a stand out (a walkway, a machine under "
                    "the line), click a removed one to put it back",
        default=False, update=lambda self, context: _redraw_views(context),
    )
    ceiling_z: bpy.props.FloatProperty(
        name="Ceiling Level",
        description="World height of the ceiling that lines hung from the ceiling reach where no building publishes a clear "
                    "height (Floorplan's Building does) and no surface is found above them",
        default=6.0, subtype='DISTANCE', unit='LENGTH', update=_rebuild_all,
    )
    floor_z: bpy.props.FloatProperty(
        name="Floor Level", description="World height of the ground floor (used where no Floors surface is below a leg)",
        default=0.0, subtype='DISTANCE', unit='LENGTH', update=_rebuild_all,
    )
    show_spine: bpy.props.BoolProperty(
        name="Show Spine",
        description="Draw the analytic centerline as a curve on top of the geometry (debug)",
        default=False,
        update=_rebuild_all,
    )
    show_flow_markers: bpy.props.BoolProperty(
        name="Flow",
        description="Where every line's goods come in and go out: a disc, a join bar and an arrow at each end, drawn like the "
                    "Racks add-on's delivery points, with a button for the line's direction, throughput and speed. Solid and "
                    "Wireframe shading, while a line is selected",
        default=True,
        update=lambda self, context: _redraw_views(context),
    )
    show_dimensions: bpy.props.BoolProperty(
        name="Dimensions",
        description="The drawing layer: every piece's length, angle or height on the active line (click one to set it) and the "
                    "tags on the lines docked with it. Shows in Solid and Wireframe shading only; off hides it all, like a CAD layer",
        default=True,
        update=lambda self, context: _redraw_views(context),
    )


def _redraw_views(context) -> None:
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


classes = (CONVEYOR_SceneSettings,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.conveyor_settings = bpy.props.PointerProperty(type=CONVEYOR_SceneSettings)


def unregister():
    del bpy.types.Scene.conveyor_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
