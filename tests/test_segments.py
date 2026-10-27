"""Plain-Python tests for model/segments.py -- run without Blender:

    python3 -m unittest tests/test_segments.py
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.segments import (  # noqa: E402
    Curve,
    Incline,
    Module,
    Pose,
    Straight,
    centerline_radius,
    end_pose,
    evaluate_chain,
    segment_length,
    segment_starts,
)

ORIGIN = Pose(0.0, 0.0, 0.0, 0.0, 0.0)
WIDTH = 0.5


class StraightTests(unittest.TestCase):
    def test_straight_along_plus_y_at_zero_heading(self):
        p = end_pose([Straight(3.0)], ORIGIN, WIDTH)
        self.assertAlmostEqual(p.x, 0.0)
        self.assertAlmostEqual(p.y, 3.0)
        self.assertAlmostEqual(p.z, 0.0)
        self.assertAlmostEqual(p.heading, 0.0)

    def test_straight_follows_heading(self):
        start = Pose(0.0, 0.0, 0.0, math.radians(90.0), 0.0)  # facing -X
        p = end_pose([Straight(2.0)], start, WIDTH)
        self.assertAlmostEqual(p.x, -2.0)
        self.assertAlmostEqual(p.y, 0.0)


class CurveTests(unittest.TestCase):
    def test_centerline_radius_adds_half_width(self):
        self.assertAlmostEqual(centerline_radius(Curve(90, 0.8), 0.5), 1.05)

    def test_left_90_turns_ccw_and_ends_at_quarter_circle(self):
        r = centerline_radius(Curve(90, 0.8), WIDTH)
        p = end_pose([Curve(90, 0.8, "LEFT")], ORIGIN, WIDTH)
        # Center is at (-r, 0); a quarter turn ends at (-r, r), facing -X.
        self.assertAlmostEqual(p.x, -r, places=6)
        self.assertAlmostEqual(p.y, r, places=6)
        self.assertAlmostEqual(p.heading, math.radians(90.0), places=9)

    def test_right_90_mirrors_left(self):
        r = centerline_radius(Curve(90, 0.8), WIDTH)
        p = end_pose([Curve(90, 0.8, "RIGHT")], ORIGIN, WIDTH)
        self.assertAlmostEqual(p.x, r, places=6)
        self.assertAlmostEqual(p.y, r, places=6)
        self.assertAlmostEqual(p.heading, math.radians(-90.0), places=9)

    def test_curve_length_is_arc_length(self):
        c = Curve(45, 1.0)
        self.assertAlmostEqual(segment_length(c, WIDTH), centerline_radius(c, WIDTH) * math.pi / 4)

    def test_every_curve_sample_sits_on_the_arc(self):
        c = Curve(90, 0.8, "LEFT")
        r = centerline_radius(c, WIDTH)
        spine = evaluate_chain([c], ORIGIN, WIDTH)
        for x, y in zip(spine.x, spine.y):
            self.assertAlmostEqual(math.hypot(x + r, y), r, places=9)

    def test_heading_is_monotonic_along_a_curve(self):
        spine = evaluate_chain([Curve(180, 0.8, "LEFT")], ORIGIN, WIDTH)
        for a, b in zip(spine.heading, spine.heading[1:]):
            self.assertGreaterEqual(b, a)


class InclineTests(unittest.TestCase):
    def test_incline_rises_by_length_times_sin(self):
        p = end_pose([Incline(30.0, 2.0)], ORIGIN, WIDTH)
        self.assertAlmostEqual(p.z, 2.0 * math.sin(math.radians(30.0)))
        self.assertAlmostEqual(p.y, 2.0 * math.cos(math.radians(30.0)))
        self.assertAlmostEqual(p.incline, math.radians(30.0))

    def test_decline_is_negative_angle(self):
        p = end_pose([Incline(-15.0, 1.0)], Pose(0, 0, 1.0, 0, 0), WIDTH)
        self.assertLess(p.z, 1.0)

    def test_pitch_change_emits_kink_point_not_a_smear(self):
        spine = evaluate_chain([Straight(1.0), Incline(20.0, 1.0)], ORIGIN, WIDTH)
        # Two samples share the kink position: one level, one at 20 deg.
        kinks = [i for i, s in enumerate(spine.s) if abs(s - 1.0) < 1e-9]
        self.assertEqual(len(kinks), 2)
        self.assertAlmostEqual(spine.incline[kinks[0]], 0.0)
        self.assertAlmostEqual(spine.incline[kinks[1]], math.radians(20.0))

    def test_level_after_incline_kinks_back(self):
        spine = evaluate_chain([Incline(20.0, 1.0), Straight(1.0)], ORIGIN, WIDTH)
        self.assertAlmostEqual(spine.incline[-1], 0.0)


class ChainTests(unittest.TestCase):
    def test_closed_loop_returns_to_start(self):
        loop = [Straight(2.0), Curve(90, 0.8), Straight(2.0), Curve(90, 0.8),
                Straight(2.0), Curve(90, 0.8), Straight(2.0), Curve(90, 0.8)]
        p = end_pose(loop, ORIGIN, WIDTH)
        self.assertAlmostEqual(p.x, 0.0, places=6)
        self.assertAlmostEqual(p.y, 0.0, places=6)
        self.assertAlmostEqual(p.heading % (2 * math.pi), 0.0, places=6)

    def test_arc_length_is_cumulative_and_matches_segment_starts(self):
        segs = [Straight(1.5), Curve(45, 1.0), Module("RAT", 0.6), Incline(10, 2.0)]
        spine = evaluate_chain(segs, ORIGIN, WIDTH)
        starts = segment_starts(segs, WIDTH)
        total = sum(segment_length(s, WIDTH) for s in segs)
        self.assertAlmostEqual(spine.length, total)
        self.assertAlmostEqual(starts[-1] + segment_length(segs[-1], WIDTH), total)
        for a, b in zip(spine.s, spine.s[1:]):
            self.assertGreaterEqual(b, a)

    def test_segment_index_tracks_which_segment_each_sample_belongs_to(self):
        segs = [Straight(1.0), Curve(90, 0.8), Straight(1.0)]
        spine = evaluate_chain(segs, ORIGIN, WIDTH)
        self.assertEqual(spine.segment_index[0], 0)
        self.assertEqual(spine.segment_index[-1], 2)
        self.assertIn(1, spine.segment_index)

    def test_module_is_a_flat_straight_footprint(self):
        p = end_pose([Module("MERGE", 0.9)], ORIGIN, WIDTH)
        self.assertAlmostEqual(p.y, 0.9)
        self.assertAlmostEqual(p.z, 0.0)


from model.segments import Pose, Spine, insert_sample_at  # noqa: E402


class InsertSampleTests(unittest.TestCase):
    def test_yaw_offset_is_interpolated(self):
        """Goods turning over an ARB / pivot module: a sample put in the module
        (a stand, 2.14) keeps the turn gradual instead of holding the start yaw."""
        sp = Spine()
        sp._append(Pose(0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 0.0, 0, 0)
        sp._append(Pose(0.0, 1.5, 0.0, 0.0, 0.0, math.pi / 2), 1.5, 0, 0)
        insert_sample_at(sp, 0.5)
        self.assertEqual(sp.s, [0.0, 0.5, 1.5])
        self.assertAlmostEqual(sp.yaw_offset[1], math.pi / 6)
        self.assertAlmostEqual(sp.y[1], 0.5)


if __name__ == "__main__":
    unittest.main()


from model.segments import (  # noqa: E402
    KIND_MODULE,
    KIND_TRANSITION,
    runs,
    transition_length,
)


class TransitionTests(unittest.TestCase):
    def test_nose_over_adds_arc_length_and_removes_kink(self):
        segs = [Straight(1.0), Incline(20.0, 1.0)]
        spine = evaluate_chain(segs, ORIGIN, WIDTH, transition_radius_m=1.5)
        extra = transition_length(0.0, math.radians(20.0), 1.5)
        self.assertAlmostEqual(spine.length, 2.0 + extra)
        # Transition samples exist and no two consecutive samples share a position.
        self.assertIn(KIND_TRANSITION, spine.kind)
        for i in range(1, len(spine)):
            d = math.dist((spine.x[i], spine.y[i], spine.z[i]), (spine.x[i - 1], spine.y[i - 1], spine.z[i - 1]))
            self.assertGreater(d, 1e-9)

    def test_nose_over_ends_at_target_pitch_and_is_tangent_continuous(self):
        spine = evaluate_chain([Straight(1.0), Incline(20.0, 1.0)], ORIGIN, WIDTH, transition_radius_m=1.5)
        first_t = spine.kind.index(KIND_TRANSITION)
        last_t = len(spine.kind) - 1 - spine.kind[::-1].index(KIND_TRANSITION)
        self.assertAlmostEqual(spine.incline[last_t], math.radians(20.0))
        # Incline attribute rises monotonically across the arc.
        for a, b in zip(spine.incline[first_t - 1:last_t], spine.incline[first_t:last_t + 1]):
            self.assertLessEqual(a, b + 1e-12)
        # Every arc sample lies on a circle of radius 1.5 centered 1.5 above the kink.
        cx, cy, cz = 0.0, 1.0, 1.5
        for i in range(first_t, last_t + 1):
            self.assertAlmostEqual(math.dist((spine.x[i], spine.y[i], spine.z[i]), (cx, cy, cz)), 1.5, places=9)

    def test_nose_down_curls_the_other_way(self):
        spine = evaluate_chain([Straight(1.0), Incline(-20.0, 1.0)], ORIGIN, WIDTH, transition_radius_m=1.5)
        last_t = len(spine.kind) - 1 - spine.kind[::-1].index(KIND_TRANSITION)
        self.assertAlmostEqual(spine.incline[last_t], math.radians(-20.0))
        self.assertLess(spine.z[last_t], 0.0)
        self.assertLess(spine.z[-1], spine.z[last_t])

    def test_transition_belongs_to_the_non_module_neighbour(self):
        segs = [Incline(15.0, 1.0), Module("RAT", 0.9)]
        spine = evaluate_chain(segs, ORIGIN, WIDTH, transition_radius_m=1.0)
        for k, si in zip(spine.kind, spine.segment_index):
            if k == KIND_TRANSITION:
                self.assertEqual(si, 0)
        # Module footprint is flat and exactly its own length.
        mod_pts = [i for i, si in enumerate(spine.segment_index) if si == 1]
        self.assertTrue(all(abs(spine.incline[i]) < 1e-12 for i in mod_pts))
        self.assertAlmostEqual(spine.s[mod_pts[-1]] - spine.s[mod_pts[0] - 1], 0.9)


class ModuleExitTests(unittest.TestCase):
    def test_rat_left_exit_turns_travel_but_not_the_item(self):
        p = end_pose([Module("RAT", 0.9, "LEFT")], ORIGIN, WIDTH)
        self.assertAlmostEqual(p.heading, math.radians(90.0))
        self.assertAlmostEqual(p.yaw_offset, math.radians(-90.0))
        self.assertAlmostEqual(p.heading + p.yaw_offset, 0.0)  # item still faces +Y
        # Center is 0.45 along +Y; the exit edge is width/2 to the LEFT (-X).
        self.assertAlmostEqual(p.x, -WIDTH / 2.0)
        self.assertAlmostEqual(p.y, 0.45)

    def test_rat_right_exit_mirrors(self):
        p = end_pose([Module("RAT", 0.9, "RIGHT")], ORIGIN, WIDTH)
        self.assertAlmostEqual(p.heading, math.radians(-90.0))
        self.assertAlmostEqual(p.x, WIDTH / 2.0)
        self.assertAlmostEqual(p.yaw_offset, math.radians(90.0))

    def test_rat_exit_length_is_half_length_plus_half_width(self):
        self.assertAlmostEqual(segment_length(Module("RAT", 0.9, "LEFT"), WIDTH), 0.45 + WIDTH / 2.0)

    def test_yaw_offset_persists_downstream(self):
        spine = evaluate_chain([Module("RAT", 0.9, "LEFT"), Straight(1.0)], ORIGIN, WIDTH)
        self.assertAlmostEqual(spine.yaw_offset[-1], math.radians(-90.0))


class RunTests(unittest.TestCase):
    def test_runs_split_at_modules_and_share_boundary_points(self):
        segs = [Straight(1.0), Curve(90, 0.8), Module("RAT", 0.9), Straight(1.0)]
        spine = evaluate_chain(segs, ORIGIN, WIDTH)
        r = runs(spine, segs)
        self.assertEqual([x.is_module for x in r], [False, True, False])
        self.assertEqual(r[0].segment_indices, (0, 1))
        self.assertEqual(r[1].segment_indices, (2,))
        self.assertEqual(r[0].first_index, 0)
        self.assertEqual(r[0].last_index, r[1].first_index)
        self.assertEqual(r[1].last_index, r[2].first_index)
        self.assertEqual(r[2].last_index, len(spine) - 1)
        for i in range(r[1].first_index, r[1].last_index + 1):
            if i > r[1].first_index:
                self.assertEqual(spine.kind[i], KIND_MODULE)

    def test_single_run_when_no_modules(self):
        segs = [Straight(1.0), Incline(10, 1.0)]
        spine = evaluate_chain(segs, ORIGIN, WIDTH, transition_radius_m=1.0)
        r = runs(spine, segs)
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0].first_index, r[0].last_index), (0, len(spine) - 1))

    def test_segment_starts_include_transitions(self):
        segs = [Straight(1.0), Incline(20.0, 1.0), Straight(1.0)]
        starts = segment_starts(segs, WIDTH, transition_radius_m=1.5)
        t = transition_length(0.0, math.radians(20.0), 1.5)
        self.assertAlmostEqual(starts[1], 1.0 + t)
        self.assertAlmostEqual(starts[2], 2.0 + 2 * t)


from model.segments import insert_sample_at  # noqa: E402


class InsertSampleTests(unittest.TestCase):
    def test_insert_on_straight_is_exact_and_keeps_order(self):
        spine = evaluate_chain([Straight(3.0)], ORIGIN, WIDTH)
        insert_sample_at(spine, 1.2)
        self.assertEqual(len(spine), 3)
        self.assertAlmostEqual(spine.y[1], 1.2)
        self.assertAlmostEqual(spine.s[1], 1.2)
        self.assertEqual(spine.segment_index[1], 0)
        for a, b in zip(spine.s, spine.s[1:]):
            self.assertLess(a, b)

    def test_insert_at_existing_sample_or_outside_is_noop(self):
        spine = evaluate_chain([Straight(3.0)], ORIGIN, WIDTH)
        insert_sample_at(spine, 3.0)
        insert_sample_at(spine, 4.0)
        insert_sample_at(spine, -1.0)
        self.assertEqual(len(spine), 2)

    def test_insert_on_incline_interpolates_height(self):
        spine = evaluate_chain([Incline(30.0, 2.0)], ORIGIN, WIDTH)
        insert_sample_at(spine, 1.0)
        i = spine.s.index(1.0)
        self.assertAlmostEqual(spine.z[i], math.sin(math.radians(30.0)))
        self.assertAlmostEqual(spine.incline[i], math.radians(30.0))


from model.segments import incline_from_rise, rise_from_incline, segment_frames, pose_at_s  # noqa: E402


class TestRiseAndFrames(unittest.TestCase):
    def test_rise_roundtrip(self):
        for angle in (5.0, 15.0, -20.0, 30.0):
            rise = rise_from_incline(angle, 3.0)
            self.assertAlmostEqual(incline_from_rise(rise, 3.0), angle, places=9)

    def test_rise_clamped_to_length(self):
        self.assertAlmostEqual(incline_from_rise(5.0, 3.0), 90.0)
        self.assertAlmostEqual(incline_from_rise(-5.0, 3.0), -90.0)
        self.assertEqual(incline_from_rise(1.0, 0.0), 0.0)

    def test_segment_frames_follow_the_chain(self):
        segs = [Straight(3.0), Incline(incline_from_rise(0.5, 2.0), 2.0), Straight(1.0)]
        frames = segment_frames(segs, Pose(0, 0, 0, 0, 0), 0.5)
        self.assertEqual(len(frames), 3)
        s0, e0 = frames[0]
        self.assertAlmostEqual(e0.y, 3.0)
        s1, e1 = frames[1]
        # Hard kink (no nose-over): the incline starts where the straight ends and gains 0.5 m.
        self.assertAlmostEqual(s1.y, 3.0)
        self.assertAlmostEqual(e1.z - s1.z, 0.5, places=9)
        s2, e2 = frames[2]
        self.assertAlmostEqual(s2.z, 0.5, places=9)
        self.assertAlmostEqual(e2.z, 0.5, places=9)

    def test_segment_frames_skip_nose_over(self):
        segs = [Straight(3.0), Incline(15.0, 2.0)]
        frames = segment_frames(segs, Pose(0, 0, 0, 0, 0), 0.5, transition_radius_m=1.5)
        s1, e1 = frames[1]
        # The incline's own footprint begins after the transition arc, already at 15 deg.
        self.assertAlmostEqual(math.degrees(s1.incline), 15.0, places=6)
        self.assertGreater(s1.y, 3.0)
        self.assertAlmostEqual(e1.z - s1.z, 2.0 * math.sin(math.radians(15.0)), places=9)

    def test_pose_at_s_interpolates(self):
        spine = evaluate_chain([Straight(2.0)], Pose(0, 0, 0, 0, 0), 0.5)
        p = pose_at_s(spine, 0.5)
        self.assertAlmostEqual(p.y, 0.5)
        self.assertAlmostEqual(pose_at_s(spine, -1.0).y, 0.0)
        self.assertAlmostEqual(pose_at_s(spine, 9.0).y, 2.0)


from model.junction import CATALOG_ANGLES_DEG, junction_geometry, junction_layout, mirror_layout, snap_angle  # noqa: E402


class TestJunctionGeometry(unittest.TestCase):
    def test_taper_lands_on_the_deck_edge_for_every_catalog_angle(self):
        for angle in CATALOG_ANGLES_DEG:
            for side in (1, -1):
                g = junction_geometry(angle, 0.54, 0.27, side)
                self.assertGreater(g.length_m, 0.5)
                if angle == 90:
                    self.assertEqual(g.fence, [])
                    self.assertAlmostEqual(g.wedge_across_m, 0.0)
                else:
                    self.assertAlmostEqual(g.fence[-1][0], side * 0.27, places=6)
                    self.assertAlmostEqual(g.fence[-2][0], side * 0.27, places=5)
                    self.assertAlmostEqual(g.fence[-1][2], 0.0)
                self.assertEqual(g.outline[0], g.outline[-1])
                if angle == 90:
                    # The main fence opens exactly between the feeder's fence ends, no stubs.
                    self.assertEqual(g.connectors, ())
                    self.assertAlmostEqual(g.y_gap_start, 0.01, places=6)
                    self.assertAlmostEqual(g.y_gap_end, 0.54 - 0.01, places=6)
                else:
                    # The main fence stops just inside the face, where the feeder's inner fence line meets it.
                    self.assertGreaterEqual(g.y_gap_start, g.y_face_start)
                    self.assertLess(g.y_gap_start, g.y_face_start + 0.05)
                    self.assertEqual(g.connectors, ())
                    self.assertGreater(g.y_gap_end, g.y_landing)
                    self.assertLessEqual(g.y_gap_end, g.length_m + 0.1)

    def test_taper_lands_on_a_fence_line_inside_the_deck_edge(self):
        g = junction_geometry(45, 0.54, 0.27, -1, fence_offset_m=0.26)
        self.assertAlmostEqual(g.fence[-2][0], -0.26, places=5)
        self.assertAlmostEqual(g.fence[-1][0], -0.26, places=6)
        # The deck outline never comes inside its own edge.
        self.assertTrue(all(abs(x) >= 0.27 - 1e-9 for x, _y in g.outline if abs(x) > 1e-9))

    def test_face_is_the_infeed_width_long(self):
        g = junction_geometry(45, 0.54, 0.27, 1)
        (x1, y1), (x2, y2) = g.outline[2], g.outline[3]
        self.assertAlmostEqual(math.hypot(x2 - x1, y2 - y1), 0.54, places=9)

    def test_mirror_layout_is_the_outbound_twin(self):
        for angle in CATALOG_ANGLES_DEG:
            for sides in ((1,), (-1,), (1, -1)):
                base = junction_layout(angle, 0.54, 0.27, sides, fence_offset_m=0.26)
                mirrored = mirror_layout(base)
                L = base.length_m
                self.assertAlmostEqual(mirrored.length_m, L)
                # Faces keep their side and move to the downstream end.
                for sd, (fx, fy) in base.faces.items():
                    mx, my = mirrored.faces[sd]
                    self.assertAlmostEqual(mx, fx)
                    self.assertAlmostEqual(my, L - fy)
                    self.assertGreaterEqual(my + 1e-9, L / 2.0)  # the wedge opens downstream (90°: face = whole module)
                # Outline stays closed, inside the same footprint.
                self.assertEqual(mirrored.outline[0], mirrored.outline[-1])
                self.assertTrue(all(-1e-9 <= y <= L + 1e-9 for _x, y in mirrored.outline))
                # Fence openings mirrored too, still ordered start < end.
                self.assertEqual(len(mirrored.gaps), len(base.gaps))
                for (y0, y1, sd), (b0, b1, bsd) in zip(mirrored.gaps, base.gaps):
                    self.assertEqual(sd, bsd)
                    self.assertLess(y0, y1)
                    self.assertAlmostEqual(y0, L - b1)
                    self.assertAlmostEqual(y1, L - b0)
                # Taper fences run in travel direction (+y), ending on the face side.
                for fence, bfence in zip(mirrored.fences, base.fences):
                    self.assertEqual(len(fence), len(bfence))
                    self.assertLessEqual(fence[0][1], fence[-1][1] + 1e-9)
                    self.assertAlmostEqual(fence[0][2], -bfence[-1][2])

    def test_snap_angle(self):
        self.assertEqual(snap_angle(43), 45)
        self.assertEqual(snap_angle(88), 90)
        self.assertEqual(snap_angle(75), 75)  # 2.6: catalog 15..90 in 15-degree steps
        self.assertIsNone(snap_angle(5))
        self.assertIsNone(snap_angle(105))


from model.segments import Spiral, spiral_center, KIND_SPIRAL  # noqa: E402  (lifts: 2.6's tests/test_lift_parts.py)
from model.segments import evaluate_chain as _eval, segment_starts as _starts, runs as _runs  # noqa: E402


class TestSpiralAndLift(unittest.TestCase):
    def test_spiral_climbs_and_turns(self):
        sp = Spiral(720.0, 0.8, "LEFT", rise_m=4.0)
        spine = _eval([sp], Pose(0, 0, 0, 0, 0), 0.5)
        end = spine.pose_at(len(spine) - 1)
        self.assertAlmostEqual(end.z, 4.0, places=6)
        self.assertAlmostEqual(end.heading, math.radians(720.0), places=6)
        self.assertAlmostEqual(end.x, 0.0, places=6)  # two full turns come back over the start
        self.assertAlmostEqual(end.y, 0.0, places=6)
        # 3D length: hypot(plan arc, rise); pitch constant along the helix
        plan = (0.8 + 0.25) * math.radians(720.0)
        self.assertAlmostEqual(spine.length, math.hypot(plan, 4.0), places=6)
        kinds = set(spine.kind[1:])
        self.assertEqual(kinds, {KIND_SPIRAL})
        self.assertTrue(all(abs(p - spine.incline[1]) < 1e-9 for p in spine.incline[1:-1]))  # constant pitch; the last point is the level exit
        cx, cy = spiral_center(Pose(0, 0, 0, 0, 0), sp, 0.5)
        self.assertAlmostEqual(cx, -1.05, places=6)  # left of the start, plan radius 1.05
        self.assertAlmostEqual(cy, 0.0, places=6)

    def test_spiral_between_straights_is_one_conveyor_run(self):
        chain = [Straight(2.0), Spiral(360.0, 0.8, "RIGHT", 3.0), Straight(2.0)]
        spine = _eval(chain, Pose(0, 0, 0, 0, 0), 0.5)
        self.assertEqual(len(_runs(spine, chain)), 1)
        self.assertAlmostEqual(spine.pose_at(len(spine) - 1).z, 3.0, places=6)


from model.segments import Module as _Module  # noqa: E402


class TestArbTurn(unittest.TestCase):
    def test_turn_module_rotates_goods_over_its_length(self):
        arb = _Module("ARB", 1.5, "STRAIGHT", tech="ARB", turn=math.pi / 2.0, side=-1)
        chain = [Straight(1.0), arb, Straight(1.0)]
        spine = _eval(chain, Pose(0, 0, 0, 0, 0), 0.5)
        self.assertAlmostEqual(spine.length, 3.5, places=9)
        # yaw offset 0 up to the module start, +90 deg at its end and after
        k = [i for i, si in enumerate(spine.segment_index) if si == 1]
        self.assertAlmostEqual(spine.yaw_offset[k[0] - 1], 0.0, places=9)
        self.assertAlmostEqual(spine.yaw_offset[k[-1]], math.pi / 2.0, places=9)
        self.assertAlmostEqual(spine.yaw_offset[-1], math.pi / 2.0, places=9)
        self.assertAlmostEqual(spine.pose_at(len(spine) - 1).heading, 0.0, places=9)  # travel heading unchanged
        self.assertEqual(len(_runs(spine, chain)), 3)

    def test_centre_module_is_a_plain_flat_footprint(self):
        arb = _Module("ARB", 1.5, "STRAIGHT", tech="ARB", center=True)
        spine = _eval([Straight(1.0), arb], Pose(0, 0, 0, 0, 0), 0.5)
        self.assertAlmostEqual(spine.length, 2.5, places=9)
        self.assertTrue(all(abs(y) < 1e-12 for y in spine.yaw_offset))
