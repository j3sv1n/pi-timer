<h1 style="font-family:'Syne', sans-serif; font-weight:800; color:#fff;">Pi <span style="color:#d14242;">Timer</span></h1>

A web-based timer management system designed to run smoothly on Raspberry Pi devices. Ideal for presentations, events, or any scenario requiring a highly visible, remotely controlled clock, countdown timer, or stopwatch on a fullscreen monitor.

## Features

- **Web Interface**: Control the clock, timer, and stopwatch through a clean web UI.
- **Real-time Display**: Dedicated display application that shows the active timer in fullscreen.
- **Custom Limits & Alerts**: Set hard stops or visual blinking alerts when a timer or stopwatch reaches a specific limit.
- **12/24 Hour Formats**: Easily toggle the standard clock display format.
- **Optional Authentication**: Secure login system with admin capabilities — or disable it for public access.
- **Responsive Design**: Works perfectly on desktop and mobile devices for easy remote control.

## Installation

### Prerequisites

- Raspberry Pi OS installed on your Pi device
- Internet connection for downloading packages

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/j3sv1n/pi-timer
   cd pi-timer
   ```

2. Run the installer:
   ```bash
   sudo bash install.sh
   ```

The installer will:
- install required system packages with `apt` (Python, pip, venv, Flask, pygame, watchdog, sdl2-dev)
- create `~/pi-timer`
- copy `display.py` and `server.py` into that directory
- create a Python venv with `--system-site-packages`
- install `Flask==2.3.3` and `Werkzeug==3.0.0` in the venv

### Optional autostart

To enable autostart for both the web server and display on boot, run:
```bash
sudo bash enable-autostart.sh
```

This creates:
- A systemd service that starts the web server automatically on system boot
- A desktop entry that starts the display app automatically on desktop login (with a 20-second delay)

If you do not want autostart, simply do not run this script. You can start both services manually anytime:
```bash
bash start-server.sh   # Start web server
bash start-display.sh  # Start display app
```

## Usage

### Web Server

By default, the web server is manual start. To run it:
```bash
bash start-server.sh
```

Or run directly:
```bash
~/pi-timer/venv/bin/python ~/pi-timer/server.py
```

Access the web interface at `http://localhost:5001`.

**To enable automatic start on system boot:**

Run `sudo bash enable-autostart.sh` to set up the systemd service. After that, the server will start automatically on boot.

To check systemd service status:
```bash
sudo systemctl status pi-timer-server.service
sudo systemctl restart pi-timer-server.service
```

### Display Application

Start the display app on the Pi monitor:
```bash
bash start-display.sh
```

Or run it manually with:
```bash
DISPLAY=:1 ~/pi-timer/venv/bin/python ~/pi-timer/display.py &
```
*(Note: The script will automatically fall back to `DISPLAY=:0` if `:1` is unavailable).*

### Web Interface

The display will automatically connect to the server and show the active mode in fullscreen. 

#### First-time setup

1. **Setup**: On first run, create an account and choose whether to enable login.
2. **Login** (if enabled): Use your username and password to access the system.

#### Using the dashboard

The dashboard contains three dedicated tabs:
*   **Clock:** Displays the current time. Allows you to configure 12-hour or 24-hour formats. 
*   **Timer:** Set a countdown duration (HH:MM:SS), start, pause, or reset the countdown. 
*   **Stopwatch:** Track elapsed time. Set optional time limits and choose whether the display should "Stop at limit" or "Blink at limit".

**Important:** Changes made in the web interface (like updating the time format or starting a timer internally) will not push to the physical monitor until you click the corresponding **"Send to Display"** button.

### Settings Panel

Access the settings panel by clicking the gear icon in the header (account required if login is enabled) to:
- **Configure Login**: Enable or disable the login system — toggle between requiring authentication or allowing public access.
- **Reset App**: Factory reset the application, removing all timer states and user accounts (except the main account).

## Configuration

The application uses several configuration files:

- `timer_state.json`: Tracks current display state, active mode, and elapsed time IDs.
- `timer_config.json`: Application settings (login system enabled/disabled, 12/24hr format).
- `timer_users.json`: User account data (encrypted).
- `timer_secret.key`: Flask session secret.

All files are created automatically in the project directory.

### Login System Configuration

On first setup, you'll be prompted to choose whether to enable or disable the login system:
- **Login Enabled** (default): Users must authenticate with username and password. Settings panel is accessible.
- **Login Disabled**: Anyone can access the app without authentication. All authentication UI is hidden.

To change this setting anytime, visit the Settings page and toggle the "Login System" checkbox.

## API Reference

### Timer & Stopwatch Control
- `GET /api/state`: Get current timer/stopwatch state
- `POST /api/timer/start`: Start a countdown timer
- `POST /api/timer/pause`: Pause the active timer
- `POST /api/timer/stop`: Reset the active timer
- `POST /api/timer/send`: Push timer UI to the display
- `POST /api/stopwatch/start`: Start the stopwatch
- `POST /api/stopwatch/pause`: Pause the stopwatch
- `POST /api/stopwatch/reset`: Reset the stopwatch
- `POST /api/stopwatch/send`: Push stopwatch UI to the display
- `GET /api/clock`: Sync and push the clock to the display

### System & Admin
- `GET /api/admin/config`: Get system configuration
- `POST /api/admin/config`: Update system configuration
- `POST /api/admin/reset`: Factory reset the application

## Development

### Project Structure

```
pi-timer/
├── server.py              # Flask web server
├── display.py             # Pygame fullscreen display
├── start-server.sh        # Manual server startup script
├── start-display.sh       # Manual display startup script
├── install.sh             # System installation script
├── enable-autostart.sh    # Systemd and desktop autostart configuration
├── timer_state.json       # Display and time tracking state
├── timer_users.json       # User accounts
├── timer_config.json      # Application settings (login system, clock format)
└── timer_secret.key       # Session secret
```
