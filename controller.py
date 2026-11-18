"""Detection -> steering (-1..+1, + = turn right) and speed (0..1)."""

import math
from dataclasses import dataclass


@dataclass
class Command:
    steer: float = 0.0
    speed: float = 0.0
    confidence: float = 0.0
    lost: bool = True
    armed: bool = False


class Controller:
    def __init__(self, cfg, frame_size=(320, 240)):
        self.cfg = dict(cfg)
        self.w, self.h = frame_size
        self.armed = bool(cfg.get("start_armed", False))
        self._steer = 0.0

    def update(self, det):
        c = self.cfg
        if det.lost or det.target is None:
            self._steer = 0.0
            return Command(0.0, 0.0, det.confidence, True, self.armed)

        if c.get("method", "proportional") == "pure_pursuit":
            # vector from the robot (bottom centre of the image) to the look-ahead point
            dx = det.target[0] - self.w / 2.0
            dy = max(1.0, (self.h - 1) - det.target[1])
            alpha = math.atan2(dx, dy)
            ld = math.hypot(dx, dy) / self.h
            raw = c.get("kp_pursuit", 0.4) * 2.0 * math.sin(alpha) / max(ld, 0.05)
        else:
            raw = c.get("kp_offset", 0.8) * det.offset + c.get("kp_angle", 0.5) * det.angle / 45.0
        raw = _clip(raw, -1.0, 1.0)

        a = _clip(c.get("steer_smoothing", 0.3), 0.0, 0.95)
        self._steer = a * self._steer + (1 - a) * raw
        steer = _clip(self._steer, -1.0, 1.0)

        # slow down in curves (large heading angle or big steering) and on low confidence
        curve = max(abs(det.angle) / max(1e-3, c.get("curve_angle_full", 35.0)), abs(steer))
        speed = c.get("max_speed", 0.5) * (1 - c.get("curve_slowdown", 0.6) * min(1.0, curve))
        speed *= min(1.0, det.confidence / max(1e-3, c.get("full_confidence", 0.7)))
        speed = _clip(max(speed, c.get("min_speed", 0.2)), 0.0, 1.0)
        if not self.armed:
            speed = 0.0
        return Command(steer, speed, det.confidence, False, self.armed)


def _clip(v, lo, hi):
    return lo if v < lo else hi if v > hi else v
