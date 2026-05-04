#!/usr/bin/env bash
set -euo pipefail

if [ -z "${SUDO_USER:-}" ]; then
  echo "This script must be run with sudo to enable autostart for the server service."
  echo "Use: sudo bash enable-autostart.sh"
  exit 1
fi

SERVICE_USER="$SUDO_USER"
SERVICE_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"
if [ -z "$SERVICE_HOME" ]; then
  echo "Unable to determine home directory for user $SERVICE_USER."
  exit 1
fi

APP_DIR="$SERVICE_HOME/pi-timer"
if [ ! -d "$APP_DIR" ]; then
  echo "App directory not found: $APP_DIR"
  echo "Run the installer first: sudo bash install.sh"
  exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root."
  echo "Use: sudo bash enable-autostart.sh"
  exit 1
fi

echo "========================================"
echo "  Pi Timer — Enable Autostart"
echo "========================================"

echo ""
echo "[1/2] Setting up systemd service for web server..."
cat > /etc/systemd/system/pi-timer-server.service << EOF
[Unit]
Description=Pi Timer Web Server
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/server.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable pi-timer-server.service
systemctl start pi-timer-server.service
echo "✓ Systemd service installed and started."

echo ""
echo "[2/2] Setting up display autostart on desktop login..."
AUTOSTART_DIR="$SERVICE_HOME/.config/autostart"
AUTOSTART_FILE="$AUTOSTART_DIR/pi-timer.desktop"

mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_FILE" << EOF
[Desktop Entry]
Type=Application
Name=Pi Timer
Exec=bash -lc 'sleep 20 && $APP_DIR/venv/bin/python $APP_DIR/display.py'
StartupNotify=false
EOF

chown "$SERVICE_USER:$SERVICE_USER" "$AUTOSTART_DIR" "$AUTOSTART_FILE"
echo "✓ Display autostart configured."

echo ""
echo "========================================"
echo "  Autostart enabled!"
echo ""
echo "  • Server starts automatically on system boot (via systemd)"
echo "  • Display starts automatically on desktop login (after 20s delay)"
echo ""
echo "========================================"
