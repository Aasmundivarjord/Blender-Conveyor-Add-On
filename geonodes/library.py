"""Pre-built node groups shipped with the extension, so the first "New
line" appends a tree in a fraction of a second instead of building it node
by node (20 s for the first roller line on Blender 5.2).

The Python builders stay the source of truth: a build script, run in each
supported Blender series, builds every tree with them and writes
geonodes/library/conveyor_nodes-<major>.<minor>.blend plus its .json (the
TREE_VERSION of each). At runtime `builder_common.get_or_create_tree` asks
here first and appends from the newest library written by this Blender
series or an older one -- never a newer one, whose trees may not read back.
A tree is appended only when the shipped set matches the code's versions
exactly (every tree, as a set: the line trees link the shipped Populate and
Frame groups, mixing shipped and built copies would cross-link stale
interfaces). Any mismatch -- a builder edited without regenerating the
libraries, no library this Blender can read -- falls back to building,
exactly as before.

Appending brings dependencies along (the shared groups, the sensor and
highlight materials). A name that already exists in the file comes in as
"name.001": for node groups the shipped copy wins (users of the old tree
are remapped to it, the old one is removed, the copy takes the name); for
materials the existing one wins (a user's restyling survives).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import bpy

LIBRARY_DIR = Path(__file__).resolve().parent / "library"
_SUFFIX = re.compile(r"\.\d{3}$")
_LIBRARY_NAME = re.compile(r"^conveyor_nodes-(\d+)\.(\d+)\.json$")
_index_cache: dict = {}


def library_paths(series=None) -> tuple:
    """(blend, json) of the library a Blender series (major, minor) writes; this Blender's by default."""
    major, minor = (series or bpy.app.version)[:2]
    stem = f"conveyor_nodes-{major}.{minor}"
    return LIBRARY_DIR / f"{stem}.blend", LIBRARY_DIR / f"{stem}.json"


def index() -> dict:
    """{tree name: shipped TREE_VERSION} of the library this Blender appends
    from: the newest written by its own series or an older one. {} when there
    is none (a library written by a NEWER series is never used: its node trees
    may not read back correctly, the trees are built from the code instead)."""
    if "data" not in _index_cache:
        data, blend = {}, None
        try:
            running = tuple(bpy.app.version[:2])
            best = None
            for path in LIBRARY_DIR.glob("conveyor_nodes-*.json"):
                m = _LIBRARY_NAME.match(path.name)
                if m is None:
                    continue
                series = (int(m.group(1)), int(m.group(2)))
                lib_blend, _lib_json = library_paths(series)
                if series > running or not lib_blend.is_file():
                    continue
                if best is None or series > best[0]:
                    best = (series, path, lib_blend)
            if best is not None:
                data = json.loads(best[1].read_text(encoding="utf-8")).get("trees", {})
                blend = best[2]
        except Exception:
            data, blend = {}, None
        _index_cache["data"] = data
        _index_cache["blend"] = blend
    return _index_cache["data"]


def provides(wanted) -> bool:
    """True when the library ships every (name, version) in `wanted`."""
    shipped = index()
    return bool(shipped) and all(shipped.get(name) == version for name, version in wanted)


def _base_name(name: str) -> str:
    return _SUFFIX.sub("", name)


def append(wanted) -> bool:
    """Appends every tree in `wanted` ([(name, version), ...]) from the
    library, as one consistent set. Returns False (nothing changed) when
    the library does not ship exactly these versions or cannot be read."""
    if not provides(wanted):
        return False
    names = [name for name, _v in wanted]
    trees_before = {ng.as_pointer() for ng in bpy.data.node_groups}
    mats_before = {m.as_pointer() for m in bpy.data.materials}
    try:
        with bpy.data.libraries.load(str(_index_cache["blend"]), link=False) as (data_from, data_to):
            missing = [n for n in names if n not in data_from.node_groups]
            if missing:
                return False
            data_to.node_groups = list(names)
    except Exception:
        return False
    new_trees = [ng for ng in bpy.data.node_groups if ng.as_pointer() not in trees_before]
    new_mats = [m for m in bpy.data.materials if m.as_pointer() not in mats_before]
    # Shipped node groups replace same-named ones (stale or not: the set is
    # consistent only with itself); existing materials replace shipped ones.
    for ng in new_trees:
        base = _base_name(ng.name)
        old = bpy.data.node_groups.get(base)
        if old is not None and old != ng:
            old.user_remap(ng)
            bpy.data.node_groups.remove(old)
        if ng.name != base:
            ng.name = base
    for mat in new_mats:
        base = _base_name(mat.name)
        existing = bpy.data.materials.get(base)
        if existing is not None and existing != mat:
            mat.user_remap(existing)
            bpy.data.materials.remove(mat)
        elif mat.name != base:
            mat.name = base
    return all(bpy.data.node_groups.get(name) is not None for name in names)


def append_one(name: str, version: int):
    """A single tree from the library (its dependencies ride along), or
    None. Used by get_or_create_tree for a tree nobody has built yet."""
    from .frame import NODE_GROUP_NAME as FRAME, TREE_VERSION as FRAME_V
    from .populate import NODE_GROUP_NAME as POPULATE, TREE_VERSION as POPULATE_V

    wanted = [(name, version)]
    # The shared groups must match too, or the appended tree would carry
    # copies that disagree with the code (see the module docstring).
    for shared_name, shared_version in ((FRAME, FRAME_V), (POPULATE, POPULATE_V)):
        if shared_name != name:
            wanted.append((shared_name, shared_version))
    if not provides(wanted):
        return None
    return bpy.data.node_groups.get(name) if append(wanted) else None
