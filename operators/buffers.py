"""The accumulation buffer's out logic (user request: "the buffer should hold goods and stack from the
back with an out logic"). Pure bookkeeping around model/buffer_queue.py:
what the buffer releases per hour, and what that means for the stream.

Out rate Auto = what the next machine downstream takes: the next
junction's technology rate, an inline module's rate (lift, spiral, angled-roller element,
wrapper, right-angle transfer), the capacity of the rack this line feeds
(operators/ports.py) -- else the in rate. A buffer whose out rate is below
the in rate holds the source back: the group moves at the out rate, the
buffer runs full and the queue backs up along the line upstream of it
(operators/stream.py).
"""
from __future__ import annotations

from ..config import loader


def out_rate(context, line, index: int, in_ph: float) -> tuple[float, str]:
    """(items per hour the buffer at `index` releases, where that number
    comes from)."""
    settings = line.conveyor_line
    seg = settings.segments[index]
    if seg.buffer_out_mode == 'MANUAL':
        return float(seg.buffer_out_ph), "set"
    segs = settings.segments
    order = range(index - 1, -1, -1) if settings.reverse else range(index + 1, len(segs))
    techs = loader.get_technologies()
    inline = loader.get_inline_module_info()
    for j in order:
        sj = segs[j]
        if sj.kind == 'SPIRAL':
            info = inline.get('SPIRAL', {})
            if info.get("rate_per_h"):
                return float(info["rate_per_h"]), str(info.get("label", "spiral")).lower()
            break
        if sj.kind != 'MODULE':
            continue
        if sj.module_kind in ('MERGE', 'DIVERTER'):
            from .build_line import resolve_junction_tech

            tech = techs.get(resolve_junction_tech(sj))
            if tech is not None and tech.rate_per_h:
                return float(tech.rate_per_h), tech.label.lower()
            break
        if sj.module_kind == 'BUFFER':
            break
        info = inline.get(sj.module_kind, {})
        if info.get("rate_per_h"):
            return float(info["rate_per_h"]), str(info.get("label", sj.module_kind)).lower()
    from .ports import capacity_of, linked_at

    hit = linked_at(context, line, "origin" if settings.reverse else "end")  # the dock at the flow END
    if hit is not None and hit[2] in ("in", "io"):
        from .populate import populate_item_length
        from .stream import group_speed

        capacity = capacity_of(hit[1], populate_item_length(context, line), group_speed(context, line))  # R22: max_population stands in
        if capacity > 0.0:
            return capacity, hit[0].name
    return float(in_ph), "= in"


def merge_downstream(context, line, index: int) -> str | None:
    """The name of a line merging in downstream of the buffer at `index`
    (its goods would collide with a slug's), or None."""
    from .detect_junctions import _is_junction, _junction_role, _sources

    settings = line.conveyor_line
    segs = settings.segments
    order = range(index - 1, -1, -1) if settings.reverse else range(index + 1, len(segs))
    for j in order:
        sj = segs[j]
        if sj.kind != 'MODULE' or not _is_junction(sj):
            continue
        for name in _sources(sj):
            other = context.scene.objects.get(name)
            if other is not None and _junction_role(sj, other) == 'MERGE':
                return name
    return None
