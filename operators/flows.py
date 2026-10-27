"""Simple flow over a docked group of lines (R22 / R22.1, 2.22.0).

The request: "simpler sliders setting population amount and speed
amount on the populated objects ... the 'master populated' object ... when
you connect conveyors to it that throughput should follow ... the merged
conveyors should be able to set the % of the master throughput coming
through there." So a populated line has two sliders, Population and Speed;
the MASTER of a stream (flagged, else the most upstream line) sets it, the
lines connected downstream follow it, a branch takes its Share of the
master, and a feeder's goods add where it merges.

The maths is warehouse_common's simple_flow, run over the same graph every
add-on builds from the published records (simple_flow.build_graph: one node
per line SECTION, "<line id>/line_in" then one per taken junction port in
u_m order, the same ids), so the population a line animates is the one any
reader resolves. v1: the lines of a docked group run at ONE
speed (one slot grid, operators/stream.py) -- the master's; a docked feeder
keeps its own Population, at that speed.

The stream (operators/stream.tree_for) takes from here: the group's speed,
each owner's flow (the main line's goods and every populated feeder's), the
cap the slot grid puts on them (the minimum pitch: item + clearance, a
right-angle transfer's stop, a pouch), and every split in the order
simple_flow deals the items (split_order), for the populate tree's
deterministic diverts (simple_flow.branch_of_item).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .._wh import simple_flow as sf

MIGRATED_KEY = "conveyor_flow_migrated"  # the line's Population was set from its pre-2.22 settings (model/flow_migration)
BUFFERS_MIGRATED_KEY = "conveyor_buffers_migrated"  # its buffers' Output % was set from their pre-2.24 Out rate (once)


# ------------------------------------------------------------ population --

def is_migrated(line) -> bool:
    return bool(line.conveyor_line.get(MIGRATED_KEY))


def legacy_populations(context, root, owners) -> dict:
    """{line name: population} the throughput model showed for the owners of
    a group (the root first, then its populated feeders): their share of the
    old slot grid (model/flow_migration)."""
    from ..geonodes.populate import MIN_CLEARANCE
    from ..model import flow_migration
    from .populate import populate_item_length

    rs = root.conveyor_line
    lengths = [populate_item_length(context, o) for o in owners]
    spacing = max([float(o.conveyor_line.populate_spacing_mm) / 1000.0 for o in owners] + [0.02])
    floor_m = max(lengths, default=0.6) + MIN_CLEARANCE
    pitch = flow_migration.old_pitch_m(abs(float(rs.speed_m_s)), float(rs.throughput_ph), spacing, float(rs.populate_fill), floor_m)
    pops = flow_migration.populations(pitch, lengths, [float(o.conveyor_line.share_pct) for o in owners[1:]])
    return {o.name: p for o, p in zip(owners, pops)}


def line_population(line, legacy: dict | None = None) -> float:
    """The population a line's slider stands for (0..1): its Population, or --
    a line from an older file not migrated yet -- what its old settings showed."""
    if not is_migrated(line) and legacy is not None and line.name in legacy:
        return float(legacy[line.name])
    return min(max(float(line.conveyor_line.population_pct) / 100.0, 0.0), 1.0)


def migrate(context, lines) -> list:
    """Writes Population on every line of `lines`' groups saved before 2.22
    (once; the old fields stay as they were). Returns the lines written."""
    from .stream import stream_root, tree_for

    done, written = set(), []
    for line in lines:
        if line.name in done or is_migrated(line):
            continue
        try:
            tree = tree_for(context, line)
        except Exception:
            continue
        group = [line_obj for line_obj in _group_lines(context, tree)]
        done.update(o.name for o in group)
        owners = [tree.root] + [o for o in group if o.name in tree.owner_names[1:]]
        legacy = legacy_populations(context, tree.root, owners)
        for o in group:
            if is_migrated(o):
                continue
            s = o.conveyor_line
            if o.name in legacy:
                s["population_pct"] = round(float(legacy[o.name]) * 100.0, 1)
            s[MIGRATED_KEY] = True
            written.append(o)
    return written


def buffer_in_flow(context, gf, line, index: int) -> float:
    """Items per operation second arriving at buffer piece `index` of `line`:
    the flow of the section its entry lies in (the one before its exit's
    boundary), from the group's resolution `gf`."""
    from .junction_ports import buffer_port_id

    if gf is None:
        return 0.0
    ids, node_of_port, _out = _sections(context, line)
    nid = node_of_port.get(buffer_port_id(line, index, create=False) or f"b:pending:{index}")
    if nid not in ids or ids.index(nid) == 0:
        return 0.0
    nf = gf.nodes.get(ids[ids.index(nid) - 1])
    return max(nf.flow, 0.0) * gf.scale if nf is not None else 0.0


def buffer_in_ph(context, line) -> dict:
    """{buffer piece index: items/h arriving there} (buffer_in_flow)."""
    from .junction_ports import buffer_pieces
    from .stream import tree_for

    gf = tree_for(context, line).flow
    return {i: buffer_in_flow(context, gf, line, i) * 3600.0 for i in buffer_pieces(line)}


def migrate_buffers(context, lines) -> list:
    """Output % on every buffer of `lines` saved before 2.24 (once a line; the
    old Out rate fields stay as they were): an Out rate of its own over what
    arrives there, Auto 100 %. Returns the lines whose Output % changed."""
    from ..model import flow_migration
    from .junction_ports import buffer_pieces

    changed = []
    for line in lines:
        s = line.conveyor_line
        if s.get(BUFFERS_MIGRATED_KEY):
            continue
        pieces = buffer_pieces(line)
        moved = False
        if pieces:
            try:
                arriving = buffer_in_ph(context, line)
            except Exception:
                arriving = {}
            for i in pieces:
                seg = s.segments[i]
                pct = flow_migration.buffer_out_pct(seg.buffer_out_mode, float(seg.buffer_out_ph), arriving.get(i, 0.0))
                if int(seg.buffer_out_pct) != pct:
                    seg["buffer_out_pct"] = pct  # the stored value; the line is rebuilt by the caller
                    moved = True
        s[BUFFERS_MIGRATED_KEY] = True
        if moved:
            changed.append(line)
    return changed


def _group_lines(context, tree) -> list:
    return [context.scene.objects[name] for name in tree.members if name in context.scene.objects]


# ----------------------------------------------------------------- graph --

@dataclass
class Split:
    """One place where a section's goods part: its edges in the order every
    add-on deals the items (simple_flow.split_order)."""
    node: str
    line: str  # the line the split is on
    at_u: float  # stream coordinate where the paths part
    edges: list  # [(dst line name, or None for the line's own continue, local fraction)]


@dataclass
class GroupFlow:
    speed: float = 0.0  # m/s, the master's (one speed per group, v1)
    master: str = ""  # the master line's name
    owner_flow: dict = field(default_factory=dict)  # owner line name -> items/s of its own goods (after the caps)
    scale: float = 1.0  # < 1: the slot grid (or a sink) holds the stream back
    nodes: dict = field(default_factory=dict)  # node id -> simple_flow.NodeFlow
    sections: dict = field(default_factory=dict)  # line name -> [node ids]
    splits: dict = field(default_factory=dict)  # split node id -> Split
    split_of: dict = field(default_factory=dict)  # branch line name -> split node id
    population: dict = field(default_factory=dict)  # line name -> population it shows (its first section, capped)
    share_of_master: dict = field(default_factory=dict)  # line name -> its first section's share of the master
    below_master: dict = field(default_factory=dict)
    merged: dict = field(default_factory=dict)
    master_node: str = ""  # the stream's master node: a line section, or a rack's / door's port leading it
    own_speed: set = field(default_factory=set)  # lines that keep their own Speed (they start at a port)
    floor_population: dict = field(default_factory=dict)  # line name -> the most its grid floor lets it carry (< 1: published)
    input_population: dict = field(default_factory=dict)  # line name -> the population it puts in (its slider; 0 without goods of its own)
    is_master: dict = field(default_factory=dict)  # line name -> its first section is its stream's master (R22.3: it publishes its slider)
    buffer_out: dict = field(default_factory=dict)  # section node id that starts at a buffer's exit -> its Output % (0..1, R22.6)

    def cap_to(self, items_per_s: float) -> None:
        """Hold the whole stream to `items_per_s` (a sink or a buffer that
        takes less): every owner slowed in proportion, nothing vanishes."""
        total = sum(self.owner_flow.values())
        if total <= items_per_s or total <= 1e-12:
            return
        k = items_per_s / total
        self.scale *= k
        self.owner_flow = {name: f * k for name, f in self.owner_flow.items()}
        self.population = {name: p * k for name, p in self.population.items()}


def group_master(lines, root):
    """The stream's master line: the flagged one (by name, the first), else the root."""
    flagged = sorted((line for line in lines if line.conveyor_line.flow_master), key=lambda line: line.name)
    return flagged[0] if flagged else root


def group_speed(lines, root) -> float:
    """The group's speed (m/s): its master's (v1: one speed per docked group)."""
    return abs(float(group_master(lines, root).conveyor_line.speed_m_s))


def _uid(line) -> str:
    from .junction_ports import UUID_KEY

    return str(line.get(UUID_KEY, "") or "") or "line:" + line.name


def _boundaries(context, line) -> list:
    """[(u_m, port id, out fraction or None)] of the line's taken junction
    faces (R22.1) and its buffers' exits (R22.6): the same ports publish_line
    writes, without writing anything (no uuid is made here)."""
    from .junction_ports import buffer_exit_u_m, buffer_pieces, buffer_port_id, docked_faces, module_u_m, port_id

    out = []
    u_of = {}
    for i, side, _src, _role in docked_faces(context, line):
        if i not in u_of:
            u_of[i] = module_u_m(context, line, i)
        out.append((u_of[i], port_id(line, i, side, create=False) or f"j:pending:{i}:{side.lower()}", None))
    for i, seg in enumerate(line.conveyor_line.segments):
        if seg.kind != 'MODULE' or seg.module_kind != 'RAT':
            continue
        for side, name in (("left", seg.merge_source), ("right", seg.merge_source_right), ("end", getattr(seg, "rat_source_end", ""))):
            if name and context.scene.objects.get(name) is not None:
                if i not in u_of:
                    u_of[i] = module_u_m(context, line, i)
                out.append((u_of[i], f"rat{i + 1}_{side}", None))
    for i in buffer_pieces(line):
        out.append((buffer_exit_u_m(context, line, i), buffer_port_id(line, i, create=False) or f"b:pending:{i}",
                    int(line.conveyor_line.segments[i].buffer_out_pct) / 100.0))
    return sorted(out, key=lambda b: (b[0], b[1]))


def _sections(context, line) -> tuple[list, dict, dict]:
    """([node ids], {port id: node id}, {node id: Output %}): "<id>/line_in",
    then one node per boundary (ports within 1 mm of the same u_m are one),
    as build_graph; a section starting at a buffer's exit is entered by a
    "buffer" edge carrying its Output % (R22.6)."""
    uid = _uid(line)
    ids = [f"{uid}/line_in"]
    node_of_port, buffer_out = {}, {}
    groups = []
    for u, pid, out in _boundaries(context, line):
        if groups and u - groups[-1][0][0] <= sf.BOUNDARY_TOL_M:
            groups[-1].append((u, pid, out))
        else:
            groups.append([(u, pid, out)])
    for group in groups:
        nid = f"{uid}/{sorted(p for _u, p, _o in group)[0]}"
        ids.append(nid)
        for _u, pid, out in group:
            node_of_port[pid] = nid
            if out is not None:
                buffer_out[nid] = out
    return ids, node_of_port, buffer_out


def _face_port(context, main, index: int, line) -> str:
    from .detect_junctions import _docked_side
    from .junction_ports import port_id

    seg = main.conveyor_line.segments[index]
    side = _docked_side(seg, line.name)
    return port_id(main, index, side, create=False) or f"j:pending:{index}:{side.lower()}"


def resolve_group(context, lines: list, parents: dict, root, populated: dict, legacy: dict,
                  member_u: dict, item_length: dict, min_pitch_m: float, fixed: dict | None = None,
                  item_routed: dict | None = None, dead_ends: set | None = None) -> GroupFlow:
    """simple_flow over the group: `parents` {name: (kind, main, index) | None}
    (operators/stream.parent_of), `populated` {name: bool}, `legacy` {name:
    pre-2.22 population}, `member_u` {branch name: stream coordinate of its
    divert}, `item_length` {name: m along travel}; `min_pitch_m` = the slot
    grid's floor. `fixed` {branch: local share} for branches that do not take a
    Share (a Route by item class: that class's part; one waiting for a Route:
    0); `item_routed` {branch: (owner names it takes, owner names passing)}:
    a branch taking its own item takes those owners' goods whole; `dead_ends`:
    lines whose goods have nowhere to go past their last split (a transfer at
    the end), so their branches there take everything."""
    from .detect_junctions import docked_diverter, docked_junction

    gf = GroupFlow()
    by_name = {line.name: line for line in lines}
    master_line = group_master(lines, root)
    gf.master = master_line.name
    gf.speed = abs(float(master_line.conveyor_line.speed_m_s))
    fixed = dict(fixed or {})
    item_routed = dict(item_routed or {})
    dead_ends = set(dead_ends or ())
    ports_of = {}
    for line in lines:
        gf.sections[line.name], ports_of[line.name], buffer_out = _sections(context, line)
        gf.buffer_out.update(buffer_out)

    # The slot grid's floor (item + clearance, a right-angle stop, a pouch) as
    # a cap on every section: published on the line's ports (R22.2), so any
    # reader resolves the same caps (max_population, silently).
    for line in lines:
        cap = (item_length.get(line.name, 0.6) + sf.GAP_AT_FULL_M) / min_pitch_m if min_pitch_m > 1e-9 else 1.0
        if cap < 1.0 - 1e-9:
            gf.floor_population[line.name] = cap
    port_nodes, port_edges, docks = _port_graph(context, lines, gf.sections, item_length, gf.speed)
    gf.own_speed = {name for name, _src, _kind in docks if _kind == "lead"}

    def build(shares: dict):
        nodes, edges = dict(port_nodes), list(port_edges)
        for line in lines:
            ids = gf.sections[line.name]
            s = line.conveyor_line
            # Goods come in at the root and at every populated feeder; a branch or
            # takeaway has no goods of its own, its Population counts when it is the master.
            brings = parents.get(line.name) is None or parents[line.name][0] == 'MERGE'
            pop = line_population(line, legacy) if (populated.get(line.name, False) or not brings) else 0.0
            gf.input_population[line.name] = pop
            for k, nid in enumerate(ids):
                nodes[nid] = sf.Node(nid, population=pop, speed=gf.speed, item_length=item_length.get(line.name, 0.6),
                                     master=(k == 0 and bool(s.flow_master)), max_population=gf.floor_population.get(line.name),
                                     own_speed=(k == 0 and line.name in gf.own_speed))
            for a, b in zip(ids, ids[1:]):
                # past a buffer's exit its Output % goes on, the rest piles up inside (R22.6)
                edges.append(sf.Edge(a, b, sf.BUFFER, gf.buffer_out[b]) if b in gf.buffer_out else sf.Edge(a, b, sf.CONTINUE))
        for name, src, kind in docks:
            ids = gf.sections[name]
            edges.append(sf.Edge(src, ids[0], sf.DOCK) if kind == "lead" else sf.Edge(ids[-1], src, sf.DOCK))
        for line in lines:
            name = line.name
            first, last = gf.sections[name][0], gf.sections[name][-1]
            p = parents.get(name)
            divert = docked_diverter(context, line)
            merge = docked_junction(context, line, 'MERGE')
            if divert is not None and divert[0].name in by_name:
                main, i = divert
                nid = ports_of[main.name].get(_face_port(context, main, i, line))
                if nid is not None:
                    ids = gf.sections[main.name]
                    edges.append(sf.Edge(ids[ids.index(nid) - 1], first, sf.DIVERT, shares.get(name)))
            if merge is not None and merge[0].name in by_name:
                main, i = merge
                nid = ports_of[main.name].get(_face_port(context, main, i, line))
                if nid is not None:
                    edges.append(sf.Edge(last, nid, sf.MERGE))
            if p is not None and p[0] == 'CONTINUE' and p[1].name in by_name:
                edges.append(sf.Edge(gf.sections[p[1].name][-1], first, sf.CONTINUE))
        return nodes, edges

    # A branch's Share is a % OF THE MASTER; the links (and simple_flow) take
    # the LOCAL fraction at its split: share / the split section's share of
    # the master, found by resolving (twice is enough: the split sections
    # upstream of a branch do not depend on its own share).
    # The master's own Share cannot be a share of itself: on a branch that is
    # the master it is the local part of what reaches its divert.
    if (master_line.name not in fixed and master_line.name not in item_routed and master_line.conveyor_line.share_pct > 0
            and docked_diverter(context, master_line) is not None):
        fixed[master_line.name] = float(master_line.conveyor_line.share_pct) / 100.0
    wanted = {line.name: float(line.conveyor_line.share_pct) / 100.0 for line in lines
              if line.name not in fixed and line.name not in item_routed
              and line.conveyor_line.share_pct > 0 and docked_diverter(context, line) is not None}
    shares = dict(wanted)
    shares.update(fixed)
    res = None
    for _round in range(4):
        nodes, edges = build(shares)
        res = sf.resolve(nodes, edges, sf.DEFAULT_SPEED)  # R22.2: every reader resolves with the one default speed
        changed = False
        local_of = {}
        for name, s in wanted.items():
            e = next((e for e in edges if e.kind == sf.DIVERT and e.dst == gf.sections[name][0]), None)
            som = res.nodes[e.src].share_of_master if e is not None and e.src in res.nodes else 1.0
            local_of[name] = min(1.0, s / som) if som > 1e-9 else 0.0
        # A branch taking its own item: those owners' goods, whole.
        own = {o: max(res.nodes[gf.sections[o][0]].flow, 0.0) for o in gf.sections if gf.sections[o][0] in res.nodes}
        for name, (takes, passing) in item_routed.items():
            through = sum(own.get(o, 0.0) for o in passing)
            local_of[name] = min(1.0, sum(own.get(o, 0.0) for o in takes) / through) if through > 1e-12 else 0.0
        # A dead end keeps nothing back: its last split's branches share all of it.
        for name in dead_ends:
            ids = gf.sections.get(name, [])
            if len(ids) < 2:
                continue
            last_split = ids[-2]
            kids = [e.dst for e in edges if e.kind == sf.DIVERT and e.src == last_split]
            names = [n for n, s_ids in gf.sections.items() if s_ids[0] in kids]
            if not names:
                continue
            explicit = {n: local_of.get(n, shares.get(n)) for n in names if n in local_of or (n in shares and shares[n] is not None)}
            auto = [n for n in names if n not in explicit]
            total = sum(v for v in explicit.values() if v is not None)
            if auto:
                rest = max(0.0, 1.0 - min(total, 1.0))
                for n in auto:
                    local_of[n] = rest / len(auto)
            elif 0.0 < total < 1.0:
                for n in explicit:
                    local_of[n] = explicit[n] / total
        for name, local in local_of.items():
            if abs(local - (shares.get(name) if shares.get(name) is not None else -1.0)) > 1e-6:
                shares[name] = local
                changed = True
        if not changed:
            break
    gf.nodes = dict(res.nodes)
    # Each owner's own goods: the root's stream at its first section, a
    # populated feeder's at its own; the slot grid holds them all.
    owners = [root] + [line for line in lines if parents.get(line.name) is not None and parents[line.name][0] == 'MERGE'
                       and populated.get(line.name, False)]
    flows = {o.name: max(res.nodes[gf.sections[o.name][0]].flow, 0.0) for o in owners if gf.sections[o.name][0] in res.nodes}
    total = sum(flows.values())
    # Resolve capped every section already. The slot grid holds every owner's
    # goods though, so where a branch leaves before a feeder merges in, all
    # owners together may still be more than it holds: then all are slowed.
    limit = gf.speed / min_pitch_m if min_pitch_m > 1e-9 else math.inf
    gf.scale = min(1.0, limit / total) if total > limit * (1.0 + 1e-6) and total > 1e-12 else 1.0
    gf.owner_flow = {name: f * gf.scale for name, f in flows.items()}
    root_nf = res.nodes.get(gf.sections[root.name][0])
    gf.master_node = root_nf.master if root_nf is not None else ""
    if gf.master_node and not any(gf.master_node == ids[0] for ids in gf.sections.values()):
        gf.master = port_label(context, gf.master_node) or gf.master  # a rack's or door's port leads the stream
    for line in lines:
        nf = res.nodes.get(gf.sections[line.name][0])
        if nf is None:
            continue
        gf.population[line.name] = min(nf.population * gf.scale, 1.0)
        gf.is_master[line.name] = bool(nf.is_master)
        gf.share_of_master[line.name] = nf.share_of_master
        gf.below_master[line.name] = nf.below_master
        gf.merged[line.name] = nf.merged_flow
    # The splits, in the order the items are dealt, with where they are.
    owner_of_node = {nid: name for name, ids in gf.sections.items() for nid in ids}
    first_of = {ids[0]: name for name, ids in gf.sections.items()}
    for src, rows in res.splits.items():
        line_name = owner_of_node.get(src)
        dsts = []
        at = None
        for dst, kind, frac in rows:
            if kind == sf.DIVERT and dst in first_of:
                dsts.append((first_of[dst], frac))
                u = member_u.get(first_of[dst])
                at = u if at is None or (u is not None and u < at) else at
            else:
                dsts.append((None, frac))  # the line's own continue
        if at is None:
            continue
        gf.splits[src] = Split(src, line_name, at, dsts)
        for dst, _frac in dsts:
            if dst is not None:
                gf.split_of[dst] = src
    return gf


def _system_record(system) -> dict:
    """A system's published records, the way build_graph reads them."""
    from .ports import LINKS_KEY, SYSTEM_KEY, _json, ports_of

    return {"system": _json(system.get(SYSTEM_KEY), {}), "ports": ports_of(system),
            "links": _json(system.get(LINKS_KEY), []), "load": _json(system.get("wh_load"), None)}


def _port_graph(context, lines, sections: dict, item_length: dict, speed: float):
    """(nodes, edges, docks) of the systems the group's lines dock at: each
    system's own graph from its published records (simple_flow.build_graph:
    its ports, and the system node dealing its delivery points when it is one
    stream), and [(line, port node, "lead" | "sink")]: a port the line STARTS
    at leads its stream (the line keeps its own Speed); one its end feeds
    takes the stream (and caps it by its max_population). A published
    population wins, even 0 (R22.5); without one a legacy rate stands in, and
    a sink's legacy capacity_ph is its max_population (build_graph does both
    when the port's or system's load gives a length; the docked line's item
    fills in here, as WC 0.6.4 does from the line's records, at the same
    speed: the port's, else its surface speed, else the load kind's default);
    a port publishing neither leads nothing: the line keeps its own
    Population."""
    from ..model import port_io
    from .ports import _load_descriptor, linked_at, system_id

    nodes, edges, docks, seen, sys_loads = {}, [], [], set(), {}
    for line in lines:
        reverse = bool(line.conveyor_line.reverse)
        for anchor in ("origin", "end"):
            hit = linked_at(context, line, anchor)
            if hit is None:
                continue
            system, port, role, _ = hit
            sid = system_id(system)
            if not sid:
                continue
            if sid not in seen:
                seen.add(sid)
                record = _system_record(system)
                sys_loads[sid] = record.get("load")
                n2, e2 = sf.build_graph([record])
                nodes.update(n2)
                edges += e2
            pid = f"{sid}/{port.get('id')}"
            starts = (anchor == "origin") != reverse
            length = item_length.get(line.name, 0.6)

            def legacy_speed():
                return port_io.goods_speed_m_s(port) or sf.default_speed(port.get("load") or sys_loads.get(sid) or _load_descriptor(context, line))
            if starts and role in ("out", "io") and pid in nodes:
                node = nodes[pid]
                if node.item_length <= 0.0:
                    node.item_length = port_io.load_length_m(port) or length
                fed = any(e.dst == pid for e in edges)
                if node.population <= 0.0 and not fed and port_io.population(port, "out") is None:
                    rate = port_io.rate_ph(port, "out", length, speed)  # no population: the legacy rate, if any
                    if rate <= 0.0:
                        continue  # no numbers: the line leads itself
                    node.speed = node.speed or legacy_speed()  # build_graph's rule
                    node.population = min(sf.population_from_rate(rate, node.speed, node.item_length), 1.0)
                docks.append((line.name, pid, "lead"))
            elif not starts and role in ("in", "io"):
                nid = pid + ":in" if role == "io" else pid
                if nid not in nodes:
                    continue
                node = nodes[nid]
                if node.item_length <= 0.0:
                    node.item_length = port_io.load_length_m(port) or length
                if node.max_population is None:
                    capacity = port_io.capacity_ph(port, length, speed)  # no max_population: the legacy capacity_ph, if any
                    if capacity > 0.0:
                        node.max_population = min(sf.population_from_rate(capacity, legacy_speed(), node.item_length), 1.0)
                docks.append((line.name, nid, "sink"))
    return nodes, edges, docks


def port_label(context, node_id: str) -> str:
    """ "Rack · aisle0_out" for a port node "<system id>/<port id>[:in]"."""
    from .ports import find_system

    sid, _, port = node_id.partition("/")
    system = find_system(context.scene, sid, "")
    return f"{system.name} · {port.split(':')[0]}" if system is not None else port


def share_text(gf: GroupFlow, line_name: str) -> str:
    """The panel's words for a line (simple_flow.share_text): "Master",
    "30 % of <master>" (+ merged), or "Stream of <master>"."""
    nf = gf.nodes.get(gf.sections.get(line_name, [""])[0])
    if nf is None:
        return ""
    return sf.share_text(nf, gf.master)
