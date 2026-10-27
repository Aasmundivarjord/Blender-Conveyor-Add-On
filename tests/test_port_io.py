"""io ports of a crane aisle served by one conveyor (model/port_io.py).
Pure Python: python3 -m unittest tests/test_port_io.py"""
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


P = _load("port_io", "model/port_io.py")

IO_PORT = {"id": "aisle0_io", "role": "io", "heading_deg": 90.0, "heading_in_deg": 270.0, "rate_ph": 45.0, "rate_in_ph": 40.0, "capacity_ph": 85.0}
OUT_PORT = {"id": "aisle0_out", "role": "out", "heading_deg": 90.0, "rate_ph": 45.0, "capacity_ph": 45.0}
IN_PORT = {"id": "aisle0_in", "role": "in", "heading_deg": 270.0, "rate_ph": 40.0, "capacity_ph": 40.0}


class PortIoTests(unittest.TestCase):
    def test_io_serves_both_roles(self):
        self.assertTrue(P.accepts(IO_PORT, "out") and P.accepts(IO_PORT, "in"))
        self.assertTrue(P.accepts(OUT_PORT, "out") and not P.accepts(OUT_PORT, "in"))
        self.assertTrue(P.accepts(IN_PORT, "in") and not P.accepts(IN_PORT, "out"))

    def test_headings_per_role(self):
        self.assertEqual(P.heading_deg(IO_PORT, "out"), 90.0)  # goods leave along heading_deg
        self.assertEqual(P.heading_deg(IO_PORT, "in"), 270.0)  # goods arrive along heading_in_deg
        self.assertEqual(P.body_heading_deg(IO_PORT, "out"), 90.0)  # an out line's body leaves with the goods
        self.assertEqual(P.body_heading_deg(IO_PORT, "in"), 450.0)  # an in line's body points back along heading_in_deg + 180
        self.assertEqual(P.heading_deg(IN_PORT, "in"), 270.0)  # a plain in port already points inward
        self.assertEqual(P.body_heading_deg(IN_PORT, "in"), 450.0)
        self.assertEqual(P.heading_deg({"role": "out"}, "out"), 0.0)

    def test_rates_per_role(self):
        self.assertEqual(P.rate_ph(IO_PORT, "out"), 45.0)
        self.assertEqual(P.rate_ph(IO_PORT, "in"), 40.0)
        self.assertEqual(P.rate_ph(IN_PORT, "in"), 40.0)  # no rate_in_ph: rate_ph is the in rate
        self.assertEqual(P.rate_ph({"role": "io", "rate_ph": "x"}, "out"), 0.0)

    def test_link_role_is_the_lines(self):
        self.assertEqual(P.link_role("in"), "in")
        self.assertEqual(P.link_role("out"), "out")
        self.assertEqual(P.link_role("io"), "out")  # never "io"


class LoadKindTests(unittest.TestCase):
    """R19: a conveyor carries known kinds only; an unknown one is refused, never a crash."""

    def test_kinds(self):
        for kind in ("pallet", "tote", "carton", "item", "custom"):
            self.assertTrue(P.carries_load({"kind": kind, "id": "x"}), kind)
        self.assertFalse(P.carries_load({"kind": "long", "id": "long:pipe:6000"}))
        self.assertFalse(P.carries_load({"kind": "spaceship"}))
        self.assertTrue(P.carries_load({"id": "legacy"}))  # an older record without a kind
        self.assertTrue(P.carries_load(None))
        self.assertNotIn("long", P.CARRIED_KINDS)
        self.assertEqual(P.load_kind({"kind": "long"}), "long")


class R22ReaderTests(unittest.TestCase):
    """Round 8 (R22): ports may publish population / speed_m_s / max_population /
    population_in / master instead of rates; readers must never require the rate keys."""
    PALLETS = {"role": "out", "population": 0.5, "speed_m_s": 0.2, "load": {"kind": "pallet", "length_m": 1.2}}

    def test_population_stands_in_for_a_missing_rate(self):
        # one pallet every (1.2 + 0.05) / 0.5 = 2.5 m at 0.2 m/s: 288 an hour
        self.assertAlmostEqual(P.rate_ph(self.PALLETS, "out"), 288.0)
        self.assertAlmostEqual(P.rate_ph({"role": "out", "population": 0.5}, "out", item_length_m=1.2, speed_m_s=0.2), 288.0)
        self.assertEqual(P.rate_ph({"role": "out", "population": 0.5}, "out"), 0.0)  # no length or speed: no guess
        self.assertEqual(P.rate_ph({"role": "out"}, "out"), 0.0)  # nothing published: nothing, never a crash

    def test_a_published_population_wins_over_a_rate(self):
        # R22.5 (warehouse_common 0.6.3's precedence): a stale legacy rate never overrides the
        # population the port publishes -- not even a population of 0 (a stopped source)
        self.assertAlmostEqual(P.rate_ph(dict(self.PALLETS, rate_ph=16.5), "out"), 288.0)
        self.assertEqual(P.rate_ph(dict(self.PALLETS, population=0.0, rate_ph=16.5), "out"), 0.0)
        self.assertAlmostEqual(P.rate_ph(dict(self.PALLETS, rate_ph=0), "out"), 288.0)
        io = {"role": "io", "population": 0.5, "population_in": 0.25, "rate_ph": 9.0, "rate_in_ph": 7.0, "speed_m_s": 0.2,
              "load": {"length_m": 1.2}}
        self.assertAlmostEqual(P.rate_ph(io, "in"), 144.0)
        self.assertAlmostEqual(P.rate_ph(io, "out"), 288.0)

    def test_a_rate_stands_in_only_without_a_population(self):
        legacy = {"role": "out", "rate_ph": 30.0, "speed_m_s": 0.2, "load": {"length_m": 1.2}}
        self.assertEqual(P.rate_ph(legacy, "out"), 30.0)
        self.assertEqual(P.rate_ph({"role": "io", "rate_ph": 45.0, "rate_in_ph": 40.0}, "in"), 40.0)
        self.assertEqual(P.rate_ph(dict(legacy, rate_ph=0), "out"), 0.0)  # 0 = not known

    def test_io_ports_and_limits(self):
        io = {"role": "io", "population": 0.5, "population_in": 0.25, "speed_m_s": 0.2, "load": {"length_m": 1.2}}
        self.assertAlmostEqual(P.rate_ph(io, "in"), 144.0)
        self.assertAlmostEqual(P.rate_ph(io, "out"), 288.0)
        self.assertEqual(P.population(io, "in"), 0.25)
        self.assertEqual(P.population({"population": 7}, "out"), 1.0)  # clamped
        sink = {"role": "in", "max_population": 0.1, "speed_m_s": 0.5}
        self.assertAlmostEqual(P.capacity_ph(sink, item_length_m=0.6), 3600.0 * 0.1 * 0.5 / 0.65)
        self.assertAlmostEqual(P.capacity_ph({"capacity_ph": 52.0, "max_population": 0.1, "speed_m_s": 0.5}, item_length_m=0.6),
                               3600.0 * 0.1 * 0.5 / 0.65)  # R22.5: the published max_population wins
        self.assertEqual(P.capacity_ph({"capacity_ph": 52.0}), 52.0)  # a legacy capacity stands in without one
        self.assertEqual(P.capacity_ph({"role": "in"}), 0.0)

    def test_speed_master_share(self):
        self.assertEqual(P.goods_speed_m_s({"speed_m_s": 0.3, "surface_speed_m_s": 0.5}), 0.3)
        self.assertEqual(P.goods_speed_m_s({"surface_speed_m_s": 0.5}), 0.5)
        self.assertIsNone(P.goods_speed_m_s({"speed_m_s": 0}))
        self.assertTrue(P.is_master({"master": True}))
        self.assertFalse(P.is_master({"master": "yes"}))  # true means the JSON true
        self.assertFalse(P.is_master({}))
        self.assertEqual(P.link_share({"share": 0.3}), 0.3)
        self.assertIsNone(P.link_share({"rate_ph": 30}))


if __name__ == "__main__":
    unittest.main()
