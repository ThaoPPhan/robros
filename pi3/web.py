"""Flask page: live MJPEG stream + keyboard/slider drive controls.

    ~/robros/.venv/bin/python3 pi3/web.py
Then open http://pi.local:8000 (or the Pi's IP) in a browser.

build_mjpeg_chunk, compute_fps, compute_wheel_command and CommandWatch are
pure (no flask/cv2/pyserial import), so tests/test_web.py runs them on the
laptop. main() is the hardware/server integration and only ever runs on the Pi.
"""
import threading
import time
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
MJPEG_BOUNDARY = b"frame"

PAGE_HTML = """<!doctype html>
<html><head><title>robros</title>
<style>
  body { margin:0; background:#111; color:#eee; font-family: sans-serif; }
  #video { width:100%; max-height:70vh; object-fit:contain; background:#000; display:block; }
  #controls { padding: 12px; }
  #stop { font-size: 24px; padding: 16px 32px; background:#c0392b; color:#fff;
          border:none; border-radius:8px; }
  #speed { width: 80%; }
</style>
</head>
<body>
<img id="video" src="/stream">
<div id="controls">
  <label>Speed: <input id="speed" type="range" min="0" max="1" step="0.05" value="0.3"></label>
  <span id="speedVal">0.30</span>
  <br><br>
  <button id="stop">STOP</button>
  <p>Hold W/S forward-back, A/D turn in place, Q/E arc turn. Space or STOP = stop.</p>
</div>
<script>
const heldKeys = new Set();
const driveKeys = new Set(["w", "a", "s", "d", "q", "e"]);
const speedInput = document.getElementById("speed");
const speedVal = document.getElementById("speedVal");
const stopButton = document.getElementById("stop");

speedInput.addEventListener("input", () => {
  speedVal.textContent = parseFloat(speedInput.value).toFixed(2);
});

function sendStop() {
  heldKeys.clear();
  fetch("/stop", { method: "POST" }).catch(() => {});
}

document.addEventListener("keydown", (e) => {
  const key = e.key.toLowerCase();
  if (key === " ") {
    e.preventDefault();
    sendStop();
    return;
  }
  if (driveKeys.has(key)) {
    e.preventDefault();
    heldKeys.add(key);
  }
});

document.addEventListener("keyup", (e) => {
  const key = e.key.toLowerCase();
  if (driveKeys.has(key)) heldKeys.delete(key);
});

// Alt-tabbing away without a keyup would otherwise leave a key "stuck" held.
window.addEventListener("blur", () => heldKeys.clear());

stopButton.addEventListener("click", sendStop);

setInterval(() => {
  fetch("/drive", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keys: Array.from(heldKeys), speed: parseFloat(speedInput.value) }),
  }).catch(() => {});
}, 100);
</script>
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


def compute_wheel_command(keys, speed: float, turn_in_place_fraction: float, arc_turn_fraction: float):
    """Mix currently-held drive keys + the speed slider into (left, right), -1..1.

    w/s drive straight; a/d turn in place at turn_in_place_fraction of speed;
    q/e arc-turn while still moving forward (the inner wheel slows down).
    Keys combine by summing their wheel deltas, then clamping -- an empty (or
    cancelling, e.g. w+s) key set is how "release = stop" falls out naturally.
    """
    left = 0.0
    right = 0.0
    turn_mag = turn_in_place_fraction * speed

    if "w" in keys:
        left += speed
        right += speed
    if "s" in keys:
        left -= speed
        right -= speed
    if "a" in keys:
        left -= turn_mag
        right += turn_mag
    if "d" in keys:
        left += turn_mag
        right -= turn_mag
    if "q" in keys:
        left += speed * (1.0 - arc_turn_fraction)
        right += speed
    if "e" in keys:
        left += speed
        right += speed * (1.0 - arc_turn_fraction)

    return max(-1.0, min(1.0, left)), max(-1.0, min(1.0, right))


class CommandWatch:
    """Tracks how long it's been since the browser last sent a drive command.
    `clock` is injectable so tests don't need real sleeps."""

    def __init__(self, timeout_s: float, clock=time.time):
        self._timeout_s = timeout_s
        self._clock = clock
        self._lock = threading.Lock()
        self._last_seen = clock()

    def touch(self) -> None:
        with self._lock:
            self._last_seen = self._clock()

    def is_stale(self) -> bool:
        with self._lock:
            return self._clock() - self._last_seen > self._timeout_s


def watchdog_loop(command_watch: CommandWatch, pico_link, poll_interval_s: float = 0.05):
    """Stops the robot if the browser goes quiet -- covers a closed tab, a
    dropped wifi connection, or a crashed page, none of which send /stop."""
    while True:
        if command_watch.is_stale():
            pico_link.set_wheels(0.0, 0.0)
        time.sleep(poll_interval_s)


def main():
    import cv2
    from flask import Flask, Response, jsonify, request

    from camera import Camera
    from pico_link import PicoLink

    config = load_config()
    cam_cfg = config["camera"]
    web_cfg = config["web"]
    pico_cfg = config["pico"]
    drive_cfg = config["drive"]

    camera = Camera(cam_cfg["backend"], cam_cfg["stream_size"], cam_cfg.get("usb_index", 0))
    camera.start()

    link = PicoLink(pico_cfg["port"], pico_cfg["baud"])
    link.start()

    command_watch = CommandWatch(web_cfg["command_timeout_s"])
    threading.Thread(target=watchdog_loop, args=(command_watch, link), daemon=True).start()

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

    @app.route("/drive", methods=["POST"])
    def drive():
        data = request.get_json(force=True, silent=True) or {}
        keys = set(data.get("keys", []))
        speed = max(0.0, min(1.0, float(data.get("speed", 0.0))))
        left, right = compute_wheel_command(
            keys, speed, drive_cfg["turn_in_place_fraction"], drive_cfg["arc_turn_fraction"],
        )
        link.set_wheels(left, right)
        command_watch.touch()
        return jsonify(ok=True)

    @app.route("/stop", methods=["POST"])
    def stop():
        link.set_wheels(0.0, 0.0)
        command_watch.touch()
        return jsonify(ok=True)

    app.run(host=web_cfg["host"], port=web_cfg["port"], threaded=True)


if __name__ == "__main__":
    main()
