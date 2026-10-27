"""
Warehouse Common: the pure contract maths every warehouse add-on shares (interop contract
v2.1 and later).

Pure Python (math, json, uuid, hashlib only): no bpy, no numpy, so it unit-tests anywhere and
runs inside any add-on. It is VENDORED, never installed: each add-on carries a copy as
`<package>/_wh/` (with the vendoring tool of the Warehouse Common source) and imports it relatively, `from ._wh import records`.
Blender extensions cannot depend on each other, so this is how the suite shares code. Do not
edit a vendored copy; change the source here, bump VERSION, re-vendor.
"""

VERSION = "0.6.9"
CONTRACT = "2.1"

# Custom property names of the contract (records are JSON strings, markers plain values)
SYSTEM_KEY = "wh_system"
PORTS_KEY = "wh_ports"
PORT_LINKS_KEY = "wh_port_links"
PORT_LINK_KEY = "wh_port_link"          # v1, a dict; kept for v1 readers
LOAD_KEY = "wh_load"
PATH_KEY = "wh_path"
OBSTACLES_KEY = "wh_obstacles"
LEVELS_KEY = "wh_levels"
ZONE_KEY = "wh_zone"
ADDONS_KEY = "wh_addons"                # window manager, JSON dict keyed by add-on id
FLOOR_KEY = "wh_floor"                  # marker: bool
TIME_SCALE_KEY = "wh_time_scale"        # marker on the SCENE: float, operation s per scene s
MATERIAL_KEY = "wh_material"            # palette id on a material datablock (R9)
SYNC_BUSY_KEY = "wh_sync_busy"          # bpy.app.driver_namespace flag during a deferred pass (R5)
LOADS_COLLECTION = "Warehouse Loads"

from . import records, frames, geometry, levels, palette, ops, contrast, loads, longload, ports, selfcheck  # noqa: E402,F401
