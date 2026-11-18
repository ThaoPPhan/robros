"""Unit tests for detector.py on synthetic images.

Run:  python3 -m unittest discover -s tests -v     (from the project folder)
"""
import os
import sys
import unittest

import cv2
import numpy as np
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from detector import LineDetector  # noqa: E402

W, H = 320, 240
BLUE_TAPE = (210, 140, 50)      # BGR, typical light-blue painter's tape
GREEN_TAPE = (70, 170, 60)      # BGR, typical green painter's tape
GREEN_HSV = ([35, 80, 40], [85, 255, 255])


def base_cfg():
    with open(os.path.join(ROOT, "config.yaml")) as f:
        cfg = yaml.safe_load(f)["detector"]
    cfg["mode"] = "center"
    return cfg


def floor(seed=0):
    """Grey concrete with mild noise and a brightness gradient."""
    rng = np.random.default_rng(seed)
    g = np.linspace(110, 150, H)[:, None, None]
    img = g + rng.normal(0, 6, (H, W, 1))
    img = np.repeat(img, 3, axis=2) + np.array([0, 2, 4])   # slightly warm grey
    return np.clip(img, 0, 255).astype(np.uint8)


def x_at(y, x_bottom, angle_deg):
    """Line through (x_bottom, H-1) leaning angle_deg to the right going up."""
    return x_bottom + np.tan(np.radians(angle_deg)) * (H - 1 - y)


def draw_line(img, x_bottom, angle_deg, color=BLUE_TAPE, thick=12):
    p0 = (int(round(x_at(H - 1, x_bottom, angle_deg))), H - 1)
    p1 = (int(round(x_at(0, x_bottom, angle_deg))), 0)
    cv2.line(img, p0, p1, color, thick, cv2.LINE_AA)
    return img


class CenterLineTests(unittest.TestCase):
    def setUp(self):
        self.det = LineDetector(base_cfg())

    def run_case(self, x_bottom, angle, **kw):
        self.det.reset()
        img = draw_line(floor(), x_bottom, angle, **kw)
        d, mask = self.det.detect(img)
        return d

    def test_offsets_and_angles(self):
        for x_bottom in (60, 110, 160, 210, 260):
            for angle in (-30, -15, 0, 15, 30):
                with self.subTest(x=x_bottom, angle=angle):
                    d = self.run_case(x_bottom, angle)
                    self.assertFalse(d.lost, d.reason)
                    self.assertAlmostEqual(d.offset, (x_bottom - W / 2) / (W / 2), delta=0.04)
                    self.assertAlmostEqual(d.angle, angle, delta=2.5)
                    self.assertGreater(d.confidence, 0.7)

    def test_sign_conventions(self):
        d = self.run_case(240, 20)            # right of centre, leaning right
        self.assertGreater(d.offset, 0)
        self.assertGreater(d.angle, 0)
        d = self.run_case(80, -20)
        self.assertLess(d.offset, 0)
        self.assertLess(d.angle, 0)

    def test_lookahead_point(self):
        cfg = base_cfg()
        top, bot = int(cfg["roi_top"] * H), H
        y_t = (bot - 1) - cfg["lookahead"] * (bot - top)
        d = self.run_case(140, 20)
        self.assertAlmostEqual(d.target[1], y_t, delta=1)
        self.assertAlmostEqual(d.target[0], x_at(y_t, 140, 20), delta=4)

    def test_no_line_is_lost(self):
        d, _ = self.det.detect(floor())
        self.assertTrue(d.lost)
        self.assertEqual(d.confidence, 0.0)

    def test_line_only_above_roi_is_ignored(self):
        img = floor()
        cv2.line(img, (0, 30), (W, 50), BLUE_TAPE, 12)     # tape across the top
        d, mask = self.det.detect(img)
        self.assertTrue(d.lost)
        self.assertEqual(np.count_nonzero(mask[: int(0.35 * H) - 2]), 0)

    def test_glare_blob_rejected(self):
        img = draw_line(floor(), 160, 0)
        cv2.circle(img, (80, 180), 30, (250, 250, 255), -1)          # bright white glare
        cv2.circle(img, (165, 170), 8, (245, 240, 235), -1)          # glare on the tape
        d, mask = self.det.detect(img)
        self.assertFalse(d.lost)
        self.assertAlmostEqual(d.offset, 0.0, delta=0.05)
        self.assertEqual(np.count_nonzero(mask[150:210, 50:110]), 0)

    def test_distractor_blob_does_not_hijack(self):
        img = draw_line(floor(), 130, 5)
        cv2.rectangle(img, (250, 150), (275, 175), BLUE_TAPE, -1)     # tape scrap
        d, _ = self.det.detect(img)
        self.assertAlmostEqual(d.offset, (130 - 160) / 160, delta=0.05)

    def test_green_tape_with_green_range(self):
        cfg = base_cfg()
        cfg["hsv_low"], cfg["hsv_high"] = GREEN_HSV
        det = LineDetector(cfg)
        img = draw_line(floor(), 200, -10, color=GREEN_TAPE)
        d, _ = det.detect(img)
        self.assertFalse(d.lost)
        self.assertAlmostEqual(d.offset, 0.25, delta=0.04)
        self.assertAlmostEqual(d.angle, -10, delta=2.5)
        # and blue settings do not see green tape
        d2, _ = LineDetector(base_cfg()).detect(img)
        self.assertTrue(d2.lost)

    def test_huge_mask_is_rejected(self):
        img = floor()
        img[100:] = BLUE_TAPE        # whole floor "matches" -> HSV range must be wrong
        d, _ = self.det.detect(img)
        self.assertTrue(d.lost)
        self.assertIn("mask too large", d.reason)

    def test_resolution_640(self):
        cfg = base_cfg()
        det = LineDetector(cfg)
        img = cv2.resize(draw_line(floor(), 200, 12), (640, 480))
        d, _ = det.detect(img)
        self.assertFalse(d.lost)
        self.assertAlmostEqual(d.offset, 0.25, delta=0.04)
        self.assertAlmostEqual(d.angle, 12, delta=2.5)


class LaneTests(unittest.TestCase):
    def setUp(self):
        cfg = base_cfg()
        cfg["mode"] = "lane"
        self.det = LineDetector(cfg)

    def lane(self, center_bottom, half_width, angle):
        img = floor()
        draw_line(img, center_bottom - half_width, angle)
        draw_line(img, center_bottom + half_width, angle)
        return img

    def test_lane_center_offsets(self):
        for c in (130, 160, 190):
            for angle in (-15, 0, 15):
                with self.subTest(c=c, angle=angle):
                    self.det.reset()
                    d, _ = self.det.detect(self.lane(c, 100, angle))
                    self.assertFalse(d.lost, d.reason)
                    self.assertAlmostEqual(d.offset, (c - 160) / 160, delta=0.04)
                    self.assertAlmostEqual(d.angle, angle, delta=2.5)
                    self.assertEqual(len(d.edges), len(d.points))

    def test_one_boundary_uses_learned_width(self):
        # learn the width with both lines, then hide the right one
        for _ in range(15):
            self.det.detect(self.lane(160, 90, 0))
        img = floor()
        draw_line(img, 160 - 90, 0)
        d, _ = self.det.detect(img)
        self.assertFalse(d.lost, d.reason)
        self.assertAlmostEqual(d.offset, 0.0, delta=0.06)
        both, _ = self.det.detect(self.lane(160, 90, 0))
        self.assertLess(d.confidence, both.confidence)   # one side = less confident

    def test_empty_lane_lost(self):
        d, _ = self.det.detect(floor())
        self.assertTrue(d.lost)


if __name__ == "__main__":
    unittest.main()
