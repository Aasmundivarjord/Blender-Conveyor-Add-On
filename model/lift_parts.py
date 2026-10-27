"""A vertical lift as a fork-column continuous vertical conveyor (Qimarox
Prorunner mk5 / Unitfine fork-arm loop lifter), pure Python, no bpy.

How the real unit is built (measured from Qimarox's published STEP
files): the line runs ACROSS the front of a flat column
(1071 mm along the line, 378 mm deep) that stands beside it. Inside the
column one chain loop runs up one leg and down the other, the legs 675 mm
apart (9 tine pitches); every carrier is a fork of 8 tines (10 x 20 mm, 75
mm pitch; drawn with 6 so it stays inside the column's outline) cantilevered
from a leveller trolley on the chain, kept level all the way round. The infeed and outfeed are roller COMBS: rollers at the same
75 mm pitch, halfway between the tines, so a fork rises through the infeed
comb and lifts the load off the rollers without stopping, carries it over
the top wheel to the other leg, and descends through the outfeed comb,
leaving the load on those rollers. Z: in and out collinear along the face
(pick over one leg, drop over the other). C: the outfeed sits over the
other leg above the infeed and runs back out over it.

Module frame (operators/build_line.py): x = right of travel, y = along it
from the module's start, z = up from the infeed roller tops. The goods'
path (model/segments._sample_lift) and the fork loop here share R, the leg
positions and the apex height, so a fork is exactly under its load.

The forks are timed to the item stream: the tree spaces them one item
slot apart round the loop and phases them onto the slot grid, so a fork is
under every load; the loop's seam (where the spacing is irregular) sits at
the bottom apex, under the infeed comb
(geonodes/cross_sections/common.build_lift_forks).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .segments import LIFT_LEN, LIFT_PICK_CLEAR, LIFT_R, LIFT_Z_BOT, lift_apex, lift_legs, lift_path_length
from .transfer_parts import BOX, RAIL, ROLLER, END_MARGIN, MAT_ACCENT, MAT_BELT, MAT_FRAME, MAT_LINKS, MAT_ROLLER, Frame, Part

LENGTH = LIFT_LEN  # comb frame along the line: the column plus 200 mm each side
R = LIFT_R  # loop radius = half the leg spacing = 9 tine pitches (both legs on one comb grid)
COLUMN_W, COLUMN_D = 1.071, 0.378
FACE_CLEAR = 0.17  # column face behind the near edge of the bed
TINE_N, TINE_PITCH, TINE_W, TINE_H = 6, 0.075, 0.010, 0.020  # 6 of the real 8: inside the column's silhouette (geonodes/cross_sections/common.LIFT_TINE_N)
TINE_ROOT = 0.03  # tines start this far in front of the face...
TINE_END = 0.045  # ...and end this far short of the far edge of the bed
CROSSBAR_W, CROSSBAR_H = 0.04, 0.05
COMB_R = 0.02  # comb rollers: 40 mm
Z_BOT = LIFT_Z_BOT  # bottom wheel centre just under the infeed
PICK_CLEAR = LIFT_PICK_CLEAR  # the top wheel centre at least this far above the outfeed
TOP_CLEAR = 0.12  # column top above the top apex
POST = 0.06
WINDOW_W = 0.9  # the opening between the posts both legs' forks come out of
UNDER_BED = R - Z_BOT + 0.2  # the column (and its loop) reach this far under the infeed: the line must sit higher than this
MOTOR = (0.35, 0.27, 0.21)  # gearmotor housing at the top rear: along, deep, tall
STEP_DEG = 5.0


@dataclass
class LiftLayout:
    height: float  # outfeed above the infeed
    shape: str  # 'Z' or 'C'
    z_top: float  # top wheel centre
    length: float = LENGTH
    y_c: float = LENGTH / 2.0  # column centre along the line
    legs: tuple = field(default=(LENGTH / 2.0 - R, LENGTH / 2.0 + R))  # (y1, y2)

    @property
    def z_bot(self) -> float:
        return Z_BOT

    @property
    def y_pick(self) -> float:
        """The leg the goods go up on (Z: the first, C: the second)."""
        return lift_legs(self.shape)[0]

    @property
    def y_drop(self) -> float:
        return lift_legs(self.shape)[1]

    @property
    def loop_length(self) -> float:
        return 2.0 * (self.z_top - self.z_bot) + 2.0 * math.pi * R

    @property
    def path_length(self) -> float:
        """The goods' path through the module (model/segments.lift_path_length)."""
        return lift_path_length(self.height, self.z_top, self.shape)

    @property
    def arc_pick(self) -> float:
        """Geometric arc (from the module start) of the pick corner."""
        return self.y_pick

    @property
    def arc_drop(self) -> float:
        return self.y_pick + self.z_top + math.pi * R + (self.z_top - self.height)

    @property
    def column_top(self) -> float:
        return self.z_top + R + TOP_CLEAR


def lift_layout(height: float, shape: str) -> LiftLayout:
    return LiftLayout(height=height, shape='C' if shape == 'C' else 'Z', z_top=lift_apex(height))


def fork_loop(layout: LiftLayout, up_y: float, down_y: float) -> list[tuple[float, float]]:
    """The fork reference path (y, z) once round the loop in the forks'
    travel direction, starting (and ending: the first point is repeated) at
    the bottom apex under the column's centre -- the seam of the fork
    spacing, hidden under the infeed comb."""
    steps = max(2, int(round(180.0 / STEP_DEG)))
    half = steps // 2
    yc = (up_y + down_y) / 2.0
    s = 1.0 if down_y > up_y else -1.0
    pts = []
    for k in range(0, half + 1):  # bottom apex -> up-leg foot (theta from 90 to 180 deg round the bottom wheel)
        a = math.pi / 2.0 + math.pi * k / steps
        pts.append((yc + s * R * math.cos(a), layout.z_bot - R * math.sin(a)))
    pts.append((up_y, layout.z_top))
    for k in range(1, steps + 1):  # over the top
        a = math.pi * k / steps
        pts.append((yc - s * R * math.cos(a), layout.z_top + R * math.sin(a)))
    pts.append((down_y, layout.z_bot))
    for k in range(1, half):  # down-leg foot -> bottom apex
        a = math.pi * k / steps
        pts.append((yc + s * R * math.cos(a), layout.z_bot - R * math.sin(a)))
    pts.append(pts[0])
    return pts


def pick_loop_coord(layout: LiftLayout, z_pick: float) -> float:
    """Loop coordinate (from the bottom apex) of the point on the up-leg
    at height z_pick: the quarter arc, then straight up."""
    return math.pi * R / 2.0 + (z_pick - layout.z_bot)


def drop_loop_coord(layout: LiftLayout, z_drop: float) -> float:
    """Loop coordinate (from the bottom apex) of the point on the DOWN-leg
    at height z_drop: up the first leg, over the top, down to it."""
    return math.pi * R / 2.0 + (layout.z_top - layout.z_bot) + math.pi * R + (layout.z_top - z_drop)


def fork_offsets(width: float, side: str) -> tuple[float, float]:
    """(x of the column face, signed tine reach from TINE_ROOT in front of
    it) for the column on `side` ('LEFT' / 'RIGHT') of a `width` wide bed."""
    s = -1.0 if side != 'RIGHT' else 1.0
    face = s * (width / 2.0 + FACE_CLEAR)
    reach = -s * (width + FACE_CLEAR - TINE_ROOT - TINE_END)
    return face, reach


def tine_stations(y_leg: float) -> list[float]:
    return [y_leg + (k - (TINE_N - 1) / 2.0) * TINE_PITCH for k in range(TINE_N)]


def comb_stations(layout: LiftLayout, y0: float, y1: float) -> list[float]:
    """Roller stations on the comb grid (halfway between the tines of
    either leg) inside [y0, y1], clear of the module boundary rollers."""
    base = layout.legs[0]
    lo, hi = max(y0, 0.0) + COMB_R + 0.01, min(y1, layout.length) - COMB_R - 0.01
    m0 = int(math.ceil((lo - base) / TINE_PITCH - 1e-9))
    m1 = int(math.floor((hi - base) / TINE_PITCH + 1e-9))
    return [base + m * TINE_PITCH for m in range(m0, m1 + 1)]


def lift_parts(layout: LiftLayout, f: Frame, side: str) -> list[Part]:
    """Static parts: the two roller combs with their frames, the stop plate,
    the column's corner posts, window and gearmotor. (The column body is a
    ROLE_COLUMN spline reaching the floor, the forks are instanced by the
    tree.)"""
    s = -1.0 if side != 'RIGHT' else 1.0
    face, _reach = fork_offsets(f.width, side)
    near = face - s * 0.04  # roller ends near the column
    far = -s * (f.width / 2.0 - END_MARGIN)
    rail_far = -s * f.fence_offset
    rail_near = face - s * 0.015
    near_rail_z = -0.06 - f.rail_h / 2.0  # lowered: the fork crossbars pass over it
    H = layout.height
    L = layout.length
    yc = layout.y_c
    parts: list[Part] = []
    if layout.shape == 'Z':
        combs = [((0.0, yc), 0.0), ((yc, L), H)]
    else:
        combs = [((0.0, L), 0.0), ((0.0, yc), H)]
    for (a, b), z in combs:
        for y in comb_stations(layout, a, b):
            parts.append(Part(ROLLER, [(near, y, z - COMB_R), (far, y, z - COMB_R)], r=COMB_R, mat=MAT_ROLLER))
        parts.append(Part(RAIL, [(rail_far, a, z + f.rail_z), (rail_far, b, z + f.rail_z)], r=f.rail_t, h=f.rail_h, mat=MAT_FRAME))
        parts.append(Part(RAIL, [(rail_near, a, z + near_rail_z), (rail_near, b, z + near_rail_z)], r=f.rail_t, h=f.rail_h, mat=MAT_FRAME))
        for y in (a + 0.02, b - 0.02):
            parts.append(Part(BOX, [(rail_near, y, z + near_rail_z), (rail_far, y, z + near_rail_z)], r=0.04, h=f.rail_h, mat=MAT_FRAME))
    # Stop plate where the goods wait over the pick leg (Z: the column
    # centreline; C: the module's far end).
    y_stop = yc if layout.shape == 'Z' else L - 0.02
    parts.append(Part(BOX, [(near, y_stop, 0.055), (far, y_stop, 0.055)], r=0.02, h=0.13, mat=MAT_ACCENT))
    # Column front: corner posts, the window, the gearmotor at the top rear.
    top = layout.column_top
    post_bottom = -UNDER_BED
    for sy in (-1.0, 1.0):
        y = yc + sy * (COLUMN_W / 2.0 - POST / 2.0)
        x = face - s * POST / 2.0  # proud of the face, toward the line
        zc = (top + post_bottom) / 2.0
        parts.append(Part(BOX, [(x, y - POST / 2.0, zc), (x, y + POST / 2.0, zc)], r=POST, h=top - post_bottom, mat=MAT_ACCENT))
    wz0, wz1 = layout.z_bot - R - 0.08, layout.z_top + R + 0.08  # past the apex forks' crossbars
    parts.append(Part(BOX, [(face - s * 0.003, yc - WINDOW_W / 2.0, (wz0 + wz1) / 2.0), (face - s * 0.003, yc + WINDOW_W / 2.0, (wz0 + wz1) / 2.0)],
                      r=0.006, h=wz1 - wz0, mat=MAT_BELT))
    mx = face + s * (COLUMN_D + MOTOR[1] / 2.0)
    my = yc + 0.2
    mz = top - MOTOR[2] / 2.0 - 0.02
    parts.append(Part(BOX, [(mx, my - MOTOR[0] / 2.0, mz), (mx, my + MOTOR[0] / 2.0, mz)], r=MOTOR[1], h=MOTOR[2], mat=MAT_LINKS))
    return parts


def column_centre(layout: LiftLayout, f: Frame, side: str) -> tuple[float, float, float]:
    """(x, y, top z) of the column body (COLUMN_W along the line, COLUMN_D deep)."""
    s = -1.0 if side != 'RIGHT' else 1.0
    face, _r = fork_offsets(f.width, side)
    return face + s * COLUMN_D / 2.0, layout.y_c, layout.column_top
