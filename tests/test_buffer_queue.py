"""model/buffer_queue: the stepping queue holds items back by whole slots,
never overlaps them and leaves the stream's grid intact downstream."""
import importlib
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if "model" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("model", ROOT / "model" / "__init__.py", submodule_search_locations=[str(ROOT / "model")])
    _model = importlib.util.module_from_spec(_spec)
    sys.modules["model"] = _model
    _spec.loader.exec_module(_model)
Q = importlib.import_module("model.buffer_queue")


class Plan(unittest.TestCase):
    def test_four_zones_half_pitch(self):
        p = Q.queue_plan(3.0, 0.75, 1.5)
        self.assertEqual((p.zones, p.slots), (4, 2))
        self.assertAlmostEqual(p.wait, 0.75)
        self.assertAlmostEqual(p.shift, 2 * 1.5)

    def test_invariants(self):
        for length in (1.0, 2.0, 3.0, 4.5, 7.0, 12.0):
            for pitch in (0.45, 0.6, 0.75, 1.0):
                for spacing in (0.8, 1.2, 1.5, 2.4, 3.0):
                    p = Q.queue_plan(length, pitch, spacing)
                    if p.zones == 0:
                        self.assertEqual(p.slots, 0)
                        continue
                    self.assertLessEqual(p.zones, int(length // pitch))
                    self.assertGreater(p.wait, 0.0)
                    self.assertLessEqual(p.wait, spacing - pitch + 1e-9)  # the zone ahead is free when the next item arrives
                    self.assertAlmostEqual(p.shift, p.slots * spacing)  # whole slots

    def test_no_overlap_and_grid_downstream(self):
        plan = Q.queue_plan(3.0, 0.75, 1.5)
        tail = 10.0
        # items one slot apart, through the whole passage: never closer than the queue pitch, same grid after
        for t in [k * 0.05 for k in range(0, 400)]:
            xs = [tail - 2.0 + j * 1.5 + t for j in range(8)]
            ds = [Q.displayed(x, tail, plan) for x in xs]
            for a, b in zip(ds, ds[1:]):
                self.assertGreaterEqual(b - a, 0.75 - 1e-9, (t, ds))
            for x, d in zip(xs, ds):
                if x - tail > plan.wait + (plan.zones - 1) * 1.5:  # left the queue
                    self.assertAlmostEqual(x - d, plan.shift)

    def test_monotone_in_time(self):
        plan = Q.queue_plan(3.0, 0.75, 1.5)
        prev = -1.0
        for k in range(0, 2000):
            d = Q.displayed(k * 0.01, 2.0, plan)
            self.assertGreaterEqual(d, prev - 1e-9)
            prev = d



class SlugTests(unittest.TestCase):
    S, P = 1.0, 0.75  # slots a metre apart, items 0.75 m nose to nose in the queue

    def test_slug_size_divides_the_stream(self):
        self.assertEqual(Q.slug_size(4, 21), 4)  # 20 slots before the slug's own 3: 4 | 20
        self.assertEqual(Q.slug_size(4, 22), 3)  # 21: 3 | 21
        self.assertEqual(Q.slug_size(1, 22), 0)

    def test_slug_fills_from_the_stop_and_leaves_together(self):
        slug, stop = 4, 10.0
        wait = Q.slug_wait(slug, self.S, self.P)
        self.assertAlmostEqual(wait, 3 * (self.S - self.P))
        # Items q = 0..3 have nominal coordinates stop + y_first - q * S: they
        # stand q pitches behind the stop until the first has waited `wait`.
        for y_first in (0.0, 0.3, wait - 1e-6):
            shown = [Q.displayed_slug(stop + y_first - q * self.S, stop, q, slug, wait, self.P, self.S) for q in range(slug)]
            for q, pos in enumerate(shown):
                arrived = y_first - q * self.S >= -q * self.P
                self.assertAlmostEqual(pos, stop - q * self.P if arrived else stop + y_first - q * self.S)
        # After the release they move as a block, nose to tail.
        for y_first in (wait + 0.5, wait + 3.0):
            shown = [Q.displayed_slug(stop + y_first - q * self.S, stop, q, slug, wait, self.P, self.S) for q in range(slug)]
            for q in range(1, slug):
                self.assertAlmostEqual(shown[q - 1] - shown[q], self.P)
            self.assertAlmostEqual(shown[0], stop + (y_first - wait))
        # The next slug's first item reaches the stop exactly when this slug has cleared it.
        y_next_first = slug * self.S - slug * self.S  # = 0: when item q=0 of the next slug stands at the stop...
        last = Q.displayed_slug(stop + slug * self.S - (slug - 1) * self.S, stop, slug - 1, slug, wait, self.P, self.S)
        self.assertGreaterEqual(last, stop + self.S - 1e-9)

    def test_slug_is_continuous_at_arrival_and_release(self):
        slug, stop, q = 3, 5.0, 1
        wait = Q.slug_wait(slug, self.S, self.P)
        eps = 1e-6
        a = -q * self.P
        self.assertAlmostEqual(Q.displayed_slug(stop + a - eps, stop, q, slug, wait, self.P, self.S), Q.displayed_slug(stop + a + eps, stop, q, slug, wait, self.P, self.S), places=4)
        r = wait - q * self.S
        self.assertAlmostEqual(Q.displayed_slug(stop + r - eps, stop, q, slug, wait, self.P, self.S), Q.displayed_slug(stop + r + eps, stop, q, slug, wait, self.P, self.S), places=4)


class FillTimeTests(unittest.TestCase):
    def test_fill_time(self):
        self.assertAlmostEqual(Q.fill_time_min(4, 100.0, 60.0), 6.0)  # 40 surplus an hour: 4 zones in 6 min
        self.assertEqual(Q.fill_time_min(4, 60.0, 100.0), float("inf"))
        self.assertEqual(Q.fill_time_min(0, 100.0, 60.0), float("inf"))


if __name__ == "__main__":
    unittest.main()
