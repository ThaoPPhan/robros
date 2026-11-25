#!/usr/bin/env bash
# Copies logs/ back from the Pi to the laptop for review.
set -euo pipefail

HOST="pi@pi.local"
DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/logs/"

mkdir -p "$DEST"
rsync -avz "$HOST:~/robros/logs/" "$DEST"
