"""A line along points (model/route.py, round 7 R21).
python3 -m unittest tests.test_route (from dev/)."""
import math
import unittest

from model import route as R

W = 0.5  # line width
RADII = [("r800", 0.8), ("r600", 0.6)]  # preferred first, then smaller
NOSE = 1.5


def plan(points, **kw):
    kw.setdefault("transition_radius_m", NOSE)
    return R.plan_route(points, W, RADII, **kw)


def kinds(route):
    return [p.kind for p in route.pieces]


class FlatRouteTests(unittest.TestCase):
    def test_two_points_one_straight(self):
        r = plan([(1.0, 2.0, 0.8), (1.0, 12.0, 0.8)])
        self.assertEqual(kinds(r), ["STRAIGHT"])
        self.assertAlmostEqual(r.pieces[0].length_m, 10.0)
        self.assertAlmostEqual(r.heading, 0.0)
        self.assertLess(r.end_error_m, 1e-6)

    def test_an_l_shape_is_straight_curve_straight(self):
        r = plan([(0.0, 0.0, 0.0), (0.0, 10.0, 0.0), (10.0, 10.0, 0.0)])
        self.assertEqual(kinds(r), ["STRAIGHT", "CURVE", "STRAIGHT"])
        t = 0.8 + W / 2.0  # tan 45 = 1
        self.assertAlmostEqual(r.pieces[0].length_m, 10.0 - t)
        self.assertEqual((round(r.pieces[1].angle_deg, 6), r.pieces[1].direction, r.pieces[1].radius_id), (90.0, "RIGHT", "r800"))
        self.assertAlmostEqual(r.pieces[2].length_m, 10.0 - t)
        self.assertLess(r.end_error_m, 1e-6)

    def test_a_fractional_corner_keeps_its_angle(self):
        a = math.radians(37.4)
        end = (12.0 * math.sin(a), 8.0 + 12.0 * math.cos(a), 0.0)  # leaves +Y, turns 37.4 deg right
        r = plan([(0.0, 0.0, 0.0), (0.0, 8.0, 0.0), end])
        self.assertAlmostEqual(r.pieces[1].angle_deg, 37.4, places=6)
        self.assertLess(r.end_error_m, 1e-5)

    def test_a_short_leg_takes_a_smaller_radius_or_is_refused(self):
        # 2.25 m between two 90-degree corners: 2 x 1.05 fits; 2.0 m needs 600 mm (2 x 0.85)
        r = plan([(0.0, 0.0, 0.0), (0.0, 5.0, 0.0), (2.0, 5.0, 0.0), (2.0, 10.0, 0.0)])
        self.assertIn("r600", [p.radius_id for p in r.pieces if p.kind == "CURVE"])
        with self.assertRaises(R.RouteError) as e:
            plan([(0.0, 0.0, 0.0), (0.0, 5.0, 0.0), (1.5, 5.0, 0.0), (1.5, 10.0, 0.0)])
        self.assertIn("point 2 to point 3", str(e.exception))

    def test_small_turns_merge_and_a_gentle_bend_keeps_a_corner(self):
        r = plan([(0.0, 0.0, 0.0), (0.0, 10.0, 0.0), (0.05, 20.0, 0.0)])
        self.assertEqual(kinds(r), ["STRAIGHT"])
        self.assertLess(r.end_error_m, 1e-6)
        arc = [(10.0 * math.sin(math.radians(k * 0.8)), 10.0 * (1 - math.cos(math.radians(k * 0.8))), 0.0) for k in range(0, 60)]
        arc = [(0.0, -5.0, 0.0)] + [(y, x, z) for x, y, z in arc]
        self.assertIn("CURVE", kinds(plan(arc)))

    def test_refusals(self):
        with self.assertRaises(R.RouteError):
            plan([(0.0, 0.0, 0.0)])
        with self.assertRaises(R.RouteError):
            plan([(0.0, 0.0, 0.0), (0.0, 0.0005, 0.0)])  # one point after dropping the duplicate
        with self.assertRaises(R.RouteError) as e:
            plan([(0.0, 0.0, 0.0), (0.0, 0.0, 3.0)])
        self.assertIn("vertically", str(e.exception))
        with self.assertRaises(R.RouteError) as e:
            plan([(0.0, 0.0, 0.0), (0.0, 10.0, 0.0), (0.0, 0.0, 0.0)])
        self.assertIn("U-turn", str(e.exception))


class InclineRouteTests(unittest.TestCase):
    def test_a_climb_to_the_end(self):
        r = plan([(0.0, 0.0, 0.0), (0.0, 10.0, 1.0)])
        self.assertEqual(kinds(r), ["STRAIGHT"])
        self.assertGreater(r.pieces[0].rise_m, 0.9)
        self.assertLess(r.end_error_m, 1e-5)

    def test_climb_then_turn_on_the_upper_level(self):
        r = plan([(0.0, 0.0, 0.0), (0.0, 10.0, 1.2), (10.0, 10.0, 1.2), (10.0, 20.0, 1.2)])
        self.assertEqual(kinds(r), ["STRAIGHT", "CURVE", "STRAIGHT", "CURVE", "STRAIGHT"])
        self.assertLess(r.end_error_m, 1e-5)
        self.assertGreater(r.max_pitch_deg, math.degrees(math.atan2(1.2, 10.0)))  # steeper than the polyline: it climbs between the curves

    def test_a_ramp_inside_a_straight_run(self):
        r = plan([(0.0, 0.0, 0.0), (0.0, 10.0, 0.0), (0.0, 16.0, 1.5), (0.0, 26.0, 1.5)])
        self.assertNotIn("CURVE", kinds(r))
        self.assertEqual(len(r.pieces), 3)
        self.assertLess(r.end_error_m, 1e-5)

    def test_hard_kinks_without_nose_over(self):
        r = plan([(0.0, 0.0, 0.0), (0.0, 10.0, 0.0), (0.0, 16.0, 1.5), (0.0, 26.0, 1.5)], transition_radius_m=0.0)
        self.assertAlmostEqual(r.pieces[1].rise_m, 1.5)
        self.assertLess(r.end_error_m, 1e-6)

    def test_incline_limits(self):
        with self.assertRaises(R.RouteError) as e:
            plan([(0.0, 0.0, 0.0), (0.0, 10.0, 1.0)], max_pitch_deg=0.0, type_label="Gravity roller")
        self.assertIn("cannot climb", str(e.exception))
        with self.assertRaises(R.RouteError) as e:
            plan([(0.0, 0.0, 0.0), (0.0, 6.0, 3.0)], max_pitch_deg=18.0, type_label="Belt")
        self.assertIn("limit 18", str(e.exception))
        self.assertLess(plan([(0.0, 0.0, 0.0), (0.0, 10.0, 1.0)], max_pitch_deg=18.0).end_error_m, 1e-5)
        self.assertLess(plan([(0.0, 0.0, 0.0), (0.0, 10.0, 0.0)], max_pitch_deg=0.0).end_error_m, 1e-6)  # flat is fine

    def test_too_short_to_climb(self):
        with self.assertRaises(R.RouteError) as e:
            plan([(0.0, 0.0, 0.0), (0.0, 1.0, 0.5), (5.0, 1.0, 0.5)])
        self.assertIn("point 1 to point 2", str(e.exception))


if __name__ == "__main__":
    unittest.main()
