"""The N sidebar opens on the Conveyor tab whenever a conveyor line becomes
the active object (user, 2026-10-10: "the plugin pops up on the N menu when
you select a conveyor"). A message-bus subscription on the view layer's
active object; re-subscribed after a file load (the bus is cleared then)."""
from __future__ import annotations

import bpy

CATEGORY = "Conveyor"  # ui/panels.py bl_category
_OWNER = object()


def _is_line(obj) -> bool:
    return obj is not None and obj.type == 'CURVES' and bool(obj.conveyor_line.is_conveyor_line)


def show_conveyor_tab(context=None) -> bool:
    """Opens the sidebar of every 3D view on the window on the Conveyor
    tab. Returns True when something changed."""
    context = context or bpy.context
    screen = context.screen
    if screen is None:
        return False
    changed = False
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        space = area.spaces.active
        if space is None:
            continue
        if not space.show_region_ui:
            space.show_region_ui = True
            changed = True
        for region in area.regions:
            if region.type != 'UI':
                continue
            try:
                if region.active_panel_category != CATEGORY:
                    region.active_panel_category = CATEGORY
                    changed = True
            except (AttributeError, TypeError):  # older Blender: no category API
                pass
        if changed:
            area.tag_redraw()
    return changed


def _second_pass():
    """A sidebar that was hidden gets its tabs on its first redraw: the
    category set before that is lost, so set it once more just after."""
    try:
        show_conveyor_tab()
    except Exception:
        pass
    return None


def _on_active_changed():
    try:
        obj = bpy.context.view_layer.objects.active
    except Exception:
        return
    if _is_line(obj):
        show_conveyor_tab()
        bpy.app.timers.register(_second_pass, first_interval=0.15)


def _subscribe():
    try:
        bpy.msgbus.clear_by_owner(_OWNER)
        bpy.msgbus.subscribe_rna(key=(bpy.types.LayerObjects, "active"), owner=_OWNER, args=(), notify=_on_active_changed,
                                 options={'PERSISTENT'})
    except Exception:
        pass
    return None  # a timer callback: never again


@bpy.app.handlers.persistent
def _on_load(_path=None):
    _subscribe()


def register():
    bpy.app.timers.register(_subscribe, first_interval=0.2)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    try:
        bpy.msgbus.clear_by_owner(_OWNER)
    except Exception:
        pass
