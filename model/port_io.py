"""Reading a published port for a line's role (contract v2 §2, the Racks'
delivery options of 2026-10-11): a crane aisle served by ONE conveyor
publishes one "io" port at the in-feed's place -- `heading_deg` is the OUT
direction (goods leaving), `heading_in_deg` the IN direction, `rate_ph`
the out rate, `rate_in_ph` the in rate, `capacity_ph` the crane's whole
dual-cycle capacity shared by both. A line is one-directional: it docks
there as an out line (goods start at the port) or an in line (goods end
there), and its link names ITS role, never "io".

Pure Python, unit-tested."""
from __future__ import annotations

OUT, IN, IO = "out", "in", "io"


def accepts(port: dict, role: str) -> bool:
    """A port of `role` or an io port serves a line of `role` (in / out)."""
    return port.get("role") in (role, IO)


def heading_deg(port: dict, role: str | None) -> float:
    """The direction (degrees, 0 = +Y, counter-clockwise, in the system's
    frame) goods travel at the port for a line of `role`: out of the system
    along `heading_deg`; into it along `heading_in_deg` when the port has
    one (an io port), else `heading_deg` (a plain "in" port already points
    inward)."""
    if role == IN and port.get("heading_in_deg") is not None:
        return float(port["heading_in_deg"])
    return float(port.get("heading_deg", 0.0) or 0.0)


def body_heading_deg(port: dict, role: str | None) -> float:
    """The heading of a line's body from its ORIGIN at the port: an out
    line leaves along the goods' direction, an in line's goods arrive at
    its origin, so its body points the other way."""
    return heading_deg(port, role) + (180.0 if role == IN else 0.0)


# ---- R22 (simple flow): the stream of a port as population and speed.
# A published population wins (R22.5: even 0, a stopped source); a legacy
# rate key stands in only when the port publishes none -- the precedence of
# warehouse_common 0.6.3's build_graph, so every reader has one number. Pure
# Python.
GAP_M = 0.05  # at 100 % population the goods are 50 mm apart


def _num(record, key: str):
    try:
        value = record.get(key)
        return None if value is None else float(value)
    except (TypeError, ValueError, AttributeError):
        return None


def _fraction(value):
    return None if value is None else min(max(value, 0.0), 1.0)


def population(port: dict, role: str | None = None):
    """How full the port's stream is (0-1) for a line of `role`:
    `population_in` for an in line at an io port that has one, else
    `population`; None when the port publishes neither."""
    key = "population_in" if (role == IN and port.get("population_in") is not None) else "population"
    return _fraction(_num(port, key))


def max_population(port: dict):
    """A sink's limit (0-1; a crane in-feed, a VLM window); None: no limit."""
    return _fraction(_num(port, "max_population"))


def goods_speed_m_s(port: dict):
    """The goods' speed at the port: R22 `speed_m_s`, else the legacy
    `surface_speed_m_s`; None when neither is a positive number."""
    for key in ("speed_m_s", "surface_speed_m_s"):
        value = _num(port, key)
        if value is not None and value > 0.0:
            return value
    return None


def is_master(record) -> bool:
    """The user's explicit master pick on a port or line (`master: true`)."""
    try:
        return record.get("master") is True
    except AttributeError:
        return False


def link_share(link: dict):
    """A link's LOCAL share of the stream at its split (0-1); None: not given."""
    return _fraction(_num(link, "share"))


def load_length_m(port: dict):
    """The length along travel of the load the port hands over (wh_load
    `length_m`), when it says."""
    load = port.get("load")
    value = _num(load, "length_m") if isinstance(load, dict) else None
    return value if value is not None and value > 0.0 else None


def flow_ph(population_: float, speed_m_s: float, item_length_m: float) -> float:
    """Items per hour of a stream that full at that speed: one item every
    (length + GAP_M) / population metres."""
    if not (population_ and speed_m_s and item_length_m) or population_ <= 0.0 or speed_m_s <= 0.0 or item_length_m <= 0.0:
        return 0.0
    return 3600.0 * population_ * speed_m_s / (item_length_m + GAP_M)


def rate_ph(port: dict, role: str | None, item_length_m: float | None = None, speed_m_s: float | None = None) -> float:
    """Items per hour the port moves for a line of `role`: its R22 population
    at the port's goods speed (else `speed_m_s`) over the port's load length
    (else `item_length_m`) when it publishes one (R22.5); else the legacy
    `rate_in_ph` (an in line at an io port that has one) or `rate_ph` when
    above 0 (the R22 transition); 0: nothing known."""
    pop = population(port, role)
    if pop is not None:
        return flow_ph(pop, goods_speed_m_s(port) or speed_m_s or 0.0, load_length_m(port) or item_length_m or 0.0)
    key = "rate_in_ph" if (role == IN and port.get("rate_in_ph") is not None) else "rate_ph"
    legacy = _num(port, key)
    return legacy if legacy is not None and legacy > 0.0 else 0.0


def capacity_ph(port: dict, item_length_m: float | None = None, speed_m_s: float | None = None) -> float:
    """What the port can take or make an hour: its R22 `max_population` the
    same way as rate_ph when published, else the legacy `capacity_ph` when
    above 0; 0: no limit known."""
    cap = max_population(port)
    if cap is not None:
        return flow_ph(cap, goods_speed_m_s(port) or speed_m_s or 0.0, load_length_m(port) or item_length_m or 0.0)
    legacy = _num(port, "capacity_ph")
    return legacy if legacy is not None and legacy > 0.0 else 0.0


def link_role(line_role: str | None) -> str:
    """What the link entry says: the LINE's role, never the port's "io"."""
    return IN if line_role == IN else OUT


# R19: the load kinds a conveyor carries. Anything else -- "long"
# bundles for cantilever racks, or a kind this add-on does not know yet -- is
# not accepted: no dock, no item, the usual note, never a crash.
CARRIED_KINDS = ("pallet", "tote", "carton", "item", "custom")


def carries_load(load) -> bool:
    """Does a conveyor carry this wh_load? No load, or a load without a kind
    (an older record), is fine; an unknown kind is not."""
    if not isinstance(load, dict):
        return True
    kind = load.get("kind")
    return kind is None or str(kind) in CARRIED_KINDS


def load_kind(load) -> str:
    return str(load.get("kind", "?")) if isinstance(load, dict) else "?"
