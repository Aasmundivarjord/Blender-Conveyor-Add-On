"""
Levels (contract v2.1, R10). `wh_levels` (Floorplan's Building, a mezzanine) lists floors above
the implicit ground (id 0, z 0). Every owner computes `level` itself (one writer per record,
R14): on its `wh_system` at the origin AND on each port, because an incline or a spiral has
its two ends on different floors.
"""

from .frames import polygon_world
from .geometry import point_in_polygon

GROUND = 0
Z_TOL_M = 0.05


def levels_world(levels, location=(0.0, 0.0, 0.0), yaw_deg=0.0):
    """A `wh_levels` list (local to its host object) -> world: footprints through the host's
    pose, z offset by the host's z. Entries without a usable id or z are dropped."""
    out = []
    oz = location[2] if len(location) > 2 else 0.0
    for lv in levels or []:
        if not isinstance(lv, dict) or "id" not in lv or "z" not in lv:
            continue
        fp = lv.get("footprint")
        entry = {"id": lv["id"], "z": oz + float(lv["z"]),
                 "footprint": polygon_world(fp, location, yaw_deg) if fp and len(fp) >= 3 else None}
        for key in ("headroom_m", "label"):               # 0.4.1: kept for ceiling_at and the UI
            if key in lv:
                entry[key] = lv[key]
        out.append(entry)
    return out


def level_at(point, levels, tol=Z_TOL_M):
    """The level of a world point (x, y, z): the highest level whose z <= point z + tol and whose
    footprint contains the point in plan (no footprint = the whole floor); GROUND (0) when none.
    `levels` in world coordinates (levels_world)."""
    best_id, best_z = GROUND, 0.0
    z = point[2] if len(point) > 2 else 0.0
    if z + tol < 0.0:
        best_z = float("-inf")          # below ground: only a basement level can claim it
    for lv in levels or []:
        lz = float(lv["z"])
        if lz > z + tol or lz < best_z:
            continue
        fp = lv.get("footprint")
        if fp and not point_in_polygon((point[0], point[1]), fp):
            continue
        if lz > best_z or best_id == GROUND:
            best_id, best_z = lv["id"], lz
    return best_id


def ceiling_at(point, levels, tol=Z_TOL_M):
    """Contract R17: the clear height above a world point (x, y, z). The point's level is found
    by the same rule as level_at (the highest level at or below it whose footprint holds it);
    that level's `headroom_m` gives the ceiling. Returns {"level", "label", "z", "headroom_m",
    "ceiling_z"}, or None when the point stands on no published level, or its level publishes
    no headroom (then the caller uses its own fallback, e.g. a scene ceiling height).
    `levels` in world coordinates (levels_world, which keeps headroom_m)."""
    z = point[2] if len(point) > 2 else 0.0
    best = None
    for lv in levels or []:
        lz = float(lv["z"])
        if lz > z + tol:
            continue
        fp = lv.get("footprint")
        if fp and not point_in_polygon((point[0], point[1]), fp):
            continue
        if best is None or lz > float(best["z"]):
            best = lv
    if best is None:
        return None
    try:
        headroom = float(best.get("headroom_m"))
    except (TypeError, ValueError):
        return None
    if headroom <= 0.0:
        return None
    return {"level": best["id"], "label": best.get("label"), "z": float(best["z"]),
            "headroom_m": headroom, "ceiling_z": float(best["z"]) + headroom}
