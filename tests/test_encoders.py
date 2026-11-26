"""Unit tests for pico/encoders.py's pure helpers: no hardware needed.

    python3 -m unittest discover tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pico"))

from encoders import compute_rate, decode_step  # noqa: E402


class TestDecodeStep(unittest.TestCase):
    def test_b_low_is_plus_one(self):
        self.assertEqual(decode_step(0, 1), 1)

    def test_b_high_is_minus_one(self):
        self.assertEqual(decode_step(1, 1), -1)

    def test_sign_flips_both(self):
        self.assertEqual(decode_step(0, -1), -1)
        self.assertEqual(decode_step(1, -1), 1)


class TestComputeRate(unittest.TestCase):
    def test_counts_per_second(self):
        self.assertEqual(compute_rate(120, 100, 0.5), 40.0)

    def test_negative_direction(self):
        self.assertEqual(compute_rate(80, 100, 0.5), -40.0)

    def test_zero_dt_is_safe(self):
        self.assertEqual(compute_rate(120, 100, 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
