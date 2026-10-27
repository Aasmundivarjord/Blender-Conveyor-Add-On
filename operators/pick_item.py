"""Populate in one click (user request 2026-10-05): turning Populate on, or
pressing its Pick button, goes straight into an eyedropper over the 3D
viewport -- click the object the line should carry and it is placed, Esc
keeps the shipped placeholder totes. No field to find, no search list.

The eyedropper is a plain modal operator: it finds the 3D View region under
the mouse (it is usually started from the sidebar, whose own region cannot
ray-cast), casts a ray through the evaluated scene and reads the object it
hit. Conveyor lines are skipped -- a click on a tote riding a line hits the
LINE (the tote is an instance of its geometry), so the status bar asks for a
loose object instead. Orbit / zoom keep working while picking.
"""
from __future__ import annotations

import bpy
from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d
from mathutils import Vector

PASS_THROUGH = {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM',
                'MOUSEROTATE', 'MOUSEZOOM', 'MOUSEPAN', 'NDOF_MOTION'}


def _active_line(context):
    obj = context.active_object
    if obj is None or obj.type != 'CURVES' or not obj.conveyor_line.is_conveyor_line:
        return None
    return obj


def _view_region_under(context, event):
    """(area, region) of the 3D View WINDOW region under the mouse, or (None, None)."""
    x, y = event.mouse_x, event.mouse_y
    for area in context.window.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for region in area.regions:
            if region.type == 'WINDOW' and region.x <= x < region.x + region.width and region.y <= y < region.y + region.height:
                return area, region
    return None, None


def object_under_mouse(context, event):
    """The scene object under the mouse in a 3D View, else None."""
    area, region = _view_region_under(context, event)
    if region is None or region.data is None:
        return None
    rv3d = region.data
    xy = Vector((event.mouse_x - region.x, event.mouse_y - region.y))
    origin = region_2d_to_origin_3d(region, rv3d, xy)
    direction = region_2d_to_vector_3d(region, rv3d, xy)
    depsgraph = context.evaluated_depsgraph_get()
    hit, _loc, _normal, _index, obj, _matrix = context.scene.ray_cast(depsgraph, origin, direction)
    if not hit or obj is None:
        return None
    return obj.original if hasattr(obj, "original") else obj


def _is_line(obj) -> bool:
    return obj is not None and obj.type == 'CURVES' and obj.conveyor_line.is_conveyor_line


def is_warehouse_system(obj) -> bool:
    """A rack / system another warehouse add-on built, publishing its
    docking ports and loads (custom property wh_ports, as the Racks add-on
    writes it)."""
    try:
        return obj is not None and "wh_ports" in obj
    except Exception:
        return False


def apply_port_load(context, line, system, port, role: str = "out") -> tuple[bool, bool, str]:
    """The line carries the load `port` delivers (its object, made by the
    system's own operator when it is missing -- deferred to a timer),
    travelling the way the load is published to travel, at the port's rate
    for the line's `role` when the line has no throughput of its own (an io
    port's `rate_in_ph` for an in line, model/port_io). Returns (changed,
    load applied, message)."""
    from ..model import port_io
    from ..props.line_settings import suspended_rebuild
    from .populate import wh_load

    load = port.get("load") if isinstance(port, dict) else None
    if not isinstance(load, dict):
        return False, True, f"{system.name}: port {port.get('id') if isinstance(port, dict) else '?'} publishes no load"
    if not port_io.carries_load(load):  # R19: e.g. "long" bundles for a cantilever rack; done: never retried
        return False, True, f"{system.name}: its {port_io.load_kind(load)} loads are not carried on a conveyor"
    item = bpy.data.objects.get(str(load.get("object", "")))
    if item is None and load.get("id"):
        from .public_api import find_load_object

        item = find_load_object(load["id"])  # built under the canonical id (warehouse_common 0.6.6)
    # A custom load (Racks R16: kind "custom", make null) is an object of the
    # user's own: taken as it is, never built; its published dims and axis
    # ride on the object for the stream (populate.wh_load) when it has none.
    custom = load.get("kind") == "custom" or ("make" in load and load.get("make") is None)
    if item is None and custom:
        return False, False, f"{system.name}: its custom load '{load.get('object') or load.get('id')}' is not in the file"
    if custom and wh_load(item) is None:
        try:
            from .._wh import records as wh_records

            # R2: a JSON string (Racks 0.17.0 and later read both forms; 2.8.1, 2026-10-12).
            wh_records.write_record(item, "wh_load", {k: v for k, v in load.items() if v is not None and isinstance(v, (str, int, float, bool))})
        except Exception:
            pass
    from .._wh import ops as wh_ops

    # (hasattr on bpy.ops is ALWAYS True, it hands out a proxy for any name: operator_exists checks the registry, R7.)
    if item is None and load.get("id") and wh_ops.operator_exists(bpy.ops, "warehouse.make_load"):
        # The other add-on builds the load's mesh: never from inside our
        # handler or an update callback (it re-entered itself through our
        # sync, round-4 case 9). A timer makes it and re-syncs the line.
        _defer_make_load(str(load["id"]), line.name, system.name, str(port.get("id", "")))
        return False, False, f"{system.name}: making its load {load.get('object') or load['id']}"
    if item is None:
        return False, False, f"{system.name}: its load '{load.get('object') or load.get('id')}' is not in the file"
    settings = line.conveyor_line
    axis = load.get("forward_axis")
    changed = False
    with suspended_rebuild():
        if not settings.populate:
            settings.populate = True
            changed = True
        if axis in ('X', 'Y') and settings.populate_forward_axis != axis:
            settings.populate_forward_axis = axis
            changed = True
        rate = port_io.rate_ph(port, role, None, float(settings.speed_m_s))  # R22: population x speed over the load's length
        if rate:
            # The line carries what the port delivers (flow kept: its Population at the line's speed).
            from ..model.public_api import population_pct_for_rate

            pct = population_pct_for_rate(rate, port_io.load_length_m(port) or 0.6, abs(float(settings.speed_m_s)))
            if abs(float(settings.population_pct) - pct) > 0.05:
                settings.population_pct = pct
                changed = True
    if settings.populate_item != item:
        settings.populate_item = item  # seeds the spacing from its length and rebuilds
        changed = True
    return changed, True, f"{line.name} carries {item.name} from {system.name} ({port.get('id', 'port')}, {float(settings.population_pct):.0f} %)"


_pending_loads: set = set()


def _defer_make_load(load_id: str, line_name: str, system_name: str = "", port_id: str = "") -> None:
    """The other add-on builds the load on a timer; then the line takes it:
    from `port` of `system` when the eyedropper picked them (a tote rack or
    flow rack face is no dock, so the dock re-sync below never applied it),
    and through its docks."""
    key = (load_id, line_name)
    if key in _pending_loads:
        return
    _pending_loads.add(key)

    def run():
        _pending_loads.discard(key)
        try:
            bpy.ops.warehouse.make_load(load_id=load_id)
        except Exception:
            pass
        line = bpy.data.objects.get(line_name)
        if line is None or not _is_line(line):
            return None
        message = ""
        system = bpy.data.objects.get(system_name) if system_name else None
        if system is not None and port_id:
            from .ports import port_by_id

            port = port_by_id(system, port_id)
            if port is not None:
                _changed, done, message = apply_port_load(bpy.context, line, system, port)
                if not done:
                    message = ""
        from .detect_junctions import sync_feeder

        sync_feeder(bpy.context, line)  # the load exists now: the docks apply it
        if message:
            try:
                bpy.context.workspace.status_text_set(message)
            except Exception:
                pass
            print(f"conveyor: {message}")
        return None

    bpy.app.timers.register(run, first_interval=0.05)


def populate_from_system(context, line, system) -> str:
    """The eyedropper on a warehouse system: the line carries what the
    system's port nearest its start delivers -- an "out" port before an
    "in" one at the same spot (a crane aisle has both at its delivery
    end). (User, 2026-10-10: "select the Rack module and be auto-populated
    with what it brings into the system".) Returns the status-bar message."""
    from .ports import port_distance, ports_of

    ports = [p for p in ports_of(system) if isinstance(p.get("load"), dict)]
    if not ports:
        return f"{system.name} publishes no loads"
    origin = line.matrix_world.translation

    def distance(port):
        return port_distance(system, port, origin)  # a face port: to its segment, not the rack's origin

    outs = [p for p in ports if p.get("role") == "out"]
    port = min(ports, key=distance)
    if outs:
        best_out = min(outs, key=distance)
        if distance(best_out) <= distance(port) + 1.0:
            port = best_out
    _changed, _done, message = apply_port_load(context, line, system, port)
    return message


class CONVEYOR_OT_pick_item(bpy.types.Operator):
    bl_idname = "conveyor.pick_item"
    bl_label = "Pick Item to Transport"
    bl_description = ("Turn Populate on and click, in the viewport, the object this line should carry. "
                      "Esc or a click on nothing keeps the placeholder totes")
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _active_line(context) is not None

    def invoke(self, context, event):
        obj = _active_line(context)
        self._line = obj.name
        self._hover = None
        settings = obj.conveyor_line
        if not settings.populate:
            # Placeholders appear right away; the pick replaces them. Batched,
            # or the checkbox's own update would start a second eyedropper.
            from ..props.line_settings import context_for, suspended_rebuild
            from .build_line import build_line

            with suspended_rebuild():
                settings.populate = True
            build_line(context_for(context, obj), obj)
        context.window_manager.modal_handler_add(self)
        context.window.cursor_modal_set('EYEDROPPER')
        self._status(context, "Click the object to transport  ·  Esc: keep the placeholder totes")
        return {'RUNNING_MODAL'}

    @staticmethod
    def _status(context, text: str) -> None:
        context.workspace.status_text_set(text)

    def _finish(self, context, message: str = "", warning: bool = False):
        context.window.cursor_modal_restore()
        self._status(context, None)
        if message:
            self.report({'WARNING'} if warning else {'INFO'}, message)
        for area in context.window.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}

    def modal(self, context, event):
        obj = bpy.data.objects.get(self._line)
        if obj is None or not _is_line(obj):
            return self._finish(context)
        if event.type in PASS_THROUGH:
            return {'PASS_THROUGH'}
        if event.type == 'MOUSEMOVE':
            hit = object_under_mouse(context, event)
            if hit is not self._hover:
                self._hover = hit
                if hit is None:
                    self._status(context, "Click the object to transport  ·  Esc: keep the placeholder totes")
                elif _is_line(hit):
                    self._status(context, f"{hit.name} is a conveyor line -- click a loose object (a tote, carton, pallet)")
                elif is_warehouse_system(hit):
                    self._status(context, f"Click to carry what {hit.name} delivers  ·  Esc: keep the placeholder totes")
                else:
                    self._status(context, f"Click to transport {hit.name}  ·  Esc: keep the placeholder totes")
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            hit = object_under_mouse(context, event)
            if hit is None:
                return self._finish(context, "Nothing picked: the line carries the placeholder totes")
            if _is_line(hit):
                self._status(context, f"{hit.name} is a conveyor line -- click a loose object")
                return {'RUNNING_MODAL'}
            if hit == obj:
                return {'RUNNING_MODAL'}
            if is_warehouse_system(hit):
                message = populate_from_system(context, obj, hit)
                return self._finish(context, message, warning=obj.conveyor_line.populate_item is None)
            obj.conveyor_line.populate_item = hit  # seeds the spacing from its length and rebuilds
            return self._finish(context, f"{obj.name} carries {hit.name}")
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            return self._finish(context)
        return {'RUNNING_MODAL'}


class CONVEYOR_OT_clear_item(bpy.types.Operator):
    bl_idname = "conveyor.clear_item"
    bl_label = "Use Placeholder Totes"
    bl_description = "Carry the shipped placeholder totes and cartons again instead of the picked object"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        obj = _active_line(context)
        return obj is not None and obj.conveyor_line.populate_item is not None

    def execute(self, context):
        _active_line(context).conveyor_line.populate_item = None
        return {'FINISHED'}


def start_picker_from_ui(context) -> bool:
    """Starts the eyedropper from a property update (the Populate checkbox);
    False when the context cannot run a modal operator (scripts, background)."""
    if getattr(context, "window", None) is None or bpy.app.background:
        return False
    try:
        return bpy.ops.conveyor.pick_item('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
    except Exception:
        return False


classes = (CONVEYOR_OT_pick_item, CONVEYOR_OT_clear_item)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
