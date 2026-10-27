"""One item stream per connected group of lines.

Lines that dock onto each other (a feeder's END on a merge junction, a
branch's START on a diverter) transport the same goods, so they share ONE
stream: one spacing, one speed, one seed, one wrap length. Every slot of
that stream has exactly one OWNER -- the root main line (0) or a docked
feeder (1..K) -- chosen per slot index with a seeded random pick, and a
slot is drawn by its owner only: the feeder draws it along its own path
and, through its continuation, down the main line; the main line never
draws it. Two lines can therefore never put an item in the same place
("items inside each other" after a merge).

Coordinates: each line maps its full-spline arc `a` to the stream
coordinate `u = a + offset`, so a feeder whose end meets the main line at
main arc `s` has offset(main) + s - (own length + transfer extra). Branch
prefixes already run in their main's arc, so a branch shares its main's
offset. Offsets are shifted so the smallest is 0; the wrap length is the
largest `offset + full length` in the group.

Routing works in the same coordinates: a diverter rule (route keys lo..hi,
u, owner mask) is pushed to every line of the group; a branch draws only
its keys, from its switch point on, for the owners whose goods are on that
main line there. The route key of a slot is its item class when some
diverter of the group has a Route set, else -- every docked branch simply
taking its SHARE of the goods (branches off diverters
used to run their own goods) -- a seeded exit index per slot: branch k
takes the slots whose exit is k, the rest ride to the main line's end.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..config import units
from ..model import transfer_motion

STOP_PAST_M = 1e-4  # a divert's stop sits this far past where the paths part: the branch draws the standing item


@dataclass
class LineStream:
    offset: float = 0.0  # full-spline arc + offset = stream coordinate u
    owner: int = 0  # slot owner index (root 0, feeders 1..K, branches -1)
    mask: int = 0  # owners this line draws (bit set); 0 = everything
    only_class: int = -1  # routed branch: the first route key it receives (item class, or exit index)
    only_hi: int = -1  # last route key it receives (-1: just only_class)
    prefix_u: float = 0.0  # nothing drawn before this stream coordinate
    parent: object = None  # (kind, main line, module index) or None
    entry_u: float = 0.0  # feeder: where its goods reach the parent's path
    routes: list = field(default_factory=list)  # (pre-2.22) rules that applied on this line
    chain: list = field(default_factory=list)  # (at, owner mask, q, class, hi, take, first, branch) splits its goods pass (2.22)
    stretch: tuple = ()  # a bypass: (stream coordinate its own path starts, the main's span to the re-join, its own length to it)
    path_splits: list = field(default_factory=list)  # (split node, the edge its goods take: a branch's name or None) in path order (R22.4)
    end_mask: int = 1  # owners whose goods reach this line's flow end
    item_routed: bool = False  # a branch sorting by its item (takes those owners' goods whole), not a share
    fraction: float = 0.0  # share branch: the fraction of the goods passing its diverter that it takes
    buffers: list = field(default_factory=list)  # FIFO buffers the goods on this line pass (2.24): (stop, pitch, period, start, first rank, rank mode, slug)
    identity_shift: int = 0  # slot identity = index + this: minus the slots the buffers ahead of this line's goods hold back (+ a slug's phase)
    holds: int = 0  # slots the buffers on this line's path hold back (the stream gets that many more)


@dataclass
class StreamTree:
    root: object
    members: dict = field(default_factory=dict)  # object name -> LineStream
    length: float = 0.0  # wrap length (0 = single line: its own curve length)
    spacing: float = 0.8
    min_spacing: float = 0.0  # the closest the goods may follow: item + clearance (+ a merge's lag)
    effective_ph: float = 0.0  # what actually flows: the throughput, or a buffer's out rate below it
    actual_spacing: float = 0.8  # the slot pitch the tree really uses (the wrap holds a whole number of slots)
    phase_s: float = 0.0  # Stream Phase (scene seconds): a slot centre meets a rack's hand-over times
    phase_m: float = 0.0  # the same in metres of travel at scene second 0
    throttle: object = None  # (line name, module index, out rate, its source) of the buffer holding the group back
    buffer_info: dict = field(default_factory=dict)  # (line name, index) -> the buffer panel's numbers
    sources: int = 0  # K feeders owning slots
    routes: list = field(default_factory=list)  # (lo, hi, u, owner mask)
    exits: int = 0  # share routing: exit portions per slot (branches, then "stays on the main"); 0 = routing by class
    exit_splits: list = field(default_factory=list)  # cumulative upper bounds of the exit portions (all but the last)
    speed: float = 0.0
    fill: float = 1.0
    seed: int = 0
    splits: list = field(default_factory=list)  # cumulative owner shares (OWNER_SLOTS long)
    throughput_ph: float = 0.0  # total items/h on the stream: the owners' targets, else their capacities (speed / pitch)
    extra_slots: int = 0  # slots the stream has beyond its lines: items waiting in buffers or on transfers keep theirs
    switch_time: float = math.inf  # scene seconds: from then on the root's slots are thinned (a buffer is full, 2.24)
    switch_fraction: float = 1.0  # to this share (its Output %)
    targeted: bool = False  # some owner set a target rate (the spacing then follows the total)
    owner_names: list = field(default_factory=list)  # root first, then the feeders owning slots
    rates: list = field(default_factory=list)  # items/h per owner
    slot_length: float = 0.0  # longest item any member draws: every member centres its goods in slots this long
    transfers: list = field(default_factory=list)  # pop-up transfers: (id, c0, c1, owner mask, class lo, hi, lift height, stop, hold, turn, inbound, branch, line, except)
    transfer_ease: float = 0.05  # travel over which goods slow down to a stop on a right-angle transfer (model/transfer_motion)
    ramp: float = 0.05  # how far the goods travel while a transfer's belts rise or lower
    flow: object = None  # operators/flows.GroupFlow: populations, flows and splits (simple_flow, 2.22)
    by_class: bool = False  # a diverter Routes by item class: the route keys are item classes

    @property
    def shared(self) -> bool:
        return len(self.members) > 1


def parent_of(context, obj):
    """(kind, main line, module index) the goods of `obj` come from / go to:
    'MERGE' when its end is docked (goods leave onto the main), 'DIVERTER'
    when its start is docked on a routed diverter (goods come from the
    main), 'CONTINUE' when it starts where another line ends and carries
    its goods on (detect_junctions.tail_continuation). None for a standalone
    line or an unrouted branch."""
    from .detect_junctions import docked_diverter, docked_junction, tail_continuation

    dock = docked_junction(context, obj)
    divert = docked_diverter(context, obj)
    if dock is not None and divert is not None and is_bypass(divert, dock):
        return 'DIVERTER', divert[0], divert[1]  # a bypass: it takes its share and rejoins downstream
    if dock is not None:
        return 'MERGE', dock[0], dock[1]
    dock = divert
    if dock is not None and dock[0].conveyor_line.populate:
        return 'DIVERTER', dock[0], dock[1]  # by class, by its own item, or its share of the goods
    tail = tail_continuation(context, obj)
    if tail is not None and stream_root(context, tail[0]).conveyor_line.populate:
        return 'CONTINUE', tail[0], tail[1]
    return None


def is_bypass(divert, merge) -> bool:
    """A line leaving a populated main at a diverter and merging back into the
    SAME main further on (simple flow: a re-join adds its share back,
    warehouse_common's resolve). `divert` / `merge` = (main, piece index)."""
    main = divert[0]
    if merge[0] != main or not main.conveyor_line.populate:
        return False
    return merge[1] < divert[1] if main.conveyor_line.reverse else merge[1] > divert[1]


def dock_root(context, obj):
    """The 'master' line of a docked group: follow end docks (merges) and
    start docks (diverters, routed or not) up to the line nobody docks on."""
    from .detect_junctions import docked_diverter, docked_junction, tail_continuation

    seen = set()
    line = obj
    while line.name not in seen:
        seen.add(line.name)
        dock = docked_junction(context, line) or docked_diverter(context, line) or tail_continuation(context, line)
        if dock is None:
            return line
        line = dock[0]
    return line


def stream_root(context, obj):
    seen = set()
    line = obj
    while line.name not in seen:
        seen.add(line.name)
        parent = parent_of(context, line)
        if parent is None:
            return line
        line = parent[1]
    return line


WRAP_MARGIN = 1e-5  # the wrap's share over its whole pitches (tree_for)


def _f(settings, key: str, default: float = 0.0) -> float:
    return float(settings.get(key, default))


def path_length_m(obj) -> float:
    """How far `obj`'s goods ride from its stream offset to its flow end: the
    path the populate tree draws them on, by length (build_line's
    path_length_m: a 45 degree divert's blend off the main runs a little
    longer than the main's stretch it replaces), full_length_m on a line not
    built since."""
    s = obj.conveyor_line
    v = s.get("path_length_m")
    return float(v) if v is not None else _f(s, "full_length_m")


def tree_for(context, obj) -> StreamTree:
    from ..geonodes.populate import MIN_CLEARANCE
    from .build_line import all_lines
    from .populate import populate_item_length

    scene = context.scene
    root = stream_root(context, obj)
    lines = [line for line in all_lines(scene) if stream_root(context, line) == root]
    tree = StreamTree(root=root)
    parents = {line.name: parent_of(context, line) for line in lines}
    by_name = {line.name: line for line in lines}
    for line in lines:
        tree.members[line.name] = LineStream(parent=parents[line.name])

    # Offsets, top-down from the root.
    def children(m):
        return [line for line in lines if parents[line.name] is not None and parents[line.name][1] == m]

    def assign(m):
        cm = tree.members[m.name]
        for child in children(m):
            cs = tree.members[child.name]
            kind = parents[child.name][0]
            s = child.conveyor_line
            if kind == 'MERGE':
                s_face_full = _f(s, "continue_from") + _f(m.conveyor_line, "prefix_length_m")
                cs.entry_u = cm.offset + s_face_full
                cs.offset = cs.entry_u - (_f(s, "prefix_length_m") + _f(s, "own_length_m") + _f(s, "continue_extra_m"))
            elif kind == 'CONTINUE':  # its item path starts with the parent's whole path (detect_junctions._sync_tail)
                cs.offset = cm.offset
                cs.prefix_u = cm.offset + _f(m.conveyor_line, "full_length_m")  # the parent's end; pulled back by the handover margin below
            else:  # DIVERTER: the branch's arcs already are the main's full arcs
                cs.offset = cm.offset
                cs.prefix_u = cm.offset + _f(s, "branch_from") - _f(s, "branch_blend")
                cs.only_class = int(m.conveyor_line.segments[parents[child.name][2]].route_class)
                if s.get("continue_target") == m.name:
                    # A bypass: its goods keep pace with the main's slots over its
                    # own path (longer or shorter than the main's stretch), so they
                    # merge back into the very slots they left -- nothing collides.
                    start = cm.offset + _f(s, "prefix_length_m")
                    rejoin = cm.offset + _f(m.conveyor_line, "prefix_length_m") + _f(s, "continue_from")
                    length = _f(s, "own_length_m") + _f(s, "continue_extra_m")
                    if rejoin - start > 0.05 and length > 0.05:
                        cs.stretch = (start, rejoin - start, length)
            assign(child)

    assign(root)
    shift = -min(ls.offset for ls in tree.members.values())
    for ls in tree.members.values():
        ls.offset += shift
        ls.entry_u += shift
        ls.prefix_u += shift
    tree.length = max(ls.offset + _f(by_name[name].conveyor_line, "full_length_m") for name, ls in tree.members.items())

    # Owners: the root and every populated feeder, in name order.
    feeders = sorted(name for name, ls in tree.members.items()
                     if ls.parent is not None and ls.parent[0] == 'MERGE' and by_name[name].conveyor_line.populate)
    owner_of = {name: k for k, name in enumerate(feeders, start=1)}
    tree.sources = len(feeders)

    def ancestors(line) -> set:
        out, cur = set(), line
        while True:
            out.add(cur.name)
            p = parents.get(cur.name)
            if p is None:
                return out
            cur = p[1]

    def ride_set(name) -> set:
        """Lines whose path the goods of feeder `name` travel after leaving it."""
        out, cur = set(), by_name[name]
        while True:
            p = parents.get(cur.name)
            if p is None or p[0] != 'MERGE':
                return out
            cur = p[1]
            out.add(cur.name)

    def owners_at(line, u: float) -> int:
        """Owner mask of the goods present on `line`'s path at stream coordinate u."""
        anc = ancestors(line)
        mask = 1
        for name, k in owner_of.items():
            if tree.members[name].entry_u <= u + 1e-6 and ride_set(name) & anc:
                mask |= 1 << k
        return mask

    NO_OWNER = 1 << 30  # a mask no real owner matches (mask 0 would mean "everything")
    NO_CLASS = 1 << 20  # a route key no slot has

    def owner_item(k: int):
        line = root if k == 0 else by_name[feeders[k - 1]]
        return effective_item(context, line)

    def allowed_owners(branch) -> int:
        """Owner mask of the goods a branch takes: the slots of every line
        transporting the SAME item as the branch (its own eyedropped item),
        or everything when the branch uses the placeholder items (then the
        diverter's Route menu picks a class)."""
        item = branch.conveyor_line.populate_item
        if item is None or item == branch:
            return (1 << (len(feeders) + 1)) - 1
        mask = 0
        for k in range(len(feeders) + 1):
            if same_item(owner_item(k), item):
                mask |= 1 << k
        return mask if mask else NO_OWNER

    for name, ls in tree.members.items():
        line = by_name[name]
        if ls.parent is not None and ls.parent[0] == 'MERGE':
            ls.owner = owner_of.get(name, -1)
            ls.mask = (1 << ls.owner) if ls.owner > 0 else 0
        elif ls.parent is not None and ls.parent[0] == 'CONTINUE':
            ls.owner = -1
            ls.mask = owners_at(line, ls.prefix_u) or NO_OWNER  # everything that reaches the parent's end
            ls.fraction = 1.0
        elif ls.parent is not None:  # routed branch
            ls.owner = -1
            ls.mask = owners_at(line, ls.prefix_u) & allowed_owners(line)
            if not ls.mask:
                ls.mask = NO_OWNER
            item = line.conveyor_line.populate_item
            if item is not None and item != line:
                ls.only_class = -1  # routing by item, not by placeholder class
        else:
            ls.owner = 0
            ls.mask = 1
    if not tree.shared:
        tree.members[root.name].mask = 0  # single line: no ownership at all

    # Simple flow (2.22.0; operators/flows.py): the owners of the
    # slots are the root (0) and every populated feeder. What each brings,
    # the group's speed and every split come from warehouse_common's
    # simple_flow over the group's graph, once the slot grid's floor is known
    # (below). A diverter Route by item CLASS makes the route keys item
    # classes; a branch without one then waits for one (takes nothing).
    owners = [root] + [by_name[n] for n in feeders]
    tree.owner_names = [o.name for o in owners]
    by_class = any(ls.parent is not None and ls.parent[0] == 'DIVERTER' and 0 <= ls.only_class < NO_CLASS
                   for ls in tree.members.values())
    tree.by_class = by_class
    for name, ls in tree.members.items():
        if by_class and ls.parent is not None and ls.parent[0] == 'DIVERTER' and ls.only_class < 0:
            item = by_name[name].conveyor_line.populate_item
            if item is None or item == by_name[name]:
                ls.only_class = NO_CLASS  # waits for a Route (another branch routes by class)

    def owners_on(name: str, u: float) -> int:
        """Owner mask of the goods on line `name`'s own path just before
        stream coordinate u. A merge at u itself is not counted yet: R22.1
        makes the ports at one place one boundary, merges landing after the
        split -- goods merged at a junction never leave by its other face."""
        ls = tree.members[name]
        if ls.parent is None:
            mask = 1
        elif ls.parent[0] == 'MERGE':
            mask = (1 << ls.owner) if ls.owner > 0 else 0
        elif ls.parent[0] == 'DIVERTER':
            mask = owners_on(ls.parent[1].name, ls.prefix_u) & allowed_owners(by_name[name])
        else:  # CONTINUE: what reaches the parent's end
            mask = owners_on(ls.parent[1].name, math.inf)
        for fname in owner_of:
            xs = tree.members[fname]
            if xs.parent is not None and xs.parent[1].name == name and xs.entry_u < u - 1e-3:
                mask |= owners_on(fname, math.inf)
        return mask

    if tree.shared:
        for name, ls in tree.members.items():
            if ls.parent is not None and ls.parent[0] in ('DIVERTER', 'CONTINUE'):
                ls.mask = owners_on(name, ls.prefix_u) or NO_OWNER

    # Buffer zones (accumulation modules), in stream coordinates, applied to
    # every line whose goods pass them (same rule as the diverter rules);
    # their stepping queues are planned once the spacing is known (below).
    from ..model import segments as seg_model
    raw_buffers: list = []  # (u of the stop, length, item length, gap, member names whose goods pass it)
    for name, ls in tree.members.items():
        line = by_name[name]
        s = line.conveyor_line
        own_len = _f(s, "own_length_m")
        rev = bool(s.reverse)
        try:
            from .build_line import evaluate_line
            b_spine, segments, width_m = evaluate_line(context, line)
            starts = seg_model.segment_starts(segments, width_m, 0.0)
        except Exception:
            continue

        def end_of(j):
            return starts[j + 1] if j + 1 < len(starts) else b_spine.length

        def run_before(i):
            """Path upstream of segment i where a queue can back up: the
            straights and curves back to the previous module (or the start)."""
            total = 0.0
            step = 1 if rev else -1
            j = i + step
            while 0 <= j < len(segments) and not isinstance(segments[j], (seg_model.Module, seg_model.Spiral)):
                total += end_of(j) - starts[j]
                j += step
            return total

        for i, seg in enumerate(s.segments):
            if i >= len(segments) or seg.kind != 'MODULE' or seg.module_kind != 'BUFFER':
                continue
            length = segments[i].length_m
            g0 = starts[i]
            f0 = _f(s, "prefix_length_m") + (own_len - (g0 + length) if rev else g0)  # flow arc of the zone start
            f1 = f0 + length
            u0, u1 = ls.offset + f0, ls.offset + f1
            hit = []
            for xname, xs in tree.members.items():
                x = by_name[xname]
                if x == line:
                    applies = True
                elif xs.parent is not None and xs.parent[0] == 'MERGE':
                    applies = line.name in ride_set(xname) and xs.entry_u <= u0 + 1e-6
                elif xs.parent is not None:
                    applies = line.name in (ancestors(x) - {xname}) and u1 <= xs.prefix_u + 1e-6
                else:
                    applies = False
                if applies:
                    hit.append(xname)
            gap_m = units.mm_to_bu(seg.buffer_gap_mm, scene)
            raw_buffers.append((u1, length, populate_item_length(context, line), gap_m, hit, line, i, run_before(i)))

    # Shared spacing: no item of any member may overlap its neighbour, even
    # while a merging item lags behind its slot on the longer wedge path.
    lag = max((_f(line.conveyor_line, "continue_extra_m") for line in lines), default=0.0)
    for line in lines:
        s = line.conveyor_line
        if s.populate or line == root or tree.members[line.name].parent is not None:
            tree.slot_length = max(tree.slot_length, populate_item_length(context, line))
    # A continuation takes over where its parent stops drawing: the parent
    # shows a slot until the item's FRONT reaches its end, i.e. its centre
    # is half an item before the end, so the child draws from that centre
    # coordinate on (Prefix is judged on the item's centre) -- the same
    # item, the same place.
    for name, ls in tree.members.items():
        if ls.parent is not None and ls.parent[0] == 'CONTINUE':
            ls.prefix_u -= populate_item_length(context, by_name[name]) / 2.0
    rs = root.conveyor_line
    tree.fill = 1.0  # Population sets the density (Spacing and Fill are pre-2.22 settings, kept untouched)
    tree.seed = 0

    from ..geonodes.populate import OWNER_SLOTS
    from . import flows

    tree.speed = flows.group_speed(lines, root)  # the master's; the stream runs along the flow, Stream Flip mirrors reversed lines
    tree.min_spacing = max((populate_item_length(context, o) + MIN_CLEARANCE + lag for o in owners), default=0.0)
    # Right-angle transfers where the goods stop (model/transfer_motion): the
    # next item must not reach a standing one, so the stream's pitch never
    # goes below the stop's own (the RAT's real cycle limit). The stream is
    # held there silently (a max_population on its in port).
    stop_techs = _rat_stop_techs(context, lines)
    if stop_techs:
        tree.transfer_ease = max(transfer_motion.ease_m(tree.speed, tech) for tech in stop_techs)  # one slow-down for the stream
        from .populate import populate_item_footprint

        footprint = max((populate_item_footprint(context, o) for o in owners), default=2.0 * tree.slot_length)
        stop_pitch = max(transfer_motion.min_pitch_m(footprint, tree.transfer_ease, transfer_motion.hold_m(tree.speed, tech))
                         for tech in stop_techs)
        tree.min_spacing = max(tree.min_spacing, stop_pitch)
    # A pouch sorter carries one item per pouch: the goods' pitch is a whole
    # number of pouch pitches (model/pouch.py), never closer than one.
    from ..config import loader as _loader

    pouch_pitch = 0.0
    root_type = _loader.get_conveyor_types().get(rs.conveyor_type)
    if root_type is not None and root_type.cross_section == "pouch":
        from ..model import pouch as pouch_model

        depth_mm = pouch_model.pouch_dims_mm(rs.pouch_size, rs.pouch_width_mm, rs.pouch_height_mm, rs.pouch_depth_mm)[2]
        pouch_pitch = units.mm_to_bu(pouch_model.pitch_mm(depth_mm, rs.pouch_pitch_mm), scene)
        tree.min_spacing = max(tree.min_spacing, pouch_pitch)
    # The flows: simple_flow over the group's graph (operators/flows.py). A
    # branch Routed by item class takes its class's part, one waiting for a
    # Route nothing, one with its own item those owners' goods whole.
    populated = {line.name: bool(line.conveyor_line.populate) for line in lines}
    legacy = {} if all(flows.is_migrated(line) for line in lines) else flows.legacy_populations(context, root, owners)
    member_u = {name: ls.prefix_u for name, ls in tree.members.items() if ls.parent is not None and ls.parent[0] == 'DIVERTER'}
    item_length = {line.name: populate_item_length(context, line) for line in lines}
    fixed, item_routed = {}, {}
    n_classes = placeholder_classes()

    def classes_on(name: str, u: float) -> set:
        """The item classes still on line `name` just before u: a Route by class
        upstream took its class away; a feeder brings every class again."""
        ls = tree.members[name]
        if ls.parent is not None and ls.parent[0] == 'DIVERTER':
            here = classes_on(ls.parent[1].name, ls.prefix_u)
            if 0 <= ls.only_class < NO_CLASS:
                here &= {ls.only_class}
        elif ls.parent is not None and ls.parent[0] == 'CONTINUE':
            here = classes_on(ls.parent[1].name, math.inf)
        else:
            here = set(range(n_classes))
        for xname, xs in tree.members.items():
            if xs.parent is None or xs.parent[1].name != name:
                continue
            if xs.parent[0] == 'MERGE' and xs.entry_u < u - 1e-3:
                here |= set(range(n_classes))
            elif xs.parent[0] == 'DIVERTER' and 0 <= xs.only_class < NO_CLASS and xs.prefix_u < u - 1e-3:
                here.discard(xs.only_class)
        return here

    for name, ls in tree.members.items():
        if ls.parent is None or ls.parent[0] != 'DIVERTER':
            continue
        if ls.only_class >= NO_CLASS:
            fixed[name] = 0.0
        elif ls.only_class >= 0:
            # Its class's part of the classes still passing there (they come in equal numbers).
            present = classes_on(ls.parent[1].name, ls.prefix_u)
            fixed[name] = (1.0 / len(present)) if ls.only_class in present else 0.0
        else:
            item = by_name[name].conveyor_line.populate_item
            if item is not None and item != by_name[name]:
                passing = owners_on(ls.parent[1].name, ls.prefix_u)
                takes = passing & allowed_owners(by_name[name])
                if takes != passing:
                    # Its item sorts: it takes those owners' goods whole. A branch whose item IS
                    # all that passes (a rack in-feed's load applied by dock_line) keeps its Share.
                    item_routed[name] = ([o.name for k, o in enumerate(owners) if takes & (1 << k)],
                                         [o.name for k, o in enumerate(owners) if passing & (1 << k)])
                    ls.item_routed = True
    dead = {line.name for line in lines if dead_end(context, line)}
    gf = flows.resolve_group(context, lines, parents, root, populated, legacy, member_u, item_length, tree.min_spacing,
                             fixed=fixed, item_routed=item_routed, dead_ends=dead)
    tree.flow = gf
    tree.rates = [gf.owner_flow.get(o.name, 0.0) * 3600.0 for o in owners]
    total = sum(tree.rates) / gf.scale if gf.scale > 1e-12 else 0.0  # what the populations ask, before the grid's floor
    # An accumulation buffer on the main line whose out rate is below what
    # arrives holds the source back (back pressure: the buffer runs full and
    # backs up, operators/buffers.py); a rack's port takes or makes only so
    # many loads an hour (operators/ports.py; index -1 = the port the line
    # starts on, -2 = the port it feeds). The group runs at that and the
    # goods never vanish.
    tree.effective_ph = sum(tree.rates)
    tree.throttle = None
    if tree.effective_ph > 0:
        # (Since 2.24 a buffer holds nothing back here: the stream runs at its
        # sliders and the buffer fills; once full, the animation thins the
        # root to what it lets out -- R22.6 publishes the state before full.)
        from .ports import capacity_of, linked_at

        for anchor in ("origin", "end"):
            dock = linked_at(context, root, anchor)
            if dock is None:
                continue
            capacity = capacity_of(dock[1], populate_item_length(context, root), tree.speed)  # R22: max_population stands in
            if capacity > 0.0 and capacity + 0.5 < tree.effective_ph:
                tree.effective_ph = capacity
                tree.throttle = (root.name, -1 if dock[2] == "out" else -2, capacity, dock[0].name)
        if tree.effective_ph < sum(tree.rates) - 1e-6:
            gf.cap_to(tree.effective_ph / 3600.0)
            tree.rates = [gf.owner_flow.get(o.name, 0.0) * 3600.0 for o in owners]
    tree.throughput_ph = sum(tree.rates)
    tree.targeted = True
    # The slot grid carries every owner's goods: one slot per item of the
    # group's whole flow, never closer than the floor.
    flow_s = tree.throughput_ph / 3600.0
    empty_pitch = max(_f(root.conveyor_line, "full_length_m"), 1.0)  # nothing flows: one slot, not drawn (route_values)
    tree.spacing = max(tree.speed / flow_s if flow_s > 1e-12 else empty_pitch, tree.min_spacing)
    if pouch_pitch > 0.0:
        tree.spacing = pouch_model.quantize_m(max(tree.spacing, pouch_pitch), pouch_pitch)
    # Each owner's part of the slots: its flow over the group's (dealt out
    # evenly by the populate tree, item by item).
    total_rate = sum(tree.rates) or 1.0
    cum, splits = 0.0, []
    for k in range(1, OWNER_SLOTS + 1):
        if k <= len(owners) - 1:
            cum += tree.rates[k - 1] / total_rate
            splits.append(cum)
        else:
            splits.append(1.0)
    tree.splits = splits
    # Where the goods part (simple_flow.branch_of_item): every split's edges
    # in the order the items are dealt -- the same in every add-on -- each
    # taking its local fraction of each owner's goods evenly, by the item's
    # running number (the populate tree's Bresenham). A Route by item class
    # takes its class, a branch with its own item those owners' goods whole.
    # Each line gets the splits its goods pass on their way to and along it,
    # and which edge is its own at each.
    splits_on = {}
    for s in gf.splits.values():
        splits_on.setdefault(s.line, []).append(s)
    for lst in splits_on.values():
        lst.sort(key=lambda s: (s.at_u, s.node))

    def own_splits(name, upto=math.inf):
        return [(s, None) for s in splits_on.get(name, []) if s.at_u < upto - 1e-9]

    def feeder_splits(name, upto):
        """The splits on the feeders' own paths bringing goods onto `name` before `upto`."""
        out = []
        for fname in owner_of:
            xs = tree.members[fname]
            if xs.parent is not None and xs.parent[1].name == name and xs.entry_u < upto - 1e-3:
                out += own_splits(fname) + feeder_splits(fname, math.inf)
        return out

    def path(name, upto=math.inf):
        """[(split, the edge `name`'s goods take there: a branch's name, None = their line's continue)]."""
        ls = tree.members[name]
        out = []
        if ls.parent is not None and ls.parent[0] == 'DIVERTER':
            out += path(ls.parent[1].name, ls.prefix_u)
            s = gf.splits.get(gf.split_of.get(name, ""))
            if s is not None:
                out.append((s, name))
        elif ls.parent is not None and ls.parent[0] == 'CONTINUE':
            out += path(ls.parent[1].name)
        return out + feeder_splits(name, upto) + own_splits(name, upto)

    def onward(name):
        """A feeder's goods ride on past its entry: the splits after it on the line it joins, and on.
        A bypass's goods past their re-join, likewise."""
        ls = tree.members[name]
        if ls.parent is not None and ls.parent[0] == 'DIVERTER' and ls.stretch:
            main = ls.parent[1].name
            back = ls.stretch[0] + ls.stretch[1]
            return [(s, None) for s in splits_on.get(main, []) if s.at_u > back + 1e-3] + onward(main)
        if ls.parent is None or ls.parent[0] != 'MERGE':
            return []
        main = ls.parent[1].name
        return [(s, None) for s in splits_on.get(main, []) if s.at_u > ls.entry_u + 1e-3] + onward(main)

    for name, ls in tree.members.items():
        steps, seen = [], set()
        for s, mine in path(name) + onward(name):
            if s.node not in seen:
                seen.add(s.node)
                steps.append((s, mine))
        steps.sort(key=lambda p: (p[0].at_u, p[0].node))
        ls.path_splits = [(s.node, mine) for s, mine in steps]
        ls.end_mask = owners_on(name, math.inf)
        chain = []
        for s, mine in steps:
            mask = owners_on(s.line, s.at_u)
            if not mask:
                continue
            edges = list(s.edges)
            if edges and edges[-1][0] is None:
                edges = edges[:-1]  # the line's own continue, dealt last: what no branch takes rides on
            remaining, first = 1.0, True
            for dst, frac in edges:
                q = min(max(frac / remaining, 0.0), 1.0) if remaining > 1e-12 else 0.0
                remaining -= frac
                lo, rule_mask = -1, mask
                xs = tree.members.get(dst) if dst is not None else None
                if xs is not None and 0 <= xs.only_class:
                    q, lo = -1.0, xs.only_class  # by item class (NO_CLASS: none)
                elif dst in item_routed:
                    q, rule_mask = 1.0, mask & allowed_owners(by_name[dst])
                chain.append((s.at_u, rule_mask, q, lo, -1, dst == mine, first, dst))
                first = False
        ls.chain = chain
    # The tree fills the wrap with a WHOLE number of slots and widens the
    # pitch to fit (an 18 m line at a 15 m pitch got 18 m slots): every
    # wait, slug and hand-over computed from the pitch was off (found
    # 2026-10-11). The wrap is therefore rounded UP to
    # whole pitches (the slots beyond the lines are never drawn), and the
    # pitch the tree really uses is recomputed the way the tree does it.
    if tree.length <= 0.0:
        tree.length = _f(root.conveyor_line, "full_length_m")
    # A hair over the whole pitches: the tree divides in single precision, and
    # an exact multiple could come out just under it there -- one slot fewer,
    # every pitch 1/n wider than the one published (a 10-slot wrap ran at
    # 1.204 m against 1.083 m: R22.4 test, 2026-10-15).
    tree.length = math.ceil(tree.length / max(tree.spacing, 1e-6) - 1e-6) * tree.spacing * (1.0 + WRAP_MARGIN)
    n_fit = max(int(math.floor(tree.length / max(tree.spacing, 1e-6) + 1e-9)), 1)
    count = max(int(math.floor(n_fit * tree.fill + 1e-9)), 1)
    tree.actual_spacing = max(tree.length / count, populate_item_length(context, root) + 0.005)
    # A root line starting on a rack's "out" port: its slots meet the rack's
    # hand-over times (operators/ports.py, model/clock.py). Every nominal
    # position is behind by phase x speed, so the slug phasing below must
    # know it.
    from .ports import linked_at, out_port_phase

    tree.phase_s = out_port_phase(context, root, tree)
    # A line grown backwards keeps its goods where they were: every piece
    # put in front moved the origin back by its length (operators/segments
    # _prepend stores the sum), so the stream's clock is set back by that
    # distance over the on-screen speed -- otherwise the whole pattern slid
    # back by the new piece (user, 2026-10-12). Not on a line fed by a rack
    # port: its clock is the rack's hand-over.
    shift_m = _f(root.conveyor_line, "stream_shift_m")
    if shift_m > 0.0 and tree.speed > 1e-9 and linked_at(context, root, "origin") is None:
        tree.phase_s -= shift_m / (tree.speed * _time_scale(context))
    tree.phase_m = tree.phase_s * tree.speed * _time_scale(context)  # metres the stream is behind at scene second 0
    # Accumulation buffers (2.24; R22.6; model/buffer_fifo): from
    # t0 each lets out Output % of what arrives -- one item every in-period /
    # Output %, first in first out (warehouse_common buffer_item_times) --
    # the rest wait inside a zone each until it is full; from then on the
    # stream's root runs at what it lets out (its grid slots thinned from the
    # switch time, the items numbered on). Every item keeps its slot: a line
    # whose goods pass a buffer gets its front stop, queue pitch, departure
    # period and start, the first rank it holds, how the ranks are numbered
    # and the slug size (populate tree "Buffer k ...").
    from ..model import buffer_fifo

    fps = context.scene.render.fps / (context.scene.render.fps_base or 1.0)
    t0 = context.scene.frame_start / fps
    scale = _time_scale(context)
    v_s = tree.speed * scale
    slot_s = tree.actual_spacing / v_s if v_s > 1e-9 else math.inf  # scene seconds between grid slots
    sources = tree.sources if tree.shared else 0
    all_owners = (1 << len(tree.owner_names)) - 1
    tree.switch_time, tree.switch_fraction = math.inf, 1.0
    max_wait = 0.0
    for u1, length, item_len, gap_m, hit, bline, bi, _run in raw_buffers:
        seg = bline.conveyor_line.segments[bi]
        pitch = item_len + gap_m
        zones = int(length // pitch) if pitch > 0 else 0
        fraction = int(seg.buffer_out_pct) / 100.0
        slug = zones if seg.buffer_release == 'SLUG' and zones >= 2 else 0
        in_s = flows.buffer_in_flow(context, tree.flow, bline, bi)  # items per operation second arriving
        info = {"in": in_s * 3600.0, "out": in_s * fraction * 3600.0, "zones": zones, "pitch": pitch, "slug": slug,
                "full_s": math.inf}
        tree.buffer_info[(bline.name, bi)] = info
        if zones <= 0 or fraction >= 1.0 - 1e-9 or in_s <= 1e-12 or not math.isfinite(slot_s):
            continue  # nothing piles up: the goods pass through
        half_slot = max(tree.slot_length, item_len) / 2.0
        stop = u1 - gap_m - item_len / 2.0 - half_slot  # the front item's slot coordinate at the photo-eye
        u_entry = u1 - length
        r_scene = in_s * scale  # items per scene second
        period = 1.0 / (fraction * r_scene) if fraction > 1e-9 else 1.0e9  # Output 0 %: nothing leaves
        # Which deal numbers the goods it sees (model/buffer_fifo): the
        # stream's item number when every slot passes, the owner's number when
        # one owner's goods do, after the route edges in front of it.
        here = owners_on(bline.name, u_entry) if tree.shared else 1
        chain = tree.members[bline.name].chain
        n_edges = sum(1 for e in chain if e[0] < u_entry - 1e-9)
        single = here > 0 and here & (here - 1) == 0
        if n_edges == 0 and (not tree.shared or here == all_owners):
            mode, owner = -1, 0
        elif single:
            mode, owner = n_edges, here.bit_length() - 1
        else:
            mode, owner = -1, 0  # several owners and a split before it: the stream's number (v1)
        # The first item held: the first of its goods whose slot reaches the stop at t0 or later.
        k = math.ceil((t0 - stop / v_s - tree.phase_s) / slot_s - 1e-9)
        first = None
        for _ in range(100000):
            own, index = buffer_fifo.slot_owner(k, tree.splits, sources)
            if mode == -1:
                first = k
                break
            if own == owner:
                rank, stays = buffer_fifo.chain_index(own, index, chain, mode) if mode > 0 else (index, True)
                if stays:
                    first = rank
                    break
            k += 1
        if first is None:
            continue
        start = tree.phase_s + k * slot_s + stop / v_s  # it reaches the stop
        full = start + zones / ((1.0 - fraction) * r_scene)
        info["full_s"] = full
        switch = full - stop / v_s  # slots crossing the origin from then on reach the stop once it is full
        if switch < tree.switch_time:
            tree.switch_time, tree.switch_fraction = switch, fraction
        max_wait = max(max_wait, (zones + slug + 1) * period)
        for xname in hit:
            tree.members[xname].buffers.append((stop, pitch, period, start, float(first), mode, slug))
    for ls in tree.members.values():
        ls.buffers.sort(key=lambda b: b[0])
    # The slots run on while their items wait: the stream has that many more,
    # so an item still in a buffer keeps its slot until it has gone.
    tree.extra_slots = int(math.ceil(v_s * max_wait / tree.actual_spacing)) + 2 if max_wait > 0.0 else 0
    # The goods that stand on right-angle transfers arrive later: the stream
    # runs that much longer beyond its lines (invisible slots), so they still
    # reach the end before it wraps.
    stand_lag = sum(transfer_motion.lag_m(tree.transfer_ease, transfer_motion.hold_m(tree.speed, tech)) for tech in stop_techs)
    tree.extra_slots += transfer_motion.extra_slots(stand_lag, tree.actual_spacing)
    tree.ramp = min(max(0.3 * tree.speed, 0.03), 0.2)  # belts rise / lower in ~0.3 s (Interroll)
    tree.transfers = _transfers(context, tree, by_name, parents, owner_of)
    return tree


def _time_scale(context) -> float:
    from ..props.scene_settings import time_scale

    return time_scale(context.scene)


def line_rate_hint(tree, name: str, total: float) -> float:
    """What flows through member `name` (items/h) as far as the tree knows
    while it is being built: a feeder's own rate, else the whole stream."""
    if name in tree.owner_names and tree.rates:
        return float(tree.rates[tree.owner_names.index(name)])
    return float(total)


def group_speed(context, obj) -> float:
    """The speed a line's goods run at: its group's, its master's (v1: one
    speed per docked group)."""
    try:
        return float(tree_for(context, obj).speed)
    except Exception:
        return float(stream_root(context, obj).conveyor_line.speed_m_s)


def line_speed(context, obj) -> float:
    """The speed of a line's own surface: its group's, and on a bypass as
    much faster as its path is longer than the main's (it keeps pace)."""
    tree = tree_for(context, obj)
    ls = tree.members.get(obj.name)
    k = ls.stretch[2] / ls.stretch[1] if ls is not None and ls.stretch and ls.stretch[1] > 1e-9 else 1.0
    return float(tree.speed) * k


def delivered_ph(context, obj) -> float:
    """Items per hour that actually reach the end of `obj` (the caps are in the flows)."""
    return line_out_ph(context, obj)


def carried_ph(tree) -> float:
    """Items per hour the group actually moves at its speed and pitch: the
    throughput asked for, or less when the pitch sits on its floor."""
    from ..model.throughput import throughput_ph

    return throughput_ph(tree.speed, tree.actual_spacing) if tree.actual_spacing > 1e-9 else 0.0


def same_item(a, b) -> bool:
    """Two carried items are the same goods: one object, or two objects with
    the same wh_load id (a rack's in-feed load applied to a branch is the
    load its main line carries, whichever object stands for it)."""
    if a is None or b is None:
        return a is b
    if a == b:
        return True
    from .._wh import loads as wh_loads
    from .populate import wh_load

    la, lb = wh_load(a), wh_load(b)
    return bool(la and lb and la.get("id") and lb.get("id") and wh_loads.same_load(str(la["id"]), str(lb["id"])))


def effective_item(context, obj):
    """The object a line carries: its own eyedropped item, else -- docked
    on another line -- what the main line of its group carries (the goods
    of a merged conveyor ARE the main conveyor's goods: user, 2026-10-09),
    else None for the placeholder totes."""
    own = obj.conveyor_line.populate_item
    if own is not None and own != obj:
        return own
    root = stream_root(context, obj)
    if root != obj:
        item = root.conveyor_line.populate_item
        if item is not None and item != root:
            return item
    return None


def line_load_ph(context, obj) -> float:
    """Items per hour into `obj`: the flow of its first section (its own
    goods on the main line or a feeder, a branch's share), held to the
    caps (operators/flows.py)."""
    gf = tree_for(context, obj).flow
    ids = gf.sections.get(obj.name) if gf is not None else None
    nf = gf.nodes.get(ids[0]) if ids else None
    return max(nf.flow, 0.0) * gf.scale * 3600.0 if nf is not None else 0.0


def line_out_ph(context, obj) -> float:
    """Items per hour leaving `obj` at its end: its last section's flow
    (branches have taken theirs, feeders added theirs)."""
    gf = tree_for(context, obj).flow
    ids = gf.sections.get(obj.name) if gf is not None else None
    nf = gf.nodes.get(ids[-1]) if ids else None
    return max(nf.flow, 0.0) * gf.scale * 3600.0 if nf is not None else 0.0


def dead_end(context, line) -> bool:
    """True when the goods riding `line` to its flow end have nowhere to go:
    its last flow piece is a right-angle transfer and nothing continues
    beyond the end (no merge, no rack port, no line carrying on). With share
    branches on such a line every item leaves through a branch."""
    from .build_line import all_lines
    from .detect_junctions import TAIL_KEY, docked_junction
    from .ports import dock_at

    s = line.conveyor_line
    if not s.segments:
        return False
    seg = s.segments[0] if s.reverse else s.segments[-1]
    if seg.kind != 'MODULE' or seg.module_kind != 'RAT':
        return False
    if docked_junction(context, line) is not None or dock_at(line, "origin" if s.reverse else "end") is not None:
        return False
    if any(o != line and o.conveyor_line.get(TAIL_KEY) == line.name for o in all_lines(context.scene)):
        return False
    return True


def share_weights(shares_pct: list) -> list:
    """[remainder, share 1, share 2, ...] in percent: explicit shares as
    given (scaled down together when they exceed 100), the rest split
    equally between the remainder (the main line's own goods) and the
    lines left at 0."""
    explicit = [max(float(x), 0.0) for x in shares_pct]
    fixed = sum(x for x in explicit if x > 0)
    if fixed > 100.0:
        explicit = [x * 100.0 / fixed for x in explicit]
        fixed = 100.0
    auto = sum(1 for x in explicit if x <= 0)
    part = (100.0 - fixed) / (auto + 1)
    return [part] + [x if x > 0 else part for x in explicit]


def capacity_ph(context, obj) -> float:
    """Items per hour a line moves on its own: speed over its item pitch
    (centre to centre, never below the item length plus clearance)."""
    from ..geonodes.populate import MIN_CLEARANCE
    from .populate import populate_item_length

    s = obj.conveyor_line
    speed = abs(float(s.speed_m_s))
    pitch = max(units.mm_to_bu(s.populate_spacing_mm, context.scene), populate_item_length(context, obj) + MIN_CLEARANCE)
    return speed * 3600.0 / pitch if pitch > 1e-6 and speed > 1e-6 else 0.0


def _transfers(context, tree: StreamTree, by_name: dict, parents: dict, owner_of: dict) -> list:
    """Pop-up transfers of the group -- RAT corners and 90 degree belt /
    chain / wheel junctions -- as (transfer id, c0, c1, owner mask, class,
    lift height): the transfer's belts are up while an item of those owners
    and that class (-1 any) has its CENTRE in [c0, c1] (stream coordinates).
    The id keys the transfer's moving parts (build_line.transfer_id).

    RAT corner: the goods ride in on the rollers, stop at the centre, the
    belts rise and carry them out sideways, then lower: [centre, the deck's
    edge less a ramp]; on a reversed line the goods arrive sideways on
    raised belts and are set down at the centre. 90 degree merge: the
    feeder's goods cross from the face to the main line's centre on raised
    belts. Routed divert: the taken goods leave the main line's path on
    raised belts and are set down at the face. The last field, `except`:
    a branch whose goods the transfer does not stop (they go straight
    through a corner to its far face), else None."""
    from ..model import transfer_parts as tp
    from .build_line import animated_transfer, resolve_junction_tech, segment_starts_for, transfer_id

    heights = {'BELT': tp.BELT_LIFT, 'CHAIN': tp.CHAIN_LIFT, 'POPUP': tp.WHEEL_LIFT}
    root = tree.root
    populated = (1 if root.conveyor_line.populate else 0) | sum(1 << k for k in owner_of.values())

    def reach_u(feeder: str, line: str):
        """Stream coordinate where the goods of `feeder` reach `line`'s path."""
        cur = feeder
        while True:
            p = parents.get(cur)
            if p is None or p[0] != 'MERGE':
                return None
            if p[1].name == line:
                return tree.members[cur].entry_u
            cur = p[1].name

    def divert_ref(name):
        """The branch whose divert decides which goods are on `name` (itself, or
        the branch a takeaway carries on from), else None: the populate tree
        lifts and stops the goods taken there (2.22: a split's edge)."""
        seen = set()
        while name is not None and name not in seen:
            seen.add(name)
            p = parents.get(name)
            if p is None or p[0] == 'MERGE':
                return None
            if p[0] == 'DIVERTER':
                return name
            name = p[1].name
        return None

    def goods_on(line, c: float):
        """(owner mask, class lo, hi, branch) of the goods passing `line` at c; None when none do."""
        ls = tree.members[line.name]
        if not tree.shared:
            return (0, -1, -1, None) if line.conveyor_line.populate else None
        if ls.parent is not None and ls.parent[0] in ('DIVERTER', 'CONTINUE'):
            mask = ls.mask & populated
            return (mask, -1, -1, divert_ref(line.name)) if mask else None
        mask = (1 << ls.owner) if ls.owner >= 0 else 0
        for name, k in owner_of.items():
            r = reach_u(name, line.name)
            if r is not None and r <= c + 1e-6:
                mask |= 1 << k
        mask &= populated
        return (mask, -1, -1, None) if mask else None

    def side_transfers(name, line, i, sources, tech, height):
        """Goods crossing a junction's face sideways on raised belts / chains /
        wheels (a 90 degree pop-up merge or divert, a RAT's side face): a
        feeder's come in raised and are set down standing on the main line's
        centre; a branch's stop on the centre, stand while lifted, then slide
        out. The stop on a divert sits a hair past the point where the paths
        part, so only the branch draws the standing item. The goods ride up
        and down at the face, the ramp inside the deck, as at a corner: they
        used to rise half a slot out on the feeder and be set down half a
        slot out on the branch, floating over its rollers (2.26.1)."""
        found = []
        hold, turn = transfer_motion.hold_m(tree.speed, tech), transfer_motion.turn_m(tree.speed, tech)
        for other in sources:
            xs = tree.members.get(other) if other else None
            if xs is None or xs.parent is None or xs.parent[1] != line or xs.parent[2] != i:
                continue
            o = by_name[other].conveyor_line
            if xs.parent[0] == 'MERGE':
                if xs.owner < 1:
                    continue  # an unpopulated feeder brings no goods
                c1 = xs.entry_u
                c0 = min(c1 - _f(o, "continue_extra_m") + tree.ramp, c1 - 0.02)  # risen once its centre is a ramp past the face
                found.append((transfer_id(name, i), c0, c1, 1 << xs.owner, -1, -1, height,
                              c1, hold, turn, True, None, name, None))
            else:
                mask = xs.mask & populated
                if mask:
                    c0 = xs.prefix_u
                    c1 = max(c0 + _f(o, "branch_blend") + _f(o, "branch_slide") - tree.ramp, c0 + 0.02)  # set down by the face
                    found.append((transfer_id(name, i), c0, c1, mask, -1, -1,
                                  height, c0 + STOP_PAST_M, hold, turn, False, other, name, None))
        return found

    from ..config import loader

    out = []
    for name, ls in tree.members.items():
        line = by_name[name]
        s = line.conveyor_line
        ctype = loader.get_conveyor_types().get(s.conveyor_type)
        if ctype is None or ctype.cross_section == "omni":
            continue
        try:
            segments, starts, width_m = segment_starts_for(context, line)
        except Exception:
            continue
        own, pre, rev = _f(s, "own_length_m"), _f(s, "prefix_length_m"), bool(s.reverse)
        for i, seg in enumerate(s.segments):
            if i >= len(segments) or seg.kind != 'MODULE':
                continue
            if seg.module_kind == 'RAT' and segments[i].exit != 'STRAIGHT':
                g_c = starts[i] + segments[i].length_m / 2.0  # the corner, geometric arc
                centre = ls.offset + pre + (own - g_c if rev else g_c)
                # The belts carry the goods from the corner to the deck's edge and set
                # them down THERE, the ramp inside the deck (they used to float half a
                # slot further, 16 mm over the takeaway rollers, then drop -- user
                # report 2026-10-09 "the RAT bugs in the animation").
                leg = max(width_m / 2.0 - tree.ramp, 0.02)
                goods = goods_on(line, centre)
                if goods is not None:
                    # The goods stop on the centre and stand while the belts rise
                    # (forward) or set them down (reversed): model/transfer_motion.
                    # Lines on its other faces part there too: the stop sits a hair
                    # past, so only the line an item leaves by draws it standing
                    # (every line drew it, three in one place, 2.26.1). The goods
                    # going straight through to a line on the far face ride the
                    # rollers on: no stop, no lift (`except`, that line's edge).
                    hold, turn = transfer_motion.hold_m(tree.speed, 'BELT'), transfer_motion.turn_m(tree.speed, 'BELT')  # a RAT lifts on belts
                    c0, c1 = (centre - leg, centre) if rev else (centre, centre + leg)
                    stop = centre if rev else centre + STOP_PAST_M
                    far = tree.members.get(getattr(seg, "rat_source_end", "") or "")
                    through = seg.rat_source_end if (not rev and far is not None and far.parent is not None
                                                     and far.parent[0] == 'DIVERTER' and far.parent[1] == line and far.parent[2] == i) else None
                    out.append((transfer_id(name, i), c0, c1, goods[0], goods[1], goods[2], heights['BELT'], stop, hold, turn, rev, goods[3], name,
                                through))
            if seg.module_kind == 'RAT':
                # A straight transfer's side faces: the goods of a line docked there
                # leave (a branch) or come in (a feeder) sideways on the belts, and
                # stop there too. On a transfer
                # the line turns on, the corner above already stops and lifts every
                # item on its centre, whichever side it leaves by.
                if segments[i].exit == 'STRAIGHT':
                    out += side_transfers(name, line, i, (seg.merge_source, seg.merge_source_right), 'BELT', heights['BELT'])
            elif animated_transfer(seg, s):
                tech = resolve_junction_tech(seg)
                out += side_transfers(name, line, i, (seg.merge_source, seg.merge_source_right), tech, heights[tech])
    # In flow order of their stops: the warps are applied one after the other.
    return sorted(out, key=lambda t: t[7] if t[8] > 0.0 else t[1])


def _rat_stop_techs(context, lines) -> list:
    """The technology of every transfer in the group where goods stop: a RAT
    the line turns on, a RAT with lines on its side faces, a 90 degree
    pop-up merge or divert with a line docked on it (model/transfer_motion)."""
    from .build_line import animated_transfer, resolve_junction_tech

    out = []
    for line in lines:
        s = line.conveyor_line
        for seg in s.segments:
            if seg.kind != 'MODULE':
                continue
            if seg.module_kind == 'RAT':
                if seg.module_exit in ('LEFT', 'RIGHT') or seg.merge_source or seg.merge_source_right:
                    out.append('BELT')
            elif animated_transfer(seg, s) and (seg.merge_source or seg.merge_source_right):
                out.append(resolve_junction_tech(seg))
    return out


def junction_load_ph(context, main, index: int):
    """Units per hour a MERGE / DIVERTER on `main` handles: for a merge the
    docked feeders' flow, for a diverter what its docked branches take. None
    while nothing flows."""
    tree = tree_for(context, main)
    if tree.throughput_ph <= 0 or tree.flow is None:
        return None
    seg = main.conveyor_line.segments[index]
    load = 0.0
    for name in (seg.merge_source, seg.merge_source_right):
        line = context.scene.objects.get(name) if name else None
        if line is not None and name in tree.members:
            load += line_load_ph(context, line)
    return load


def branch_share(context, obj):
    """R22.1: the LOCAL fraction (0..1) of the goods passing its diverter that
    branch `obj` takes -- the fraction simple_flow deals at that split, which
    is also what the animation deals (2.22). None for a line that is no branch."""
    gf = tree_for(context, obj).flow
    if gf is None:
        return None
    s = gf.splits.get(gf.split_of.get(obj.name, ""))
    if s is None:
        return None
    return next((min(max(frac, 0.0), 1.0) for dst, frac in s.edges if dst == obj.name), None)


def arrivals_record(context, obj):
    """R22.4: when the goods reach `obj`'s flow end, exactly, for a system port
    there (a rack's in-feed crane meets the real items, not an average):
    {"schedule": [[t_from, phase_s, period_s]], "path": [[fractions, branch]],
    "delay_s": d} in operation seconds -- the slot grid's crossings of the
    stream origin (item k: phase + k period, the populate tree's numbering),
    the deals on the way (the owners', then every split's fractions in
    simple_flow.split_order with the edge toward the port: what the populate
    tree deals by Bresenham), and the travel to the port (the right-angle
    stops on the way included). None for a stopped stream, or where a merge
    (a feeder's, a bypass re-joining), a Route by class, a branch sorting by
    its item, or a buffer lies on the way."""
    from .ports import _clock
    from ..model import transfer_motion

    tree = tree_for(context, obj)
    ls = tree.members.get(obj.name)
    gf = tree.flow
    if ls is None or gf is None or tree.speed <= 1e-9 or tree.throughput_ph <= 0.0 or tree.by_class:
        return None
    if ls.identity_shift or ls.buffers or ls.holds or math.isfinite(tree.switch_time):
        return None  # a buffer holds the goods back on the way, or a full one slows the root
    if tree.shared and ls.end_mask != 1:
        return None  # a feeder's goods reach the end too: a merge on the way
    # The lines the port's goods ride, and where they leave each.
    path_lines, leave_at, cur = [], {}, obj.name
    u_end = float(ls.offset) + path_length_m(obj)
    leave_at[obj.name] = u_end
    while cur is not None:
        path_lines.append(cur)
        p = tree.members[cur].parent
        if p is None:
            break
        if p[0] == 'MERGE':
            return None
        leave_at[p[1].name] = tree.members[cur].prefix_u if p[0] == 'DIVERTER' else math.inf
        cur = p[1].name
    if path_lines[-1] != tree.root.name:
        return None
    for name, xs in tree.members.items():
        main = xs.parent[1].name if xs.parent is not None else None
        if xs.stretch and main in leave_at and name not in leave_at and xs.stretch[0] + xs.stretch[1] < leave_at[main] - 1e-9:
            return None  # a bypass's goods re-join on the way: a merge
    if any(tree.members[name].item_routed for name in path_lines):
        return None  # a branch sorting by its item takes owners whole: not a share
    path = []
    if tree.shared and len(tree.owner_names) > 1:
        total = sum(tree.rates) or 1.0
        path.append([[round(r / total, 9) for r in tree.rates], 0])  # the owners' deal: the root's goods
    branches = {name for name in path_lines if tree.members[name].parent is not None and tree.members[name].parent[0] == 'DIVERTER'}
    for node, mine in ls.path_splits:
        s = gf.splits.get(node)
        if s is None or s.at_u >= u_end - 1e-9 or s.line not in leave_at:
            continue  # (a feeder's own splits: not on the root goods' way)
        fractions = [round(float(f), 9) for _dst, f in s.edges]
        branch = next((j for j, (dst, _f2) in enumerate(s.edges) if dst == mine), None)
        path.append([fractions, branch])
    # The travel: from the stream origin (an item centre half a slot in) to the
    # port, plus the stand at every stop its goods make on the way.
    from .populate import populate_item_length

    inset = max(tree.slot_length, populate_item_length(context, tree.root)) / 2.0
    lag = 0.0
    for t in tree.transfers:
        stop, hold, branch_ref, line_name, through = t[7], t[8], t[11], t[12], t[13]
        if hold <= 0.0 or (through is not None and through in branches):
            continue  # (the goods of a line on a corner's far face ride straight through)
        if branch_ref is not None:
            applies = branch_ref in branches and stop < u_end
        else:
            # A corner's stop sits a hair past where the lines on its faces part:
            # their goods stand there too (it was left out of their delay).
            applies = line_name in leave_at and stop < leave_at[line_name] + 2.0 * STOP_PAST_M
        if applies:
            lag += transfer_motion.lag_m(tree.transfer_ease, hold)
    t_start, scale = _clock(context.scene)
    period = tree.actual_spacing / tree.speed
    phase = (tree.phase_s - t_start) * scale
    return {"schedule": [[0.0, round(phase, 6), round(period, 9)]], "path": path,
            "delay_s": round((u_end - inset + lag) / tree.speed, 6)}


def placeholder_classes() -> int:
    """How many item classes the placeholder goods come in (a diverter's Route picks one)."""
    import bpy

    from .populate import PLACEHOLDER_COLLECTION_NAME

    coll = bpy.data.collections.get(PLACEHOLDER_COLLECTION_NAME)
    return max(len(coll.objects) if coll is not None else 1, 1)
