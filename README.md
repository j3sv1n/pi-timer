<h1 style="font-family:'Syne', sans-serif; font-weight:800; color:#fff;">Pi <span style="color:#d14242;">Timer</span></h1>

A web-based timer management system designed to run smoothly on Raspberry Pi devices. Ideal for presentations, events, or any scenario requiring a highly visible, remotely controlled clock, countdown timer, or stopwatch on a fullscreen monitor.

## Features

- **Web Interface**: Control the clock, timer, and stopwatch through a clean web UI.
- **Real-time Display**: Dedicated display application that shows the active timer in fullscreen.
- **Custom Limits & Alerts**: Set hard stops or visual blinking alerts when a timer or stopwatch reaches a specific limit.
- **12/24 Hour Formats**: Easily toggle the standard clock display format.
- **Bitfocus Companion Integration**: Fully supported native HTTP polling and variable pushing for physical Stream Deck control.
- **Optional Authentication**: Secure login system — or disable it for public/API access.
- **Responsive Design**: Works perfectly on desktop and mobile devices for easy remote control.

## Installation

### Prerequisites

- Raspberry Pi OS installed on your Pi device
- Internet connection for downloading packages

### Setup

1. Clone the repository:
   ```bash
   git clone [https://github.com/j3sv1n/pi-timer](https://github.com/j3sv1n/pi-timer)
   cd pi-timer

```

2. Run the installer:
```bash
sudo bash install.sh

```



The installer will:

* install required system packages with `apt` (Python, pip, venv, Flask, pygame, watchdog, sdl2-dev)
* create `~/pi-timer`
* copy `display.py` and `server.py` into that directory
* create a Python venv with `--system-site-packages`
* install `Flask==2.3.3` and `Werkzeug==3.0.0` in the venv

### Optional autostart

To enable autostart for both the web server and display on boot, run:

```bash
sudo bash enable-autostart.sh

```

This creates:

* A systemd service that starts the web server automatically on system boot
* A desktop entry that starts the display app automatically on desktop login (with a 20-second delay)

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

1. **Setup**: On first run, create a Master Password and choose whether to enable login.
2. **Login** (if enabled): Use your password to access the system.

#### Using the dashboard

The dashboard contains three dedicated tabs:

* **Clock:** Displays the current time. Allows you to configure 12-hour or 24-hour formats.
* **Timer:** Set a countdown duration (HH:MM:SS), start, pause, or reset the countdown.
* **Stopwatch:** Track elapsed time. Set optional time limits and choose whether the display should "Stop at limit" or "Blink at limit".

**Important:** Changes made in the web interface (like updating the time format or starting a timer internally) will not push to the physical monitor until you click the corresponding **"Send to Display"** button.

### Settings Panel

Access the settings panel by clicking the gear icon in the header to:

* **Configure Companion Integration**: Link your Bitfocus Companion IP and Port.
* **Configure Access Control**: Enable or disable the password requirement.
* **Change Password**: Update your Master Password.
* **Factory Reset**: Factory reset the application, removing all timer states and passwords.

---

## Bitfocus Companion Integration

Pi Timer supports comprehensive, two-way integration with Bitfocus Companion, allowing you to control the timer, set durations, push displays, and view live blinking feedback directly on a Stream Deck.

### Step 1: Configure Pi Timer

1. Open the Pi Timer Web Interface and go to **Settings**.
2. **UNCHECK "Require password for access"** and save. *(Companion cannot send HTTP commands if the password blocks it).*
3. Under **Companion Integration**, enter the IP address and Port of the computer running Companion (e.g., `192.168.1.100:8000`). Save the settings.

### Step 2: Configure Companion Connections

1. In Companion, go to the **Connections** tab.
2. Search for and add: **Generic HTTP Requests**.
3. Set the **Base URL** to your Pi Timer's address (e.g., `http://192.168.1.50:5001`).

### Step 3: Setup Variables inside Companion

1. Go to Companion's **Settings** tab. Enable the **HTTP API** (note the port, usually `8000`).
2. Go to the **Variables** tab -> **Custom Variables**.
3. Create the following exact variables (leave values blank, Pi Timer will fill them):
* `comp_t_h`, `comp_t_m`, `comp_t_s` *(Timer input display)*
* `comp_s_h`, `comp_s_m`, `comp_s_s` *(Stopwatch input display)*
* `comp_t_play`, `comp_s_play` *(Dynamic Play/Pause text)*
* `comp_clk_fmt`, `comp_sw_limit` *(Mode tracking text)*
* `comp_live_1`, `comp_live_2` *(Live preview text)*
* `comp_live_blink`, `comp_active_mode` *(Feedback states)*



### Step 4: Building Your Buttons

**For all Action Buttons:** - **Type:** `Generic HTTP Requests: POST`

* **Header:** `Content-Type: application/json`

#### Global Control Buttons

* **Send Clock**: URI: `/api/clock` | Body: `{}`
* **Send Timer**: URI: `/api/timer/send` | Body: `{}`
* **Send Stopwatch**: URI: `/api/stopwatch/send` | Body: `{}`
* **Toggle 12/24 Mode**: URI: `/api/comp/clock/toggle_fmt` | Body: `{}` | Button Text: `$(custom:comp_clk_fmt)`

#### Timer Configuration & Control

* **+ / - Buttons**: URI: `/api/comp/timer/adj`
* Body for Hours: `{"add": 3600}` or `{"sub": 3600}`
* Body for Minutes: `{"add": 60}` or `{"sub": 60}`
* Body for Seconds: `{"add": 1}` or `{"sub": 1}`


* **Value Display Buttons (Text Only)**: `$(custom:comp_t_h)`, `$(custom:comp_t_m)`, `$(custom:comp_t_s)`
* **Start Timer**: URI: `/api/comp/timer/start` | Body: `{}`
* **Pause/Resume Timer**: URI: `/api/comp/timer/toggle` | Body: `{}` | Button Text: `$(custom:comp_t_play)`
* **Reset Timer**: URI: `/api/timer/stop` | Body: `{}`

#### Stopwatch Configuration & Control

* **+ / - Buttons**: URI: `/api/comp/sw/adj`
* Body for Hours: `{"add": 3600}` or `{"sub": 3600}`
* Body for Minutes: `{"add": 60}` or `{"sub": 60}`
* Body for Seconds: `{"add": 1}` or `{"sub": 1}`


* **Value Display Buttons (Text Only)**: `$(custom:comp_s_h)`, `$(custom:comp_s_m)`, `$(custom:comp_s_s)`
* **Start Stopwatch**: URI: `/api/comp/sw/start` | Body: `{}`
* **Pause/Resume Stopwatch**: URI: `/api/comp/sw/toggle` | Body: `{}` | Button Text: `$(custom:comp_s_play)`
* **Reset Stopwatch**: URI: `/api/stopwatch/reset` | Body: `{}`
* **Toggle Limit Action**: URI: `/api/comp/sw/toggle_action` | Body: `{}` | Button Text: `$(custom:comp_sw_limit)`

#### Live Preview & Blinking Button

1. Create a button with no actions.
2. Set Button Text to:
```text
$(custom:comp_live_1)
$(custom:comp_live_2)

```


3. Set background to **Black**, text to **Red**.
4. Go to **Feedbacks** -> Add "Check custom variable value".
5. Variable: `$(custom:comp_live_blink)` | Operator: `=` | Value: `blink`
6. Check **Flash/Blinking**. Change style to **Red Background**, **White Text**.

#### Active Display Feedbacks

To highlight which mode is currently pushed to the screen:

1. On your "Send" buttons, go to the **Feedbacks** tab.
2. Add "Check custom variable value".
3. Variable: `$(custom:comp_active_mode)` | Operator: `=`
4. Value: `clock`, `timer`, or `stopwatch` (depending on the button).
5. Set background color to green or bright red when active.

---

## API Reference

### Timer & Stopwatch Control

* `GET /api/state`: Get current timer/stopwatch state
* `POST /api/timer/start`: Start a countdown timer
* `POST /api/timer/pause`: Pause the active timer
* `POST /api/timer/resume`: Resume the active timer
* `POST /api/timer/stop`: Reset the active timer
* `POST /api/timer/send`: Push timer UI to the display
* `POST /api/stopwatch/start`: Start the stopwatch
* `POST /api/stopwatch/pause`: Pause the stopwatch
* `POST /api/stopwatch/resume`: Resume the stopwatch
* `POST /api/stopwatch/reset`: Reset the stopwatch
* `POST /api/stopwatch/send`: Push stopwatch UI to the display
* `GET /api/clock`: Sync and push the clock to the display

### System & Admin

* `GET /api/admin/config`: Get system configuration
* `POST /api/admin/config`: Update system configuration
* `POST /api/admin/reset`: Factory reset the application
* `POST /api/password/change`: Change the master password

## Development

### Project Structure

```text
pi-timer/
├── server.py              # Flask web server
├── display.py             # Pygame fullscreen display
├── start-server.sh        # Manual server startup script
├── start-display.sh       # Manual display startup script
├── install.sh             # System installation script
├── enable-autostart.sh    # Systemd and desktop autostart configuration
├── timer_state.json       # Display and time tracking state
├── timer_auth.json        # Password hash
├── timer_config.json      # Application settings (login, clock format, companion)
└── timer_secret.key       # Session secret

```