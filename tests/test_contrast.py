"""Overlay colours read on a light AND a dark viewport (suite UI rule,
2026-10-13). Pure Python: python3 -m unittest tests.test_contrast (from dev/)."""
import unittest

from _wh import contrast as C  # (model/contrast.py moved to warehouse_common 0.3)

LIGHT_BG = (0.95, 0.95, 0.95)  # Åsmund's light theme
WHITE_BG = (1.0, 1.0, 1.0)
DARK_BG = (0.188, 0.188, 0.188)  # Blender's default dark viewport (0x303030)
DARKER_BG = (0.10, 0.10, 0.10)


class ContrastTests(unittest.TestCase):
    def test_luminance_and_ratio(self):
        self.assertAlmostEqual(C.contrast((0, 0, 0), (1, 1, 1)), 21.0, places=3)
        self.assertAlmostEqual(C.contrast((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)), 1.0)

    def test_light_or_dark(self):
        self.assertTrue(C.is_light(LIGHT_BG) and C.is_light(WHITE_BG))
        self.assertFalse(C.is_light(DARK_BG) or C.is_light(DARKER_BG))

    def test_strokes_and_accents_read_on_their_background(self):
        for bg in (LIGHT_BG, WHITE_BG, DARK_BG, DARKER_BG):
            p = C.palette(bg)
            self.assertGreaterEqual(C.contrast(p["stroke"], bg), 7.0, (bg, "stroke"))
            for name in C.ACCENTS:
                self.assertGreaterEqual(C.contrast(p[name], bg), 3.0, (bg, name))  # WCAG non-text contrast

    def test_halo_is_the_opposite_tone(self):
        self.assertGreater(C.luminance(C.palette(LIGHT_BG)["halo"]), 0.9)
        self.assertLess(C.luminance(C.palette(DARK_BG)["halo"]), 0.01)

    def test_text_reads_on_its_box(self):
        for bg in (LIGHT_BG, DARK_BG):
            p = C.palette(bg)
            for box in ("box", "box_hover"):
                self.assertGreaterEqual(C.contrast(p["text"], p[box][:3]), 7.0, (bg, box))
            for name in C.ACCENTS:  # a tag on an accent box picks its own ink
                fill = p[name]
                self.assertGreaterEqual(C.contrast(C.text_on(fill), fill), 4.5, (bg, name))

    def test_light_box_stands_off_a_light_background_by_its_edge(self):
        p = C.palette(LIGHT_BG)
        self.assertGreaterEqual(C.contrast(p["box_edge"][:3], LIGHT_BG), 4.5)


if __name__ == "__main__":
    unittest.main()
