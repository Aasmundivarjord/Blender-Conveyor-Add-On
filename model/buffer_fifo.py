"""Accumulation buffers as a FIFO (2.24; R22.6): what the
populate tree draws, in Python -- for operators/stream.py (the numbers it
hands the tree) and the unit tests. Pure: no bpy.

The buffer takes what the line before brings; Output %
of it leaves, the rest piles up -- filled with the goods from the line
before -- until the buffer is full; then it takes only what it lets out and
the line before follows. warehouse_common's buffer_item_times is the shared
truth: from t0 the buffer lets one item out every in-period / Output %
(FIFO), the rest wait inside, at most its zones; the stream's root is
switched to the capped rate when it is full. In the populate tree every item
keeps its slot of the stream's grid all the way: it rolls on until it meets
the queue, stands while the queue steps up one zone per departure, and
leaves the front stop at its departure time, behind its slot by the time it
waited. The root's switch is on the grid too: from the switch time the
root's slots are thinned to Output % (Bresenham), the items numbered on --
so every per-item time is within one in-period of buffer_item_times.

Coordinates are slot coordinates (an item's centre minus half a slot,
stream-wise); times are scene seconds; v is the on-screen speed.

The rank of an item at a buffer -- its number among the goods that reach it,
the FIFO order -- is the stream's item number when every slot passes it
(rank mode -1), the item's number among its owner's goods when one owner's
do (0), or its number after the first n route edges of the line's chain (n:
a buffer behind a split). `slot_owner` and `chain_index` repeat the populate
tree's deal (geonodes/populate.slot_owner, route_chain).
"""
from __future__ import annotations

import math

EPS = 1e-4  # geonodes/populate BRESENHAM_EPS


def deal(i: float, q: float) -> tuple[bool, int, float]:
    """One step of simple_flow.branch_of_item (the tree's _deal): an edge with
    local share q takes item i when floor((i + 1) q) > floor(i q). Returns
    (taken, its number among the taken, its number among those left)."""
    a = math.floor(i * q + EPS)
    b = math.floor((i + 1) * q + EPS)
    return b > a, a, i - b


def slot_owner(k: float, splits: list, sources: int) -> tuple[int, float]:
    """(owner, the item's number among that owner's): the root (0) and the
    feeders deal the stream's items in order, each its share evenly
    (`splits` = the cumulative Owner Split k, 1.0 when unused)."""
    if sources <= 0:
        return 0, k
    i, remaining, prev = k, 1.0, 0.0
    for j in range(len(splits) + 1):
        upper = splits[j] if j < len(splits) else 1.0
        frac = max(upper - prev, 0.0)
        q = min(frac / max(remaining, 1e-6), 1.0)
        taken, a, rest = deal(i, q)
        if taken:
            return j, a
        i = rest
        remaining -= frac
        prev = upper
    return 0, k


def chain_index(owner: int, index: float, chain: list, n: int) -> tuple[float, bool]:
    """(the item's number after the first `n` edges of the line's route chain,
    whether those edges leave it on this line's way). `chain` entries are
    operators/stream.py's (at, owner mask, share, class, hi, take, first,
    branch); an edge Routed by class is taken as not taking the item."""
    i, decided, stays = index, False, True
    for at, mask, q, _cls, _hi, take, first, _branch in chain[:max(n, 0)]:
        applies = mask > 0 and (mask >> int(owner)) & 1 == 1
        decided_now = decided and not first
        share = q >= 0.0
        dealt, a, rest = deal(i, max(q, 0.0))
        hit = dealt if share else False
        taken = applies and not decided_now and hit
        moved = applies and share and not decided_now
        if taken:
            i = a if share else i
        elif moved:
            i = rest
        decided = decided_now or taken
        away = (not taken) if take else taken  # this line's way: away unless taken; another way: away if taken
        if applies and away:
            stays = False
    return i, stays


def thinned(k: float, k_switch: float, fraction: float) -> tuple[bool, float]:
    """The root's grid slot k from the switch on: (it carries an item, that
    item's number). Before the switch every slot does, numbered as it is."""
    if k < k_switch:
        return True, k
    taken, a, _rest = deal(k - k_switch, fraction)
    return taken, k_switch + a


def departure(m: float, arrive: float, first: float, start: float, period: float, slug: int = 0) -> float:
    """When rank m leaves the front stop: items before `first` (in the buffer
    before t0) pass straight through; from `first` one every `period` (FIFO,
    never before it arrives) -- in a slug, the whole batch of `slug` together
    when its last member would have left."""
    if m < first or period <= 0.0:
        return arrive
    if slug > 0:
        batch = math.floor((m - first) / slug)
        return max(arrive, start + ((batch + 1) * slug - 1) * period)
    return max(arrive, start + (m - first) * period)


def front(t: float, first: float, start: float, period: float, slug: int = 0) -> float:
    """The first rank not gone by time t (the item at the front stop)."""
    if period <= 0.0 or t < start:
        return first
    if slug > 0:
        done = math.floor((t - start - (slug - 1) * period) / (slug * period)) + 1 if t >= start + (slug - 1) * period else 0
        return first + max(done, 0) * slug
    return first + math.floor((t - start) / period) + 1


def shown(x: float, t: float, v: float, stop: float, pitch: float, m: float, first: float, start: float,
          period: float, slug: int = 0) -> float:
    """Where an item whose slot coordinate is `x` at scene second t is drawn
    (the populate tree's formula): before the queue it rolls on; in it, it
    stands its rank's zone behind the front stop, stepping up (at the belt's
    speed) as the front leaves -- one zone, or a slug's worth; it leaves its
    spot at its departure and goes on, behind its slot by the time it
    waited."""
    if v <= 0.0 or period <= 0.0 or m < first:
        return x
    arrive = t - (x - stop) / v  # when its slot reaches the front stop
    j = (m - first) % slug if slug > 0 else 0  # its place in a slug, from the front
    leave = departure(m, arrive - j * pitch / v, first, start, period, slug)  # from its spot
    if t >= leave:
        return stop - j * pitch + v * (t - leave)
    head = front(t, first, start, period, slug)
    spot = stop - (m - head) * pitch
    if head > first:
        last = start + (head - first - 1) * period  # when the front last moved off
        spot -= max(0.0, pitch * (slug if slug > 0 else 1) - v * (t - last))
    return min(x, spot)


def full_after(capacity: int, fraction: float, in_per_s: float) -> float:
    """Seconds from t0 until the buffer holds `capacity` (simple_flow.buffer_fill's full_at - t0)."""
    if fraction >= 1.0 or in_per_s <= 0.0 or capacity <= 0:
        return math.inf
    return capacity / ((1.0 - fraction) * in_per_s)
