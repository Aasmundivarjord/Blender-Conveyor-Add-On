"""The pouch sorter's figures (pocket sorter: Ferag Skyfall, Dürkopp Adler,
Knapp, TGW): an overhead rail with trolleys carrying hanging pouches, one
item per pouch, sorted by rail switches. The pouch is a flat bag whose
broad face stands across the rail -- its WIDTH (across) and HEIGHT (hanging
length) are what a sales drawing states, its DEPTH along the rail is the
thin side. Standard sizes with a custom option (user, 2026-10-11: "the bag
in x & y dimension, standard but controllable").

Pure Python, unit-tested."""
from __future__ import annotations

import math

# id, label, width mm, height mm. The 400 x 600 pouch is the common
# e-commerce size (shoe boxes, polybags, folded garments).
STANDARD_POUCHES = (
    ("STD_400_600", "400 × 600 mm (standard)", 400.0, 600.0),
    ("STD_300_450", "300 × 450 mm (small)", 300.0, 450.0),
    ("STD_500_700", "500 × 700 mm (large)", 500.0, 700.0),
)
CUSTOM = "CUSTOM"
DEFAULT_SIZE = STANDARD_POUCHES[0][0]
DEFAULT_DEPTH_MM = 120.0  # along the rail: the loaded pouch's thickness
DEFAULT_PITCH_MM = 250.0  # trolley pitch along the rail
MIN_GAP_MM = 30.0  # pouches never touch: pitch >= depth + this
RAIL_W_M, RAIL_H_M = 0.06, 0.08  # the overhead rail's section (pushed as Rail Thickness / Rail Height)
TROLLEY_H_M = 0.04  # the trolley body hanging under the rail
HOOK_M = 0.10  # trolley to the pouch's hanger bar
ITEM_LIFT_M = 0.04  # an item's bottom above the pouch's bottom
PORTAL_RISE_M = 0.25  # the portal beam above the rail top


def size_items() -> list:
    """(id, label, description) for the Pouch enum."""
    out = [(sid, label, f"Pouch {w:.0f} mm wide, {h:.0f} mm high") for sid, label, w, h in STANDARD_POUCHES]
    out.append((CUSTOM, "Custom…", "Enter the pouch width and height"))
    return out


def pouch_dims_mm(size_id: str, custom_w_mm: float, custom_h_mm: float, depth_mm: float) -> tuple[float, float, float]:
    """(width, height, depth) in mm of the pouch a line carries."""
    for sid, _label, w, h in STANDARD_POUCHES:
        if sid == size_id:
            return float(w), float(h), max(float(depth_mm), 10.0)
    return max(float(custom_w_mm), 50.0), max(float(custom_h_mm), 50.0), max(float(depth_mm), 10.0)


def pitch_mm(depth_mm: float, wanted_mm: float) -> float:
    """The trolley pitch: what the user set, never closer than the pouches' depth plus a gap."""
    return max(float(wanted_mm), float(depth_mm) + MIN_GAP_MM)


def quantize_m(spacing_m: float, pitch_m: float) -> float:
    """The goods' pitch on a pouch sorter: a whole number of pouch pitches
    (one item per pouch; a throughput below one per pouch leaves pouches empty)."""
    if pitch_m <= 0.0:
        return spacing_m
    return max(1, math.ceil(spacing_m / pitch_m - 1e-6)) * pitch_m


def item_drop_m(pouch_height_m: float) -> float:
    """Height Offset for the goods: from the rail top (the spine) down to the
    pouch's bottom plus ITEM_LIFT_M, so an item sits inside its pouch."""
    return -(RAIL_H_M + TROLLEY_H_M + HOOK_M + pouch_height_m) + ITEM_LIFT_M


def line_values(size_id: str, custom_w_mm: float, custom_h_mm: float, depth_mm: float, wanted_pitch_mm: float, mm_to_m) -> dict:
    """The pouch tree's inputs for a line (Blender units through `mm_to_m`)."""
    w, h, d = pouch_dims_mm(size_id, custom_w_mm, custom_h_mm, depth_mm)
    return {
        "Pouch Width": mm_to_m(w), "Pouch Height": mm_to_m(h), "Pouch Depth": mm_to_m(d),
        "Pouch Pitch": mm_to_m(pitch_mm(d, wanted_pitch_mm)),
        "Hook Length": HOOK_M, "Portal Rise": PORTAL_RISE_M,
        "Rail Thickness": RAIL_W_M, "Rail Height": RAIL_H_M, "Rail Top Drop": 0.0,
        "Guide Rails": False,
        "Height Offset": item_drop_m(mm_to_m(h)),
    }


# Stand-in goods for a pouch line without a picked item (user, 2026-10-13: "it
# looks like it's populating a cube object"): the general placeholders are a
# 600 mm tote and a 500 mm carton, which stuck out of a 120 mm deep pouch. Same
# number and NAME ORDER as operators/populate.PLACEHOLDER_ITEMS (Carton, Tote ->
# route class 0, 1), sized to fit the smallest standard pouch (300 x 450, 120
# deep). In the placeholders' convention: (name, across mm, along mm, height mm),
# X across the travel, Y along it; a pouch line turns goods across the rail
# (Item Yaw + 90 deg), so their Y lies across the pouch.
POUCH_ITEMS = (
    ("Pouch Item 1 Box 250x80", 80.0, 250.0, 170.0),  # a small carton (a shoe box)
    ("Pouch Item 2 Polybag 260x60", 60.0, 260.0, 300.0),  # a flat polybag (a folded garment)
)


def fits(item_mm, pouch_mm, margin_mm: float = 10.0) -> bool:
    """Does an item (two horizontal sides and a height, mm) go into a pouch
    (width, height, depth, mm)? Its longer side lies across the pouch, the
    shorter along the rail, and it must clear the bag by `margin_mm`."""
    short, long_ = sorted((float(item_mm[0]), float(item_mm[1])))
    width, height, depth = (float(v) for v in pouch_mm)
    return long_ <= width - margin_mm and short <= depth - margin_mm and float(item_mm[2]) <= height - margin_mm
