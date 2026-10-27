"""Floor stands along a line (user, 2026-10-13: "set the interval of the feet
... sometimes you need to create tunnels or other things"). The spacing is a
per-line setting; any piece can go without legs, and the stands then stand
flush with both edges of the leg-free stretch (model/spine.py marks them,
geonodes/cross_sections/common.support_stations places them). An open span
longer than MAX_FREE_SPAN_M needs a bridge frame or hangers: the panel says so.
Pure Python: python3 -m unittest tests.test_legs (from dev/)."""
from __future__ import annotations

import math

DEFAULT_SPACING_M = 1.5
MAX_FREE_SPAN_M = 3.0  # a conveyor frame spans about this between stands; more needs a truss


def free_intervals(starts, ends, legs) -> list[tuple[float, float]]:
    """(start, end) arc-length intervals of the leg-free stretches: consecutive
    pieces without legs merge into one."""
    out: list[tuple[float, float]] = []
    for a, b, has_legs in zip(starts, ends, legs):
        a, b = float(a), float(b)
        if has_legs or b <= a:
            continue
        if out and a <= out[-1][1] + 1e-6:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def longest_free_span(intervals) -> float:
    return max((b - a for a, b in intervals), default=0.0)


# ------------------------------------------------------------------ the stand plan (2.14)
# Stands are planned here, marked on the spine (model/spine.py, attribute
# `stand`) and placed by the node trees at the marked samples, so the panel's
# per-stand buttons (ui/stands.py) and the geometry always agree.

SPIRAL_CLEARANCE_M = 0.3  # a stand's posts stay this far outside a spiral's footprint (its lower turns run under the line there)
REMOVED_REACH_M = 0.3  # a removed stand takes out the planned stand nearest to it within half the spacing, at least this
ADD_GAP_M = 0.6  # a gap between two stands this long or longer offers a + to add one in its middle (2.26.3)


def _subtract(a: float, b: float, blocked) -> list[tuple[float, float]]:
    """The parts of [a, b] outside every blocked interval."""
    parts = [(a, b)]
    for c, d in sorted(blocked):
        out = []
        for x, y in parts:
            if d <= x or c >= y:
                out.append((x, y))
                continue
            if c > x:
                out.append((x, c))
            if d < y:
                out.append((d, y))
        parts = out
    return [(x, y) for x, y in parts if y - x > 1e-6]


def zone_intervals(s, x, y, zones) -> list[tuple[float, float]]:
    """Arc intervals where the line's plan position -- the polyline through
    (x[i], y[i]) at arc s[i] -- lies inside any circle (cx, cy, r) of
    `zones`, merged: around a spiral, where a stand would stand in its
    turns. Exact on straight steps (a straight is two samples)."""
    hits = []
    for cx, cy, r in zones:
        for i in range(len(s) - 1):
            dx, dy = x[i + 1] - x[i], y[i + 1] - y[i]
            fx, fy = x[i] - cx, y[i] - cy
            a = dx * dx + dy * dy
            c = fx * fx + fy * fy - r * r
            if a < 1e-12:  # no plan movement (a lift's climb, a transfer's corner)
                if c <= 0.0 and s[i + 1] > s[i]:
                    hits.append((s[i], s[i + 1]))
                continue
            b = 2.0 * (fx * dx + fy * dy)
            disc = b * b - 4.0 * a * c
            if disc <= 0.0:
                continue
            root = math.sqrt(disc)
            lo, hi = max((-b - root) / (2.0 * a), 0.0), min((-b + root) / (2.0 * a), 1.0)
            if hi > lo:
                hits.append((s[i] + lo * (s[i + 1] - s[i]), s[i] + hi * (s[i + 1] - s[i])))
    merged: list[tuple[float, float]] = []
    for a, b in sorted(hits):
        if merged and a <= merged[-1][1] + 1e-6:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def share_joints(ranges, carriers, no_stand=()) -> list[tuple[float, float, bool, bool]]:
    """One stand where two runs meet. Each run gets a stand flush with each
    end, so a joint got two a post apart, their foot plates through each
    other (the legs around a right-angle transfer, 2.26.1). The run flagged in
    `carriers` (a transfer on its own stands) keeps the stand and the other
    rests on it; between two of a kind the first keeps it. A joint inside a
    stretch without stands (`no_stand`: leg-free or carried) is left alone.
    `ranges`: [(a, b, skip_a, skip_b)] in arc order, as plan_stands takes them."""
    out = [list(r) for r in ranges]
    flags = list(carriers) + [False] * (len(out) - len(carriers))
    for k in range(len(out) - 1):
        prev, nxt = out[k], out[k + 1]
        joint = float(prev[1])
        if abs(joint - float(nxt[0])) > 1e-6 or prev[3] or nxt[2]:
            continue
        if any(float(c) - 1e-6 <= joint <= float(d) + 1e-6 for c, d in no_stand):
            continue
        if flags[k + 1] and not flags[k]:
            prev[3] = True
        else:
            nxt[2] = True
    return [tuple(r) for r in out]


def plan_stands(ranges, spacing: float, size: float, blocked=(), removed=(), sources: list | None = None, carried=(),
                added=(), added_sources: list | None = None, gaps: list | None = None):
    """Arc positions of the stands along a line.

    `ranges`: [(a, b, skip_start, skip_end)], the runs that carry stands, in
    arc order (the fence paths and the right-angle transfers). Each run minus
    the `blocked` intervals (leg-free pieces) and the `carried` ones (spirals
    and the line over a spiral's footprint: carried by the spiral, so never
    counted as a span without support) splits into supported stretches; each stretch gets a stand flush with each end (its post half a
    post in from the end) and evenly between, at most `spacing` apart
    (floor(L / spacing) + 2 stands, as the trees always did). A run end
    flagged skip gets none (a docked transfer rests on the frame it docks on).
    `removed`: arcs where the user took a stand out; each takes out the
    planned stand nearest to it within half the spacing (at least
    REMOVED_REACH_M), one stand per spot, the closest pairs first -- so the
    spot stays clear when the stands are spaced anew (another spacing, a
    longer piece). `sources`, when a list, receives the index into `removed`
    of each stand taken out, in the order of `removed_at`.
    `added`: arcs where the user added a stand (2.26.3); each stands there
    when it lies on a supported stretch (kept a half post inside its ends)
    and a post clear of every other stand, else not at all. `added_sources`,
    when a list, receives (arc, index into `added`) of each one placed;
    `gaps`, when a list, the middle of every stretch between two stands at
    least ADD_GAP_M long on a supported stretch (where a + adds one).

    Returns (stands, removed_at, longest_span): the stand arcs, the arcs of the
    stands taken out (where the panel offers to put them back), and the
    longest stretch without a stand that is longer than the spacing (a
    leg-free piece, a removed stand, a free end), 0.0 when there is none."""
    spacing = max(float(spacing), 0.1)
    size = max(float(size), 0.0)
    stands: list[float] = []
    supported: list[tuple[float, float]] = []
    no_stand = list(blocked) + list(carried)
    for a, b, skip_a, skip_b in ranges:
        for c, d in _subtract(float(a), float(b), no_stand):
            length = d - c
            supported.append((c, d))
            if length <= size + 1e-6:
                stands.append((c + d) / 2.0)
                continue
            n = int(math.floor(length / spacing + 1e-6)) + 2  # + 1e-6: a 1.2 m setting arrives as 1.2000000477 (single precision)
            first, last = c + size / 2.0, d - size / 2.0
            pts = [first + k * (last - first) / (n - 1) for k in range(n)]
            if skip_a and abs(c - float(a)) < 1e-9:
                pts = pts[1:]
            if skip_b and abs(d - float(b)) < 1e-9:
                pts = pts[:-1]
            stands.extend(pts)
    stands = sorted(stands)
    deduped: list[float] = []
    for s in stands:
        if not deduped or s - deduped[-1] > 1e-3:
            deduped.append(s)
    stands = deduped
    reach = max(REMOVED_REACH_M, spacing / 2.0) + 1e-9
    pairs = sorted((abs(s - float(r)), k, j) for k, r in enumerate(removed) for j, s in enumerate(stands) if abs(s - float(r)) <= reach)
    spot_of: dict[int, int] = {}  # stand index -> spot index
    for _d, k, j in pairs:
        if j not in spot_of and k not in spot_of.values():
            spot_of[j] = k
    taken = sorted((stands[j], k) for j, k in spot_of.items())
    stands = [s for j, s in enumerate(stands) if j not in spot_of]
    removed_at = [a for a, _k in taken]
    if sources is not None:
        sources.extend(k for _a, k in taken)
    placed: list[tuple[float, int]] = []
    for k, a in enumerate(added):
        a = float(a)
        stretch = next(((c, d) for c, d in supported if c - 1e-9 <= a <= d + 1e-9), None)
        if stretch is None:
            continue  # on a leg-free piece, a spiral, off the runs
        c, d = stretch
        a = (c + d) / 2.0 if d - c <= size else min(max(a, c + size / 2.0), d - size / 2.0)
        if any(abs(a - s) < size + 1e-3 for s in stands) or any(abs(a - p) < size + 1e-3 for p, _k in placed):
            continue
        placed.append((a, k))
    if placed:
        stands = sorted(stands + [a for a, _k in placed])
    if added_sources is not None:
        added_sources.extend(placed)
    if gaps is not None:
        for x, y in zip(stands, stands[1:]):
            mid = (x + y) / 2.0
            if y - x >= ADD_GAP_M - 1e-9 and any(c + size / 2.0 <= mid <= d - size / 2.0 for c, d in supported):
                gaps.append(mid)
    # The longest clear stretch (post face to post face) beyond the spacing:
    # between stands, and at a run's free end (a leg-free first or last piece
    # is a cantilever). A 3 m tunnel reads 3.0 m.
    # Only on the runs that carry stands (touching runs merged) and outside
    # what something else carries (a spiral, a lift between runs).
    longest = 0.0
    if ranges:
        lo = min(float(a) for a, _b, _sa, _sb in ranges)
        hi = max(float(b) for _a, b, _sa, _sb in ranges)
        if stands:
            gaps = [(lo, stands[0] - size / 2.0), (stands[-1] + size / 2.0, hi)]
            gaps += [(x + size / 2.0, y - size / 2.0) for x, y in zip(stands, stands[1:])]
        else:
            gaps = [(lo, hi)]
        runs_on: list[tuple[float, float]] = []
        for a, b, _sa, _sb in sorted(ranges):
            if runs_on and float(a) <= runs_on[-1][1] + 1e-6:
                runs_on[-1] = (runs_on[-1][0], max(runs_on[-1][1], float(b)))
            else:
                runs_on.append((float(a), float(b)))
        for x, y in gaps:
            for a, b in runs_on:
                c, d = max(x, a), min(y, b)
                for e, f in (_subtract(c, d, carried) if d > c else []):
                    if f - e > spacing + 1e-6:
                        longest = max(longest, f - e)
    return stands, removed_at, longest
