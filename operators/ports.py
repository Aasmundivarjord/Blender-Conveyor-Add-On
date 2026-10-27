"""Docking at the ports other warehouse add-ons publish, and this add-on's
own descriptor, ports and path for them -- the Racks add-on and the
shared warehouse library contract (v2). Nothing is imported across
add-ons: custom properties (JSON strings) on objects, plus one operator
of the other side that makes a load object.

A system carries `wh_ports`: a JSON list of ports in its local frame
(id, role in / out / io, kind point / face, position, heading_deg in this
add-on's convention, width_m, a load, rate_ph, capacity_ph, a handover
point, a revision that bumps when the load changes, surface_speed_m_s,
exclusive). A line docks by its ORIGIN (an "out" port: it starts there,
forward; an "in" port when reversed: it ends there, the body pointing
away) and by its END (a forward line whose end lands on an "in" port),
one dock per anchor, a port taking one line only. The docked line takes
the port's width, load, axis and rate, draws its goods from the
handover, writes `wh_port_links` (a JSON list, one entry per dock, keys
in the contract) and the v1 dict `wh_port_link` (the first entry), keeps
the rates current on every rebuild, follows a system that moves (origin
docks always, end docks within a metre) and says so on its panel when it
lost a port. Every line also publishes itself: `wh_system` (a stable
uuid that survives renames; a copy gets a new one), `wh_ports` with
`line_in` at its flow start and `line_out` at its flow end (taken when
that end is docked), and `wh_path`, its centreline.
(User request: "conveyors should snap to the rack's crane in/out
conveyors".)

Contract v2.1, through the vendored warehouse_common
copy in `_wh`: records are read in both forms, JSON string or IDProperty
(R2), and written as compact JSON only when they change; `level` on the
descriptor and on every port comes from the scene's `wh_levels` (R10);
whoever carries `wh_port_links` naming a port holds it, a flow route as
much as a line (R15); the registry entry says `"contract": "2.1"` and
leaves on unregister (R11).
"""
from __future__ import annotations

import json
import math
import os
import re
import uuid

import bpy
from mathutils import Vector

from .._wh import levels as wh_levels
from .._wh import records as wh_records
from ..model import port_io
from . import junction_ports

PORT_KEY = "conveyor_port"  # JSON {"origin": dock, "end": dock}; dock = {system, system_id, port, role, revision, load_id}
NOTE_KEY = "conveyor_port_note"  # JSON {"kind": lost | taken | scaled, "text", "system", "port", "anchor"}
LINKS_KEY = "wh_port_links"  # JSON list, one entry per dock (contract §3)
LINK_KEY = "wh_port_link"  # v1: the first entry, a dict
SYSTEM_KEY = "wh_system"  # JSON descriptor (contract §1)
PORTS_KEY = "wh_ports"
PATH_KEY = "wh_path"
LEVELS_KEY = "wh_levels"  # on a building / mezzanine host: the floors above the ground (contract §5, R10)
ADDONS_KEY = "wh_addons"  # window manager: the registry of add-ons (contract §6, R11)
CONTRACT = "2.1"  # the contract level this add-on implements, said in its registry entry
UUID_KEY = "conveyor_uuid"
NAME_KEY = "conveyor_self_name"  # the object's name when its identity was last written: a copy keeps the original's
REV_KEY = "conveyor_ports_rev"  # [last published load object, revision]
BY = "conveyor_system"
ADDON_ID = "conveyor_system"
MIN_REACH_M = 0.6  # a port is an invisible point: it captures from at least this far, whatever the line-to-line Dock Distance
Z_TOL_M = 0.25
FOLLOW_END_M = 1.0  # an end dock re-aims while the port stays this close; further away it is lost
HINT_M = 2.0  # a free end this close to a free port gets a hint and a Dock button
ANCHOR_NAMES = {"origin": "start", "end": "end"}

_cache: dict = {}  # system name -> (raw json, parsed ports)
_systems_seen: dict = {}  # system name -> (matrix, raw ports) at the last handler pass
_pending_loads: set = set()


# ------------------------------------------------------------- reading --

def is_line(obj) -> bool:
    try:
        return obj is not None and obj.type == 'CURVES' and bool(obj.conveyor_line.is_conveyor_line)
    except Exception:
        return False


def is_system(obj) -> bool:
    """Another add-on's system publishing ports (never one of our lines)."""
    try:
        return obj is not None and PORTS_KEY in obj and not is_line(obj)
    except Exception:
        return False


def systems(scene) -> list:
    return [o for o in scene.objects if is_system(o)]


def scaled(system) -> bool:
    try:
        return any(abs(float(s) - 1.0) > 0.01 for s in system.matrix_world.to_scale())
    except Exception:
        return False


def _json(raw, default):
    """A record as plain Python from a JSON string or an IDProperty group /
    array (readers accept both forever, contract v2.1 R2): warehouse_common's reader."""
    try:
        value = wh_records.read_record(raw, default)
    except Exception:
        return default
    return default if value is None else value


def ports_of(system) -> list:
    raw = system.get(PORTS_KEY, "")
    if raw is None:
        return []
    if not isinstance(raw, str):  # an IDProperty list (a file saved before v2.1): read as it is, uncached
        return [p for p in _json(raw, []) if isinstance(p, dict) and p.get("id")]
    cached = _cache.get(system.name)
    if cached is None or cached[0] != raw:
        parsed = [p for p in _json(raw, []) if isinstance(p, dict) and p.get("id")]
        _cache[system.name] = (raw, parsed)
    return _cache[system.name][1]


def port_by_id(system, port_id: str):
    return next((p for p in ports_of(system) if p.get("id") == port_id), None) if system is not None else None


def system_id(system) -> str:
    desc = _json(system.get(SYSTEM_KEY), {}) if system is not None else {}
    return str(desc.get("id", "")) if isinstance(desc, dict) else ""


def find_system(scene, sid: str, name: str):
    """The system by its stable id first, its name second."""
    if sid:
        for system in systems(scene):
            if system_id(system) == sid:
                return system
    system = scene.objects.get(name) if name else None
    return system if is_system(system) else None


def scene_levels(scene) -> list:
    """Every `wh_levels` entry in the scene (Floorplan's building, a mezzanine
    add-on's deck), in world coordinates (contract v2.1 R10)."""
    out = []
    for host in scene.objects:
        if LEVELS_KEY not in host:
            continue
        entries = _json(host.get(LEVELS_KEY), [])
        if not isinstance(entries, list):
            continue
        M = host.matrix_world
        loc = M.translation
        out.extend(wh_levels.levels_world(entries, (loc.x, loc.y, loc.z), math.degrees(M.to_euler().z)))
    return out


def level_at_world(point, levels: list):
    """The level of a world point: the highest `wh_levels` entry under it (within
    5 cm) whose footprint holds it in plan; 0 on the ground. Written on the
    descriptor at the origin AND on every port: an incline or a spiral has its
    two ends on different floors (R10)."""
    if not levels:
        return 0
    return wh_levels.level_at((float(point[0]), float(point[1]), float(point[2])), levels)


def world_port(system, port, role: str | None = None):
    """(world position, world heading in radians (0 = +Y, counter-clockwise),
    world handover point or None) of a port, the heading being the goods'
    direction for a line of `role` (model/port_io: an io port -- one
    conveyor serving a crane aisle both ways -- publishes `heading_deg` for
    goods leaving and `heading_in_deg` for goods arriving). A FACE port (a tote rack's
    pick face, a flow rack's pick / fill face) carries "face": [p0, p1] and
    "outward" instead of a position: its position is the face's middle and
    its heading the outward direction (it measured from the rack's origin
    before, so the eyedropper took a flow rack's fill face for its pick
    face)."""
    M = system.matrix_world
    pos_local = port.get("position")
    face = port.get("face")
    if pos_local is None and isinstance(face, (list, tuple)) and len(face) == 2:
        a, b = Vector(face[0]), Vector(face[1])
        pos_local = (a + b) / 2.0
    pos = M @ Vector(pos_local or (0.0, 0.0, 0.0))
    outward = port.get("outward")
    if "heading_deg" in port or not isinstance(outward, (list, tuple)) or len(outward) < 2:
        from ..model import port_io

        heading = M.to_euler().z + math.radians(port_io.heading_deg(port, role))
    else:
        heading = M.to_euler().z + math.atan2(-float(outward[0]), float(outward[1]))  # 0 = +Y, counter-clockwise
    hand = port.get("handover")
    handover = M @ Vector(hand) if hand else None
    return pos, heading, handover


def dock_pos(port, pos: Vector, own_z: float) -> Vector:
    """Where a line's end goes when it docks at `port` (R16): the port's XY and,
    for a `z_free` port ("may be joined at ANY height": a dock door, a ground
    door, a flow point at floor level), the line's OWN height; other ports set z."""
    return Vector((pos.x, pos.y, own_z if port.get("z_free") else pos.z))


def port_distance(system, port, point: Vector) -> float:
    """Plan distance from `point` to the port: to a face port's segment, to a point port's position."""
    face = port.get("face")
    if isinstance(face, (list, tuple)) and len(face) == 2 and port.get("position") is None:
        M = system.matrix_world
        a, b = M @ Vector(face[0]), M @ Vector(face[1])
        ab = b - a
        t = 0.0 if ab.length_squared < 1e-12 else max(0.0, min(1.0, (point - a).dot(ab) / ab.length_squared))
        return (a + ab * t - point).length
    return (world_port(system, port)[0] - point).length


def holder_of(scene, system, port_id: str, exclude=None):
    """Who holds that port (ports are exclusive): the line docked there, else
    ANY other object whose `wh_port_links` names it by `system_id` + `port`
    (a Floorplan flow route, for one: contract v2.1 R15), else None."""
    from .build_line import all_lines

    sid = system_id(system)
    for line in all_lines(scene):
        if line == exclude:
            continue
        for dock in docks(line).values():
            same_system = (sid and dock.get("system_id") == sid) or dock.get("system") == system.name
            if same_system and dock.get("port") == port_id:
                return line
    for obj in scene.objects:
        if obj == exclude or obj == system or LINKS_KEY not in obj or is_line(obj):
            continue
        for entry in wh_records.supported(_json(obj.get(LINKS_KEY), [])):
            if str(entry.get("port", "")) != str(port_id):
                continue
            entry_sid = str(entry.get("system_id", "") or "")
            if (entry_sid and entry_sid == sid) or (not entry_sid and entry.get("system") == system.name):
                return obj
    return None


def holder_name(holder) -> str:
    """How the UI names whoever holds a port: its descriptor's label ("Route AMR-2"), else the object's name."""
    if holder is None:
        return ""
    desc = _json(holder.get(SYSTEM_KEY), {})
    label = desc.get("label") if isinstance(desc, dict) else None
    return str(label) if label else holder.name


def scan_ports(scene, point: Vector, role: str, radius: float, exclude=None) -> list:
    """Point ports of `role` (or io) within `radius` of `point` in plan and
    about its height, nearest first, each with its holder and whether its
    system is scaled."""
    out = []
    for system in systems(scene):
        is_scaled = scaled(system)
        for port in ports_of(system):
            if port.get("kind", "point") != "point" or port.get("role") not in (role, "io"):
                continue
            pos, heading, handover = world_port(system, port)
            if abs(pos.z - point.z) > Z_TOL_M and not port.get("z_free"):
                continue
            d = math.hypot(pos.x - point.x, pos.y - point.y)
            if d > radius:
                continue
            from ..model import port_io

            out.append({"d": d, "system": system, "port": port, "pos": pos, "heading": heading, "handover": handover,
                        "holder": holder_of(scene, system, port.get("id"), exclude), "scaled": is_scaled,
                        "refused": not port_io.carries_load(port.get("load"))})  # R19: a load kind a conveyor does not carry
    out.sort(key=lambda c: c["d"])
    return out


def nearest_port(scene, point: Vector, role: str, reach: float, exclude=None):
    """(system, port, world position, world heading, world handover) of the
    closest FREE port of `role` within `reach`, on an unscaled system."""
    for c in scan_ports(scene, point, role, reach, exclude):
        if c["holder"] is None and not c["scaled"] and not c["refused"]:
            return c["system"], c["port"], c["pos"], c["heading"], c["handover"]
    return None


def blocked_port_near(scene, point: Vector, role: str, reach: float, exclude=None):
    """A port within reach that cannot be docked: taken by another line, or on a scaled system."""
    for c in scan_ports(scene, point, role, reach, exclude):
        if c["holder"] is not None or c["scaled"] or c["refused"]:
            return c
    return None


def port_at(scene, point: Vector, reach: float):
    """For New Line at Cursor: the port under the cursor, an "out" port
    first (the line starts there), else an "in" one (the line ends there)."""
    return nearest_port(scene, point, "out", reach) or nearest_port(scene, point, "in", reach)


def _reach(context) -> float:
    from .detect_junctions import _reach as dock_reach

    return max(dock_reach(context), MIN_REACH_M)


# ------------------------------------------------------- bookkeeping --

def docks(obj) -> dict:
    """{anchor: dock} of this line ("origin" / "end"); an old single dock is read as its anchor."""
    data = _json(obj.get(PORT_KEY), {})
    if not isinstance(data, dict):
        return {}
    if "system" in data:  # the v1 flat dock
        return {str(data.get("anchor", "origin")): {k: v for k, v in data.items() if k != "anchor"}}
    return {k: v for k, v in data.items() if k in ("origin", "end") and isinstance(v, dict)}


def write_record(target, key: str, value) -> bool:
    """warehouse_common's writer (compact JSON, only on change), counted for the sync statistics (R5)."""
    from .sync_stats import note_write

    changed = wh_records.write_record(target, key, value)
    if changed:
        note_write()
    return changed


def _save_docks(obj, data: dict) -> None:
    """The dock record, written only when it changes: a port whose load is not
    in the file yet (Racks builds it on a timer) is re-tried on every sync pass
    and re-stored unchanged, which rewrote the record once per pass, forever
    (2.10.0; R5 wants a settled pass to make 0 writes)."""
    from .sync_stats import note_write

    if data:
        text = json.dumps(data)
        if obj.get(PORT_KEY) != text:
            obj[PORT_KEY] = text
            note_write()
    elif PORT_KEY in obj:
        del obj[PORT_KEY]
        note_write()


def dock_at(obj, anchor: str):
    return docks(obj).get(anchor)


def linked_at(context, obj, anchor: str):
    """(system, port, role, anchor) of this line's dock at `anchor`, or None."""
    dock = dock_at(obj, anchor)
    if dock is None:
        return None
    system = find_system(context.scene, str(dock.get("system_id", "")), str(dock.get("system", "")))
    port = port_by_id(system, str(dock.get("port", "")))
    if port is None:
        return None
    return system, port, str(dock.get("role", "out")), anchor


def linked(context, obj):
    """The line's dock, origin first (what most read-outs want), or None."""
    return linked_at(context, obj, "origin") or linked_at(context, obj, "end")


FLOW_PORT_KEYS = ("population", "population_in", "speed_m_s", "max_population", "master", "share",
                  "rate_ph", "rate_in_ph", "capacity_ph", "surface_speed_m_s")
FLOW_SYSTEM_KEYS = ("population", "speed_m_s", "max_population", "master")


def flow_signature(system, port) -> str:
    """What a docked line's stream reads from the system it docks at: the
    port's sliders, caps and legacy rates and its system's own stream (R22).
    Another add-on changing any of them re-resolves the line (2.23.2: a
    door's population going 0 -> 0.5 left the line publishing 0)."""
    sysrec = _json(system.get(SYSTEM_KEY), {})
    sysrec = sysrec if isinstance(sysrec, dict) else {}
    return json.dumps([port.get(k) for k in FLOW_PORT_KEYS] + [sysrec.get(k) for k in FLOW_SYSTEM_KEYS])


def _store(obj, anchor: str, system, port, role: str, load_done: bool = True) -> None:
    data = docks(obj)
    old = data.get(anchor) or {}
    sid = system_id(system)
    keep = {"by": old["by"]} if old.get("by") and old.get("port") == port.get("id") and old.get("system_id") == sid else {}
    data[anchor] = {**keep, "system": system.name, "system_id": sid, "port": port.get("id"), "role": role,
                    "revision": int(port.get("revision", 0) or 0),
                    "load_id": str((port.get("load") or {}).get("id", "")) if load_done else "",  # `by`: who asked for the dock (R6)
                    "flow": flow_signature(system, port)}
    _save_docks(obj, data)


def _forget(obj, anchor: str) -> bool:
    data = docks(obj)
    if anchor not in data:
        return False
    del data[anchor]
    _save_docks(obj, data)
    return True


def note(obj) -> dict | None:
    data = _json(obj.get(NOTE_KEY), None)
    return data if isinstance(data, dict) and data.get("text") else None


def set_note(obj, kind: str, text: str, system: str = "", port: str = "", anchor: str = "", extra: dict | None = None) -> None:
    from .sync_stats import note_write

    data = {"kind": kind, "text": text, "system": system, "port": port, "anchor": anchor}
    if extra:
        data.update(extra)
    text_json = json.dumps(data)
    if obj.get(NOTE_KEY) != text_json:
        obj[NOTE_KEY] = text_json
        note_write()


def clear_note(obj, anchor: str | None = None) -> None:
    n = note(obj)
    if n is None:
        return
    if anchor is None or n.get("anchor") == anchor:
        del obj[NOTE_KEY]


# ------------------------------------------------------------- rates --

def _rate(context, obj) -> float:
    """The headline rate of the line (what it asks for / takes)."""
    from .stream import line_load_ph

    try:
        return float(line_load_ph(context, obj))
    except Exception:
        return 0.0


def _delivered(context, obj) -> float:
    """What actually flows: cut down by a buffer, a rack's capacity or a
    saturated line (the rack runs its aisle at this)."""
    from .stream import delivered_ph

    try:
        return float(delivered_ph(context, obj))
    except Exception:
        return _rate(context, obj)


def capacity_of(port, item_length_m: float | None = None, speed_m_s: float | None = None) -> float:
    """What the port takes or makes an hour: its `capacity_ph`, else (R22)
    its `max_population` at the goods' speed (model/port_io.capacity_ph)."""
    try:
        return port_io.capacity_ph(port, item_length_m, speed_m_s)
    except Exception:
        return 0.0


def _clock(scene) -> tuple[float, float]:
    """(t_start in scene seconds, the scene's time scale)."""
    from ..props.scene_settings import time_scale

    fps = scene.render.fps / (scene.render.fps_base or 1.0)
    return scene.frame_start / fps, time_scale(scene)


def _inset(context, root, tree) -> float:
    from .populate import populate_item_length

    return max(tree.slot_length, populate_item_length(context, root)) / 2.0


def crossings_at(context, obj, u_port: float):
    """(phase_s, period_s), operation seconds, at which this line's goods'
    centres cross stream coordinate `u_port`; None when the stream stands."""
    from ..model.clock import crossing_phase_op_s
    from .stream import tree_for

    tree = tree_for(context, obj)
    if obj.name not in tree.members or tree.speed <= 1e-9:
        return None
    t_start, scale = _clock(context.scene)
    phase, period = crossing_phase_op_s(tree.phase_s, t_start, scale, _inset(context, tree.root, tree), u_port, tree.speed, tree.actual_spacing)
    # Where only some of the slots arrive (a branch's share, a feeder's own
    # goods), the period is the average one, 1 / the flow there (R22: WC's
    # convention; exact arrivals would deal branch_of_item over the master's).
    from .stream import line_out_ph

    flow = line_out_ph(context, obj)
    if 0.0 < flow < tree.throughput_ph * (1.0 - 1e-6):
        period = 3600.0 / flow
        phase = phase % period
    return phase, period


def in_port_crossings(context, obj):
    """The goods' crossings of this line's flow END (the port it feeds)."""
    from .stream import tree_for

    tree = tree_for(context, obj)
    ls = tree.members.get(obj.name)
    if ls is None:
        return None
    from .stream import path_length_m

    return crossings_at(context, obj, float(ls.offset) + path_length_m(obj))


def out_port_phase(context, root, tree) -> float:
    """Stream Phase (scene seconds) for a root line starting on a linked
    "out" port: the rack publishes when its loads' centres cross the port
    (phase_s + k period_s, operation seconds); a slot centre is put there
    at those times. 0 otherwise."""
    from ..model.clock import stream_phase_scene_s

    hit = linked_at(context, root, "origin")
    if hit is None or hit[2] not in ("out", "io"):
        return 0.0
    _system, port, _role, _anchor = hit
    try:
        phase_op = float(port.get("phase_s", 0.0) or 0.0)
    except Exception:
        phase_op = 0.0
    t_start, scale = _clock(context.scene)
    return stream_phase_scene_s(t_start, phase_op, scale, _inset(context, root, tree), 0.0, tree.speed, tree.actual_spacing)


def start_offset_m(context, obj) -> float:
    """How far along the line the goods start: the port's handover point
    when the line starts on an "out" port."""
    hit = linked_at(context, obj, "origin")
    if hit is None or hit[2] not in ("out", "io"):
        return 0.0
    system, port, _role, _anchor = hit
    pos, _h, handover = world_port(system, port)
    if handover is None:
        return 0.0
    return max(0.0, (Vector((handover.x, handover.y, 0.0)) - Vector((pos.x, pos.y, 0.0))).length)


# ------------------------------------------------------------- links --

def _entries(context, obj) -> list:
    entries = []
    requested = None
    for anchor in ("origin", "end"):
        hit = linked_at(context, obj, anchor)
        if hit is None:
            continue
        system, port, role, _ = hit
        if requested is None:
            requested, rate = _rate(context, obj), _delivered(context, obj)
        # Contract §3: the anchor is the FLOW start / end; a reversed line's
        # origin is its flow end (IO-2).
        flow_anchor = ANCHOR_NAMES[anchor] if not obj.conveyor_line.reverse else ANCHOR_NAMES["end" if anchor == "origin" else "origin"]
        entry = {"version": 2, "system_id": system_id(system), "system": system.name, "port": str(port.get("id")), "role": role,
                 "anchor": flow_anchor, "rate_ph": round(rate, 3), "requested_ph": round(requested, 3), "by": BY,
                 "line_id": str(obj.get(UUID_KEY, ""))}
        if role == "in" or (role == "io" and anchor == "end"):
            try:
                crossings = in_port_crossings(context, obj)
            except Exception:
                crossings = None
            if crossings is not None:
                entry["phase_s"], entry["period_s"] = round(float(crossings[0]), 4), round(float(crossings[1]), 4)
        if flow_anchor == "end":
            # R22.4: exactly when the goods arrive, behind the splits on the way
            # (simple_flow.branch_arrivals); absent where it cannot be exact.
            from .stream import arrivals_record

            try:
                arrivals = arrivals_record(context, obj)
            except Exception:
                arrivals = None
            if arrivals is not None:
                entry["arrivals"] = arrivals
        entries.append(entry)
    # R22.1: the junction this line leaves or joins, the line it carries on from.
    try:
        entries += junction_ports.junction_links(context, obj)
    except Exception as exc:
        print(f"conveyor: junction links of {obj.name} failed: {exc!r}")
    return entries


def write_links(context, obj, entries: list | None = None) -> None:
    entries = _entries(context, obj) if entries is None else entries
    if entries:
        write_record(obj, LINKS_KEY, entries)  # compact JSON, written only when it changed (R2)
        from .sync_stats import note_write

        docked = [e for e in entries if "edge" not in e]  # the v1 entry is a dock at a system's port, never a junction
        if docked:
            first = docked[0]
            v1 = {k: first[k] for k in ("system", "port", "role", "rate_ph", "requested_ph", "by", "phase_s", "period_s") if k in first}
            if _json(obj.get(LINK_KEY), None) != v1:
                obj[LINK_KEY] = v1  # the v1 entry stays a dict until no v1 reader is left
                note_write()
        elif obj.get(LINK_KEY) is not None:
            del obj[LINK_KEY]
            note_write()
        return
    # No dock, no link. A line's links are OUR record (one writer per record, R14): whatever is
    # there goes, including entries an older Racks (0.18 and before) wrote onto lines.
    from .sync_stats import note_write

    for key in (LINKS_KEY, LINK_KEY):
        if obj.get(key) is not None:
            del obj[key]
            note_write()


def refresh_links(context, obj) -> None:
    """After a rebuild: the rates and crossing times the systems read
    follow the line -- and a line without docks carries no link of ours
    (a lost end dock left its entry behind)."""
    try:
        entries = _entries(context, obj)
        if not entries:
            if obj.get(LINKS_KEY) is not None or obj.get(LINK_KEY) is not None:
                write_links(context, obj, entries)
            return
        if obj.get(LINKS_KEY) != wh_records.dumps(entries):
            write_links(context, obj, entries)
    except Exception:
        pass


def release_port(context, obj, anchor: str | None = None) -> bool:
    """The line left its port(s): drop the dock(s) and our links."""
    had = False
    for a in (("origin", "end") if anchor is None else (anchor,)):
        had |= _forget(obj, a)
    write_links(context, obj)
    return had


# --------------------------------------------------------- what docks --

def set_width(settings, width_mm: float) -> bool:
    """The line as wide as the port: a catalogue width when one matches,
    else Custom. True when it changed."""
    from ..config import loader
    from .build_line import resolve_width_mm

    target = float(round(width_mm))
    if abs(resolve_width_mm(settings) - target) < 0.5:
        return False
    for group in loader.get_width_presets().values():
        for preset in group:
            if abs(float(preset.width_mm) - target) < 0.5:
                try:
                    settings.width_preset = preset.id
                    return True
                except TypeError:
                    break  # not a width this conveyor type offers
    settings.width_preset = 'CUSTOM'
    settings.custom_width_mm = target
    return True


def carries_upstream_goods(context, obj) -> bool:
    """A branch or takeaway carries its main line's goods (stream.parent_of
    DIVERTER / CONTINUE): an in-port at its end receives them, it does not
    decide them (2.23.3: a branch given a rack in-feed's EUR1 sorted for an
    item its placeholder main never brought, and took nothing)."""
    from .stream import parent_of

    parent = parent_of(context, obj)
    return parent is not None and parent[0] in ('DIVERTER', 'CONTINUE')


def apply_port(context, obj, system, port, role: str, fresh: bool = True) -> tuple[bool, bool]:
    """Width, load, axis and throughput from the port; on a fresh dock the
    line's speed too (`surface_speed_m_s`, the delivery conveyor's roller
    speed, so the hand-over has no speed step -- the user may raise it
    afterwards). Returns (changed, load applied)."""
    from ..props.line_settings import suspended_rebuild
    from .pick_item import apply_port_load

    settings = obj.conveyor_line
    changed = False
    with suspended_rebuild():
        width_m = port.get("width_m")
        if width_m:
            changed |= set_width(settings, float(width_m) * 1000.0)
        surface = port_io.goods_speed_m_s(port)  # R22 speed_m_s, else the legacy surface_speed_m_s
        if fresh and surface and abs(float(settings.speed_m_s) - float(surface)) > 1e-6:
            settings.speed_m_s = float(surface)
            changed = True
    done = True
    if role in ("out", "io") or (settings.populate_item is None and not carries_upstream_goods(context, obj)):
        applied, done, _msg = apply_port_load(context, obj, system, port, role)
        changed |= applied
    return changed, done


def _changed_load(dock, port) -> bool:
    if dock is None:
        return True
    from .._wh import loads as wh_loads

    load_id = str((port.get("load") or {}).get("id", ""))
    return (int(port.get("revision", 0) or 0) != int(dock.get("revision", 0) or 0)
            or not wh_loads.same_load(load_id, str(dock.get("load_id", ""))))


def _dock_origin(context, obj, system, port, role: str, fresh: bool) -> None:
    from .detect_junctions import _place_origin, _rebuild, _release_origin, _remember_matrix

    from .detect_junctions import _world_matrix

    cur = dock_at(obj, "origin")
    pos, heading, _handover = world_port(system, port, role)  # an in line: the goods' arriving direction (heading_in_deg on an io port)
    pos = dock_pos(port, pos, _world_matrix(obj).translation.z)
    if fresh:
        _release_origin(context, obj)  # whatever line junction the origin held before
    moved = _place_origin(obj, pos, heading + (math.pi if role == "in" else 0.0))
    if moved:
        _remember_matrix(obj)
    changed, done = apply_port(context, obj, system, port, role, fresh) if (fresh or _changed_load(cur, port)) else (False, True)
    _store(obj, "origin", system, port, role, done)
    clear_note(obj, "origin")
    write_links(context, obj)
    if fresh or changed or moved:
        _rebuild(context, obj)


def sync_port(context, obj) -> bool:
    """The ORIGIN at a port: "out" (or io) for a forward line (it starts
    there), "in" (or io) for a reversed one (it ends there). Returns True
    when docked: the origin is pinned, like an origin attached to a line."""
    from .detect_junctions import _rebuild, _world_matrix, flow_reversed

    scene = context.scene
    if not obj.conveyor_line.segments:
        return False
    cur = dock_at(obj, "origin")
    if not systems(scene):
        if cur is not None and release_port(context, obj, "origin"):
            _rebuild(context, obj)
        return False
    origin = _world_matrix(obj) @ Vector((0.0, 0.0, 0.0))
    role = "in" if flow_reversed(obj) else "out"
    reach = _reach(context)
    hit = nearest_port(scene, origin, role, reach, exclude=obj)
    if hit is None:
        if cur is not None:
            release_port(context, obj, "origin")
            _rebuild(context, obj)  # the goods start at the line's start again
        blocked = blocked_port_near(scene, origin, role, reach, exclude=obj)
        if blocked is not None:
            _note_blocked(obj, blocked, "origin")
        else:
            n = note(obj)
            if n is not None and n.get("anchor") == "origin" and n.get("kind") in ("taken", "scaled", "refused"):
                clear_note(obj, "origin")
        return False
    system, port, _pos, _heading, _handover = hit
    fresh = cur is None or cur.get("port") != port.get("id") or (cur.get("system") != system.name and cur.get("system_id") != system_id(system))
    _dock_origin(context, obj, system, port, "in" if role == "in" else "out", fresh)
    return True


def _note_blocked(obj, blocked: dict, anchor: str) -> None:
    system, port = blocked["system"], blocked["port"]
    if blocked["scaled"]:
        set_note(obj, "scaled", f"{system.name} is scaled; sizes are 1:1 metres", system.name, str(port.get("id")), anchor)
    elif blocked.get("refused"):
        from ..model import port_io

        set_note(obj, "refused", f"{port.get('id')} on {system.name} delivers {port_io.load_kind(port.get('load'))} loads: "
                                 "not carried on a conveyor", system.name, str(port.get("id")), anchor)
    else:
        holder = blocked["holder"]
        set_note(obj, "taken", f"{port.get('id')} is taken by {holder_name(holder)}", system.name, str(port.get("id")), anchor,
                 extra={"foreign": not is_line(holder)})  # another add-on's record frees the port there, never a take-over here (R14)


def _end_pose(context, obj):
    from .detect_junctions import _line_data, _world_matrix

    spine = _line_data(context, obj)[0]
    if len(spine) == 0:
        return None
    end = spine.pose_at(len(spine) - 1)
    end_local = Vector((end.x, end.y, end.z))
    return end, end_local, _world_matrix(obj) @ end_local


def _aim_end(context, obj, end, end_local, end_world, pos: Vector, heading: float) -> bool:
    from .detect_junctions import _remember_matrix, _rotate_about

    new_yaw = heading - end.heading
    yaw_now = obj.rotation_euler.z
    new_yaw = yaw_now + ((new_yaw - yaw_now + math.pi) % (2.0 * math.pi) - math.pi)
    moved = abs(new_yaw - yaw_now) > 1e-6 or (end_world - pos).length > 1e-4
    if moved:
        _rotate_about(obj, end_local, pos, new_yaw)
        _remember_matrix(obj)
    return moved


def _dock_end(context, obj, system, port, fresh: bool) -> None:
    from .detect_junctions import _rebuild

    cur = dock_at(obj, "end")
    pose = _end_pose(context, obj)
    if pose is None:
        return
    end, end_local, end_world = pose
    pos, heading, _handover = world_port(system, port, "in")  # aimed along the goods' arriving direction
    pos = dock_pos(port, pos, end_world.z)
    moved = _aim_end(context, obj, end, end_local, end_world, pos, heading)
    changed, done = apply_port(context, obj, system, port, "in", fresh) if (fresh or _changed_load(cur, port)) else (False, True)
    _store(obj, "end", system, port, "in", done)
    clear_note(obj, "end")
    write_links(context, obj)
    if fresh or changed or moved:
        _rebuild(context, obj)


def sync_port_end(context, obj) -> bool:
    """A forward line whose END lands at an "in" (or io) port docks that
    end there, flowing into the system (turned about its end). True when docked."""
    from .detect_junctions import _rebuild, flow_reversed

    scene = context.scene
    cur = dock_at(obj, "end")
    if flow_reversed(obj) or not obj.conveyor_line.segments or (not systems(scene) and cur is None):
        if cur is not None and release_port(context, obj, "end"):
            _rebuild(context, obj)
        return False
    pose = _end_pose(context, obj)
    if pose is None:
        return False
    _end, _end_local, end_world = pose
    reach = _reach(context)
    hit = nearest_port(scene, end_world, "in", reach, exclude=obj)
    if hit is None:
        if cur is not None:
            release_port(context, obj, "end")
            _rebuild(context, obj)
        blocked = blocked_port_near(scene, end_world, "in", reach, exclude=obj)
        if blocked is not None:
            _note_blocked(obj, blocked, "end")
        else:
            n = note(obj)
            if n is not None and n.get("anchor") == "end" and n.get("kind") in ("taken", "scaled", "refused"):
                clear_note(obj, "end")
        return False
    system, port, _pos, _heading, _handover = hit
    fresh = cur is None or cur.get("port") != port.get("id") or (cur.get("system") != system.name and cur.get("system_id") != system_id(system))
    _dock_end(context, obj, system, port, fresh)
    return True


def _follow(context, line, anchor: str, system, port, role: str):
    """The system moved or changed: keep the dock. ("moved" | "same" | "lost", distance)."""
    from .detect_junctions import _place_origin, _remember_matrix, _world_matrix

    pos, heading, _handover = world_port(system, port)
    if anchor == "origin":
        moved = _place_origin(line, dock_pos(port, pos, _world_matrix(line).translation.z), heading + (math.pi if role == "in" else 0.0))
        if moved:
            _remember_matrix(line)
        return ("moved" if moved else "same"), 0.0
    pose = _end_pose(context, line)
    if pose is None:
        return "same", 0.0
    end, end_local, end_world = pose
    pos = dock_pos(port, pos, end_world.z)
    d = (end_world - pos).length
    if d > FOLLOW_END_M:
        return "lost", d
    return ("moved" if _aim_end(context, line, end, end_local, end_world, pos, heading) else "same"), d


def sync_links(context, scene) -> None:
    """Every handler pass: systems that moved or changed their ports pull
    their docked lines along (or lose them), ports gone let go, loads
    changed refresh the item, and a line that lost a port or waits for a
    taken one tries again whenever a system changed."""
    from .build_line import all_lines
    from .detect_junctions import _rebuild, sync_feeder

    signatures = {}
    for system in systems(scene):
        raw = system.get(PORTS_KEY, "")
        signatures[system.name] = (tuple(round(v, 4) for row in system.matrix_world for v in row),
                                   raw if isinstance(raw, str) else wh_records.dumps(_json(raw, [])))
    changed = {name for name, sig in signatures.items() if _systems_seen.get(name) != sig}
    first_pass = not _systems_seen
    _systems_seen.clear()
    _systems_seen.update(signatures)
    if first_pass:
        changed = set()  # a reload is not a move
    for line in all_lines(scene):
        data = docks(line)
        n = note(line)
        if not data and n is None:
            continue
        touched = False
        for anchor in list(data.keys()):
            dock = data[anchor]
            system = find_system(scene, str(dock.get("system_id", "")), str(dock.get("system", "")))
            port = port_by_id(system, str(dock.get("port", "")))
            role = str(dock.get("role", "out"))
            if system is None or port is None or port.get("role") not in (role, "io"):
                _forget(line, anchor)
                write_links(context, line)  # lost = no link: the system must see the port free
                set_note(line, "lost", f"lost {dock.get('system')} · {dock.get('port')} (port gone)", str(dock.get("system")), str(dock.get("port")), anchor)
                touched = True
                continue
            if system.name in changed:
                state, d = _follow(context, line, anchor, system, port, role)
                if state == "lost":
                    _forget(line, anchor)
                    write_links(context, line)
                    set_note(line, "lost", f"lost {system.name} · {port.get('id')} ({d:.1f} m away)", system.name, str(port.get("id")), anchor)
                    touched = True
                    continue
                touched |= state == "moved"
            flow = flow_signature(system, port)
            if _changed_load(dock, port):
                applied, done = apply_port(context, line, system, port, role, fresh=False)
                touched |= applied
                _store(line, anchor, system, port, role, done)
            elif dock.get("flow") != flow:
                from .._wh import loads as wh_loads

                same_load = wh_loads.same_load(str(dock.get("load_id", "")), str((port.get("load") or {}).get("id", "")))
                _store(line, anchor, system, port, role, same_load)  # a dock stored before 2.23.2 just records it
            # Another add-on changed what the stream reads there (a door's
            # population, a rack's speed or cap): the stream follows (R22).
            touched |= dock.get("flow") is not None and dock.get("flow") != flow
        if touched:
            _rebuild(context, line)
        n = note(line)
        if n is not None and n.get("kind") in ("lost", "taken", "scaled", "refused") and changed:
            sync_feeder(context, line)  # its port may be back, free or unscaled


# ------------------------------------------------------- the own side --

def ensure_identity(context, obj) -> str:
    """The line's stable id: written once, kept through renames; a copy
    (same id as another line, its recorded name not its own) gets a new one."""
    from .build_line import all_lines

    uid = str(obj.get(UUID_KEY, "") or "")
    recorded = str(obj.get(NAME_KEY, "") or "")
    if uid and recorded and recorded != obj.name:
        if any(o != obj and str(o.get(UUID_KEY, "")) == uid for o in all_lines(context.scene)):
            uid = ""
    if not uid:
        uid = uuid.uuid4().hex
        obj[UUID_KEY] = uid
    if recorded != obj.name:
        obj[NAME_KEY] = obj.name
    return uid


def is_copy(context, obj) -> bool:
    """A line whose recorded name is another's and whose id another line
    holds: a duplicate (Shift+D) that still carries the original's docks."""
    from .build_line import all_lines

    uid = str(obj.get(UUID_KEY, "") or "")
    recorded = str(obj.get(NAME_KEY, "") or "")
    return bool(uid) and bool(recorded) and recorded != obj.name and any(o != obj and str(o.get(UUID_KEY, "")) == uid for o in all_lines(context.scene))


def _resample(points: list, step: float) -> list:
    out = []
    for i, p in enumerate(points):
        if i == 0:
            out.append(p)
            continue
        prev = out[-1]
        seg = p - prev
        n = max(1, int(math.ceil(seg.length / step - 1e-9)))
        for k in range(1, n + 1):
            out.append(prev + seg * (k / n))
    return out


def _own_points(obj):
    from .detect_junctions import _own_point_range

    cd = obj.data
    if not cd.curves or "position" not in cd.attributes:
        return [], []
    first, stop = _own_point_range(obj)
    pts = [Vector(v.vector) for v in cd.attributes["position"].data][first:stop]
    heads = [v.value for v in cd.attributes["heading"].data][first:stop] if "heading" in cd.attributes else [0.0] * len(pts)
    return pts, heads


def _version() -> str:
    try:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "blender_manifest.toml")
        with open(path, encoding="utf-8") as f:
            m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
            return m.group(1) if m else "2.6"
    except Exception:
        return "2.6"


def _load_descriptor(context, obj) -> dict:
    """The load as it travels on this line (wh_load: `length_m` ALONG travel,
    `forward_axis` the item's axis pointing that way): its own record, else
    one from its box. Where the goods ride sideways on the line (after a 90
    degree pop-up transfer, which does not turn them: "1200 in, 800 out")
    and their width is the larger side, length and width trade places and
    the forward axis turns -- the length the line's pitch uses and every
    reader's population must use (2.23.4: a branch published the main's
    0.8 m and warehouse_common sized it 0.8 while it ran 1.2)."""
    from .populate import goods_turned, item_length_along, wh_load
    from .stream import effective_item

    item = effective_item(context, obj)
    if item is None or item == obj:
        return {"kind": "tote", "id": "placeholder", "object": "", "length_m": 0.6, "width_m": 0.4, "height_m": 0.3, "forward_axis": "Y"}
    load = wh_load(item)
    if not load:
        from .populate import item_extents, resolve_forward_axis

        sx, sy, _z = item_extents(item)
        axis = resolve_forward_axis(obj.conveyor_line, item)
        along = item_length_along(obj.conveyor_line, item)
        load = {"kind": "item", "id": f"object:{item.name}", "object": item.name, "length_m": round(along, 3),
                "width_m": round(sy if axis in ('X', 'NEG_X') else sx, 3), "height_m": round(item.dimensions.z, 3), "forward_axis": axis[-1]}
    try:
        length, width = float(load.get("length_m") or 0.0), float(load.get("width_m") or 0.0)
    except (TypeError, ValueError):
        return load
    if width > length + 1e-6 and goods_turned(context, obj):
        turned = {"X": "Y", "Y": "X"}.get(str(load.get("forward_axis", "")), load.get("forward_axis"))
        load = dict(load, length_m=load["width_m"], width_m=load["length_m"], forward_axis=turned)
    return load


def publish_line(context, obj) -> None:
    """The line's own descriptor, ports and path for other add-ons
    (contract v2 §1, §2, §6). Called at the end of every build."""
    from ..config import loader
    from ..geonodes.modules.common import SIDE_PLATE
    from .build_line import all_lines, resolve_width_mm
    from .detect_junctions import TAIL_KEY, _world_matrix, docked_junction, origin_dock
    from .stream import path_length_m, tree_for

    scene = context.scene
    settings = obj.conveyor_line
    uid = ensure_identity(context, obj)
    M = _world_matrix(obj)  # from the channels: matrix_world is stale right after a move
    levels = scene_levels(scene)
    pts, heads = _own_points(obj)
    if not pts:
        return
    from .stream import line_speed

    try:
        surface_speed = round(float(line_speed(context, obj)), 3)  # the speed in use: a docked line runs at its master's
    except Exception:
        surface_speed = round(float(settings.speed_m_s), 3)
    if surface_speed <= 0.0:
        surface_speed = round(float(settings.speed_m_s), 3)
    width_m = resolve_width_mm(settings) / 1000.0
    half = width_m / 2.0 + SIDE_PLATE
    path = _resample(pts, 1.0)
    left_side = [(p.x - math.cos(h) * half, p.y - math.sin(h) * half) for p, h in zip(pts, heads)]
    right_side = [(p.x + math.cos(h) * half, p.y + math.sin(h) * half) for p, h in zip(pts, heads)]
    footprint = [[round(x, 3), round(y, 3)] for x, y in left_side + list(reversed(right_side))]
    try:
        floor_z = float(scene.conveyor_settings.floor_z)
    except Exception:
        floor_z = 0.0
    descriptor = {
        "version": 2, "addon": ADDON_ID, "kind": "line", "id": uid, "object": obj.name, "label": obj.name,
        "level": level_at_world(M.translation, levels),  # the floor under the origin (R10); each port says its own
        "footprint": footprint, "height_m": round(M.translation.z - floor_z, 3), "clearance_m": 0.0, "zone": None,
    }
    # R22 / R22.2: the population the line animates (its first section, as
    # warehouse_common resolves the published records), the speed in use (a
    # docked line runs at its master's), and the user's master pick.
    floor_pop = None
    try:
        from .stream import tree_for as _tree_for

        gf = _tree_for(context, obj).flow
        if gf is not None and obj.name in gf.population:
            # R22.3: a master publishes its slider (the stream's input), every
            # other line the population it animates (resolved, capped).
            master_input = gf.is_master.get(obj.name) and obj.name in gf.input_population
            value = gf.input_population[obj.name] if master_input else gf.population[obj.name]
            descriptor["population"] = round(float(value), 6)
            floor_pop = gf.floor_population.get(obj.name)
        descriptor["speed_m_s"] = surface_speed
    except Exception:
        pass
    if settings.flow_master:
        descriptor["master"] = True
    write_record(obj, SYSTEM_KEY, descriptor)
    write_record(obj, PATH_KEY, [[round(p.x, 3), round(p.y, 3), round(p.z, 3)] for p in path])
    # The two ends as ports, in the line's own frame.
    ex, ey, ez, hd = settings.end_pose
    if settings.reverse:
        start_pose, end_pose = ((ex, ey, ez), (hd + 180.0) % 360.0), ((0.0, 0.0, 0.0), 180.0)
    else:
        start_pose, end_pose = ((0.0, 0.0, 0.0), 0.0), ((ex, ey, ez), hd % 360.0)
    # Docks are geometric (the origin, the far end); ports are flow-wise: on
    # a reversed line the goods start at the far end and leave at the origin.
    # (A reversed feeder docked by its origin used to publish line_in taken.)
    taken_origin = dock_at(obj, "origin") is not None or origin_dock(context, obj) is not None or bool(settings.get(TAIL_KEY))
    taken_far = (dock_at(obj, "end") is not None or docked_junction(context, obj, 'DIVERTER' if settings.reverse else 'MERGE') is not None
                 or any(o != obj and o.conveyor_line.get(TAIL_KEY) == obj.name for o in all_lines(scene)))
    taken_start, taken_end = (taken_far, taken_origin) if settings.reverse else (taken_origin, taken_far)
    load = _load_descriptor(context, obj)
    # (A JSON string: an ID-property array may not hold a string -- the
    # first live run died on exactly that.)
    rev = _json(obj.get(REV_KEY), {})
    rev = rev if isinstance(rev, dict) else {}
    load_key = str(load.get("id", "")) + "|" + str(load.get("object", ""))
    if rev.get("key") != load_key:
        rev = {"key": load_key, "rev": int(rev.get("rev", 0) or 0) + (1 if rev.get("key") else 0)}
        obj[REV_KEY] = json.dumps(rev)
    revision = int(rev.get("rev", 0) or 0)
    try:
        rate = _delivered(context, obj) if (settings.populate or docks(obj)) else 0.0
    except Exception:
        rate = 0.0
    try:
        tree = tree_for(context, obj)
        capacity = 3600.0 * tree.speed / tree.min_spacing if tree.min_spacing > 1e-9 else 0.0
        ls = tree.members.get(obj.name)
        u_start = float(ls.offset) if ls is not None else 0.0
        u_end = u_start + path_length_m(obj)
    except Exception:
        capacity, u_start, u_end = 0.0, 0.0, float(settings.get("full_length_m", 0.0))
    from ..props.scene_settings import time_scale

    scale = time_scale(scene)
    from ..model import port_io

    ctype = loader.get_conveyor_types().get(settings.conveyor_type)
    surface = ctype.cross_section if ctype is not None else "roller"
    ports = []
    for pid, role, (pos, heading_deg), taken, u_port in (("line_in", "in", start_pose, taken_start, u_start), ("line_out", "out", end_pose, taken_end, u_end)):
        h = math.radians(heading_deg)
        handover = (pos[0] - math.sin(h) * 0.6, pos[1] + math.cos(h) * 0.6, pos[2]) if role == "in" else (pos[0] + math.sin(h) * 0.6, pos[1] - math.cos(h) * 0.6, pos[2])
        port = {"version": 2, "id": pid, "role": role, "kind": "point", "position": [round(v, 3) for v in pos], "heading_deg": round(heading_deg, 2),
                "width_m": round(width_m, 3), "surface": surface, "surface_speed_m_s": surface_speed, "load": load,
                "rate_ph": round(rate, 3), "capacity_ph": round(capacity, 1), "handover": [round(v, 3) for v in handover], "taken": bool(taken),
                "revision": revision, "time_scale": round(scale, 3), "exclusive": True,
                "accepts": list(port_io.CARRIED_KINDS),  # R19: never "long"
                "level": level_at_world(M @ Vector(pos), levels)}
        if pid == "line_in" and floor_pop is not None:
            port["max_population"] = round(float(floor_pop), 6)  # the slot grid's floor caps the line (R22.2: readers resolve the same)
        if role == "out":
            try:
                crossings = crossings_at(context, obj, u_port) if settings.populate else None
            except Exception:
                crossings = None
            if crossings is not None:
                port["phase_s"], port["period_s"] = round(float(crossings[0]), 4), round(float(crossings[1]), 4)
        ports.append(port)
    # A right-angle transfer's free side faces: anything may dock there (a
    # station, a shuttle lift, another conveyor through the + on the face).
    try:
        from .detect_junctions import _line_data
        from ..model.transfer_parts import rat_length

        _spine, segments, width_line, _starts, frames = _line_data(context, obj)
        for i, seg in enumerate(settings.segments):
            if i >= len(segments) or seg.kind != 'MODULE' or seg.module_kind != 'RAT':
                continue
            start = frames[i][0]
            length_m = segments[i].length_m
            h = start.heading
            fwd = (-math.sin(h), math.cos(h))
            right = (math.cos(h), math.sin(h))
            faces = [("left", -1.0, seg.merge_source, seg.rat_face_left_mm), ("right", 1.0, seg.merge_source_right, seg.rat_face_right_mm)]
            if seg.module_exit in ('LEFT', 'RIGHT'):  # a corner's far face: a line straight through
                faces.append(("end", 0.0, getattr(seg, "rat_source_end", ""), getattr(seg, "rat_face_end_mm", 0.0)))
            for side, sd, name, face_mm in faces:
                if side.upper() == seg.module_exit:
                    continue  # the line's own path leaves here
                if side == "end":
                    px, py = start.x + fwd[0] * length_m, start.y + fwd[1] * length_m
                    heading_deg = math.degrees(h) % 360.0  # outward: straight on
                else:
                    dx = sd * (width_line / 2.0 + SIDE_PLATE)
                    px, py = start.x + right[0] * dx + fwd[0] * length_m / 2.0, start.y + right[1] * dx + fwd[1] * length_m / 2.0
                    heading_deg = math.degrees(h - sd * math.pi / 2.0) % 360.0  # outward
                face_w = (face_mm / 1000.0 - 0.04) if face_mm > 0 else width_m
                face = {"version": 2, "id": f"rat{i + 1}_{side}", "role": "io", "kind": "point", "position": [round(px, 3), round(py, 3), round(start.z, 3)],
                        "heading_deg": round(heading_deg, 2), "width_m": round(face_w, 3), "surface": "popup_belt", "surface_speed_m_s": surface_speed,
                        "load": load, "rate_ph": round(rate, 3), "capacity_ph": round(capacity, 1), "taken": bool(name), "revision": revision,
                        "time_scale": round(scale, 3), "exclusive": True, "accepts": list(port_io.CARRIED_KINDS),
                        "level": level_at_world(M @ Vector((px, py, start.z)), levels)}
                if name:  # R22.1: a taken face is a boundary of the stream graph, at the transfer's centre
                    face["u_m"] = round(junction_ports.module_u_m(context, obj, i), 3)
                    if floor_pop is not None:
                        face["max_population"] = round(float(floor_pop), 6)  # its section's cap, as the line's
                ports.append(face)
    except Exception:
        pass
    # R22.1: every taken merge / divert face is a port of its own (operators/junction_ports.py).
    try:
        jports = junction_ports.junction_ports(context, obj, M, levels)
        if floor_pop is not None:
            for jport in jports:
                jport["max_population"] = round(float(floor_pop), 6)  # the section from here on: the line's cap
        ports += jports
    except Exception as exc:
        print(f"conveyor: junction ports of {obj.name} failed: {exc!r}")
    # R22.6: every buffer's exit, with its Output % and how many it holds.
    try:
        bports = junction_ports.buffer_ports(context, obj, levels)
        if floor_pop is not None:
            for bport in bports:
                bport["max_population"] = round(float(floor_pop), 6)  # the section after it: the line's cap too
        ports += bports
    except Exception as exc:
        print(f"conveyor: buffer ports of {obj.name} failed: {exc!r}")
    write_record(obj, PORTS_KEY, ports)
    junction_ports.stamp(obj)
    try:
        from .obstacles import write_hits

        write_hits(context, obj)  # R13: the goods envelope against the scene's wh_obstacles
    except Exception:
        pass


def register_addon_entry():
    """Our entry in window_manager["wh_addons"] (contract §6): written from a
    timer after enable and again on load_post (the window manager is not
    saved and not reachable in register())."""
    try:
        from ..config import loader

        wm = bpy.context.window_manager
        data = _json(wm.get(ADDONS_KEY, ""), {})
        if not isinstance(data, dict):
            data = {}
        data[ADDON_ID] = {"version": _version(), "contract": CONTRACT, "add": "conveyor.new_line",
                          "kinds": [{"kind": "line", "label": "Conveyor line", "presets": list(loader.get_offered_types().keys())}]}  # line types: a module is a piece, not a preset
        wh_records.write_record(wm, ADDONS_KEY, data)
    except Exception:
        pass
    return None


def remove_addon_entry() -> None:
    """On unregister (R11): our entry leaves the registry; the other add-ons' entries stay."""
    try:
        wm = bpy.context.window_manager
        data = _json(wm.get(ADDONS_KEY, ""), {})
        if isinstance(data, dict) and ADDON_ID in data:
            del data[ADDON_ID]
            wh_records.write_record(wm, ADDONS_KEY, data)
    except Exception:
        pass


# ----------------------------------------------------------- the panel --

def _buffer_before_end(obj) -> bool:
    segs = obj.conveyor_line.segments
    order = range(len(segs)) if obj.conveyor_line.reverse else range(len(segs) - 1, -1, -1)
    for j in order:
        if segs[j].kind == 'MODULE' and segs[j].module_kind == 'BUFFER':
            return True
        if segs[j].kind == 'MODULE':
            return False
    return False


def draw_port(layout, context, obj) -> None:
    """Where the line is docked, what it lost or waits for, the capacity
    of the system it feeds, and a hint with a Dock button when a free end
    sits near a free port."""
    from ..ui.panels import _alert, _dim_label
    from .detect_junctions import _world_matrix, docked_junction, flow_reversed, origin_dock

    from ..ui.panels import SHOW_THROUGHPUT_PHYSICS

    scene = context.scene
    for anchor in ("origin", "end"):
        hit = linked_at(context, obj, anchor)
        if hit is None:
            continue
        system, port, role, _ = hit
        row = layout.row(align=True)
        what = "Starts at" if role == "out" or (role == "io" and anchor == "origin" and not flow_reversed(obj)) else "Feeds"
        # Where it is docked, never a rate (the Population row says how full the stream is).
        row.label(text=f"{what} {system.name} · {port.get('id')}", icon='LINKED')
        dock = dock_at(obj, anchor) or {}
        if dock.get("by"):
            _dim_label(layout, f"Docked by {dock['by']}")
        if not SHOW_THROUGHPUT_PHYSICS:
            continue  # a rack that takes less holds the stream back, silently
        requested, rate = _rate(context, obj), _delivered(context, obj)
        from .populate import populate_item_length

        capacity = capacity_of(port, populate_item_length(context, obj), float(obj.conveyor_line.speed_m_s))
        if what == "Feeds" and capacity > 0.0 and requested > capacity + 0.5:
            _alert(layout, f"{system.name} takes {capacity:,.0f}/h, this line brings {requested:,.0f}/h")
            if not _buffer_before_end(obj):
                op = layout.operator("conveyor.add_buffer_before_port", text=f"Add buffer before {system.name}", icon='ADD')
                op.line = obj.name
    n = note(obj)
    if n is not None:
        row = layout.row(align=True)
        row.alert = n.get("kind") != "taken"
        row.label(text=str(n.get("text", "")), icon='UNLINKED' if n.get("kind") == "lost" else 'ERROR')
        if n.get("kind") == "taken" and not n.get("foreign"):
            op = row.operator("conveyor.port_take_over", text="Take over", icon='LINKED')
            op.line, op.system, op.port, op.anchor = obj.name, str(n.get("system", "")), str(n.get("port", "")), str(n.get("anchor", "origin"))
        op = row.operator("conveyor.port_note_clear", text="", icon='X')
        op.line = obj.name
    # Hints for free ends near free ports.
    if not systems(scene):
        return
    reach = _reach(context)
    ends = []
    if dock_at(obj, "origin") is None and origin_dock(context, obj) is None and not obj.conveyor_line.get("conveyor_tail_target"):
        ends.append(("origin", _world_matrix(obj) @ Vector((0.0, 0.0, 0.0)), "in" if flow_reversed(obj) else "out"))
    if not flow_reversed(obj) and dock_at(obj, "end") is None and docked_junction(context, obj) is None:
        pose = _end_pose(context, obj)
        if pose is not None:
            ends.append(("end", pose[2], "in"))
    for anchor, point, role in ends:
        cands = [c for c in scan_ports(scene, point, role, HINT_M, exclude=obj) if c["d"] > reach or c["scaled"] or c["refused"] or c["holder"] is not None]
        if not cands:
            continue
        c = cands[0]
        system, port = c["system"], c["port"]
        if c["scaled"]:
            _alert(layout, f"{system.name} is scaled; sizes are 1:1 metres")
        elif c["refused"]:
            from ..model import port_io

            _dim_label(layout, f"{port.get('id')} on {system.name} delivers {port_io.load_kind(port.get('load'))} loads: not carried on a conveyor")
        elif c["holder"] is not None:
            _dim_label(layout, f"{port.get('id')} on {system.name} is taken by {holder_name(c['holder'])}")
        else:
            row = layout.row(align=True)
            row.label(text=f"{c['d']:.1f} m from {system.name} · {port.get('id')} — move within {reach:.1f} m, or", icon='INFO')
            op = row.operator("conveyor.port_dock", text="Dock", icon='LINKED')
            op.line, op.system, op.port, op.anchor = obj.name, system.name, str(port.get("id")), anchor


# ------------------------------------------------------------ operators --

def _line_by_name(context, name: str):
    obj = context.scene.objects.get(name)
    return obj if is_line(obj) else None


def dock_line_at(context, obj, system, port, anchor: str) -> bool:
    """Snap `anchor` of `obj` onto the port (the Dock button): an origin
    takes the port's role (reversed for an "in" port), an end aims in."""
    from .detect_junctions import _place_origin, _remember_matrix, _world_matrix, sync_feeder
    from ..props.line_settings import suspended_rebuild

    pos, heading, _handover = world_port(system, port)
    role = str(port.get("role", "out"))
    if anchor == "origin":
        wants_reverse = role == "in"
        if role != "io" and bool(obj.conveyor_line.reverse) != wants_reverse:
            with suspended_rebuild():
                obj.conveyor_line.reverse = wants_reverse
        _place_origin(obj, dock_pos(port, pos, _world_matrix(obj).translation.z), heading + (math.pi if wants_reverse else 0.0))
    else:
        pose = _end_pose(context, obj)
        if pose is None:
            return False
        end, end_local, end_world = pose
        _aim_end(context, obj, end, end_local, end_world, dock_pos(port, pos, end_world.z), heading)
    _remember_matrix(obj)
    sync_feeder(context, obj)
    return dock_at(obj, anchor) is not None


class CONVEYOR_OT_port_dock(bpy.types.Operator):
    bl_idname = "conveyor.port_dock"
    bl_label = "Dock at Port"
    bl_description = "Snap this end of the line onto the nearby port of that system"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    line: bpy.props.StringProperty(options={'SKIP_SAVE'})
    system: bpy.props.StringProperty(options={'SKIP_SAVE'})
    port: bpy.props.StringProperty(options={'SKIP_SAVE'})
    anchor: bpy.props.StringProperty(default="origin", options={'SKIP_SAVE'})

    def execute(self, context):
        obj = _line_by_name(context, self.line)
        system = context.scene.objects.get(self.system)
        port = port_by_id(system, self.port) if is_system(system) else None
        if obj is None or port is None:
            self.report({'WARNING'}, "That port is gone")
            return {'CANCELLED'}
        if holder_of(context.scene, system, self.port, exclude=obj) is not None:
            self.report({'WARNING'}, f"{self.port} is taken")
            return {'CANCELLED'}
        if not dock_line_at(context, obj, system, port, self.anchor):
            self.report({'WARNING'}, f"{obj.name} did not dock at {self.system} · {self.port}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"{obj.name} docked at {self.system} · {self.port}")
        return {'FINISHED'}


class CONVEYOR_OT_port_take_over(bpy.types.Operator):
    bl_idname = "conveyor.port_take_over"
    bl_label = "Take Over Port"
    bl_description = "Undock the line holding this port and dock this line there instead (undo restores both)"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    line: bpy.props.StringProperty(options={'SKIP_SAVE'})
    system: bpy.props.StringProperty(options={'SKIP_SAVE'})
    port: bpy.props.StringProperty(options={'SKIP_SAVE'})
    anchor: bpy.props.StringProperty(default="origin", options={'SKIP_SAVE'})

    def execute(self, context):
        from .detect_junctions import _rebuild

        obj = _line_by_name(context, self.line)
        system = context.scene.objects.get(self.system)
        port = port_by_id(system, self.port) if is_system(system) else None
        if obj is None or port is None:
            return {'CANCELLED'}
        holder = holder_of(context.scene, system, self.port, exclude=obj)
        if holder is not None and not is_line(holder):
            # Another add-on's record (one writer per record, R14): the port is freed in that add-on.
            self.report({'WARNING'}, f"{self.port} is held by {holder_name(holder)}: free it there first")
            return {'CANCELLED'}
        if holder is not None:
            for anchor, dock in docks(holder).items():
                if dock.get("port") == self.port and (dock.get("system") == system.name or dock.get("system_id") == system_id(system)):
                    _forget(holder, anchor)
            write_links(context, holder)
            set_note(holder, "lost", f"{self.port} taken over by {obj.name}", system.name, self.port, "origin")
            _rebuild(context, holder)
        clear_note(obj)
        if not dock_line_at(context, obj, system, port, self.anchor):
            return {'CANCELLED'}
        return {'FINISHED'}


class CONVEYOR_OT_port_note_clear(bpy.types.Operator):
    bl_idname = "conveyor.port_note_clear"
    bl_label = "Clear"
    bl_description = "Dismiss this note"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    line: bpy.props.StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        obj = _line_by_name(context, self.line)
        if obj is not None:
            clear_note(obj)
        return {'FINISHED'}


class CONVEYOR_OT_add_buffer_before_port(bpy.types.Operator):
    bl_idname = "conveyor.add_buffer_before_port"
    bl_label = "Add Buffer Before the System"
    bl_description = "A 6 m accumulation buffer at the end of this line, Out rate Auto (what the system takes): the pile-up is modelled where it happens"
    bl_options = {'REGISTER', 'UNDO'}

    line: bpy.props.StringProperty(options={'SKIP_SAVE'})
    length_mm: bpy.props.FloatProperty(default=6000.0, min=1500.0)

    def execute(self, context):
        from ..props.line_settings import suspended_rebuild
        from .build_line import build_line

        obj = _line_by_name(context, self.line) or (context.active_object if is_line(context.active_object) else None)
        if obj is None:
            return {'CANCELLED'}
        settings = obj.conveyor_line
        segs = settings.segments
        last = len(segs) - 1 if not settings.reverse else 0  # the piece at the flow end
        if segs[last].kind != 'STRAIGHT' or segs[last].length_mm < self.length_mm + 150.0:
            self.report({'WARNING'}, f"The last piece must be a straight at least {(self.length_mm + 150) / 1000:.1f} m long")
            return {'CANCELLED'}
        with suspended_rebuild():
            segs[last]["length_mm"] = segs[last].length_mm - self.length_mm
            seg = segs.add()
            seg.kind = 'MODULE'
            seg.module_kind = 'BUFFER'
            seg["length_mm"] = self.length_mm
            seg.buffer_out_mode = 'AUTO'
            if settings.reverse:
                segs.move(len(segs) - 1, 0)
                settings.active_segment_index = 0
            else:
                settings.active_segment_index = len(segs) - 1
        build_line(context, obj)
        self.report({'INFO'}, f"Buffer of {self.length_mm / 1000:.1f} m before the end of {obj.name}")
        return {'FINISHED'}


classes = (CONVEYOR_OT_port_dock, CONVEYOR_OT_port_take_over, CONVEYOR_OT_port_note_clear, CONVEYOR_OT_add_buffer_before_port)


@bpy.app.handlers.persistent
def _on_load(_path=None):
    _systems_seen.clear()
    _cache.clear()
    register_addon_entry()


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.app.timers.register(register_addon_entry, first_interval=0.3)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    try:
        if bpy.app.timers.is_registered(register_addon_entry):
            bpy.app.timers.unregister(register_addon_entry)  # disabled within 0.3 s of enabling: no late entry
    except Exception:
        pass
    remove_addon_entry()
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
