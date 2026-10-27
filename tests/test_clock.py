import unittest

from model.clock import crossing_phase_op_s, stream_phase_scene_s


class ClockTests(unittest.TestCase):
    def test_round_trip_at_an_out_port(self):
        # Frame start 1 at 24 fps, clock x4, 0.2 m/s, slots 14.4 m apart (50/h), tote inset 0.3 m.
        t_start, scale, v, A, inset = 1 / 24.0, 4.0, 0.2, 14.4, 0.3
        for phase_op in (0.0, 10.0, 60.0):
            phi = stream_phase_scene_s(t_start, phase_op, scale, inset, 0.0, v, A)
            self.assertGreaterEqual(phi, 0.0)
            self.assertLess(phi, A / (v * scale))
            got, period = crossing_phase_op_s(phi, t_start, scale, inset, 0.0, v, A)
            self.assertAlmostEqual(period, A / v)  # 72 operation seconds = 50/h
            self.assertAlmostEqual(got % period, phase_op % period, places=6)

    def test_in_port_phase_moves_with_the_port_position(self):
        t_start, scale, v, A, inset = 0.0, 1.0, 0.5, 10.0, 0.3
        p0, period = crossing_phase_op_s(0.0, t_start, scale, inset, 10.3, v, A)
        p1, _ = crossing_phase_op_s(0.0, t_start, scale, inset, 15.3, v, A)
        self.assertAlmostEqual(period, 20.0)
        self.assertAlmostEqual((p1 - p0) % period, 10.0)  # 5 m further at 0.5 m/s


if __name__ == "__main__":
    unittest.main()
