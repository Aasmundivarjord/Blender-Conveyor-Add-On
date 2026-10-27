"""The stop on a right-angle transfer (model/transfer_motion.py).
python3 -m unittest tests.test_transfer_motion (from dev/)."""
import unittest

from model import transfer_motion as M


class StopTests(unittest.TestCase):
    def test_continuous_and_stopping_on_the_centre(self):
        c, a, h = 5.0, 0.08, 0.25
        xs = [4.0 + k * 0.001 for k in range(3001)]
        ys = [M.shown(x, c, a, h) for x in xs]
        self.assertTrue(all(abs(y1 - y0) <= 0.0011 for y0, y1 in zip(ys, ys[1:])))  # no jumps
        self.assertTrue(all(y1 >= y0 - 1e-12 for y0, y1 in zip(ys, ys[1:])))  # never backwards
        self.assertAlmostEqual(M.shown(c + a, c, a, h), c)  # arrives with speed 0
        self.assertAlmostEqual(M.shown(c + a + h, c, a, h), c)  # stands the whole hold
        self.assertAlmostEqual(M.shown(c - a, c, a, h), c - a)  # unchanged until it starts slowing
        self.assertAlmostEqual(M.shown(10.0, c, a, h), 10.0 - M.lag_m(a, h))

    def test_speed_profile(self):
        c, a, h = 0.0, 0.1, 0.2
        dv = lambda x: (M.shown(x + 1e-6, c, a, h) - M.shown(x - 1e-6, c, a, h)) / 2e-6
        self.assertAlmostEqual(dv(c - a + 1e-4), 1.0, places=2)  # full speed into the slow-down
        self.assertAlmostEqual(dv(c), 0.5, places=2)  # half way down
        self.assertAlmostEqual(dv(c + a + h / 2), 0.0, places=6)  # standing
        self.assertAlmostEqual(dv(c + 3 * a + h - 1e-4), 1.0, places=2)  # back to speed

    def test_timings(self):
        self.assertAlmostEqual(M.turn_m(1.0, 'BELT'), 0.3)  # the 0.3 s lift (Interroll RM 8731)
        self.assertAlmostEqual(M.hold_m(0.5, 'BELT'), 0.25)
        self.assertGreater(M.hold_m(0.2, 'CHAIN'), M.hold_m(0.2, 'BELT'))  # pallets lift slower
        self.assertAlmostEqual(M.ease_m(0.5, 'BELT'), 0.25 / 3.0)
        self.assertEqual(M.ease_m(3.0, 'BELT'), M.EASE_MAX_M)
        self.assertEqual(M.timing('UNKNOWN'), M.TIMING['BELT'])

    def test_pitch_and_padding(self):
        self.assertAlmostEqual(M.min_pitch_m(0.6 + 0.4, 0.08, 0.25), 1.0 + 0.41 + M.CLEARANCE_M)  # a 600 x 400 tote
        self.assertEqual(M.extra_slots(0.0, 1.0), 0)
        self.assertEqual(M.extra_slots(0.41, 1.0), 1)
        self.assertEqual(M.extra_slots(2.0, 1.0), 2)


if __name__ == "__main__":
    unittest.main()
