#!/usr/bin/env bash
# Over SSH on the Pi: copy pico/*.py to the Pico with mpremote and reset it.
# Refuses to run while pi3/robot.py is running (both need the Pico's serial port).
set -euo pipefail

HOST="pi@pi.local"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# This script only pushes ~/robros/pico FROM THE PI onto the Pico -- it never
# touches the laptop. Without this, editing pico/ on the laptop and running
# only deploy_pico.sh silently re-flashes whatever old code is already on the
# Pi, ignoring every edit (the exact bug that cost a very long debugging
# session on 2026-11-25).
"$SCRIPT_DIR/deploy.sh"

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

# mpremote's cp silently skips a file it thinks is "up to date" (its check
# isn't reliable against the Pico's filesystem) -- delete each file first so
# there's nothing to compare against and the copy always actually happens.
for f in "${files[@]}"; do
  "$MPREMOTE" connect "$PICO_PORT" rm ":$f" > /dev/null 2>&1 || true
done

# One mpremote session for every copy + the final reset. Separate
# connect/disconnect per file risked main.py restarting mid-deploy (it auto-runs
# on any reset) and racing the next copy over the same serial port.
cmd=("$MPREMOTE" connect "$PICO_PORT")
first=1
for f in "${files[@]}"; do
  echo "copying $f"
  if [ "$first" -eq 1 ]; then
    cmd+=(cp "$f" :"$f")
    first=0
  else
    cmd+=(+ cp "$f" :"$f")
  fi
done
cmd+=(+ reset)

echo "resetting Pico"
"${cmd[@]}"
REMOTE
