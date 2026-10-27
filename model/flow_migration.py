"""Population for a line saved before the simple-flow switch (2.22.0,
R22: "Migration on first build: Population = the current effective pitch
converted, capped at 1, and the line is marked migrated. The old fields stay
untouched for older versions"). Pure: the old settings in, a population per
owner of the stream out.

Before 2.22 the stream's goods sat on one slot grid: its pitch was the main
line's throughput over its speed (or the Spacing in Placement), thinned by
Fill; the docked feeders each owned a share of the slots (their Share %, the
rest split equally with the main line). What the user saw was each owner's
goods every `pitch / share` metres, so that is what is kept: an owner's
population = its share x (its item length + the 0.05 m gap) / the pitch."""
from __future__ import annotations

GAP_AT_FULL_M = 0.05  # warehouse_common simple_flow.GAP_AT_FULL_M


def old_pitch_m(speed_m_s: float, throughput_ph: float, spacing_m: float, fill: float, floor_m: float) -> float:
    """The pitch the throughput model gave the stream: the throughput at the
    line's speed (never below the floor: item + clearance), else the Spacing;
    Fill thinned the slots out."""
    if throughput_ph > 0.0 and speed_m_s > 1e-6:
        base = max(speed_m_s * 3600.0 / throughput_ph, floor_m)
    else:
        base = max(spacing_m, floor_m)
    return base / min(max(fill, 0.01), 1.0)


def owner_weights_pct(feeder_shares_pct: list) -> list:
    """[main line, feeder 1, ...] in percent, as the throughput model dealt
    the slots (operators/stream.share_weights before 2.22): explicit shares as
    given (scaled down together above 100), the rest split equally between
    the main line and the feeders left at 0."""
    explicit = [max(float(x), 0.0) for x in feeder_shares_pct]
    fixed = sum(x for x in explicit if x > 0)
    if fixed > 100.0:
        explicit = [x * 100.0 / fixed for x in explicit]
        fixed = 100.0
    auto = sum(1 for x in explicit if x <= 0)
    part = (100.0 - fixed) / (auto + 1)
    return [part] + [x if x > 0 else part for x in explicit]


def populations(pitch_m: float, item_lengths_m: list, feeder_shares_pct: list) -> list:
    """Population (0..1) of each owner [main line, feeder 1, ...]: its share
    of the slots x (its item length + the gap) / the pitch, capped at 1."""
    if pitch_m <= 1e-9:
        return [0.0 for _ in item_lengths_m]
    weights = owner_weights_pct(feeder_shares_pct)
    return [min(1.0, max(0.0, w / 100.0 * (max(length, 0.0) + GAP_AT_FULL_M) / pitch_m))
            for w, length in zip(weights, item_lengths_m)]


def buffer_out_pct(mode: str, out_ph: float, in_ph: float) -> int:
    """Output % for a buffer saved before 2.24 ("Manual buffer Out
    rates become Output % from the rate ratio where possible, else 100 %"):
    an Out rate of its own (Set) over what arrives there, at most 100; Auto
    (the next machine's rate) and anything unknown: 100."""
    if mode != 'MANUAL' or in_ph <= 0.0 or out_ph < 0.0:
        return 100
    return int(max(0, min(100, round(100.0 * out_ph / in_ph))))
