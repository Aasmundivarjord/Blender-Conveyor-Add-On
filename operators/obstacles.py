"""Obstacle alerts (interop contract v2.1, R13): a line whose goods envelope
crosses a `wh_obstacles` entry (a wall piece, a column, a stair, a shaft,
a keep-out: Floorplan writes them on its Building) in plan AND in height is
flagged on its panel and in the scene's Checks. Alert only, never a fix.

The envelope runs from the conveying surface (the line's `wh_path`) up to the
surface plus the load height: the item's height when the line carries an
object, 1 m without one. The maths is the vendored `_wh.geometry`
(path_obstacle_hits: running along a wall face does not count, a lintel above
a door only hits goods tall enough to reach it). The hits are written on the
line as our own record `conveyor_obstacle_hits` by every build (publish_line)
and by the sync pass when an obstacle host or a line moved."""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

from .._wh import frames as wh_frames
from .._wh import geometry as wh_geometry

OBSTACLES_KEY = "wh_obstacles"
HITS_KEY = "conveyor_obstacle_hits"  # JSON list of {"id", "label", "host", "z0", "z1"} on a line; absent = clear
DEFAULT_ENVELOPE_M = 1.0

_seen: dict = {}  # scene name -> fingerprint of the obstacle hosts and the lines' poses at the last sync


def scene_obstacles(scene) -> list:
    """Every `wh_obstacles` entry in the scene, polygon and z in world coordinates, with its host's name and label."""
    from .ports import SYSTEM_KEY, _json

    out = []
    for host in scene.objects:
        if OBSTACLES_KEY not in host:
            continue
        entries = _json(host.get(OBSTACLES_KEY), [])
        if not isinstance(entries, list):
            continue
        M = host.matrix_world
        loc = M.translation
        yaw = math.degrees(M.to_euler().z)
        desc = _json(host.get(SYSTEM_KEY), {})
        host_label = str(desc.get("label")) if isinstance(desc, dict) and desc.get("label") else host.name
        for ob in entries:
            poly = ob.get("polygon") if isinstance(ob, dict) else None
            if not poly or len(poly) < 3:
                continue
            try:
                z0, z1 = float(ob.get("z0", 0.0)), float(ob.get("z1", 1e9))
            except (TypeError, ValueError):
                continue
            out.append({**ob, "polygon": wh_frames.polygon_world(poly, (loc.x, loc.y, loc.z), yaw),
                        "z0": z0 + loc.z, "z1": z1 + loc.z, "host": host.name, "host_label": host_label})
    return out


def envelope_m(context, line) -> float:
    """The load height above the conveying surface: the item's height, or 1 m without an item."""
    try:
        from .stream import effective_item

        item = effective_item(context, line)
        if item is not None and item != line and float(item.dimensions.z) > 1e-6:
            return float(item.dimensions.z)
    except Exception:
        pass
    return DEFAULT_ENVELOPE_M


def line_hits(context, line, obstacles: list | None = None) -> list:
    """The obstacles the line's goods envelope crosses: [{"id", "label", "host", "z0", "z1"}]."""
    from .detect_junctions import _world_matrix
    from .ports import PATH_KEY, _json

    path = _json(line.get(PATH_KEY), [])
    if not isinstance(path, list) or len(path) < 2:
        return []
    M = _world_matrix(line)
    world = []
    for p in path:
        try:
            w = M @ Vector((float(p[0]), float(p[1]), float(p[2])))
        except (TypeError, ValueError, IndexError):
            continue
        world.append((w.x, w.y, w.z))
    if len(world) < 2:
        return []
    obstacles = scene_obstacles(context.scene) if obstacles is None else obstacles
    if not obstacles:
        return []
    hits = wh_geometry.path_obstacle_hits(world, envelope_m(context, line), obstacles)
    return [{"id": str(ob.get("id", "")), "label": str(ob.get("label") or ob.get("kind") or "obstacle"), "host": str(ob.get("host_label") or ob.get("host", "")),
             "z0": round(float(ob.get("z0", 0.0)), 2), "z1": round(float(ob.get("z1", 0.0)), 2)} for ob, _i in hits]


def hits_of(line) -> list:
    from .ports import _json

    data = _json(line.get(HITS_KEY), [])
    return [h for h in data if isinstance(h, dict)] if isinstance(data, list) else []


def describe(hit: dict) -> str:
    where = f" of {hit['host']}" if hit.get("host") else ""
    return f"Goods cross {hit.get('label', 'an obstacle')} {hit.get('id', '')}{where} (z {hit.get('z0', 0):g}–{hit.get('z1', 0):g} m)"


def write_hits(context, line, obstacles: list | None = None) -> bool:
    """Recompute and store the line's hits; True when the record changed."""
    from .ports import write_record
    from .sync_stats import note_write

    hits = line_hits(context, line, obstacles)
    if hits:
        return write_record(line, HITS_KEY, hits)
    if HITS_KEY in line:
        del line[HITS_KEY]
        note_write()
        return True
    return False


def _fingerprint(scene, lines) -> tuple:
    from .detect_junctions import _matrix_flat
    from .ports import PATH_KEY

    hosts = []
    for host in scene.objects:
        if OBSTACLES_KEY in host:
            raw = host.get(OBSTACLES_KEY)
            hosts.append((host.name, raw if isinstance(raw, str) else repr(raw), tuple(round(v, 4) for row in host.matrix_world for v in row)))
    poses = [(line.name, tuple(_matrix_flat(line)), line.get(PATH_KEY) if isinstance(line.get(PATH_KEY), str) else "") for line in lines]
    return tuple(hosts), tuple(poses)


def sync(context, scene) -> int:
    """In the deferred pass: when an obstacle host or a line moved (or an obstacle
    list changed), every line's hits are recomputed. Returns the lines rewritten."""
    from .build_line import all_lines

    lines = all_lines(scene)
    key = _fingerprint(scene, lines)
    if _seen.get(scene.name) == key:
        return 0
    _seen[scene.name] = key
    obstacles = scene_obstacles(scene)
    return sum(1 for line in lines if write_hits(context, line, obstacles))


def scene_checks(context) -> list:
    """[(line, hit)] for the Checks over the whole scene."""
    from .build_line import all_lines

    out = []
    for line in all_lines(context.scene):
        for hit in hits_of(line):
            out.append((line, hit))
    return out
