"""Unit tests for pi3/web.py's pure helpers: no flask/cv2 needed.

    python3 -m unittest discover tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi3"))

from web import build_mjpeg_chunk, compute_fps  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
