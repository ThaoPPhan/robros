import os
import sys
import unittest

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from controller import Controller  # noqa: E402
from detector import Detection  # noqa: E402


def cfg(**kw):
    with open(os.path.join(ROOT, "config.yaml")) as f:
        c = yaml.safe_load(f)["controller"]
    c.update(steer_smoothing=0.0, start_armed=True)
    c.update(kw)
    return c


def det(offset=0.0, angle=0.0, conf=1.0, lost=False, tx=160, ty=120):
    return Detection(offset=offset, angle=angle, confidence=conf, lost=lost, target=(tx, ty))


class ControllerTests(unittest.TestCase):
    def test_lost_stops(self):
        cmd = Controller(cfg()).update(det(offset=0.5, lost=True))
        self.assertEqual((cmd.steer, cmd.speed), (0.0, 0.0))
        self.assertTrue(cmd.lost)

    def test_steer_sign(self):
        c = Controller(cfg())
        self.assertGreater(c.update(det(offset=0.3)).steer, 0)
        self.assertLess(c.update(det(offset=-0.3)).steer, 0)
        self.assertGreater(c.update(det(angle=20)).steer, 0)

    def test_straight_full_speed_curve_slower(self):
        c = Controller(cfg())
        straight = c.update(det()).speed
        curve = c.update(det(angle=30, offset=0.2)).speed
        self.assertAlmostEqual(straight, cfg()["max_speed"])
        self.assertLess(curve, straight)
        self.assertGreaterEqual(curve, cfg()["min_speed"])

    def test_low_confidence_slower(self):
        c = Controller(cfg())
        self.assertLess(c.update(det(conf=0.4)).speed, c.update(det(conf=1.0)).speed)

    def test_disarmed_zero_speed(self):
        cmd = Controller(cfg(start_armed=False)).update(det(offset=0.3))
        self.assertEqual(cmd.speed, 0.0)
        self.assertGreater(cmd.steer, 0)

    def test_pure_pursuit(self):
        c = Controller(cfg(method="pure_pursuit"))
        self.assertAlmostEqual(c.update(det(tx=160)).steer, 0.0)
        self.assertGreater(c.update(det(tx=220)).steer, 0)
        self.assertLess(c.update(det(tx=100)).steer, 0)
        self.assertLessEqual(abs(c.update(det(tx=319, ty=230)).steer), 1.0)

    def test_clipped(self):
        cmd = Controller(cfg()).update(det(offset=1.0, angle=60))
        self.assertLessEqual(cmd.steer, 1.0)


if __name__ == "__main__":
    unittest.main()
