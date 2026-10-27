"""Dataclasses for conveyor catalog data. Mirrors config/presets/*.json 1:1.

All dimensional fields are millimeters -- the single canonical unit --
regardless of the scene's display unit system. Conversion happens in
config.units, never here. Edit the JSON to correct/extend the catalog.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class WidthPreset:
    id: str
    label: str
    width_mm: float
    system: str  # "ISO" or "CEMA"


@dataclass(frozen=True)
class RollerSpec:
    duty_class: str  # "light", "standard", "mdr"
    diameter_mm: float
    pitch_mm: float
    source: str
    verified: bool
    note: str = ""


@dataclass(frozen=True)
class InclineLimit:
    conveyor_type: str
    max_angle_deg: float
    note: str
    verified: bool


@dataclass(frozen=True)
class TechnologySpec:
    """A merge / divert technology (config/presets/technologies.json):
    where it may be used and its typical rate."""

    id: str
    label: str
    angles: tuple
    roles: tuple
    rate_per_h: Optional[float]
    note: str = ""


@dataclass(frozen=True)
class ConveyorTypeSpec:
    id: str
    label: str
    category: str
    cross_section: str  # key into the geonodes cross-section builder registry
    default_duty_class: Optional[str]
    width_groups: tuple[str, ...]
    supports_continuous_curve: bool
    min_bend_radius_mm: Optional[float]
    angle_snap_deg: Optional[float]
    notes: str = ""
    # Rules of thumb: typical speed window (m/s) and practical rate per line (units/h).
    speed_m_s: tuple = (0.0, 0.0)
    rate_per_h: Optional[float] = None
    hidden: bool = False  # not offered (type list, gallery, presets); lines saved with it still build


@dataclass(frozen=True)
class CurveRadiusPreset:
    id: str
    label: str
    radius_mm: float
    system: str


@dataclass(frozen=True)
class ModuleSpec:
    id: str  # "RAT", "MERGE", "DIVERTER"
    label: str
    length_mm: float
    allows_exit: bool
    note: str = ""


@dataclass(frozen=True)
class SegmentCatalog:
    straight_min_mm: float
    straight_max_mm: float
    straight_increment_mm: float
    straight_default_mm: float
    curve_angles_deg: tuple[int, ...]
    curve_default_angle_deg: int
    curve_radii: tuple[CurveRadiusPreset, ...]
    curve_default_radius_id: str
    incline_angles_deg: tuple[int, ...]
    incline_default_angle_deg: int
    incline_default_length_mm: float
    nose_over_radius_mm: dict[str, float]  # keyed by cross-section id, plus "default"
    modules: dict[str, ModuleSpec]
    junction_snap_tolerance_mm: float

    def nose_over_radius_for(self, cross_section: str) -> float:
        return self.nose_over_radius_mm.get(cross_section, self.nose_over_radius_mm["default"])

    def curve_radius_by_id(self, radius_id: str) -> Optional[CurveRadiusPreset]:
        for r in self.curve_radii:
            if r.id == radius_id:
                return r
        return None
