"""Unit tests for pi3/pico_link.py's telemetry parser: no hardware needed.

    python3 -m unittest discover tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi3"))

from pico_link import parse_telemetry_line  # noqa: E402


class TestParseTelemetryLine(unittest.TestCase):
    def test_valid_line(self):
        result = parse_telemetry_line("E,12345,10,-5,2.0,-1.0,0.3,-0.3,0")
        self.assertEqual(result, {
            "ms": 12345,
            "count_left": 10,
            "count_right": -5,
            "rate_left": 2.0,
            "rate_right": -1.0,
            "out_left": 0.3,
            "out_right": -0.3,
            "failsafe": False,
        })

    def test_failsafe_flag_true(self):
        result = parse_telemetry_line("E,1,0,0,0,0,0,0,1")
        self.assertTrue(result["failsafe"])

    def test_rejects_wrong_kind(self):
        self.assertIsNone(parse_telemetry_line("M,1,2"))

    def test_rejects_wrong_field_count(self):
        self.assertIsNone(parse_telemetry_line("E,1,2,3"))

    def test_rejects_non_numeric_fields(self):
        self.assertIsNone(parse_telemetry_line("E,x,y,z,a,b,c,d,e"))


if __name__ == "__main__":
    unittest.main()
