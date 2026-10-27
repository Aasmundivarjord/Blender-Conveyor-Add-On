"""
(warehouse_common) Lifted from the Racks add-on, commit 454613d (warehouse_racks/loads/long_catalogue.py), contract R19,
with only the import changed, and checked equal to Racks' module.
"""
"""
The `long` load kind (contract R19): bundles and packs of long goods
on cantilever racks -- steel tube, hollow-section and profile bundles, timber packs, sheet packs -- as
DATA, their canonical load ids and their `wh_load` records. Pure (no bpy).

Written in the Racks add-on first, shaped like warehouse_common `loads` (R20), and lifted into
warehouse_common 0.5.0; Racks keeps only the mesh building. Values are typical catalogue dimensions
of steel sections, timber and sheet packs.

Id (one canonical form per load):

    long:<std>:<material>:<section>:<length>[:<pack>]

- std: EU or NA; material: steel, stainless, alu, spruce, pine, spf, syp, plywood, mdf, osb.
- section: <form>-<size>, a key of SECTIONS[std] (EU sizes in mm, NA in inches, as with cartons).
- length: EU metres "%g" (6, 12, 4.8); NA feet with "ft" ("21ft", "16ft"). A metre length on NA or an
  ft length on EU is refused, so is any other spelling of the same number ("6.0").
- pack: hex<k> (hexagon, k pieces a side), g<a>x<b> (grid a wide x b high) or n<count>. The section's
  DEFAULT pack is left out of the id; the parser fills it in. A non-default pack keeps its part.

The record is the wh_load v1 base (kind "long", length along travel, forward_axis "X": the bundle
runs length-first on side-loaders and roller tables, as a pallet's X face does) plus optional
`pieces`, `bundle` ("hex" | "grid" | "nested" | "pack" | "sheets"), `bearer_height_m` (part of
height_m) and `mass_kg`. Readers may ignore the optional fields. Origin: bottom centre, bearers
included.
"""

import math
import re

from . import loads as wh_loads

MM = wh_loads.MM
INCH = wh_loads.INCH
FOOT = 12 * INCH
KIND = "long"
LENGTH_RANGE_M = (0.3, 24.0)

mm = wh_loads.mm
inch = wh_loads.inch

# kg/m3
DENSITY = {"steel": 7850.0, "stainless": 7900.0, "alu": 2700.0, "spruce": 470.0, "pine": 520.0, "spf": 480.0,
           "syp": 590.0, "plywood": 600.0, "mdf": 740.0, "osb": 620.0}
MATERIAL_NAMES = {"steel": "Steel", "stainless": "Stainless", "alu": "Aluminium", "spruce": "Spruce",
                  "pine": "Pine", "spf": "SPF", "syp": "SYP", "plywood": "Plywood", "mdf": "MDF", "osb": "OSB"}
METALS = ("steel", "stainless", "alu")
TIMBERS = ("spruce", "pine", "spf", "syp")
BOARDS = ("plywood", "mdf", "osb", "steel", "alu")
FORM_MATERIALS = {"pipe": METALS, "shs": METALS, "hss": METALS, "ipe": METALS, "angle": METALS,
                  "board": TIMBERS, "lumber": TIMBERS, "sheet": BOARDS}
# Which packs a form can take: hex (round sections), grid, n (sheets; nested profiles only at their default).
FORM_PACKS = {"pipe": ("hex", "g"), "shs": ("g",), "hss": ("g",), "ipe": ("g",), "angle": ("n",),
              "board": ("g",), "lumber": ("g",), "sheet": ("n",)}


class LongSection:
    """One cross-section of the catalogue. `cell` = (across, up) of one piece in a grid (a pipe:
    its OD both ways; an I-section: flange width x depth, webs vertical; timber: lying flat).
    `steel_kg_m` = mass per metre in steel (others scale by density); None: from the size."""
    __slots__ = ("key", "standard", "form", "label", "cell", "od", "wall", "pack", "bearer", "steel_kg_m",
                 "sheet_length", "nested")

    def __init__(self, key, standard, form, label, cell, pack, bearer=0.0, od=0.0, wall=0.0, steel_kg_m=None,
                 sheet_length=0.0, nested=None):
        self.key, self.standard, self.form, self.label = key, standard, form, label
        self.cell, self.pack, self.bearer = cell, pack, bearer
        self.od, self.wall, self.steel_kg_m = od, wall, steel_kg_m
        self.sheet_length, self.nested = sheet_length, nested


def _sections():
    eu = (
        # EN 10255 medium DN50, hexagonal bundle of 37 [long_loads 0.1, 8.3]
        LongSection("pipe-60.3x3.6", "EU", "pipe", "pipe 60.3x3.6", (mm(60.3), mm(60.3)), "hex4",
                    od=mm(60.3), wall=mm(3.6)),
        # EN 10219 SHS, 4 x 4 grid; 3379 kg for 16 x 12 m [long_loads 2]
        LongSection("shs-100x100x6", "EU", "shs", "SHS 100x100x6", (mm(100), mm(100)), "g4x4", steel_kg_m=17.6),
        # IPE 200, 22.4 kg/m, webs vertical 5 x 2 on 100 mm bearers [long_loads 2]
        LongSection("ipe-200", "EU", "ipe", "IPE 200", (mm(100), mm(200)), "g5x2", bearer=mm(100), steel_kg_m=22.4),
        # equal angle, nested layers of 4 / 3, 10 high: 210 x 275 mm [long_loads 2]
        LongSection("angle-50x50x5", "EU", "angle", "angle 50x50x5", (mm(50), mm(50)), "n35", steel_kg_m=3.77,
                    nested=(mm(210), mm(275))),
        # sawn spruce 47 x 150 lying flat, 7 wide x 21 high, on 75 mm bearers [long_loads 0.3]
        LongSection("board-47x150", "EU", "board", "board 47x150", (mm(150), mm(47)), "g7x21", bearer=mm(75)),
        # MDF 2440 x 1220 x 18, 50 sheets on 100 mm bearers [long_loads 0.4]
        LongSection("sheet-2440x1220x18", "EU", "sheet", "sheet 2440x1220x18", (mm(1220), mm(18)), "n50",
                    bearer=mm(100), sheet_length=mm(2440)),
    )
    na = (
        # 2 in Sch 40 (2.375 in OD, 0.154 in wall), hexagon of 37 [long_loads 0.1]
        LongSection("pipe-2in-s40", "NA", "pipe", "pipe 2 in Sch 40", (inch(2.375), inch(2.375)), "hex4",
                    od=inch(2.375), wall=inch(0.154)),
        # A500 HSS 4 x 4 x 1/4, 12.21 lb/ft, 4 x 4 grid [long_loads 2]
        LongSection("hss-4x4x0.25", "NA", "hss", "HSS 4x4x1/4", (inch(4), inch(4)), "g4x4", steel_kg_m=18.17),
        # 2x4 (1.5 x 3.5 in) lying flat, 14 wide x 21 high, 1.5 in attached dunnage [long_loads 0.3]
        LongSection("lumber-2x4", "NA", "lumber", "lumber 2x4", (inch(3.5), inch(1.5)), "g14x21", bearer=inch(1.5)),
        # 3/4 in plywood 48 x 96 in, 44 sheets on 3.5 in runners [long_loads 0.4]
        LongSection("sheet-48x96x0.75", "NA", "sheet", "sheet 48x96x3/4", (inch(48), inch(0.75)), "n44",
                    bearer=inch(3.5), sheet_length=inch(96)),
    )
    return {"EU": {s.key: s for s in eu}, "NA": {s.key: s for s in na}}


SECTIONS = _sections()

# The starting catalogue, default packs, canonical ids.
PRESETS = (
    "long:EU:steel:pipe-60.3x3.6:6",
    "long:EU:steel:shs-100x100x6:12",
    "long:EU:steel:ipe-200:12",
    "long:EU:steel:angle-50x50x5:6",
    "long:EU:spruce:board-47x150:4.8",
    "long:EU:mdf:sheet-2440x1220x18:2.44",
    "long:NA:steel:pipe-2in-s40:21ft",
    "long:NA:steel:hss-4x4x0.25:24ft",
    "long:NA:spf:lumber-2x4:16ft",
    "long:NA:plywood:sheet-48x96x0.75:8ft",
)

_PACK = re.compile(r"^(?:hex(?P<k>[1-9][0-9]*)|g(?P<a>[1-9][0-9]*)x(?P<b>[1-9][0-9]*)|n(?P<n>[1-9][0-9]*))$")
_NUMBER = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")


# ---------------------------------------------------------------------------
# Lengths and packs
# ---------------------------------------------------------------------------

def length_text(standard, length_m):
    """The canonical length part: EU metres "%g" (to the mm), NA feet "%gft" (to 1/1000 ft)."""
    if standard == "NA":
        return "%gft" % round(float(length_m) / FOOT, 3)
    return "%g" % round(float(length_m), 3)


def parse_length(standard, text):
    """Metres from a length part; ValueError for the other standard's form or a non-canonical spelling."""
    if standard == "NA":
        if not text.endswith("ft") or not _NUMBER.match(text[:-2]):
            raise ValueError("An NA long-load length is in feet, e.g. '21ft': %r" % (text,))
        value = float(text[:-2]) * FOOT
    else:
        if not _NUMBER.match(text):
            raise ValueError("An EU long-load length is in metres, e.g. '6': %r" % (text,))
        value = float(text)
    if length_text(standard, value) != text:
        raise ValueError("Not the canonical length %r (use %r)" % (text, length_text(standard, value)))
    lo, hi = LENGTH_RANGE_M
    if not lo <= value <= hi:
        raise ValueError("Long-load length %g m outside %g-%g m" % (value, lo, hi))
    return value


def parse_pack(section, text):
    """(kind, numbers) of a pack part for `section`: ("hex", (k,)), ("g", (a, b)) or ("n", (count,))."""
    m = _PACK.match(text or "")
    if not m:
        raise ValueError("Not a pack: %r" % (text,))
    if m.group("k"):
        kind, nums = "hex", (int(m.group("k")),)
    elif m.group("a"):
        kind, nums = "g", (int(m.group("a")), int(m.group("b")))
    else:
        kind, nums = "n", (int(m.group("n")),)
    if kind not in FORM_PACKS[section.form]:
        raise ValueError("A %s cannot be packed as %r" % (section.form, text))
    if section.nested is not None and text != section.pack:
        raise ValueError("Nested %s bundles come only as %r" % (section.form, section.pack))
    if kind == "hex" and not 2 <= nums[0] <= 9 or kind == "g" and max(nums) > 40 or kind == "n" and nums[0] > 500:
        raise ValueError("Pack %r out of range" % (text,))
    return kind, nums


# ---------------------------------------------------------------------------
# Ids
# ---------------------------------------------------------------------------

def section_of(standard, key):
    try:
        return SECTIONS[standard][key]
    except KeyError:
        raise ValueError("Not a long-load section: %r %r" % (standard, key)) from None


def long_load_id(standard, material, section, length_m, pack=None):
    """The canonical id: the default pack left out, the length in the standard's one form."""
    sec = section_of(standard, section)
    lid = "long:%s:%s:%s:%s" % (standard, material, section, length_text(standard, length_m))
    if pack not in (None, sec.pack):
        lid += ":" + pack
    parse_long_id(lid)                      # material, length, pack and sheet length all checked
    return lid


def parse_long_id(lid):
    """(standard, material, section key, length m, pack) of a canonical long id (pack filled in with
    the default when the id leaves it out); ValueError when malformed, unknown or not canonical."""
    parts = str(lid).split(":")
    if parts[0] != KIND or len(parts) not in (5, 6):
        raise ValueError("Not a long-load id: %r" % (lid,))
    _kind, std, material, key, length = parts[:5]
    if std not in SECTIONS:
        raise ValueError("Not a standard: %r" % (std,))
    sec = section_of(std, key)
    if material not in FORM_MATERIALS[sec.form]:
        raise ValueError("A %s does not come in %r" % (sec.form, material))
    value = parse_length(std, length)
    pack = parts[5] if len(parts) == 6 else sec.pack
    if len(parts) == 6 and pack == sec.pack:
        raise ValueError("The default pack is left out of the id: %r" % (lid,))
    parse_pack(sec, pack)
    if sec.sheet_length and abs(value - sec.sheet_length) > 0.002:
        raise ValueError("A %s pack is %s long" % (sec.label, length_text(std, sec.sheet_length)))
    return std, material, key, value, pack


def is_long(lid):
    return str(lid).startswith(KIND + ":")


# ---------------------------------------------------------------------------
# Sizes and records
# ---------------------------------------------------------------------------

def bundle_dims(std, material, key, length_m, pack):
    """dict(length, width, height, pieces, bundle, bearer, mass) of a bundle (metres, kg)."""
    sec = section_of(std, key)
    kind, nums = parse_pack(sec, pack)
    cw, ch = sec.cell
    if kind == "hex":
        k = nums[0]
        pieces = 3 * k * (k - 1) + 1
        width, height = (2 * k - 1) * sec.od, sec.od * (1.0 + math.sqrt(3.0) * (k - 1))
        bundle = "hex"
    elif kind == "g":
        a, b = nums
        pieces, width, height = a * b, a * cw, b * ch
        bundle = "pack" if sec.form in ("board", "lumber") else "grid"
    elif sec.nested is not None:
        pieces, (width, height), bundle = nums[0], sec.nested, "nested"
    else:                                                     # sheets
        pieces, width, height, bundle = nums[0], cw, nums[0] * ch, "sheets"
    length = sec.sheet_length or length_m
    density = DENSITY[material]
    if sec.form == "pipe":
        area = math.pi * sec.wall * (sec.od - sec.wall)        # m2 of steel in one tube
        mass = pieces * area * length * density
    elif sec.steel_kg_m is not None:
        mass = pieces * sec.steel_kg_m * length * density / DENSITY["steel"]
    else:                                                     # timber and sheets: solid pieces
        mass = pieces * cw * ch * length * density
    return {"length": length, "width": width, "height": height + sec.bearer, "pieces": pieces, "bundle": bundle,
            "bearer": sec.bearer, "mass": mass}


def name_of(lid):
    std, material, key, length_m, pack = parse_long_id(lid)
    sec = section_of(std, key)
    dims = bundle_dims(std, material, key, length_m, pack)
    unit = "%g ft" % round(dims["length"] / FOOT, 3) if std == "NA" else "%g m" % round(dims["length"], 3)
    return "%s %s, %d pcs, %s" % (MATERIAL_NAMES[material], sec.label, dims["pieces"], unit)


def long_load(lid, source=None):
    """The wh_load record of a long-load id (v1 base plus the optional long fields)."""
    std, material, key, length_m, pack = parse_long_id(lid)
    dims = bundle_dims(std, material, key, length_m, pack)
    name = name_of(lid)
    rec = {
        "version": wh_loads.LOAD_VERSION,
        "kind": KIND,
        "id": lid,
        "name": name,
        "standard": std,
        "length_m": round(float(dims["length"]), 4),
        "width_m": round(float(dims["width"]), 4),
        "height_m": round(float(dims["height"]), 4),
        "forward_axis": "X",
        "object": "WH Load " + name,
        "make": wh_loads.MAKE_LOAD_OP,
    }
    if source:
        rec["source"] = source
    rec["pieces"] = int(dims["pieces"])
    rec["bundle"] = dims["bundle"]
    rec["bearer_height_m"] = round(float(dims["bearer"]), 4)
    rec["mass_kg"] = round(float(dims["mass"]), 1)
    return rec


# ---------------------------------------------------------------------------
# warehouse_common `loads` entry points, extended with "long"
# ---------------------------------------------------------------------------

def parse_load_id(lid):
    """As warehouse_common loads.parse_load_id, plus "long": ("long", "<std>:<material>:<section>:
    <length>[:<pack>]", material, 0.0)."""
    if is_long(lid):
        parse_long_id(lid)
        return KIND, str(lid)[len(KIND) + 1:], str(lid).split(":")[2], 0.0
    return wh_loads.parse_load_id(lid)


def is_known(lid):
    try:
        parse_load_id(lid)
        return True
    except (ValueError, TypeError):
        return False


def object_name(lid):
    if is_long(lid):
        return "WH Load " + name_of(lid)
    return wh_loads.object_name(lid)


def load_from_id(lid, source=None):
    if is_long(lid):
        return long_load(lid, source)
    return wh_loads.load_from_id(lid, source)


def placeholder_size(lid):
    """(length along travel, width across, height) of a catalogue load, long loads included."""
    rec = load_from_id(lid)
    return rec["length_m"], rec["width_m"], rec["height_m"]
