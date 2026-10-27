"""The public operators' decisions without bpy (interop contract v2.1, R6), so
they unit-test anywhere: which end of a line a flow anchor means, what a rate
request changes, what a load record must carry (operators/public_api.py)."""
from __future__ import annotations

import json

RATE_KEY = "conveyor_rate_from"  # {"by", "rate_ph", "own_pct"}: a rate set from outside, the line's own Population kept underneath (pre-2.22: "own_ph")
GAP_AT_FULL_M = 0.05  # warehouse_common simple_flow: the gap between items at Population 100 %
ITEM_KEY = "conveyor_item_from"  # {"by", "load_id", "object"}: the item set from outside
LAYOUT_KEY = "conveyor_layout_from"  # {"by", "points"}: the line was laid out along points from outside (R21)
FLOW_KEY = "conveyor_flow_from"  # {"by", "population", "speed_m_s", "share"}: what set_line_flow set (R22)

ADDON_NAMES = {"warehouse_floorplan": "Floorplan", "warehouse_racks": "Racks", "conveyor_system": "Conveyor", "pallet_shuttle": "Shuttle"}


def addon_name(by: str) -> str:
    """A caller's add-on id as the panels say it: warehouse_floorplan -> Floorplan."""
    by = str(by or "").strip()
    return ADDON_NAMES.get(by) or by.replace("warehouse_", "").replace("_", " ").strip().title() or "another add-on"
FLOW_ANCHORS = ("start", "end")
AXES = ("X", "Y", "NEG_X", "NEG_Y")


def geometric_anchor(flow_anchor: str, reverse: bool, origin_taken: bool) -> tuple[str, bool]:
    """(dock anchor "origin" / "end", the Reverse the line needs) for a flow anchor.
    "start" = the goods start here (an out port): the origin, forward. "end" = the
    goods end here (an in port): the far end when the origin is already taken
    (docked elsewhere) and the line runs forward; else the origin, reversed (the
    line ends there, its body pointing away from the system)."""
    if flow_anchor == "start":
        return "origin", False
    if origin_taken and not reverse:
        return "end", False
    return "origin", True


def flow_plan(current: dict, population: float, speed_m_s: float, share: float, is_branch: bool) -> tuple[dict, dict, list]:
    """set_line_flow (contract R22): (the settings to write {name: value},
    what was set {key: value} for the record, problems). `population` 0..1,
    `speed_m_s` > 0, `share` 0..1 OF THE MASTER (a branch's Share slider; the
    link keeps the local fraction). A negative value leaves that one as it
    is. `current`: {"population_pct", "speed_m_s", "share_pct"} now."""
    writes, setting, problems = {}, {}, []
    if population is not None and population >= 0.0:
        if population > 1.0 + 1e-9:
            problems.append(f"population {population:g} is not 0..1")
        else:
            pct = round(float(population) * 100.0, 4)
            setting["population"] = round(float(population), 6)
            if abs(pct - float(current.get("population_pct", 0.0))) > 1e-6:
                writes["population_pct"] = pct
    if speed_m_s is not None and speed_m_s > 0.0:
        setting["speed_m_s"] = round(float(speed_m_s), 6)
        if abs(float(speed_m_s) - float(current.get("speed_m_s", 0.0))) > 1e-6:  # the setting is single precision
            writes["speed_m_s"] = float(speed_m_s)
    if share is not None and share >= 0.0:
        if share > 1.0 + 1e-9:
            problems.append(f"share {share:g} is not 0..1")
        elif not is_branch:
            problems.append("share applies to a branch (a line leaving a diverter)")
        else:
            pct = int(round(float(share) * 100.0))
            setting["share"] = round(float(share), 6)
            if pct != int(current.get("share_pct", 0)):
                writes["share_pct"] = pct
    return writes, setting, problems


def population_pct_for_rate(rate_ph: float, item_length_m: float, speed_m_s: float) -> float:
    """The Population (%) that carries `rate_ph` items an hour at `speed_m_s`
    (simple_flow.population_from_rate), capped at 100 %."""
    if rate_ph <= 0.0 or speed_m_s <= 1e-9:
        return 0.0
    return min(100.0, 100.0 * rate_ph * (max(item_length_m, 0.0) + GAP_AT_FULL_M) / (3600.0 * speed_m_s))


def population_plan(record: dict | None, current_pct: float, rate_ph: float, item_length_m: float,
                    speed_m_s: float) -> tuple[float | None, dict | None, bool]:
    """set_line_rate since 2.22 (a shim, rate -> population): (the
    Population % to write or None to leave it, the record to keep or None to
    drop it, whether anything changes). The line's own Population stays in
    the record; 0 releases and gives it back."""
    try:
        wanted = max(0.0, float(rate_ph))
    except (TypeError, ValueError):
        wanted = 0.0
    current = float(current_pct)
    if wanted <= 0.0:
        if record is None:
            return None, None, False
        own = _float(record.get("own_pct"), current)
        return (own if abs(own - current) > 1e-6 else None), None, True
    pct = population_pct_for_rate(wanted, item_length_m, speed_m_s)
    if record is not None and abs(_float(record.get("rate_ph"), -1.0) - wanted) < 1e-6 and abs(current - pct) < 1e-6:
        return None, dict(record), False
    own = _float(record.get("own_pct"), current) if record is not None else current
    return (pct if abs(pct - current) > 1e-6 else None), {"rate_ph": round(wanted, 3), "own_pct": round(own, 3)}, True


def _float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def rate_plan(record: dict | None, current_ph: int, rate_ph: float) -> tuple[int | None, dict | None, bool]:
    """What set_line_rate does: (the Throughput to write or None to leave it,
    the record to keep or None to drop it, whether anything changes). `record`
    is the stored {"rate_ph", "own_ph", ...} or None; `current_ph` the line's
    Throughput now. 0 releases: the line's own setting comes back."""
    try:
        wanted = int(round(max(0.0, float(rate_ph))))
    except (TypeError, ValueError):
        wanted = 0
    current = int(current_ph)
    if wanted <= 0:
        if record is None:
            return None, None, False
        own = _int(record.get("own_ph"))
        return (own if own != current else None), None, True
    if record is not None and _int(record.get("rate_ph")) == wanted and current == wanted:
        return None, dict(record), False
    own = _int(record.get("own_ph")) if record is not None else current
    return (wanted if wanted != current else None), {"rate_ph": wanted, "own_ph": own}, True


def _int(value) -> int:
    try:
        return int(round(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def parse_load(load_json) -> dict | None:
    """A wh_load record from the operator's JSON text (a dict is taken as it is); None without an id."""
    try:
        load = json.loads(load_json) if isinstance(load_json, (str, bytes)) else dict(load_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(load, dict) or not str(load.get("id", "") or "").strip():
        return None
    return load


def placeholder_dims(load: dict) -> tuple[float, float, float]:
    """(length along travel, width, height) in metres for a placeholder of the load; a tote when nothing is said."""
    def num(key, default):
        try:
            v = float(load.get(key, default) or default)
        except (TypeError, ValueError):
            v = default
        return v if v > 0.0 else default

    return num("length_m", 0.6), num("width_m", 0.4), num("height_m", 0.3)


def forward_axis(load: dict) -> str | None:
    """The line's Forward Axis for the load, or None when the load does not say."""
    axis = str(load.get("forward_axis", "") or "").upper().replace("-", "NEG_")
    return axis if axis in AXES else None
