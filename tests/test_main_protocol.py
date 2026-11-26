"""Unit tests for pico/main.py's pure protocol/failsafe logic: no hardware needed.

    python3 -m unittest discover tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pico"))

from main import State, apply_command, check_failsafe, parse_line  # noqa: E402


class TestParseLine(unittest.TestCase):
    def test_m_command(self):
        self.assertEqual(parse_line("M,0.5,-0.25"), ("M", (0.5, -0.25)))

    def test_s_command(self):
        self.assertEqual(parse_line("S,1,0.3"), ("S", (1.0, 0.3)))

    def test_h_command(self):
        self.assertEqual(parse_line("H,42"), ("H", (42,)))

    def test_r_and_x_commands(self):
        self.assertEqual(parse_line("R"), ("R", ()))
        self.assertEqual(parse_line("X"), ("X", ()))

    def test_rejects_garbage(self):
        self.assertIsNone(parse_line(""))
        self.assertIsNone(parse_line("Z,1,2"))
        self.assertIsNone(parse_line("M,abc,2"))
        self.assertIsNone(parse_line("M,1"))


class TestApplyCommand(unittest.TestCase):
    def test_m_sets_targets_and_timestamp(self):
        state = State()
        apply_command(state, "M", (0.4, -0.4), now_ms=1000)
        self.assertEqual(state.target_left, 0.4)
        self.assertEqual(state.target_right, -0.4)
        self.assertEqual(state.last_command_ms, 1000)

    def test_s_mixes_steer(self):
        state = State()
        apply_command(state, "S", (1.0, 0.5), now_ms=1000)
        self.assertEqual(state.target_left, 1.0)
        self.assertEqual(state.target_right, 0.0)

    def test_heartbeat_marks_seen(self):
        state = State()
        apply_command(state, "H", (7,), now_ms=2000)
        self.assertTrue(state.heartbeat_seen)
        self.assertEqual(state.last_heartbeat_ms, 2000)

    def test_x_zeroes_targets_and_current(self):
        state = State()
        state.target_left = 0.9
        state.current_left = 0.5
        apply_command(state, "X", (), now_ms=3000)
        self.assertEqual(state.target_left, 0.0)
        self.assertEqual(state.current_left, 0.0)


class TestCheckFailsafe(unittest.TestCase):
    def test_no_command_yet_trips(self):
        self.assertTrue(check_failsafe(None, None, False, 300, 600))

    def test_fresh_command_is_ok(self):
        self.assertFalse(check_failsafe(50, None, False, 300, 600))

    def test_stale_command_trips(self):
        self.assertTrue(check_failsafe(301, None, False, 300, 600))

    def test_heartbeat_only_matters_once_seen(self):
        self.assertFalse(check_failsafe(50, None, False, 300, 600))
        self.assertTrue(check_failsafe(50, 601, True, 300, 600))
        self.assertFalse(check_failsafe(50, 599, True, 300, 600))


if __name__ == "__main__":
    unittest.main()
