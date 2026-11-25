#!/usr/bin/env bash
# Copies the repo to the Pi. Never touches .venv or logs/ there (excluded, not deleted).
set -euo pipefail

HOST="pi@pi.local"
DEST="~/robros/"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/"

rsync -avz \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='logs/' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  "$SRC" "$HOST:$DEST"
