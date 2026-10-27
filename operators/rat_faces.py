"""A right-angle transfer takes the width of the conveyor on each of its
sides ("auto hold the width of the conveyors side they
are attached to"). Sides where a line docks as a junction source already
did (detect_junctions._set_infeed). Two attachments did not; they are
applied at the start of every build:

- a transfer that TURNS at the end of its line: the takeaway carrying on
  from its exit side (New Line from End) sets that side's width, so the
  module grows to it as it does for a docked branch;
- a standalone transfer unit (a line made only of transfers): its deck takes
  the width of the line feeding it, else of its takeaway.

A transfer inside a longer line keeps the line's own width at its start and
end: those are the main line's sides. Every write compares first."""
from __future__ import annotations

from ..config import units

EXIT_FROM_TAIL_KEY = "rat_exit_from_tail"  # on the segment: its exit face width comes from the takeaway


def tails_by_target(scene) -> dict:
    """{line name: [the lines carrying on from its end]} (TAIL_KEY)."""
    from .build_line import all_lines
    from .detect_junctions import TAIL_KEY

    out: dict = {}
    for line in all_lines(scene):
        target = line.conveyor_line.get(TAIL_KEY)
        if target:
            out.setdefault(target, []).append(line)
    return out


def _takeaway(obj, tails: dict):
    found = tails.get(obj.name) or []
    return found[0] if found else None


def is_rat_unit(settings) -> bool:
    segs = settings.segments
    return len(segs) > 0 and all(s.kind == 'MODULE' and s.module_kind == 'RAT' for s in segs)


def _turning_last_rat(settings):
    segs = settings.segments
    if not segs:
        return None
    last = segs[-1]
    if last.kind == 'MODULE' and last.module_kind == 'RAT' and last.module_exit in ('LEFT', 'RIGHT'):
        return last
    return None


def frame_width_mm(line, scene) -> float:
    """The line's frame width, rails included: what a face opens to (as _set_infeed)."""
    from .build_line import resolve_width_mm
    from .detect_junctions import RAIL_THICKNESS_M

    return units.bu_to_mm(units.mm_to_bu(resolve_width_mm(line.conveyor_line), scene) + 2.0 * RAIL_THICKNESS_M, scene)


def _exit_key(seg) -> str:
    return "rat_face_left_mm" if seg.module_exit == 'LEFT' else "rat_face_right_mm"


def _wanted_exit_mm(obj, scene, tails: dict):
    """(segment, wanted face width) for a turning transfer at the line's end; None when not one."""
    seg = _turning_last_rat(obj.conveyor_line)
    if seg is None:
        return None
    take = _takeaway(obj, tails)
    if take is None:
        return (seg, 0.0) if seg.get(EXIT_FROM_TAIL_KEY) else None  # only undo what this module set
    return seg, frame_width_mm(take, scene)


def _width_source(context, obj, tails: dict):
    from .detect_junctions import TAIL_KEY

    feeder = context.scene.objects.get(obj.conveyor_line.get(TAIL_KEY, "") or "")
    if feeder is not None and feeder.type == 'CURVES' and feeder.conveyor_line.is_conveyor_line:
        return feeder
    return _takeaway(obj, tails)


def _unit_differs(settings, src_settings) -> bool:
    if settings.width_preset != src_settings.width_preset:
        return True
    return src_settings.width_preset == 'CUSTOM' and abs(settings.custom_width_mm - src_settings.custom_width_mm) > 0.5


def apply(context, obj, tails: dict | None = None) -> bool:
    """At the start of a build: the exit face of a turning transfer at the
    line's end and the deck of a standalone unit. True when anything changed."""
    from ..props.line_settings import suspended_rebuild

    scene = context.scene
    tails = tails_by_target(scene) if tails is None else tails
    settings = obj.conveyor_line
    changed = False
    if is_rat_unit(settings):
        src = _width_source(context, obj, tails)
        if src is not None and _unit_differs(settings, src.conveyor_line):
            with suspended_rebuild():  # no rebuild and no spread to selected lines from here
                try:
                    settings.width_preset = src.conveyor_line.width_preset
                    if src.conveyor_line.width_preset == 'CUSTOM':
                        settings.custom_width_mm = src.conveyor_line.custom_width_mm
                except TypeError:  # that width is not in this type's catalogue
                    from .build_line import resolve_width_mm

                    settings.width_preset = 'CUSTOM'
                    settings.custom_width_mm = resolve_width_mm(src.conveyor_line)
            changed = True
    wanted = _wanted_exit_mm(obj, scene, tails)
    if wanted is not None:
        seg, mm = wanted
        key = _exit_key(seg)
        if abs(float(seg.get(key, 0.0)) - mm) > 0.5:
            seg[key] = float(mm)
            changed = True
        if mm > 0.0 and not seg.get(EXIT_FROM_TAIL_KEY):
            seg[EXIT_FROM_TAIL_KEY] = True
            changed = True
        elif mm <= 0.0 and EXIT_FROM_TAIL_KEY in seg:
            del seg[EXIT_FROM_TAIL_KEY]
            changed = True
    return changed


def neighbours_to_refresh(context, obj) -> list:
    """After `obj` was built: the lines whose transfer widths depend on it and
    are now off -- a unit fed by it, the transfer line it carries on from."""
    from .detect_junctions import TAIL_KEY

    scene = context.scene
    tails = tails_by_target(scene)
    out = []
    for other in tails.get(obj.name, []):  # lines carrying on from obj: a unit takes its feeder's width
        if is_rat_unit(other.conveyor_line) and _unit_differs(other.conveyor_line, obj.conveyor_line):
            out.append(other)
    parent = scene.objects.get(obj.conveyor_line.get(TAIL_KEY, "") or "")
    if parent is not None and parent.type == 'CURVES' and parent.conveyor_line.is_conveyor_line:
        wanted = _wanted_exit_mm(parent, scene, tails)
        if wanted is not None and abs(float(wanted[0].get(_exit_key(wanted[0]), 0.0)) - wanted[1]) > 0.5:
            out.append(parent)
        elif (is_rat_unit(parent.conveyor_line) and _width_source(context, parent, tails) is obj
              and _unit_differs(parent.conveyor_line, obj.conveyor_line)):
            out.append(parent)
    return out


def stale_exit_faces(scene, lines) -> list:
    """Turning transfers whose exit width came from a takeaway that is gone."""
    tails = tails_by_target(scene)
    out = []
    for line in lines:
        seg = _turning_last_rat(line.conveyor_line)
        if seg is not None and seg.get(EXIT_FROM_TAIL_KEY) and _takeaway(line, tails) is None:
            out.append(line)
    return out
