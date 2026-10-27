"""The public operators other add-ons drive a conveyor line with (interop
contract v2.1, R6): `conveyor.set_line_rate`, `conveyor.set_line_item` and
`conveyor.dock_line`. Keyed by the line's `wh_system.id` (never an object
name), idempotent (nothing is rebuilt when nothing changes) and recording the
caller in `by` (shown on the panel: "rate from warehouse_racks"). Other add-ons
never write `conveyor_line.*` themselves (R6, R7, R14).

Returns and reports: a missing line_id, system_id or port_id, a bad anchor, a
negative rate or a load without an id cancel ({'CANCELLED'}) with a WARNING
report naming what is missing (never an ERROR, so a caller gets the set back
instead of an exception); a dock that cannot happen (port taken or scaled
system) cancels the same way. A request that changes nothing finishes
({'FINISHED'}) without a rebuild. Decisions in model/public_api.py."""
from __future__ import annotations

import math

import bpy

from ..model.public_api import (FLOW_ANCHORS, FLOW_KEY, ITEM_KEY, RATE_KEY, flow_plan, forward_axis, geometric_anchor, parse_load,
                                placeholder_dims, population_plan)
from .._wh import ops as wh_ops
from .._wh import records as wh_records

LOADS_COLLECTION = "Warehouse Loads"
UNKNOWN_BY = "unknown"


# ---------------------------------------------------------------- lookups --

def line_by_id(scene, line_id):
    """The line whose `wh_system.id` is `line_id` (its stable uuid), or None."""
    from .build_line import all_lines
    from .ports import SYSTEM_KEY, UUID_KEY, _json

    lid = str(line_id or "").strip()
    if not lid:
        return None
    lines = all_lines(scene)
    for line in lines:
        if str(line.get(UUID_KEY, "") or "") == lid:
            return line
    for line in lines:  # a line whose uuid was never written: its descriptor's id
        desc = _json(line.get(SYSTEM_KEY), {})
        if isinstance(desc, dict) and str(desc.get("id", "")) == lid:
            return line
    return None


def record(obj, key: str) -> dict | None:
    from .ports import _json

    data = _json(obj.get(key), None)
    return data if isinstance(data, dict) else None


def _write(obj, key: str, data: dict) -> bool:
    return wh_records.write_record(obj, key, data)


def _clear(obj, key: str) -> None:
    if key in obj:
        del obj[key]


def _by(value: str) -> str:
    return str(value or "").strip() or UNKNOWN_BY


# ------------------------------------------------------------------- rate --

def follows_note(context, line):
    """ "<line> follows Rack · out0" when a system's port leads the line's
    stream (R22: the Population it is given is kept, the port's flow is what
    runs and is published); None when a line leads it."""
    from .stream import tree_for

    try:
        gf = tree_for(context, line).flow
    except Exception:
        return None
    if gf is None or not gf.master_node or line.conveyor_line.flow_master:
        return None
    if any(gf.master_node == ids[0] for ids in gf.sections.values()):
        return None  # a line section is the master
    return f"{line.name} follows {gf.master}"


class CONVEYOR_OT_set_line_rate(bpy.types.Operator):
    bl_idname = "conveyor.set_line_rate"
    bl_label = "Set Line Rate (other add-ons)"
    bl_description = ("Deprecated since 2.22 (use set_line_flow): another add-on sets this line's flow as items/h, "
                      "kept as the Population that carries it at the line's speed; 0 gives the line its own Population back")
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    line_id: bpy.props.StringProperty(name="Line id", description="The line's wh_system.id", options={'SKIP_SAVE'})
    rate_ph: bpy.props.FloatProperty(name="Rate (items/h)", default=0.0, options={'SKIP_SAVE'})
    by: bpy.props.StringProperty(name="By", description="The add-on asking, e.g. warehouse_racks", options={'SKIP_SAVE'})

    def execute(self, context):
        line = line_by_id(context.scene, self.line_id)
        if line is None:
            self.report({'WARNING'}, f"No conveyor line with id '{self.line_id}'")
            return {'CANCELLED'}
        if self.rate_ph < 0.0:
            self.report({'WARNING'}, "rate_ph must be 0 (release) or more")
            return {'CANCELLED'}
        settings = line.conveyor_line
        rec = record(line, RATE_KEY)
        from .populate import populate_item_length
        from .stream import tree_for

        speed = tree_for(context, line).speed  # the speed the line's goods run at (its master's)
        new_pct, new_rec, _changed = population_plan(rec, float(settings.population_pct), self.rate_ph,
                                                     populate_item_length(context, line), speed)
        if new_rec is not None:
            _write(line, RATE_KEY, dict(new_rec, by=_by(self.by)))  # the caller's name follows the latest request
        elif rec is not None:
            _clear(line, RATE_KEY)
        if new_pct is not None:
            settings.population_pct = new_pct  # the property's update rebuilds the line and its stream
        if self.rate_ph > 0.0 and not settings.populate:
            self.report({'WARNING'}, f"{line.name} carries no goods (Populate is off): the rate is stored, its ports publish nothing until it does")
        note = follows_note(context, line) if self.rate_ph > 0.0 else None
        if note:
            self.report({'INFO'}, note)  # kept, but the port's flow runs (R22)
        return {'FINISHED'}


# ------------------------------------------------------------------- flow --

class CONVEYOR_OT_set_line_flow(bpy.types.Operator):
    """Contract R22: another add-on sets a line's simple-flow sliders --
    Population (0..1), Speed (m/s) and, on a branch, its Share of the master
    (0..1). A negative value leaves that one as it is. The line follows its
    master as before: Population counts where the line leads its stream."""
    bl_idname = "conveyor.set_line_flow"
    bl_label = "Set Line Flow (other add-ons)"
    bl_description = "Another add-on sets this line's Population, Speed and (a branch) Share of the master; negative values leave them"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    line_id: bpy.props.StringProperty(name="Line id", description="The line's wh_system.id", options={'SKIP_SAVE'})
    population: bpy.props.FloatProperty(name="Population", default=-1.0, options={'SKIP_SAVE'})
    speed_m_s: bpy.props.FloatProperty(name="Speed (m/s)", default=-1.0, options={'SKIP_SAVE'})
    share: bpy.props.FloatProperty(name="Share of the master", default=-1.0, options={'SKIP_SAVE'})
    by: bpy.props.StringProperty(name="By", description="The add-on asking, e.g. warehouse_floorplan", options={'SKIP_SAVE'})

    def execute(self, context):
        line = line_by_id(context.scene, self.line_id)
        if line is None:
            self.report({'WARNING'}, f"No conveyor line with id '{self.line_id}'")
            return {'CANCELLED'}
        from .detect_junctions import docked_diverter
        from .build_line import build_line
        from ..props.line_settings import suspended_rebuild

        settings = line.conveyor_line
        current = {"population_pct": float(settings.population_pct), "speed_m_s": float(settings.speed_m_s),
                   "share_pct": int(settings.share_pct)}
        writes, setting, problems = flow_plan(current, self.population, self.speed_m_s, self.share,
                                              docked_diverter(context, line) is not None)
        if problems and not setting:
            self.report({'WARNING'}, "; ".join(problems))
            return {'CANCELLED'}
        for problem in problems:
            self.report({'WARNING'}, problem)
        if setting:
            wanted = dict(setting, by=_by(self.by))
            if record(line, FLOW_KEY) != wanted:
                _write(line, FLOW_KEY, wanted)  # who set what ("Set by Floorplan")
        if writes:
            with suspended_rebuild():
                for name, value in writes.items():
                    setattr(settings, name, value)
            build_line(context, line)  # once, for every slider it set; its stream peers follow
        if writes and not settings.populate and docked_diverter(context, line) is None:
            self.report({'WARNING'}, f"{line.name} carries no goods (Populate is off): its Population counts once it does")
        note = follows_note(context, line) if self.population >= 0.0 else None
        if note:
            self.report({'INFO'}, note)  # its Population is kept, the port's flow runs (R22)
        return {'FINISHED'}


# ------------------------------------------------------------------- item --

def _load_object(load: dict):
    """The object carrying this load id: named as the load says, or found in Warehouse Loads."""
    name = str(load.get("object", "") or "")
    obj = bpy.data.objects.get(name) if name else None
    if obj is not None and obj.type == 'MESH':
        return obj
    return find_load_object(load.get("id", ""))


def find_load_object(lid):
    """The mesh in Warehouse Loads whose wh_load is this load -- ids compared
    as warehouse_common spells them (loads.same_load, 0.6.6: Racks makes
    "pallet:EUR1:Plastic:1.0" as "...:1"), so a caller's spelling never
    misses the object another add-on built."""
    from .._wh import loads as wh_loads
    from .populate import wh_load

    if not lid:
        return None
    coll = bpy.data.collections.get(LOADS_COLLECTION)
    if coll is not None:
        for o in coll.all_objects:
            wl = wh_load(o)
            if wl is not None and o.type == 'MESH' and wl.get("id") and wh_loads.same_load(str(wl.get("id")), str(lid)):
                return o
    return None


def _placeholder_for(scene, load: dict):
    """Our own placeholder box for a load nobody can build: in the placeholder
    collection (not linked to the scene, drawn only as the stream's items)."""
    from ..config import units
    from .._wh import loads as wh_loads
    from .populate import _build_box_mesh, ensure_placeholders

    lid = wh_loads.canonical_load_id(str(load.get("id", "")))  # one placeholder per load, however it was spelled
    name = f"Load {lid}"[:63]
    coll = ensure_placeholders(scene)
    obj = bpy.data.objects.get(name)
    if obj is not None and obj.type == 'MESH':
        if obj.name not in coll.objects:
            coll.objects.link(obj)
        return obj
    if not all(load.get(k) for k in ("length_m", "width_m", "height_m")):
        # A catalogue load id without sizes: the exact box from warehouse_common's catalogue (0.4).
        try:
            from .._wh import loads as wh_loads

            cat_l, cat_w, cat_h = wh_loads.placeholder_size(lid)
            load = {**load, "length_m": load.get("length_m") or cat_l, "width_m": load.get("width_m") or cat_w,
                    "height_m": load.get("height_m") or cat_h}
        except Exception:
            pass
    length, width, height = placeholder_dims(load)
    axis = forward_axis(load) or "Y"
    across, along = (length, width) if axis in ("X", "NEG_X") else (width, length)
    mesh = bpy.data.meshes.new(name)
    _build_box_mesh(mesh, units.mm_to_bu(across * 1000.0, scene), units.mm_to_bu(along * 1000.0, scene), units.mm_to_bu(height * 1000.0, scene))
    try:
        from ..geonodes import materials

        mesh.materials.append(materials.plastic())
    except Exception:
        pass
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    # Our own object: it says what it is for the stream (a JSON string, R2; readers take both forms).
    wh_records.write_record(obj, "wh_load", {k: v for k, v in {"kind": load.get("kind", "item"), "id": lid, "length_m": length, "width_m": width,
                                                               "height_m": height, "forward_axis": axis, "object": obj.name}.items()
                                             if isinstance(v, (str, int, float, bool))})
    return obj


def resolve_item(context, load: dict):
    """R6: the existing object in Warehouse Loads, else `warehouse.make_load` when
    that add-on is here, else a placeholder sized from the load."""
    obj = _load_object(load)
    if obj is not None:
        return obj
    lid = str(load.get("id", ""))
    if wh_ops.operator_exists(bpy.ops, "warehouse.make_load"):  # never hasattr: bpy.ops answers True for any name (R7)
        try:
            bpy.ops.warehouse.make_load(load_id=lid)
        except Exception:
            pass
        obj = _load_object(load)
        if obj is not None:
            return obj
    return _placeholder_for(context.scene, load)


class CONVEYOR_OT_set_line_item(bpy.types.Operator):
    bl_idname = "conveyor.set_line_item"
    bl_label = "Set Line Item (other add-ons)"
    bl_description = "Another add-on sets what this line carries, from a wh_load record (JSON)"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    line_id: bpy.props.StringProperty(name="Line id", options={'SKIP_SAVE'})
    load_json: bpy.props.StringProperty(name="Load (wh_load JSON)", options={'SKIP_SAVE'})
    by: bpy.props.StringProperty(name="By", options={'SKIP_SAVE'})

    def execute(self, context):
        from ..props.line_settings import suspended_rebuild
        from .detect_junctions import _rebuild

        line = line_by_id(context.scene, self.line_id)
        if line is None:
            self.report({'WARNING'}, f"No conveyor line with id '{self.line_id}'")
            return {'CANCELLED'}
        load = parse_load(self.load_json)
        if load is None:
            self.report({'WARNING'}, "load_json must be a wh_load record with an id")
            return {'CANCELLED'}
        from ..model import port_io

        if not port_io.carries_load(load):  # R19
            self.report({'WARNING'}, f"A conveyor does not carry {port_io.load_kind(load)} loads")
            return {'CANCELLED'}
        item = resolve_item(context, load)
        if item is None or item == line:
            self.report({'WARNING'}, f"No item for load '{load.get('id')}'")
            return {'CANCELLED'}
        apply_load(context, line, load, item, self.by)
        return {'FINISHED'}


def apply_load(context, line, load: dict, item, by: str) -> bool:
    """The line carries `item` for the wh_load record `load`: the travel axis
    first (the spacing is seeded from the item's length along it), then the
    item (its update rebuilds), then Populate; the caller recorded in
    conveyor_item_from. True when something changed."""
    from ..props.line_settings import suspended_rebuild
    from .detect_junctions import _rebuild

    settings = line.conveyor_line
    axis = forward_axis(load)
    changed = False
    with suspended_rebuild():
        if axis is not None and settings.populate_forward_axis != axis:
            settings.populate_forward_axis = axis
            changed = True
        if not settings.populate:
            settings.populate = True
            changed = True
    if settings.populate_item != item:
        settings.populate_item = item  # its update seeds the spacing from the item and rebuilds
        changed = True
    elif changed:
        _rebuild(context, line)
    _write(line, ITEM_KEY, {"by": _by(by), "load_id": str(load.get("id")), "object": item.name})
    return changed


# ------------------------------------------------------------------- dock --

class CONVEYOR_OT_dock_line(bpy.types.Operator):
    bl_idname = "conveyor.dock_line"
    bl_label = "Dock Line at Port (other add-ons)"
    bl_description = ("Another add-on docks this line at a system's port: its flow start on an out port (anchor start), "
                      "its flow end on an in port (anchor end), taking the port's direction and width")
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    line_id: bpy.props.StringProperty(name="Line id", options={'SKIP_SAVE'})
    system_id: bpy.props.StringProperty(name="System id", description="The system's wh_system.id", options={'SKIP_SAVE'})
    port_id: bpy.props.StringProperty(name="Port id", options={'SKIP_SAVE'})
    anchor: bpy.props.StringProperty(name="Anchor", description="start (the goods start here) or end (they end here)", default="start", options={'SKIP_SAVE'})
    by: bpy.props.StringProperty(name="By", options={'SKIP_SAVE'})

    def execute(self, context):
        from ..props.line_settings import suspended_rebuild
        from .detect_junctions import _place_origin, _remember_matrix, _world_matrix, origin_dock, sync_feeder
        from .ports import (_aim_end, _end_pose, _save_docks, carries_upstream_goods, dock_at, dock_pos, docks, find_system, holder_name, holder_of,
                            port_by_id, scaled, system_id as sid_of, world_port)

        scene = context.scene
        line = line_by_id(scene, self.line_id)
        if line is None:
            self.report({'WARNING'}, f"No conveyor line with id '{self.line_id}'")
            return {'CANCELLED'}
        anchor = str(self.anchor or "").strip().lower()
        if anchor not in FLOW_ANCHORS:
            self.report({'WARNING'}, "anchor must be 'start' or 'end'")
            return {'CANCELLED'}
        system = find_system(scene, str(self.system_id or "").strip(), "")
        if system is None:
            self.report({'WARNING'}, f"No system with id '{self.system_id}'")
            return {'CANCELLED'}
        port = port_by_id(system, str(self.port_id or ""))
        if port is None:
            self.report({'WARNING'}, f"No port '{self.port_id}' on {system.name}")
            return {'CANCELLED'}
        role = str(port.get("role", "out"))
        if (anchor == "start" and role == "in") or (anchor == "end" and role == "out"):
            self.report({'WARNING'}, f"{port.get('id')} is an {role} port: the goods {'end' if role == 'in' else 'start'} there (anchor '{'end' if role == 'in' else 'start'}')")
            return {'CANCELLED'}
        if scaled(system):
            self.report({'WARNING'}, f"{system.name} is scaled; sizes are 1:1 metres")
            return {'CANCELLED'}
        from ..model import port_io

        if not port_io.carries_load(port.get("load")):  # R19: e.g. a cantilever rack's "long" bundles
            self.report({'WARNING'}, f"{port.get('id')} on {system.name} delivers {port_io.load_kind(port.get('load'))} loads: "
                                     "a conveyor does not carry them")
            return {'CANCELLED'}
        sid = sid_of(system)
        by = _by(self.by)
        for geo in ("origin", "end"):
            d = dock_at(line, geo)
            if d is not None and str(d.get("system_id", "")) == sid and str(d.get("port", "")) == str(port.get("id")):
                if d.get("by") != by:  # already there: only the caller's name is recorded, nothing rebuilt
                    data = docks(line)
                    data[geo]["by"] = by
                    _save_docks(line, data)
                return {'FINISHED'}
        holder = holder_of(scene, system, str(port.get("id")), exclude=line)
        if holder is not None:
            self.report({'WARNING'}, f"{port.get('id')} on {system.name} is taken by {holder_name(holder)}")
            return {'CANCELLED'}
        settings = line.conveyor_line
        origin_taken = dock_at(line, "origin") is not None or origin_dock(context, line) is not None
        geo, reverse = geometric_anchor(anchor, bool(settings.reverse), origin_taken)
        if geo == "origin":
            if bool(settings.reverse) != reverse:
                with suspended_rebuild():
                    settings.reverse = reverse
            line_role = "in" if reverse else "out"
            pos, heading, _handover = world_port(system, port, line_role)
            pos = dock_pos(port, pos, _world_matrix(line).translation.z)  # R16: a z_free port keeps the line's height
            if _place_origin(line, pos, heading + (math.pi if line_role == "in" else 0.0)):
                _remember_matrix(line)
        else:
            pose = _end_pose(context, line)
            if pose is None:
                self.report({'WARNING'}, f"{line.name} has no end to dock")
                return {'CANCELLED'}
            end, end_local, end_world = pose
            pos, heading, _handover = world_port(system, port, "in")
            _aim_end(context, line, end, end_local, end_world, dock_pos(port, pos, end_world.z), heading)
            _remember_matrix(line)
        sync_feeder(context, line)  # the dock itself: width, load and rate from the port, links written, line rebuilt
        d = dock_at(line, geo)
        if d is None or str(d.get("system_id", "")) != sid or str(d.get("port", "")) != str(port.get("id")):
            self.report({'WARNING'}, f"{line.name} did not dock at {system.name} · {port.get('id')}")
            return {'CANCELLED'}
        data = docks(line)
        data[geo]["by"] = by
        _save_docks(line, data)
        # The port's load, applied NOW (the hand dock defers a missing load object to a timer; a
        # public operator leaves its effect done when it returns: Racks and scripts read it straight away).
        load = port.get("load")
        follows = str(d.get("role", "out")) == "in" and carries_upstream_goods(context, line)  # a branch's goods are its main's
        if isinstance(load, dict) and str(load.get("id", "") or "").strip() and line.conveyor_line.populate_item is None and not follows:
            item = resolve_item(context, load)
            if item is not None and item != line:
                from .ports import _store

                apply_load(context, line, load, item, by)
                _store(line, geo, system, port, str(d.get("role", "out")), True)  # the load is on: no retry on later passes
        return {'FINISHED'}


classes = (CONVEYOR_OT_set_line_rate, CONVEYOR_OT_set_line_flow, CONVEYOR_OT_set_line_item, CONVEYOR_OT_dock_line)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
