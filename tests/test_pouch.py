"""The pouch sorter's figures (model/pouch.py). Pure Python:
python3 -m unittest tests/test_pouch.py"""
import importlib.util
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


P = _load("pouch", "model/pouch.py")


class PouchTests(unittest.TestCase):
    def test_standard_sizes_and_custom(self):
        self.assertEqual(P.pouch_dims_mm("STD_400_600", 0.0, 0.0, 120.0), (400.0, 600.0, 120.0))
        self.assertEqual(P.pouch_dims_mm("STD_300_450", 999.0, 999.0, 80.0), (300.0, 450.0, 80.0))  # a standard ignores the custom fields
        self.assertEqual(P.pouch_dims_mm("CUSTOM", 350.0, 550.0, 100.0), (350.0, 550.0, 100.0))
        self.assertEqual(P.pouch_dims_mm("CUSTOM", 10.0, 10.0, 1.0), (50.0, 50.0, 10.0))  # floors
        ids = [i[0] for i in P.size_items()]
        self.assertEqual(ids[0], P.DEFAULT_SIZE)
        self.assertEqual(ids[-1], P.CUSTOM)

    def test_pitch_keeps_the_pouches_apart(self):
        self.assertEqual(P.pitch_mm(120.0, 250.0), 250.0)
        self.assertEqual(P.pitch_mm(300.0, 250.0), 330.0)  # deep pouches: pitch follows depth + gap

    def test_goods_pitch_is_whole_pouches(self):
        self.assertAlmostEqual(P.quantize_m(0.25, 0.25), 0.25)
        self.assertAlmostEqual(P.quantize_m(0.3, 0.25), 0.5)  # one item every second pouch
        self.assertAlmostEqual(P.quantize_m(1.9, 0.25), 2.0)
        self.assertAlmostEqual(P.quantize_m(0.1, 0.25), 0.25)  # never closer than one per pouch

    def test_items_sit_inside_the_pouch(self):
        drop = P.item_drop_m(0.6)
        bottom = -(P.RAIL_H_M + P.TROLLEY_H_M + P.HOOK_M + 0.6)  # the pouch's bottom below the rail top
        self.assertAlmostEqual(drop, bottom + P.ITEM_LIFT_M)
        self.assertLess(drop, -0.7)

    def test_line_values(self):
        v = P.line_values("STD_400_600", 0.0, 0.0, 120.0, 250.0, lambda mm: mm / 1000.0)
        self.assertAlmostEqual(v["Pouch Width"], 0.4)
        self.assertAlmostEqual(v["Pouch Pitch"], 0.25)
        self.assertFalse(v["Guide Rails"])
        self.assertAlmostEqual(v["Rail Top Drop"], 0.0)
        self.assertAlmostEqual(v["Height Offset"], P.item_drop_m(0.6))


if __name__ == "__main__":
    unittest.main()
