"""Population from the settings a line was saved with before the simple-flow
switch (model/flow_migration.py, 2.22.0). Pure Python:
python3 -m unittest tests/test_flow_migration.py"""
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


M = _load("flow_migration", "model/flow_migration.py")


class FlowMigrationTests(unittest.TestCase):
    def test_spacing_and_fill(self):
        # The default line: 800 mm spacing, 600 mm totes, Fill 100 %: 0.65 / 0.8.
        pitch = M.old_pitch_m(0.5, 0, 0.8, 1.0, 0.605)
        self.assertAlmostEqual(pitch, 0.8)
        self.assertAlmostEqual(M.populations(pitch, [0.6], [])[0], 0.8125)
        # Fill 50 % thinned the slots: half the population.
        self.assertAlmostEqual(M.populations(M.old_pitch_m(0.5, 0, 0.8, 0.5, 0.605), [0.6], [])[0], 0.40625)

    def test_throughput_at_speed(self):
        # 1800/h at 0.5 m/s: one item a metre.
        pitch = M.old_pitch_m(0.5, 1800, 0.8, 1.0, 0.605)
        self.assertAlmostEqual(pitch, 1.0)
        self.assertAlmostEqual(M.populations(pitch, [0.6], [])[0], 0.65)
        # More than the speed carries: the floor held it nose to tail, so it is full.
        self.assertAlmostEqual(M.populations(M.old_pitch_m(0.5, 20000, 0.8, 1.0, 0.605), [0.6], [])[0], 1.0)

    def test_feeders_keep_their_share_of_the_slots(self):
        # One feeder at 30 %, one at 0 (auto): the main and the auto feeder split the other 70 %.
        self.assertEqual(M.owner_weights_pct([30, 0]), [35.0, 30.0, 35.0])
        pops = M.populations(1.0, [0.6, 0.6, 0.4], [30, 0])
        self.assertAlmostEqual(pops[0], 0.35 * 0.65)
        self.assertAlmostEqual(pops[1], 0.30 * 0.65)
        self.assertAlmostEqual(pops[2], 0.35 * 0.45)
        # Shares above 100 % were scaled down together.
        self.assertEqual(M.owner_weights_pct([80, 80]), [0.0, 50.0, 50.0])

    def test_buffer_out_rate_becomes_output_pct(self):
        # round 8: "Manual buffer Out rates become Output % from the rate ratio where possible, else 100 %"
        self.assertEqual(M.buffer_out_pct('MANUAL', 300.0, 1200.0), 25)
        self.assertEqual(M.buffer_out_pct('MANUAL', 1500.0, 1200.0), 100)  # more out than in: everything passes
        self.assertEqual(M.buffer_out_pct('MANUAL', 300.0, 0.0), 100)  # nothing arrives: no ratio
        self.assertEqual(M.buffer_out_pct('AUTO', 300.0, 1200.0), 100)  # Auto (the next machine): 100 %

    def test_no_pitch(self):
        self.assertEqual(M.populations(0.0, [0.6, 0.6], [0]), [0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
