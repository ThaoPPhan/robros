# ROBROS: delivery robot for the PEO Ottawa Robotics Competition (Nov 29, 2026)

## How we work (read first)
- I am rebuilding the software from scratch to UNDERSTAND it. Work ONE milestone at a time
  (see "Milestones"). After each milestone: STOP, tell me exactly how to test it on the real robot,
  and WAIT for my result. Never start the next milestone on your own.
- Small, readable files; plain Python; comments explain WHY. After writing a file, explain in a few
  sentences what it does and how it fits the rest.
- Explain things to me in Vietnamese; code, comments and file names stay in English.
- Scope now: MANUAL mode (competition stage 1). No autonomous driving, lane following or obstacle
  avoidance until I explicitly ask (they are listed under "Later").
- Every tunable number goes in `pi3/config.yaml` (Pi) or `pico/config.py` (Pico), never hard-coded.
- Add small unit tests for logic that needs no hardware (parsers, wheel mixing, timeouts, ramps).

## Development setup
- Claude Code runs on my LAPTOP in `~/robros` (git repo). The robot is a Raspberry Pi 3B at
  `pi@pi.local` (passwordless SSH). The Pi is too small to run Claude Code.
- In M0 create:
  - `deploy.sh`: rsync the repo to `pi@pi.local:~/robros/` (exclude .git, .venv, logs/, __pycache__).
  - `deploy_pico.sh`: over SSH on the Pi, copy `pico/*.py` to the Pico with mpremote and reset it.
    It must refuse to run while `pi3/robot.py` is running (both need the same serial port).
  - `fetch_logs.sh`: rsync `pi@pi.local:~/robros/logs/` back to `./logs/`.
- On the Pi: venv at `~/robros/.venv`, created with `--system-site-packages` (picamera2, OpenCV,
  Flask, numpy, yaml come from apt); `mpremote` and `pyserial` installed in the venv with pip.
- Hardware libraries (picamera2, serial ports) don't exist on the laptop: import them inside functions
  or behind try/except so unit tests run locally.
- SAFETY: never run anything that can move the motors without asking me first and waiting for my OK.
  Read-only checks over SSH (list devices, read the LiDAR, grab a camera frame) are fine. Long-running
  programs (web server, robot.py): give me the exact command; I start them myself.

## Pi environment: already set up and verified (Nov 25)
- Raspberry Pi OS Lite 64-bit on a fresh SD card, hostname pi, user pi, SSH works.
- apt: git, rsync, python3-venv, python3-picamera2, python3-opencv, python3-numpy, python3-yaml,
  python3-flask, python3-serial.
- venv: ~/robros/.venv (--system-site-packages) with mpremote 1.29.0; pyserial 3.5 comes from apt.
  Scripts and instructions must use ~/robros/.venv/bin/python3 and ~/robros/.venv/bin/mpremote
  (or tell me to `source .venv/bin/activate`). deploy.sh must never overwrite or delete .venv.
- UART: /dev/serial0 -> ttyAMA0 (full PL011 UART, Bluetooth disabled, serial console off) = LiDAR.
- Pico: /dev/ttyACM0, by-id /dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_65c3861722555a53-if00,
  MicroPython detected by mpremote.
- Camera: rpicam-hello lists 0 : ov5647 (modes 640x480 @ 62 fps, 1296x972, 1920x1080, 2592x1944).
  Use 640x480 sensor mode scaled to 320x240 for speed.
- M0 can therefore skip installation steps: only the skeleton, scripts, config and check_hw.py.

## Project layout
```
robros/
├── CLAUDE.md, README.md, deploy.sh, deploy_pico.sh, fetch_logs.sh, .gitignore
├── pi3/                      # runs on the Raspberry Pi 3B (CPython)
│   ├── config.yaml           # ports, camera, speeds, limits
│   ├── check_hw.py           # M0: read-only hardware check
│   ├── pico_link.py          # M1: talk to the Pico (commands out, telemetry in)
│   ├── test_pico.py          # M1: short wheel test (wheels lifted)
│   ├── camera.py             # M2: frames from Pi camera or USB camera
│   ├── web.py                # M2/M3: Flask page: video + drive controls
│   ├── robot.py              # M4: THE program for runs: one control loop
│   ├── lidar.py              # M5: LiDAR reader thread
│   └── (later) lane.py, auto.py, obstacle.py
├── pico/                     # runs on the Pico (MicroPython)
│   ├── config.py             # pins, PWM frequency, timeouts, ramp rates
│   ├── motors.py             # DRV8871 control
│   ├── encoders.py           # encoder counting
│   └── main.py               # protocol + failsafe loop (runs at boot)
├── tests/                    # unit tests (run on laptop and Pi)
└── logs/                     # CSV logs of runs (testing evidence)
```

## Competition facts that drive the design
- Two stages on the same track: 1) MANUAL (we drive while watching the robot's own camera),
  2) AUTONOMOUS (no human control except emergency stop).
- The robot carries an open box with 1 kg of sand; spilled sand is penalised. All speed changes must be
  smooth and turns gentle. Finishing with the payload matters more than speed.
- Live forward camera viewed by the team is mandatory. A physical master switch cuts motor power
  (software stop is extra, not a replacement). No loose wiring.
- Onboard cost cap CAD 500; the laptop is offboard and free.
- Track: a 90 cm wide lane, edges marked with BLUE painter's tape on polished concrete, about 24 m,
  six sharp 90° corners. Route: N 330 cm, R; E 200, L; N 640, L; W 170, R; N 170, R; E 270, R;
  S 570, finish (approximate, along the lane centre). Obstacles: to be announced; only detect and
  drive around them.

## Hardware
- Raspberry Pi 3B, Raspberry Pi OS Lite 64-bit, powered by a micro-USB wall charger (5 V / 2.5 A).
  Weak CPU and 1 GB RAM: camera at 320x240, no heavy libraries.
- Pico: RP2040 clone running MicroPython, connected to a Pi USB-A port. Port (use this, not ttyACM0):
  `/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_65c3861722555a53-if00`
- Camera: Pi Camera v1.3 on the ribbon port (picamera2), or a wide USB camera
  (`cv2.VideoCapture`). Selectable in config.
- LiDAR (LDRobot/LeDong LD06/LD19 class) on the Pi's GPIO UART `/dev/serial0`, 230400 baud.
  Wiring: P5V -> pin 2, GND -> pin 6, DATA -> pin 10 (GPIO15 RXD), CTL not connected.
- Motors: 2x JGA25-370 12 V, 130 RPM, Hall quadrature encoders (11 pulses per motor turn).
  Drivers: 2x DRV8871. Battery: 12.6 V Li-ion 2800 mAh (5 A max, built-in protection) through a
  master switch and Wago splitters to both drivers. The DRV8871 header pin VM carries 12 V: unused.

## Drive geometry
- Differential drive: 2 driven wheels on one axle through the centre of a round body, 2 ball casters
  (front and back). Turning = different wheel speeds; turn in place = opposite speeds.
- Wheel diameter 70 mm (circumference 219.9 mm). Track width 230 mm. Robot diameter 260 mm.
- Top speed about 0.48 m/s; plan 0.15-0.25 m/s with the sand box.
- Turn in place 90°: each wheel rolls pi x 230 / 4 = 180.6 mm, in opposite directions.
- Heading change (rad) = (right distance - left distance) / 0.230; distance = (left + right) / 2.
- Encoder counts per wheel turn: TO BE MEASURED in M1 (turn a wheel 10 times by hand).
- Manual driving: W/S forward/back, A/D gentle turn in place (limited to ~60% of the speed setting),
  Q/E arc turns.

## Pico: pins and behaviour (MicroPython, pico/)
- Left DRV8871 IN1/IN2 = GP10/GP11; right IN1/IN2 = GP12/GP13; both driver GNDs to Pico GND.
- Left encoder A/B = GP2/GP3; right A/B = GP4/GP5; encoder VCC = Pico 3V3 (never 5 V).
- DRV8871: IN1=1,IN2=0 forward; 0,1 reverse; 1,1 brake; 0,0 coast. Use slow-decay PWM with
  machine.PWM at 20 kHz (forward: IN1 high, PWM on IN2 inverted; reverse: the mirror).
- Encoders: Pin.irq on the rising edge of A, read B for direction (1x decoding; fast enough).
- Motors OFF at boot. Read commands from USB stdin without blocking (select.poll).
- Protocol, text lines ending in `\n`:
  - Pi -> Pico: `M,<left>,<right>` wheel speeds -1..1 · `S,<steer>,<speed>` (steer + = right;
    left = speed + 0.5*steer, right = speed - 0.5*steer, scaled to stay within 1) ·
    `H,<seq>` heartbeat · `R` reset encoder counts · `X` stop now.
  - Pico -> Pi, 20 Hz: `E,<ms>,<countL>,<countR>,<rateL>,<rateR>,<outL>,<outR>,<failsafe>`
- Failsafe: no M/S command for 300 ms -> stop; heartbeats seen once then none for 600 ms -> stop.
- Ramp: output changes at most 1.5 per second when speeding up, 3.0 when slowing down.
  Dead-band: outputs below MIN_OUTPUT (about 0.12, to be measured) are lifted so the wheel turns.
- Direction fixes in pico/config.py: L_DIR, R_DIR, L_ENC_SIGN, R_ENC_SIGN (+1/-1).

## LiDAR protocol (pi3/lidar.py)
- 47-byte packets: `0x54 0x2C`, speed (u16, deg/s), start angle (u16, 0.01°),
  12 x (distance mm u16, intensity u8), end angle (u16), timestamp (u16), CRC8 (poly 0x4D, table
  method, init 0) over the first 46 bytes. Angles spread evenly start..end (handle 360° wrap).
  0° = sensor front, clockwise. Distance 0 = no return. About 450 points per scan at 10 Hz.

## Milestones (in order; stop and wait after each)
**M0: Skeleton + hardware check.** Layout above, `.gitignore`, `pi3/config.yaml`, the three scripts,
`pi3/check_hw.py` (read-only): Pico port present (list files on it with mpremote), LiDAR packets valid
(+ scan rate), camera frames (+ fps). Done when all three report OK on the Pi.

**M1: Pico firmware + Pi link.** `pico/` (config, motors, encoders, main) and `pi3/pico_link.py`
(background thread: sends the current command + heartbeat at 20 Hz, keeps the latest telemetry,
stops on exit) + `pi3/test_pico.py` (lifted wheels: forward 1 s, back 1 s, each wheel alone, stop,
print counts) + a hand-turn mode to measure counts per wheel turn. Done when: directions correct,
counts rise forward, the robot stops when the Pi program is killed, counts per turn measured.

**M2: Camera stream.** `pi3/camera.py` + `pi3/web.py`: live MJPEG at 320x240 on port 8000, fps printed.
Done when: smooth video at http://pi.local:8000.

**M3: Drive from the browser.** Same page: hold W/A/S/D/Q/E to drive (release = stop), speed slider,
big STOP button, space = stop; browser sends about 10 commands/s; no command for 0.3 s -> stop.
Done when: driving works on the floor and closing the tab stops the robot.

**M4: The control loop.** `pi3/robot.py`: one loop at 20 Hz: inputs (browser command, Pico telemetry)
-> mode (STOP or MANUAL; starts in STOP) -> safety (lost Pico, lost browser, errors -> stop) -> send
to Pico -> one CSV row in `logs/`. Page shows mode, wheel speeds, encoder counts, Pico status.
Done when: same driving as M3, through the loop, and a log file appears.

**M5: LiDAR in the loop.** `pi3/lidar.py` thread; nearest distance ahead on the page, small top-down
map; optional emergency stop in MANUAL closer than X cm ahead (checkbox to disable).
Done when: a box in front appears on the map and triggers the stop.

**M6: Ready for stage 1.** Gamepad support (browser Gamepad API), snapshot button, a "competition
day" section in README.md (exact start-up commands, checks). Done when: a mock track is driven with
the sand box without spilling.

## Later (only when I ask)
Calibration (counts per metre, 90° turn), lane detection (blue tape edges, HSV), route plan with
odometry and 90° turns, obstacle detection and sidestep with the LiDAR, IMU (BNO085) if turns drift.