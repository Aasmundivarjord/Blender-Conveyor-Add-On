import unittest

from model.throughput import required_speed_m_s, throughput_ph


class ThroughputTests(unittest.TestCase):
    def test_one_item_per_metre_per_second(self):
        self.assertAlmostEqual(required_speed_m_s(3600.0, 1.0), 1.0)
        self.assertAlmostEqual(throughput_ph(1.0, 1.0), 3600.0)

    def test_totes_at_twelve_thousand_an_hour(self):
        # 600 mm totes with the 0.38 m gap the merge needs: 0.98 m pitch.
        v = required_speed_m_s(12000.0, 0.979)
        self.assertAlmostEqual(v, 3.263, places=3)
        self.assertAlmostEqual(throughput_ph(v, 0.979), 12000.0, places=6)

    def test_degenerate_inputs(self):
        self.assertEqual(required_speed_m_s(0.0, 0.8), 0.0)
        self.assertEqual(required_speed_m_s(-5.0, 0.8), 0.0)
        self.assertEqual(throughput_ph(1.0, 0.0), 0.0)
        self.assertEqual(throughput_ph(-1.0, 0.5), 7200.0)


if __name__ == "__main__":
    unittest.main()
