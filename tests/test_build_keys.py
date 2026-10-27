"""Build mode's keys (model/build_keys.py). Pure Python: python3 -m unittest tests.test_build_keys (from dev/)."""
import unittest

from model.build_keys import HINT, adjust, key_action

RADII = [("r600", 600.0, "metric"), ("r610", 609.6, "imperial"), ("r800", 800.0, "metric"), ("r1219", 1219.2, "imperial")]


class BuildKeysTests(unittest.TestCase):
    def test_the_plain_arrows_build(self):
        self.assertEqual(key_action('UP_ARROW', 'PRESS'), "add:STRAIGHT")
        self.assertEqual(key_action('LEFT_ARROW', 'PRESS'), "add:CURVE_LEFT")
        self.assertEqual(key_action('RIGHT_ARROW', 'PRESS'), "add:CURVE_RIGHT")
        self.assertEqual(key_action('DOWN_ARROW', 'PRESS'), "more")

    def test_backspace_removes_enter_and_esc_end(self):
        self.assertEqual(key_action('BACK_SPACE', 'PRESS'), "remove")
        self.assertEqual(key_action('DEL', 'PRESS'), "remove")
        for key in ('RET', 'NUMPAD_ENTER', 'ESC'):
            self.assertEqual(key_action(key, 'PRESS'), "end")

    def test_releases_and_repeats_pass(self):
        self.assertIsNone(key_action('UP_ARROW', 'RELEASE'))
        self.assertIsNone(key_action('UP_ARROW', 'CLICK'))

    def test_shift_tunes_the_piece_just_added_ctrl_or_cmd_its_height(self):
        self.assertEqual(key_action('UP_ARROW', 'PRESS', shift=True), "adjust:longer")
        self.assertEqual(key_action('DOWN_ARROW', 'PRESS', shift=True), "adjust:shorter")
        self.assertEqual(key_action('LEFT_ARROW', 'PRESS', shift=True), "adjust:left")
        self.assertEqual(key_action('RIGHT_ARROW', 'PRESS', shift=True), "adjust:right")
        for mod in ({"ctrl": True}, {"oskey": True}):  # Cmd: macOS keeps Ctrl + up / down for Mission Control
            self.assertEqual(key_action('UP_ARROW', 'PRESS', **mod), "adjust:up")
            self.assertEqual(key_action('DOWN_ARROW', 'PRESS', **mod), "adjust:down")

    def test_other_modifiers_are_not_build_mode_s(self):
        # Alt + arrows have their own keymap, Ctrl / Cmd + Z is undo, mixed modifiers are Blender's
        self.assertIsNone(key_action('UP_ARROW', 'PRESS', alt=True))
        self.assertIsNone(key_action('Z', 'PRESS', ctrl=True))
        self.assertIsNone(key_action('Z', 'PRESS', oskey=True))
        self.assertIsNone(key_action('LEFT_ARROW', 'PRESS', ctrl=True))
        self.assertIsNone(key_action('UP_ARROW', 'PRESS', shift=True, ctrl=True))
        self.assertIsNone(key_action('BACK_SPACE', 'PRESS', shift=True))

    def test_a_straight_grows_and_shrinks_by_the_catalogue_step(self):
        s = {"kind": 'STRAIGHT', "length_mm": 3000.0, "rise_mm": 0.0}
        self.assertEqual(adjust(s, "longer")[0], {"length_mm": 3150.0})
        self.assertEqual(adjust(s, "shorter")[0], {"length_mm": 2850.0})
        self.assertIsNone(adjust({**s, "length_mm": 150.0}, "shorter")[0])
        self.assertIn("steer a curve", adjust(s, "left")[1])

    def test_a_curve_steers_15_degrees_and_flips_through_straight(self):
        c = {"kind": 'CURVE', "angle_deg": 90.0, "direction": 'LEFT', "radius_id": "r800", "custom_radius_mm": 800.0}
        self.assertEqual(adjust(c, "left")[0], {"curve_angle_deg": 105, "curve_direction": 'LEFT'})
        self.assertEqual(adjust(c, "right")[0], {"curve_angle_deg": 75, "curve_direction": 'LEFT'})
        self.assertEqual(adjust({**c, "angle_deg": 15.0}, "right")[0], {"curve_angle_deg": 15, "curve_direction": 'RIGHT'})
        self.assertEqual(adjust({**c, "direction": 'RIGHT'}, "right")[0], {"curve_angle_deg": 105, "curve_direction": 'RIGHT'})
        self.assertIsNone(adjust({**c, "angle_deg": 180.0}, "left")[0])

    def test_a_curve_s_radius_steps_through_its_own_system(self):
        c = {"kind": 'CURVE', "angle_deg": 90.0, "direction": 'LEFT', "radius_id": "r600", "custom_radius_mm": 800.0}
        self.assertEqual(adjust(c, "longer", RADII)[0], {"curve_radius": "r800"})  # metric to metric, not 609.6
        self.assertIsNone(adjust(c, "shorter", RADII)[0])
        self.assertEqual(adjust({**c, "radius_id": "CUSTOM"}, "longer", RADII)[0], {"custom_radius_mm": 900.0})

    def test_height_raises_a_straight_and_keeps_a_spiral_s_way(self):
        s = {"kind": 'STRAIGHT', "length_mm": 3000.0, "rise_mm": 0.0}
        self.assertEqual(adjust(s, "up")[0], {"rise_mm": 100.0})
        self.assertEqual(adjust(s, "down")[0], {"rise_mm": -100.0})
        self.assertEqual(adjust({**s, "rise_mm": 100.0}, "down"), ({"rise_mm": 0.0}, "Level"))
        sp = {"kind": 'SPIRAL', "rise_mm": 3000.0}
        self.assertEqual(adjust(sp, "up")[0], {"rise_mm": 3100.0})
        self.assertIsNone(adjust({**sp, "rise_mm": 100.0}, "down")[0])  # never flips: the panel's Spiral Down does
        self.assertEqual(adjust({"kind": 'MODULE', "module": 'LIFT', "rise_mm": -2000.0}, "down")[0], {"rise_mm": -2100.0})
        self.assertIsNone(adjust({"kind": 'CURVE', "angle_deg": 90.0, "direction": 'LEFT', "rise_mm": 0.0}, "up")[0])
        self.assertIsNone(adjust({"kind": 'MODULE', "module": 'RAT', "rise_mm": 0.0}, "up")[0])

    def test_everything_else_passes_through(self):
        for event in ('MIDDLEMOUSE', 'WHEELUPMOUSE', 'TRACKPADPAN', 'MOUSEMOVE', 'LEFTMOUSE', 'RIGHTMOUSE', 'NUMPAD_1', 'G', 'TAB'):
            self.assertIsNone(key_action(event, 'PRESS'), event)

    def test_the_hint_names_every_key(self):
        for word in ("Straight", "Curve L", "Curve R", "More", "Shift", "Height", "Backspace", "Enter", "Esc"):
            self.assertIn(word, HINT)


if __name__ == "__main__":
    unittest.main()
