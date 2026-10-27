"""
The shared load catalogue (contract R20): pallets, totes and cartons as DATA, their load ids and
their `wh_load` records (contract v1/v2 "wh_load"). Lifted from the Racks add-on 0.23.0
(standards.py, interop.py), which stays the one add-on that BUILDS load meshes through
`warehouse.make_load`; every other add-on can now size a placeholder exactly from a load id even
when Racks is not installed. Dimensions in metres. A pallet stands as in a rack: `width` is the
fork-entry face (X), `depth` runs into the rack (Y).
"""

MM = 0.001
INCH = 0.0254
MAKE_LOAD_OP = "warehouse.make_load"
LOAD_VERSION = 1                       # wh_load records are contract v1 (unchanged by v2 / v2.1)


def mm(v):
    return v * MM


def inch(v):
    return v * INCH


class Pallet:
    __slots__ = ("id", "name", "standard", "width", "depth", "height", "plastic_height")

    def __init__(self, pid, name, standard, width, depth, height, plastic_height):
        self.id, self.name, self.standard = pid, name, standard
        self.width, self.depth, self.height, self.plastic_height = width, depth, height, plastic_height

    def height_for(self, material):
        return self.plastic_height if material == "Plastic" else self.height


class Tote:
    __slots__ = ("id", "name", "standard", "width", "depth", "height")

    def __init__(self, tid, name, standard, width, depth, height):
        self.id, self.name, self.standard = tid, name, standard
        self.width, self.depth, self.height = width, depth, height


PALLETS = {p.id: p for p in (
    Pallet("EUR1", "EUR1 1200x800", "EU", mm(800), mm(1200), mm(144), mm(160)),
    Pallet("EUR2", "EUR2 1200x1000", "EU", mm(1000), mm(1200), mm(144), mm(160)),
    Pallet("EUR6", "Half 800x600", "EU", mm(600), mm(800), mm(144), mm(150)),
    Pallet("GMA", "GMA 48x40", "NA", inch(40), inch(48), inch(5.5), inch(6)),
)}
PALLET_MATERIALS = ("Wood", "Plastic")

TOTES = {t.id: t for t in (
    Tote("EU_600_400_120", "EU 600x400x120", "EU", mm(400), mm(600), mm(120)),
    Tote("EU_600_400_220", "EU 600x400x220", "EU", mm(400), mm(600), mm(220)),
    Tote("EU_600_400_320", "EU 600x400x320", "EU", mm(400), mm(600), mm(320)),
    Tote("EU_600_400_420", "EU 600x400x420", "EU", mm(400), mm(600), mm(420)),
    Tote("EU_400_300_220", "EU 400x300x220", "EU", mm(300), mm(400), mm(220)),
    Tote("NA_24_16_9", "NA 24x16x9", "NA", inch(16), inch(24), inch(9)),
    Tote("NA_24_16_12", "NA 24x16x12", "NA", inch(16), inch(24), inch(12)),
)}

# Legacy carton sizes (length along travel, width across, height); "carton:EU:M" still resolves
CARTONS = {
    "EU": {"S": (mm(300), mm(200), mm(150)), "M": (mm(400), mm(300), mm(250)), "L": (mm(600), mm(400), mm(300))},
    "NA": {"S": (inch(12), inch(10), inch(6)), "M": (inch(16), inch(12), inch(10)), "L": (inch(24), inch(16), inch(12))},
}
# The modular carton catalogue: footprints that tile the pallet module, long side first
CARTON_MODULES = ("Default", "Half module", "Quarter module", "Eighth module", "Sixteenth module",
                  "Full module", "Industrial module")
CARTON_MODULE_DIMS = {
    "EU": (None, (mm(600), mm(400)), (mm(400), mm(300)), (mm(300), mm(200)), (mm(200), mm(150)),
           (mm(1200), mm(800)), (mm(1200), mm(1000))),
    "NA": (None, (inch(24), inch(20)), (inch(16), inch(12)), (inch(12), inch(10)), (inch(10), inch(8)),
           (inch(48), inch(40)), (inch(48), inch(48))),
}
CARTON_HEIGHTS = ("Low", "Medium", "High", "Custom")
CARTON_HEIGHT_VALUES = {"EU": (mm(150), mm(250), mm(350)), "NA": (inch(6), inch(10), inch(14))}
CARTON_DEFAULT_MODULE = 1              # "Default" = the half module


def carton_module_dims(standard, index):
    dims = CARTON_MODULE_DIMS[standard]
    return dims[max(0, min(int(index), len(dims) - 1))]


def carton_height(standard, index, custom=0.0):
    values = CARTON_HEIGHT_VALUES[standard]
    index = max(0, min(int(index), len(CARTON_HEIGHTS) - 1))
    if index >= len(values):
        return max(mm(20), float(custom))
    return values[index]


def carton_size_text(standard, along, across, height):
    """'600x400x250' (mm) or '24x20x10' (in): the size part of a catalogue carton's load id."""
    unit = MM if standard == "EU" else INCH
    return "x".join("%g" % round(v / unit, 1) for v in (along, across, height))


def carton_dims_from_text(standard, text):
    """(along, across, height) in metres from 'S' / 'M' / 'L' or '600x400x250'; ValueError otherwise."""
    if text in CARTONS[standard]:
        return CARTONS[standard][text]
    parts = text.split("x")
    if len(parts) != 3:
        raise ValueError("Not a carton size: %r" % (text,))
    unit = MM if standard == "EU" else INCH
    along, across, height = (float(v) * unit for v in parts)
    if min(along, across, height) <= 0.0:
        raise ValueError("Not a carton size: %r" % (text,))
    return along, across, height


# ---------------------------------------------------------------------------
# Load ids and wh_load records
# ---------------------------------------------------------------------------

def load_id(kind, spec_id, material="", load_height=0.0):
    """'tote:EU_600_400_220', 'carton:EU:M' / 'carton:EU:600x400x250', 'pallet:EUR1:Wood:1.2'
    (load height 0 = an empty pallet), 'custom:<object name>'."""
    if kind == "pallet":
        return "pallet:%s:%s:%g" % (spec_id, material or "Wood", round(load_height, 3))
    return "%s:%s" % (kind, spec_id)


def _is_long(lid):
    return str(lid).startswith("long:")


def parse_load_id(lid):
    """(kind, spec id, material, load height); ValueError when malformed or unknown. A "long"
    id (R19) is handled by longload: ("long", "<std>:<material>:<section>:<length>[:<pack>]",
    material, 0.0)."""
    if _is_long(lid):
        from . import longload
        return longload.parse_load_id(lid)
    parts = str(lid).split(":")
    if parts[0] == "tote" and len(parts) == 2 and parts[1] in TOTES:
        return "tote", parts[1], "", 0.0
    if parts[0] == "carton" and len(parts) == 3 and parts[1] in CARTONS:
        carton_dims_from_text(parts[1], parts[2])
        return "carton", "%s:%s" % (parts[1], parts[2]), "", 0.0
    if parts[0] == "custom" and len(parts) >= 2 and parts[1]:
        return "custom", ":".join(parts[1:]), "", 0.0
    if parts[0] == "pallet" and len(parts) == 4 and parts[1] in PALLETS and parts[2] in PALLET_MATERIALS:
        return "pallet", parts[1], parts[2], float(parts[3])
    raise ValueError("Not a load id: %r" % (lid,))


def canonical_load_id(lid):
    """The one spelling of a load id, so add-ons match ids alike (0.6.6): a pallet's
    height as %g ("pallet:EUR1:Plastic:1.0" -> ":1"), a carton size in whole/decimal mm or inches as
    carton_size_text writes it. Long ids are already strict (non-canonical spellings are refused);
    custom ids and anything that does not parse come back as given."""
    text = str(lid)
    try:
        kind, spec, material, height = parse_load_id(text)
    except (ValueError, TypeError):
        return text
    if kind == "pallet":
        return load_id("pallet", spec, material, height)
    if kind == "carton":
        std, size = spec.split(":", 1)
        if size not in CARTONS[std]:
            size = carton_size_text(std, *carton_dims_from_text(std, size))
        return "carton:%s:%s" % (std, size)
    return text


def same_load(a, b):
    """Are two load ids the same load? (canonical_load_id on both sides)"""
    return canonical_load_id(a) == canonical_load_id(b)


def is_known(lid):
    try:
        parse_load_id(lid)
        return True
    except (ValueError, TypeError):
        return False


def object_name(lid):
    """Name of the shared load object for a load id (one per file, made by warehouse.make_load)."""
    if _is_long(lid):
        from . import longload
        return longload.object_name(lid)
    kind, spec_id, material, height = parse_load_id(lid)
    if kind == "tote":
        return "WH Load " + TOTES[spec_id].name
    if kind == "carton":
        std, size = spec_id.split(":")
        return "WH Load Carton %s %s" % (std, size)
    if kind == "custom":
        return spec_id
    name = "WH Load " + PALLETS[spec_id].name + (" plastic" if material == "Plastic" else "")
    return name + (" %.2f m" % height if height > 0.0 else " empty")


def _base(kind, lid, name, standard, length, width, height, forward_axis, source):
    rec = {
        "version": LOAD_VERSION,
        "kind": kind,
        "id": lid,
        "name": name,
        "standard": standard,
        "length_m": round(float(length), 4),
        "width_m": round(float(width), 4),
        "height_m": round(float(height), 4),
        "forward_axis": forward_axis,
        "object": object_name(lid),
        "make": MAKE_LOAD_OP,
    }
    if source:
        rec["source"] = source
    return rec


def tote_load(tote_id, source=None):
    """A Euro container travels long side first."""
    t = TOTES[tote_id]
    return _base("tote", load_id("tote", t.id), t.name, t.standard, t.depth, t.width, t.height, "Y", source)


def carton_load(standard, size, source=None):
    """`size`: legacy 'S' / 'M' / 'L' or a catalogue size '600x400x250'."""
    length, width, height = carton_dims_from_text(standard, size)
    return _base("carton", load_id("carton", "%s:%s" % (standard, size)), "Carton %s %s" % (standard, size),
                 standard, length, width, height, "Y", source)


def catalogue_carton_load(standard, module_index, height_index, custom_height=0.0, source=None):
    index = module_index if carton_module_dims(standard, module_index) else CARTON_DEFAULT_MODULE
    along, across = carton_module_dims(standard, index)
    height = carton_height(standard, height_index, custom_height)
    return carton_load(standard, carton_size_text(standard, along, across, height), source)


def pallet_load(pallet_id, material="Wood", load_height=0.0, source=None):
    """A pallet runs as it stands in the rack: the fork-entry face (its width) along travel."""
    p = PALLETS[pallet_id]
    lid = load_id("pallet", p.id, material, load_height)
    height = max(load_height, p.height_for(material))
    name = p.name + (" plastic" if material == "Plastic" else "") + (" loaded" if load_height > 0.0 else " empty")
    rec = _base("pallet", lid, name, p.standard, p.width, p.depth, height, "X", source)
    rec["pallet_material"] = material
    return rec


def custom_load(object_name_, along, across, height, forward_axis="Y", standard="EU", source=None):
    """A user's own object used as it is (`make` None: readers never build it)."""
    rec = _base("custom", "custom:" + object_name_, object_name_, standard, along, across, height, forward_axis, source)
    rec["object"] = object_name_
    rec["make"] = None
    return rec


def load_from_id(lid, source=None):
    """The wh_load record of a catalogue load id (custom ids have no catalogue size)."""
    if _is_long(lid):
        from . import longload
        return longload.long_load(lid, source)
    kind, spec_id, material, height = parse_load_id(lid)
    if kind == "tote":
        return tote_load(spec_id, source)
    if kind == "carton":
        std, size = spec_id.split(":")
        return carton_load(std, size, source)
    if kind == "custom":
        raise ValueError("A custom load has no catalogue size: %r" % (lid,))
    return pallet_load(spec_id, material, height, source)


def placeholder_size(lid):
    """(length along travel, width across, height) of a catalogue load, for an add-on that
    draws a stand-in box when Racks is not there to build the real mesh."""
    rec = load_from_id(lid)
    return rec["length_m"], rec["width_m"], rec["height_m"]
