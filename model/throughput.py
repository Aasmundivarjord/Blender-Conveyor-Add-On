"""Line throughput, pure Python (no bpy): the planner's formula.

A conveyor running at v (m/s) with one item every `pitch` metres (the
item's length plus the gap behind it) carries 3600 * v / pitch items per
hour. Sizing a line goes the other way round: a required throughput Q at a
chosen pitch needs v = Q * pitch / 3600. (Industrial Monitor Direct,
"How to calculate conveyor capacity" / "Belt speed"; Supply Chain Digest,
Cliff Holste on merge and sorter rates; the roller-conveyor throughput
guides: the same relation everywhere, items per hour = 3600 x speed /
(length + gap).) The pitch never closes below the item plus a clearance:
merges and sorters need a gap to work in (operators/stream.py)."""
from __future__ import annotations


def required_speed_m_s(throughput_ph: float, pitch_m: float) -> float:
    """The speed a line must run at to move `throughput_ph` items per hour
    with one item every `pitch_m` metres."""
    return max(float(throughput_ph), 0.0) * max(float(pitch_m), 0.0) / 3600.0


def throughput_ph(speed_m_s: float, pitch_m: float) -> float:
    """Items per hour a line moves at `speed_m_s` with one item every `pitch_m`."""
    return 0.0 if pitch_m <= 0.0 else 3600.0 * abs(float(speed_m_s)) / float(pitch_m)
