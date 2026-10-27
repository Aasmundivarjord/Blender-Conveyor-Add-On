"""Loads the JSON catalog in config/presets/ into config.specs dataclasses.

Parsed once per Blender session and cached at module level. To correct or
extend the catalog, edit the JSON -- nothing here should need to change.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .specs import (
    ConveyorTypeSpec,
    CurveRadiusPreset,
    InclineLimit,
    ModuleSpec,
    RollerSpec,
    SegmentCatalog,
    WidthPreset,
)

_PRESETS_DIR = Path(__file__).parent / "presets"

_conveyor_types: Optional[dict[str, ConveyorTypeSpec]] = None
_width_groups: Optional[dict[str, list[WidthPreset]]] = None
_roller_duty_classes: Optional[dict[str, RollerSpec]] = None
_incline_limits: Optional[dict[str, InclineLimit]] = None
_segment_catalog: Optional[SegmentCatalog] = None


def _read_json(name: str) -> dict:
    with open(_PRESETS_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def get_conveyor_types() -> dict[str, ConveyorTypeSpec]:
    global _conveyor_types
    if _conveyor_types is None:
        data = _read_json("conveyor_types.json")
        _conveyor_types = {
            t["id"]: ConveyorTypeSpec(
                id=t["id"],
                label=t["label"],
                category=t["category"],
                cross_section=t["cross_section"],
                default_duty_class=t.get("default_duty_class"),
                width_groups=tuple(t.get("width_groups", [])),
                supports_continuous_curve=t["supports_continuous_curve"],
                min_bend_radius_mm=t.get("min_bend_radius_mm"),
                angle_snap_deg=t.get("angle_snap_deg"),
                notes=t.get("notes", ""),
                speed_m_s=tuple(t.get("speed_m_s", (0.0, 0.0))),
                rate_per_h=t.get("rate_per_h"),
                hidden=bool(t.get("hidden", False)),
            )
            for t in data["types"]
        }
    return _conveyor_types


def get_line_types() -> dict[str, ConveyorTypeSpec]:
    """Types a whole line can be (swept cross-sections). Modules are
    segments inside a line, not line types."""
    return {k: v for k, v in get_conveyor_types().items() if not v.cross_section.startswith("module_")}


def get_offered_types(current: str = "") -> dict[str, ConveyorTypeSpec]:
    """The line types the panel, the type gallery and the presets offer: all
    but the hidden ones (the omni-wheel deck until its redesign, 2.26.1),
    and `current` even when hidden (a line saved with it shows its type)."""
    return {k: v for k, v in get_line_types().items() if not v.hidden or k == current}


def get_width_presets() -> dict[str, list[WidthPreset]]:
    global _width_groups
    if _width_groups is None:
        data = _read_json("conveyor_widths.json")
        _width_groups = {
            group_id: [
                WidthPreset(id=w["id"], label=w["label"], width_mm=w["width_mm"], system=group["system"])
                for w in group["widths"]
            ]
            for group_id, group in data["groups"].items()
        }
    return _width_groups


def get_width_preset_by_id(width_id: str) -> Optional[WidthPreset]:
    for group in get_width_presets().values():
        for width in group:
            if width.id == width_id:
                return width
    return None


def get_roller_duty_classes() -> dict[str, RollerSpec]:
    global _roller_duty_classes
    if _roller_duty_classes is None:
        data = _read_json("roller_specs.json")
        _roller_duty_classes = {
            duty_class: RollerSpec(
                duty_class=duty_class,
                diameter_mm=spec["diameter_mm"],
                pitch_mm=spec["pitch_mm"],
                source=spec["source"],
                verified=spec["verified"],
                note=spec.get("note", ""),
            )
            for duty_class, spec in data["duty_classes"].items()
        }
    return _roller_duty_classes


_technologies: Optional[dict] = None
_inline_modules: Optional[dict] = None


def get_technologies() -> dict:
    """Junction technologies (id -> TechnologySpec)."""
    global _technologies
    if _technologies is None:
        from .specs import TechnologySpec

        d = _read_json("technologies.json")
        _technologies = {
            tid: TechnologySpec(id=tid, label=t["label"], angles=tuple(t["angles"]), roles=tuple(t["roles"]),
                                rate_per_h=t.get("rate_per_h"), note=t.get("note", ""))
            for tid, t in d["junction_technologies"].items()
        }
    return _technologies


def get_inline_module_info() -> dict:
    """Rate notes for inline modules (angled-roller element, fixed pivot, ...)."""
    global _inline_modules
    if _inline_modules is None:
        _inline_modules = _read_json("technologies.json").get("inline_modules", {})
    return _inline_modules


def get_incline_rules() -> dict:
    return _read_json("segments.json")["incline"].get("rules_of_thumb", {})


INCLINE_LIMIT_KEYS = {'belt': 'belt_smooth'}  # conveyor type -> incline_limits.json entry


def incline_limit_deg(conveyor_type: str) -> Optional[float]:
    """The steepest a type may climb (incline_limits.json); 0 = it cannot
    climb; None = no limit known (a pouch sorter's rail)."""
    limit = get_incline_limits().get(INCLINE_LIMIT_KEYS.get(conveyor_type, conveyor_type))
    return None if limit is None else float(limit.max_angle_deg)


def get_incline_limits() -> dict[str, InclineLimit]:
    global _incline_limits
    if _incline_limits is None:
        data = _read_json("incline_limits.json")
        _incline_limits = {
            limit["conveyor_type"]: InclineLimit(
                conveyor_type=limit["conveyor_type"],
                max_angle_deg=limit["max_angle_deg"],
                note=limit["note"],
                verified=limit["verified"],
            )
            for limit in data["limits"]
        }
    return _incline_limits


def get_segment_catalog() -> SegmentCatalog:
    global _segment_catalog
    if _segment_catalog is None:
        d = _read_json("segments.json")
        st, cu, inc = d["straight"], d["curve"], d["incline"]
        _segment_catalog = SegmentCatalog(
            straight_min_mm=st["min_mm"],
            straight_max_mm=st["max_mm"],
            straight_increment_mm=st["increment_mm"],
            straight_default_mm=st["default_mm"],
            curve_angles_deg=tuple(int(a) for a in cu["angles_deg"]),
            curve_default_angle_deg=int(cu["default_angle_deg"]),
            curve_radii=tuple(
                CurveRadiusPreset(id=r["id"], label=r["label"], radius_mm=r["radius_mm"], system=r["system"])
                for r in cu["inside_radii"]
            ),
            curve_default_radius_id=cu["default_radius_id"],
            incline_angles_deg=tuple(int(a) for a in inc["angles_deg"]),
            incline_default_angle_deg=int(inc["default_angle_deg"]),
            incline_default_length_mm=inc["default_length_mm"],
            nose_over_radius_mm=dict(inc["nose_over_radius_mm"]),
            modules={
                mid: ModuleSpec(
                    id=mid,
                    label=m["label"],
                    length_mm=m["length_mm"],
                    allows_exit=m.get("allows_exit", False),
                    note=m.get("note", ""),
                )
                for mid, m in d["modules"].items()
            },
            junction_snap_tolerance_mm=d["junction_snap_tolerance_mm"],
        )
    return _segment_catalog
