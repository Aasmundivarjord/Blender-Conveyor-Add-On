"""Segment-chain math for a conveyor line. Pure Python, no bpy.

A conveyor line is a chain of catalog segments snapped end to end -- the way
real systems are assembled, and the way CET models them -- not a freeform
curve. Each segment has closed-form geometry (a line or a circular arc), so
the line's heading (yaw) and incline (pitch) at any arc length are exact
scalars. Everything downstream (rails, rollers, legs, populated items) builds
its rotation from those two scalars alone, which makes the frame roll-free
by construction and removes any dependence on sampled curve tangents.

Conventions (shared with geonodes/frame.py and the cross-section builders --
change all or none):
  - heading `h` is yaw about +Z, in radians, CCW from above. h = 0 travels
    along +Y. Turning LEFT increases h. Heading is cumulative, never wrapped,
    so a line that loops back on itself has no +-pi discontinuity to smear.
  - incline `p` is pitch in radians, positive = nose up.
  - the frame at a spine point is Euler XYZ (p, 0, h): Rz(h) * Rx(p).
    forward = R*(0,1,0), right = R*(1,0,0) = (cos h, sin h, 0) -- always
    horizontal, i.e. zero roll -- and up = R*(0,0,1).
  - `yaw_offset` is the extra yaw a transported ITEM carries relative to the
    travel heading. It is 0 until the line passes through a right-angle
    transfer: a RAT pushes product sideways without turning it, so after a
    LEFT exit the travel heading has gained +90 deg while the item has not,
    i.e. yaw_offset -= 90 deg. Rollers use `heading`; items use
    `heading + yaw_offset`.
  - all lengths in meters (Blender units); config/units.py converts at the
    boundary.

Curves and nose-over transitions are sampled into a polyline at a fixed
angular step. The spine is consumed as a POLY curve whose per-point
attributes are interpolated linearly between samples -- exact for
constant-curvature arcs and for straights, so the only approximation is the
chord position error, which at the default 2 degree step is far below a
millimeter at catalog radii.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Literal, Union

Direction = Literal["LEFT", "RIGHT"]
Exit = Literal["STRAIGHT", "LEFT", "RIGHT"]

CURVE_SAMPLE_STEP_DEG = 2.0

# Per-point `kind` attribute values written to the spine.
KIND_STRAIGHT = 0
KIND_CURVE = 1
KIND_INCLINE = 2
KIND_MODULE = 3
KIND_TRANSITION = 4
KIND_SPIRAL = 5
KIND_LIFT = 6  # goods stay level here (item_level attribute)

MODULE_KIND_IDS = {"RAT": 1, "MERGE": 2, "DIVERTER": 3, "BUFFER": 4, "LIFT": 5, "ARB": 6, "PIVOT": 7, "WRAPPER": 8}
TECH_IDS = {"SKEW": 1, "POPUP": 2, "STRIP": 3, "ARB": 4, "PUSHER": 5, "BELT": 6, "CHAIN": 7}  # junction technologies (technologies.json)
# Fork-column vertical lift (model/lift_parts.py): comb frame along the line,
# loop radius (= half the leg spacing), bottom wheel centre under the infeed,
# top wheel centre at least this far above the outfeed.
LIFT_LEN, LIFT_R, LIFT_Z_BOT, LIFT_PICK_CLEAR = 1.47, 0.3375, -0.02, 0.02
EXIT_IDS = {"STRAIGHT": 0, "LEFT": 1, "RIGHT": 2}


@dataclass(frozen=True)
class Straight:
    length_m: float


@dataclass(frozen=True)
class Curve:
    angle_deg: float
    inside_radius_m: float
    direction: Direction = "LEFT"


@dataclass(frozen=True)
class Incline:
    """A straight run at a constant pitch. angle_deg > 0 climbs, < 0
    descends. length_m is measured along the slope."""

    angle_deg: float
    length_m: float


@dataclass(frozen=True)
class Spiral:
    """A helix: a horizontal curve of `angle_deg` (any number of turns) that
    climbs `rise_m` evenly along the way. Pitch is constant, the frame
    turns with the arc (no roll)."""

    angle_deg: float
    inside_radius_m: float
    direction: Direction = "LEFT"
    rise_m: float = 3.0


@dataclass(frozen=True)
class Module:
    """A discrete inserted module (RAT, merge junction, diverter, buffer,
    vertical lift). Occupies a flat footprint `length_m` long (along the
    incoming heading) and one conveyor width across. With exit LEFT/RIGHT
    (RAT only) the spine runs to the footprint's center, turns 90 degrees,
    and leaves through the side edge half a width away. A LIFT (kind
    "LIFT") is a fork-column lift: along the infeed comb to the pick leg,
    straight up, a semicircle of LIFT_R over the top wheel (its centre
    `apex_m` up) onto the other leg, straight down to `height_m` and along
    again -- on out (Z, same heading) or back over the entry (C, heading
    reversed); its `length_m` is that path's length."""

    kind: str
    length_m: float
    exit: Exit = "STRAIGHT"
    height_m: float = 0.0
    shape: str = "Z"
    # Junctions / angled-roller elements (visual + goods behaviour):
    tech: str = ""  # junction technology id (TECH_IDS) or "ARB" / "PIVOT"
    skew: float = 0.0  # radians: direction of the transfer / angled rollers relative to the heading
    turn: float = 0.0  # radians the goods rotate over the module (angled-roller / pivot turn)
    center: bool = False  # angled-roller centre / align: goods drift to the centre lane
    side: int = 0  # geometric side of the face / pivot (+1 right, -1 left)
    flip: bool = False  # the junction layout is mirrored along the geometry (diverter, or a reversed main)
    apex_m: float = 0.0  # LIFT: the top wheel centre above the infeed (lift_apex)


def lift_legs(shape: str = "Z") -> tuple[float, float]:
    """(y of the leg the goods go up, y of the leg they come down) along
    the module: Z picks over the first leg, C over the second."""
    y1, y2 = LIFT_LEN / 2.0 - LIFT_R, LIFT_LEN / 2.0 + LIFT_R
    return (y1, y2) if shape != "C" else (y2, y1)


def lift_apex(height_m: float) -> float:
    """The top wheel centre: just above the outfeed (Qimarox: the top of
    the loop 351 mm over the outfeed = LIFT_PICK_CLEAR + LIFT_R)."""
    return max(height_m, 0.0) + LIFT_PICK_CLEAR


def lift_path_length(height_m: float, apex_m: float, shape: str = "Z") -> float:
    y_pick, y_drop = lift_legs(shape)
    along_out = (LIFT_LEN - y_drop) if shape != "C" else y_drop
    return y_pick + apex_m + math.pi * LIFT_R + (apex_m - height_m) + along_out


def lift_module(height_m: float, shape: str = "Z", apex_m: float | None = None) -> Module:
    if apex_m is None:
        apex_m = max(height_m, 0.0) + LIFT_PICK_CLEAR
    return Module("LIFT", lift_path_length(height_m, apex_m, shape), "STRAIGHT", height_m, shape, apex_m=apex_m)


Segment = Union[Straight, Curve, Incline, Spiral, Module]


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    z: float
    heading: float  # radians
    incline: float  # radians
    yaw_offset: float = 0.0  # radians, see module docstring


@dataclass
class Spine:
    """Sampled centerline of a whole chain. Parallel lists, one entry per
    sample point."""

    x: list[float] = field(default_factory=list)
    y: list[float] = field(default_factory=list)
    z: list[float] = field(default_factory=list)
    heading: list[float] = field(default_factory=list)
    incline: list[float] = field(default_factory=list)
    yaw_offset: list[float] = field(default_factory=list)
    s: list[float] = field(default_factory=list)  # cumulative arc length
    segment_index: list[int] = field(default_factory=list)
    kind: list[int] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.x)

    @property
    def length(self) -> float:
        return self.s[-1] if self.s else 0.0

    def _append(self, pose: Pose, s: float, seg_i: int, kind: int) -> None:
        self.x.append(pose.x)
        self.y.append(pose.y)
        self.z.append(pose.z)
        self.heading.append(pose.heading)
        self.incline.append(pose.incline)
        self.yaw_offset.append(pose.yaw_offset)
        self.s.append(s)
        self.segment_index.append(seg_i)
        self.kind.append(kind)

    def pose_at(self, i: int) -> Pose:
        return Pose(self.x[i], self.y[i], self.z[i], self.heading[i], self.incline[i], self.yaw_offset[i])


def forward_flat(heading: float) -> tuple[float, float]:
    """Unit horizontal travel direction for a heading (see module docstring)."""
    return (-math.sin(heading), math.cos(heading))


def left_of(heading: float) -> tuple[float, float]:
    """Unit horizontal vector to the LEFT of travel."""
    return (-math.cos(heading), -math.sin(heading))


def centerline_radius(curve: Curve, width_m: float) -> float:
    """Catalogs quote a curve's INSIDE radius; the spine runs down the
    centerline, half a conveyor width further out."""
    return curve.inside_radius_m + width_m / 2.0


def segment_length(segment: Segment, width_m: float) -> float:
    """Length of the segment's own spine, excluding any nose-over transition
    inserted ahead of it (see transition_length)."""
    if isinstance(segment, Straight):
        return segment.length_m
    if isinstance(segment, Incline):
        return segment.length_m
    if isinstance(segment, Module):
        if segment.exit == "STRAIGHT" or segment.kind != "RAT":
            return segment.length_m
        return segment.length_m / 2.0 + width_m / 2.0
    if isinstance(segment, Curve):
        return centerline_radius(segment, width_m) * math.radians(abs(segment.angle_deg))
    if isinstance(segment, Spiral):
        arc = spiral_plan_radius(segment, width_m) * math.radians(abs(segment.angle_deg))
        return math.hypot(arc, segment.rise_m)
    raise TypeError(f"Unknown segment type: {type(segment).__name__}")


def spiral_plan_radius(spiral: Spiral, width_m: float) -> float:
    return spiral.inside_radius_m + width_m / 2.0


def spiral_pitch(spiral: Spiral, width_m: float) -> float:
    """Pitch (radians) of the helix: rise over the plan arc."""
    arc = spiral_plan_radius(spiral, width_m) * math.radians(abs(spiral.angle_deg))
    return math.atan2(spiral.rise_m, arc) if arc > 1e-9 else 0.0


def segment_incline(segment: Segment, width_m: float = 0.5) -> float:
    if isinstance(segment, Incline):
        return math.radians(segment.angle_deg)
    if isinstance(segment, Spiral):
        return spiral_pitch(segment, width_m)
    return 0.0


def transition_length(from_incline: float, to_incline: float, radius_m: float) -> float:
    return radius_m * abs(to_incline - from_incline)


def kind_of(segment: Segment) -> int:
    if isinstance(segment, Straight):
        return KIND_STRAIGHT
    if isinstance(segment, Curve):
        return KIND_CURVE
    if isinstance(segment, Incline):
        return KIND_INCLINE
    if isinstance(segment, Module):
        return KIND_LIFT if segment.kind == "LIFT" else KIND_MODULE
    if isinstance(segment, Spiral):
        return KIND_SPIRAL
    raise TypeError(f"Unknown segment type: {type(segment).__name__}")


def _advance_straight(pose: Pose, length_m: float, incline_rad: float) -> Pose:
    fx, fy = forward_flat(pose.heading)
    run = length_m * math.cos(incline_rad)
    rise = length_m * math.sin(incline_rad)
    return Pose(pose.x + fx * run, pose.y + fy * run, pose.z + rise, pose.heading, incline_rad, pose.yaw_offset)


def _sample_curve(
    pose: Pose, curve: Curve, width_m: float, step_deg: float
) -> Iterable[tuple[Pose, float]]:
    """Yields (pose, arc_length_from_segment_start) for every sample AFTER
    the start pose, ending exactly at the segment's end."""
    radius = centerline_radius(curve, width_m)
    total = math.radians(abs(curve.angle_deg))
    sign = 1.0 if curve.direction == "LEFT" else -1.0
    steps = max(1, math.ceil(abs(curve.angle_deg) / step_deg))

    # Center sits `radius` to the left (left turn) or right (right turn).
    lx, ly = left_of(pose.heading)
    cx = pose.x + sign * lx * radius
    cy = pose.y + sign * ly * radius

    for i in range(1, steps + 1):
        phi = total * i / steps
        h = pose.heading + sign * phi
        # Point on the arc is `radius` away from the center, opposite the
        # center-facing side -- i.e. minus the (signed) left vector at h.
        lx_i, ly_i = left_of(h)
        x = cx - sign * lx_i * radius
        y = cy - sign * ly_i * radius
        yield Pose(x, y, pose.z, h, 0.0, pose.yaw_offset), radius * phi


def spiral_center(pose: Pose, spiral: Spiral, width_m: float) -> tuple[float, float]:
    """Plan center of the helix for a spiral starting at `pose`."""
    radius = spiral_plan_radius(spiral, width_m)
    sign = 1.0 if spiral.direction == "LEFT" else -1.0
    lx, ly = left_of(pose.heading)
    return pose.x + sign * lx * radius, pose.y + sign * ly * radius


def _sample_spiral(
    pose: Pose, spiral: Spiral, width_m: float, step_deg: float
) -> Iterable[tuple[Pose, float]]:
    """Like _sample_curve, climbing evenly: arc lengths are the true 3D
    helix lengths so the goods keep their speed."""
    radius = spiral_plan_radius(spiral, width_m)
    total = math.radians(abs(spiral.angle_deg))
    sign = 1.0 if spiral.direction == "LEFT" else -1.0
    steps = max(1, math.ceil(abs(spiral.angle_deg) / step_deg))
    pitch = spiral_pitch(spiral, width_m)
    cx, cy = spiral_center(pose, spiral, width_m)
    for i in range(1, steps + 1):
        phi = total * i / steps
        h = pose.heading + sign * phi
        lx_i, ly_i = left_of(h)
        x = cx - sign * lx_i * radius
        y = cy - sign * ly_i * radius
        z = pose.z + spiral.rise_m * i / steps
        yield Pose(x, y, z, h, pitch, pose.yaw_offset), math.hypot(radius * phi, spiral.rise_m * i / steps)


def _sample_lift(pose: Pose, lift: Module, step_deg: float) -> Iterable[tuple[Pose, float]]:
    """Fork-column lift path (model/lift_parts.py): along the infeed comb
    to the pick leg, straight up (a fork lifts the load off the comb
    rollers), a semicircle of LIFT_R over the top wheel onto the other leg,
    straight down to the outfeed and along again -- on out (Z) or back over
    the entry (C). The corners are sharp, as on the real unit (the load
    stops on the comb and is lifted). Yields (pose, arc from the module's
    start); a corner is a second sample at the same point with the new
    frame; the final pose is level (C: heading + pi)."""
    up = math.pi / 2.0
    y_pick, y_drop = lift_legs(lift.shape)
    z_top = lift.apex_m
    s = 0.0
    p = _advance_straight(pose, y_pick, 0.0)
    s += y_pick
    yield p, s
    p = Pose(p.x, p.y, p.z, p.heading, up, p.yaw_offset)  # the pick corner
    yield p, s
    p = _advance_straight(p, z_top, up)
    s += z_top
    yield p, s
    target = -up if lift.shape != "C" else 3.0 * up  # over the top: on to the far leg (Z) or back to the near one (C)
    for q, ds in _sample_transition(p, target, LIFT_R, step_deg):
        yield q, s + ds
    s += LIFT_R * math.pi
    p = q  # type: ignore[possibly-undefined]
    down = z_top - lift.height_m
    p = _advance_straight(p, down, p.incline)
    s += down
    yield p, s
    if lift.shape == "C":
        p = Pose(p.x, p.y, p.z, p.heading + math.pi, 0.0, p.yaw_offset)  # the drop corner, leaving backwards
        along = y_drop
    else:
        p = Pose(p.x, p.y, p.z, p.heading, 0.0, p.yaw_offset)
        along = LIFT_LEN - y_drop
    yield p, s
    p = _advance_straight(p, along, 0.0)
    s += along
    yield p, s


def _sample_transition(
    pose: Pose, to_incline: float, radius_m: float, step_deg: float
) -> Iterable[tuple[Pose, float]]:
    """Nose-over: a vertical arc of `radius_m` in the plane of travel,
    turning the pitch from pose.incline to `to_incline`. Same construction
    as _sample_curve but in the (along-travel, z) plane: the arc's center
    sits `radius_m` along the current up-normal (nose-up) or down-normal
    (nose-down), and each sample is the center minus that normal at the
    new pitch."""
    dp = to_incline - pose.incline
    steps = max(1, math.ceil(abs(math.degrees(dp)) / step_deg))
    sign = 1.0 if dp > 0 else -1.0
    fx, fy = forward_flat(pose.heading)
    p0 = pose.incline
    # Normal to the direction of travel within the vertical plane, as
    # (along, z) components: n(p) = (-sin p, cos p).
    cu = sign * (-math.sin(p0)) * radius_m
    cz = pose.z + sign * math.cos(p0) * radius_m
    for i in range(1, steps + 1):
        p = p0 + dp * i / steps
        u = cu - sign * (-math.sin(p)) * radius_m
        z = cz - sign * math.cos(p) * radius_m
        yield Pose(pose.x + fx * u, pose.y + fy * u, z, pose.heading, p, pose.yaw_offset), radius_m * abs(dp) * i / steps


def evaluate_chain(
    segments: list[Segment],
    start: Pose,
    width_m: float,
    curve_step_deg: float = CURVE_SAMPLE_STEP_DEG,
    transition_radius_m: float = 0.0,
) -> Spine:
    """Walks the chain from `start`, returning the sampled centerline.

    Straights, inclines and modules contribute their end point only (their
    heading/incline are constant, so linear interpolation between samples
    is exact). Curves are sampled every `curve_step_deg`. The start pose's
    incline is ignored -- a chain always begins level; an Incline segment
    is what tilts it.

    A pitch change between two segments becomes a nose-over arc of
    `transition_radius_m` (sampled like a curve, kind KIND_TRANSITION,
    adding its own length to the chain). With radius 0 it degenerates to a
    hard kink: a zero-length duplicate point carrying the NEW incline, so
    interpolation never smears one segment's pitch into its neighbour. The
    transition is attributed to whichever neighbour is not a module, so a
    module's own footprint stays exactly flat and exactly its own length.
    """
    spine = Spine()
    pose = Pose(start.x, start.y, start.z, start.heading, 0.0, start.yaw_offset)
    spine._append(pose, 0.0, 0, kind_of(segments[0]) if segments else KIND_STRAIGHT)
    s = 0.0

    for i, seg in enumerate(segments):
        target_incline = segment_incline(seg, width_m)
        if isinstance(seg, Spiral) or (isinstance(seg, Module) and seg.kind == "LIFT"):
            target_incline = pose.incline  # bends itself: no nose-over, its stated height is exact
        if target_incline != pose.incline:
            owner = i - 1 if (isinstance(seg, Module) and i > 0) else i
            if transition_radius_m > 0.0:
                for p, ds in _sample_transition(pose, target_incline, transition_radius_m, curve_step_deg):
                    spine._append(p, s + ds, owner, KIND_TRANSITION)
                s += transition_length(pose.incline, target_incline, transition_radius_m)
                pose = p  # type: ignore[possibly-undefined]
            else:
                pose = Pose(pose.x, pose.y, pose.z, pose.heading, target_incline, pose.yaw_offset)
                spine._append(pose, s, i, kind_of(seg))

        if isinstance(seg, Curve):
            for p, ds in _sample_curve(pose, seg, width_m, curve_step_deg):
                spine._append(p, s + ds, i, KIND_CURVE)
            pose = p  # type: ignore[possibly-undefined]
            s += segment_length(seg, width_m)
        elif isinstance(seg, Spiral):
            for p, ds in _sample_spiral(pose, seg, width_m, curve_step_deg):
                spine._append(p, s + ds, i, KIND_SPIRAL)
            s += segment_length(seg, width_m)
            # Leaves level: a zero-length duplicate carrying incline 0 (hard kink).
            pose = Pose(p.x, p.y, p.z, p.heading, 0.0, p.yaw_offset)  # type: ignore[possibly-undefined]
            spine._append(pose, s, i, KIND_SPIRAL)
        elif isinstance(seg, Module) and seg.kind == "LIFT":
            for p, ds in _sample_lift(pose, seg, curve_step_deg):
                spine._append(p, s + ds, i, KIND_LIFT)
            pose = p  # type: ignore[possibly-undefined]
            s += segment_length(seg, width_m)
        elif isinstance(seg, Module) and seg.kind == "RAT" and seg.exit != "STRAIGHT":
            half = seg.length_m / 2.0
            pose = _advance_straight(pose, half, 0.0)
            s += half
            spine._append(pose, s, i, KIND_MODULE)
            turn = math.pi / 2.0 if seg.exit == "LEFT" else -math.pi / 2.0
            # The item keeps its yaw while travel turns: compensate.
            pose = Pose(pose.x, pose.y, pose.z, pose.heading + turn, 0.0, pose.yaw_offset - turn)
            spine._append(pose, s, i, KIND_MODULE)
            pose = _advance_straight(pose, width_m / 2.0, 0.0)
            s += width_m / 2.0
            spine._append(pose, s, i, KIND_MODULE)
        else:
            length = segment_length(seg, width_m)
            pose = _advance_straight(pose, length, target_incline)
            if isinstance(seg, Module) and abs(seg.turn) > 1e-12:
                # The goods rotate over the module (angled-roller / pivot turn): the
                # yaw offset interpolates from the module's start to its end.
                pose = Pose(pose.x, pose.y, pose.z, pose.heading, pose.incline, pose.yaw_offset + seg.turn)
            s += length
            spine._append(pose, s, i, kind_of(seg))

    return spine


def incline_from_rise(rise_m: float, length_m: float) -> float:
    """Pitch in degrees of a straight of slope length `length_m` whose end
    sits `rise_m` above (+) or below (-) its start. Clamped so |rise| never
    exceeds the length (a vertical run is not a conveyor)."""
    if length_m <= 0.0:
        return 0.0
    ratio = max(-1.0, min(1.0, rise_m / length_m))
    return math.degrees(math.asin(ratio))


def rise_from_incline(angle_deg: float, length_m: float) -> float:
    return length_m * math.sin(math.radians(angle_deg))


def pose_at_s(spine: Spine, s_target: float) -> Pose:
    """Pose at arc length `s_target`, linearly interpolated between the
    neighbouring samples (exact on straights, sub-mm on 2-degree arcs).
    Clamped to the spine's ends."""
    n = len(spine)
    if n == 0:
        return Pose(0.0, 0.0, 0.0, 0.0, 0.0)
    if s_target <= spine.s[0]:
        return spine.pose_at(0)
    if s_target >= spine.s[-1]:
        return spine.pose_at(n - 1)
    for i in range(1, n):
        if spine.s[i] >= s_target:
            span = spine.s[i] - spine.s[i - 1]
            if span <= 1e-12:
                return spine.pose_at(i)
            t = (s_target - spine.s[i - 1]) / span

            def lerp(a, b):
                return a + (b - a) * t

            return Pose(
                lerp(spine.x[i - 1], spine.x[i]),
                lerp(spine.y[i - 1], spine.y[i]),
                lerp(spine.z[i - 1], spine.z[i]),
                lerp(spine.heading[i - 1], spine.heading[i]),
                lerp(spine.incline[i - 1], spine.incline[i]),
                spine.yaw_offset[i - 1],
            )
    return spine.pose_at(n - 1)


def segment_frames(
    segments: list[Segment], start: Pose, width_m: float, transition_radius_m: float = 0.0
) -> list[tuple[Pose, Pose]]:
    """(start pose, end pose) of every segment's OWN footprint, i.e.
    excluding the nose-over that may precede it. Drives the elevation
    gizmo and the 'next segment attaches here' readout."""
    spine = evaluate_chain(segments, start, width_m, transition_radius_m=transition_radius_m)
    starts = segment_starts(segments, width_m, transition_radius_m)
    out = []
    for seg, s0 in zip(segments, starts):
        out.append((pose_at_s(spine, s0), pose_at_s(spine, s0 + segment_length(seg, width_m))))
    return out


def end_pose(
    segments: list[Segment], start: Pose, width_m: float, transition_radius_m: float = 0.0
) -> Pose:
    spine = evaluate_chain(segments, start, width_m, transition_radius_m=transition_radius_m)
    return spine.pose_at(len(spine) - 1)


def reanchor_pose(x: float, y: float, z: float, yaw: float, old_end: tuple, new_end: tuple) -> tuple[float, float, float, float]:
    """Where a line's object goes so that the end of its first piece stays
    put in the world after that piece changed: it ended at `old_end` and
    now ends at `new_end` (both local (x, y, z, heading)). World heading =
    yaw + local heading, Blender's Z rotation applied to local x, y.
    Returns (x', y', z', yaw')."""
    ox, oy, oz, oh = old_end
    nx, ny, nz, nh = new_end
    yaw2 = yaw + oh - nh
    c0, s0 = math.cos(yaw), math.sin(yaw)
    c1, s1 = math.cos(yaw2), math.sin(yaw2)
    return (x + (c0 * ox - s0 * oy) - (c1 * nx - s1 * ny),
            y + (s0 * ox + c0 * oy) - (s1 * nx + c1 * ny),
            z + oz - nz, yaw2)


def prepend_pose(x: float, y: float, z: float, yaw: float, ex: float, ey: float, ez: float, eh: float) -> tuple[float, float, float, float]:
    """Where a line's object goes after a piece is put in FRONT of its first
    one so that everything already built stays where it is: the new piece
    runs from the new origin to (ex, ey, ez) with heading eh in the NEW
    local frame, and that end must land on the old origin with the old yaw.
    Returns (x', y', z', yaw')."""
    return reanchor_pose(x, y, z, yaw, (0.0, 0.0, 0.0, 0.0), (ex, ey, ez, eh))


def segment_starts(segments: list[Segment], width_m: float, transition_radius_m: float = 0.0) -> list[float]:
    """Arc length at which each segment's own footprint begins (after any
    nose-over transition that precedes it)."""
    starts = []
    s = 0.0
    incline = 0.0
    for seg in segments:
        target = segment_incline(seg, width_m)
        if isinstance(seg, Spiral) or (isinstance(seg, Module) and seg.kind == "LIFT"):
            target = incline  # bends itself, leaves level
        if target != incline:
            s += transition_length(incline, target, transition_radius_m)
            incline = target
        starts.append(s)
        s += segment_length(seg, width_m)
        if isinstance(seg, Spiral) or (isinstance(seg, Module) and seg.kind == "LIFT"):
            incline = 0.0
    return starts


@dataclass(frozen=True)
class Run:
    """A maximal stretch of the spine that is either one module footprint
    or a chain of non-module segments. The cross-section geometry sweeps
    conveyor runs and skips module runs (the module's own node group
    covers that footprint), so the spine is written as one spline per
    run in addition to the single continuous spline populate reads."""

    first_index: int  # inclusive sample index
    last_index: int  # inclusive sample index
    is_module: bool
    segment_indices: tuple[int, ...]


def runs(spine: Spine, segments: list[Segment]) -> list[Run]:
    if not segments or len(spine) == 0:
        return []
    groups: list[list[int]] = []
    for i, seg in enumerate(segments):
        if isinstance(seg, Module) or not groups or isinstance(segments[groups[-1][-1]], Module):
            groups.append([i])
        else:
            groups[-1].append(i)

    last_of_segment: dict[int, int] = {}
    for idx, seg_i in enumerate(spine.segment_index):
        last_of_segment[seg_i] = idx

    out: list[Run] = []
    prev_end = 0
    for g in groups:
        end = last_of_segment.get(g[-1], prev_end)
        out.append(Run(prev_end, end, isinstance(segments[g[0]], Module), tuple(g)))
        prev_end = end
    return out


def insert_sample_at(spine: Spine, s_target: float) -> None:
    """Inserts a sample at arc length `s_target` (no-op if one already
    exists within 1e-6 or the target is outside the spine). Linear
    interpolation between the neighbouring samples is exact on straights
    and inclines and sub-millimeter on 2-degree-sampled arcs. Used to put
    exact points at guide-rail gap boundaries so the `guide_gap` attribute
    never smears across a long straight."""
    n = len(spine)
    if n == 0 or s_target < spine.s[0] or s_target > spine.s[-1]:
        return
    for i in range(1, n):
        if abs(spine.s[i] - s_target) < 1e-6 or abs(spine.s[i - 1] - s_target) < 1e-6:
            return
        if spine.s[i - 1] < s_target < spine.s[i]:
            t = (s_target - spine.s[i - 1]) / (spine.s[i] - spine.s[i - 1])

            def lerp(a, b):
                return a + (b - a) * t

            spine.x.insert(i, lerp(spine.x[i - 1], spine.x[i]))
            spine.y.insert(i, lerp(spine.y[i - 1], spine.y[i]))
            spine.z.insert(i, lerp(spine.z[i - 1], spine.z[i]))
            spine.heading.insert(i, lerp(spine.heading[i - 1], spine.heading[i]))
            spine.incline.insert(i, lerp(spine.incline[i - 1], spine.incline[i]))
            spine.yaw_offset.insert(i, lerp(spine.yaw_offset[i - 1], spine.yaw_offset[i]))  # goods turning over an angled-roller / pivot module keep turning
            spine.s.insert(i, s_target)
            spine.segment_index.insert(i, spine.segment_index[i])
            spine.kind.insert(i, spine.kind[i])
            return
