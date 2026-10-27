"""
The shared "WH" material palette (contract v2.1, R9; values from the Racks add-on). Only things that cross add-ons are here: loads and
conveyor frames and rollers. Equipment keeps its own add-on prefix (WR / SH / Conveyor - / WF).

Values are Principled BSDF inputs; base colour is LINEAR RGB, alpha 1, no emission. Each entry
also carries `viewport_color` (0.3.0): the Solid-mode colour to put in `Material.diffuse_color`,
capped so light materials read on a light theme. They apply only when a material is CREATED: a
legacy material that is found and stamped keeps the user's edited values.

Lookup order in every add-on: a material carrying `wh_material` == id -> a legacy material
(by its `wr_material_key`, see LEGACY_KEYS, or by name, LEGACY_NAMES) which is then stamped
with `wh_material` (and renamed to the WH name only while its name is unchanged) -> create.
"""

PALETTE = {
    "pallet_wood": {"name": "WH Pallet Wood", "base_color": (0.36, 0.22, 0.09), "roughness": 0.80, "metallic": 0.0},
    "pallet_plastic": {"name": "WH Plastic Pallet", "base_color": (0.005, 0.06, 0.45), "roughness": 0.45, "metallic": 0.0},
    "cardboard": {"name": "WH Cardboard", "base_color": (0.42, 0.24, 0.10), "roughness": 0.88, "metallic": 0.0},
    "packing_tape": {"name": "WH Packing Tape", "base_color": (0.45, 0.30, 0.13), "roughness": 0.25, "metallic": 0.0},
    "shipping_label": {"name": "WH Shipping Label", "base_color": (0.85, 0.85, 0.83), "roughness": 0.60, "metallic": 0.0},
    "tote_plastic": {"name": "WH Tote Plastic", "base_color": (0.01, 0.04, 0.33), "roughness": 0.42, "metallic": 0.0},
    "conveyor_frame": {"name": "WH Conveyor Frame", "base_color": (0.55, 0.56, 0.58), "roughness": 0.38, "metallic": 0.9},
    "conveyor_rollers": {"name": "WH Conveyor Rollers", "base_color": (0.72, 0.73, 0.74), "roughness": 0.25, "metallic": 1.0},
}

# Solid-mode colour (Material.diffuse_color, "Viewport Display"): a light neutral material is
# shown darker in the viewport only, so it reads on a light theme (about 0.95 background); the
# render keeps base_color. Cap = linear luminance 0.40 (Racks 0.22.0 uses the same for its own).
VIEWPORT_LUMINANCE_CAP = 0.40


def viewport_color(base_color, cap=VIEWPORT_LUMINANCE_CAP):
    """The viewport display colour for a LINEAR base colour: unchanged when its luminance is at
    most `cap`, else scaled down to it (hue kept)."""
    r, g, b = (float(v) for v in tuple(base_color)[:3])
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    if lum <= cap or lum <= 0.0:
        return (r, g, b)
    k = cap / lum
    return (r * k, g * k, b * k)


for _m in PALETTE.values():
    _m["viewport_color"] = tuple(round(v, 4) for v in viewport_color(_m["base_color"]))

# Racks / Shuttle `wr_material_key` -> palette id (Shuttle's `conveyor`, "WR Conveyor Grey",
# maps to conveyor_frame too: that was the collision R9 fixes)
LEGACY_KEYS = {
    "wood": "pallet_wood", "plastic_pallet": "pallet_plastic", "cardboard": "cardboard",
    "tape": "packing_tape", "label": "shipping_label", "tote": "tote_plastic",
    "conveyor": "conveyor_frame", "conveyor_roller": "conveyor_rollers",
}

# Materials that carry no key, matched by exact name (the Conveyor add-on's own)
LEGACY_NAMES = {
    "Conveyor - Steel (Galvanized)": "conveyor_frame",
    "Conveyor - Roller (Zinc)": "conveyor_rollers",
}


def palette_id_for_legacy(key=None, name=None):
    """The palette id a legacy material belongs to, or None."""
    if key and key in LEGACY_KEYS:
        return LEGACY_KEYS[key]
    if name and name in LEGACY_NAMES:
        return LEGACY_NAMES[name]
    return None
