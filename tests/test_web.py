"""Unit tests for pi3/web.py's pure helpers: no flask/cv2 needed.

    python3 -m unittest discover tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi3"))

from web import CommandWatch, build_mjpeg_chunk, compute_fps, compute_wheel_command  # noqa: E402


class TestBuildMjpegChunk(unittest.TestCase):
    def test_wraps_bytes_with_boundary_and_headers(self):
        chunk = build_mjpeg_chunk(b"abc")
        self.assertTrue(chunk.startswith(b"--frame\r\n"))
        self.assertIn(b"Content-Type: image/jpeg\r\n", chunk)
        self.assertIn(b"Content-Length: 3\r\n\r\n", chunk)
        self.assertTrue(chunk.endswith(b"abc\r\n"))

    def test_content_length_matches_byte_count(self):
        chunk = build_mjpeg_chunk(b"x" * 100)
        self.assertIn(b"Content-Length: 100\r\n\r\n", chunk)

    def test_empty_bytes(self):
        chunk = build_mjpeg_chunk(b"")
        self.assertIn(b"Content-Length: 0\r\n\r\n", chunk)


class TestComputeFps(unittest.TestCase):
    def test_normal(self):
        self.assertAlmostEqual(compute_fps(60, 2.0), 30.0)

    def test_zero_elapsed_is_safe(self):
        self.assertEqual(compute_fps(10, 0.0), 0.0)

    def test_zero_frames(self):
        self.assertEqual(compute_fps(0, 2.0), 0.0)


class TestComputeWheelCommand(unittest.TestCase):
    def test_no_keys_is_stopped(self):
        self.assertEqual(compute_wheel_command(set(), 0.5, 0.6, 0.5), (0.0, 0.0))

    def test_w_drives_both_wheels_forward(self):
        self.assertEqual(compute_wheel_command({"w"}, 0.5, 0.6, 0.5), (0.5, 0.5))

    def test_s_drives_both_wheels_backward(self):
        self.assertEqual(compute_wheel_command({"s"}, 0.5, 0.6, 0.5), (-0.5, -0.5))

    def test_opposing_keys_cancel(self):
        self.assertEqual(compute_wheel_command({"w", "s"}, 0.5, 0.6, 0.5), (0.0, 0.0))

    def test_a_turns_in_place_left(self):
        left, right = compute_wheel_command({"a"}, 0.5, 0.6, 0.5)
        self.assertAlmostEqual(left, -0.3)
        self.assertAlmostEqual(right, 0.3)

    def test_d_turns_in_place_right(self):
        left, right = compute_wheel_command({"d"}, 0.5, 0.6, 0.5)
        self.assertAlmostEqual(left, 0.3)
        self.assertAlmostEqual(right, -0.3)

    def test_q_arcs_left_while_moving_forward(self):
        left, right = compute_wheel_command({"q"}, 0.5, 0.6, 0.5)
        self.assertGreater(left, 0.0)
        self.assertGreater(right, 0.0)
        self.assertLess(left, right)

    def test_e_arcs_right_while_moving_forward(self):
        left, right = compute_wheel_command({"e"}, 0.5, 0.6, 0.5)
        self.assertGreater(left, 0.0)
        self.assertGreater(right, 0.0)
        self.assertLess(right, left)

    def test_output_is_clamped_to_unit_range(self):
        left, right = compute_wheel_command({"w", "q"}, 1.0, 0.6, 0.5)
        self.assertLessEqual(abs(left), 1.0)
        self.assertLessEqual(abs(right), 1.0)


class TestCommandWatch(unittest.TestCase):
    def test_not_stale_right_after_touch(self):
        clock = [100.0]
        watch = CommandWatch(0.3, clock=lambda: clock[0])
        watch.touch()
        clock[0] += 0.1
        self.assertFalse(watch.is_stale())

    def test_stale_once_timeout_elapses(self):
        clock = [100.0]
        watch = CommandWatch(0.3, clock=lambda: clock[0])
        watch.touch()
        clock[0] += 0.5
        self.assertTrue(watch.is_stale())


if __name__ == "__main__":
    unittest.main()
