"""Flask page: live MJPEG stream from the camera.

    ~/robros/.venv/bin/python3 pi3/web.py
Then open http://pi.local:8000 (or the Pi's IP) in a browser.

build_mjpeg_chunk and compute_fps are pure (no flask/cv2 import), so
tests/test_web.py runs them on the laptop. main() is the hardware/server
integration and only ever runs on the Pi.
"""
import time
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
MJPEG_BOUNDARY = b"frame"

PAGE_HTML = """<!doctype html>
<html><head><title>robros camera</title></head>
<body style="margin:0;background:#000">
<img src="/stream" style="width:100%;height:100vh;object-fit:contain">
</body></html>
"""


def load_config():
    import yaml  # not available on the laptop; only needed to run this script

    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def build_mjpeg_chunk(jpeg_bytes: bytes) -> bytes:
    """Wrap one JPEG frame as a multipart/x-mixed-replace chunk."""
    return (
        b"--" + MJPEG_BOUNDARY + b"\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Content-Length: " + str(len(jpeg_bytes)).encode() + b"\r\n\r\n"
        + jpeg_bytes + b"\r\n"
    )


def compute_fps(frame_count: int, elapsed_s: float) -> float:
    return frame_count / elapsed_s if elapsed_s > 0 else 0.0


def main():
    import cv2
    from flask import Flask, Response

    from camera import Camera

    config = load_config()
    cam_cfg = config["camera"]
    web_cfg = config["web"]

    camera = Camera(cam_cfg["backend"], cam_cfg["stream_size"], cam_cfg.get("usb_index", 0))
    camera.start()

    app = Flask(__name__)

    def frame_generator():
        frame_count = 0
        window_start = time.time()
        while True:
            frame = camera.read_frame()
            ok, jpeg = cv2.imencode(".jpg", frame)
            if not ok:
                continue
            yield build_mjpeg_chunk(jpeg.tobytes())

            frame_count += 1
            elapsed = time.time() - window_start
            if elapsed >= 2.0:
                print("camera fps: {:.1f}".format(compute_fps(frame_count, elapsed)))
                frame_count = 0
                window_start = time.time()

    @app.route("/")
    def index():
        return PAGE_HTML

    @app.route("/stream")
    def stream():
        return Response(
            frame_generator(),
            mimetype="multipart/x-mixed-replace; boundary=" + MJPEG_BOUNDARY.decode(),
        )

    app.run(host=web_cfg["host"], port=web_cfg["port"], threaded=True)


if __name__ == "__main__":
    main()
