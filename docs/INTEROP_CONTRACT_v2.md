# Interop contract — Conveyor's pointer and API reference

**Canonical text:** `Blender Plugins/_coordination/INTEROP.md` (owned by the Master plugin PM, under
git): contract v1, v2 and v2.1 (rules R1–R16, including Conveyor's R3 and R16 wording). This file no
longer mirrors it. **Conveyor implements contract v2.1** (its `wh_addons` entry says
`"contract": "2.1"`) with the pure contract maths vendored from `Warehouse Common` as `_wh/`.

## What Conveyor implements, by rule

| Rule | Topic | Conveyor |
|---|---|---|
| R1 | Shuttle's id is `pallet_shuttle` (doc fix in v2 §1/§7) | n/a |
| R2 | RECORDS (`wh_system`, `wh_ports`, `wh_port_links`, `wh_load`, `wh_path`, `wh_obstacles`, `wh_levels`, `wh_zone`) are compact JSON strings; readers accept a JSON string OR an IDProperty dict/list forever; SCALAR MARKERS (`wh_floor` bool, scene `wh_time_scale` float) stay plain values; the v1 `wh_port_link` stays a dict until no v1 reader is left | **2.7.0** readers, **2.9.0** all writers |
| R3 | Floors | **2.7.0** |
| R4 | Scene units | Racks (W1); Conveyor keeps metres |
| R5 | Handler hygiene | **2.9.0** |
| R6 | Public Conveyor operators, keyed by `wh_system | **2.8.0** (signatures in 10.1) |
| R7 | No cross-add-on code | 2.8.0 (operator_exists everywhere) |
| R8 | Placement avoids every `wh_system` footprint + `clearance_m` and every `wh_obstacles` polygon on the same level, except `"container" | Racks / Floorplan |
| R9 | Shared "WH" material palette | **2.11.0**: the frame and the rollers are `conveyor_frame` / `conveyor_rollers` (geonodes/materials.py: stamp > legacy name stamped and renamed while unchanged > created from `_wh.palette`); a `wh_material` datablock is never cleared or rebuilt here; the other materials keep the `Conveyor - ` prefix |
| R10 | Levels | **2.7.0** |
| R11 | Registry | **2.7.0** |
| R12 | Shuttle joins the contract (parked) | n/a |
| R13 | Obstacles | **2.10.0**: `operators/obstacles.py` (vendored `path_obstacle_hits`), hits stored on the line as `conveyor_obstacle_hits`, recomputed by every build and by the sync pass when a host or a line moves; tested against a Floorplan 0.2.0 building (walls, a door's gap and its lintel) |
| R14 | One writer per record | holds; a line's `wh_port_links` / `wh_port_link` are rewritten or cleared whole by Conveyor, so entries an older Racks (≤ 0.18) wrote onto a line are dropped on its next rebuild |
| R16 | Docking at a `z_free` port (a dock door, a ground door, a flow point | **2.8.0** |
| R15 | Links from any system | **2.7.0** |

Records Conveyor writes on its lines: `wh_system` (with `level`), `wh_ports` (`line_in`, `line_out`,
RAT faces; each with `level`), `wh_path`, `wh_port_links` (+ the v1 `wh_port_link` dict), the item's
`wh_load` on its own placeholder loads; the registry entry in `window_manager["wh_addons"]`. Its own
non-contract records on lines: `conveyor_port`, `conveyor_port_note`, `conveyor_rate_from`,
`conveyor_item_from`, `conveyor_obstacle_hits`, `conveyor_floor_mark` (on marked floors).

### 10.1 The R6 operators (Conveyor 2.8.0)

All three take the line by its `wh_system.id` (string), record the caller in `by` (a free
string, the calling add-on's id), return `{'FINISHED'}` when done or when nothing had to
change (no rebuild then), and `{'CANCELLED'}` with a `WARNING` report (never an `ERROR`, so
callers get the set back, not an exception) when something is missing. Discover them with
`_wh.ops.operator_exists(bpy.ops, "conveyor.set_line_rate")` etc. (not `hasattr`, see R7); an
older Conveyor lacks them.

```python
bpy.ops.conveyor.set_line_rate(line_id="<wh_system.id>", rate_ph=45.0, by="warehouse_racks")
```
Sets the line's Throughput (items/h, rounded to an integer). The line's own setting is kept
underneath and the panel says "Rate from warehouse_racks: 45/h (own setting 120/h)".
`rate_ph=0` releases: the own setting comes back. Cancels on an unknown `line_id`
("No conveyor line with id '…'") or a negative rate. A line that carries no goods (Populate
off) stores the rate but its ports publish 0/h until it does: FINISHED with a WARNING report. The same rate again changes nothing; a
different `by` with the same rate only updates the name.

```python
bpy.ops.conveyor.set_line_item(line_id="<wh_system.id>", load_json='{"kind":"pallet","id":"pallet:EUR1:Wood:1.2","length_m":1.2,"width_m":0.8,"height_m":1.0,"forward_axis":"X"}', by="warehouse_racks")
```
The line carries the load: its item is the object named by `object` or any object in
`Warehouse Loads` whose `wh_load.id` matches; else `warehouse.make_load(load_id=…)` is called
when that operator is registered and the object looked up again; else Conveyor makes its own
placeholder box ("Load <id>", sized from the record, in its placeholder collection).
`forward_axis` (X, Y, NEG_X / -X, NEG_Y / -Y) sets the Forward Axis; Populate is switched on.
Cancels on an unknown `line_id` or a `load_json` that is not a record with an `id`. The same
load again changes nothing.

```python
bpy.ops.conveyor.dock_line(line_id="<wh_system.id>", system_id="<wh_system.id of the rack>", port_id="aisle0_out", anchor="start", by="warehouse_racks")
```
Docks the line at the port: `anchor="start"` puts the line's flow START on an out (or io)
port, forward; `anchor="end"` puts its flow END on an in (or io) port: the far end when the
line's origin is already docked elsewhere and the line runs forward, else the origin,
reversed (the line ends there, its body pointing away). Direction, width, load and rate
come from the port as for a hand dock; `wh_port_links` is written. The port's load is applied
before the operator returns (2.11.1): the item resolved as for `set_line_item` (the named
object, else `Warehouse Loads`, else `warehouse.make_load`, else a placeholder), so a caller
can read the line's item and, after `set_line_rate`, its published rates at once. Cancels on an unknown
`line_id` / `system_id` / `port_id`, an anchor other than start / end, an anchor that does
not fit the port's role (start on an in port, end on an out port), a scaled system, a port
held by someone else ("… is taken by Route AMR-2") or a dock that did not take. Docking
again at the same port changes nothing but the recorded `by`.
