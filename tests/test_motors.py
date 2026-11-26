"""Unit tests for pico/motors.py's pure helpers: no hardware needed.

    python3 -m unittest discover tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pico"))

from motors import apply_dead_band, mix_steer, ramp_toward  # noqa: E402


class TestMixSteer(unittest.TestCase):
    def test_straight_is_equal(self):
        self.assertEqual(mix_steer(0.0, 0.5), (0.5, 0.5))

    def test_positive_steer_turns_right(self):
        left, right = mix_steer(0.4, 0.5)
        self.assertGreater(left, right)

    def test_scales_down_when_over_range(self):
        left, right = mix_steer(1.0, 1.0)
        self.assertLessEqual(max(abs(left), abs(right)), 1.0)

    def test_stays_unscaled_within_range(self):
        left, right = mix_steer(0.2, 0.3)
        self.assertAlmostEqual(left, 0.4)
        self.assertAlmostEqual(right, 0.2)


class TestRampToward(unittest.TestCase):
    def test_reaches_target_within_limit(self):
        self.assertEqual(ramp_toward(0.0, 0.1, dt=1.0, ramp_up_per_s=1.5, ramp_down_per_s=3.0), 0.1)

    def test_speeding_up_is_capped_at_ramp_up(self):
        result = ramp_toward(0.0, 1.0, dt=0.1, ramp_up_per_s=1.5, ramp_down_per_s=3.0)
        self.assertAlmostEqual(result, 0.15)

    def test_slowing_down_uses_the_faster_ramp_down(self):
        result = ramp_toward(1.0, 0.0, dt=0.1, ramp_up_per_s=1.5, ramp_down_per_s=3.0)
        self.assertAlmostEqual(result, 0.7)

    def test_already_at_target_is_a_no_op(self):
        self.assertEqual(ramp_toward(0.3, 0.3, dt=1.0, ramp_up_per_s=1.5, ramp_down_per_s=3.0), 0.3)


class TestApplyDeadBand(unittest.TestCase):
    def test_lifts_small_positive(self):
        self.assertEqual(apply_dead_band(0.05, 0.12), 0.12)

    def test_lifts_small_negative(self):
        self.assertEqual(apply_dead_band(-0.05, 0.12), -0.12)

    def test_leaves_zero_alone(self):
        self.assertEqual(apply_dead_band(0.0, 0.12), 0.0)

    def test_leaves_large_values_alone(self):
        self.assertEqual(apply_dead_band(0.5, 0.12), 0.5)


if __name__ == "__main__":
    unittest.main()
