"""Unit test confirming Camera's constructor touches no hardware: no
picamera2/cv2 needed just to import pi3/camera.py and build one.

    python3 -m unittest discover tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi3"))

from camera import Camera  # noqa: E402


class TestCameraInit(unittest.TestCase):
    def test_stores_config_without_importing_hardware_libs(self):
        cam = Camera("usb", [320, 240], usb_index=1)
        self.assertEqual(cam.backend, "usb")
        self.assertEqual(cam.size, (320, 240))
        self.assertEqual(cam.usb_index, 1)

    def test_size_is_always_a_tuple(self):
        cam = Camera("picamera2", (640, 480))
        self.assertEqual(cam.size, (640, 480))


if __name__ == "__main__":
    unittest.main()
