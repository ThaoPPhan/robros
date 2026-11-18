# Robros – line-following vision

Computer vision for the autonomous delivery robot. It runs on a Raspberry Pi 4 with a
Pi Camera v1.3 (OV5647) and follows painter's tape on concrete, in either of two modes:
a single centre line, or a lane between two lines. It outputs a steering command and a
speed, and can optionally send them to a Raspberry Pi Pico over UART.

```
camera.py      frame sources: picamera2 (CSI), OpenCV (USB UVC / video file), image folders
detector.py    HSV mask + glare rejection + morphology -> offset, angle, look-ahead, confidence
controller.py  detection -> steer (-1..+1, + = right) and speed (0..1)
server.py      web UI on :8000: live MJPEG + mask stream, /calibrate, snapshots, GO/STOP
serial_link.py UART sender to the Pico (20 Hz commands + heartbeat)
settings.py    config loading, comment-preserving save
main.py        ties it together; live and offline modes, CSV logging
config.yaml    every tunable value
tests/         unit tests (synthetic images, controller, serial over a pseudo-terminal)
tools/make_synthetic.py   generates perspective test frames of a tape course
samples/       synthetic test frames (center line, lane, and a video)
```

## 1. Setup

Tested on Raspberry Pi OS 64-bit based on Debian 13 "trixie" (kernel 6.18), Python 3.13,
OpenCV 4.10, picamera2, Flask 3.1, pyserial 3.5.

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv python3-numpy python3-yaml \
                    python3-flask python3-serial
rpicam-hello --list-cameras      # should list: 0 : ov5647 [2592x1944 ...]
```

All dependencies come from apt, so no venv is needed. If you want one anyway, create it with
`python3 -m venv --system-site-packages .venv` so that picamera2 (apt-only) stays importable.

Quick camera check, which prints the capture fps for 5 s:

```bash
cd ~/robros
python3 camera.py
```

## 2. Running

### Live (camera + web UI, no motors)

```bash
python3 main.py                  # open http://<pi-ip>:8000 on the laptop
python3 main.py --size 640x480   # higher resolution
python3 main.py --mode lane      # two-line lane mode (or set detector.mode in config.yaml)
```

The terminal prints one status line per second:

```
fps  30.0 | proc  4.1 ms | off +0.12 ang  -3.4 conf 0.85       | steer +0.08 speed 0.42
```

Terminal keys (type the letter, then Enter): `s` saves a snapshot, `g` arms (GO), `x` disarms (STOP), `q` quits.

**Safety:** the program starts **disarmed**. Steering is computed and sent, but speed is
forced to 0 until you press **GO** on the web page or type `g`. The web page's **STOP**
button, or the space bar on that page, disarms again. Use `--arm` (or
`controller.start_armed: true`) only when you really want the car to drive straight away.

### With the Pico (UART)

```bash
python3 main.py --serial                       # uses serial.port from config (/dev/serial0)
python3 main.py --serial --serial-port /dev/ttyAMA0
```

### Offline (no car, no camera)

The offline mode runs exactly the same pipeline on saved images or a video:

```bash
python3 main.py --source snapshots/                 # one result line per image + CSV log
python3 main.py --source snapshots/ --out out/      # also write annotated images
python3 main.py --source run.mp4 --quiet            # video file
python3 main.py --source snapshots/ --serve         # replay in a loop at 10 fps with the web UI,
                                                    # so you can tune on /calibrate
python3 main.py --source samples/synthetic_center --serve --rate 5
```

### Collecting test images on the real floor

* On the web page, click **Save snapshot** or press `s`. In the terminal, type `s` + Enter.
  Either way you get `snapshots/snap_<time>.png` (the raw, lossless frame) and `..._view.jpg`
  (the annotated view).
* `python3 main.py --record-every 0.5` saves a raw frame every 0.5 s while you push the car
  along the course by hand. Then tune with `--source snapshots/ --serve`.
* `http://<pi-ip>:8000/frame.jpg` and `/mask.jpg` return single frames.

## 3. Calibrating the tape colour

1. Put the car on the course under the real lighting and run `python3 main.py`.
2. Open `http://<pi-ip>:8000/calibrate`.
3. Click the tape in the left image. The page shows its HSV value; click **use ± range**
   to centre the thresholds on it. Alternatively, start from the **Blue preset** or the
   **Green preset**.
4. Adjust the sliders while you watch the mask, which should show white tape on black.
   - Raise **S low** until the grey concrete disappears. Concrete has low saturation, so
     this is usually the key slider.
   - Lower **V low** if the tape breaks up in shadows.
   - If floor reflections show up in the mask, lower **Glare V min** or raise **Glare S max**.
   - Use **Open** to remove speckle and **Close** to fill gaps that glare leaves in the tape.
   - Move **ROI top** down until walls and objects in the distance are excluded.
5. Click **Save to config.yaml**. Only those keys are rewritten; comments are kept, and the
   previous file goes to `config.yaml.bak`.
6. Check it on several spots: in the brightest glare, in a shadow and in a curve.

OpenCV hue runs from 0 to 179 (half of the usual degrees). Blue painter's tape usually sits
around H 95–120 and green around H 40–80.

`camera.lock_exposure_after: 2.0` freezes exposure and white balance 2 s after start, so the
tape colour doesn't shift when a bright glare patch enters the view. Start the program with
the camera looking at the course, not at a lamp. Set it to 0 to keep auto exposure.

## 4. What the numbers mean

| value | meaning |
|---|---|
| `offset` -1..+1 | line (or lane centre) relative to the image centre at the bottom of the ROI; **+ = the line is to the right** |
| `angle` deg | heading of the line going up the image; **+ = it bends or points right**. It is measured in image space, so perspective exaggerates it. |
| look-ahead point | the point on the line `detector.lookahead` × ROI height above the ROI bottom (yellow circle) |
| `confidence` 0..1 | (share of scan bands where tape was found) × straightness × (whether points were found near the bottom); in lane mode, bands with only one visible boundary count less |
| line lost | `confidence < detector.min_confidence`, or the mask covers more than `max_mask_frac` of the ROI (the HSV range is wrong). Lost means steer 0 and speed 0. |
| `steer` -1..+1 | **+ = turn right** |
| `speed` 0..1 | `max_speed`, reduced in curves (`curve_slowdown`) and at low confidence, and never below `min_speed` while the line is tracked |

How detection works: the ROI is split into `n_bands` horizontal bands. In each band, the
columns that are mostly tape form runs. Starting at the bottom band (nearest the robot), the
run closest to the previous point is followed up the image, so tape scraps elsewhere are
ignored. In lane mode, the nearest runs left and right of the current centre are the two
boundaries. If only one is visible, the centre is placed half a learned lane width away from it.

Controller (`controller.method`):
* `proportional` (default): `steer = kp_offset·offset + kp_angle·angle/45`
* `pure_pursuit`: `steer = kp_pursuit · 2·sin(α)/Ld`, where α and Ld are the angle and
  distance from the bottom centre to the look-ahead point (Ld normalised to the image height)

Tuning: start slow (`max_speed: 0.3`). If the car oscillates, lower `kp_offset` or raise
`steer_smoothing`. If it cuts corners or reacts late, raise `kp_angle` or move the
look-ahead point closer.

## 5. UART protocol (Pi → Pico)

115200 baud, 8N1, ASCII lines:

```
S,<steer>,<speed>,<confidence>\n    20 Hz, e.g.  S,-0.250,0.400,0.87
H,<seq>\n                           5 Hz heartbeat, seq = 0..65535 counting up
```

* If the vision loop stalls for more than 0.3 s (`serial.stale_timeout`), the Pi sends
  `S,0.000,0.000,0.00` and **stops sending heartbeats**.
* On exit (including Ctrl-C), the Pi sends three stop commands.
* **On the Pico side:** stop the motors if no valid `S` line arrives for about 300 ms, or if
  the heartbeat stops. Anything the Pico sends back is shown as `pico_rx` in `/api/status`.

### Enable the UART (not enabled on this Pi yet)

`/dev/serial0` does not exist yet, and `cmdline.txt` still runs a login console on it. Fix:

```bash
sudo raspi-config nonint do_serial_cons 1   # disable the serial login console
sudo raspi-config nonint do_serial_hw 0     # enable the UART hardware
# optional, recommended: use the full PL011 UART instead of the mini UART
# (Bluetooth is then disabled):
echo "dtoverlay=disable-bt" | sudo tee -a /boot/firmware/config.txt
sudo reboot
ls -l /dev/serial0
```

Wiring (3.3 V logic on both sides, no level shifter needed): Pi GPIO14/TXD (pin 8) → Pico
GP1 (UART0 RX); Pi GPIO15/RXD (pin 10) ← Pico GP0 (UART0 TX); GND ↔ GND.

Minimal MicroPython receiver for the Pico (a starting point; it has not been run on a Pico):

```python
from machine import UART, Pin
import time
uart = UART(0, 115200, tx=Pin(0), rx=Pin(1))
buf, last = b"", time.ticks_ms()
steer = speed = 0.0
while True:
    if uart.any():
        buf += uart.read()
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            p = line.decode().strip().split(",")
            if p[0] == "S" and len(p) == 4:
                steer, speed = float(p[1]), float(p[2]); last = time.ticks_ms()
    if time.ticks_diff(time.ticks_ms(), last) > 300:
        steer = speed = 0.0                  # failsafe
    left, right = speed + steer * 0.5, speed - steer * 0.5   # skid-steer mix (tune)
    # set_motors(left, right)
    time.sleep_ms(5)
```

## 6. Logs (testing evidence)

Every run writes `logs/run_<date>_<time>.csv` (offline runs write `logs/offline_...csv`) with these columns:
`timestamp, frame, source, offset, angle, target_x, target_y, confidence, lost, steer, speed, armed, fps, proc_ms`.
`proc_ms` is the vision processing time per frame. Use `--no-log` to disable logging.

## 7. Tests

```bash
python3 -m unittest discover -s tests -v
```

* `test_detector.py`: draws tape lines on a synthetic grey floor at known offsets
  (−0.6..+0.6) and angles (−30..+30°) and checks offset (±0.04), angle (±2.5°), the
  look-ahead point, the ROI cut-off, glare rejection, rejection of distractor scraps, green
  tape, an over-wide HSV range, 640×480, lane mode with two lines, and a lane with one
  boundary missing.
* `test_controller.py`: sign conventions, stop when lost, curve and confidence slowdown,
  disarm, pure pursuit.
* `test_serial_link.py`: the real UART code over a pseudo-terminal: message format,
  20 Hz rate, 5 Hz heartbeat, stop on stale data, stop on close.

Synthetic perspective frames for end-to-end checks:
`python3 tools/make_synthetic.py samples/x [--lane] [--green] [--video]`.

## 8. Changing the camera later

* **USB UVC camera:** set `camera.backend: opencv` and `camera.device: 0` (or
  `/dev/video0`). `opencv_fourcc: MJPG` lets most cameras reach 30 fps.
* **Fisheye OV5647:** it still uses the `picamera2` backend. The strong distortion bends
  straight tape near the edges, so offset and angle will need re-tuning, or an undistort
  step added in `camera.py` (not implemented yet).
* Upside-down mount: `hflip: true` and `vflip: true`.
