"""How goods move through a right-angle transfer ("add a
small transition when the bin is lifted on the RAT ... now it is lifted and
moved to the side"). An item arrives, slows to a stop on the transfer's
centre, stands while the belts rise under it, goes out sideways on the
raised belts and is set down at the deck's edge, then carries on. On a
reversed line it is the other way round: it comes in sideways on raised
belts, stops on the centre, is set down and carries on along the line.

The timing is a pure function of the stream coordinate (scene time x speed),
the same on every line of a stream, so hand-overs stay continuous and
nothing is written per frame (contract R5). geonodes/populate.stop_warp is
this module's `shown` in nodes. Pure Python, no bpy.

Timings per transfer technology: (settle s, lift s, deceleration m/s²).
- BELT / POPUP (totes, cartons): the lift takes 0.3 s -- Interroll RM 8731
  right-angle transfer datasheet; the settle and the deceleration of an MDR
  zone stop are assumed.
- CHAIN (pallets): no published lift time (Interroll's PM 9730 chain
  transfer lifts up to 30 mm); a loaded pallet is assumed to settle and lift
  slower."""
from __future__ import annotations

import math

TIMING = {
    'BELT': (0.2, 0.3, 1.5),
    'POPUP': (0.2, 0.3, 1.5),
    'CHAIN': (0.5, 1.0, 0.5),
}
EASE_MIN_M, EASE_MAX_M = 0.01, 0.15
CLEARANCE_M = 0.005


def timing(tech: str) -> tuple:
    return TIMING.get(tech, TIMING['BELT'])


def ease_m(speed: float, tech: str) -> float:
    """How far before the centre the item starts to slow down: v² / 2a (the
    slowing costs this much travel again as lag)."""
    _settle, _lift, decel = timing(tech)
    return min(max(speed * speed / (2.0 * decel), EASE_MIN_M), EASE_MAX_M)


def hold_m(speed: float, tech: str) -> float:
    """The stand on the centre, in stream travel: settle, then lift (or set down)."""
    settle, lift, _decel = timing(tech)
    return max(speed, 0.0) * (settle + lift)


def turn_m(speed: float, tech: str) -> float:
    """The last part of the stand, while the belts rise (or lower)."""
    return max(speed, 0.0) * timing(tech)[1]


def lag_m(ease: float, hold: float) -> float:
    """How much later every item is past the transfer: slowing down, standing, speeding up."""
    return 2.0 * ease + hold


def min_pitch_m(footprint: float, ease: float, hold: float) -> float:
    """The closest the goods may follow each other through a stopping
    transfer: the next item (its length along travel) must not reach the
    standing one before that has gone out sideways by its own width. So the
    pitch is at least length + width (`footprint`) + the stop's lag."""
    return footprint + lag_m(ease, hold) + CLEARANCE_M


def shown(x: float, c: float, ease: float, hold: float) -> float:
    """Where an item whose undelayed coordinate is `x` is shown: unchanged
    before c - ease, slowing (speed falling linearly) to a stop at c, standing
    `hold`, speeding up over the same travel, then lag_m late."""
    a = max(ease, 1e-4)
    d = x - (c - a)
    if d < 0.0:
        return x
    if d < 2.0 * a:
        return (c - a) + d - d * d / (4.0 * a)
    if d < 2.0 * a + hold:
        return c
    e = d - 2.0 * a - hold
    if e < 2.0 * a:
        return c + e * e / (4.0 * a)
    return x - lag_m(a, hold)


def extra_slots(total_lag: float, pitch: float) -> int:
    """Slots the stream needs beyond its lines so the late goods still reach the end."""
    if total_lag <= 0.0 or pitch <= 1e-9:
        return 0
    return int(math.ceil(total_lag / pitch - 1e-9))
