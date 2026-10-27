"""Invariants of the fork-column lift (model/lift_parts.py, model/segments
lift path). Pure Python: python3 -m unittest tests/test_lift_parts.py"""
import importlib
import importlib.util
import math
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("model", ROOT / "model" / "__init__.py", submodule_search_locations=[str(ROOT / "model")])
_model = importlib.util.module_from_spec(_spec)
sys.modules["model"] = _model
_spec.loader.exec_module(_model)
S = importlib.import_module("model.segments")
L = importlib.import_module("model.lift_parts")
T = importlib.import_module("model.transfer_parts")
FRAME = T.Frame(width=0.5, roller_r=0.024, pitch=0.052)


def _poly_len(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


class Lift(unittest.TestCase):
    def test_loop(self):
        for h in (0.3, 1.0, 3.0, 8.0):
            lay = L.lift_layout(h, 'Z')
            self.assertAlmostEqual(lay.z_top, h + S.LIFT_PICK_CLEAR)
            loop = L.fork_loop(lay, lay.y_pick, lay.y_drop)
            self.assertEqual(loop[0], loop[-1], "the loop closes")
            self.assertAlmostEqual(_poly_len(loop), lay.loop_length, delta=0.003 * lay.loop_length)
            self.assertAlmostEqual(loop[0][0], lay.y_c)  # the seam: the bottom apex under the column centre
            self.assertAlmostEqual(loop[0][1], lay.z_bot - L.R)
            # The pick corner's loop coordinate lands on the up-leg at the infeed height.
            l_pick = L.pick_loop_coord(lay, 0.0)
            acc, pos = 0.0, None
            for a, b in zip(loop, loop[1:]):
                d = math.hypot(b[0] - a[0], b[1] - a[1])
                if acc + d >= l_pick:
                    t = (l_pick - acc) / d
                    pos = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                    break
                acc += d
            self.assertAlmostEqual(pos[0], lay.y_pick, delta=0.01)
            self.assertAlmostEqual(pos[1], 0.0, delta=0.01)

    def test_path_through_the_chain(self):
        for shape in ('Z', 'C'):
            lay = L.lift_layout(3.0, shape)
            lift = S.lift_module(3.0, shape, lay.z_top)
            self.assertAlmostEqual(lift.length_m, lay.path_length)
            chain = [S.Straight(1.0), lift, S.Straight(1.0)]
            spine = S.evaluate_chain(chain, S.Pose(0, 0, 0, 0, 0), 0.5)
            self.assertAlmostEqual(spine.length, 2.0 + lift.length_m, places=6)
            end = spine.pose_at(len(spine) - 1)
            self.assertAlmostEqual(end.z, 3.0, places=6)
            if shape == 'Z':
                self.assertAlmostEqual(end.y, 1.0 + S.LIFT_LEN + 1.0, places=6)
                self.assertAlmostEqual(end.heading, 0.0, places=6)
            else:
                self.assertAlmostEqual(end.y, 0.0, places=6)
                self.assertAlmostEqual(abs(end.heading), math.pi, places=6)
            self.assertAlmostEqual(max(spine.z), lay.z_top + S.LIFT_R, places=6)
            # The goods never leave the module's footprint sideways and stay level (KIND_LIFT).
            lift_pts = [k for k in range(len(spine)) if spine.segment_index[k] == 1]
            self.assertTrue(all(spine.kind[k] == S.KIND_LIFT for k in lift_pts))
            self.assertTrue(all(abs(spine.x[k]) < 1e-9 for k in lift_pts))

    def test_tines_pass_between_the_comb_rollers(self):
        for shape in ('Z', 'C'):
            lay = L.lift_layout(2.0, shape)
            parts = L.lift_parts(lay, FRAME, 'LEFT')
            rollers = [p for p in parts if p.kind == T.ROLLER]
            self.assertGreater(len(rollers), 12)
            for z in (0.0, 2.0):
                ys = sorted(p.points[0][1] for p in rollers if abs(p.points[0][2] - (z - L.COMB_R)) < 1e-9)
                self.assertTrue(ys, f"{shape}: no comb at {z}")
                self.assertTrue(all(b - a >= L.TINE_PITCH - 1e-9 for a, b in zip(ys, ys[1:])))
                for leg in lay.legs:
                    for t in L.tine_stations(leg):
                        self.assertTrue(all(abs(t - y) >= L.TINE_PITCH / 2.0 - 1e-9 for y in ys), f"{shape}: tine at {t} hits a roller")

    def test_column_and_forks_sit_beside_the_bed(self):
        lay = L.lift_layout(2.0, 'Z')
        for side, sign in (('LEFT', -1.0), ('RIGHT', 1.0)):
            face, reach = L.fork_offsets(FRAME.width, side)
            self.assertGreater(sign * face, FRAME.width / 2.0)  # the face is outside the bed, on its side
            tip = face - sign * L.TINE_ROOT + reach
            self.assertAlmostEqual(tip, -sign * (FRAME.width / 2.0 - L.TINE_END))  # tines end short of the far edge
            cx, cy, top = L.column_centre(lay, FRAME, side)
            self.assertGreater(sign * cx, FRAME.width / 2.0)
            self.assertAlmostEqual(cy, lay.y_c)
            self.assertGreater(top, lay.z_top + L.R)
            parts = L.lift_parts(lay, FRAME, side)
            self.assertEqual(len([p for p in parts if p.kind == T.BOX and p.mat == T.MAT_ACCENT and p.h > 1.0]), 2, "two corner posts")
            for p in parts:
                for x, _y, _z in p.points:
                    self.assertLessEqual(-sign * x, FRAME.width / 2.0 + 0.05, "nothing sticks out on the far side")


if __name__ == "__main__":
    unittest.main()
