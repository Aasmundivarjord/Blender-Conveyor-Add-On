"""The public operators' decisions (model/public_api.py, contract v2.1 R6) and the
vendored operator_exists (R7). Pure Python: python3 -m unittest tests.test_public_api (from dev/)."""
import json
import unittest

from _wh import ops
from model.public_api import (flow_plan, forward_axis, geometric_anchor, parse_load, placeholder_dims, population_pct_for_rate,
                              population_plan, rate_plan)


class AnchorTests(unittest.TestCase):
    def test_start_is_the_origin_forward(self):
        self.assertEqual(geometric_anchor("start", True, True), ("origin", False))

    def test_end_takes_the_far_end_when_the_origin_is_taken(self):
        self.assertEqual(geometric_anchor("end", False, True), ("end", False))

    def test_end_on_a_free_line_reverses_it_at_the_origin(self):
        self.assertEqual(geometric_anchor("end", False, False), ("origin", True))
        self.assertEqual(geometric_anchor("end", True, True), ("origin", True))


class SetLineFlowTests(unittest.TestCase):
    """conveyor.set_line_flow (contract R22 / R22.3): Population 0..1, Speed m/s, a branch's Share of the master."""
    NOW = {"population_pct": 50.0, "speed_m_s": 0.5, "share_pct": 0}

    def test_sets_what_it_is_given(self):
        writes, setting, problems = flow_plan(self.NOW, 0.4, 0.8, 0.3, True)
        self.assertEqual(writes, {"population_pct": 40.0, "speed_m_s": 0.8, "share_pct": 30})
        self.assertEqual(setting, {"population": 0.4, "speed_m_s": 0.8, "share": 0.3})
        self.assertEqual(problems, [])

    def test_negative_leaves_it(self):
        self.assertEqual(flow_plan(self.NOW, -1.0, -1.0, -1.0, True), ({}, {}, []))
        writes, setting, _p = flow_plan(self.NOW, -1.0, 0.7, -1.0, False)
        self.assertEqual((writes, setting), ({"speed_m_s": 0.7}, {"speed_m_s": 0.7}))

    def test_the_same_again_writes_nothing(self):
        writes, setting, problems = flow_plan(self.NOW, 0.5, 0.5, -1.0, False)
        self.assertEqual(writes, {})
        self.assertEqual(setting, {"population": 0.5, "speed_m_s": 0.5})

    def test_share_is_a_branchs(self):
        writes, setting, problems = flow_plan(self.NOW, -1.0, -1.0, 0.3, False)
        self.assertEqual((writes, setting), ({}, {}))
        self.assertTrue(problems and "branch" in problems[0])

    def test_out_of_range(self):
        writes, setting, problems = flow_plan(self.NOW, 1.5, -1.0, 2.0, True)
        self.assertEqual((writes, setting), ({}, {}))
        self.assertEqual(len(problems), 2)


class PopulationShimTests(unittest.TestCase):
    """set_line_rate since 2.22 (round 8): a rate becomes the Population that carries it."""

    def test_rate_as_population(self):
        # 900/h of 0.6 m totes at 0.5 m/s: 900 x 0.65 / 1800 = 32.5 %
        self.assertAlmostEqual(population_pct_for_rate(900.0, 0.6, 0.5), 32.5)
        self.assertEqual(population_pct_for_rate(20000.0, 0.6, 0.5), 100.0)  # more than fits: full
        self.assertEqual(population_pct_for_rate(0.0, 0.6, 0.5), 0.0)

    def test_set_keeps_the_own_population(self):
        pct, rec, changed = population_plan(None, 50.0, 900.0, 0.6, 0.5)
        self.assertAlmostEqual(pct, 32.5)
        self.assertEqual(rec, {"rate_ph": 900.0, "own_pct": 50.0})
        self.assertTrue(changed)

    def test_same_rate_again_changes_nothing(self):
        rec = {"rate_ph": 900.0, "own_pct": 50.0, "by": "warehouse_racks"}
        self.assertEqual(population_plan(rec, 32.5, 900.0, 0.6, 0.5), (None, rec, False))

    def test_zero_gives_the_own_population_back(self):
        self.assertEqual(population_plan({"rate_ph": 900.0, "own_pct": 50.0}, 32.5, 0.0, 0.6, 0.5), (50.0, None, True))
        self.assertEqual(population_plan(None, 32.5, 0.0, 0.6, 0.5), (None, None, False))


class RateTests(unittest.TestCase):
    def test_set_keeps_the_own_setting(self):
        self.assertEqual(rate_plan(None, 120, 45.0), (45, {"rate_ph": 45, "own_ph": 120}, True))

    def test_same_rate_again_changes_nothing(self):
        rec = {"rate_ph": 45, "own_ph": 120, "by": "warehouse_racks"}
        self.assertEqual(rate_plan(rec, 45, 45.0), (None, rec, False))

    def test_a_new_rate_keeps_the_original_own_setting(self):
        self.assertEqual(rate_plan({"rate_ph": 45, "own_ph": 120}, 45, 60.4), (60, {"rate_ph": 60, "own_ph": 120}, True))

    def test_zero_releases(self):
        self.assertEqual(rate_plan({"rate_ph": 45, "own_ph": 120}, 45, 0.0), (120, None, True))
        self.assertEqual(rate_plan({"rate_ph": 45, "own_ph": 45}, 45, 0.0), (None, None, True))  # same value: record goes, no write
        self.assertEqual(rate_plan(None, 45, 0.0), (None, None, False))

    def test_user_edit_under_an_external_rate_is_put_back(self):
        self.assertEqual(rate_plan({"rate_ph": 45, "own_ph": 120}, 70, 45.0), (45, {"rate_ph": 45, "own_ph": 120}, True))


class LoadTests(unittest.TestCase):
    def test_parse(self):
        load = {"kind": "pallet", "id": "pallet:EUR1:Wood:1.2", "length_m": 1.2, "forward_axis": "X"}
        self.assertEqual(parse_load(json.dumps(load)), load)
        self.assertEqual(parse_load(load), load)
        self.assertIsNone(parse_load("{}"))
        self.assertIsNone(parse_load('{"id": " "}'))
        self.assertIsNone(parse_load("not json"))
        self.assertIsNone(parse_load("[1, 2]"))

    def test_placeholder_dims_and_axis(self):
        self.assertEqual(placeholder_dims({"length_m": 1.2, "width_m": 0.8, "height_m": 1.0}), (1.2, 0.8, 1.0))
        self.assertEqual(placeholder_dims({"length_m": "x"}), (0.6, 0.4, 0.3))
        self.assertEqual(forward_axis({"forward_axis": "x"}), "X")
        self.assertEqual(forward_axis({"forward_axis": "-Y"}), "NEG_Y")
        self.assertIsNone(forward_axis({"forward_axis": "AUTO"}))
        self.assertIsNone(forward_axis({}))


class OperatorExistsTests(unittest.TestCase):
    """R7: hasattr on bpy.ops is always True; the vendored check uses dir()."""

    def test_registry_lookup(self):
        class Module:
            def __init__(self, names):
                self._names = names

            def __dir__(self):
                return self._names

        class Ops:
            def __getattr__(self, name):  # like bpy.ops: a proxy for ANY module name
                return Module(["make_load"] if name == "warehouse" else [])

        self.assertTrue(hasattr(Ops(), "nothing"))  # the trap
        self.assertTrue(ops.operator_exists(Ops(), "warehouse.make_load"))
        self.assertFalse(ops.operator_exists(Ops(), "warehouse.nothing"))
        self.assertFalse(ops.operator_exists(Ops(), "nothing.make_load"))
        self.assertFalse(ops.operator_exists(Ops(), "make_load"))


if __name__ == "__main__":
    unittest.main()
