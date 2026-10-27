"""Default PBR materials, shared per role: brushed/galvanized steel, black
rubber (belt), safety-yellow paint, neutral plastic. One material per role
across every line so the user can restyle everything at once by editing it.

The frame and the rollers are the two that cross add-ons (interop contract
v2.1, R9 + D4): they are the shared "WH" palette materials `conveyor_frame`
("WH Conveyor Frame") and `conveyor_rollers` ("WH Conveyor Rollers"), one
datablock with the Racks and Shuttle add-ons. Lookup: a material stamped
`wh_material` == id (whatever its name: a user's rename keeps it) -> else our
legacy "Conveyor - Steel (Galvanized)" / "Conveyor - Roller (Zinc)" (a file
from 2.10 or older), stamped and renamed to the WH name while its name is
still the legacy one, its edited values kept -> else created from the
palette's values (the same as ours were, so a Conveyor-only scene looks the
same). A stamped material is shared: it is never cleared or rebuilt here."""
from __future__ import annotations

import bpy

from .._wh import palette as wh_palette

MATERIAL_NAMES = {
    "steel": "Conveyor - Steel (Galvanized)",  # legacy name of the shared conveyor_frame (2.10 and older files)
    "rubber": "Conveyor - Rubber (Belt)",
    "paint": "Conveyor - Safety Yellow",
    "plastic": "Conveyor - Plastic (Neutral)",
    "roller": "Conveyor - Roller (Zinc)",  # legacy name of the shared conveyor_rollers
    "highlight": "Conveyor - Active Segment",
    "sensor": "Conveyor - Sensor (Black)",
}
WH_KEY = "wh_material"  # the palette id on a shared material datablock (contract v2.1 R9)
SHARED_ROLES = {"steel": "conveyor_frame", "roller": "conveyor_rollers"}


# Bump when a material's node setup changes. An existing material at the
# current version is left alone (user restyling survives); an older one is
# rebuilt.
MATERIAL_VERSION = 3
_VERSION_KEY = "conveyor_material_version"


# Material slots every line object carries, in this order. The node trees
# read their materials from these slots (through modifier inputs pushed by
# build_line), so colours are changed in Blender's own Material panel and
# duplicate / link behave like on any other object.
SLOT_ROLES = ("Frame", "Rollers", "Belt", "Modules", "Links")
SLOT_INPUTS = {"Frame": "Frame Material", "Rollers": "Roller Material", "Belt": "Belt Material",
               "Modules": "Module Material", "Links": "Link Material"}


def default_for_role(role: str) -> bpy.types.Material:
    return {"Frame": steel, "Rollers": roller, "Belt": rubber, "Modules": paint, "Links": plastic}[role]()


def ensure_slots(obj) -> list:
    """Makes sure the line's Curves data has one material slot per role
    (filled with the shared defaults where empty) and returns the slot
    materials in SLOT_ROLES order. Never overwrites a user's choice."""
    mats = obj.data.materials
    while len(mats) < len(SLOT_ROLES):
        mats.append(None)
    out = []
    for i, role in enumerate(SLOT_ROLES):
        default = default_for_role(role)  # built or refreshed (version, viewport display) on every pass
        if mats[i] is None:
            mats[i] = default
        out.append(mats[i])
    return out


_UNSET_DISPLAY = (0.8, 0.8, 0.8)  # Blender's default viewport colour: nobody chose it


def shared_material(palette_id: str):
    """The material stamped `wh_material` == palette_id, or None."""
    for mat in bpy.data.materials:
        try:
            if mat.get(WH_KEY) == palette_id:
                return mat
        except Exception:
            continue
    return None


def _shared(palette_id: str) -> bpy.types.Material:
    """R9 lookup: the stamped datablock > our legacy-named material, stamped and
    renamed while its name is unchanged (its values kept) > created from the palette."""
    spec = wh_palette.PALETTE[palette_id]
    mat = shared_material(palette_id)
    if mat is not None:
        return mat  # shared with Racks / Shuttle, or ours already stamped: never cleared, never rebuilt
    legacy_name = next((n for n, pid in wh_palette.LEGACY_NAMES.items() if pid == palette_id), None)
    mat = bpy.data.materials.get(legacy_name) if legacy_name else None
    if mat is not None:
        mat[WH_KEY] = palette_id
        if mat.name == legacy_name and bpy.data.materials.get(spec["name"]) is None:
            mat.name = spec["name"]
        if not mat.use_nodes or mat.node_tree is None or not mat.node_tree.nodes:
            mat.use_nodes = True
            mat.node_tree.nodes.clear()
            _principled(mat, spec["base_color"], roughness=spec["roughness"], metallic=spec["metallic"])
        mat[_VERSION_KEY] = MATERIAL_VERSION
        return mat
    mat = bpy.data.materials.new(spec["name"])
    mat.use_nodes = True
    mat.node_tree.nodes.clear()
    _principled(mat, spec["base_color"], roughness=spec["roughness"], metallic=spec["metallic"])
    viewport = spec.get("viewport_color") or wh_palette.viewport_color(spec["base_color"])
    mat.diffuse_color = (*tuple(viewport)[:3], 1.0)  # Solid mode: capped so steel never reads near-white on a light theme (_wh 0.3)
    mat[WH_KEY] = palette_id
    mat[_VERSION_KEY] = MATERIAL_VERSION
    return mat


def _get_or_create(name: str) -> tuple[bpy.types.Material, bool]:
    mat = bpy.data.materials.get(name)
    if mat is not None and mat.get(WH_KEY):
        return mat, False  # a shared WH material (another add-on's or ours): never cleared
    if mat is not None and mat.get(_VERSION_KEY) == MATERIAL_VERSION and mat.use_nodes:
        if tuple(round(c, 3) for c in mat.diffuse_color[:3]) == _UNSET_DISPLAY:
            # Older files: give the viewport display the node tree's base colour (a user's own choice is kept).
            bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf is not None:
                mat.diffuse_color = tuple(bsdf.inputs["Base Color"].default_value)
                mat.roughness = bsdf.inputs["Roughness"].default_value
                mat.metallic = bsdf.inputs["Metallic"].default_value
        return mat, False
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.node_tree.nodes.clear()
    mat[_VERSION_KEY] = MATERIAL_VERSION
    return mat, True


def _principled(mat: bpy.types.Material, base_color, roughness: float, metallic: float = 0.0):
    # Viewport display (Solid shading, Workbench renders, the library's
    # pictures) follows the rendered look, so modules read yellow and belts
    # black before anyone switches to Material Preview.
    mat.diffuse_color = (*base_color, 1.0)
    mat.roughness = roughness
    mat.metallic = metallic
    tree = mat.node_tree
    bsdf = tree.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    output = tree.nodes.new('ShaderNodeOutputMaterial')
    output.location = (300, 0)
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return bsdf


def cardboard_box() -> bpy.types.Material:
    """The shared WH Cardboard (the pouch line's stand-in box): one look with Racks' loads."""
    return _shared("cardboard")


def steel() -> bpy.types.Material:
    """The frame: the shared WH Conveyor Frame (palette values = the old galvanized steel)."""
    return _shared(SHARED_ROLES["steel"])


def roller() -> bpy.types.Material:
    """The rollers: the shared WH Conveyor Rollers (palette values = the old zinc roller)."""
    return _shared(SHARED_ROLES["roller"])


def rubber() -> bpy.types.Material:
    """Belt rubber. Its texture coordinate along the belt is the geometry
    attribute `belt_scroll` (= arc length - time * speed, stored by the belt
    tree), so this ONE shared material scrolls at every line's own speed --
    a per-object speed can't otherwise live in a shared material."""
    mat, fresh = _get_or_create(MATERIAL_NAMES["rubber"])
    if not fresh and max(mat.diffuse_color[:3]) > 0.3:
        # A light viewport colour on the belt rubber is a stale display
        # setting, never a restyle: Solid shading drew the pop-up belts
        # light grey and a RAT's slots read as grooves.
        mat.diffuse_color = (0.02, 0.02, 0.02, 1.0)
        mat.roughness = 0.7
        mat.metallic = 0.0
    if fresh:
        bsdf = _principled(mat, (0.02, 0.02, 0.02), roughness=0.7, metallic=0.0)
        tree = mat.node_tree
        attr = tree.nodes.new('ShaderNodeAttribute')
        attr.attribute_name = "belt_scroll"
        attr.location = (-900, -200)
        geo = tree.nodes.new('ShaderNodeNewGeometry')
        geo.location = (-900, -450)
        sep = tree.nodes.new('ShaderNodeSeparateXYZ')
        sep.location = (-700, -450)
        tree.links.new(geo.outputs["Position"], sep.inputs["Vector"])
        # Coordinate: scroll along the belt, raw world x+y across (fine grain only).
        coord = tree.nodes.new('ShaderNodeCombineXYZ')
        coord.location = (-500, -300)
        tree.links.new(attr.outputs["Fac"], coord.inputs["X"])
        tree.links.new(sep.outputs["Z"], coord.inputs["Y"])
        noise = tree.nodes.new('ShaderNodeTexNoise')
        noise.location = (-300, -200)
        noise.inputs["Scale"].default_value = 60.0
        noise.inputs["Detail"].default_value = 3.0
        tree.links.new(coord.outputs["Vector"], noise.inputs["Vector"])
        bump = tree.nodes.new('ShaderNodeBump')
        bump.location = (-100, -200)
        bump.inputs["Strength"].default_value = 0.12
        tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
        tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
        # Faint seam stripes every 2 m so the scroll is readable in motion.
        wave = tree.nodes.new('ShaderNodeTexWave')
        wave.location = (-300, 100)
        wave.inputs["Scale"].default_value = 0.5
        tree.links.new(coord.outputs["Vector"], wave.inputs["Vector"])
        ramp = tree.nodes.new('ShaderNodeMath')
        ramp.operation = 'MULTIPLY_ADD'
        ramp.location = (-100, 100)
        ramp.inputs[1].default_value = 0.02
        ramp.inputs[2].default_value = 0.015
        tree.links.new(wave.outputs["Fac"], ramp.inputs[0])
        mix = tree.nodes.new('ShaderNodeMix')
        mix.data_type = 'RGBA'
        mix.location = (100, 100)
        mix.inputs["Factor"].default_value = 1.0
        mix.inputs["A"].default_value = (0.02, 0.02, 0.02, 1.0)
        tree.links.new(ramp.outputs["Value"], mix.inputs["B"])
        tree.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    return mat


def paint() -> bpy.types.Material:
    mat, fresh = _get_or_create(MATERIAL_NAMES["paint"])
    if fresh:
        _principled(mat, (0.95, 0.72, 0.05), roughness=0.4, metallic=0.0)
    return mat


def highlight() -> bpy.types.Material:
    """Opaque Blender-selection orange for the active-segment rail sleeves
    (see cross_sections/common.build_highlight); `diffuse_color` makes it
    read in Solid shading too."""
    mat, fresh = _get_or_create(MATERIAL_NAMES["highlight"])
    if fresh:
        bsdf = _principled(mat, (1.0, 0.42, 0.02), roughness=0.5, metallic=0.0)
        bsdf.inputs["Emission Color"].default_value = (1.0, 0.42, 0.02, 1.0)
        bsdf.inputs["Emission Strength"].default_value = 0.3
        mat.diffuse_color = (1.0, 0.42, 0.02, 1.0)
    return mat


def sensor() -> bpy.types.Material:
    """Photo-eye housings (buffer zone sensors): matt black plastic."""
    mat, fresh = _get_or_create(MATERIAL_NAMES["sensor"])
    if fresh:
        _principled(mat, (0.012, 0.012, 0.014), roughness=0.45, metallic=0.0)
    return mat


def plastic() -> bpy.types.Material:
    mat, fresh = _get_or_create(MATERIAL_NAMES["plastic"])
    if fresh:
        _principled(mat, (0.6, 0.6, 0.62), roughness=0.3, metallic=0.0)
    return mat
