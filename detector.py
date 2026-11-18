"""Tape line / lane detection from a BGR frame.

Pipeline: blur -> HSV -> inRange -> remove glare (bright & unsaturated) -> open/close
-> cut to the region of interest -> scan N horizontal bands from the bottom up,
tracking the tape blob (center mode) or the two boundary blobs (lane mode) ->
fit the resulting centre points.

Sign conventions (image coordinates, camera looking forward):
  offset  -1..+1   line/lane centre relative to the image centre at the ROI bottom;
                   + = the line is to the RIGHT of the robot.
  angle   degrees  heading of the line going up the image; + = it leans RIGHT
                   (the course bends / points right). Measured in image space, so it is
                   exaggerated by perspective - fine for control, not a true floor angle.
  target  (x, y)   look-ahead point in pixels for pure pursuit.
"""

from dataclasses import dataclass, field

import cv2
import numpy as np

# Keys the calibration page may change live (and save to config.yaml).
TUNABLE = ("mode", "hsv_low", "hsv_high", "roi_top", "roi_bottom", "glare_v_min",
           "glare_s_max", "blur", "open_kernel", "close_kernel")


@dataclass
class Detection:
    offset: float = 0.0
    angle: float = 0.0
    target: tuple = None              # (x, y) look-ahead point, pixels
    target_offset: float = 0.0        # look-ahead point x, normalised -1..+1
    confidence: float = 0.0
    lost: bool = True
    points: list = field(default_factory=list)   # [(x, y, weight)] centre points per band
    edges: list = field(default_factory=list)    # lane mode: [(xl or None, xr or None, y)]
    fit: tuple = None                 # (a, b) with x = a*y + b
    mask_frac: float = 0.0
    reason: str = ""


class LineDetector:
    def __init__(self, cfg):
        self.cfg = {}
        self.update(cfg)
        self._prev_x = None           # bottom centre from last frame (for tracking)
        self._lane_w = None           # learned lane width per band (px)

    # -- parameters --------------------------------------------------------------
    def update(self, cfg):
        """Apply (a subset of) detector config. Safe to call between frames."""
        self.cfg.update(cfg)
        c = self.cfg
        self.mode = c.get("mode", "center")
        if self.mode not in ("center", "lane"):
            raise ValueError("detector.mode must be 'center' or 'lane'")
        self.hsv_low = np.array(c["hsv_low"], np.uint8)
        self.hsv_high = np.array(c["hsv_high"], np.uint8)
        self._k_open = _kernel(c.get("open_kernel", 3))
        self._k_close = _kernel(c.get("close_kernel", 7))
        self._lane_w = None

    def params(self):
        return {k: self.cfg.get(k) for k in TUNABLE}

    # -- mask --------------------------------------------------------------------
    def roi_rows(self, h):
        top = int(round(np.clip(self.cfg.get("roi_top", 0.35), 0, 0.95) * h))
        bot = int(round(np.clip(self.cfg.get("roi_bottom", 1.0), 0.05, 1) * h))
        if bot <= top + 4:
            bot = min(h, top + 5)
        return top, bot

    def make_mask(self, frame):
        """Binary mask (uint8 0/255, full frame size) of tape pixels inside the ROI."""
        h = frame.shape[0]
        top, bot = self.roi_rows(h)
        roi = frame[top:bot]
        b = int(self.cfg.get("blur", 5))
        if b >= 3:
            b |= 1
            roi = cv2.GaussianBlur(roi, (b, b), 0)
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        lo, hi = self.hsv_low, self.hsv_high
        if lo[0] <= hi[0]:
            m = cv2.inRange(hsv, lo, hi)
        else:  # hue range wraps around 180 (only needed for red tape)
            m = cv2.inRange(hsv, lo, np.array([179, hi[1], hi[2]], np.uint8)) | \
                cv2.inRange(hsv, np.array([0, lo[1], lo[2]], np.uint8), hi)
        gv, gs = int(self.cfg.get("glare_v_min", 255)), int(self.cfg.get("glare_s_max", 0))
        if gv < 255 and gs > 0:
            glare = cv2.inRange(hsv, np.array([0, 0, gv], np.uint8),
                                np.array([179, gs, 255], np.uint8))
            m = cv2.bitwise_and(m, cv2.bitwise_not(glare))
        if self._k_open is not None:
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, self._k_open)
        if self._k_close is not None:
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, self._k_close)
        full = np.zeros(frame.shape[:2], np.uint8)
        full[top:bot] = m
        return full

    # -- main entry ----------------------------------------------------------------
    def detect(self, frame):
        mask = self.make_mask(frame)
        return self.analyze(mask), mask

    def analyze(self, mask):
        c = self.cfg
        h, w = mask.shape
        top, bot = self.roi_rows(h)
        roi = mask[top:bot]
        det = Detection()
        det.mask_frac = float(np.count_nonzero(roi)) / roi.size
        if det.mask_frac > c.get("max_mask_frac", 0.5):
            det.reason = "mask too large (check HSV range)"
            self._prev_x = None
            return det

        n = max(3, int(c.get("n_bands", 12)))
        edges_y = np.linspace(top, bot, n + 1).astype(int)
        scale = w / 320.0
        min_run = max(1, c.get("min_run_px", 3) * scale)
        max_run = c.get("max_run_frac", 0.45) * w
        max_jump = c.get("max_jump_frac", 0.15) * w
        fill = c.get("min_band_fill", 0.3)
        cx = w / 2.0

        if self._lane_w is None or len(self._lane_w) != n:
            self._lane_w = np.full(n, c.get("lane_width", 0.6) * w)

        ref = self._prev_x if self._prev_x is not None else cx
        first = True
        pts, edges = [], []
        # bottom band first, so tracking starts near the robot
        for i in range(n - 1, -1, -1):
            y0, y1 = edges_y[i], edges_y[i + 1]
            if y1 <= y0:
                continue
            band = mask[y0:y1]
            prof = np.count_nonzero(band, axis=0) >= max(1, fill * (y1 - y0))
            runs = [r for r in _runs(prof) if min_run <= r[1] - r[0] <= max_run]
            if not runs:
                continue
            centers = [(a + b - 1) / 2.0 for a, b in runs]
            ym = (y0 + y1 - 1) / 2.0
            # the first band found may be further from ref (line may have moved since
            # last frame); afterwards points must be continuous
            jump = max_jump * (3 if first else 1)

            if self.mode == "center":
                j = int(np.argmin([abs(x - ref) for x in centers]))
                x = centers[j]
                if abs(x - ref) > jump and not (first and self._prev_x is None):
                    continue
                pts.append((x, ym, 1.0))
            else:
                left = [x for x in centers if x < ref]
                right = [x for x in centers if x >= ref]
                xl = max(left) if left else None
                xr = min(right) if right else None
                lw = self._lane_w[i]
                # reject a boundary that is implausibly close to the lane centre
                if xl is not None and ref - xl < 0.15 * lw:
                    xl = None
                if xr is not None and xr - ref < 0.15 * lw:
                    xr = None
                if xl is not None and xr is not None:
                    x, wt = (xl + xr) / 2.0, 1.0
                    self._lane_w[i] = 0.8 * lw + 0.2 * (xr - xl)
                elif xl is not None:
                    x, wt = xl + lw / 2.0, 0.6
                elif xr is not None:
                    x, wt = xr - lw / 2.0, 0.6
                else:
                    continue
                if abs(x - ref) > jump and not first:
                    continue
                pts.append((x, ym, wt))
                edges.append((xl, xr, ym))
            ref = x
            first = False

        det.points, det.edges = pts, edges
        if len(pts) < 3:
            det.reason = "too few line points"
            self._prev_x = None
            return det

        P = np.array(pts, float)
        xs, ys, ws = P[:, 0], P[:, 1], P[:, 2]
        a, b = np.polyfit(ys, xs, 1, w=ws)
        det.fit = (float(a), float(b))
        det.angle = float(np.degrees(np.arctan(-a)))

        # offset at the bottom of the ROI: use the fit through the nearest points
        near = P[np.argsort(-ys)[:min(4, len(P))]]
        if len(near) >= 2 and np.ptp(near[:, 1]) > 0:
            an, bn = np.polyfit(near[:, 1], near[:, 0], 1)
            x_bot = an * (bot - 1) + bn
        else:
            x_bot = a * (bot - 1) + b
        det.offset = float(np.clip((x_bot - cx) / cx, -1, 1))

        # look-ahead target: interpolate along detected points, extrapolate with fit
        y_t = (bot - 1) - c.get("lookahead", 0.5) * (bot - top)
        order = np.argsort(ys)
        if ys.min() <= y_t <= ys.max():
            x_t = float(np.interp(y_t, ys[order], xs[order]))
        else:
            x_t = float(a * y_t + b)
        det.target = (float(np.clip(x_t, 0, w - 1)), float(y_t))
        det.target_offset = float(np.clip((x_t - cx) / cx, -1, 1))

        # confidence = coverage x straightness x (lane: both sides seen)
        coverage = min(1.0, ws.sum() / n)
        if len(P) >= 4:
            q = np.polyfit(ys, xs, 2, w=ws)
            resid = xs - np.polyval(q, ys)
        else:
            resid = xs - (a * ys + b)
        rms = float(np.sqrt(np.average(resid ** 2, weights=ws)))
        straight = float(np.clip(1.0 - rms / (0.05 * w), 0, 1))
        near_bonus = 1.0 if ys.max() >= top + 0.6 * (bot - top) else 0.6
        det.confidence = float(np.clip(coverage * (0.5 + 0.5 * straight) * near_bonus, 0, 1))
        det.lost = det.confidence < c.get("min_confidence", 0.35)
        if det.lost:
            det.reason = "low confidence"
            self._prev_x = None
        else:
            self._prev_x = float(np.clip(x_bot, 0, w - 1))
        return det

    def reset(self):
        self._prev_x = None
        self._lane_w = None


def _kernel(k):
    k = int(k or 0)
    if k < 2:
        return None
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def _runs(prof):
    """[(start, end_exclusive)] of True runs in a 1-D bool array."""
    d = np.diff(np.concatenate(([0], prof.astype(np.int8), [0])))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    return list(zip(starts.tolist(), ends.tolist()))


# -- drawing ---------------------------------------------------------------------
def draw_overlay(frame, mask, det, cmd=None, fps=None, top_bot=None, extra=None):
    """Annotated copy of frame: ROI, mask outline, line, look-ahead point and numbers."""
    out = frame.copy()
    h, w = out.shape[:2]
    if top_bot:
        top, bot = top_bot
        out[:top] = (out[:top] * 0.45).astype(np.uint8)  # dim ignored area
        cv2.line(out, (0, top), (w, top), (0, 200, 255), 1)
        if bot < h:
            cv2.line(out, (0, bot - 1), (w, bot - 1), (0, 200, 255), 1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(out, contours, -1, (255, 0, 255), 1)
    for xl, xr, y in det.edges:
        for x in (xl, xr):
            if x is not None:
                cv2.circle(out, (int(x), int(y)), 3, (255, 255, 0), -1)
    col = (0, 0, 255) if det.lost else (0, 255, 0)
    for x, y, _ in det.points:
        cv2.circle(out, (int(x), int(y)), 3, col, -1)
    if det.fit is not None and det.points:
        a, b = det.fit
        y0 = int(min(p[1] for p in det.points))
        y1 = h - 1
        cv2.line(out, (int(a * y0 + b), y0), (int(a * y1 + b), y1), col, 2)
    if det.target is not None:
        tx, ty = int(det.target[0]), int(det.target[1])
        cv2.line(out, (w // 2, h - 1), (tx, ty), (0, 255, 255), 1)
        cv2.circle(out, (tx, ty), 6, (0, 255, 255), 2)
    cv2.line(out, (w // 2, h - 12), (w // 2, h - 1), (255, 255, 255), 1)

    s = max(0.35, w / 900.0)
    lines = [f"off {det.offset:+.2f}  ang {det.angle:+5.1f}  conf {det.confidence:.2f}"]
    if cmd is not None:
        lines.append(f"steer {cmd.steer:+.2f}  speed {cmd.speed:.2f}" +
                     ("" if cmd.armed else "  [DISARMED]"))
    if fps is not None:
        lines.append(f"fps {fps:.1f}")
    if det.lost:
        lines.append("LINE LOST" + (f": {det.reason}" if det.reason else ""))
    if extra:
        lines.append(extra)
    for i, t in enumerate(lines):
        y = int(14 * s / 0.35) * (i + 1)
        cv2.putText(out, t, (4, y), cv2.FONT_HERSHEY_SIMPLEX, s, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, t, (4, y), cv2.FONT_HERSHEY_SIMPLEX, s,
                    (80, 80, 255) if (det.lost and t.startswith("LINE")) else (255, 255, 255),
                    1, cv2.LINE_AA)
    return out
