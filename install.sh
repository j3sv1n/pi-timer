#!/usr/bin/env bash
# ============================================================
# Pi Timer — Raspberry Pi OS installer
# Run once as root on a fresh Raspberry Pi OS install:
#   sudo bash install.sh
# ============================================================

set -euo pipefail

if [ -z "${SUDO_USER:-}" ]; then
  echo "This installer must be run with sudo from the target user account."
  echo "Use: sudo bash install.sh"
  exit 1
fi
SERVICE_USER="$SUDO_USER"
SERVICE_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"
if [ -z "$SERVICE_HOME" ]; then
  echo "Unable to determine home directory for user $SERVICE_USER."
  exit 1
fi
APP_DIR="$SERVICE_HOME/pi-timer"
VENV_DIR="$APP_DIR/venv"
TMPDIR_CUSTOM="$SERVICE_HOME/tmp"

if [ "$(id -u)" -ne 0 ]; then
  echo "This installer must be run as root."
  echo "Use: sudo bash install.sh"
  exit 1
fi

echo "========================================"
echo "  Pi Timer installer"
echo "========================================"

echo ""
echo "[1/5] Installing system packages..."
apt-get update -q
apt-get install -y -q \
  python3 python3-pip python3-venv \
  python3-watchdog python3-flask python3-pygame \
  libsdl2-dev fonts-dejavu

echo ""
echo "[2/5] Creating app directory..."
mkdir -p "$APP_DIR"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$SCRIPT_DIR" != "$APP_DIR" ]; then
  cp "$SCRIPT_DIR/server.py" "$APP_DIR/server.py" 2>/dev/null || echo "server.py not found in script dir"
  cp "$SCRIPT_DIR/display.py" "$APP_DIR/display.py" 2>/dev/null || echo "display.py not found in script dir"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

echo ""
echo "[3/5] Creating Python virtualenv..."
rm -rf "$VENV_DIR"
sudo -u "$SERVICE_USER" python3 -m venv "$VENV_DIR" --system-site-packages

echo ""
echo "[4/5] Installing Flask, Werkzeug, and required packages..."
mkdir -p "$TMPDIR_CUSTOM"
chown "$SERVICE_USER:$SERVICE_USER" "$TMPDIR_CUSTOM"

sudo -u "$SERVICE_USER" TMPDIR="$TMPDIR_CUSTOM" \
  "$VENV_DIR/bin/python" -m pip install --break-system-packages --no-cache-dir \
  "Flask==2.3.3" "Werkzeug==3.0.0" "waitress"

rm -rf "$TMPDIR_CUSTOM"

echo ""
echo "[5/5] Installation complete."
echo ""
echo "Access the web interface at: http://$(hostname -I | awk '{print $1}'):5001"
echo ""
echo "To start the web server manually:"
echo "  bash $SCRIPT_DIR/start-server.sh"
echo ""
echo "To start the display manually:"
echo "  bash $SCRIPT_DIR/start-display.sh"
echo ""
echo "To enable autostart for both server and display on boot:"
echo "  sudo bash $SCRIPT_DIR/enable-autostart.sh"
echo "========================================"
