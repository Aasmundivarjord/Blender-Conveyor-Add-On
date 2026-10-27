"""Where a line hung from the ceiling hangs from (contract R17): its
level's ceiling -- the level's z plus `headroom_m` in the `wh_levels` of
Floorplan's Building or a mezzanine, by warehouse_common's
`levels.ceiling_at` (0.4.1: the level_at rule, then that level's headroom) --
else the Scene panel's Ceiling level. A surface above the line (a deck in the
Floors collection) still comes first, stand by stand, in the node tree
(geonodes/cross_sections/common.ceiling_above). The deferred pass keeps the
value current when the hall's clear height changes or a line moves into
another hall; it writes only what changed (R5)."""
from __future__ import annotations

import math

from .._wh import geometry as wh_geometry
from .._wh import levels as wh_levels

FROM_KEY = "ceiling_from"  # on the line settings: the level the ceiling comes from ("" = the Scene setting)
Z_KEY = "ceiling_z_m"  # on the line settings: the world z it hangs from (for the Line panel)


def scene_levels(scene) -> list:
    """Every `wh_levels` entry in world coordinates (levels_world keeps
    headroom_m and label since warehouse_common 0.4.1), each with its host's
    name for the Line panel."""
    from .ports import LEVELS_KEY, _json

    out = []
    for host in scene.objects:
        if LEVELS_KEY not in host:
            continue
        entries = _json(host.get(LEVELS_KEY), [])
        if not isinstance(entries, list):
            continue
        M = host.matrix_world
        loc = M.translation
        for level in wh_levels.levels_world(entries, (loc.x, loc.y, loc.z), math.degrees(M.to_euler().z)):
            level["host"] = host.name
            out.append(level)
    return out


def _host_of(point, hit: dict, levels: list) -> str:
    """The host of the level ceiling_at chose (two halls both have a level 0 at z 0)."""
    for lv in levels:
        if str(lv.get("id")) == str(hit["level"]) and abs(float(lv["z"]) - hit["z"]) < 1e-6:
            fp = lv.get("footprint")
            if not fp or wh_geometry.point_in_polygon((point[0], point[1]), fp):
                return lv.get("host", "")
    return ""


def describe(hit: dict, host: str) -> str:
    """'Building clear height' for a hall's ground level, 'Building · Mezzanine 1' for another."""
    if str(hit.get("level")) == "0":
        return f"{host} clear height"
    return f"{host} · {hit.get('label') or 'level ' + str(hit.get('level'))}"


def line_ceiling(scene, obj, levels=None) -> tuple[float, str]:
    """(world z, where it comes from) for a line hung from the ceiling, read
    at the line's origin like its `wh_system.level` (R10). "" = the Scene
    panel's Ceiling level."""
    levels = scene_levels(scene) if levels is None else levels
    p = obj.matrix_world.translation
    point = (p.x, p.y, p.z)
    hit = wh_levels.ceiling_at(point, levels)
    if hit is not None:
        return hit["ceiling_z"], describe(hit, _host_of(point, hit, levels))
    return float(scene.conveyor_settings.ceiling_z), ""


def store(settings, z: float, source: str) -> int:
    """The Line panel's copy; returns the writes made (compare before write)."""
    writes = 0
    if abs(float(settings.get(Z_KEY, -1e9)) - z) > 1e-6:
        settings[Z_KEY] = float(z)
        writes += 1
    if settings.get(FROM_KEY, "") != source:
        settings[FROM_KEY] = source
        writes += 1
    return writes


def sync(context, scene) -> int:
    """In the deferred pass: every hung line's Ceiling Z follows its level's
    clear height (or the Scene setting). Returns the lines changed."""
    from .build_line import all_lines, push_input
    from .sync_stats import note_write

    lines = [line for line in all_lines(scene) if line.conveyor_line.support_mount == 'CEILING']
    if not lines:
        return 0
    levels = scene_levels(scene)
    changed = 0
    for line in lines:
        z, source = line_ceiling(scene, line, levels)
        writes = store(line.conveyor_line, z, source)
        if push_input(line, "Ceiling Z", z):
            writes += 1
        if writes:
            note_write(writes)
            changed += 1
    return changed
