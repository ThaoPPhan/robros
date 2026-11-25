# ROBROS

Delivery robot for the PEO Ottawa Robotics Competition (Nov 29, 2026).
Design details, milestones, and hardware pinout live in `CLAUDE.md`.

## Layout

- `pi3/` — runs on the Raspberry Pi 3B.
- `pico/` — runs on the Pico (MicroPython).
- `tests/` — unit tests, run on the laptop or the Pi.
- `logs/` — CSV logs from runs (not committed).

## Laptop -> Pi workflow

- `./deploy.sh` — sync this repo to the Pi (`pi@pi.local:~/robros/`).
- `./deploy_pico.sh` — flash `pico/*.py` onto the Pico over SSH + mpremote.
- `./fetch_logs.sh` — copy `logs/` back from the Pi to `./logs/`.

## Running checks

Laptop (no hardware):

```
python3 -m unittest discover tests
```

Pi (real hardware, read-only):

```
~/robros/.venv/bin/python3 pi3/check_hw.py
```
