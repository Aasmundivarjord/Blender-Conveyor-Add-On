"""Invariants of the pallet wrapper layout (model/wrapper_parts.py).
Pure Python: python3 -m unittest tests/test_wrapper_parts.py"""
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel, submodule_search_locations=[])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


T = _load("model.transfer_parts", "model/transfer_parts.py")
sys.modules.setdefault("model", type(sys)("model"))
sys.modules["model"].transfer_parts = T
W = _load("model.wrapper_parts", "model/wrapper_parts.py")


class WrapperTests(unittest.TestCase):
    def test_turntable_scales_with_the_line(self):
        self.assertAlmostEqual(W.table_radius(0.5), W.TABLE_MIN_R)  # a tote line still gets the smallest unit
        self.assertAlmostEqual(W.table_radius(1.26), 1.008)  # a pallet line: a 2 m table (Lantech Q: 81 in)
        self.assertGreater(W.module_length(1.26), 2.0 * W.table_radius(1.26))

    def test_parts_stay_inside_the_footprint_and_the_mast_clears_the_table(self):
        f = T.Frame(width=1.26, roller_r=0.03, pitch=0.1)
        length = W.module_length(1.26)
        parts, fences = W.wrapper_parts(length, f, "WRAP")
        self.assertEqual(fences, [])
        R = W.table_radius(1.26)
        for p in parts:
            for _x, y, _z in p.points:
                self.assertGreaterEqual(y, -1e-9)
                self.assertLessEqual(y, length + 1e-9)
        mast = [p for p in parts if p.kind == T.BOX and p.h > 2.5][0]
        self.assertGreater(abs(mast.points[0][0]) - W.MAST_D / 2.0, R)  # the mast stands clear of the turntable
        self.assertGreaterEqual(mast.points[0][2] + mast.h / 2.0, W.WRAP_H)  # and reaches the wrap height
        rolls = [p for p in parts if p.kind == T.ROLLER and abs(p.r - W.ROLL_R) < 1e-9]
        self.assertEqual(len(rolls), 1)

    def test_unwrapper_carries_a_knife_not_a_roll(self):
        f = T.Frame(width=1.06, roller_r=0.03, pitch=0.1)
        parts, _ = W.wrapper_parts(W.module_length(1.06), f, "UNWRAP")
        self.assertFalse([p for p in parts if p.kind == T.ROLLER and abs(p.r - W.ROLL_R) < 1e-9])
        self.assertTrue([p for p in parts if p.kind == T.BOX and p.mat == T.MAT_ACCENT and p.h < 0.1])


if __name__ == "__main__":
    unittest.main()
