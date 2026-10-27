"""model/buffer_fifo.py: the populate tree's FIFO buffer and the root's switch,
checked against warehouse_common's simple_flow (buffer_item_times,
branch_of_item). python3 -m unittest tests.test_buffer_fifo"""
import importlib.util
import math
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


B = _load("buffer_fifo", ROOT / "model" / "buffer_fifo.py")
SF = _load("wc_simple_flow", ROOT / "_wh" / "simple_flow.py")


class DealTests(unittest.TestCase):
    def test_owners_deal_as_branch_of_item(self):
        for k in range(-20, 60):
            self.assertEqual(B.slot_owner(k, [0.4, 1.0], 1), SF.branch_of_item(k, [0.4, 0.6]))
        self.assertEqual(B.slot_owner(7, [1.0], 0), (0, 7))  # no sources: the item number

    def test_a_split_before_the_buffer(self):
        # a 30 % divert before it: the main's goods are numbered among those left, the branch's among the taken
        chain = [(5.0, 1, 0.3, -1, -1, False, True, "Branch")]
        for k in range(0, 40):
            branch, index = SF.branch_of_item(k, [0.3, 0.7])
            i, stays = B.chain_index(0, k, chain, 1)
            self.assertEqual(stays, branch == 1)
            if stays:
                self.assertEqual(i, index)

    def test_thinning_numbers_the_items_on(self):
        taken = [B.thinned(k, 10, 0.4) for k in range(10, 30)]
        self.assertEqual(sum(1 for t, _n in taken if t), 8)  # 40 % of 20 slots
        self.assertEqual([n for t, n in taken if t], list(range(10, 18)))  # numbered on, without gaps
        self.assertEqual(B.thinned(4, 10, 0.4), (True, 4))  # before the switch: every slot, as it is


class FifoTests(unittest.TestCase):
    def test_departures_are_buffer_item_times(self):
        # items arrive at the entry every 2 s from item 0 at t = 5; Output 40 %: one leaves every 5 s from t0 = 5
        p_in, f = 2.0, 0.4
        schedule = [[0.0, 5.0, p_in]]
        for k in range(0, 40):
            _enter, leave = SF.buffer_item_times(k, schedule, f, 30, t0=5.0)
            arrive = 5.0 + k * p_in
            self.assertAlmostEqual(B.departure(k, arrive, 0, 5.0, p_in / f), leave, places=9)

    def test_the_queue_stands_a_zone_apart_and_steps_up(self):
        v, stop, pitch, period = 0.5, 10.0, 0.75, 5.0
        t = 32.5  # ranks 0..5 have left (5 s apart from t = 5, the last at 30); 6, 7, 8 wait, stepped up
        drawn = [B.shown(stop + 3.0 + k, t, v, stop, pitch, m, 0, 5.0, period) for k, m in enumerate((6, 7, 8))]
        self.assertAlmostEqual(drawn[0], stop)  # the front item at the photo-eye
        self.assertAlmostEqual(drawn[1] - drawn[2], pitch)
        self.assertAlmostEqual(drawn[0] - drawn[1], pitch)
        # a second after a departure the queue is still rolling up: 0.5 m of its 0.75 m step done
        self.assertAlmostEqual(B.shown(stop + 3.0, 31.0, v, stop, pitch, 6, 0, 5.0, period), stop - 0.25)
        # rank 6 leaves at 5 + 6 x 5 = 35 s and goes on at the belt's speed, from the stop
        self.assertAlmostEqual(B.shown(stop + 20.0, 35.0 + 2.0, v, stop, pitch, 6, 0, 5.0, period), stop + v * 2.0)

    def test_an_item_never_held_rolls_through(self):
        # before t0 (rank below first) or with no out period: where its slot is
        self.assertEqual(B.shown(12.0, 3.0, 0.5, 10.0, 0.75, -3, 0, 5.0, 5.0), 12.0)
        self.assertEqual(B.shown(12.0, 3.0, 0.5, 10.0, 0.75, 4, 0, 5.0, 0.0), 12.0)

    def test_a_slug_leaves_together_nose_to_tail(self):
        v, stop, pitch, period, slug = 0.5, 10.0, 0.75, 5.0, 3
        leave = 5.0 + (3 - 1) * period  # batch 0 leaves when its last would have: t = 15
        after = [B.shown(stop + 30.0, leave + 1.0, v, stop, pitch, m, 0, 5.0, period, slug) for m in (0, 1, 2)]
        self.assertAlmostEqual(after[0], stop + v * 1.0)
        self.assertAlmostEqual(after[0] - after[1], pitch)
        self.assertAlmostEqual(after[1] - after[2], pitch)

    def test_full_after(self):
        # 6 zones, Output 40 %, 1 item/s in: 0.6 a second stays: full after 10 s (buffer_fill's full_at)
        self.assertAlmostEqual(B.full_after(6, 0.4, 1.0), 10.0)
        self.assertAlmostEqual(SF.buffer_fill(100.0, 1.0, 0.4, 6).full_at, 10.0)
        self.assertEqual(B.full_after(6, 1.0, 1.0), math.inf)


if __name__ == "__main__":
    unittest.main()
