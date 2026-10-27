"""The physical parts of transfer sections -- merge / divert junctions and
right-angle transfers (RATs) -- pure Python, no bpy.

Everything is in the MODULE's local frame: x = right of the main line's
travel, y = along it from the module's start, z = up from the conveying
surface (roller tops). operators/build_line.py moves the parts into the
line's space and model/spine.py writes them as extra splines; the node
trees only sweep / instance them (geonodes/cross_sections/common.
build_parts). Keeping the layout here keeps it exact and testable.

How the real units are built (manufacturer data: Interroll RM 8731 belt
transfer, RM 8330 / 8230 angled merges, RM 8711 HPD; Itoh Denki F-RAT-NX75
and POP-UP; Hytrol E24; Intralox angled-roller belt):
  - the main line is left alone: its rollers run straight through every
    junction, square to it, and its frame is continuous;
  - a pop-up belt transfer is 2-5 vertical "blades" standing in widened
    roller gaps, parallel to the rollers and nearly as long, each with a
    ~16 mm belt along its top edge; drive and lift sit in a box bolted
    under the side frames. The bed is re-spaced locally: the rollers either
    side of a blade move up against it, the others keep the line's pitch;
  - pop-up wheels: a row of small wheels in EVERY gap of an opened-up bed
    (90 degrees), or angled wheels set in flat cover plates between the
    rollers (angled transfers);
  - a high-performance divert (HPD) is a few 120 mm cassettes in place of
    main-line rollers, each a top plate with two rows of round pockets on a
    60 mm grid and a short roller in each pocket, swivelled to the angle;
  - an angled merge is the END of the feeder: its rollers stay square to
    its travel and get shorter one by one (stepping along the main line's
    frame), a sheet-metal dead plate covers the stepped ends and fills the
    sharp tip, and its long-side guide bends into the main line's guide;
  - a RAT at a corner is a transfer bed with the belts running toward the
    exit, an end stop across the far end and guard rails on the closed
    sides.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# Part kinds (the spine role each one is written with lives in model/spine.py).
ROLLER, BELT, CHAIN, WHEEL, BOX, RAIL, FENCE = "ROLLER", "BELT", "CHAIN", "WHEEL", "BOX", "RAIL", "FENCE"
PLATE = "PLATE"  # flat sheet-metal plate: a closed level polygon at its underside
# Material slot of a part. Rollers always take the Rollers slot, belts the
# Belt slot, chains the Links slot, rails the Frame slot; wheels and boxes
# take the one named here (build_parts).
MAT_FRAME, MAT_ROLLER, MAT_BELT, MAT_ACCENT, MAT_LINKS = 0, 1, 2, 3, 4

# Transfer belt and blade. Interroll runs 16 mm belts on 24 mm blades 4 mm
# under the rollers; drawn so, a RAT read as plain rollers at any distance.
# Robotunits-size 24 mm belts on blades that fill their slot,
# 1 mm under the roller line, read as black strands across the bed.
BELT_W, BELT_T = 0.024, 0.006
BLADE_W, BLADE_H = 0.030, 0.065  # the vertical plate ("blade") a transfer belt runs on
BLADE_SPACING = 0.18  # blade centres: three on a ~0.5 m transfer
PULLEY_R = 0.013  # belt end pulleys
CHAIN_W, CHAIN_T = 0.03, 0.02
WHEEL_R, WHEEL_W = 0.02, 0.016  # pop-up wheels: 40 mm polyurethane
WHEEL_PITCH = 0.075  # across a 90 degree wheel transfer (Itoh F-RAT-NX75)
WHEEL_PITCH_ANGLED = 0.12  # angled wheels set in cover plates (Itoh POP-UP)
WHEEL_RISE = 0.003  # popped-up wheel tops above the roller tops
# Pop-up strokes (lowered -> raised). Moving parts are laid out LOWERED and
# carry `lift`; the node tree raises them while goods cross the transfer
# (geonodes/cross_sections/common.build_parts, operators/stream.py).
# Belts rest just under the roller line, visible in their slots (4 mm down they
# vanished between 48 mm rollers: a standalone RAT read as plain rollers),
# and still rise 12 mm over the rollers (Interroll: 12 mm).
BELT_REST_TOP, BELT_LIFT = -0.001, 0.013
CHAIN_REST_TOP, CHAIN_LIFT = -0.005, 0.03  # pallet chains lift up to 30 mm
WHEEL_LIFT = 0.006  # wheels 3 mm under -> 3 mm over the rollers
HPD_CASSETTE, HPD_GRID = 0.12, 0.06  # Interroll HPD: 120 mm cassettes, pockets on a 60 mm grid
HPD_POCKET_R, HPD_ROLLER_R, HPD_ROLLER_L = 0.021, 0.012, 0.03
PLATE_T = 0.003  # sheet-metal dead / cover plates
PLATE_TOP = 0.002  # dead plate top above the roller tops (over the roller ends)
END_MARGIN = 0.012  # roller ends clear of the frame
CLEAR = 0.004  # roller to blade / plate / frame
MIN_ROLLER = 0.06  # a shorter wedge roller is left out (the dead plate covers the tip)


@dataclass
class Part:
    kind: str
    points: list  # [(x, y, z), ...]: an axis (rollers, wheels), a centreline (belts, boxes), a polyline (rails, fences) or an outline (plates)
    r: float = 0.0  # radius (rollers, wheels) or width (boxes)
    h: float = 0.0  # height (boxes)
    mat: int = MAT_FRAME
    lift: float = 0.0  # moving part of a pop-up transfer: how far it rises when the transfer works (laid out lowered)
    tr: int = 0  # the transfer it belongs to (operators/build_line.transfer_id); the tree lifts it in step with the goods


@dataclass
class Frame:
    """Frame / roller figures of the line the section sits in (Blender units)."""
    width: float  # between the frame rails (the conveying width)
    roller_r: float
    pitch: float  # the line's roller pitch
    rail_t: float = 0.02
    rail_h: float = 0.10
    rail_drop: float = 0.015  # rail top below the roller tops
    fence_offset: float = field(default=0.0)  # rail centre from the centreline

    def __post_init__(self):
        if self.fence_offset <= 0.0:
            self.fence_offset = self.width / 2.0 + self.rail_t / 2.0

    @property
    def rail_z(self) -> float:
        return -(self.rail_drop + self.rail_h / 2.0)

    @property
    def frame_bottom(self) -> float:
        return -(self.rail_drop + self.rail_h)

    def transfer_pitch(self, insert_w: float) -> float:
        """Roller pitch of a bed opened up for a row of wheels in every gap."""
        return max(self.pitch, 2.0 * self.roller_r + insert_w + 0.012)


FENCE_TOP = 0.18  # guide rail top above the rollers (Guide Rail Rise + Height)
POST = 0.03  # square fence post


def fence_posts(points: list, f: Frame, spacing: float = 1.0) -> list[Part]:
    """Posts carrying a part-built fence (RAT guards, end stops, merge
    tapers) down to the frame: one near each end and about every `spacing`
    in between. (Without them the short guards read as loose tubes.)"""
    if len(points) < 2:
        return []
    segs = []
    total = 0.0
    for a, b in zip(points, points[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        segs.append((a, b, d, total))
        total += d
    if total < 0.02:
        return []
    inset = min(0.04, total / 2.0)
    n = max(1, int(round((total - 2.0 * inset) / spacing)))
    stations = [inset + k * (total - 2.0 * inset) / n for k in range(n + 1)] if total > 2.0 * inset else [total / 2.0]
    top, bottom = FENCE_TOP, -f.rail_drop
    parts = []
    for s in stations:
        for a, b, d, s0 in segs:
            if s <= s0 + d + 1e-9 and d > 1e-9:
                t = (s - s0) / d
                x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
                ux, uy = (b[0] - a[0]) / d, (b[1] - a[1]) / d
                zc = (top + bottom) / 2.0
                parts.append(Part(BOX, [(x - ux * POST / 2.0, y - uy * POST / 2.0, zc), (x + ux * POST / 2.0, y + uy * POST / 2.0, zc)],
                                  r=POST, h=top - bottom, mat=MAT_FRAME))
                break
    return parts


def _unit(v) -> tuple[float, float]:
    n = math.hypot(v[0], v[1]) or 1.0
    return v[0] / n, v[1] / n


# ---------------------------------------------------------------- the bed

def _interior_stations(length: float, pitch: float) -> list[float]:
    """Roller positions strictly inside [0, length]: the neighbouring runs
    already put a roller on each boundary."""
    n = max(1, int(round(length / pitch)))
    step = length / n
    return [k * step for k in range(1, n)]


def _fill(a: float, b: float, pitch: float, gap_min: float) -> list[float]:
    """Stations strictly between rollers at a and b, evenly spaced at about
    `pitch` and never closer than `gap_min`."""
    span = b - a
    n = max(1, int(round(span / pitch)))
    while n > 1 and span / n < gap_min - 1e-9:
        n -= 1
    return [a + k * span / n for k in range(1, n)]


def slotted_bed(length: float, f: Frame, slots: list) -> list[float]:
    """Roller stations inside [0, length] at about the line's pitch, leaving
    each slot (y0, y1) -- a blade, a chain strand, a row of cassettes --
    free: the rollers either side move up against it and the others are
    spread evenly in between, the way transfer beds are re-spaced locally.
    Slots must stay a roller's radius clear of both ends."""
    r = f.roller_r
    gap_min = 2.0 * r + CLEAR
    ys: list[float] = []
    cursor = 0.0
    for a, b in sorted(slots):
        lo, hi = a - r - CLEAR, b + r + CLEAR
        if lo - cursor >= gap_min:
            ys += _fill(cursor, lo, f.pitch, gap_min)
            ys.append(lo)
        if length - hi >= gap_min:
            ys.append(hi)
            cursor = hi
        else:
            cursor = length  # the next run's first roller flanks it
    if length - cursor >= gap_min:
        ys += _fill(cursor, length, f.pitch, gap_min)
    return ys


def _roller(x0: float, x1: float, y: float, f: Frame, yaw: float = 0.0) -> Part:
    """A roller across the bed at y (axis along x), yawed about its centre."""
    cx, half = (x0 + x1) / 2.0, (x1 - x0) / 2.0
    dx, dy = half * math.cos(yaw), half * math.sin(yaw)
    return Part(ROLLER, [(cx - dx, y - dy, -f.roller_r), (cx + dx, y + dy, -f.roller_r)], r=f.roller_r, mat=MAT_ROLLER)


def bed_rollers(ys: list[float], f: Frame) -> list[Part]:
    """The main line's rollers, square across the bed at the stations `ys`."""
    half = f.width / 2.0 - END_MARGIN
    return [_roller(-half, half, y, f) for y in ys]


def _gap_pairs(ys: list[float], y0: float, y1: float) -> list[tuple[float, float]]:
    """Consecutive rollers whose gap centre lies inside [y0, y1]."""
    return [(a, b) for a, b in zip(ys, ys[1:]) if y0 <= (a + b) / 2.0 <= y1]


STAND_CLEAR = 0.045  # floor stands carry the frame on a ~40 mm cross member right under it
HANGER_T = 0.008


def _drive_box(y0: float, y1: float, f: Frame, length_max: float = 0.46, across: float | None = None,
               depth: float = 0.125, motor: bool = True) -> list[Part]:
    """Drive / lift box under a transfer. Only the high-performance divert's
    cassette body uses it now: under the pop-up belts, chains and wheels of
    RATs and junctions the box (with its hangers and motor) read as "ugly
    blocks" from below (user, 2026-10-10) and is gone -- those units are a
    frame with the mechanism inside it. (Interroll RM 8731: 462 mm long,
    ~127 mm deep, a deeper motor section to one side), Links colour. The
    real box is bolted under both side frames; here it hangs from them on
    two end plates, inside the floor stands' posts and below the cross
    member they carry the frame on, so a stand that happens to fall under
    the transfer never runs through it."""
    top = f.frame_bottom - STAND_CLEAR
    yc = (y0 + y1) / 2.0
    length = min(length_max, max(y1 - y0, 0.2))
    across = min(f.width - 0.04 if across is None else across, f.width - 0.04)
    zc = top - depth / 2.0
    parts = [Part(BOX, [(0.0, yc - length / 2.0, zc), (0.0, yc + length / 2.0, zc)], r=across, h=depth, mat=MAT_LINKS)]
    hz = f.frame_bottom - STAND_CLEAR / 2.0
    for y in (yc - length / 2.0 + HANGER_T, yc + length / 2.0 - HANGER_T):
        parts.append(Part(BOX, [(-across / 2.0, y, hz), (across / 2.0, y, hz)], r=HANGER_T, h=STAND_CLEAR, mat=MAT_LINKS))
    if motor:
        mw = 0.35 * across
        mx = across / 2.0 - mw / 2.0
        parts.append(Part(BOX, [(mx, yc - 0.3 * length, top - depth - 0.03), (mx, yc + 0.3 * length, top - depth - 0.03)],
                          r=mw, h=0.06, mat=MAT_LINKS))
    return parts


# ---------------------------------------------------- pop-up belts / chains

def blade_bed(y0: float, y1: float, f: Frame, length: float) -> tuple[list[float], list[float]]:
    """(blade centres, roller stations) of a pop-up belt transfer bed
    `length` long whose blades spread over [y0, y1] (2-5 blades on real
    units, three in most layouts, about BLADE_SPACING apart). The rollers
    flanking a blade stand right against it; every other gap of the bed is
    the same: the line's pitch, stretched a little so the section's length
    comes out whole (real units re-space the rollers over the unit like
    this). The rollers on 0 and `length` belong to the next runs."""
    r = f.roller_r
    flank = BLADE_W / 2.0 + r + CLEAR  # blade centre to a flanking roller
    gap_min = 2.0 * r + CLEAR
    pitch = max(f.pitch, gap_min)
    m = max(1, int(round((BLADE_SPACING - 2.0 * flank) / pitch)))  # plain gaps between two blades
    zone = max(y1 - y0, 0.0)
    n = max(1, min(5, int(zone / (2.0 * flank + m * pitch)) + 1))
    while n > 0:
        free = length - n * 2.0 * flank
        n_plain = min(int(round(free / pitch)), int(free / gap_min + 1e-9)) if free > 0.0 else -1
        if n_plain >= m * (n - 1) and (n_plain > 0 or free < 1e-9):
            break
        n -= 1
    if n == 0:
        return [], _interior_stations(length, pitch)
    step = free / n_plain if n_plain else 0.0
    spare = n_plain - m * (n - 1)  # plain gaps before + after the blades
    group = n * 2.0 * flank + m * (n - 1) * step
    before = int(round(((y0 + y1) / 2.0 - group / 2.0) / step)) if step else 0
    before = min(max(before, 0), spare)
    gaps = [(step, False)] * before
    for k in range(n):
        gaps.append((2.0 * flank, True))
        if k < n - 1:
            gaps += [(step, False)] * m
    gaps += [(step, False)] * (spare - before)
    ys, blades, y = [], [], 0.0
    for gap, is_blade in gaps:
        if is_blade:
            blades.append(y + gap / 2.0)
        y += gap
        ys.append(y)
    return blades, ys[:-1]  # the last station is `length`


def popup_belts(blade_ys: list[float], f: Frame) -> list[Part]:
    """Pop-up belt transfer (Interroll RM 8731, Hytrol E24, Robotunits): a
    galvanized blade (carrier) filling each slot, parallel to the rollers
    and nearly as long, with a black belt along its top edge that turns
    down round an end pulley at each end. Laid out LOWERED (belt tops just
    under the roller line: a light slot floor with a black belt line
    between the rollers at rest); blade, belt and pulleys rise BELT_LIFT
    together while goods are carried across."""
    parts = []
    reach = f.width / 2.0 - 0.02  # end pulley centres
    top = BELT_REST_TOP
    zb = top - BELT_T - BLADE_H / 2.0
    for y in blade_ys:
        # A galvanized carrier (the frame colour) under the black belt: the
        # slot floor is light, the belt a black line across it -- the
        # Interroll look. (Black on
        # black over a dark floor read as plain roller gaps.)
        parts.append(Part(BOX, [(-reach, y, zb), (reach, y, zb)], r=BLADE_W, h=BLADE_H, mat=MAT_FRAME, lift=BELT_LIFT))
        parts.append(Part(BELT, [(-reach, y, top - BELT_T / 2.0), (reach, y, top - BELT_T / 2.0)], r=BELT_W, h=BELT_T, mat=MAT_BELT,
                          lift=BELT_LIFT))
        for sx in (-1.0, 1.0):
            parts.append(Part(WHEEL, [(sx * reach, y - BELT_W / 2.0, top - PULLEY_R), (sx * reach, y + BELT_W / 2.0, top - PULLEY_R)],
                              r=PULLEY_R, mat=MAT_BELT, lift=BELT_LIFT))
    return parts


def chain_positions(y0: float, y1: float) -> list[float]:
    """Two strands (three past 0.9 m) spread over [y0, y1]."""
    zone = max(y1 - y0, 0.0)
    n = 3 if zone > 0.9 else 2
    a, b = y0 + 0.2 * zone, y1 - 0.2 * zone
    return [a + k * (b - a) / (n - 1) for k in range(n)]


def popup_chains(chain_ys: list[float], f: Frame) -> list[Part]:
    """Pop-up chain transfer (pallets and heavy loads; Interroll PM 9730):
    strands of duplex chain across the bed in widened roller gaps, each
    round a sprocket at both ends, a jack shaft under the bed joining them
    and a gear motor hung outside the frame."""
    parts = []
    reach = f.width / 2.0 - 0.03
    sprocket = 0.033
    top = CHAIN_REST_TOP
    for y in chain_ys:
        parts.append(Part(CHAIN, [(-reach, y, top - CHAIN_T / 2.0), (reach, y, top - CHAIN_T / 2.0)], r=CHAIN_W, h=CHAIN_T, mat=MAT_LINKS,
                          lift=CHAIN_LIFT))
        for sx in (-1.0, 1.0):
            parts.append(Part(WHEEL, [(sx * reach, y - 0.012, top - sprocket), (sx * reach, y + 0.012, top - sprocket)],
                              r=sprocket, mat=MAT_LINKS, lift=CHAIN_LIFT))
    if len(chain_ys) > 1:
        shaft_z = -(2.0 * f.roller_r + 0.014)  # under the rollers
        y_a, y_b = min(chain_ys), max(chain_ys)
        parts.append(Part(WHEEL, [(reach, y_a, shaft_z), (reach, y_b, shaft_z)], r=0.012, mat=MAT_LINKS))
        # Lift frame between the strands and the gear motor under the bed
        # (hung outside the frame it ran into the floor stands).
        yc = (y_a + y_b) / 2.0
        z_motor = f.frame_bottom - STAND_CLEAR - 0.08 - 0.06
        parts.append(Part(BOX, [(0.1 * f.width, yc - 0.1, z_motor), (0.1 * f.width, yc + 0.1, z_motor)], r=0.14, h=0.12, mat=MAT_ACCENT))
    return parts


# ----------------------------------------------------------- pop-up wheels

def _wheel(x: float, y: float, z: float, axle: tuple[float, float], r: float = WHEEL_R, w: float = WHEEL_W,
           mat: int = MAT_BELT) -> Part:
    ax, ay = axle
    return Part(WHEEL, [(x - ax * w / 2.0, y - ay * w / 2.0, z), (x + ax * w / 2.0, y + ay * w / 2.0, z)], r=r, mat=mat)


def _row_xs(half: float, pitch: float, stagger: bool = False) -> list[float]:
    """Positions across the bed within +-half, `pitch` apart, centred;
    staggered rows sit half a pitch over (one fewer)."""
    n = max(1, int(2.0 * half / pitch) + 1)
    xs = [(i - (n - 1) / 2.0) * pitch for i in range(n)]
    if stagger and n > 1:
        xs = [x + pitch / 2.0 for x in xs[:-1]]
    return xs


def popup_wheels(ys: list[float], y0: float, y1: float, f: Frame, direction: tuple[float, float] = (1.0, 0.0)) -> list[Part]:
    """Pop-up wheel transfer at 90 degrees (Itoh F-RAT-NX75): a row of black
    wheels in EVERY gap inside [y0, y1] of the opened-up bed `ys` (the
    section's roller stations including both ends), alternate rows
    staggered, each row on a carriage bar; laid out lowered (wheel tops 3 mm
    under the rollers), wheels and bars rise WHEEL_LIFT while goods are
    carried across; the wheels roll along `direction`."""
    dx, dy = _unit(direction)
    axle = (-dy, dx)
    half = f.width / 2.0 - 0.04
    rest = WHEEL_RISE - WHEEL_LIFT - WHEEL_R
    parts = []
    for row, (a, b) in enumerate(_gap_pairs(ys, y0, y1)):
        y = (a + b) / 2.0
        for x in _row_xs(half, WHEEL_PITCH, row % 2 == 1):
            wheel = _wheel(x, y, rest, axle)
            wheel.lift = WHEEL_LIFT
            parts.append(wheel)
        parts.append(Part(BOX, [(-half - 0.01, y, -0.05 - WHEEL_LIFT), (half + 0.01, y, -0.05 - WHEEL_LIFT)], r=0.014, h=0.02,
                          mat=MAT_LINKS, lift=WHEEL_LIFT))
    return parts


def popup_wheels_plated(ys: list[float], y0: float, y1: float, f: Frame, direction: tuple[float, float]) -> list[Part]:
    """Angled pop-up wheel transfer (Itoh POP-UP, Fortna IntelliROL): a flat
    cover plate in every gap of the opened-up bed `ys` (the section's roller
    stations including both ends), just under the roller tops, and in the
    gaps inside [y0, y1] a row of wheels turned to roll along `direction`
    rising 3 mm through the plate."""
    dx, dy = _unit(direction)
    axle = (-dy, dx)
    half = f.width / 2.0 - 0.05
    edge = f.width / 2.0 - 0.006
    parts = []
    row = 0
    for a, b in zip(ys, ys[1:]):
        y = (a + b) / 2.0
        w = (b - a) - 2.0 * f.roller_r - 0.006
        if w < 0.02:
            continue
        zp = -0.001 - PLATE_T / 2.0
        parts.append(Part(BOX, [(-edge, y, zp), (edge, y, zp)], r=w, h=PLATE_T, mat=MAT_FRAME))
        if y0 <= y <= y1:
            parts += [_wheel(x, y, WHEEL_RISE - WHEEL_R, axle) for x in _row_xs(half, WHEEL_PITCH_ANGLED, row % 2 == 1)]
            row += 1
    return parts


# --------------------------------------------------- high-performance divert

def _swivel_roller(x: float, y: float, top: float, axle: tuple[float, float]) -> Part:
    ax, ay = axle
    h = HPD_ROLLER_L / 2.0
    z = top - HPD_ROLLER_R
    return Part(ROLLER, [(x - ax * h, y - ay * h, z), (x + ax * h, y + ay * h, z)], r=HPD_ROLLER_R, mat=MAT_ROLLER)


def hpd_cassettes(c0: float, n: int, f: Frame, direction: tuple[float, float]) -> list[Part]:
    """High-performance divert (Interroll HPD, RM 8711): `n` cassettes of
    120 mm laid from c0 along the main line in place of its rollers. Each is
    a top plate with two rows of round pockets on a 60 mm grid and a short
    roller in every pocket, all swivelled to roll along `direction`; the
    drive box hangs under the bed."""
    dx, dy = _unit(direction)
    axle = (-dy, dx)
    edge = f.width / 2.0 - 0.004
    xs = _row_xs(f.width / 2.0 - HPD_GRID / 2.0 - 0.006, HPD_GRID)
    top = 0.0005  # plate top, just over the roller tops
    parts = []
    for k in range(n):
        ya = c0 + k * HPD_CASSETTE
        yc = ya + HPD_CASSETTE / 2.0
        parts.append(Part(BOX, [(-edge, yc, top - 0.002), (edge, yc, top - 0.002)], r=HPD_CASSETTE - 0.003, h=0.004, mat=MAT_FRAME))
        for y in (ya + HPD_GRID / 2.0, ya + 1.5 * HPD_GRID):
            for x in xs:
                parts.append(Part(WHEEL, [(x, y, top - 0.0015), (x, y, top + 0.0005)], r=HPD_POCKET_R, mat=MAT_BELT))  # the pocket
                parts.append(_swivel_roller(x, y, top + 0.0015, axle))
    span = n * HPD_CASSETTE
    parts += _drive_box(c0, c0 + span, f, length_max=span, across=min(0.7 * f.width, 0.45), depth=0.2)
    return parts


# ------------------------------------------------------ angled feeder ends

def _travel(geom, side: int) -> tuple[float, float]:
    """The feeder's travel in the (unmirrored) module frame: square to its
    end face, into the main line."""
    s = 1.0 if side >= 0 else -1.0
    p1, p2 = geom.outline[2], geom.outline[3]
    ux, uy = _unit((p2[0] - p1[0], p2[1] - p1[1]))
    return -s * uy, s * ux


def _clip_spans(p0, d, poly) -> list[tuple[float, int, float, int]]:
    """Stretches of the line p0 + t d inside the closed polygon: (t_in,
    edge index crossed there, t_out, edge index)."""
    hits = []
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        denom = d[0] * ey - d[1] * ex
        if abs(denom) < 1e-12:
            continue
        rx, ry = ax - p0[0], ay - p0[1]
        t = (rx * ey - ry * ex) / denom
        u = (rx * d[1] - ry * d[0]) / denom
        if -1e-9 <= u < 1.0 - 1e-9:
            hits.append((t, i))
    hits.sort()
    return [(hits[k][0], hits[k][1], hits[k + 1][0], hits[k + 1][1]) for k in range(0, len(hits) - 1, 2)]


def _clip_line_polygon(p0, d, poly) -> list[tuple[float, float]]:
    """Intervals [t0, t1] of the line p0 + t d inside the (closed) polygon."""
    return [(t0, t1) for t0, _i0, t1, _i1 in _clip_spans(p0, d, poly)]


def _end_clearance(d, poly, i: int, margin: float, r: float) -> float:
    """How far to pull the end of a roller (axis d, radius r) back from the
    polygon edge `i` it crosses so its whole end cap stays `margin` inside."""
    ax, ay = poly[i]
    bx, by = poly[(i + 1) % len(poly)]
    ex, ey = _unit((bx - ax, by - ay))
    mx, my = -ey, ex  # edge normal
    along = abs(d[0] * mx + d[1] * my)
    across = abs(-d[1] * mx + d[0] * my)
    return (margin + r * across) / max(along, 0.2)


def _wedge(geom, side: int, f: Frame):
    """The feeder's angled end on one side: (polygon, per-edge frame
    clearance, face start p1, roller direction u, step direction n), or None
    for a square (90 degree) dock."""
    poly = list(geom.outline[2:-3])  # p1, p2, taper arc..., (edge, y_landing); closes along the main line's frame
    if len(poly) < 3 or not geom.fence:
        return None
    p1, p2 = poly[0], poly[1]
    u = _unit((p2[0] - p1[0], p2[1] - p1[1]))
    # Edge 0 is the face; the last edge runs along the main line's frame, with
    # the angled end's own side frame against it; the others follow the
    # taper's frame rail (centred on the fence line).
    margins = [0.0] + [f.rail_t / 2.0 + CLEAR] * (len(poly) - 2) + [f.rail_t + CLEAR]
    return poly, margins, p1, u, _travel(geom, side)


def _wedge_bed(geom, side: int, f: Frame) -> tuple[list[Part], float | None]:
    """(rollers, distance of the last roller row from the face)."""
    w = _wedge(geom, side, f)
    if w is None:
        return [], None
    poly, margins, p1, (ux, uy), (nx, ny) = w
    r = f.roller_r
    pitch = max(f.pitch, 2.0 * r + CLEAR)
    parts = []
    last = None
    for k in range(400):
        dist = (k + 0.5) * pitch
        cx, cy = p1[0] + nx * dist, p1[1] + ny * dist
        spans = _clip_spans((cx, cy), (ux, uy), poly)
        if not spans:
            if k > 0:
                break
            continue
        for t0, i0, t1, i1 in spans:
            a = t0 + _end_clearance((ux, uy), poly, i0, margins[i0], r)
            b = t1 - _end_clearance((ux, uy), poly, i1, margins[i1], r)
            if b - a < MIN_ROLLER:
                continue
            parts.append(Part(ROLLER, [(cx + ux * a, cy + uy * a, -r), (cx + ux * b, cy + uy * b, -r)], r=r, mat=MAT_ROLLER))
            last = dist
    return parts, last


def wedge_rollers(geom, side: int, f: Frame) -> list[Part]:
    """Rollers of the feeder's angled end on one side: square to its travel
    (parallel to the face), each clipped to the wedge so its end caps clear
    the main line's frame and the taper's frame -- shorter row by row toward
    the tip (unmirrored junction frame)."""
    return _wedge_bed(geom, side, f)[0]


def _clip_half_plane(poly: list, a: float, b: float, c: float) -> list:
    """Sutherland-Hodgman: the part of the polygon where a x + b y <= c."""
    out = []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        fp, fq = a * p[0] + b * p[1] - c, a * q[0] + b * q[1] - c
        if fp <= 0.0:
            out.append(p)
        if (fp < 0.0 < fq) or (fq < 0.0 < fp):
            t = fp / (fp - fq)
            out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
    return out


def _tidy(poly: list, eps: float = 1e-6) -> list:
    """Drops repeated points (consecutive and the closing one)."""
    out = []
    for p in poly:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > eps:
            out.append(p)
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= eps:
        out.pop()
    return out


def polygon_area(poly: list) -> float:
    """Signed area (counter-clockwise positive)."""
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))


def wedge_plates(geom, side: int, f: Frame) -> list[Part]:
    """Sheet-metal dead plate of the feeder's angled end (Interroll RM
    8330): a band along the main line's frame over the angled end's side
    frame and the stepped roller ends, and the triangle that fills the sharp
    tip past the last roller. Two level polygons (the band, and the tip
    outside the band) meeting edge to edge, their undersides PLATE_T below
    PLATE_TOP."""
    w = _wedge(geom, side, f)
    if w is None:
        return []
    poly, _margins, p1, (_ux, uy), (nx, ny) = w
    _rollers, last = _wedge_bed(geom, side, f)
    r = f.roller_r
    s = 1.0 if side >= 0 else -1.0
    edge = abs(p1[0])
    # The band covers the side frame and half a roller cap past the axis ends.
    band = f.rail_t + CLEAR + r * abs(uy) + 0.008
    tip = (last + r + CLEAR) if last is not None else 0.0
    tip_side = _clip_half_plane(poly, -nx, -ny, -(tip + nx * p1[0] + ny * p1[1]))  # (q - p1) . n >= tip
    pieces = [_clip_half_plane(poly, s, 0.0, edge + band), _clip_half_plane(tip_side, -s, 0.0, -(edge + band))]
    z = PLATE_TOP - PLATE_T
    out = []
    for piece in pieces:
        piece = _tidy(piece)
        if len(piece) >= 3 and abs(polygon_area(piece)) > 1e-5:
            out.append(Part(PLATE, [(x, y, z) for x, y in piece], mat=MAT_FRAME))
    return out


def wedge_frame(geom, f: Frame) -> list[Part]:
    """Frame of the feeder's angled end: a rail under the taper fence (its
    long side, bending onto the main line) and the angled end's side frame
    against the main line's frame."""
    if not geom.fence:
        return []
    parts = [Part(RAIL, [(x, y, f.rail_z) for x, y, _h in geom.fence], r=f.rail_t, h=f.rail_h, mat=MAT_FRAME)]
    p1 = geom.outline[2]
    s = 1.0 if p1[0] >= 0.0 else -1.0
    x = p1[0] + s * f.rail_t / 2.0
    if geom.y_landing - p1[1] > 0.05:
        parts.append(Part(RAIL, [(x, p1[1], f.rail_z), (x, geom.y_landing, f.rail_z)], r=f.rail_t, h=f.rail_h, mat=MAT_FRAME))
    return parts


# -------------------------------------------- angled-roller belts and pushers

ARB_R, ARB_LEN, ARB_ROW, ARB_COL = 0.011, 0.028, 0.05, 0.05  # angled-roller belt: small angled rollers on a 50 mm grid


def arb_rollers(outline: list, length: float, direction: tuple[float, float], f: Frame) -> list[Part]:
    """Angled-roller belt: rows of small free rollers embedded
    in the belt on a 50 mm grid, all turned to drive the goods along
    `direction`, their tops just proud of the belt; clipped to the
    junction's `outline` (main bed + wedge, unmirrored). The belt plate
    itself is laid by the tree over the outline."""
    poly = list(outline[:-1]) if outline[0] == outline[-1] else list(outline)
    dx, dy = _unit(direction)
    ax, ay = -dy, dx  # axle perpendicular to the rolling direction
    parts = []
    zc = 0.004 - ARB_R
    y = ARB_ROW / 2.0
    while y < length - ARB_ROW / 4.0:
        for t0, t1 in _clip_line_polygon((0.0, y), (1.0, 0.0), poly):
            t0, t1 = t0 + 0.03, t1 - 0.03
            if t1 - t0 < 0.01:
                continue
            n = max(1, int((t1 - t0) // ARB_COL) + 1)
            for k in range(n):
                x = t0 + (k * (t1 - t0) / (n - 1) if n > 1 else (t1 - t0) / 2.0)
                parts.append(Part(WHEEL, [(x - ax * ARB_LEN / 2.0, y - ay * ARB_LEN / 2.0, zc), (x + ax * ARB_LEN / 2.0, y + ay * ARB_LEN / 2.0, zc)],
                                  r=ARB_R, mat=MAT_LINKS))
        y += ARB_ROW
    return parts


def pusher_parts(length: float, face_side: int, f: Frame) -> list[Part]:
    """Pusher divert: a pneumatic / electric pusher unit on a bracket beside
    the frame on the side AWAY from the branch, in line with its centre, the
    paddle resting against that side's guide line 6 mm over the rollers,
    ready to push the load across (unmirrored frame)."""
    s = 1.0 if face_side >= 0 else -1.0
    far = -s  # the pusher side
    yc = length / 2.0
    edge = f.width / 2.0 + f.rail_t
    body_x = far * (edge + 0.17)
    paddle_h = 0.15
    parts = [
        Part(BOX, [(body_x, yc - 0.16, 0.02), (body_x, yc + 0.16, 0.02)], r=0.22, h=0.18, mat=MAT_ACCENT),  # cylinder / drive housing
        Part(BOX, [(far * (edge + 0.03), yc - 0.14, -0.1), (far * (edge + 0.03), yc + 0.14, -0.1)], r=0.06, h=0.02, mat=MAT_FRAME),  # mounting bracket
        Part(BOX, [(far * (edge + 0.04), yc - 0.12, -0.05), (far * (edge + 0.04), yc + 0.12, -0.05)], r=0.02, h=0.12, mat=MAT_FRAME),
        Part(BOX, [(far * (f.width / 2.0 - 0.02), yc, 0.09), (far * (edge + 0.06), yc, 0.09)], r=0.04, h=0.04, mat=MAT_FRAME),  # rod
        Part(BOX, [(far * (f.width / 2.0 - 0.03), yc - 0.24, 0.006 + paddle_h / 2.0), (far * (f.width / 2.0 - 0.03), yc + 0.24, 0.006 + paddle_h / 2.0)],
             r=0.02, h=paddle_h, mat=MAT_ACCENT),  # paddle
    ]
    return parts


# ------------------------------------------------------------ assemblies

def junction_parts(layout, sides: tuple, tech: str, flip: bool, f: Frame, surface: str = "rollers") -> list[Part]:
    """All parts of one junction module (MERGE or DIVERTER) of `layout`
    (model/junction.JunctionLayout; `sides` its infeed sides). `flip`: the
    layout is the mirrored (outbound) one -- the parts are laid out for the
    unmirrored layout and mirrored at the end."""
    L = layout.length_m
    geoms = [layout.sides[sd] for sd in sides]
    # Transfer zone along the main line: where the feeder's face meets it.
    y0 = min(g.y_face_start for g in geoms)
    y1 = max(g.y_face_end for g in geoms)
    angled = any(g.fence for g in geoms)
    rollers = surface == "rollers" and tech != "ARB"  # an angled-roller junction is a belt section (the tree lays its plate)
    travel = _travel(geoms[0], sides[0])
    keep = f.roller_r + CLEAR + 0.01  # slots stay clear of the next runs' boundary rollers

    def inside(a: float, b: float) -> tuple[float, float]:
        return max(a, keep), min(b, L - keep)

    mech: list[Part] = []
    slots: list = []
    bed_ys = None
    if tech == "BELT":
        blades, bed_ys = blade_bed(y0, y1, f, L)
        mech = popup_belts(blades, f)
    elif tech == "CHAIN":
        strands = chain_positions(*inside(y0, y1))
        slots = [(y - 0.025, y + 0.025) for y in strands]  # chain and sprockets
        mech = popup_chains(strands, f)
    elif tech == "POPUP":
        bed_ys = _interior_stations(L, f.transfer_pitch(2.0 * WHEEL_R))
        stations = [0.0] + bed_ys + [L]  # with the next runs' rollers
        if angled:
            mech = popup_wheels_plated(stations, y0, max(y1, max(g.y_landing for g in geoms)), f, travel)
        else:
            mech = popup_wheels(stations, y0, y1, f, travel)
    elif tech == "STRIP":
        # HPD cassettes where the goods cross: between the face's middle and
        # the sharp tip (upstream of the opening once mirrored for a divert),
        # more of them the longer the opening in the main line's side.
        g = geoms[0]
        n = max(2, min(4, int((g.y_gap_end - g.y_gap_start) / 0.3 + 0.5)))
        n = min(n, int((L - 2.0 * keep) / HPD_CASSETTE))
        if n >= 1:
            span = n * HPD_CASSETTE
            yc = (g.face_center[1] + g.y_landing) / 2.0 if angled else g.face_center[1]
            c0 = max(keep, min(yc - span / 2.0, L - keep - span))
            slots = [(c0, c0 + span)]
            mech = hpd_cassettes(c0, n, f, travel)
    elif tech == "ARB":
        outline = [(x, L - y) for x, y in layout.outline] if flip else list(layout.outline)
        mech = arb_rollers(outline, L, travel, f)
    elif tech == "PUSHER":
        mech = pusher_parts(L, sides[0], f)
    if bed_ys is None:
        bed_ys = slotted_bed(L, f, slots)
    parts: list[Part] = []
    if rollers:
        parts += bed_rollers(bed_ys, f)
        for g, sd in zip(geoms, sides):
            parts += wedge_rollers(g, sd, f)
            parts += wedge_plates(g, sd, f)
    for g in geoms:
        parts += wedge_frame(g, f)
        if g.fence:
            parts += fence_posts([(x, y, 0.0) for x, y, _h in g.fence], f, spacing=0.6)
    parts += mech
    if flip:
        parts = [mirror(p, L) for p in parts]
    return parts


def mirror(part: Part, length: float) -> Part:
    """The part mirrored along the main line (y -> L - y)."""
    return Part(part.kind, [(x, length - y, z) for x, y, z in part.points], part.r, part.h, part.mat, part.lift, part.tr)


def tag_transfer(parts: list[Part], transfer: int) -> list[Part]:
    """Marks the moving parts (lift > 0) as belonging to `transfer`."""
    for p in parts:
        if p.lift > 0.0:
            p.tr = transfer
    return parts


def rat_length(length: float, face_left: float = 0.0, face_right: float = 0.0) -> float:
    """A right-angle transfer's footprint along its line: its own length,
    or the frame width of the widest line docked on a side face -- that
    face runs the module's whole length, so a 1200 mm line docking on an
    800 mm RAT stretches it to 1240 mm (user, 2026-10-11)."""
    return max(float(length), float(face_left or 0.0), float(face_right or 0.0))


STAND_POST = 0.05  # square posts of a RAT's own stands
STAND_BAR = 0.04
GUIDE_RISE, GUIDE_H, GUIDE_T = 0.12, 0.06, 0.008  # the line's guide rail (geonodes Guide Rail Rise / Height / Thickness defaults)


def end_stop(y: float, off: float, f: Frame) -> list[Part]:
    """A guard across the bed at `y` (a transfer's free start or end face):
    a bar at guide-rail height between the fence lines, on posts. A BOX,
    not a FENCE line: the tree sweeps fences with their normal left of the
    point heading, and a guard across the line swept flat, then upright at
    one end and hanging at the other (2026-10-11); a box is
    turned along its own two points and stands whatever the heading."""
    line = [(-off, y, 0.0), (off, y, 0.0)]
    zc = GUIDE_RISE + GUIDE_H / 2.0
    return [Part(BOX, [(-off, y, zc), (off, y, zc)], r=GUIDE_T, h=GUIDE_H, mat=MAT_FRAME)] + fence_posts(line, f)


def _stand(f: Frame, pts: list, floor_drop: float) -> list[Part]:
    """Two posts under `pts` (x, y) from the frame down to the floor, with a bar between them."""
    if floor_drop < 0.15:
        return []
    top = f.frame_bottom
    bottom = -floor_drop
    zc = (top + bottom) / 2.0
    out = [Part(BOX, [(x, y - STAND_POST / 2.0, zc), (x, y + STAND_POST / 2.0, zc)], r=STAND_POST, h=top - bottom) for x, y in pts]
    (x0, y0), (x1, y1) = pts
    zb = bottom + 0.12
    out.append(Part(BOX, [(x0, y0, zb), (x1, y1, zb)], r=STAND_BAR, h=STAND_BAR))
    return out


def rat_parts(length: float, exit_side: str, f: Frame, tech: str = "BELT", open_sides: tuple = (), face_widths: dict | None = None,
              closed_start: bool = False, closed_end: bool = False, stands: tuple = (), floor_drop: float = 0.0) -> tuple[list[Part], list[list[tuple]]]:
    """A right-angle transfer section of `length` along the incoming travel.
    Returns (parts, fence polylines). exit_side: 'LEFT' / 'RIGHT' (the line
    turns there; goods leave through that side at the middle) or
    'STRAIGHT' (a transfer bed the line runs straight through).
    `open_sides`: sides other lines dock on, each opened to `face_widths`
    (that line's frame width; the guards either side close the step to a
    wider deck). `closed_start` / `closed_end`: a guard across the start /
    end face of a standalone transfer nothing meets. `stands`: the free
    faces ('LEFT', 'RIGHT', 'START', 'END') that get their own legs, down
    `floor_drop` to the floor."""
    parts: list[Part] = []
    fences: list[list[tuple]] = []
    keep = f.roller_r + CLEAR + 0.01
    y0, y1 = max(0.08, keep), min(length - 0.08, length - keep)
    if tech == "POPUP":
        ys = _interior_stations(length, f.transfer_pitch(2.0 * WHEEL_R))
        sx = -1.0 if exit_side == 'LEFT' else 1.0
        parts += bed_rollers(ys, f) + popup_wheels([0.0] + ys + [length], y0, y1, f, (sx, 0.0))
    else:
        blades, ys = blade_bed(y0, y1, f, length)
        parts += bed_rollers(ys, f) + popup_belts(blades, f)
    off = f.fence_offset
    # Frame: both sides, plus the far end when the line turns here (or nothing follows).
    for sx in (-1.0, 1.0):
        parts.append(Part(RAIL, [(sx * off, 0.0, f.rail_z), (sx * off, length, f.rail_z)], r=f.rail_t, h=f.rail_h))
    openings = {s for s in (exit_side, *open_sides) if s in ('LEFT', 'RIGHT')}
    stops = []  # faces guarded across (end_stop): the far end when the line turns here or nothing follows, the start when nothing meets it
    if (exit_side in ('LEFT', 'RIGHT') and 'END' not in open_sides) or closed_end:
        parts.append(Part(RAIL, [(-off, length, f.rail_z), (off, length, f.rail_z)], r=f.rail_t, h=f.rail_h))
        stops.append(length)
    if closed_start:
        parts.append(Part(RAIL, [(-off, 0.0, f.rail_z), (off, 0.0, f.rail_z)], r=f.rail_t, h=f.rail_h))
        stops.append(0.0)
    c = length / 2.0
    widths = face_widths or {}
    for side, sx in (('LEFT', -1.0), ('RIGHT', 1.0)):
        if side in openings:
            # Guards either side of the opening a line leaves (or comes in)
            # through, as wide as that line's frame.
            half = float(widths.get(side, 2.0 * off)) / 2.0 + 0.01
            open0, open1 = c - half, c + half
            if open0 > 0.06:
                fences.append([(sx * off, 0.0, 0.0), (sx * off, open0, 0.0)])
            if length - open1 > 0.06:
                fences.append([(sx * off, open1, 0.0), (sx * off, length, 0.0)])
        else:
            fences.append([(sx * off, 0.0, 0.0), (sx * off, length, 0.0)])  # closed side: a guard the full length
    for line in fences:
        parts += fence_posts(line, f)
    for y in stops:
        parts += end_stop(y, off, f)
    # A standalone transfer stands on its own legs under every free face.
    inset = min(0.12, length / 4.0)
    for side in stands:
        if side == 'LEFT':
            parts += _stand(f, [(-(off + 0.03), inset), (-(off + 0.03), length - inset)], floor_drop)
        elif side == 'RIGHT':
            parts += _stand(f, [(off + 0.03, inset), (off + 0.03, length - inset)], floor_drop)
        elif side == 'START':
            parts += _stand(f, [(-(off - 0.05), 0.06), (off - 0.05, 0.06)], floor_drop)
        elif side == 'END':
            parts += _stand(f, [(-(off - 0.05), length - 0.06), (off - 0.05, length - 0.06)], floor_drop)
    return parts, fences
