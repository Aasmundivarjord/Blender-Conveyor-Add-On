"""'Conveyor - Populate' node group: transported items along the full
spine spline.

Layout is deterministic (no jitter, no random thinning): `Item Length`,
`Spacing` and `Fill` give a count; that many items are spread evenly over
the usable span (start + half an item ... end - half an item) so the first
item sits flush with the line's start. Motion is (index * spacing +
seconds * Speed) wrapped over the span: an item rides to the line's very
end and reappears at the start (reverse: the other way round).

Orientation: `heading`, `incline` and `yaw_offset` are sampled from the
spine at the item's arc length and go through the ONE frame group. The
extra yaw (yaw_offset after a right-angle transfer, the item's forward-
axis remap, the user's manual offset) is applied in the item's LOCAL frame
after the tilt -- Rz(h) Rx(p) Rz(yaw) -- so an item sliding sideways up an
incline still has its up along the surface normal. Lane/height offsets are
rotated by the frame (not the yaw) before being added: a raw world-space
offset would sink the item into an inclined belt (v1 bug 4.1.7).

Pop-up transfers (RAT corners, 90 degree belt / chain / wheel junctions):
`Transfer k From/To` is the stretch of the stream (item-centre coordinates)
over which transfer k carries goods, for the slot owners in `Mask` and the
item class `Class` (operators/stream.py). An item inside it rides `Height`
higher (the belts lifted it off the rollers). The slot grid is deterministic
in time, so the group also outputs `Lift k`: how far transfer k's belts are
up right now (0..1), from the slot nearest its window -- the line tree
raises the transfer's moving parts by it (cross_sections/common.build_parts).
Parametric in time: no simulation, scrubbing works.

Accumulation buffers (2.24; `Buffer k ...`, model/buffer_fifo.py):
a FIFO. From t0 a buffer lets out Output % of what arrives -- one item every
`Period`, from `First` (the first rank it holds) at `Start` -- the rest roll
up to the queue and stand a zone each (`Pitch`) behind the front `Stop`,
stepping up as the front leaves (`Slug` > 0: a whole slug at once). An
item's rank (the FIFO order) is its item number, its owner's number, or its
number after n route edges (`Rank`). Every item keeps its slot: one that
waited is drawn behind it by the time it waited, so the stream has `Stream
Extra Slots` more slots and wraps that much later. Once the buffer is full
the stream's root runs at what it lets out: from `Switch Time` its slots are
thinned to `Switch Fraction` (Bresenham) and the items numbered on.

Simple flow (2.22.0): every slot has an item NUMBER, k = the k-th
item centre to cross the stream origin (item 0 at `Stream Phase`; k = wraps
x slots - identity), as warehouse_common's simple_flow counts them. The
owners deal the items in order, each its share evenly (`Owner Split k`,
sequential Bresenham), and every split on the line's path deals them the way
simple_flow.branch_of_item does: `Route k` is one EDGE of a split, in the
order the split deals (operators/stream.py chain) -- its local `Share` of
the items still undealt there, or an item class (`Share` < 0) -- `Take` when
it is this line's own way on, `First` on a split's first edge. An item's
running number goes with it (its number among the items its edge takes, or
among those left): the same items leave at a divert in every add-on.
"""
from __future__ import annotations

import math

import bpy

from .builder_common import NodeGraph, get_or_create_tree, mark_tree_built
from .frame import frame_rotation

NODE_GROUP_NAME = "Conveyor - Populate"
TREE_VERSION = 31  # 31: Transfer k Except, a corner's straight-through goods (2.26.1); 30: buffers as a FIFO, the root thinned once one is full (2.24); 29: simple flow (2.22)

MIN_CLEARANCE = 0.005  # items can never touch, whatever Spacing says


def _sample_attr(g: NodeGraph, curve, name: str, length):
    n = g.node('GeometryNodeSampleCurve', mode='LENGTH', data_type='FLOAT')
    n.use_all_curves = False
    g.link(curve, n.inputs["Curves"])
    g.link(g.named_attribute(name), n.inputs["Value"])
    g.link(length, n.inputs["Length"])
    return n


def build(rebuild: bool = False) -> bpy.types.NodeTree:
    tree, needs_build = get_or_create_tree(NODE_GROUP_NAME, TREE_VERSION, rebuild=rebuild)
    if not needs_build:
        return tree
    g = NodeGraph(tree)

    g.input("Curve", 'NodeSocketGeometry')
    g.input("Item", 'NodeSocketObject')
    g.input("Use Item", 'NodeSocketBool', default=False)
    g.input("Placeholders", 'NodeSocketCollection')
    g.input("Placeholder Count", 'NodeSocketInt', default=1, min_value=1)
    g.input("Item Length", 'NodeSocketFloat', default=0.6, min_value=0.02, subtype='DISTANCE')
    g.input("Slot Length", 'NodeSocketFloat', default=0.0, min_value=0.0, subtype='DISTANCE')  # shared stream: its longest item
    g.input("Item Bottom", 'NodeSocketFloat', default=0.0, subtype='DISTANCE')
    g.input("Spacing", 'NodeSocketFloat', default=0.8, min_value=0.02, subtype='DISTANCE')
    g.input("Fill", 'NodeSocketFloat', default=1.0, min_value=0.01, max_value=1.0, subtype='FACTOR')
    g.input("Lane Offset", 'NodeSocketFloat', default=0.0, subtype='DISTANCE')
    g.input("Height Offset", 'NodeSocketFloat', default=0.0, subtype='DISTANCE')
    g.input("Item Yaw", 'NodeSocketFloat', default=0.0, subtype='ANGLE')
    g.input("Speed", 'NodeSocketFloat', default=0.0)
    g.input("Seed", 'NodeSocketInt', default=0)
    # Routing (operators/stream.py): the stream may follow a
    # longer/shorter path than this curve and show only one item class.
    g.input("Stream Length", 'NodeSocketFloat', default=0.0, min_value=0.0)  # wrap length; 0 = this curve's length
    g.input("Stream Offset", 'NodeSocketFloat', default=0.0)  # u = arc + offset (operators/stream.py); negative for queues
    g.input("Stream Flip", 'NodeSocketBool', default=False)  # reversed line: flow runs from the curve's end to its start
    g.input("Owner Mask", 'NodeSocketInt', default=0, min_value=0)  # slot owners drawn here; 0 = all
    g.input("Stream Sources", 'NodeSocketInt', default=0, min_value=0)  # K feeders owning slots
    for k in range(1, OWNER_SLOTS + 1):  # cumulative share of owners 0..k-1 (1.0 = unused)
        g.input(f"Owner Split {k}", 'NodeSocketFloat', default=1.0, min_value=0.0, max_value=1.0)
    g.input("Prefix", 'NodeSocketFloat', default=0.0, min_value=0.0)  # stream coordinate before which another line draws
    add_route_inputs(g)
    add_stretch_inputs(g)
    # Accumulation buffers on the goods' path (operators/stream.py, model/buffer_fifo.py): a FIFO; the
    # stream's slots run on while their items wait.
    g.input("Stream Extra Slots", 'NodeSocketInt', default=0, min_value=0)  # slots beyond the lines: waiting items keep theirs
    g.input("Identity Shift", 'NodeSocketInt', default=0)  # slot identity = index + this (unused since 2.24: 0)
    g.input("Stream Phase", 'NodeSocketFloat', default=0.0)  # scene seconds the stream's clock is behind the scene's (a rack's hand-over times)
    add_buffer_inputs(g)
    add_transfer_inputs(g, with_ids=False)
    g.output("Instances", 'NodeSocketGeometry')
    for k in range(1, TRANSFER_SLOTS + 1):
        g.output(f"Lift {k}", 'NodeSocketFloat')

    gi = g.node('NodeGroupInput')
    curve = gi.outputs["Curve"]
    item = gi.outputs["Item"]
    use_item = gi.outputs["Use Item"]
    placeholders = gi.outputs["Placeholders"]
    placeholder_count = gi.outputs["Placeholder Count"]
    item_length = gi.outputs["Item Length"]
    item_bottom = gi.outputs["Item Bottom"]
    spacing = gi.outputs["Spacing"]
    fill = gi.outputs["Fill"]
    lane_offset = gi.outputs["Lane Offset"]
    height_offset = gi.outputs["Height Offset"]
    item_yaw = gi.outputs["Item Yaw"]
    speed = gi.outputs["Speed"]
    seed = gi.outputs["Seed"]

    # ---- Count and spacing.
    g.stage("Count and spacing", "how many slots fit the stream's span and how far apart they are")
    length_node = g.node('GeometryNodeCurveLength')
    g.link(curve, length_node.inputs["Curve"])
    total = length_node.outputs["Length"]
    stream_in = gi.outputs["Stream Length"]
    # Wrap span W of the (possibly shared) stream, in stream coordinates u.
    span = g.switch('FLOAT', g.compare('FLOAT', 'GREATER_THAN', stream_in, 0.001), total, stream_in)
    # The item's centre sits half a SLOT into its slot. Every line of a
    # shared stream must use the same slot (the group's longest item): with
    # its own item length a line carrying small items put them (L1 - L2) / 2
    # off the grid, into the neighbouring slot's goods after a merge.
    slot_length = g.math('MAXIMUM', gi.outputs["Slot Length"], item_length)
    inset = g.math('MULTIPLY', slot_length, 0.5)
    min_spacing = g.math('ADD', item_length, MIN_CLEARANCE)
    safe_spacing = g.math('MAXIMUM', spacing, min_spacing)
    n_fit = g.math('MAXIMUM', g.math('FLOOR', g.math('DIVIDE', span, safe_spacing)), 1.0)
    count = g.math('MAXIMUM', g.math('FLOOR', g.math('MULTIPLY', n_fit, fill)), 1.0)
    # Loop spacing: the span divided by the count, so the wrapped item never
    # lands on the first one and every item stays on ONE grid through the
    # wrap (slot_pitch() repeats this for the fork lifts).
    actual_spacing = g.math('MAXIMUM', g.math('DIVIDE', span, count), min_spacing)

    # Buffers hold goods back by whole slots: the stream has that many slots
    # more and wraps that much later, so the tail of every path stays full.
    extra = gi.outputs["Stream Extra Slots"]
    count_ext = g.math('ADD', count, extra)
    span_ext = g.math('ADD', span, g.math('MULTIPLY', extra, actual_spacing))

    g.stage("Slots", "one point per slot")
    points_node = g.node('GeometryNodeCurveToPoints', mode='COUNT')
    g.link(curve, points_node.inputs["Curve"])
    g.link(count_ext, points_node.inputs["Count"])
    points = points_node.outputs["Points"]

    # ---- Arc-length position of each item, wrapped over the span.
    g.stage("Arc position", "where each slot is now: index x spacing + time x speed, wrapped over the span")
    base = g.math('MULTIPLY', g.index(), actual_spacing)
    traveled = g.math('MULTIPLY', g.math('SUBTRACT', g.scene_seconds(), gi.outputs["Stream Phase"]), speed)
    raw = g.math('ADD', base, traveled)
    # Double modulo keeps the result in [0, span) for negative Speed too.
    u_nominal = g.math('MODULO', g.math('ADD', g.math('MODULO', raw, span_ext), span_ext), span_ext)
    # The slot's identity (its class is seeded by it), modulo the slot count:
    # the same slot has the same identity on every line.
    ident = g.math('ADD', g.index(), gi.outputs["Identity Shift"])
    ident = g.math('MODULO', g.math('ADD', g.math('MODULO', ident, count_ext), count_ext), count_ext)

    # ---- Who the slot belongs to and what it carries (before the transfers: they stop only their goods).
    g.stage("Owner and class", "the item's number, the owner dealt it, its item class, and the splits it passes (simple_flow)")
    pick = g.node('FunctionNodeRandomValue', data_type='INT')  # the placeholder = the item class
    pick.inputs["Min"].default_value = 0
    g.link(g.math('SUBTRACT', placeholder_count, 1.0), pick.inputs["Max"])
    g.link(seed, pick.inputs["Seed"])
    g.link(ident, pick.inputs["ID"])
    item_class = g.switch('INT', use_item, pick.outputs["Value"], 0)  # 0 with an eyedropped item
    # The item's number in the stream (simple_flow): the k-th item centre to
    # cross the stream origin, item 0 at Stream Phase -- the slot's wraps x
    # the slots, minus its identity. Unbounded, so the dealing never repeats.
    raw_id = g.math('ADD', g.math('MULTIPLY', ident, actual_spacing), traveled)
    wraps = g.math('FLOOR', g.math('DIVIDE', raw_id, span_ext))
    k_item = g.math('SUBTRACT', g.math('MULTIPLY', wraps, count_ext), ident)
    # Once a buffer is full the root runs at what it lets out: from the switch
    # its slots are thinned to that share and the items numbered on (2.24).
    k_item, carried = root_switch(g, gi, k_item, actual_spacing, speed)
    # The owners deal the items, each its share evenly; then every split on
    # this line's path, edge by edge, as every add-on deals them.
    owner, owner_index = slot_owner(g, gi, k_item)
    taken_at, hidden_after, route_index = route_chain(g, gi, owner, owner_index, item_class)

    # ---- The accumulation buffers on the path: first in, first out.
    g.stage("Buffers", "Output % of what arrives leaves, one item a period; the rest wait a zone each and step up (model/buffer_fifo)")
    u_buffered = fifo_buffers(g, gi, u_nominal, speed, k_item, owner_index, route_index)

    def owner_in(mask):
        return owner_matches(g, mask, owner)

    def class_in(lo, hi=None):
        return key_in(g, item_class, lo, hi)

    def goods_of(k):
        """Transfer k's goods: by owner, and those its Rule's edge takes (or its class)."""
        rule = gi.outputs[f"Transfer {k} Rule"]
        sel = class_in(gi.outputs[f"Transfer {k} Class"], gi.outputs[f"Transfer {k} Hi"])
        for r, flag in enumerate(taken_at):
            sel = g.switch('BOOLEAN', g.compare('INT', 'EQUAL', rule, r), sel, flag)
        sel = g.switch('BOOLEAN', g.compare('INT', 'GREATER_EQUAL', rule, ROUTE_SLOTS), sel, False)
        skip = gi.outputs[f"Transfer {k} Except"]  # the goods edge `Except` takes ride on: none of this transfer's
        for r, flag in enumerate(taken_at):
            sel = g.boolean('AND', sel, g.boolean('NOT', g.boolean('AND', g.compare('INT', 'EQUAL', skip, r), flag)))
        return g.boolean('AND', owner_in(gi.outputs[f"Transfer {k} Mask"]), sel)

    # ---- Right-angle transfers: the goods a transfer turns slow down to a
    # stop on its centre, stand while the belts rise under them, then go out
    # sideways (model/transfer_motion.shown); on a reversed line they stand
    # there while they are set down. The same warp on every line of the
    # stream, in flow order, so a hand-over stays where it was.
    g.stage("Transfer stops", "arrive, slow to a stop on a right-angle transfer's centre, stand while the belts move, go on (model/transfer_motion)")
    ease = gi.outputs["Transfer Ease"]
    center = g.math('ADD', u_buffered, inset)
    stops = []  # per transfer: (its goods, stopping there, coordinate before its warp, after it)
    for k in range(1, TRANSFER_SLOTS + 1):
        ok = goods_of(k)
        hold = gi.outputs[f"Transfer {k} Hold"]
        stopping = g.boolean('AND', ok, g.compare('FLOAT', 'GREATER_THAN', hold, 0.0))
        warped = stop_warp(g, center, gi.outputs[f"Transfer {k} Stop"], ease, hold)
        after = g.switch('FLOAT', stopping, center, warped)
        stops.append((ok, stopping, center, after))
        center = after
    center_u = center  # the item's centre in stream coordinates (the rules, windows and stops are there)
    # A bypass keeps pace with the main's slots (operators/stream.py stretch):
    # its own path is drawn over the main's span between its divert and its
    # re-join, so its goods merge back into the slots they left.
    s_from, s_span, s_len = gi.outputs["Stretch From"], gi.outputs["Stretch Span"], gi.outputs["Stretch Length"]
    d = g.math('SUBTRACT', center_u, s_from)
    inside = g.math('ADD', s_from, g.math('MULTIPLY', d, g.math('DIVIDE', s_len, g.math('MAXIMUM', s_span, 1e-6))))
    after = g.math('ADD', center_u, g.math('SUBTRACT', s_len, s_span))
    stretched = g.switch('FLOAT', g.compare('FLOAT', 'LESS_THAN', d, s_span), after, inside)
    shown_u = g.switch('FLOAT', g.compare('FLOAT', 'LESS_THAN', d, 0.0), stretched, center_u)
    shown_u = g.switch('FLOAT', g.compare('FLOAT', 'GREATER_THAN', s_span, 0.0), center_u, shown_u)
    u = g.math('SUBTRACT', shown_u, inset)
    # This line's own FLOW arc of the slot: u minus its stream offset. A
    # reversed line runs its flow from the curve's end to its start, so the
    # sampled curve length is mirrored.
    flip = gi.outputs["Stream Flip"]
    local = g.math('SUBTRACT', u, gi.outputs["Stream Offset"])
    center_flow = g.math('ADD', inset, local)
    at_length = g.switch('FLOAT', flip, center_flow, g.math('SUBTRACT', total, center_flow))

    # Items ride all the way to the end (front face at the line's end) and
    # reappear at the start; the old "despawn one spacing early" left the
    # last stretch -- often the last module -- empty.
    # A slot before this line's start or past its end is another line's
    # business (or nobody's).
    front_margin = g.math('ADD', inset, g.math('MULTIPLY', item_length, 0.5))  # slot start -> item front
    visible = g.boolean('AND', g.compare('FLOAT', 'GREATER_EQUAL', local, 0.0),
                        g.compare('FLOAT', 'LESS_EQUAL', local, g.math('SUBTRACT', total, front_margin)))

    # ---- Pose from the spine attributes at that length.
    g.stage("Pose", "position and rotation from the spine's heading and incline at that arc")
    pos_sample = _sample_attr(g, curve, "heading", at_length)
    heading = pos_sample.outputs["Value"]
    position = pos_sample.outputs["Position"]
    incline_raw = _sample_attr(g, curve, "incline", at_length).outputs["Value"]
    level = _sample_attr(g, curve, "item_level", at_length).outputs["Value"]  # 1 on vertical lifts: carriers stay level
    incline = g.switch('FLOAT', g.compare('FLOAT', 'GREATER_THAN', level, 0.5), incline_raw, 0.0)
    yaw_offset = _sample_attr(g, curve, "yaw_offset", at_length).outputs["Value"]

    frame = frame_rotation(g, heading, incline)
    # Items face their direction of travel: on a reversed line that is the
    # opposite of the spine heading.
    extra_yaw = g.math('ADD', g.math('ADD', yaw_offset, item_yaw), g.switch('FLOAT', flip, 0.0, math.pi))
    rotation = g.rotate_rotation(frame, g.euler_to_rotation(g.combine_xyz(z=extra_yaw)), 'LOCAL')

    # ---- Pop-up transfers: the item rides up with the belts. At a stop the
    # belts move while it stands (the last `Turn` of the stand); elsewhere
    # while its centre is inside the transfer's window.
    g.stage("Transfer lift", "the item rides up with a transfer's belts: while it stands at a stop, else inside the window")
    ramp = gi.outputs["Transfer Ramp"]
    item_lift = 0.0
    on_belts = []  # per transfer: how far this slot is on its belts (0..1), a field over the slots
    for k, (ok, stopping, before, after) in enumerate(stops, start=1):
        c0, c1 = gi.outputs[f"Transfer {k} From"], gi.outputs[f"Transfer {k} To"]
        plain = window(g, center_u, c0, c1, ramp)
        hold, turn = gi.outputs[f"Transfer {k} Hold"], gi.outputs[f"Transfer {k} Turn"]
        stand_end = g.math('ADD', gi.outputs[f"Transfer {k} Stop"], g.math('ADD', ease, hold))  # undelayed coordinate where the stand ends
        moved = _ease(g, before, g.math('SUBTRACT', stand_end, turn), stand_end, 0.0, 1.0)  # 0 -> 1 over the last Turn of the stand
        out_lift = g.math('MULTIPLY', moved, _ease(g, after, c1, g.math('ADD', c1, ramp), 1.0, 0.0))  # rises standing, set down past To
        in_lift = g.math('MULTIPLY', _ease(g, after, g.math('SUBTRACT', c0, ramp), c0, 0.0, 1.0), g.math('SUBTRACT', 1.0, moved))  # comes in up, set down standing
        at_stop = g.switch('FLOAT', gi.outputs[f"Transfer {k} Inbound"], out_lift, in_lift)
        lifted = g.switch('FLOAT', ok, 0.0, g.switch('FLOAT', stopping, plain, at_stop))
        on_belts.append(lifted)
        item_lift = g.math('ADD', item_lift, g.math('MULTIPLY', lifted, gi.outputs[f"Transfer {k} Height"]))

    lift = g.math('ADD', g.math('SUBTRACT', height_offset, item_bottom), item_lift)
    lane_scale = _sample_attr(g, curve, "lane_scale", at_length).outputs["Value"]  # 1 -> 0 over an angled-roller centre module
    local_offset = g.combine_xyz(x=g.math('MULTIPLY', lane_offset, lane_scale), z=lift)
    placed = g.set_position(points, position=position, offset=g.rotate_vector(local_offset, frame))

    # ---- Instance source: eyedropped object, or a random placeholder per point.
    g.stage("Instance source", "the eyedropped object or the placeholder collection")
    collection_info = g.node('GeometryNodeCollectionInfo')
    g.link(placeholders, collection_info.inputs["Collection"])
    collection_info.inputs["Separate Children"].default_value = True
    collection_info.inputs["Reset Children"].default_value = True

    item_info = g.node('GeometryNodeObjectInfo', transform_space='ORIGINAL')
    g.link(item, item_info.inputs["Object"])
    item_info.inputs["As Instance"].default_value = True

    # ---- Which slots this line draws.
    g.stage("Which slots show", "owner, routing rules, buffers: only this line's goods, only where they are")
    visible = g.boolean('AND', g.boolean('AND', visible, owner_in(gi.outputs["Owner Mask"])), carried)  # a thinned slot carries nothing
    # Routing: a branch shows only its class from its switch point on; every
    # line of the group hides a routed class past the diverter it leaves at
    # (for the owners whose goods are on that main line there). Decided on
    # the item's CENTRE: Prefix and Route At are where the paths part (the
    # diverter's centre, the start of a blend), and the paths are sampled
    # at the centre -- judged on the slot's start, the main line kept an
    # item half a slot past the turn and the branch picked it up half a
    # slot into its slide: a 0.4 m jump every time (user, 2026-10-10).
    past_prefix = g.compare('FLOAT', 'GREATER_EQUAL', center_u, gi.outputs["Prefix"])
    visible = g.boolean('AND', visible, past_prefix)
    # Past a split where it went another way (route_chain), the item is not this line's.
    visible = g.boolean('AND', visible, g.compare('FLOAT', 'LESS_EQUAL', center_u, hidden_after))

    source = g.switch('GEOMETRY', use_item, collection_info.outputs["Instances"], item_info.outputs["Geometry"])
    # Object Info (As Instance) drops the source's scale (probed in v1); re-inject it.
    scale = g.switch('VECTOR', use_item, g.combine_xyz(1.0, 1.0, 1.0), item_info.outputs["Scale"])

    instances = g.instance_on_points(
        placed, source, rotation=rotation, scale=scale, selection=visible,
        pick_instance=True, instance_index=pick.outputs["Value"],
    )

    # ---- How far each transfer's belts are up right now: the most any
    # slot of its owners and class is on them (an Attribute Statistic over
    # the slots -- the slots' positions go through the buffers, so the belts
    # follow the goods wherever they really are).
    g.stage("Belt lift per transfer", "how far each transfer's belts are up right now (Lift k outputs)")
    lifts = []
    for k, lifted in enumerate(on_belts, start=1):
        stat = g.node('GeometryNodeAttributeStatistic', data_type='FLOAT', domain='POINT')
        g.link(points, stat.inputs["Geometry"])
        g.link(lifted, stat.inputs["Attribute"])
        has_height = g.compare('FLOAT', 'GREATER_THAN', gi.outputs[f"Transfer {k} Height"], 0.0)
        lifts.append(g.switch('FLOAT', has_height, 0.0, stat.outputs["Max"]))

    g.stage("Output", "the instances and the lift values")
    go = g.node('NodeGroupOutput')
    g.link(instances, go.inputs["Instances"])
    for k, lift_k in enumerate(lifts, start=1):
        g.link(lift_k, go.inputs[f"Lift {k}"])
    g.guide("The item stream of one line (or of a group of docked lines sharing a stream): where every slot is right now, what it carries, who draws it, and how far each pop-up transfer's belts are up.")
    mark_tree_built(tree, TREE_VERSION)
    return tree


# ------------------------------------------------ slots, owners, transfers

TRANSFER_SLOTS = 6  # pop-up transfers per group of lines whose belts move with the goods


def add_transfer_inputs(g: NodeGraph, with_ids: bool) -> None:
    """Transfer k From/To (item-centre stream coordinates), Mask, Class,
    Height, and the shared ramp; line trees also get each transfer's Id
    (the spine attribute part_tr of its moving parts)."""
    for k in range(1, TRANSFER_SLOTS + 1):
        if with_ids:
            g.input(f"Transfer {k} Id", 'NodeSocketInt', default=0)
        g.input(f"Transfer {k} From", 'NodeSocketFloat', default=0.0)
        g.input(f"Transfer {k} To", 'NodeSocketFloat', default=-1.0)
        g.input(f"Transfer {k} Mask", 'NodeSocketInt', default=0, min_value=0)
        g.input(f"Transfer {k} Class", 'NodeSocketInt', default=-1, min_value=-1)  # item classes [Class, Hi] it lifts (-1: all)
        g.input(f"Transfer {k} Rule", 'NodeSocketInt', default=-1, min_value=-1)  # >= 0: the goods route edge k takes (>= ROUTE_SLOTS: none)
        g.input(f"Transfer {k} Hi", 'NodeSocketInt', default=-1, min_value=-1)
        g.input(f"Transfer {k} Height", 'NodeSocketFloat', default=0.0)
        g.input(f"Transfer {k} Stop", 'NodeSocketFloat', default=0.0)  # item-centre stream coordinate the goods stop at (a right-angle transfer's centre)
        g.input(f"Transfer {k} Hold", 'NodeSocketFloat', default=0.0, min_value=0.0)  # how long they stand there, in stream travel (0: no stop)
        g.input(f"Transfer {k} Turn", 'NodeSocketFloat', default=0.0, min_value=0.0)  # the last part of the stand, while the belts move
        g.input(f"Transfer {k} Inbound", 'NodeSocketBool', default=False)  # they come in on raised belts and are set down standing
        g.input(f"Transfer {k} Except", 'NodeSocketInt', default=-1, min_value=-1)  # >= 0: the goods route edge k takes are not this transfer's
    g.input("Transfer Ramp", 'NodeSocketFloat', default=0.05, min_value=0.0)
    g.input("Transfer Ease", 'NodeSocketFloat', default=0.05, min_value=0.0)  # travel over which the goods slow down to a stop


TRANSFER_INPUTS = tuple(name for k in range(1, TRANSFER_SLOTS + 1)
                        for name in (f"Transfer {k} From", f"Transfer {k} To", f"Transfer {k} Mask",
                                     f"Transfer {k} Class", f"Transfer {k} Rule", f"Transfer {k} Hi", f"Transfer {k} Height",
                                     f"Transfer {k} Stop", f"Transfer {k} Hold", f"Transfer {k} Turn", f"Transfer {k} Inbound",
                                     f"Transfer {k} Except")) + ("Transfer Ramp", "Transfer Ease")


def _ease(g: NodeGraph, value, a, b, lo, hi):
    """lo at a, hi at b, a smoothstep between (Map Range, clamped)."""
    n = g.node('ShaderNodeMapRange', data_type='FLOAT', interpolation_type='SMOOTHSTEP', clamp=True)
    for name, v in (("Value", value), ("From Min", a), ("From Max", b), ("To Min", lo), ("To Max", hi)):
        if isinstance(v, bpy.types.NodeSocket):
            g.link(v, n.inputs[name])
        else:
            n.inputs[name].default_value = v
    return n.outputs["Result"]


def stop_warp(g: NodeGraph, x, c, ease, hold):
    """model/transfer_motion.shown in nodes: the undelayed coordinate x ->
    where the item is: unchanged before c - ease, slowing (speed falling
    linearly) to a stop at c, standing `hold`, speeding up over the same
    travel, then 2 ease + hold late."""
    a = g.math('MAXIMUM', ease, 1e-4)
    a2 = g.math('MULTIPLY', a, 2.0)
    a4 = g.math('MULTIPLY', a, 4.0)
    start = g.math('SUBTRACT', c, a)
    d = g.math('SUBTRACT', x, start)
    slowing = g.math('SUBTRACT', g.math('ADD', start, d), g.math('DIVIDE', g.math('MULTIPLY', d, d), a4))
    e = g.math('SUBTRACT', d, g.math('ADD', a2, hold))
    speeding = g.math('ADD', c, g.math('DIVIDE', g.math('MULTIPLY', e, e), a4))
    past = g.math('SUBTRACT', x, g.math('ADD', a2, hold))
    shown = g.switch('FLOAT', g.compare('FLOAT', 'LESS_THAN', e, a2), past, speeding)
    shown = g.switch('FLOAT', g.compare('FLOAT', 'LESS_THAN', d, g.math('ADD', a2, hold)), shown, c)
    shown = g.switch('FLOAT', g.compare('FLOAT', 'LESS_THAN', d, a2), shown, slowing)
    return g.switch('FLOAT', g.compare('FLOAT', 'LESS_THAN', d, 0.0), shown, x)


def window(g: NodeGraph, c, c0, c1, ramp):
    """1 while c is inside [c0, c1], easing to 0 over `ramp` either side."""
    def ease(value, a, b, lo, hi):
        n = g.node('ShaderNodeMapRange', data_type='FLOAT', interpolation_type='SMOOTHSTEP', clamp=True)
        for name, v in (("Value", value), ("From Min", a), ("From Max", b), ("To Min", lo), ("To Max", hi)):
            if isinstance(v, bpy.types.NodeSocket):
                g.link(v, n.inputs[name])
            else:
                n.inputs[name].default_value = v
        return n.outputs["Result"]

    rise = ease(c, g.math('SUBTRACT', c0, ramp), c0, 0.0, 1.0)
    fall = ease(c, c1, g.math('ADD', c1, ramp), 1.0, 0.0)
    return g.math('MULTIPLY', rise, fall)


BRESENHAM_EPS = 1e-4  # simple_flow uses 1e-9 in doubles; nodes compute in float32


def _deal(g: NodeGraph, i, q):
    """One step of simple_flow.branch_of_item: an edge with local share q
    takes item i of the items still undealt when floor((i + 1) q) >
    floor(i q). Returns (taken, its number among the taken, its number among
    those left)."""
    a = g.math('FLOOR', g.math('ADD', g.math('MULTIPLY', i, q), BRESENHAM_EPS))
    b = g.math('FLOOR', g.math('ADD', g.math('MULTIPLY', g.math('ADD', i, 1.0), q), BRESENHAM_EPS))
    return g.compare('FLOAT', 'GREATER_THAN', b, a), a, g.math('SUBTRACT', i, b)


def slot_owner(g: NodeGraph, gi, k_item):
    """(owner, the item's number among that owner's): the root (0) and the K
    feeders deal the stream's items in order, each its share evenly
    (`Owner Split k` cumulative); 0 and the item number without sources."""
    i = k_item
    remaining, prev = 1.0, 0.0
    owner, index, done = 0.0, k_item, False
    for j in range(OWNER_SLOTS + 1):
        upper = gi.outputs[f"Owner Split {j + 1}"] if j < OWNER_SLOTS else 1.0
        frac = g.math('MAXIMUM', g.math('SUBTRACT', upper, prev), 0.0)
        q = g.math('MINIMUM', g.math('DIVIDE', frac, g.math('MAXIMUM', remaining, 1e-6)), 1.0)
        taken, a, rest = _deal(g, i, q)
        take = g.boolean('AND', taken, g.boolean('NOT', done))
        owner = g.switch('FLOAT', take, owner, float(j))
        index = g.switch('FLOAT', take, index, a)
        dealt = g.boolean('OR', done, take)
        i = g.switch('FLOAT', dealt, rest, i)
        done = dealt
        remaining = g.math('SUBTRACT', remaining, frac)
        prev = upper
    single = g.compare('INT', 'GREATER_THAN', gi.outputs["Stream Sources"], 0)
    owner = g.switch('INT', single, 0, owner)
    return owner, g.switch('FLOAT', single, k_item, index)


def route_chain(g: NodeGraph, gi, owner, index, item_class):
    """The splits this line's goods pass (operators/stream.py chain), edge by
    edge in the order they deal: ([taken by edge k], the stream coordinate
    past which the item is no longer this line's, [its running number after
    edge k]: its number in the stream it goes on in, what a buffer behind
    that edge ranks it by). An edge applies to the
    owners in its Mask; a split's edges deal an item once (`First` starts a
    split); `Share` >= 0 deals evenly by the item's running number, < 0
    takes the item class [Class, Hi]. Past an edge that took the item the
    other way -- or a `Take` edge (this line's way on) that did not -- the
    item is not this line's."""
    i, decided, hidden = index, False, 1.0e9
    taken_at, indices = [], []
    for k in range(1, ROUTE_SLOTS + 1):
        at, mask, q = gi.outputs[f"Route At {k}"], gi.outputs[f"Route Mask {k}"], gi.outputs[f"Route Share {k}"]
        applies = g.boolean('AND', g.compare('INT', 'GREATER_THAN', mask, 0), owner_matches(g, mask, owner))
        decided_now = g.boolean('AND', decided, g.boolean('NOT', gi.outputs[f"Route First {k}"]))
        share = g.compare('FLOAT', 'GREATER_EQUAL', q, 0.0)
        dealt, a, rest = _deal(g, i, g.math('MAXIMUM', q, 0.0))
        hit = g.switch('BOOLEAN', share, key_in(g, item_class, gi.outputs[f"Route Class {k}"], gi.outputs[f"Route Hi {k}"]), dealt)
        taken = g.boolean('AND', g.boolean('AND', applies, g.boolean('NOT', decided_now)), hit)
        moved = g.boolean('AND', g.boolean('AND', applies, share), g.boolean('NOT', decided_now))
        i = g.switch('FLOAT', taken, g.switch('FLOAT', moved, i, rest), g.switch('FLOAT', share, i, a))
        decided = g.boolean('OR', decided_now, taken)
        away = g.switch('BOOLEAN', gi.outputs[f"Route Take {k}"], taken, g.boolean('NOT', taken))
        hide = g.boolean('AND', applies, away)
        hidden = g.switch('FLOAT', hide, hidden, g.math('MINIMUM', hidden, at))
        taken_at.append(taken)
        indices.append(i)
    return taken_at, hidden, indices


def add_stretch_inputs(g: NodeGraph) -> None:
    """A bypass's stretch (operators/stream.py): where its own path starts
    (stream coordinate), the main's span to the re-join, its own length to
    it. Span 0: none."""
    g.input("Stretch From", 'NodeSocketFloat', default=0.0)
    g.input("Stretch Span", 'NodeSocketFloat', default=0.0, min_value=0.0)
    g.input("Stretch Length", 'NodeSocketFloat', default=0.0, min_value=0.0)


def add_route_inputs(g: NodeGraph) -> None:
    """Route k: one edge of a split on the line's path (operators/stream.py chain)."""
    for k in range(1, ROUTE_SLOTS + 1):
        g.input(f"Route At {k}", 'NodeSocketFloat', default=0.0)  # stream coordinate where the paths part
        g.input(f"Route Mask {k}", 'NodeSocketInt', default=0, min_value=0)  # owners it deals (0: no edge)
        g.input(f"Route Share {k}", 'NodeSocketFloat', default=-1.0, max_value=1.0)  # local share of the undealt; < 0: by class
        g.input(f"Route Class {k}", 'NodeSocketInt', default=-1, min_value=-1)
        g.input(f"Route Hi {k}", 'NodeSocketInt', default=-1, min_value=-1)
        g.input(f"Route Take {k}", 'NodeSocketBool', default=False)  # this line's own way on
        g.input(f"Route First {k}", 'NodeSocketBool', default=False)  # the split's first edge


ROUTE_INPUTS = tuple(name for k in range(1, 9)
                     for name in (f"Route At {k}", f"Route Mask {k}", f"Route Share {k}", f"Route Class {k}",
                                  f"Route Hi {k}", f"Route Take {k}", f"Route First {k}"))


def key_in(g: NodeGraph, key, lo, hi=None):
    """lo < 0 (any), or lo <= key <= hi (hi < 0 or None: just lo)."""
    if hi is None:
        return g.boolean('OR', g.compare('INT', 'LESS_THAN', lo, 0), g.compare('INT', 'EQUAL', key, lo))
    top = g.switch('INT', g.compare('INT', 'LESS_THAN', hi, 0), hi, lo)
    inside = g.boolean('AND', g.compare('INT', 'GREATER_EQUAL', key, lo), g.compare('INT', 'LESS_EQUAL', key, top))
    return g.boolean('OR', g.compare('INT', 'LESS_THAN', lo, 0), inside)


def owner_matches(g: NodeGraph, mask, owner):
    """mask == 0 (no ownership) or bit `owner` of mask is set."""
    bit = g.math('MODULO', g.math('FLOOR', g.math('DIVIDE', mask, g.math('POWER', 2.0, owner))), 2.0)
    return g.boolean('OR', g.compare('INT', 'EQUAL', mask, 0), g.compare('FLOAT', 'GREATER_THAN', bit, 0.5))


BUFFER_SLOTS = 2  # FIFO buffers on one line's path


def add_buffer_inputs(g: NodeGraph) -> None:
    """The FIFO buffers on the goods' path, in flow order (model/buffer_fifo,
    operators/stream.py), and the root's switch once one is full."""
    g.input("Switch Time", 'NodeSocketFloat', default=1.0e9)  # scene s: from then on the root's slots are thinned
    g.input("Switch Fraction", 'NodeSocketFloat', default=1.0, min_value=0.0, max_value=1.0)  # to this share
    for k in range(1, BUFFER_SLOTS + 1):
        g.input(f"Buffer {k} Stop", 'NodeSocketFloat', default=-1.0)  # slot coordinate of the front stop (< 0: none)
        g.input(f"Buffer {k} Pitch", 'NodeSocketFloat', default=0.75, min_value=0.02)  # queue pitch (item + gap)
        g.input(f"Buffer {k} Period", 'NodeSocketFloat', default=0.0, min_value=0.0)  # scene s between departures (0: passes through)
        g.input(f"Buffer {k} Start", 'NodeSocketFloat', default=0.0)  # scene s the first rank held leaves the stop
        g.input(f"Buffer {k} First", 'NodeSocketFloat', default=0.0)  # the first rank held (those before pass through)
        g.input(f"Buffer {k} Rank", 'NodeSocketInt', default=-1)  # -1 the item number, 0 the owner's, n after n route edges
        g.input(f"Buffer {k} Slug", 'NodeSocketInt', default=0, min_value=0)  # > 0: leaves in slugs of that many


BUFFER_INPUTS = ("Switch Time", "Switch Fraction",
                 *(f"Buffer {k} {name}" for k in range(1, BUFFER_SLOTS + 1)
                   for name in ("Stop", "Pitch", "Period", "Start", "First", "Rank", "Slug")))

POPULATE_INPUTS = (
    "Item", "Use Item", "Placeholders", "Placeholder Count", "Item Length", "Slot Length", "Item Bottom",
    "Spacing", "Fill", "Lane Offset", "Height Offset", "Item Yaw", "Seed",
    "Stream Length", "Stream Offset", "Stream Flip", "Owner Mask", "Stream Sources", "Prefix",
    *(f"Owner Split {k}" for k in range(1, 9)),
    "Stream Extra Slots", "Identity Shift", "Stream Phase",
    *BUFFER_INPUTS,
    *ROUTE_INPUTS, "Stretch From", "Stretch Span", "Stretch Length",
)  # + TRANSFER_INPUTS (defined below the builder)
ROUTE_SLOTS = 8  # split edges on a line's path (operators/stream.py chain)
OWNER_SLOTS = 8  # feeders per group that can own slots


def add_populate_inputs(g: NodeGraph) -> None:
    """Declares the populate pass-through inputs on a line tree (shared by
    every cross-section so build_line can set them uniformly)."""
    g.input("Populate", 'NodeSocketBool', default=False)
    g.input("Item", 'NodeSocketObject')
    g.input("Use Item", 'NodeSocketBool', default=False)
    g.input("Placeholders", 'NodeSocketCollection')
    g.input("Placeholder Count", 'NodeSocketInt', default=1, min_value=1)
    g.input("Item Length", 'NodeSocketFloat', default=0.6, min_value=0.02, subtype='DISTANCE')
    g.input("Slot Length", 'NodeSocketFloat', default=0.0, min_value=0.0, subtype='DISTANCE')
    g.input("Item Bottom", 'NodeSocketFloat', default=0.0, subtype='DISTANCE')
    g.input("Spacing", 'NodeSocketFloat', default=0.8, min_value=0.02, subtype='DISTANCE')
    g.input("Fill", 'NodeSocketFloat', default=1.0, min_value=0.01, max_value=1.0, subtype='FACTOR')
    g.input("Lane Offset", 'NodeSocketFloat', default=0.0, subtype='DISTANCE')
    g.input("Height Offset", 'NodeSocketFloat', default=0.0, subtype='DISTANCE')
    g.input("Item Yaw", 'NodeSocketFloat', default=0.0, subtype='ANGLE')
    g.input("Seed", 'NodeSocketInt', default=0)
    g.input("Stream Length", 'NodeSocketFloat', default=0.0, min_value=0.0)  # wrap length; 0 = this curve's length
    g.input("Stream Offset", 'NodeSocketFloat', default=0.0)  # u = arc + offset (operators/stream.py); negative for queues
    g.input("Stream Flip", 'NodeSocketBool', default=False)  # reversed line: flow runs from the curve's end to its start
    g.input("Owner Mask", 'NodeSocketInt', default=0, min_value=0)  # slot owners drawn here; 0 = all
    g.input("Stream Sources", 'NodeSocketInt', default=0, min_value=0)  # K feeders owning slots
    for k in range(1, OWNER_SLOTS + 1):  # cumulative share of owners 0..k-1 (1.0 = unused)
        g.input(f"Owner Split {k}", 'NodeSocketFloat', default=1.0, min_value=0.0, max_value=1.0)
    g.input("Prefix", 'NodeSocketFloat', default=0.0, min_value=0.0)  # stream coordinate before which another line draws
    add_route_inputs(g)
    add_stretch_inputs(g)
    # Accumulation buffers on the goods' path (operators/stream.py, model/buffer_fifo.py): a FIFO; the
    # stream's slots run on while their items wait.
    g.input("Stream Extra Slots", 'NodeSocketInt', default=0, min_value=0)  # slots beyond the lines: waiting items keep theirs
    g.input("Identity Shift", 'NodeSocketInt', default=0)  # slot identity = index + this (unused since 2.24: 0)
    g.input("Stream Phase", 'NodeSocketFloat', default=0.0)  # scene seconds the stream's clock is behind the scene's (a rack's hand-over times)
    add_buffer_inputs(g)
    add_transfer_inputs(g, with_ids=True)
    add_lift_inputs(g)


LIFT_SLOTS = 2  # fork-column lifts per line whose forks are animated


def add_lift_inputs(g: NodeGraph) -> None:
    """Per lift (build_line caches the loop, operators/populate.route_values
    pushes these): whether it exists, the phase putting its forks on the
    slot grid (loop coordinate of the pick corner minus its flow arc), the
    column face's x and the signed tine reach
    (cross_sections/common.build_lift_forks)."""
    for k in range(1, LIFT_SLOTS + 1):
        g.input(f"Lift {k} Active", 'NodeSocketBool', default=False)
        g.input(f"Lift {k} Phase", 'NodeSocketFloat', default=0.0)
        g.input(f"Lift {k} Pick", 'NodeSocketFloat', default=0.0)  # loop coordinate of the pick corner
        g.input(f"Lift {k} Drop", 'NodeSocketFloat', default=0.0)  # ... and of the drop corner
        g.input(f"Lift {k} Face", 'NodeSocketFloat', default=0.0)
        g.input(f"Lift {k} Reach", 'NodeSocketFloat', default=0.0)
        g.input(f"Lift {k} Fork Pitch", 'NodeSocketFloat', default=0.4, min_value=0.05, subtype='DISTANCE')  # forks about this far apart


def slot_pitch(g: NodeGraph, gi, full_curve):
    """(the slot pitch the populate group lays this line's goods on, half
    a slot) from the line tree's inputs -- the same count math as build()."""
    length_node = g.node('GeometryNodeCurveLength')
    g.link(full_curve, length_node.inputs["Curve"])
    total = length_node.outputs["Length"]
    stream_in = gi.outputs["Stream Length"]
    span = g.switch('FLOAT', g.compare('FLOAT', 'GREATER_THAN', stream_in, 0.001), total, stream_in)
    item_length = gi.outputs["Item Length"]
    inset = g.math('MULTIPLY', g.math('MAXIMUM', gi.outputs["Slot Length"], item_length), 0.5)
    min_spacing = g.math('ADD', item_length, MIN_CLEARANCE)
    safe_spacing = g.math('MAXIMUM', gi.outputs["Spacing"], min_spacing)
    n_fit = g.math('MAXIMUM', g.math('FLOOR', g.math('DIVIDE', span, safe_spacing)), 1.0)
    count = g.math('MAXIMUM', g.math('FLOOR', g.math('MULTIPLY', n_fit, gi.outputs["Fill"])), 1.0)
    return g.math('MAXIMUM', g.math('DIVIDE', span, count), min_spacing), inset


def root_switch(g: NodeGraph, gi, k_item, spacing, speed):
    """(the item number, whether the slot carries an item): from `Switch
    Time` -- a buffer is full -- the root's grid slots crossing the stream
    origin are thinned to `Switch Fraction` (Bresenham) and the items
    numbered on, so the owners and splits deal them without gaps
    (model/buffer_fifo.thinned)."""
    period = g.math('DIVIDE', spacing, g.math('MAXIMUM', speed, 1e-6))  # scene s between slots at the origin
    first = g.math('CEIL', g.math('SUBTRACT', g.math('DIVIDE', g.math('SUBTRACT', gi.outputs["Switch Time"], gi.outputs["Stream Phase"]), period), 1e-6))
    after = g.compare('FLOAT', 'GREATER_EQUAL', k_item, first)
    taken, a, _rest = _deal(g, g.math('SUBTRACT', k_item, first), gi.outputs["Switch Fraction"])
    return (g.switch('FLOAT', after, k_item, g.math('ADD', first, a)),
            g.switch('BOOLEAN', after, True, taken))


def fifo_buffers(g: NodeGraph, gi, x, speed, k_item, owner_index, route_index):
    """Where a slot whose nominal slot coordinate is `x` is drawn through the
    FIFO buffers on its path, in flow order (model/buffer_fifo.shown, the
    same formula): before the queue it rolls on; in it, it stands its rank's
    zone behind the front stop and steps up at the belt's speed as the front
    leaves (one zone, or a slug's worth); from its departure it goes on,
    behind its slot by the time it waited. The rank -- the FIFO order -- is
    the item number, the owner's number, or the number after n route edges
    (`Buffer k Rank`)."""
    t = g.scene_seconds()
    v = g.math('MAXIMUM', speed, 1e-6)
    for k in range(1, BUFFER_SLOTS + 1):
        stop, pitch = gi.outputs[f"Buffer {k} Stop"], gi.outputs[f"Buffer {k} Pitch"]
        period, start, first = gi.outputs[f"Buffer {k} Period"], gi.outputs[f"Buffer {k} Start"], gi.outputs[f"Buffer {k} First"]
        mode, slug = gi.outputs[f"Buffer {k} Rank"], gi.outputs[f"Buffer {k} Slug"]
        rank = g.switch('FLOAT', g.compare('INT', 'EQUAL', mode, 0), k_item, owner_index)
        for n, idx in enumerate(route_index, start=1):
            rank = g.switch('FLOAT', g.compare('INT', 'EQUAL', mode, n), rank, idx)
        since = g.math('SUBTRACT', rank, first)  # its place among those held
        active = g.boolean('AND', g.boolean('AND', g.compare('FLOAT', 'GREATER_EQUAL', stop, 0.0), g.compare('FLOAT', 'GREATER_THAN', period, 0.0)),
                           g.compare('FLOAT', 'GREATER_EQUAL', since, 0.0))
        slugged = g.compare('INT', 'GREATER_THAN', slug, 0)
        size = g.math('MAXIMUM', slug, 1.0)
        arrive = g.math('SUBTRACT', t, g.math('DIVIDE', g.math('SUBTRACT', x, stop), v))  # when its slot reaches the front stop
        j = g.switch('FLOAT', slugged, 0.0, g.math('MODULO', since, size))  # its place in a slug, from the front
        base_one = g.math('ADD', start, g.math('MULTIPLY', since, period))
        batch = g.math('FLOOR', g.math('DIVIDE', since, size))
        base_slug = g.math('ADD', start, g.math('MULTIPLY', g.math('SUBTRACT', g.math('MULTIPLY', g.math('ADD', batch, 1.0), size), 1.0), period))
        leave = g.math('MAXIMUM', g.math('SUBTRACT', arrive, g.math('DIVIDE', g.math('MULTIPLY', j, pitch), v)),
                       g.switch('FLOAT', slugged, base_one, base_slug))
        gone = g.compare('FLOAT', 'GREATER_EQUAL', t, leave)
        after = g.math('ADD', g.math('SUBTRACT', stop, g.math('MULTIPLY', j, pitch)), g.math('MULTIPLY', v, g.math('SUBTRACT', t, leave)))
        # The front of the queue: the first rank not gone.
        done_one = g.math('ADD', g.math('FLOOR', g.math('DIVIDE', g.math('SUBTRACT', t, start), period)), 1.0)
        done_slug = g.math('MULTIPLY', g.math('ADD', g.math('FLOOR', g.math('DIVIDE', g.math('SUBTRACT', g.math('SUBTRACT', t, start),
                                                                                                         g.math('MULTIPLY', g.math('SUBTRACT', size, 1.0), period)),
                                                                                   g.math('MULTIPLY', size, period))), 1.0), size)
        head = g.math('ADD', first, g.math('MAXIMUM', g.switch('FLOAT', slugged, done_one, done_slug), 0.0))
        spot = g.math('SUBTRACT', stop, g.math('MULTIPLY', g.math('SUBTRACT', rank, head), pitch))
        last = g.math('ADD', start, g.math('MULTIPLY', g.math('SUBTRACT', g.math('SUBTRACT', head, first), 1.0), period))  # the front last moved off
        step = g.math('MULTIPLY', pitch, size)
        lag = g.math('MAXIMUM', g.math('SUBTRACT', step, g.math('MULTIPLY', v, g.math('SUBTRACT', t, last))), 0.0)
        spot = g.switch('FLOAT', g.compare('FLOAT', 'GREATER_THAN', head, first), spot, g.math('SUBTRACT', spot, lag))
        inside = g.math('MINIMUM', x, spot)
        x = g.switch('FLOAT', active, x, g.switch('FLOAT', gone, inside, after))
    return x


def populate_branch(g: NodeGraph, gi, full_curve, speed):
    """Instantiates the populate group inside a line tree, switched by the
    line's Populate input. Returns (instances geometry (empty when off),
    [Lift k sockets]: how far each pop-up transfer's belts are up now)."""
    kwargs = {name: gi.outputs[name] for name in (*POPULATE_INPUTS, *TRANSFER_INPUTS)}
    node = g.node('GeometryNodeGroup')
    node.node_tree = build()
    g.link(full_curve, node.inputs["Curve"])
    g.link(speed, node.inputs["Speed"])
    for name, socket in kwargs.items():
        g.link(socket, node.inputs[name])
    lifts = [node.outputs[f"Lift {k}"] for k in range(1, TRANSFER_SLOTS + 1)]
    return g.switch('GEOMETRY', gi.outputs["Populate"], None, node.outputs["Instances"]), lifts
