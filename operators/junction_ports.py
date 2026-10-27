"""The stream graph, published (contract R22.1).

Line-to-line junctions used to be this add-on's own data; every add-on now
builds the same stream graph from records (warehouse_common
simple_flow.build_graph), and this add-on is their only writer (R14):

- On the MAIN line, in its `wh_ports`, each TAKEN junction face is a port
  `{"id": "j:<uuid>", "role": "out" (a divert) | "in" (a merge), "kind":
  "point", "position", "heading_deg", "width_m", "u_m", "taken": true,
  "exclusive": true, "level"}`: the face centre and the goods' direction
  there, and `u_m` the flow-path distance from `line_in` to the junction's
  centre, so both faces of one junction share it (one boundary in the
  graph). A free junction publishes nothing: it is no docking offer. A
  right-angle transfer's faces keep their io ports (`rat<n>_<side>`) and
  gain `u_m` when taken.
- On the DOCKED line, in its `wh_port_links`: the main line's id and port,
  `anchor` start (a divert) or end (a merge), `edge` divert | merge and a
  divert's LOCAL `share` (stream.branch_share); a line carrying on from
  another's end links that line's `line_out` with `edge` continue.

The uuid is made once per junction face and kept on the main line's
piece (`wh_junction_left` / `wh_junction_right`); a re-fit carries it
(detect_junctions._choices), so a feeder sliding along keeps its port."""
from __future__ import annotations

import math
import uuid

JUNCTION_UID_KEYS = {'LEFT': "wh_junction_left", 'RIGHT': "wh_junction_right"}
BUFFER_UID_KEY = "wh_buffer"  # a buffer piece's id: its port "b:<uuid>" (R22.6)
RECORDS_REV_KEY = "conveyor_records_rev"  # which records this line was last published with
RECORDS_REV = 2  # 2: R22.1 junction ports and links (2.21.0); a line without it is republished once
BY = "conveyor_system"
UUID_KEY = "conveyor_uuid"  # = ports.UUID_KEY (no import: ports imports this module)


def _note_write() -> None:
    from .sync_stats import note_write

    note_write()


def face_uid(main, index: int, side: str, create: bool = True) -> str:
    """The uuid of the junction face on `side` of piece `index` of `main`,
    made once. Unique within the line: a copied piece carrying another
    face's uuid gets its own."""
    segs = main.conveyor_line.segments
    key = JUNCTION_UID_KEYS['RIGHT' if side == 'RIGHT' else 'LEFT']
    seg = segs[index]
    uid = str(seg.get(key, "") or "")
    if uid:
        clash = any((j, k) != (index, key) and str(s.get(k, "") or "") == uid
                    for j, s in enumerate(segs) for k in JUNCTION_UID_KEYS.values())
        if not clash:
            return uid
    if not create:
        return ""
    uid = uuid.uuid4().hex
    seg[key] = uid
    _note_write()
    return uid


def clear_uids(seg) -> None:
    """A piece that is no junction any more forgets its faces' ids."""
    for key in JUNCTION_UID_KEYS.values():
        if key in seg:
            del seg[key]


def port_id(main, index: int, side: str, create: bool = True) -> str:
    """The port a line docked on that face links: a RAT's io face port, else the junction's j: port."""
    seg = main.conveyor_line.segments[index]
    if seg.module_kind == 'RAT':
        return f"rat{index + 1}_{side.lower()}"
    uid = face_uid(main, index, side, create)
    return f"j:{uid}" if uid else ""


def module_u_m(context, main, index: int) -> float:
    """Flow-path distance from `main`'s line_in to the centre of piece `index`."""
    from .build_line import segment_starts_for

    segments, starts, _width = segment_starts_for(context, main)
    s = main.conveyor_line
    centre = starts[index] + segments[index].length_m / 2.0
    own = float(s.get("own_length_m", 0.0))
    return max(own - centre, 0.0) if s.reverse else centre


def line_id(context, line) -> str:
    from .ports import ensure_identity

    return str(line.get(UUID_KEY, "") or "") or ensure_identity(context, line)


def docked_faces(context, main) -> list:
    """[(piece index, side, docked line, role)] of every merge / divert face of
    `main` a line really docks on (a stale name -- a deleted line, a copy's
    leftover -- is not one)."""
    from .detect_junctions import _docked_side, _source_role, _sources, docked_junction

    out = []
    for i, seg in enumerate(main.conveyor_line.segments):
        if seg.kind != 'MODULE' or seg.module_kind not in ('MERGE', 'DIVERTER'):
            continue
        for name in _sources(seg):
            line = context.scene.objects.get(name)
            if line is None or line == main:
                continue
            role = _source_role(context, seg, name)
            hit = docked_junction(context, line, role)
            if hit is None or hit[0] != main or hit[1] != i:
                continue
            out.append((i, _docked_side(seg, name), line, role))
    return out


def junction_ports(context, main, M, levels) -> list:
    """`main`'s taken junction faces as ports (R22.1), in its own frame."""
    from .build_line import resolve_width_mm
    from .detect_junctions import _module_face_world
    from .ports import level_at_world

    out = []
    faces = docked_faces(context, main)
    if not faces:
        return out
    inv = M.inverted()
    yaw = main.rotation_euler.z
    u_of = {}
    for i, side, line, role in faces:
        if i not in u_of:
            u_of[i] = module_u_m(context, main, i)
        centre, heading, _geom = _module_face_world(context, main, i, side, role)
        p = inv @ centre
        out.append({"version": 2, "id": port_id(main, i, side), "role": "in" if role == 'MERGE' else "out", "kind": "point",
                    "position": [round(p.x, 3), round(p.y, 3), round(p.z, 3)],
                    "heading_deg": round(math.degrees(heading - yaw) % 360.0, 2),
                    "width_m": round(resolve_width_mm(line.conveyor_line) / 1000.0, 3), "u_m": round(u_of[i], 3),
                    "taken": True, "exclusive": True, "level": level_at_world(centre, levels)})
    out.sort(key=lambda p: (p["u_m"], p["id"]))
    return out


# -------------------------------------------------------------- buffers --
# R22.6 (warehouse_common 0.6.5): every buffer on a line is a
# boundary of its stream sections, published in the line's wh_ports at its
# EXIT: {"id": "b:<uuid>", "role": "buffer", "kind": "point", "u_m",
# "taken": true, "exclusive": true, "out_fraction" (Output %), "capacity_items"
# (its zones)}. build_graph joins the sections with a "buffer" edge whose share
# is the out fraction; resolve passes that much on, the rest piles up. The
# populations published are the state before the buffer is full.

def buffer_pieces(line) -> list:
    """Indices of `line`'s buffer pieces."""
    return [i for i, seg in enumerate(line.conveyor_line.segments) if seg.kind == 'MODULE' and seg.module_kind == 'BUFFER']


def buffer_uid(line, index: int, create: bool = True) -> str:
    """The uuid of buffer piece `index`, made once; a copied piece carrying
    another's gets its own."""
    segs = line.conveyor_line.segments
    seg = segs[index]
    uid = str(seg.get(BUFFER_UID_KEY, "") or "")
    if uid and not any(j != index and str(s.get(BUFFER_UID_KEY, "") or "") == uid for j, s in enumerate(segs)):
        return uid
    if not create:
        return ""
    uid = uuid.uuid4().hex
    seg[BUFFER_UID_KEY] = uid
    _note_write()
    return uid


def buffer_port_id(line, index: int, create: bool = True) -> str:
    uid = buffer_uid(line, index, create)
    return f"b:{uid}" if uid else ""


def buffer_exit_u_m(context, line, index: int, segments=None, starts=None) -> float:
    """Flow-path distance from `line`'s line_in to the exit of buffer piece `index`."""
    if segments is None or starts is None:
        from .build_line import segment_starts_for

        segments, starts, _width = segment_starts_for(context, line)
    s = line.conveyor_line
    a = starts[index]
    own = float(s.get("own_length_m", 0.0))
    return max(own - a, 0.0) if s.reverse else a + segments[index].length_m


def buffer_capacity(context, line, index: int, segments=None) -> int:
    """How many items buffer piece `index` holds: its zones, an item and the
    queue gap each."""
    from ..config import units
    from .populate import populate_item_length

    if segments is None:
        from .build_line import segment_starts_for

        segments, _starts, _width = segment_starts_for(context, line)
    pitch = populate_item_length(context, line) + units.mm_to_bu(line.conveyor_line.segments[index].buffer_gap_mm, context.scene)
    return int(segments[index].length_m // pitch) if pitch > 1e-9 else 0


def buffer_ports(context, line, levels) -> list:
    """`line`'s buffers as ports at their exits (R22.6), in its own frame."""
    from mathutils import Vector

    from .build_line import resolve_width_mm, segment_frames_for, segment_starts_for
    from .ports import level_at_world

    pieces = buffer_pieces(line)
    if not pieces:
        return []
    segments, starts, _width = segment_starts_for(context, line)
    frames = segment_frames_for(context, line)
    rev = bool(line.conveyor_line.reverse)
    M = line.matrix_world
    out = []
    for i in pieces:
        start, end = frames[i]
        pose = start if rev else end  # the exit: where the goods leave the buffer
        heading = pose.heading + (math.pi if rev else 0.0)
        seg = line.conveyor_line.segments[i]
        out.append({"version": 2, "id": buffer_port_id(line, i), "role": "buffer", "kind": "point",
                    "position": [round(pose.x, 3), round(pose.y, 3), round(pose.z, 3)],
                    "heading_deg": round(math.degrees(heading) % 360.0, 2),
                    "width_m": round(resolve_width_mm(line.conveyor_line) / 1000.0, 3),
                    "u_m": round(buffer_exit_u_m(context, line, i, segments, starts), 3), "taken": True, "exclusive": True,
                    "out_fraction": round(int(seg.buffer_out_pct) / 100.0, 4), "capacity_items": buffer_capacity(context, line, i, segments),
                    "level": level_at_world(M @ Vector((pose.x, pose.y, pose.z)), levels)})
    return out


def junction_links(context, obj) -> list:
    """`obj`'s links to the junction it leaves (a divert) or joins (a merge),
    and to the line whose end it carries on from (R22.1)."""
    from .detect_junctions import _docked_side, docked_junction, tail_continuation
    from .stream import branch_share

    out = []
    own = str(obj.get(UUID_KEY, "") or "")
    for kind, edge, anchor in (('DIVERTER', 'divert', 'start'), ('MERGE', 'merge', 'end')):
        hit = docked_junction(context, obj, kind)
        if hit is None:
            continue
        main, i = hit
        seg = main.conveyor_line.segments[i]
        pid = port_id(main, i, _docked_side(seg, obj.name))
        if not pid:
            continue
        entry = {"version": 2, "system_id": line_id(context, main), "system": main.name, "port": pid,
                 "role": "io" if seg.module_kind == 'RAT' else ("out" if kind == 'DIVERTER' else "in"),
                 "anchor": anchor, "edge": edge, "by": BY, "line_id": own}
        if kind == 'DIVERTER':
            try:
                share = branch_share(context, obj)
            except Exception:
                share = None
            if share is None and obj.conveyor_line.share_pct > 0:
                # A bypass (its end merges back) runs as a feeder in today's stream: its Share stands in.
                share = min(float(obj.conveyor_line.share_pct) / 100.0, 1.0)
            if share is not None:
                entry["share"] = round(share, 4)
        out.append(entry)
    tail = tail_continuation(context, obj)
    if tail is not None:
        prev = tail[0]
        out.append({"version": 2, "system_id": line_id(context, prev), "system": prev.name, "port": "line_out", "role": "out",
                    "anchor": "start", "edge": "continue", "by": BY, "line_id": own})
    return out


def stamp(obj) -> None:
    if obj.get(RECORDS_REV_KEY) != RECORDS_REV:
        obj[RECORDS_REV_KEY] = RECORDS_REV
        _note_write()


def needs_republish(obj) -> bool:
    return obj.get(RECORDS_REV_KEY) != RECORDS_REV
