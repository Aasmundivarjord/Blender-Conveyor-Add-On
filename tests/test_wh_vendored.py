"""The vendored warehouse_common copy (_wh/, contract v2.1 decision D3) is
untouched and current, and the pieces this add-on relies on behave as the
contract says. Pure Python: python3 -m unittest tests.test_wh_vendored (from dev/)."""
import json
import pathlib
import unittest

import _wh
from _wh import levels, records, selfcheck

ROOT = pathlib.Path(__file__).resolve().parents[1]


class VendoredCopyTests(unittest.TestCase):
    def test_untouched(self):
        self.assertEqual(selfcheck.modified_files(), [])

    def test_manifest_matches_the_source_version(self):
        data = json.loads((ROOT / "_wh" / "VENDORED.json").read_text(encoding="utf-8"))
        self.assertEqual(data["version"], _wh.VERSION)
        self.assertEqual(data["contract"], "2.1")
        self.assertEqual(data["source"], "warehouse_common")


class RecordTests(unittest.TestCase):
    """R2: readers take a JSON string or an IDProperty; writers write compact JSON only on change."""

    def test_read_both_forms(self):
        load = {"kind": "pallet", "id": "EUR1", "length_m": 1.2, "forward_axis": "X"}
        self.assertEqual(records.read_record(json.dumps(load), None), load)
        self.assertEqual(records.read_record(load, None), load)
        self.assertEqual(records.read_record(json.dumps([load]), []), [load])
        self.assertEqual(records.read_record("", {}), {})
        self.assertEqual(records.read_record(None, {}), {})
        self.assertEqual(records.read_record("{not json", {}), {})

    def test_write_only_on_change(self):
        target = {}
        ports = [{"version": 2, "id": "line_in", "level": "mezz1"}]
        self.assertTrue(records.write_record(target, "wh_ports", ports))
        self.assertEqual(target["wh_ports"], '[{"version":2,"id":"line_in","level":"mezz1"}]')
        self.assertFalse(records.write_record(target, "wh_ports", ports))
        self.assertTrue(records.write_record(target, "wh_ports", []))

    def test_version_gate(self):
        self.assertEqual(records.supported([{"version": 2, "port": "a"}, {"port": "b"}, {"version": 3, "port": "c"}, "junk"]),
                         [{"version": 2, "port": "a"}, {"port": "b"}])


class LevelTests(unittest.TestCase):
    """R10: a level per point, so an incline's two ends sit on different floors."""

    MEZZ = [{"version": 2, "id": "mezz1", "label": "Mezzanine 1", "z": 4.2, "footprint": [[-10, -10], [30, -10], [30, 20], [-10, 20]]}]

    def test_origin_and_ports(self):
        world = levels.levels_world(self.MEZZ, (0.0, 0.0, 0.0), 0.0)
        self.assertEqual(levels.level_at((5.0, 5.0, 4.2), world), "mezz1")
        self.assertEqual(levels.level_at((5.0, 5.0, 4.16), world), "mezz1")  # within the 5 cm tolerance
        self.assertEqual(levels.level_at((5.0, 5.0, 4.0), world), 0)  # an incline's lower end
        self.assertEqual(levels.level_at((40.0, 5.0, 4.2), world), 0)  # outside the footprint
        self.assertEqual(levels.level_at((5.0, 5.0, 0.0), world), 0)

    def test_host_pose(self):
        world = levels.levels_world(self.MEZZ, (0.0, 0.0, 1.0), 90.0)  # the building raised 1 m and turned
        self.assertEqual(levels.level_at((5.0, 5.0, 4.2), world), 0)  # the deck is at 5.2 now
        self.assertEqual(levels.level_at((-5.0, 5.0, 5.2), world), "mezz1")  # turned: x -> y, y -> -x
        self.assertEqual(levels.level_at((25.0, 5.0, 5.2), world), 0)


if __name__ == "__main__":
    unittest.main()
