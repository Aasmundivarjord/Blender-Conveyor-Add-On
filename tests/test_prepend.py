"""model/segments.prepend_pose: putting a piece in front of a line's first
one must leave everything already built where it is. Pure Python:
python3 -m unittest tests/test_prepend.py"""
import importlib
import importlib.util
import math
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if "model" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("model", ROOT / "model" / "__init__.py", submodule_search_locations=[str(ROOT / "model")])
    _model = importlib.util.module_from_spec(_spec)
    sys.modules["model"] = _model
    _spec.loader.exec_module(_model)
S = importlib.import_module("model.segments")


def world(x, y, z, yaw, px, py, pz):
    c, s = math.cos(yaw), math.sin(yaw)
    return (x + c * px - s * py, y + s * px + c * py, z + pz)


class Prepend(unittest.TestCase):
    def check(self, loc, yaw, end):
        """The new piece's end (local, new frame) lands on the old origin with the old yaw."""
        x, y, z, yaw2 = S.prepend_pose(*loc, yaw, *end)
        self.assertAlmostEqual(yaw2 + end[3], yaw, places=9)
        for a, b in zip(world(x, y, z, yaw2, end[0], end[1], end[2]), loc):
            self.assertAlmostEqual(a, b, places=9)

    def test_straight_moves_the_origin_straight_back(self):
        x, y, z, yaw = S.prepend_pose(10.0, 5.0, 0.7, 0.0, 0.0, 3.0, 0.0, 0.0)
        self.assertEqual((round(x, 9), round(y, 9), round(z, 9), yaw), (10.0, 2.0, 0.7, 0.0))

    def test_reanchor(self):
        loc, yaw = (4.0, -1.0, 0.7), 0.4
        same = S.reanchor_pose(*loc, yaw, (1.0, 2.0, 0.1, 0.3), (1.0, 2.0, 0.1, 0.3))
        for a, b in zip(same, loc + (yaw,)):
            self.assertAlmostEqual(a, b)
        old, new = (0.0, 3.0, 0.0, 0.0), (-1.05, 1.05, 0.0, math.pi / 2)  # a 3 m straight turned into a 90° left curve
        x, y, z, yaw2 = S.reanchor_pose(*loc, yaw, old, new)
        for a, b in zip(world(x, y, z, yaw2, *new[:3]), world(*loc, yaw, *old[:3])):
            self.assertAlmostEqual(a, b, places=9)
        self.assertAlmostEqual(yaw2 + new[3], yaw + old[3])

    def test_curves_and_rises(self):
        r = 1.05
        self.check((10.0, 5.0, 0.7), 0.0, (-r, r, 0.0, math.pi / 2))  # a 90° left curve ends at (-r, r) heading +90°
        self.check((3.0, -2.0, 1.0), 0.6, (r, r, 0.0, -math.pi / 2))  # right curve on a rotated line
        self.check((3.0, -2.0, 1.0), -2.2, (0.0, 2.5, 0.4, 0.0))  # a rising straight
        self.check((0.0, 0.0, 0.0), 1.0, (0.3, 1.2, -0.2, 0.7))


if __name__ == "__main__":
    unittest.main()
