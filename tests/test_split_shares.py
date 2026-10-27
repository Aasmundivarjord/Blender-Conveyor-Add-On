"""The local share of a divert, as the stream animates it (model/split_shares.py,
contract R22.1). Pure Python: python3 -m unittest tests/test_split_shares.py"""
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


S = _load("split_shares", "model/split_shares.py")
Rule, Member = S.Rule, S.Member
PORTIONS = {0: 0.3, 1: 0.2, 2: 0.5}  # share routing: two branch slices and the remainder riding on


def rule(u, atoms, mask=0b1):
    return Rule(u, frozenset(atoms), mask)


class SplitShareTests(unittest.TestCase):
    def test_second_branch_takes_its_share_of_what_is_left(self):
        r1, r2 = rule(2.0, {0}), rule(5.0, {1})
        members = {"main": Member(None, routes=[r1, r2]),
                   "b1": Member('DIVERTER', "main", 2.0, rule=r1),
                   "b2": Member('DIVERTER', "main", 5.0, rule=r2)}
        self.assertAlmostEqual(S.local_share(members, {}, [1.0], PORTIONS, "b1"), 0.3)
        self.assertAlmostEqual(S.local_share(members, {}, [1.0], PORTIONS, "b2"), 0.2 / 0.7)

    def test_a_feeder_merging_between_counts_whole(self):
        r1, r2 = rule(2.0, {0}, 0b01), rule(5.0, {1}, 0b11)
        members = {"main": Member(None, routes=[r1, r2]),
                   "feeder": Member('MERGE', "main", 3.5, owner=1, routes=[r2]),
                   "b1": Member('DIVERTER', "main", 2.0, rule=r1),
                   "b2": Member('DIVERTER', "main", 5.0, rule=r2)}
        # passing: 100 x 0.7 of the main's goods + 50 x 1.0 of the feeder's; taken: 0.2 of both
        self.assertAlmostEqual(S.local_share(members, {1: "feeder"}, [100.0, 50.0], PORTIONS, "b2"), 30.0 / 120.0)

    def test_a_merge_at_the_same_place_is_not_part_of_the_split(self):
        r1, r2 = rule(2.0, {0}, 0b01), rule(5.0, {1}, 0b11)
        members = {"main": Member(None, routes=[r1, r2]),
                   "feeder": Member('MERGE', "main", 5.0004, owner=1, routes=[r2]),
                   "b1": Member('DIVERTER', "main", 2.0, rule=r1),
                   "b2": Member('DIVERTER', "main", 5.0, rule=r2)}
        self.assertAlmostEqual(S.local_share(members, {1: "feeder"}, [100.0, 50.0], PORTIONS, "b2"), 0.2 / 0.7)

    def test_both_faces_of_one_diverter_split_the_same_goods(self):
        left, right = rule(5.0, {0}), rule(5.0, {1})
        members = {"main": Member(None, routes=[left, right]),
                   "left": Member('DIVERTER', "main", 5.0, rule=left),
                   "right": Member('DIVERTER', "main", 5.0, rule=right)}
        a = S.local_share(members, {}, [1.0], PORTIONS, "left")
        b = S.local_share(members, {}, [1.0], PORTIONS, "right")
        self.assertAlmostEqual(a, 0.3)
        self.assertAlmostEqual(b, 0.2)
        self.assertLessEqual(a + b, 1.0)

    def test_class_routing(self):
        classes = {0: 0.5, 1: 0.5}
        rb, rc = rule(2.0, {1}), rule(4.0, {1})
        members = {"main": Member(None, routes=[rb, rc]),
                   "b": Member('DIVERTER', "main", 2.0, rule=rb),
                   "c": Member('DIVERTER', "main", 4.0, rule=rc)}
        self.assertAlmostEqual(S.local_share(members, {}, [1.0], classes, "b"), 0.5)
        self.assertAlmostEqual(S.local_share(members, {}, [1.0], classes, "c"), 0.0)  # the first took every one of that class

    def test_item_routing_takes_its_item_owners(self):
        r = rule(6.0, {0}, 0b10)  # one atom; only the feeder carries the branch's item
        members = {"main": Member(None, routes=[r]),
                   "feeder": Member('MERGE', "main", 3.0, owner=1, routes=[r]),
                   "b": Member('DIVERTER', "main", 6.0, rule=r)}
        self.assertAlmostEqual(S.local_share(members, {1: "feeder"}, [60.0, 40.0], {0: 1.0}, "b"), 0.4)

    def test_branch_of_a_branch(self):
        rb, rs = rule(2.0, {0, 1}), rule(4.0, {0})
        portions = {0: 0.2, 1: 0.1, 2: 0.7}
        members = {"main": Member(None, routes=[rb]),
                   "b": Member('DIVERTER', "main", 2.0, rule=rb, routes=[rs]),
                   "s": Member('DIVERTER', "b", 4.0, rule=rs)}
        self.assertAlmostEqual(S.local_share(members, {}, [1.0], portions, "b"), 0.3)
        self.assertAlmostEqual(S.local_share(members, {}, [1.0], portions, "s"), 0.2 / 0.3)

    def test_a_branch_on_a_feeder_sees_only_the_feeders_goods(self):
        r = rule(1.0, {0}, 0b11)
        members = {"main": Member(None, routes=[]),
                   "feeder": Member('MERGE', "main", 3.0, owner=1, routes=[r]),
                   "d": Member('DIVERTER', "feeder", 1.0, rule=r)}
        self.assertAlmostEqual(S.local_share(members, {1: "feeder"}, [900.0, 100.0], {0: 0.5, 1: 0.5}, "d"), 0.5)

    def test_a_takeaway_carries_what_rode_to_the_end(self):
        r1, r2, r3 = rule(2.0, {0}), rule(5.0, {1}), rule(12.0, {2})
        members = {"main": Member(None, routes=[r1, r2]),
                   "b1": Member('DIVERTER', "main", 2.0, rule=r1),
                   "b2": Member('DIVERTER', "main", 5.0, rule=r2),
                   "next": Member('CONTINUE', "main", 10.0, routes=[r3]),
                   "d": Member('DIVERTER', "next", 12.0, rule=r3)}
        self.assertAlmostEqual(S.local_share(members, {}, [1.0], PORTIONS, "d"), 1.0)

    def test_nothing_passing(self):
        r = rule(1.0, {0}, 0b10)
        members = {"main": Member(None, routes=[]),
                   "feeder": Member('MERGE', "main", 3.0, owner=-1, routes=[r]),
                   "d": Member('DIVERTER', "feeder", 1.0, rule=r)}
        self.assertIsNone(S.local_share(members, {}, [1.0], {0: 1.0}, "d"))
        self.assertIsNone(S.local_share(members, {}, [1.0], {0: 1.0}, "main"))


if __name__ == "__main__":
    unittest.main()
