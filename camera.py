"""Camera / frame sources behind one small interface.

Every source has start(), read() -> (frame_bgr, timestamp) or (None, None) at end of
stream, stop(), and a `name`. Frames are always BGR uint8 at the configured size.

Backends:
  Picamera2Camera  - CSI camera via picamera2 (Pi Camera v1.3 / OV5647, fisheye OV5647)
  OpenCVCamera     - USB UVC camera (or a video file) via cv2.VideoCapture
  ImageFolderSource / VideoFileSource - offline replay of saved images / videos
"""

import glob
import os
import time

import cv2

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")


class Camera:
    name = "camera"
    live = True

    def start(self):
        pass

    def read(self):
        raise NotImplementedError

    def stop(self):
        pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


class Picamera2Camera(Camera):
    name = "picamera2"

    def __init__(self, width, height, fps=30, hflip=False, vflip=False,
                 lock_exposure_after=0.0, controls=None):
        self.size = (int(width), int(height))
        self.fps = fps
        self.hflip, self.vflip = hflip, vflip
        self.lock_after = float(lock_exposure_after or 0)
        self.controls = dict(controls or {})
        self.cam = None
        self._t0 = None
        self._locked = False

    def start(self):
        from libcamera import Transform
        from picamera2 import Picamera2

        self.cam = Picamera2()
        ctrls = {"FrameRate": float(self.fps)}
        ctrls.update(self.controls)
        cfg = self.cam.create_video_configuration(
            # "RGB888" in picamera2 is BGR byte order in memory = what OpenCV expects.
            main={"size": self.size, "format": "RGB888"},
            transform=Transform(hflip=int(self.hflip), vflip=int(self.vflip)),
            buffer_count=4,
            queue=False,  # always hand back the newest frame (lowest latency)
            controls=ctrls,
        )
        self.cam.configure(cfg)
        self.cam.start()
        self._t0 = time.monotonic()

    def _maybe_lock(self, md):
        if self._locked or self.lock_after <= 0:
            return
        if time.monotonic() - self._t0 < self.lock_after:
            return
        lock = {"AeEnable": False, "AwbEnable": False}
        for key in ("ExposureTime", "AnalogueGain", "ColourGains"):
            if key in md and key not in self.controls:
                lock[key] = md[key]
        self.cam.set_controls(lock)
        self._locked = True
        print(f"[camera] exposure/white balance locked: "
              f"exp={md.get('ExposureTime')}us gain={md.get('AnalogueGain', 0):.2f} "
              f"wb={md.get('ColourGains')}")

    def read(self):
        req = self.cam.capture_request()
        try:
            frame = req.make_array("main")
            md = req.get_metadata()
        finally:
            req.release()
        self._maybe_lock(md)
        return frame, time.time()

    def stop(self):
        if self.cam is not None:
            try:
                self.cam.stop()
            finally:
                self.cam.close()
                self.cam = None


class OpenCVCamera(Camera):
    name = "opencv"

    def __init__(self, device=0, width=320, height=240, fps=30, fourcc="MJPG",
                 hflip=False, vflip=False):
        self.device = device
        self.size = (int(width), int(height))
        self.fps, self.fourcc = fps, fourcc
        self.flip = _flip_code(hflip, vflip)
        self.cap = None

    def start(self):
        dev = self.device
        if isinstance(dev, str) and dev.isdigit():
            dev = int(dev)
        self.cap = cv2.VideoCapture(dev, cv2.CAP_V4L2) if isinstance(dev, int) else cv2.VideoCapture(dev)
        if not self.cap.isOpened():
            raise RuntimeError(f"OpenCV could not open camera {self.device!r}")
        if self.fourcc:
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.fourcc))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.size[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def read(self):
        ok, frame = self.cap.read()
        if not ok:
            return None, None
        frame = _fit(frame, self.size)
        if self.flip is not None:
            frame = cv2.flip(frame, self.flip)
        return frame, time.time()

    def stop(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None


class ImageFolderSource(Camera):
    """Replays a folder of images (or a single image). rate=0 means as fast as possible."""
    name = "images"
    live = False

    def __init__(self, path, width, height, rate=0.0, loop=False):
        if os.path.isdir(path):
            files = sorted(f for f in glob.glob(os.path.join(path, "*"))
                           if f.lower().endswith(IMAGE_EXTS))
        else:
            files = [path]
        if not files:
            raise RuntimeError(f"no images found in {path}")
        self.files = files
        self.size = (int(width), int(height))
        self.rate, self.loop = rate, loop
        self.i = 0
        self.current = None
        self._next_t = 0.0

    def read(self):
        if self.i >= len(self.files):
            if not self.loop:
                return None, None
            self.i = 0
        _pace(self)
        self.current = self.files[self.i]
        self.i += 1
        frame = cv2.imread(self.current, cv2.IMREAD_COLOR)
        if frame is None:
            print(f"[images] skipping unreadable {self.current}")
            return self.read()
        return _fit(frame, self.size), time.time()


class VideoFileSource(OpenCVCamera):
    name = "video"
    live = False

    def __init__(self, path, width, height, rate=0.0, loop=False):
        super().__init__(device=path, width=width, height=height, fourcc=None)
        self.rate, self.loop = rate, loop
        self.current = path
        self._next_t = 0.0

    def start(self):
        self.cap = cv2.VideoCapture(self.device)
        if not self.cap.isOpened():
            raise RuntimeError(f"could not open video {self.device}")

    def read(self):
        _pace(self)
        frame, ts = super().read()
        if frame is None and self.loop:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            frame, ts = super().read()
        return frame, ts


def _pace(src):
    if src.rate and src.rate > 0:
        now = time.monotonic()
        if src._next_t > now:
            time.sleep(src._next_t - now)
        src._next_t = max(now, src._next_t) + 1.0 / src.rate


def _fit(frame, size):
    if frame.ndim == 2:
        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    if (frame.shape[1], frame.shape[0]) != size:
        frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
    return frame


def _flip_code(hflip, vflip):
    if hflip and vflip:
        return -1
    if hflip:
        return 1
    if vflip:
        return 0
    return None


def make_camera(cam_cfg, source=None, rate=0.0, loop=False):
    """Build a frame source from the `camera:` config section, or an offline source."""
    w, h = cam_cfg["width"], cam_cfg["height"]
    if source:
        if os.path.isdir(source) or source.lower().endswith(IMAGE_EXTS):
            return ImageFolderSource(source, w, h, rate=rate, loop=loop)
        return VideoFileSource(source, w, h, rate=rate, loop=loop)
    backend = cam_cfg.get("backend", "picamera2")
    if backend == "picamera2":
        return Picamera2Camera(w, h, cam_cfg.get("fps", 30), cam_cfg.get("hflip", False),
                               cam_cfg.get("vflip", False), cam_cfg.get("lock_exposure_after", 0),
                               cam_cfg.get("controls"))
    if backend == "opencv":
        return OpenCVCamera(cam_cfg.get("device", 0), w, h, cam_cfg.get("fps", 30),
                            cam_cfg.get("opencv_fourcc", "MJPG"),
                            cam_cfg.get("hflip", False), cam_cfg.get("vflip", False))
    raise ValueError(f"unknown camera backend {backend!r}")


if __name__ == "__main__":
    # Quick check: python3 camera.py [config.yaml]  -> prints capture fps for 5 s
    import sys
    import yaml
    cfg = yaml.safe_load(open(sys.argv[1] if len(sys.argv) > 1 else "config.yaml"))
    with make_camera(cfg["camera"]) as cam:
        n, t0 = 0, time.monotonic()
        while time.monotonic() - t0 < 5:
            frame, _ = cam.read()
            n += 1
        print(f"{cam.name}: {frame.shape} {n / (time.monotonic() - t0):.1f} fps")
