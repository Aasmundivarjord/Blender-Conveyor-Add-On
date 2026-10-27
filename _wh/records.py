"""
Records: how every `wh_*` record crosses the add-on boundary (contract v2.1, R2).

RECORDS (dicts and lists: wh_system, wh_ports, wh_port_links, wh_load, wh_path, wh_obstacles,
wh_levels, wh_zone) are compact JSON strings in one custom property each. Readers also accept
IDProperty groups and arrays, which files saved before v2.1 carry, forever. SCALAR MARKERS
(wh_floor, the scene's wh_time_scale) are plain values and do not go through here. The v1
`wh_port_link` stays a dict until no v1 reader is left.
"""

import json
import uuid

SUPPORTED_MAJOR = 2


def to_plain(value):
    """IDProperty groups and arrays -> dicts and lists, recursively."""
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "to_list"):
        return value.to_list()
    if isinstance(value, dict):
        return {k: to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(v) for v in value]
    return value


def read_record(raw, default=None):
    """A record as plain Python, from a JSON string or an IDProperty; `default` when it is
    missing, empty or malformed (a reader never raises on someone else's data)."""
    if raw is None:
        return default
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        if not raw:
            return default
        try:
            value = json.loads(raw)
        except ValueError:
            return default
        return default if value is None else value
    return to_plain(raw)


def dumps(value):
    """The one encoding writers use: compact JSON."""
    return json.dumps(value, separators=(",", ":"))


def write_record(target, key, value):
    """Write `value` as a JSON string under `key` of `target` (an ID, or any mapping) only when
    it differs from what is there; True when written. Skipping equal writes keeps the
    depsgraph quiet (R5)."""
    text = dumps(value)
    if target.get(key) == text:
        return False
    target[key] = text
    return True


def is_supported(record, major=SUPPORTED_MAJOR):
    """Readers ignore records of a higher major version than they know (missing = 1)."""
    if not isinstance(record, dict):
        return False
    try:
        return int(float(record.get("version", 1))) <= major
    except (TypeError, ValueError):
        return False


def supported(records, major=SUPPORTED_MAJOR):
    """The entries of a record list a reader may use."""
    return [r for r in (records or []) if is_supported(r, major)]


def new_system_id():
    """A `wh_system.id`: uuid4, written once, kept through renames and file reloads."""
    return str(uuid.uuid4())


def duplicate_fixes(records):
    """The v2 duplicate rule. `records` = [(object name, recorded `object`, id)]; returns the
    names that must get a NEW id: of several objects sharing one id, those whose name differs
    from the name recorded in their descriptor (the Shift+D copies). A lone object with a
    changed name is a rename and keeps its id. If every holder was renamed, the first keeps it."""
    by_id = {}
    for name, recorded, sid in records:
        by_id.setdefault(sid, []).append((name, recorded))
    out = []
    for _sid, group in by_id.items():
        if len(group) < 2:
            continue
        copies = [name for name, recorded in group if name != recorded]
        if len(copies) == len(group):
            copies = copies[1:]
        out.extend(copies)
    return out
