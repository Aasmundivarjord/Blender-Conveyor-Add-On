"""Leg-free stretches (model/legs.py). python3 -m unittest tests.test_legs (from dev/)."""
import unittest

from model import legs as L
from model import pouch as P


class LegTests(unittest.TestCase):
    def test_free_intervals_merge_neighbours(self):
        starts, ends = [0.0, 4.0, 7.0, 9.0], [4.0, 7.0, 9.0, 12.0]
        self.assertEqual(L.free_intervals(starts, ends, [True, False, False, True]), [(4.0, 9.0)])
        self.assertEqual(L.free_intervals(starts, ends, [False, True, False, True]), [(0.0, 4.0), (7.0, 9.0)])
        self.assertEqual(L.free_intervals(starts, ends, [True] * 4), [])

    def test_longest_span(self):
        self.assertAlmostEqual(L.longest_free_span([(0.0, 4.0), (7.0, 9.5)]), 4.0)
        self.assertEqual(L.longest_free_span([]), 0.0)
        self.assertGreater(4.0, L.MAX_FREE_SPAN_M)


class StandPlanTests(unittest.TestCase):
    SIZE = 0.06

    def test_a_joint_gets_one_stand_the_transfers(self):
        # straight 0-3, transfer 3-3.9, straight 3.9-6.9: two stands a post apart at each joint before 2.26.1
        ranges = [(0.0, 3.0, False, False), (3.0, 3.9, False, False), (3.9, 6.9, False, False)]
        shared = L.share_joints(ranges, [False, True, False])
        self.assertEqual(shared, [(0.0, 3.0, False, True), (3.0, 3.9, False, False), (3.9, 6.9, True, False)])
        stands, _r, longest = L.plan_stands(shared, 1.5, self.SIZE)
        self.assertTrue(all(b - a > 0.3 for a, b in zip(stands, stands[1:])), stands)
        self.assertIn(3.03, [round(s, 6) for s in stands])  # the transfer's own
        self.assertIn(3.87, [round(s, 6) for s in stands])
        self.assertEqual(longest, 0.0)  # no span beyond the spacing: the transfer's stands carry the straights' ends

    def test_an_added_stand_stands_where_the_user_put_it(self):
        base, _r, _l = L.plan_stands([(0.0, 6.0, False, False)], 1.5, self.SIZE)
        placed = []
        stands, _r, _l = L.plan_stands([(0.0, 6.0, False, False)], 1.5, self.SIZE, added=[2.2], added_sources=placed)
        self.assertEqual(len(stands), len(base) + 1)
        self.assertIn(2.2, [round(s, 6) for s in stands])
        self.assertEqual(placed, [(2.2, 0)])

    def test_an_added_stand_keeps_a_post_clear_and_off_leg_free_pieces(self):
        base, _r, _l = L.plan_stands([(0.0, 6.0, False, False)], 1.5, self.SIZE)
        placed = []
        L.plan_stands([(0.0, 6.0, False, False)], 1.5, self.SIZE, added=[base[1] + 0.02], added_sources=placed)
        self.assertEqual(placed, [], "on top of a planned stand: none")
        L.plan_stands([(0.0, 9.0, False, False)], 1.5, self.SIZE, blocked=[(3.0, 6.0)], added=[4.5], added_sources=placed)
        self.assertEqual(placed, [], "a piece with Legs off gets none")
        L.plan_stands([(0.0, 6.0, False, False)], 1.5, self.SIZE, added=[5.999], added_sources=placed)
        self.assertEqual(placed, [], "at the very end: the end stand is there")
        L.plan_stands([(0.0, 6.0, False, False)], 1.5, self.SIZE, removed=[base[2]], added=[base[2]], added_sources=placed)
        self.assertEqual([round(a, 6) for a, _k in placed], [round(base[2], 6)], "taken out, then added on the spot: it stands")

    def test_gaps_offer_a_plus_in_their_middle(self):
        gaps = []
        stands, _r, _l = L.plan_stands([(0.0, 6.0, False, False), (6.0, 6.9, True, False)], 1.5, self.SIZE, gaps=gaps)
        self.assertEqual(len(gaps), len(stands) - 1)
        self.assertTrue(all(a < g < b for g, a, b in zip(gaps, stands, stands[1:])))
        gaps = []
        L.plan_stands([(0.0, 9.0, False, False)], 1.5, self.SIZE, blocked=[(3.0, 6.0)], gaps=gaps)
        self.assertFalse([g for g in gaps if 3.0 < g < 6.0], "none across a piece with Legs off")
        gaps = []
        L.plan_stands([(0.0, 0.5, False, False)], 1.5, self.SIZE, gaps=gaps)
        self.assertEqual(gaps, [], "two stands closer than ADD_GAP_M: no room for another")

    def test_two_transfers_and_two_runs_keep_the_first(self):
        shared = L.share_joints([(0.0, 0.9, False, False), (0.9, 1.8, False, False)], [True, True])
        self.assertEqual(shared, [(0.0, 0.9, False, False), (0.9, 1.8, True, False)])

    def test_a_joint_without_stands_is_left_alone(self):
        ranges = [(0.0, 3.0, False, False), (3.0, 3.9, False, False)]
        self.assertEqual(L.share_joints(ranges, [False, True], no_stand=[(3.0, 3.9)]), ranges)  # the transfer has Legs off
        self.assertEqual(L.share_joints([(0.0, 3.0, False, True), (3.0, 3.9, False, False)], [False, True]),
                         [(0.0, 3.0, False, True), (3.0, 3.9, False, False)])  # already resting on it
        self.assertEqual(L.share_joints([(0.0, 3.0, False, False), (9.0, 12.0, False, False)], [False, False]),
                         [(0.0, 3.0, False, False), (9.0, 12.0, False, False)])  # a lift between: no joint

    def test_flush_ends_and_even_spacing(self):
        stands, removed, longest = L.plan_stands([(0.0, 12.0, False, False)], 1.5, self.SIZE)
        self.assertEqual(len(stands), 10)  # floor(12 / 1.5) + 2, as the trees always did
        self.assertAlmostEqual(stands[0], 0.03)
        self.assertAlmostEqual(stands[-1], 11.97)
        gaps = [b - a for a, b in zip(stands, stands[1:])]
        self.assertTrue(all(abs(g - gaps[0]) < 1e-9 and g <= 1.5 for g in gaps))
        self.assertEqual((removed, longest), ([], 0.0))

    def test_a_blocked_piece_gets_flush_edge_stands(self):
        stands, _r, longest = L.plan_stands([(0.0, 11.0, False, False)], 1.5, self.SIZE, blocked=[(4.0, 7.0)])
        self.assertFalse([s for s in stands if 4.0 < s < 7.0])
        self.assertIn(round(4.0 - 0.03, 9), [round(s, 9) for s in stands])
        self.assertIn(round(7.0 + 0.03, 9), [round(s, 9) for s in stands])
        self.assertAlmostEqual(longest, 3.0)  # post face to post face

    def test_skip_flags_and_dedupe(self):
        stands, _r, _l = L.plan_stands([(0.0, 3.0, True, False), (3.0, 6.0, False, True)], 1.5, self.SIZE)
        self.assertGreater(stands[0], 0.5)  # no stand at the skipped start
        self.assertLess(stands[-1], 5.5)  # nor at the skipped end
        self.assertEqual(len(stands), len(set(round(s, 6) for s in stands)))

    def test_remove_and_report_the_span(self):
        stands, _r, _l = L.plan_stands([(0.0, 6.0, False, False)], 1.5, self.SIZE)
        middle = stands[2]
        after, removed, longest = L.plan_stands([(0.0, 6.0, False, False)], 1.5, self.SIZE, removed=[middle + 0.1])
        self.assertEqual(len(after), len(stands) - 1)
        self.assertEqual(removed, [middle])
        self.assertGreater(longest, 1.5)
        untouched, removed2, _l2 = L.plan_stands([(0.0, 6.0, False, False)], 1.5, self.SIZE, removed=[7.0])
        self.assertEqual((len(untouched), removed2), (len(stands), []))  # beyond half the spacing from every stand: nothing goes

    def test_carried_stretches_are_not_spans_without_support(self):
        # 2 m straight, a 13 m spiral (carried by its drum), 2 m straight: no alert
        stands, _r, longest = L.plan_stands([(0.0, 17.0, False, False)], 1.5, self.SIZE, carried=[(2.0, 15.0)])
        self.assertEqual(longest, 0.0)
        self.assertFalse([s for s in stands if 2.0 < s < 15.0])
        # the same 13 m as a leg-free stretch is one
        _s, _r, free = L.plan_stands([(0.0, 17.0, False, False)], 1.5, self.SIZE, blocked=[(2.0, 15.0)])
        self.assertAlmostEqual(free, 13.0)
        # a lift between two runs (no run there) is not one either
        _s, _r, lift = L.plan_stands([(0.0, 3.0, False, False), (9.0, 12.0, False, False)], 1.5, self.SIZE)
        self.assertEqual(lift, 0.0)

    def test_zone_intervals_on_a_straight_and_merged(self):
        # a 10 m straight along y (two samples), a circle of r 2 centred 1 m beside it at y 5
        got = L.zone_intervals([0.0, 10.0], [0.0, 0.0], [0.0, 10.0], [(1.0, 5.0, 2.0)])
        self.assertEqual(len(got), 1)
        self.assertAlmostEqual(got[0][0], 5.0 - 3 ** 0.5)
        self.assertAlmostEqual(got[0][1], 5.0 + 3 ** 0.5)
        two = L.zone_intervals([0.0, 5.0, 10.0], [0.0, 0.0, 0.0], [0.0, 5.0, 10.0], [(0.0, 4.0, 1.5), (0.0, 6.0, 1.5)])
        self.assertEqual([(round(a, 6), round(b, 6)) for a, b in two], [(2.5, 7.5)])
        self.assertEqual(L.zone_intervals([0.0, 10.0], [0.0, 0.0], [0.0, 10.0], [(5.0, 5.0, 1.0)]), [])

    def test_a_single_precision_spacing_counts_as_typed(self):
        stands, _r, _l = L.plan_stands([(0.0, 12.0, False, False)], 1.2000000476837158, self.SIZE)
        self.assertEqual(len(stands), 12)

    def test_a_removed_spot_survives_new_spacing(self):
        stands, _r, _l = L.plan_stands([(0.0, 12.0, False, False)], 1.5, self.SIZE)
        spot = stands[6]
        respaced, removed, _l2 = L.plan_stands([(0.0, 12.0, False, False)], 1.2, self.SIZE, removed=[spot])
        nearest = min(L.plan_stands([(0.0, 12.0, False, False)], 1.2, self.SIZE)[0], key=lambda s: abs(s - spot))
        self.assertEqual(removed, [nearest])  # the stand now nearest the spot goes
        self.assertNotIn(nearest, respaced)

    def test_two_spots_take_two_stands_and_report_their_sources(self):
        stands, _r, _l = L.plan_stands([(0.0, 12.0, False, False)], 1.5, self.SIZE)
        sources = []
        after, removed, longest = L.plan_stands([(0.0, 12.0, False, False)], 1.5, self.SIZE, removed=[stands[5] + 0.2, stands[4] - 0.1, 40.0], sources=sources)
        self.assertEqual(removed, [stands[4], stands[5]])
        self.assertEqual(sources, [1, 0])  # the spot behind each removed stand, in removed order
        self.assertEqual(len(after), len(stands) - 2)
        self.assertAlmostEqual(longest, stands[6] - stands[3] - self.SIZE)

    def test_a_free_first_piece_is_a_cantilever(self):
        stands, _r, longest = L.plan_stands([(0.0, 7.0, False, False)], 1.5, self.SIZE, blocked=[(0.0, 3.5)])
        self.assertAlmostEqual(stands[0], 3.53)
        self.assertAlmostEqual(longest, 3.5)


class PouchFitTests(unittest.TestCase):
    def test_standins_fit_the_smallest_pouch(self):
        small = P.pouch_dims_mm("STD_300_450", 0, 0, P.DEFAULT_DEPTH_MM)
        for _name, across, along, height in P.POUCH_ITEMS:
            self.assertTrue(P.fits((across, along, height), small), _name)

    def test_a_tote_does_not_fit(self):
        self.assertFalse(P.fits((400.0, 600.0, 280.0), P.pouch_dims_mm("STD_400_600", 0, 0, 120.0)))

    def test_same_count_and_order_as_the_placeholders(self):
        names = [n for n, *_ in P.POUCH_ITEMS]
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(names), 2)  # operators/populate.PLACEHOLDER_ITEMS: Carton, Tote


if __name__ == "__main__":
    unittest.main()
