"""(Superseded in 2.24 by model/buffer_fifo.py -- buffers are a FIFO with an
Output % now; nothing imports this module any more.)

An accumulation buffer as a STEPPING QUEUE in the parametric item
stream (no simulation): the goods roll in, stop behind each other in the
buffer's zones, step forward one zone at a time and leave -- and every
item that passed it is late by a WHOLE number of slots, so downstream the
stream is still the same slot grid (merges and diverters further on keep
working: operators/stream.py "Identity Shift").

Pure Python, unit-tested.

With items one slot S apart (one per T = S / v seconds), queue pitch p
(item length + gap) and K zones in the buffer, an item entering the last
zone waits, then advances one zone (p, taking p / v) at every step and
waits the rest of the period: K_eff zones in use, K_eff - 1 steps, then it
leaves at the next step. Its delay is w + (K_eff - 1)(S - p) of nominal
travel (w = the first wait). Choosing the delay as m whole slots:

    m = floor(K (1 - p / S))          the most whole slots K zones can hold back
    K_eff = ceil(m / (1 - p / S))     zones that need (<= K)
    w = m S - (K_eff - 1)(S - p)      in (0, S - p]: the zone ahead is free
                                      just as the next item arrives
m = 0 (a short buffer, or items already packed at the queue pitch): the
buffer is a plain conveyor.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class QueuePlan:
    zones: int  # zones in use (K_eff)
    slots: int  # whole slots every item is held back (m)
    wait: float  # nominal travel of the first wait, at the last zone's stop (m)
    pitch: float  # queue pitch (m)

    @property
    def shift(self) -> float:
        """Delay in metres of nominal travel: slots x spacing (see queue_plan)."""
        return self.wait + (self.zones - 1) * (self.spacing - self.pitch) if self.zones else 0.0

    spacing: float = 0.0


def queue_plan(length: float, pitch: float, spacing: float) -> QueuePlan:
    """The stepping queue a buffer of `length` holds with items `spacing`
    apart and a queue pitch `pitch`; zones = slots = 0 when it cannot hold
    anything back."""
    if pitch <= 0.0 or spacing <= pitch + 1e-9 or length < pitch:
        return QueuePlan(0, 0, 0.0, pitch, spacing)
    zones_available = int(length // pitch)
    rho = pitch / spacing
    m = int(math.floor(zones_available * (1.0 - rho) + 1e-9))
    if m <= 0:
        return QueuePlan(0, 0, 0.0, pitch, spacing)
    k_eff = int(math.ceil(m / (1.0 - rho) - 1e-9))
    k_eff = max(1, min(k_eff, zones_available))
    wait = m * spacing - (k_eff - 1) * (spacing - pitch)
    return QueuePlan(k_eff, m, wait, pitch, spacing)


def fill_time_min(zones: int, in_ph: float, out_ph: float) -> float:
    """Minutes until a buffer of `zones` zones is full when it receives
    `in_ph` and releases `out_ph` items per hour (inf when it never fills)."""
    surplus = float(in_ph) - float(out_ph)
    if zones <= 0 or surplus <= 1e-9:
        return float("inf")
    return zones * 60.0 / surplus


def slug_size(zones_available: int, slots_before: int) -> int:
    """How many items a slug release takes: the largest slug of at most
    `zones_available` items whose size divides the stream's slot count
    (`slots_before` = the stream's slots plus the other buffers' holds,
    before this slug's own K - 1), so the slug pattern repeats cleanly
    round the stream's wrap. 0 when fewer than two fit."""
    n = int(slots_before) - 1
    for k in range(int(zones_available), 1, -1):
        if n % k == 0:
            return k
    return 0


def slug_wait(slug: int, spacing: float, pitch: float) -> float:
    """Nominal travel the FIRST item of a slug waits at the stop: until the
    last of the `slug` items, arriving one `spacing` apart, has reached its
    place `pitch` behind the one before."""
    return max(slug - 1, 0) * (spacing - pitch)


def displayed_slug(x: float, stop: float, q: int, slug: int, wait: float, pitch: float, spacing: float) -> float:
    """Where item `q` of a slug (0 = the first to arrive, at the stop) is
    shown when its nominal slot coordinate is `x`: it rolls to its place
    `q` pitches behind the stop, stands until the slug is complete, then
    the whole slug moves off together (the node tree's formula)."""
    if slug <= 0:
        return x
    y = x - stop
    spot = stop - q * pitch
    arrive = -q * pitch
    release = wait - q * spacing
    if y < arrive:
        return x
    if y < release:
        return spot
    return spot + (y - release)


def displayed(x: float, tail: float, plan: QueuePlan) -> float:
    """Where an item whose nominal slot coordinate is `x` is shown, for a
    queue whose last zone's stop is at `tail` (the same formula the node
    tree evaluates; here for the tests)."""
    if plan.zones <= 0 or x <= tail:
        return x
    y = x - tail
    if y < plan.wait:
        return tail
    z = y - plan.wait
    n = int(z // plan.spacing)
    r = z - n * plan.spacing
    last = plan.zones - 1
    if n < last:
        return tail + n * plan.pitch + min(r, plan.pitch)
    return tail + last * plan.pitch + (z - last * plan.spacing)
