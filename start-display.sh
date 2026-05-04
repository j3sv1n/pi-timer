#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$HOME/pi-timer"
if [ ! -d "$APP_DIR" ]; then
  echo "App directory not found: $APP_DIR"
  echo "Run the installer first: sudo bash install.sh"
  exit 1
fi

cd "$APP_DIR"

# Try DISPLAY:1 first, fall back to DISPLAY:0 if it doesn't work
echo "Starting Pi Timer display..."

# The display.py script will handle the fallback internally,
# but we can help by trying to set it here first
if [ -S /tmp/.X11-unix/1 ] 2>/dev/null; then
  echo "  Using DISPLAY:1"
  DISPLAY=:1 "$APP_DIR/venv/bin/python" "$APP_DIR/display.py" &
else
  echo "  DISPLAY:1 not available, using DISPLAY:0"
  DISPLAY=:0 "$APP_DIR/venv/bin/python" "$APP_DIR/display.py" &
fi
