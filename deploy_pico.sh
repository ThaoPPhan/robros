#!/usr/bin/env bash
# Over SSH on the Pi: copy pico/*.py to the Pico with mpremote and reset it.
# Refuses to run while pi3/robot.py is running (both need the Pico's serial port).
set -euo pipefail

HOST="pi@pi.local"

ssh "$HOST" bash -s <<'REMOTE'
set -euo pipefail

if pgrep -f "pi3/robot.py" > /dev/null; then
  echo "refusing: pi3/robot.py is running and holds the Pico serial port." >&2
  echo "stop it first, then re-run deploy_pico.sh." >&2
  exit 1
fi

if [ ! -d ~/robros/pico ]; then
  echo "no pico/ dir yet, nothing to deploy."
  exit 0
fi

MPREMOTE=~/robros/.venv/bin/mpremote
PICO_PORT=/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_65c3861722555a53-if00

cd ~/robros/pico
shopt -s nullglob
files=(*.py)
if [ ${#files[@]} -eq 0 ]; then
  echo "no pico/*.py files yet, nothing to deploy."
  exit 0
fi

for f in "${files[@]}"; do
  echo "copying $f"
  "$MPREMOTE" connect "$PICO_PORT" cp "$f" :"$f"
done

echo "resetting Pico"
"$MPREMOTE" connect "$PICO_PORT" reset
REMOTE
