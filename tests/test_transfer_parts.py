"""Invariants of the transfer-section layouts (model/transfer_parts.py).
Pure Python: python3 -m unittest tests/test_transfer_parts.py"""
import importlib.util
import math
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


J = _load("junction", "model/junction.py")
T = _load("transfer_parts", "model/transfer_parts.py")
FRAME = T.Frame(width=0.5, roller_r=0.024, pitch=0.052)
EDGE = 0.27  # deck half width = the main frame's outer face
ANGLES = (15, 30, 45, 60, 75)


def _layout(angle, side=1):
    return J.junction_layout(angle, 0.54, EDGE, (side,), fence_offset_m=0.26, fence_inset_m=0.01)


def _parts(angle, tech, side=1, divert=False):
    """Parts of a junction as build_line makes them: a divert gets the mirrored layout and flip."""
    lay = _layout(angle, side)
    if divert:
        lay = J.mirror_layout(lay)
    return lay, T.junction_parts(lay, (side,), tech, divert, FRAME)


def _mid_y(p):
    return (p.points[0][1] + p.points[-1][1]) / 2.0


def _bed(parts):
    """Main-bed rollers: full-width rollers square across the main line."""
    return sorted((p for p in parts if p.kind == T.ROLLER and p.r == FRAME.roller_r
                   and abs(p.points[0][0]) < EDGE and abs(p.points[1][0]) < EDGE and abs(p.points[1][0] - p.points[0][0]) > 0.3),
                  key=_mid_y)


def _inside(poly, x, y):
    """Point in polygon (ray casting)."""
    hit = False
    n = len(poly)
    for i in range(n):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            hit = not hit
    return hit


class TransferParts(unittest.TestCase):
    def test_wedge_rollers_clear_the_main_frame(self):
        r = FRAME.roller_r
        for angle in ANGLES:
            for side in (1, -1):
                g = _layout(angle, side).sides[side]
                parts = T.wedge_rollers(g, side, FRAME)
                self.assertTrue(parts, f"no wedge rollers at {angle}")
                for p in parts:
                    (ax, ay, _), (bx, by, _) = p.points
                    ux, uy = T._unit((bx - ax, by - ay))
                    for x, y in ((ax, ay), (bx, by)):  # end-cap corners
                        for sgn in (1, -1):
                            cx = x - sgn * r * uy
                            self.assertGreaterEqual(side * cx, EDGE + FRAME.rail_t - 1e-6,
                                                    f"{angle}/{side}: wedge roller cap in the frame")

    def test_wedge_rollers_parallel_to_the_face(self):
        g = _layout(45, 1).sides[1]
        fx, fy = g.outline[3][0] - g.outline[2][0], g.outline[3][1] - g.outline[2][1]
        for p in T.wedge_rollers(g, 1, FRAME):
            (ax, ay, _), (bx, by, _) = p.points
            self.assertAlmostEqual((bx - ax) * fy - (by - ay) * fx, 0.0, places=6)

    def test_main_line_rollers_stay_square(self):
        """Merge modules leave the main line alone (no skewed rollers)."""
        for angle in ANGLES:
            _lay, parts = _parts(angle, "SKEW")
            bed = _bed(parts)
            self.assertGreater(len(bed), 5)
            for p in bed:
                self.assertAlmostEqual(p.points[0][1], p.points[1][1], places=9)

    def test_bed_rollers_never_touch(self):
        for tech, angles in (("SKEW", ANGLES), ("POPUP", ANGLES + (90,)), ("STRIP", ANGLES + (90,)),
                             ("BELT", (90,)), ("CHAIN", (90,)), ("PUSHER", (90,))):
            for angle in angles:
                for divert in (False, True):
                    _lay, parts = _parts(angle, tech, divert=divert)
                    ys = [_mid_y(p) for p in _bed(parts)]
                    for a, b in zip(ys, ys[1:]):
                        self.assertGreater(b - a, 2 * FRAME.roller_r, f"{tech} {angle}: bed rollers overlap")

    def test_blades_sit_in_widened_gaps(self):
        for divert in (False, True):
            lay, parts = _parts(90, "BELT", divert=divert)
            blades = [p for p in parts if p.kind == T.BOX and p.lift > 0.0 and abs(p.r - T.BLADE_W) < 1e-9]
            belts = [p for p in parts if p.kind == T.BELT]
            self.assertTrue(2 <= len(blades) <= 5 and len(belts) == len(blades), "2-5 blades, one belt each")
            ys = [_mid_y(p) for p in _bed(parts)] + [0.0, lay.length_m]  # plus the next runs' boundary rollers
            for blade in blades:
                y = _mid_y(blade)
                nearest = min(abs(y - ry) for ry in ys)
                self.assertGreaterEqual(nearest, FRAME.roller_r + T.BLADE_W / 2.0 + T.CLEAR - 1e-6, "blade hits a roller")

    def test_blade_beds_keep_an_even_pitch(self):
        """Blade gaps are exactly a blade plus two clearances; every other
        gap (to the next runs' rollers too) is one common step: the line's
        pitch, stretched a little to make the length come out whole."""
        flank = T.BLADE_W / 2.0 + FRAME.roller_r + T.CLEAR
        cases = [(_parts(90, "BELT", divert=d)[0].length_m, _parts(90, "BELT", divert=d)[1]) for d in (False, True)]
        cases += [(L, T.rat_parts(L, 'LEFT', FRAME)[0]) for L in (0.6, 0.9, 1.2)]
        for L, parts in cases:
            ys = [0.0] + [_mid_y(p) for p in _bed(parts)] + [L]
            blades = [_mid_y(p) for p in parts if p.kind == T.BOX and p.lift > 0.0 and abs(p.r - T.BLADE_W) < 1e-9]
            self.assertTrue(2 <= len(blades) <= 5, L)
            steps = []
            for a, b in zip(ys, ys[1:]):
                if any(a < y < b for y in blades):
                    self.assertAlmostEqual(b - a, 2.0 * flank, places=6)
                else:
                    steps.append(b - a)
            self.assertTrue(steps)
            self.assertLess(max(steps) - min(steps), 1e-6, f"{L}: uneven bed")
            self.assertTrue(FRAME.pitch - 1e-9 <= steps[0] <= 1.25 * FRAME.pitch, f"{L}: step {steps[0]}")

    def test_wheel_beds_open_up(self):
        for angle in (45, 90):
            _lay, parts = _parts(angle, "POPUP")
            wheels = [p for p in parts if p.kind == T.WHEEL]
            self.assertTrue(wheels)
            ys = [_mid_y(p) for p in _bed(parts)]
            self.assertTrue(all(b - a >= 2 * FRAME.roller_r + 2 * T.WHEEL_R for a, b in zip(ys, ys[1:])), angle)
            if angle < 90:
                self.assertTrue([p for p in parts if p.kind == T.BOX and p.mat == T.MAT_FRAME and p.h == T.PLATE_T], "cover plates")

    def test_hpd_cassettes(self):
        for angle in (30, 45, 90):
            for divert in (False, True):
                lay, parts = _parts(angle, "STRIP", divert=divert)
                pockets = [p for p in parts if p.kind == T.WHEEL and abs(p.points[0][0] - p.points[1][0]) < 1e-9
                           and abs(p.points[0][1] - p.points[1][1]) < 1e-9]
                swivel = [p for p in parts if p.kind == T.ROLLER and p.r == T.HPD_ROLLER_R]
                self.assertTrue(pockets and len(pockets) == len(swivel) and len(pockets) % 16 == 0, f"{angle}: 2 rows of 8 per cassette")
                # Rollers turned square to the feeder's travel.
                g = lay.sides[1]
                tx, ty = T._travel(g, 1)
                if divert:
                    ty = -ty
                for p in swivel:
                    (ax, ay, _), (bx, by, _) = p.points
                    self.assertAlmostEqual((bx - ax) * tx + (by - ay) * ty, 0.0, places=6)
                # No main-line roller under the cassettes.
                ys = [_mid_y(p) for p in pockets]
                lo, hi = min(ys) - T.HPD_GRID / 2.0, max(ys) + T.HPD_GRID / 2.0
                for p in _bed(parts):
                    y = _mid_y(p)
                    self.assertFalse(lo - FRAME.roller_r < y < hi + FRAME.roller_r, "a roller under the HPD")

    def test_dead_plate_covers_the_tip(self):
        for angle in ANGLES:
            for side in (1, -1):
                g = _layout(angle, side).sides[side]
                plates = T.wedge_plates(g, side, FRAME)
                self.assertTrue(plates and all(p.kind == T.PLATE for p in plates), f"{angle}: no dead plate")
                poly = list(g.outline[2:-3])
                area = abs(T.polygon_area(poly))
                covered = sum(abs(T.polygon_area([(x, y) for x, y, _z in p.points])) for p in plates)
                self.assertLess(covered, area + 1e-9, f"{angle}: plates overlap or leave the wedge")
                for p in plates:
                    for x, y, _z in p.points:
                        self.assertTrue(any(_inside(poly, x + dx, y + dy) for dx in (-1e-6, 1e-6) for dy in (-1e-6, 1e-6))
                                        or min(math.hypot(x - a, y - b) for a, b in poly) < 1e-6
                                        or side * x <= EDGE + 1e-6, f"{angle}: plate point off the wedge")
                # It runs right into the sharp tip.
                tip = (side * EDGE, g.y_landing)
                self.assertLess(min(math.hypot(x - tip[0], y - tip[1]) for p in plates for x, y, _z in p.points), 0.02, f"{angle}")

    def test_mirrored_layout_mirrors_parts(self):
        lay = _layout(45, 1)
        a = T.junction_parts(lay, (1,), "SKEW", False, FRAME)
        b = T.junction_parts(J.mirror_layout(lay), (1,), "SKEW", True, FRAME)
        self.assertEqual(len(a), len(b))
        L = lay.length_m
        for pa, pb in zip(a, b):
            for (xa, ya, za), (xb, yb, zb) in zip(pa.points, pb.points):
                self.assertAlmostEqual(xa, xb)
                self.assertAlmostEqual(L - ya, yb)

    def test_rat_corner_is_guarded(self):
        parts, fences = T.rat_parts(0.9, 'LEFT', FRAME)
        off = FRAME.fence_offset
        closed = [f for f in fences if all(abs(x - off) < 1e-9 for x, _y, _z in f)]
        stop = [p for p in parts if p.kind == T.BOX and abs(p.h - T.GUIDE_H) < 1e-9 and abs(p.points[0][1] - 0.9) < 1e-9]
        self.assertTrue(closed and stop, "closed-side guard and end stop (a bar across the far end) expected")
        self.assertTrue(any(p.kind == T.BELT for p in parts))
        self.assertFalse(any(p.kind == T.BOX and p.mat == T.MAT_LINKS for p in parts), "no drive box under a RAT (2026-10-10)")

    def test_arb_rollers_inside_the_outline(self):
        for divert in (False, True):
            lay, parts = _parts(45, "ARB", divert=divert)
            wheels = [p for p in parts if p.kind == T.WHEEL]
            self.assertGreater(len(wheels), 50)
            self.assertFalse([p for p in parts if p.kind == T.ROLLER], "an ARB junction is a belt: no rollers")
            poly = lay.outline[:-1]  # the outline the tree lays the belt plate over
            for p in wheels:
                x = (p.points[0][0] + p.points[1][0]) / 2.0
                self.assertTrue(_inside(poly, x, _mid_y(p)), "ARB roller off the belt")


if __name__ == "__main__":
    unittest.main()


class RatFacesTests(unittest.TestCase):
    """A right-angle transfer with lines of other widths on its faces (2026-10-11)."""

    def test_length_follows_the_widest_docked_line(self):
        self.assertAlmostEqual(T.rat_length(0.9, 0.0, 0.0), 0.9)
        self.assertAlmostEqual(T.rat_length(0.9, 1.24, 0.0), 1.24)  # a 1200 mm line (frame 1240) on the left face
        self.assertAlmostEqual(T.rat_length(0.9, 0.0, 0.84), 0.9)

    def test_opening_is_as_wide_as_the_docked_line(self):
        length = T.rat_length(1.8, 1.24)  # a long transfer: the guards either side of the 1240 mm opening close the step
        parts, fences = T.rat_parts(length, 'STRAIGHT', FRAME, open_sides=('LEFT',), face_widths={'LEFT': 1.24})
        off = FRAME.fence_offset
        left = sorted(f for f in fences if all(abs(x + off) < 1e-9 for x, _y, _z in f))
        self.assertTrue(left, "guards either side of the opening expected")
        gap = min(abs(f[0][1] - length / 2.0) for f in left) * 2.0
        self.assertAlmostEqual(gap, 1.24 + 0.02, places=2)  # the opening spans the docked line's frame
        right = [f for f in fences if all(abs(x - off) < 1e-9 for x, _y, _z in f)]
        self.assertEqual(len(right), 1)  # the free right face stays closed the full length
        self.assertAlmostEqual(right[0][1][1], length)

    def test_standalone_transfer_stands_on_its_own_legs(self):
        parts, fences = T.rat_parts(0.9, 'STRAIGHT', FRAME, closed_start=True, closed_end=True,
                                    stands=('LEFT', 'RIGHT', 'START', 'END'), floor_drop=0.7)
        posts = [p for p in parts if p.kind == T.BOX and abs(p.r - T.STAND_POST) < 1e-9]
        self.assertEqual(len(posts), 8)  # two per face
        bottom = min(p.points[0][2] - p.h / 2.0 for p in posts)
        self.assertAlmostEqual(bottom, -0.7, places=6)  # down to the floor
        self.assertFalse([f for f in fences if all(abs(y) < 1e-9 for _x, y, _z in f) or all(abs(y - 0.9) < 1e-9 for _x, y, _z in f)],
                         "no fence sweeps across the ends (they came out flat / hanging)")
        bars = [p for p in parts if p.kind == T.BOX and abs(p.h - T.GUIDE_H) < 1e-9 and abs(p.r - T.GUIDE_T) < 1e-9]
        self.assertEqual(sorted(round(p.points[0][1], 6) for p in bars), [0.0, 0.9])  # a bar across both free ends
        self.assertTrue(all(abs(p.points[0][2] - (T.GUIDE_RISE + T.GUIDE_H / 2.0)) < 1e-9 for p in bars))  # at guide-rail height
        posts = [p for p in parts if p.kind == T.BOX and p.lift == 0.0 and abs(p.r - T.POST) < 1e-9]  # (blades lift; posts do not)
        self.assertEqual(len(posts), 8)  # two posts per guard, four guards
        parts2, _ = T.rat_parts(0.9, 'STRAIGHT', FRAME, stands=('LEFT',), floor_drop=0.05)
        self.assertFalse([p for p in parts2 if p.kind == T.BOX and abs(p.r - T.STAND_POST) < 1e-9], "no stands at floor level")

    def test_a_line_straight_through_the_far_face_opens_the_end_stop(self):
        """A corner RAT keeps its end stop until a line docks on its far face (2026-10-11 night)."""
        closed, _ = T.rat_parts(0.9, 'LEFT', FRAME)
        opened, _ = T.rat_parts(0.9, 'LEFT', FRAME, open_sides=('END',))
        bars = lambda parts: [p for p in parts if p.kind == T.BOX and abs(p.h - T.GUIDE_H) < 1e-9 and abs(p.points[0][1] - 0.9) < 1e-9]
        self.assertEqual(len(bars(closed)), 1)
        self.assertEqual(len(bars(opened)), 0)
        stops = lambda parts: [p for p in parts if p.kind == T.RAIL and all(abs(y - 0.9) < 1e-9 for _x, y, _z in p.points)]
        self.assertEqual(len(stops(closed)), 1)
        self.assertEqual(len(stops(opened)), 0)

    def test_belts_are_legible_at_rest(self):
        """Round 7: a standalone RAT read as plain rollers. The belts rest just
        under the roller line in steel-blade slots and still rise 12 mm over it."""
        parts, _ = T.rat_parts(0.9, 'STRAIGHT', FRAME)
        blades = [p for p in parts if p.kind == T.BOX and p.lift > 0.0 and abs(p.r - T.BLADE_W) < 1e-9]
        belts = [p for p in parts if p.kind == T.BELT]
        self.assertTrue(blades and len(belts) == len(blades))
        self.assertTrue(all(p.mat == T.MAT_FRAME for p in blades))  # a galvanized carrier under the black belt (round 12)
        top = max(p.points[0][2] + p.h / 2.0 for p in belts)
        self.assertGreaterEqual(top, -0.0025)  # at rest just under the roller tops (z = 0)
        self.assertLessEqual(top, 0.0)
        self.assertGreaterEqual(blades[0].r, 0.028)  # the blade fills its slot: a black band, not a line
        self.assertAlmostEqual(top + belts[0].lift, 0.012, places=6)  # raised: 12 mm over the rollers

    def test_a_line_as_wide_as_the_face_opens_it_fully(self):
        length = T.rat_length(0.9, 1.24)
        _parts, fences = T.rat_parts(length, 'STRAIGHT', FRAME, open_sides=('LEFT',), face_widths={'LEFT': 1.24})
        off = FRAME.fence_offset
        self.assertFalse([f for f in fences if all(abs(x + off) < 1e-9 for x, _y, _z in f)], "the whole face is the opening")
