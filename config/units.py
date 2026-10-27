"""Unit conversion and display formatting.

All dimensional data is stored in millimeters (config.specs, the segment
PropertyGroups). This module is the only place that converts mm to/from
Blender units or to a display string -- nothing else formats a length.
"""
from __future__ import annotations

import bpy

from .. import ADDON_PACKAGE

MM_PER_INCH = 25.4
MM_PER_M = 1000.0


def _get_addon_preferences():
    addon = bpy.context.preferences.addons.get(ADDON_PACKAGE)
    return addon.preferences if addon else None


def get_display_unit_system(scene: bpy.types.Scene) -> str:
    """'METRIC' or 'IMPERIAL'. The addon preference override wins over the
    scene's own unit settings."""
    prefs = _get_addon_preferences()
    if prefs is not None and prefs.unit_override != 'AUTO':
        return prefs.unit_override
    return scene.unit_settings.system if scene.unit_settings.system != 'NONE' else 'METRIC'


def mm_to_bu(mm: float, scene: bpy.types.Scene) -> float:
    """Millimeters to Blender units (a Blender unit is
    `scene.unit_settings.scale_length` meters)."""
    return (mm / MM_PER_M) / scene.unit_settings.scale_length


def bu_to_mm(value: float, scene: bpy.types.Scene) -> float:
    return value * scene.unit_settings.scale_length * MM_PER_M


def format_length_mm(mm: float, scene: bpy.types.Scene) -> str:
    system = get_display_unit_system(scene)
    if system == 'IMPERIAL':
        inches = mm / MM_PER_INCH
        if inches >= 12.0:
            return f"{inches / 12.0:.2f} ft"
        return f"{inches:.2f} in"
    if mm >= 1000.0:
        return f"{mm / 1000.0:.2f} m"
    return f"{mm:.0f} mm"
