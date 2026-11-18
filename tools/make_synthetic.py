#!/usr/bin/env python3
"""Generate synthetic camera-like test frames: a tape course on grey concrete seen
through a tilted forward camera (perspective), with glare spots.

  python3 tools/make_synthetic.py samples/synthetic [--lane] [--green] [--video]
"""
import argparse
import os

import cv2
import numpy as np

W, H = 320, 240
BLUE, GREEN = (210, 140, 50), (70, 170, 60)


def course(n=60, lane=False):
    """Top-down 800x1600 'floor' maps; robot drives along an S-curve."""
    rng = np.random.default_rng(1)
    big_w, big_h = 800, 4000
    base = (rng.normal(128, 7, (big_h, big_w, 1)) + np.linspace(-10, 10, big_w)[None, :, None])
    base = np.clip(np.repeat(base, 3, 2) + [0, 2, 5], 0, 255).astype(np.uint8)
    ys = np.arange(big_h)
    xs = big_w / 2 + 160 * np.sin(ys / 450.0) + 60 * np.sin(ys / 170.0)
    return base, xs


def render(base, xs, y_robot, color, lane, glare_seed):
    big_h, big_w = base.shape[:2]
    img = base.copy()
    pts = np.stack([xs, np.arange(big_h)], 1).astype(np.int32)
    if lane:
        for d in (-110, 110):
            cv2.polylines(img, [pts + [d, 0]], False, color, 26, cv2.LINE_AA)
    else:
        cv2.polylines(img, [pts], False, color, 26, cv2.LINE_AA)
    rng = np.random.default_rng(glare_seed)
    # window of floor in front of the robot: robot at (xs[y_robot], y_robot) looking "up"
    cx = xs[y_robot]
    heading = np.arctan2(xs[y_robot - 40] - xs[y_robot + 40], 80)
    near, far, half_near, half_far = 0, 700, 170, 520
    c, s = np.cos(heading), np.sin(heading)

    def floor_pt(lat, fwd):
        return [cx + lat * c + fwd * s, y_robot - fwd * c + lat * s]
    src = np.float32([floor_pt(-half_far, far), floor_pt(half_far, far),
                      floor_pt(half_near, near), floor_pt(-half_near, near)])
    dst = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
    M = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(img, M, (W, H), flags=cv2.INTER_AREA, borderMode=cv2.BORDER_REFLECT)
    for _ in range(rng.integers(0, 3)):           # glare from ceiling lights
        g = np.zeros((H, W), np.float32)
        cv2.ellipse(g, (int(rng.uniform(40, 280)), int(rng.uniform(20, 200))),
                    (int(rng.uniform(15, 40)), int(rng.uniform(6, 18))), 0, 0, 360, 1.0, -1)
        g = cv2.GaussianBlur(g, (0, 0), 6)[..., None]
        out = np.clip(out * (1 - g) + 252 * g, 0, 255).astype(np.uint8)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--lane", action="store_true")
    ap.add_argument("--green", action="store_true")
    ap.add_argument("--video", action="store_true", help="also write course.mp4")
    ap.add_argument("-n", type=int, default=60)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    base, xs = course(lane=a.lane)
    color = GREEN if a.green else BLUE
    vw = None
    if a.video:
        vw = cv2.VideoWriter(os.path.join(a.out, "course.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 20, (W, H))
    for i, y in enumerate(np.linspace(3800, 900, a.n).astype(int)):
        f = render(base, xs, y, color, a.lane, i)
        cv2.imwrite(os.path.join(a.out, f"frame_{i:03d}.png"), f)
        if vw:
            vw.write(f)
    if vw:
        vw.release()
    print(f"wrote {a.n} frames to {a.out}")


if __name__ == "__main__":
    main()
