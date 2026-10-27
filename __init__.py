"""Path-Driven Conveyor System, v2.

Registration entry point. Each submodule owns one concern and exposes
register()/unregister(); this file stays a plain wiring list.
"""

ADDON_PACKAGE = __package__ or __name__

from .props import preferences as _preferences
from .props import scene_settings as _scene_settings
from .props import line_settings as _line_settings
from .operators import build_line as _build_line
from .operators import new_line as _new_line
from .operators import segments as _segments
from .operators import build_mode as _build_mode
from .operators import detect_junctions as _detect_junctions
from .operators import junction_edit as _junction_edit
from .operators import pick_item as _pick_item
from .operators import ports as _ports
from .operators import floors as _floors
from .operators import public_api as _public_api
from .operators import stands as _stands
from .operators import checks as _checks
from .ui import panels as _panels
from .ui import gizmos as _gizmos
from .ui import segment_edit as _segment_edit
from .ui import flow_markers as _flow_markers
from .ui import stands as _stand_buttons
from .ui import line_map as _line_map
from .ui import piece_library as _piece_library
from .ui import dimensions as _dimensions
from .ui import sidebar as _sidebar

_modules = (
    _preferences,
    _scene_settings,
    _line_settings,
    _build_line,
    _new_line,
    _segments,
    _build_mode,
    _detect_junctions,
    _junction_edit,
    _pick_item,
    _ports,
    _floors,
    _public_api,
    _stands,
    _checks,
    _line_map,
    _piece_library,
    _panels,
    _gizmos,
    _segment_edit,
    _flow_markers,
    _stand_buttons,
    _dimensions,
    _sidebar,
)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
