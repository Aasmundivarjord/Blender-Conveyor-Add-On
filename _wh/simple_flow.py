"""
Simple flow (contract R22): the maths every add-on shares so that a stream of goods looks the same in
each of them. Pure Python (no bpy, standard library only).

Lifted from the Racks add-on (commit 50eb5f1) into Warehouse Common 0.6.0. Changes since: 0.6.1 a
system node takes its out ports' item, 0.6.2 exact branch arrivals, 0.6.3 a self-clamped master is
capped and legacy rates stand in for population, 0.6.4 a port that says nothing is no source, legacy
stand-ins take the docked line's item, a sink's capacity_ph is its limit, 0.6.5 buffers (R22.6).

The user sets two sliders on a populated object: Population (0-1, how full the stream looks) and
Speed (m/s). Everything else follows from them.

- **Pitch.** At population 1 the goods run nose to tail with a small visible gap (GAP_AT_FULL_M,
  0.05 m): pitch = (item length + gap) / population.
- **Flow is what is conserved, invisibly.** flow = population x speed / (item length + gap), in items
  per second. A follower at another speed or carrying another item gets the population that keeps
  the flow; no item appears or vanishes at a hand-over. Panels still show only percentages, and never
  a number above 100 % (`share_text`).
- **Shares.** Links store LOCAL fractions (they sum to <= 1 at a split); panels show the share as a %
  OF THE MASTER. absolute = the product of the local fractions from the stream's root.
- **Merges** add flows and cap the occupancy at 1; feeders that would overflow are slowed at their
  roots. **Sinks with a limit** (`max_population`) cap the arriving stream silently: the stream is
  slowed upstream so that nothing vanishes.
- **The master** of a stream is the node flagged `master: true` (the most upstream flagged one), else
  the stream's most upstream node. Cycles are detected and reported. The order of edges never depends
  on the order they were given in (`split_order`), so every add-on diverts the same items.
- **Animation sync** (`period_s` / `phase_s` stay, R22): period = 1 / flow; item k's centre crosses the
  stream origin at phase + k x period (item 0 at t = 0 at the origin), so at a point the phase =
  travel time from the origin (mod period). A stream that changes rate is a piecewise schedule
  (`crossing_time`, `item_index`): items already on their way keep their times.
- **Buffers:** the share of what arrives that does not leave (Output %) piles up until the buffer is
  full; then it accepts only what it lets out. `buffer_fill` is the aggregate (panels), and
  `buffer_item_times` the per-item FIFO (animation).
- **A source with a working limit** (cranes, a VLM): its Population slider means "share of the most
  it can make", population = slider x `population_cap(items per hour, speed, item length)`.
- **The graph** comes from the published records (`build_graph`): ports, line sections, docks,
  diverts, merges and continues.

Units: metres, seconds, items. `item_length` is the load's length along travel (wh_load `length_m`).
"""

import math
from dataclasses import dataclass, field

GAP_AT_FULL_M = 0.05         # between items at population 1
EPS = 1e-9
INF = math.inf

# Default goods speed by load kind (m/s): pallet lines are slow, totes and cartons run on rollers / belts.
DEFAULT_SPEEDS = {"pallet": 0.2, "long": 0.2, "tote": 0.5, "carton": 0.5, "custom": 0.5}
DEFAULT_SPEED = 0.5

# Stream graph edge kinds. continue / dock / divert keep the goods in their stream (divert: a branch
# that takes a share); merge joins a feeder stream into another one (its flow adds there).
CONTINUE, DOCK, DIVERT, MERGE = "continue", "dock", "divert", "merge"
BUFFER = "buffer"            # 0.6.5 (R22.6): a buffer's exit; its share is Output %, the rest stays inside
MAIN_KINDS = (CONTINUE, DOCK, DIVERT, BUFFER)
_KIND_PRIORITY = {CONTINUE: 0, BUFFER: 0, DOCK: 1, DIVERT: 2, MERGE: 3}


def edge_key(e):
    """The one total order of edges, wherever they are sorted or one is chosen: kind (continue < dock
    < divert < merge), src, dst, a share before none, the share."""
    return (_KIND_PRIORITY.get(e.kind, len(_KIND_PRIORITY)), str(e.src), str(e.dst), e.share is None,
            -1.0 if e.share is None else float(e.share))


# ---------------------------------------------------------------------------
# Items, pitch, flow
# ---------------------------------------------------------------------------

def item_length(load, default=0.0):
    """The length along travel of a `wh_load` record (dict), else `default`."""
    try:
        value = float((load or {}).get("length_m", default))
    except (TypeError, ValueError, AttributeError):
        return default
    return value if value > 0.0 and math.isfinite(value) else default


def default_speed(load_or_kind):
    """The default goods speed (m/s) for a `wh_load` record or a load kind: pallet and long 0.2,
    tote, carton and custom 0.5."""
    kind = load_or_kind.get("kind") if isinstance(load_or_kind, dict) else load_or_kind
    return DEFAULT_SPEEDS.get(kind, DEFAULT_SPEED)


def full_pitch(length, gap=GAP_AT_FULL_M):
    """Item centre to item centre at population 1."""
    return max(float(length), 0.0) + gap


def pitch(population, length, gap=GAP_AT_FULL_M):
    """Item centre to item centre at `population` (inf when empty)."""
    return full_pitch(length, gap) / population if population > EPS else INF


def flow(population, speed, length, gap=GAP_AT_FULL_M):
    """Items per second of a stream."""
    if population <= 0.0 or speed <= 0.0:
        return 0.0
    return population * speed / full_pitch(length, gap)


def population_for_flow(items_per_s, speed, length, gap=GAP_AT_FULL_M):
    """The population that carries `items_per_s` at `speed` (not capped: > 1 means it cannot)."""
    if items_per_s <= 0.0:
        return 0.0
    if speed <= 0.0:
        return INF
    return items_per_s * full_pitch(length, gap) / speed


def population_from_rate(rate_ph, speed, length, gap=GAP_AT_FULL_M):
    """A legacy items-per-hour rate as a population: rate x (L + gap) / (3600 x v), not capped."""
    return population_for_flow(max(float(rate_ph), 0.0) / 3600.0, speed, length, gap)


def follow(population, speed, length, to_speed, to_length, share=1.0, gap=GAP_AT_FULL_M):
    """A follower's population: `share` of the leader's flow at the follower's own speed and item."""
    return population_for_flow(share * flow(population, speed, length, gap), to_speed, to_length, gap)


def population_cap(items_per_hour, speed, length, gap=GAP_AT_FULL_M):
    """The most a source (or sink) that handles at most `items_per_hour` can fill a stream running at
    `speed`, as a population (0..1)."""
    return min(1.0, population_from_rate(max(items_per_hour, 0.0), speed, length, gap))


def population_for_activity(activity, items_per_hour, speed, length, gap=GAP_AT_FULL_M):
    """A limited source's slider: `activity` (0..1) of the most it makes (cranes flat out = 1)."""
    return min(max(activity, 0.0), 1.0) * population_cap(items_per_hour, speed, length, gap)


def cap(population, max_population=None):
    """Occupancy capped at 1 and at a sink's `max_population`."""
    limit = 1.0 if max_population is None else min(1.0, max(max_population, 0.0))
    return min(max(population, 0.0), limit)


# ---------------------------------------------------------------------------
# Shares
# ---------------------------------------------------------------------------

def split_order(edges):
    """The branches leaving one point in the order every add-on uses (fractions, `branch_of_item`):
    the edges with an explicit share by their `dst`, then those without one (the remainder) by `dst`;
    ties (parallel edges) by `edge_key`."""
    explicit = sorted((e for e in edges if e.share is not None), key=lambda e: (str(e.dst), edge_key(e)))
    rest = sorted((e for e in edges if e.share is None), key=lambda e: (str(e.dst), edge_key(e)))
    return explicit + rest


def split_report(shares):
    """(fractions, unassigned, oversplit) of the branches leaving one point, in their split order.

    Explicit shares (0..1) stand as given, scaled down when they add up to more than 1 (`oversplit` =
    their total, else None); branches without a share (None: the remainder) share what is left equally
    (a single remainder branch takes it all). With no remainder branch and explicit shares adding up to
    less than 1, `unassigned` = 1 - total: the source simply sends that much less (nothing vanishes)."""
    explicit = [min(max(float(s), 0.0), 1.0) for s in shares if s is not None]
    total = sum(explicit)
    scale = 1.0 / total if total > 1.0 + EPS else 1.0
    rest = max(0.0, 1.0 - total * scale)
    n_free = sum(1 for s in shares if s is None)
    fractions = [rest / n_free if s is None else min(max(float(s), 0.0), 1.0) * scale for s in shares]
    unassigned = rest if n_free == 0 and rest > EPS and shares else None
    return fractions, unassigned, (total if total > 1.0 + EPS else None)


def split_fractions(shares):
    """The local fractions of `split_report`."""
    return split_report(shares)[0]


def absolute_share(local_fractions):
    """The share of the stream's root: the product of the local fractions along the path."""
    out = 1.0
    for f in local_fractions:
        out *= f
    return out


def share_of_master(node_absolute, master_absolute):
    """A node's share as a fraction OF THE MASTER (absolute shares from the root)."""
    return node_absolute / master_absolute if master_absolute > EPS else 0.0


def local_from_absolute(child_of_master, parent_of_master):
    """The local fraction to store on a link when the user types the branch's % of the master."""
    if parent_of_master <= EPS:
        return 0.0
    return min(max(child_of_master / parent_of_master, 0.0), 1.0)


def branch_of_item(k, fractions):
    """(branch, index) of item k at a split, so that every add-on sends the same items the same way.

    k is the item's number in the stream: the k-th item centre to cross the stream origin,
    k = round((t_cross - phase_s) / period_s), negative for items already on the line at t = 0.
    `fractions` are the split's local fractions in `split_order`. Branch 0 takes its share of the items
    evenly (Bresenham), branch 1 its share of those branch 0 left, and so on; over any run of items
    each branch gets its fraction to within one item. `branch` is None for an item no branch takes
    (fractions adding up to < 1). `index` is the item's number in the stream it goes on in: among the
    items of its branch, or among the items no branch took. It is what a further split downstream
    uses as its k (a line with several diverters in a row), and it numbers those items 0, 1, 2 ...
    without gaps, negative ones included."""
    index, remaining = int(k), 1.0
    for j, f in enumerate(fractions):
        if remaining <= EPS:
            return None, index
        q = min(max(f / remaining, 0.0), 1.0)
        taken_before = math.floor(index * q + EPS)
        taken_with = math.floor((index + 1) * q + EPS)
        if taken_with > taken_before:
            return j, taken_before
        index -= taken_with                     # its number among the items this branch leaves
        remaining -= f
    return None, index


# ---------------------------------------------------------------------------
# Animation sync: period, phase and piecewise schedules
# ---------------------------------------------------------------------------

def period(population, speed, length, gap=GAP_AT_FULL_M):
    """Seconds between item centres crossing a point (inf when empty). Equal to 1 / flow."""
    f = flow(population, speed, length, gap)
    return 1.0 / f if f > 0.0 else INF


def travel_time(segments):
    """Seconds from the stream origin along `segments` [(length m, speed m/s)], e.g. a rack's own
    delivery conveyor at its speed, then a line at its own."""
    t = 0.0
    for length, speed in segments:
        if speed <= 0.0:
            return INF
        t += max(float(length), 0.0) / speed
    return t


def phase(seconds_from_origin, period_s):
    """`phase_s` at a point: an item centre crosses the stream origin at t = 0 (and every period),
    so it crosses a point that far downstream at phase + k x period."""
    if not math.isfinite(period_s) or period_s <= 0.0 or not math.isfinite(seconds_from_origin):
        return 0.0
    return seconds_from_origin % period_s


def phase_at(distance, speed, period_s):
    """`phase_s` at `distance` metres down a stream running at `speed` throughout."""
    return phase(travel_time([(distance, speed)]), period_s)


def crossing_times(phase_s, period_s, t0, t1):
    """phase + k x period for every integer k with t0 <= time <= t1, ascending."""
    if not math.isfinite(period_s) or period_s <= 0.0:
        return []
    k = math.ceil((t0 - phase_s) / period_s - 1e-9)
    out = []
    while phase_s + k * period_s <= t1 + 1e-9:
        out.append(phase_s + k * period_s)
        k += 1
    return out


def _segments(schedule):
    """[(k0, c0, period)]: item k of a segment crosses at c0 + (k - k0) x period; segment i holds the
    items from its k0 to the next segment's k0 - 1 (segment 0 from minus infinity)."""
    sched = sorted(schedule, key=lambda s: s[0])
    if not sched:
        return []
    _t, ph, per = sched[0]
    segs = [(0, float(ph or 0.0), per)]
    for t_from, ph_i, per_i in sched[1:]:
        k_last = _last_before(segs, t_from)
        c_last = _crossing(segs, k_last) if k_last is not None else -INF
        k0 = (k_last + 1) if k_last is not None else segs[-1][0]
        if not math.isfinite(per_i) or per_i <= 0.0:
            segs.append((k0, INF, INF))
        elif ph_i is None:                            # chained: one new period after the last old item
            segs.append((k0, c_last + per_i if math.isfinite(c_last) else t_from, per_i))
        else:                                         # on its own lattice, after both t_from and the last item
            start = max(t_from, c_last + 1e-9) if math.isfinite(c_last) else t_from
            n = math.ceil((start - ph_i) / per_i - 1e-12)
            segs.append((k0, ph_i + n * per_i, per_i))
    return segs


def _crossing(segs, k):
    seg = segs[0]
    for s in segs[1:]:
        if k >= s[0]:
            seg = s
    k0, c0, per = seg
    if not math.isfinite(per) or per <= 0.0 or not math.isfinite(c0):
        return INF                                   # a stopped stream: no (more) items
    return c0 + (k - k0) * per


def _last_before(segs, t, inclusive=False):
    """The last item crossing before t (at or before it with `inclusive`), or None."""
    best = None
    for i, (k0, c0, per) in enumerate(segs):
        k_end = segs[i + 1][0] - 1 if i + 1 < len(segs) else None
        if not math.isfinite(per) or not math.isfinite(c0) or per <= 0.0:
            continue
        x = (t - c0) / per
        k = k0 + (math.floor(x + 1e-9) if inclusive else math.ceil(x - 1e-9) - 1)
        if i > 0 and k < k0:
            continue
        if k_end is not None:
            k = min(k, k_end)
        best = k if best is None else max(best, k)
    return best


class CompiledSchedule:
    """A schedule prepared once (`compile_schedule`): crossing_time, item_index and buffer_item_times
    take it in place of the list, without rebuilding its segments for every item."""
    __slots__ = ("entries", "segments")

    def __init__(self, schedule):
        self.entries = sorted(schedule, key=lambda s: s[0])
        self.segments = _segments(self.entries)


def compile_schedule(schedule):
    return schedule if isinstance(schedule, CompiledSchedule) else CompiledSchedule(schedule)


def _segs_of(schedule):
    return schedule.segments if isinstance(schedule, CompiledSchedule) else _segments(schedule)


def crossing_time(k, schedule):
    """When item k crosses the point a `schedule` describes: [(t_from, phase_s, period_s)], one entry
    per rate the stream has had, by start time. Items cross at phase_s + k x period_s on the first
    entry; from each later t_from the next item follows the last one at the new period (phase_s None:
    chained, so items already on their way keep their times) or on that entry's own lattice (phase_s
    given). A period of inf stops the stream. Closed form: O(entries) per item, nothing baked."""
    segs = _segs_of(schedule)
    return _crossing(segs, int(k)) if segs else INF


def item_index(t, schedule):
    """The last item k that has crossed by time t (crossing_time(k) <= t), or None before the first."""
    segs = _segs_of(schedule)
    return _last_before(segs, t, inclusive=True) if segs else None


def switched_schedule(schedule, t_switch, period_s, phase_s=None):
    """`schedule` with the stream's rate changed at `t_switch` (chained by default)."""
    entries = schedule.entries if isinstance(schedule, CompiledSchedule) else list(schedule)
    return sorted(entries + [(t_switch, phase_s, period_s)], key=lambda s: s[0])


MAX_ARRIVALS = 200000


def item_on_path(k, path):
    """The item's number in the stream it reaches after `path`, or None when a split on the way sends
    it elsewhere. `path` = [(fractions, branch), ...] from the stream origin: each split's local
    fractions in `split_order` and the branch this point lies on (None: the items no branch takes)."""
    index = int(k)
    for fractions, branch in path:
        taken, index = branch_of_item(index, fractions)
        if taken != branch:
            return None
    return index


def branch_arrivals(schedule, path, t0, t1, delay_s=0.0):
    """When items ARRIVE at a point behind one or more splits, exactly as `branch_of_item` deals them
    (WC 0.6.2, R22.4): a branch gets an uneven pattern (30 % takes items 0, 3, 6, 10 ...), which an
    averaged period cannot reproduce at a hand-over. `schedule` = the stream's crossings at its origin
    (list or `compile_schedule`), `path` as in `item_on_path`, `delay_s` = the travel time from the
    origin to the point (seconds, the same clock as the schedule). Returns the arrival times in
    [t0, t1], ascending. Merges on the way are not covered: readers fall back to period_s / phase_s."""
    sched = compile_schedule(schedule)
    if not sched.segments:
        return []
    k = item_index(t0 - delay_s, sched)
    if k is None:
        k = 0
    else:                                                     # back to the first item arriving at t0 or later
        while math.isfinite(crossing_time(k, sched)) and crossing_time(k, sched) + delay_s >= t0 - 1e-9:
            k -= 1
        k += 1
    out = []
    for _ in range(MAX_ARRIVALS):
        t = crossing_time(k, sched)
        if not math.isfinite(t) or t + delay_s > t1 + 1e-9:
            break
        if t + delay_s >= t0 - 1e-9 and item_on_path(k, path) is not None:
            out.append(t + delay_s)
        k += 1
    return out


# ---------------------------------------------------------------------------
# Buffers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BufferState:
    queued: float                # items in the buffer at t (fractional: the add-on rounds for display)
    accepted: float              # items per second it takes in at t
    released: float              # items per second it lets out at t
    full_at: float               # time it became / becomes full (inf: never)


def buffer_fill(t, in_flow, out_fraction, capacity_items, t0=0.0, initial=0.0):
    """The aggregate of a buffer that lets out `out_fraction` (Output %) of what arrives: the rest piles
    up from t0 on until `capacity_items`; once full it accepts only what it lets out. For panels and
    tests; the animation uses `buffer_item_times`."""
    out_fraction = min(max(out_fraction, 0.0), 1.0)
    capacity_items = max(capacity_items, 0.0)
    in_flow = max(in_flow, 0.0)
    released = in_flow * out_fraction
    growth = in_flow - released
    start = min(max(initial, 0.0), capacity_items)
    full_at = t0 + (capacity_items - start) / growth if growth > EPS else INF
    if t <= t0:
        return BufferState(start, in_flow if start < capacity_items else released, released, full_at)
    if t >= full_at:
        return BufferState(capacity_items, released, released, full_at)
    return BufferState(start + growth * (t - t0), in_flow, released, full_at)


def buffer_item_times(k, schedule, out_fraction, capacity_items, t0=0.0):
    """(enters_s, leaves_s) of item k at a FIFO buffer: `schedule` = the items' arrival at its entry
    (see `crossing_time`). Items arriving before t0 pass straight through. From t0 the buffer lets out
    one item per in-period / out_fraction (Output %); the rest wait inside, at most `capacity_items`;
    once full, item k enters only when item k - capacity has left, so further goods visibly wait at
    the entry. Switch the stream's root to the capped rate at the time the buffer fills
    (`switched_schedule`) and the entry queue is at most the surplus already on its way. Closed form:
    nothing baked. leaves_s is inf for items that never leave (Output 0 %)."""
    schedule = compile_schedule(schedule)
    arrive = crossing_time(k, schedule)
    segs = schedule.segments
    first = _last_before(segs, t0) if segs else None
    k_start = (first + 1) if first is not None else int(k)
    if k < k_start or not math.isfinite(arrive):
        return arrive, arrive
    a_start = crossing_time(k_start, schedule)
    p_in = crossing_time(k_start + 1, schedule) - a_start
    out_fraction = min(max(out_fraction, 0.0), 1.0)
    p_out = p_in / out_fraction if out_fraction > EPS and math.isfinite(p_in) else INF
    capacity = max(int(capacity_items), 0)

    def base(j):                                     # when item j is let out if nothing held it up
        if j <= k_start:
            return a_start if j == k_start else -INF
        return a_start + (j - k_start) * p_out if math.isfinite(p_out) else INF
    leaves = max(arrive, base(k)) if math.isfinite(p_out) or k == k_start else INF
    if out_fraction <= EPS:
        leaves = INF
    if k - k_start < capacity:
        enters = arrive
    else:
        before = k - capacity
        left = INF if out_fraction <= EPS else max(crossing_time(before, schedule), base(before))
        enters = max(arrive, left)
    return enters, leaves


# ---------------------------------------------------------------------------
# The stream graph: masters, shares, merges and caps
# ---------------------------------------------------------------------------

@dataclass
class Node:
    """A populated thing: a port, a line section, a system with its own sliders. `population` /
    `speed` are its own sliders (used when it is the master); `item_length` its goods along travel;
    `max_population` a sink's limit. `own_speed` keeps its own speed instead of the master's: only
    where a new stream starts, a port -> line dock (the line keeps its Speed slider and gets the
    flow-conserved population; the port keeps its own speed)."""
    id: str
    population: float = 0.0
    speed: float = 0.0
    item_length: float = 0.0
    master: bool = False
    own_speed: bool = False
    max_population: float = None


@dataclass
class Edge:
    """Goods go from `src` to `dst`. `share`: the local fraction at a split (None: the remainder)."""
    src: str
    dst: str
    kind: str = CONTINUE
    share: float = None


@dataclass
class NodeFlow:
    master: str                  # the stream's master node id
    stream: str                  # the stream's root node id
    population: float            # what the node shows (0..1, capped)
    speed: float
    flow: float                  # items per second
    share_of_root: float         # absolute share along the main path
    share_of_master: float       # the node's share of the master's stream (absolute / master's)
    period: float                # seconds (1 / flow; inf when empty)
    capped: bool = False         # a cap (1, max_population, a full merge) held this node back
    overflow: float = 0.0        # items/s cut at this merge (the feeders were slowed by that much)
    is_master: bool = False
    merged_flow: float = 0.0     # items/s merged in upstream on its own path (and here)
    below_master: bool = False   # the master or downstream of it on the main path


@dataclass
class Resolution:
    nodes: dict = field(default_factory=dict)          # node id -> NodeFlow
    cycles: list = field(default_factory=list)         # [[node ids]]: main paths that loop
    conflicts: list = field(default_factory=list)      # [[flagged ids]]: streams with several masters
    stream_cycles: list = field(default_factory=list)  # [[root ids]]: merges that loop between streams
    unassigned: list = field(default_factory=list)     # [(split node, 1 - total)]: no remainder branch
    oversplit: list = field(default_factory=list)      # [(split node, total)]: shares scaled down
    splits: dict = field(default_factory=dict)         # split node -> [(dst, kind, fraction)] in split order
    loops: list = field(default_factory=list)          # [(divert src, divert dst, merge src, merge dst)]:
                                                       # a recirculation, its branch runs as its own stream
    buffered: list = field(default_factory=list)       # [(node before the buffer exit, 1 - Output %)]: what
                                                       # accumulates inside (0.6.5, R22.6), not lost


def share_text(nodeflow, master_name):
    """What a panel shows for a node, never a number above 100 %: "Master", "30 % of <master>" (with
    " + merged" when goods merge in on its way), or "Stream of <master>" for a node upstream of a
    flagged master or on a sibling branch."""
    if nodeflow.is_master:
        return "Master"
    if nodeflow.below_master:
        text = "%d %% of %s" % (round(100.0 * min(nodeflow.share_of_master, 1.0)), master_name)
        return text + (" + merged" if nodeflow.merged_flow > EPS else "")
    return "Stream of %s" % master_name


def _main_parents(main_edges):
    """node id -> its incoming main edge: of several, the first by `edge_key` (continue < dock <
    divert, then src ...). Returns (parent, losers): the others stay in their source's split and merge
    their part of it into the node."""
    candidates = {}
    for e in sorted(main_edges, key=edge_key):
        candidates.setdefault(e.dst, []).append(e)
    parent, losers = {}, []
    for dst in sorted(candidates):
        parent[dst] = candidates[dst][0]
        losers += candidates[dst][1:]
    return parent, losers


def _streams(nodes, parent, res):
    """Root of every node's stream, breaking main-path cycles (reported) at a flagged node, else at
    the smallest id."""
    root = {}
    for nid in sorted(nodes):
        path, seen, cur = [], set(), nid
        while cur in parent and cur not in seen and cur not in root:
            seen.add(cur)
            path.append(cur)
            cur = parent[cur].src
        if cur in root:
            r = root[cur]
        elif cur in seen:                                        # a loop
            loop = path[path.index(cur):]
            flagged = sorted(n for n in loop if nodes[n].master)
            r = flagged[0] if flagged else min(loop)
            if sorted(loop) not in [sorted(c) for c in res.cycles]:
                res.cycles.append(sorted(loop))
            del parent[r]                                        # cut the loop at r
            root[r] = r
        else:
            r = cur
            root[r] = r
        for n in path:
            root[n] = r
    return root


def _depth_order(r, kids):
    out, todo = [], [r]
    while todo:
        n = todo.pop(0)
        out.append(n)
        todo += [e.dst for e in kids.get(n, [])]
    return out


def resolve(nodes, edges, default_speed=0.0):
    """Population, speed, flow and shares of every node of a stream graph.

    `nodes`: {id: Node} (or an iterable of Node); `edges`: [Edge]. Each stream is a tree of main edges
    (continue, dock, divert) from its root; its master is the most upstream node flagged `master`,
    else the root. The master's own sliders set the stream: every node gets the master's flow scaled
    by the shares (and adds the flow merging into it from feeder streams, which are resolved first).
    A node's speed is the master's unless `own_speed`. Goods enter only at nodes nothing comes into: a
    stream whose root a feeder merges into carries just what merges in (a master that wanted more is
    marked capped). Caps (occupancy 1, `max_population`) slow the
    whole stream at its root so that nothing vanishes. Where a merge would overflow even with its main
    stream stopped, the feeders are slowed at their roots in proportion (one more pass) and the cut is
    reported as `overflow` on the merge node.

    A merge within one stream either RE-JOINS it (a bypass: its goods add back, as the stream's own) or
    RECIRCULATES into a node upstream of its source: then the last divert on the way from that node to
    the source is cut, its branch runs as its own stream (own sliders, like a feeder) and the merge back
    stays as a feeder merge; reported in `loops`. A recirculation with no divert on the way is a cycle:
    the merge is dropped and reported in `cycles`.
    """
    if not isinstance(nodes, dict):
        nodes = {n.id: n for n in nodes}
    first = _resolve_once(nodes, edges, default_speed, {})
    feeder_caps = {}
    for nid, nf in first.nodes.items():
        if nf.overflow <= 0.0:
            continue
        feeds = [(e, first.nodes[e.src].flow) for e in first.merges if e.dst == nid and e.src in first.nodes]
        merged = sum((1.0 if e.share is None else min(max(e.share, 0.0), 1.0)) * f for e, f in feeds)
        if merged <= EPS:
            continue
        keep = max(0.0, merged - nf.overflow) / merged
        for e, f in feeds:
            feeder_caps[e.src] = min(feeder_caps.get(e.src, INF), f * keep)
    if not feeder_caps:
        return first.result
    second = _resolve_once(nodes, edges, default_speed, feeder_caps)
    for nid, nf in first.nodes.items():
        if nf.overflow > 0.0:
            second.nodes[nid].overflow = nf.overflow
            second.nodes[nid].capped = True
    for nid in feeder_caps:
        second.nodes[nid].capped = True
    return second.result


@dataclass
class _Pass:
    result: Resolution
    merges: list

    @property
    def nodes(self):
        return self.result.nodes


def _recirculations(nodes, parent, merges, res):
    """Cut every recirculation (a same-stream merge into an ancestor of its source) at the last divert
    on its way, reported in res.loops; drop those with no divert (res.cycles). Returns (root, merges)."""
    root = _streams(nodes, parent, res)
    merges = sorted(merges, key=edge_key)
    while True:
        for i, e in enumerate(merges):
            if root[e.src] != root[e.dst]:
                continue
            below, cur, upstream = [], e.src, False
            while True:
                if cur == e.dst:
                    upstream = True
                    break
                if cur not in parent:
                    break
                below.append(cur)
                cur = parent[cur].src
            if not upstream:
                continue                                         # a re-join: dealt with in the stream
            divert = next((parent[n] for n in below if parent[n].kind == DIVERT), None)
            if divert is not None:
                del parent[divert.dst]
                res.loops.append((divert.src, divert.dst, e.src, e.dst))
            else:
                loop = sorted(set(below) | {e.dst})
                if loop not in res.cycles:
                    res.cycles.append(loop)
                merges = merges[:i] + merges[i + 1:]
            root = _streams(nodes, parent, res)
            break
        else:
            return root, merges


def _resolve_once(nodes, edges, default_speed, flow_caps):
    res = Resolution()
    # Fresh copies in the one total order: nothing below depends on the order the edges came in.
    main_kind = [Edge(e.src, e.dst, e.kind, e.share) for e in sorted(
        (e for e in edges if e.kind in MAIN_KINDS and e.src in nodes and e.dst in nodes), key=edge_key)]
    parent, losers = _main_parents(main_kind)
    # A main edge that lost its node to another stays in its source's split and merges its part there
    # (its share is set once the split is known, after the recirculation cuts).
    loser_merges = [Edge(e.src, e.dst, MERGE, e.share) for e in losers]
    placeholder = {id(m): e for m, e in zip(loser_merges, losers)}     # loser_merges keeps the ids alive
    merges = [Edge(e.src, e.dst, MERGE, e.share) for e in sorted(
        (e for e in edges if e.kind == MERGE and e.src in nodes and e.dst in nodes), key=edge_key)]
    merges += loser_merges
    root, merges = _recirculations(nodes, parent, merges, res)
    split_edges = {}
    for e in list(parent.values()) + losers:
        split_edges.setdefault(e.src, []).append(e)
    kids, fractions, fraction_of = {}, {}, {}
    for src in sorted(split_edges):
        ordered = split_order(split_edges[src])
        fr, unassigned, oversplit = split_report([e.share for e in ordered])
        if len(ordered) == 1 and ordered[0].kind == BUFFER:
            # a buffer's exit passes Output % on; the rest piles up inside (buffer_fill), nothing is lost
            out = 1.0 if ordered[0].share is None else min(max(float(ordered[0].share), 0.0), 1.0)
            fr, unassigned, oversplit = [out], None, None
            if out < 1.0 - EPS:
                res.buffered.append((src, 1.0 - out))
        for e, f in zip(ordered, fr):
            fraction_of[id(e)] = f
            if parent.get(e.dst) is e:
                fractions[(e.src, e.dst)] = f
        kids[src] = [e for e in ordered if parent.get(e.dst) is e]
        if len(ordered) > 1 or any(e.kind == DIVERT for e in ordered):
            res.splits[src] = [(e.dst, e.kind, f) for e, f in zip(ordered, fr)]
        if unassigned is not None:
            res.unassigned.append((src, unassigned))
        if oversplit is not None:
            res.oversplit.append((src, oversplit))
    merges = sorted((Edge(m.src, m.dst, MERGE, fraction_of[id(placeholder[id(m)])]) if id(m) in placeholder else m
                     for m in merges), key=edge_key)
    feeders = [e for e in merges if root[e.src] != root[e.dst]]
    rejoins = {}
    for e in merges:
        if root[e.src] == root[e.dst]:
            rejoins.setdefault(root[e.src], []).append(e)
    members = {}
    for nid, r in root.items():
        members.setdefault(r, []).append(nid)

    # Order the streams: a stream after every stream feeding into it.
    feeds = {r: set() for r in members}
    for e in feeders:
        feeds[root[e.dst]].add(root[e.src])
    order, state = [], {}

    def visit(r, trail):
        if state.get(r) == 2:
            return
        if state.get(r) == 1:
            loop = trail[trail.index(r):]
            if sorted(loop) not in [sorted(c) for c in res.stream_cycles]:
                res.stream_cycles.append(sorted(loop))
            return
        state[r] = 1
        for f in sorted(feeds[r]):
            visit(f, trail + [r])
        state[r] = 2
        order.append(r)
    for r in sorted(members):
        visit(r, [])

    for r in order:
        _resolve_stream(r, nodes, parent, kids, fractions, rejoins.get(r, []), feeders, root, res, default_speed,
                        flow_caps)
    return _Pass(res, feeders)


def _stream_order(r, members, parent, rejoins, res):
    """The stream's nodes in a topological order over its main edges and re-joins (ready nodes by id);
    a ring of re-joins (none recirculates alone) is broken at its largest merge, reported as a cycle."""
    rejoins = sorted(rejoins, key=edge_key)
    while True:
        indeg = {n: 0 for n in members}
        succ = {n: [] for n in members}
        for n in members:
            if n in parent and n != r:
                succ[parent[n].src].append(n)
                indeg[n] += 1
        for e in rejoins:
            succ[e.src].append(e.dst)
            indeg[e.dst] += 1
        ready = sorted(n for n in members if indeg[n] == 0)
        out = []
        while ready:
            n = ready.pop(0)
            out.append(n)
            for d in succ[n]:
                indeg[d] -= 1
                if indeg[d] == 0:
                    ready.append(d)
                    ready.sort()
        if len(out) == len(members):
            return out, rejoins
        left = set(members) - set(out)
        ring = [e for e in rejoins if e.src in left and e.dst in left]
        cut = ring[-1]
        loop = sorted(left)
        if loop not in res.cycles:
            res.cycles.append(loop)
        rejoins = [e for e in rejoins if e is not cut]


def _resolve_stream(r, nodes, parent, kids, fractions, rejoins, feeders, root, res, default_speed, flow_caps):
    members = _depth_order(r, kids)
    depth = {r: 0}
    for n in members[1:]:
        depth[n] = depth[parent[n].src] + 1
    order, rejoins = _stream_order(r, members, parent, rejoins, res)
    flagged = sorted((n for n in members if nodes[n].master), key=lambda n: (depth[n], n))
    if len(flagged) > 1:
        res.conflicts.append(flagged)
    m = flagged[0] if flagged else r
    master = nodes[m]
    speed_m = master.speed if master.speed > 0.0 else default_speed
    joins_into = {}
    for e in rejoins:
        joins_into.setdefault(e.dst, []).append(e)
    below = {m}
    for n in order:
        if (n in parent and n != r and parent[n].src in below) or any(e.src in below for e in joins_into.get(n, [])):
            below.add(n)

    def speed_of(n):
        node = nodes[n]
        return node.speed if node.own_speed and node.speed > 0.0 else speed_m

    def length_of(n):
        return nodes[n].item_length if nodes[n].item_length > 0.0 else master.item_length

    def merge_share(e):
        return 1.0 if e.share is None else min(max(e.share, 0.0), 1.0)

    # Flow merging in from feeder streams (already resolved), at each node.
    merge_in = {n: 0.0 for n in members}
    for e in feeders:
        if e.dst in merge_in and e.src in res.nodes:
            merge_in[e.dst] += merge_share(e) * res.nodes[e.src].flow
    # flow(n) = A(n) x F_root + B(n): A the stream's own goods (the absolute share, re-joins added back),
    # B the goods merged in from feeders and carried down.
    A, B = {}, {}
    for n in order:
        if n == r:
            A[n], B[n] = 1.0, merge_in[n]
        else:
            p = parent[n].src
            f = fractions.get((p, n), 1.0)
            A[n], B[n] = A[p] * f, B[p] * f + merge_in[n]
        for e in joins_into.get(n, []):
            A[n] += merge_share(e) * A[e.src]
            B[n] += merge_share(e) * B[e.src]
    target = flow(cap(master.population, master.max_population), speed_m, length_of(m))
    # 0.6.3: a master its own max_population clamps is capped too (R22.3: it still publishes its slider)
    self_clamped = cap(master.population, master.max_population) < cap(master.population) - 1e-12
    wanted = max(0.0, (target - B[m]) / A[m]) if A[m] > EPS else 0.0
    # Goods enter the graph only where nothing comes in: a stream whose root a feeder merges into is no
    # source, it carries what merges in (its master is marked capped when it wanted more).
    fed_root = any(e.dst == r for e in feeders)
    short = fed_root and wanted > 1e-12
    if fed_root:
        wanted = 0.0

    def limit_flow(n):
        sp = speed_of(n)
        lim = flow(cap(1.0, nodes[n].max_population), sp, length_of(n)) if sp > 0.0 else INF
        return min(lim, flow_caps.get(n, INF))
    # Caps: the largest root flow that keeps every node within its limit.
    F = wanted
    for n in order:
        if A[n] > EPS and A[n] * F + B[n] > limit_flow(n) + 1e-12:
            F = max(0.0, (limit_flow(n) - B[n]) / A[n])
    held = F < wanted - 1e-12
    for n in order:
        f_n = A[n] * F + B[n]
        sp, lim = speed_of(n), limit_flow(n)
        overflow = max(0.0, f_n - lim)
        f_n -= overflow
        pop = cap(population_for_flow(f_n, sp, length_of(n)) if sp > 0.0 else 0.0, nodes[n].max_population)
        at_limit = math.isfinite(lim) and f_n >= lim - 1e-12 and f_n > 0.0
        res.nodes[n] = NodeFlow(master=m, stream=r, population=pop, speed=sp, flow=f_n, share_of_root=A[n],
                                share_of_master=share_of_master(A[n], A[m]),
                                period=(1.0 / f_n) if f_n > 0.0 else INF,
                                capped=(held and at_limit) or overflow > 0.0 or ((short or self_clamped) and n == m),
                                overflow=overflow, is_master=(n == m), merged_flow=B[n], below_master=(n in below))


# ---------------------------------------------------------------------------
# The graph from the published records
# ---------------------------------------------------------------------------

def _num(value, default=None):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _frac(value):
    v = _num(value)
    return None if v is None else min(max(v, 0.0), 1.0)


BOUNDARY_TOL_M = 0.001       # line ports within this of the same u_m are one section boundary


def build_graph(records):
    """(nodes {id: Node}, edges [Edge]) from the records the add-ons publish, one dict per object:
    {"system": wh_system, "ports": wh_ports list, "links": wh_port_links list, "load": wh_load or None}.

    - A system's port is the node "<system id>/<port id>"; an io port is two, "<sys>/<port>" (its out
      direction) and "<sys>/<port>:in". A system that publishes its own `population` (a rack that is
      one stream for all its delivery points) is the node "<sys>", with a divert to each of its out
      ports by the port's `share` (none: the remainder).
    - A conveyor line (wh_system kind "line") is one node per section: "<line>/line_in", then one per
      boundary in `u_m` order, each section continuing into the next. A boundary is every port other
      than line_in / line_out that is `taken` and has a numeric `u_m` (junction ports "j:<uuid>",
      right-angle-transfer faces "rat<i>_left | _right | _end"); ports within 1 mm of the same u_m are
      ONE boundary, the section "<line>/<first port id>". A line without boundaries is one node; a
      line's ports never split into ":in" nodes.
    - A line's links: starting at a system port, "<sys>/<port>" docks into the line's first section
      (`own_speed` on the line: it keeps its Speed); ending at one, its last section docks into
      "<sys>/<port>" (or "<sys>/<port>:in"). At another line's boundary: OUT of it (edge divert, or
      anchor start) the section BEFORE the boundary diverts into this line by the link's `share`, so
      every branch at one boundary is one split; INTO it (edge merge, or anchor end) a merge into the
      boundary's section. Ending at another line's line_in (or starting at its line_out): a continue.
      A link's `edge` overrides the kind.
    - Node sliders: `population` (an io port's IN node: `population_in`), `speed_m_s`, `master`,
      `max_population` and the item length (the port's `load`, else the object's) from the records.
      Links held by objects other than lines are skipped (they carry no port of their own)."""
    nodes, edges = {}, []
    systems, lines = {}, {}
    for rec in records:
        sysrec = rec.get("system") if isinstance(rec, dict) else None
        if not isinstance(sysrec, dict) or not sysrec.get("id"):
            continue
        systems[str(sysrec["id"])] = rec
        if sysrec.get("kind") == "line":
            lines[str(sysrec["id"])] = rec

    raw = {}                     # system port node id -> (record, load, population key, sink side)

    def node_from(nid, src, load, population_key="population", sink=False):
        length = item_length(src.get("load") or load)
        population, speed = _frac(src.get(population_key)), _num(src.get("speed_m_s"), 0.0)
        max_population = _frac(src.get("max_population"))
        legacy_speed = speed or _num(src.get("surface_speed_m_s"), 0.0) or default_speed(src.get("load") or load)
        if population is None:
            # 0.6.3, the R22 transition: a port that publishes only a legacy rate (rate_ph, an io port's
            # in side rate_in_ph) stands in with the population that carries that rate, at its own speed,
            # exactly as the add-ons' readers already do. Drop once every writer publishes population.
            rate = _num(src.get("rate_in_ph" if population_key == "population_in" else "rate_ph"))
            if rate and rate > 0.0 and length > 0.0:
                speed = legacy_speed
                population = min(1.0, population_from_rate(rate, speed, length))
        if max_population is None and sink:
            # 0.6.4, the same transition for a sink: a legacy capacity_ph is its limit
            capacity = _num(src.get("capacity_ph"))
            if capacity and capacity > 0.0 and length > 0.0:
                max_population = min(1.0, population_from_rate(capacity, legacy_speed, length))
        return Node(nid, population=population or 0.0, speed=speed, item_length=length,
                    master=src.get("master") is True, max_population=max_population)

    def informed(pid):
        """Does a system port say anything about its flow? A population (even 0: a stopped source), a
        legacy rate, or its own system's stream feeding it. 0.6.4: a port that says nothing is no
        source; a line docked there leads with its own sliders."""
        if any(e.dst == pid for e in edges):
            return True
        src, _load, key, _sink = raw.get(pid, ({}, None, "population", False))
        return any(src.get(k) is not None for k in ((key, "rate_in_ph") if key == "population_in" else (key, "rate_ph")))

    def item_from_line(pid, line_rec):
        """0.6.4: a legacy port without any item size takes the docked line's item for its stand-ins."""
        if pid in raw and nodes[pid].item_length <= 0.0:
            src, _load, key, sink = raw[pid]
            line_in = next((p for p in (line_rec.get("ports") or []) if isinstance(p, dict) and p.get("id") == "line_in"), {})
            line_load = line_rec.get("load") or line_in.get("load")
            if item_length(line_load) > 0.0:
                nodes[pid] = node_from(pid, src, line_load, key, sink)

    sections, section_of, buffer_out = {}, {}, {}
    for sid, rec in systems.items():
        sysrec, load = rec["system"], rec.get("load")
        ports = [p for p in (rec.get("ports") or []) if isinstance(p, dict) and p.get("id") is not None]
        if sid in lines:
            line_in = next((p for p in ports if p.get("id") == "line_in"), {})
            bounds = sorted((p for p in ports if p.get("id") not in ("line_in", "line_out") and p.get("taken") is True
                             and _num(p.get("u_m")) is not None), key=lambda p: (_num(p.get("u_m")), str(p["id"])))
            groups = []
            for p in bounds:
                if groups and _num(p.get("u_m")) - _num(groups[-1][0].get("u_m")) <= BOUNDARY_TOL_M:
                    groups[-1].append(p)
                else:
                    groups.append([p])
            base = dict(line_in, **{k: sysrec[k] for k in ("population", "speed_m_s", "master") if k in sysrec})
            ids = ["%s/line_in" % sid]
            node = node_from(ids[0], base, load or line_in.get("load"))
            nodes[ids[0]] = node
            for group in groups:
                first = sorted(str(p["id"]) for p in group)[0]
                nid = "%s/%s" % (sid, first)
                limits = [m for m in (_frac(p.get("max_population")) for p in group) if m is not None]
                src = {k: base[k] for k in ("population", "speed_m_s") if k in base}
                section = node_from(nid, src, load or line_in.get("load"))
                section.max_population = min(limits) if limits else None
                nodes[nid] = section
                for p in group:
                    section_of[(sid, str(p["id"]))] = nid
                    if p.get("role") == "buffer":
                        out = _frac(p.get("out_fraction"))
                        buffer_out[nid] = 1.0 if out is None else out
                ids.append(nid)
            for a, b in zip(ids, ids[1:]):
                if b in buffer_out:                    # 0.6.5 (R22.6): the section after a buffer's exit
                    edges.append(Edge(a, b, BUFFER, buffer_out[b]))
                else:
                    edges.append(Edge(a, b, CONTINUE))
            sections[sid] = ids
            continue
        out_ports = []
        for p in ports:
            nid = "%s/%s" % (sid, p["id"])
            role = p.get("role")
            if role in ("out", "io", None):
                nodes[nid] = node_from(nid, p, load)
                raw[nid] = (p, load, "population", False)
                out_ports.append(p)
            if role == "in":
                nodes[nid] = node_from(nid, p, load, sink=True)
                raw[nid] = (p, load, "population", True)
            if role == "io":
                nodes[nid + ":in"] = node_from(nid + ":in", p, load, "population_in", sink=True)
                raw[nid + ":in"] = (p, load, "population_in", True)
        if _frac(sysrec.get("population")) is not None:
            # A rack carries its loads on its ports, not on its wh_system or object (WC 0.6.1): without
            # one of its own, the system node takes the item of its first out port by id that has one.
            if item_length(sysrec.get("load") or load) <= 0.0:
                load = next((p.get("load") for p in sorted(out_ports, key=lambda p: str(p["id"]))
                             if item_length(p.get("load")) > 0.0), load)
            nodes[sid] = node_from(sid, sysrec, load)
            for p in out_ports:
                edges.append(Edge(sid, "%s/%s" % (sid, p["id"]), DIVERT, _frac(p.get("share"))))

    for lid, rec in lines.items():
        first, last = sections[lid][0], sections[lid][-1]
        for link in rec.get("links") or []:
            if not isinstance(link, dict):
                continue
            target, port = str(link.get("system_id", "")), str(link.get("port", ""))
            anchor = link.get("anchor", "start")
            kind = link.get("edge")
            share = _frac(link.get("share"))
            if target in lines:
                boundary = section_of.get((target, port))
                if boundary is not None:
                    out = kind == DIVERT or (kind != MERGE and anchor == "start")
                    if out:
                        ids = sections[target]
                        before = ids[ids.index(boundary) - 1]
                        edges.append(Edge(before, first, kind or DIVERT, share))
                    else:
                        edges.append(Edge(last, boundary, kind or MERGE, share))
                elif port == "line_in" and anchor == "end":
                    edges.append(Edge(last, sections[target][0], kind or CONTINUE, share))
                elif port == "line_out" and anchor == "start":
                    edges.append(Edge(sections[target][-1], first, kind or CONTINUE, share))
                continue
            if target not in systems:
                continue
            pid = "%s/%s" % (target, port)
            if anchor == "start" and pid in nodes:
                item_from_line(pid, rec)
                if informed(pid):
                    edges.append(Edge(pid, first, kind or DOCK, share))
                    nodes[first].own_speed = True
            elif anchor == "end":
                into = pid + ":in" if pid + ":in" in nodes else pid
                if into in nodes:
                    item_from_line(into, rec)
                    edges.append(Edge(last, into, kind or DOCK, share))
    return nodes, edges
