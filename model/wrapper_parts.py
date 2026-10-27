"""A conveyorised turntable stretch wrapper (pallet wrapper / unwrapper),
pure Python, no bpy: the Handle It FA-4000 / Lantech Q Automatic class of
machine (research 2026-10-10). A chain conveyor runs across a round
turntable (65-81 in = 1.65-2.06 m, up to 15-16 rpm); a mast beside it
carries the film carriage (a pre-stretch film roll) up and down the load;
wrap heights 86-92 in (2.2-2.3 m); 40-45 loads per hour; the machine's own
infeed and exit chain sections run at about 0.23 m/s. Here the line's
pieces before and after are those sections, and the module holds the
turntable with the chain conveyor across it plus a short fixed chain
section at each end.

Module frame (operators/build_line.py): x = right of travel, y = along it
from the module's start, z = up from the conveying surface. Everything is
scaled from the line's width (user, 2026-10-10: "scaled to the conveyor's
size"): the turntable spans the line and more, the two chain strands sit
under a pallet's outer runners.
"""
from __future__ import annotations

from .transfer_parts import BOX, CHAIN, CHAIN_T, CHAIN_W, MAT_ACCENT, MAT_FRAME, MAT_LINKS, MAT_ROLLER, RAIL, ROLLER, WHEEL, Frame, Part

TABLE_MIN_R = 0.825  # a 65 in turntable, the smallest conveyorised unit
TABLE_R_PER_W = 0.80  # radius from the line's width: a 1260 mm pallet line gets a 2.0 m table (Lantech Q: 81 in)
TABLE_T = 0.14  # the turntable disc
TABLE_TOP = -0.045  # disc top under the chain tops
BASE_W, BASE_H = 1.3, 0.30  # pedestal under the disc: ring gear and drive
MAST_W, MAST_D = 0.26, 0.30  # mast: along the line, out from it
MAST_GAP = 0.30  # mast face clear of the turntable's edge
WRAP_H = 2.3  # wrap height (86-92 in)
MAST_H = WRAP_H + 0.45  # mast top above the surface
MAST_BELOW = 0.45  # mast base below the surface: about floor level at a pallet conveyor's height
CARRIAGE = (0.55, 0.42, 0.75)  # film carriage: along the line, out from the mast, tall
CARRIAGE_Z = 0.95  # its centre at rest, part way up the load
ROLL_R, ROLL_L = 0.14, 0.52  # a 20 in film roll, 10 in across
CUTTER_REACH = 0.45  # unwrapper: the knife arm reaching in over the load's face
CABINET = (0.50, 0.30, 0.90)  # control cabinet beside the mast base
END_SECTION_MIN = 0.25  # the fixed chain section at each end of the module


def table_radius(width: float) -> float:
    return max(TABLE_MIN_R, TABLE_R_PER_W * width)


def chain_x(width: float) -> float:
    """Half the spacing of the two chain strands: under a pallet's outer runners."""
    return max(0.25, min(width / 2.0 - 0.14, 0.45))


def module_length(width: float) -> float:
    """The footprint a line of `width` needs: the turntable plus a fixed chain section each end."""
    return 2.0 * table_radius(width) + 2.0 * END_SECTION_MIN + 0.2


def wrapper_parts(length: float, f: Frame, mode: str = "WRAP", mast_side: str = "RIGHT") -> tuple[list[Part], list[list[tuple]]]:
    """Static parts of the wrapper. Returns (parts, fence polylines): no
    fences, the turntable must stay open all round. `mode` WRAP carries a
    film roll on the carriage, UNWRAP a knife arm reaching in over the load."""
    parts: list[Part] = []
    W = f.width
    R = table_radius(W)
    yc = length / 2.0
    sm = 1.0 if mast_side == "RIGHT" else -1.0
    # Turntable (a vertical cylinder) on its pedestal. A WHEEL part, not a
    # ROLLER: wheels take the module colour (the real table is painted),
    # rollers always take the roller material.
    parts.append(Part(WHEEL, [(0.0, yc, TABLE_TOP - TABLE_T), (0.0, yc, TABLE_TOP)], r=R, mat=MAT_ACCENT))
    zb = TABLE_TOP - TABLE_T - BASE_H / 2.0
    parts.append(Part(BOX, [(-BASE_W / 2.0, yc, zb), (BASE_W / 2.0, yc, zb)], r=BASE_W, h=BASE_H, mat=MAT_FRAME))
    # The chain conveyor: two strands the module long (fixed sections at the
    # ends, the table's own section in the middle) with their side beams.
    cx = chain_x(W)
    for sx in (-cx, cx):
        parts.append(Part(CHAIN, [(sx, 0.0, -CHAIN_T / 2.0), (sx, length, -CHAIN_T / 2.0)], r=CHAIN_W, h=CHAIN_T, mat=MAT_LINKS))
    beam_z = -(CHAIN_T + 0.05)
    for sx in (-(cx + 0.06), cx + 0.06):
        parts.append(Part(BOX, [(sx, yc - R * 0.9, beam_z), (sx, yc + R * 0.9, beam_z)], r=0.05, h=0.08, mat=MAT_FRAME))
    # Side frame rails of the fixed sections only: the turntable is open.
    off = f.fence_offset
    end = max((length - 2.0 * R) / 2.0, 0.0)
    if end > 0.05:
        for sx in (-1.0, 1.0):
            parts.append(Part(RAIL, [(sx * off, 0.0, f.rail_z), (sx * off, end, f.rail_z)], r=f.rail_t, h=f.rail_h))
            parts.append(Part(RAIL, [(sx * off, length - end, f.rail_z), (sx * off, length, f.rail_z)], r=f.rail_t, h=f.rail_h))
    # The mast beside the table, its head, the film carriage on its inner face.
    xm = sm * (R + MAST_GAP + MAST_D / 2.0)
    zm = (MAST_H - MAST_BELOW) / 2.0
    parts.append(Part(BOX, [(xm, yc - MAST_W / 2.0, zm), (xm, yc + MAST_W / 2.0, zm)], r=MAST_D, h=MAST_H + MAST_BELOW, mat=MAT_FRAME))
    parts.append(Part(BOX, [(xm, yc - 0.22, MAST_H + 0.08), (xm, yc + 0.22, MAST_H + 0.08)], r=MAST_D + 0.1, h=0.16, mat=MAT_ACCENT))
    xc = xm - sm * (MAST_D / 2.0 + CARRIAGE[1] / 2.0)
    parts.append(Part(BOX, [(xc, yc - CARRIAGE[0] / 2.0, CARRIAGE_Z), (xc, yc + CARRIAGE[0] / 2.0, CARRIAGE_Z)],
                      r=CARRIAGE[1], h=CARRIAGE[2], mat=MAT_LINKS))
    x_face = xc - sm * CARRIAGE[1] / 2.0  # the carriage's face toward the load
    if mode == "UNWRAP":
        # A knife arm reaching in over the load's face, its blade hanging down.
        parts.append(Part(BOX, [(x_face, yc, CARRIAGE_Z + 0.2), (x_face - sm * CUTTER_REACH, yc, CARRIAGE_Z + 0.2)], r=0.06, h=0.08, mat=MAT_ACCENT))
        xk = x_face - sm * CUTTER_REACH
        parts.append(Part(ROLLER, [(xk, yc, CARRIAGE_Z - 0.1), (xk, yc, CARRIAGE_Z + 0.16)], r=0.02, mat=MAT_ROLLER))
    else:
        xr, yr = x_face - sm * (ROLL_R + 0.03), yc + 0.12
        parts.append(Part(ROLLER, [(xr, yr, CARRIAGE_Z - ROLL_L / 2.0), (xr, yr, CARRIAGE_Z + ROLL_L / 2.0)], r=ROLL_R, mat=MAT_ROLLER))
    # Control cabinet beside the mast base, downstream of it.
    y0 = yc + MAST_W / 2.0 + 0.06
    parts.append(Part(BOX, [(xm, y0, CABINET[2] / 2.0 - 0.3), (xm, y0 + CABINET[0], CABINET[2] / 2.0 - 0.3)], r=CABINET[1], h=CABINET[2], mat=MAT_FRAME))
    return parts, []
