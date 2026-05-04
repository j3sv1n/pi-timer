#!/usr/bin/env python3
"""
Pi Timer - Web Management Server
Timer and stopwatch control via a web interface.
Runs on port 5001.
"""

import os
import json
import time
import secrets
from pathlib import Path
from flask import (Flask, request, jsonify, send_from_directory,
                   render_template_string, abort, session, redirect, url_for)
from werkzeug.security import generate_password_hash, check_password_hash
import re

BASE_DIR   = Path(__file__).parent
STATE_FILE = BASE_DIR / "timer_state.json"
USERS_FILE = BASE_DIR / "timer_users.json"
SECRET_FILE = BASE_DIR / "timer_secret.key"
CONFIG_FILE = BASE_DIR / "timer_config.json"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

if SECRET_FILE.exists():
    app.secret_key = SECRET_FILE.read_text().strip()
else:
    app.secret_key = secrets.token_hex(32)
    SECRET_FILE.write_text(app.secret_key)
    try:
        os.chmod(SECRET_FILE, 0o600)
    except Exception:
        pass

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


def read_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "mode": "clock",  # clock, timer, stopwatch
        "timer_seconds": 0,
        "timer_remaining": 0,
        "timer_running": False,
        "timer_limit_seconds": 0,
        "timer_limit_action": "stop",  # stop or blink
        "stopwatch_seconds": 0,
        "stopwatch_running": False,
        "stopwatch_limit_seconds": 0,
        "stopwatch_limit_action": "stop",  # stop or blink
    }


def write_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def read_users():
    if USERS_FILE.exists():
        try:
            data = json.loads(USERS_FILE.read_text())
            if "users" in data and "owner" in data:
                return data
        except Exception:
            pass
    return {"owner": None, "users": {}}


def write_users(data):
    USERS_FILE.write_text(json.dumps(data, indent=2))
    try:
        os.chmod(USERS_FILE, 0o600)
    except Exception:
        pass


def read_config():
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            if "login_enabled" in data:
                return data
        except Exception:
            pass
    return {"login_enabled": True}


def write_config(data):
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def is_login_enabled():
    return read_config().get("login_enabled", True)


def is_authenticated():
    if not is_login_enabled():
        return True
    return session.get("user_id") is not None


def is_admin():
    if not is_login_enabled():
        return True
    users = read_users()
    user_id = session.get("user_id")
    return user_id in users.get("users", {}) and users["users"][user_id].get("is_admin", False)


def is_owner():
    if not is_login_enabled():
        return True
    return session.get("user_id") == read_users().get("owner")


# ──────────────────────────────────────────────────────────────────────────────
# Auth Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/setup", methods=["GET", "POST"])
def setup():
    """First-time setup: create owner account and choose login preference."""
    users = read_users()
    if users["owner"] is not None:
        return redirect(url_for("index"))
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        enable_login = request.form.get("enable_login") == "true"
        
        if not username or not password:
            return render_template_string(SETUP_HTML, error="Username and password required.")
        if len(username) < 3 or len(password) < 3:
            return render_template_string(SETUP_HTML, error="Username and password must be at least 3 characters.")
        if not USERNAME_RE.match(username):
            return render_template_string(SETUP_HTML, error="Invalid username.")
        
        users["owner"] = username
        users["users"][username] = {
            "password_hash": generate_password_hash(password),
            "is_admin": True,
        }
        write_users(users)
        write_config({"login_enabled": enable_login})
        session["user_id"] = username
        return redirect(url_for("index"))
    
    return render_template_string(SETUP_HTML, error=None)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Login for existing users."""
    if not is_login_enabled():
        return redirect(url_for("index"))
    
    if session.get("user_id"):
        return redirect(url_for("index"))
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        users = read_users()
        
        if username in users.get("users", {}):
            user = users["users"][username]
            if check_password_hash(user["password_hash"], password):
                session["user_id"] = username
                return redirect(url_for("index"))
        
        return render_template_string(LOGIN_HTML, error="Invalid username or password.")
    
    return render_template_string(LOGIN_HTML, error=None)


@app.route("/logout", methods=["POST"])
def logout():
    """Logout the current user."""
    session.pop("user_id", None)
    return redirect(url_for("login" if is_login_enabled() else "index"))


# ──────────────────────────────────────────────────────────────────────────────
# Main Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Main dashboard."""
    users = read_users()
    if users["owner"] is None:
        return redirect(url_for("setup"))
    
    if not is_authenticated():
        return redirect(url_for("login"))
    
    login_enabled = is_login_enabled()
    is_admin_user = is_admin() if login_enabled else True
    
    return render_template_string(DASHBOARD_HTML, 
                                 login_enabled=login_enabled,
                                 is_admin=is_admin_user)


@app.route("/admin")
def admin():
    """Admin panel."""
    users = read_users()
    if users["owner"] is None:
        return redirect(url_for("setup"))
    
    if not is_authenticated():
        return redirect(url_for("login"))
    
    if not is_admin():
        abort(403)
    
    login_enabled = is_login_enabled()
    is_owner_user = is_owner()
    
    return render_template_string(ADMIN_HTML,
                                 login_enabled=login_enabled,
                                 is_owner=is_owner_user,
                                 current_user=session.get("user_id"))


# ──────────────────────────────────────────────────────────────────────────────
# API Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/state", methods=["GET"])
def api_get_state():
    """Get current timer/stopwatch state."""
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(read_state())


@app.route("/api/state", methods=["POST"])
def api_update_state():
    """Update timer/stopwatch state."""
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    data = request.get_json() or {}
    
    # Update fields as needed
    for key in ["mode", "timer_seconds", "timer_remaining", "timer_running",
                "timer_limit_seconds", "timer_limit_action",
                "stopwatch_seconds", "stopwatch_running",
                "stopwatch_limit_seconds", "stopwatch_limit_action"]:
        if key in data:
            state[key] = data[key]
    
    write_state(state)
    return jsonify(state)


@app.route("/api/timer/start", methods=["POST"])
def api_timer_start():
    """Start a timer with specified duration."""
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json() or {}
    duration = data.get("duration", 60)  # seconds
    limit_seconds = data.get("limit_seconds", 0)
    limit_action = data.get("limit_action", "stop")
    
    state = read_state()
    state["mode"] = "timer"
    state["timer_seconds"] = duration
    state["timer_remaining"] = duration
    state["timer_running"] = True
    state["timer_limit_seconds"] = limit_seconds
    state["timer_limit_action"] = limit_action
    write_state(state)
    
    return jsonify(state)


@app.route("/api/timer/pause", methods=["POST"])
def api_timer_pause():
    """Pause the timer."""
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    state["timer_running"] = False
    write_state(state)
    return jsonify(state)


@app.route("/api/timer/resume", methods=["POST"])
def api_timer_resume():
    """Resume the timer."""
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    state["timer_running"] = True
    write_state(state)
    return jsonify(state)


@app.route("/api/timer/stop", methods=["POST"])
def api_timer_stop():
    """Stop and reset the timer."""
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    state["mode"] = "clock"
    state["timer_running"] = False
    state["timer_remaining"] = 0
    write_state(state)
    return jsonify(state)


@app.route("/api/stopwatch/start", methods=["POST"])
def api_stopwatch_start():
    """Start the stopwatch."""
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json() or {}
    limit_seconds = data.get("limit_seconds", 0)
    limit_action = data.get("limit_action", "stop")
    
    state = read_state()
    state["mode"] = "stopwatch"
    state["stopwatch_running"] = True
    state["stopwatch_seconds"] = 0
    state["stopwatch_limit_seconds"] = limit_seconds
    state["stopwatch_limit_action"] = limit_action
    write_state(state)
    return jsonify(state)


@app.route("/api/stopwatch/pause", methods=["POST"])
def api_stopwatch_pause():
    """Pause the stopwatch."""
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    state["stopwatch_running"] = False
    write_state(state)
    return jsonify(state)


@app.route("/api/stopwatch/resume", methods=["POST"])
def api_stopwatch_resume():
    """Resume the stopwatch."""
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    state["stopwatch_running"] = True
    write_state(state)
    return jsonify(state)


@app.route("/api/stopwatch/stop", methods=["POST"])
def api_stopwatch_stop():
    """Stop and reset the stopwatch."""
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    state["mode"] = "clock"
    state["stopwatch_running"] = False
    state["stopwatch_seconds"] = 0
    write_state(state)
    return jsonify(state)


@app.route("/api/clock", methods=["GET"])
def api_clock():
    """Get current time for clock display."""
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    state["mode"] = "clock"
    write_state(state)
    return jsonify({"timestamp": time.time()})


# Admin API Routes

@app.route("/api/admin/users", methods=["GET"])
def api_admin_get_users():
    """Get list of all users."""
    if not is_authenticated() or not is_admin():
        return jsonify({"error": "Unauthorized"}), 401
    
    users = read_users()
    return jsonify({
        "owner": users.get("owner"),
        "users": {uid: {"is_admin": u.get("is_admin", False)} 
                  for uid, u in users.get("users", {}).items()}
    })


@app.route("/api/admin/config", methods=["GET", "POST"])
def api_admin_config():
    """Get or update app configuration."""
    if not is_authenticated() or not is_owner():
        return jsonify({"error": "Unauthorized"}), 401
    
    if request.method == "GET":
        return jsonify(read_config())
    
    data = request.get_json() or {}
    config = read_config()
    if "login_enabled" in data:
        config["login_enabled"] = data["login_enabled"]
    write_config(config)
    return jsonify(config)


@app.route("/api/admin/reset", methods=["POST"])
def api_admin_reset():
    """Reset app to factory state (owner only)."""
    if not is_authenticated() or not is_owner():
        return jsonify({"error": "Unauthorized"}), 401
    
    write_state({
        "mode": "clock",
        "timer_seconds": 0,
        "timer_remaining": 0,
        "timer_running": False,
        "timer_limit_seconds": 0,
        "timer_limit_action": "stop",
        "stopwatch_seconds": 0,
        "stopwatch_running": False,
        "stopwatch_limit_seconds": 0,
        "stopwatch_limit_action": "stop",
    })
    
    # Reset users and config
    write_users({"owner": None, "users": {}})
    write_config({"login_enabled": True})
    
    session.pop("user_id", None)
    return jsonify({"status": "reset"})


# ──────────────────────────────────────────────────────────────────────────────
# HTML Templates
# ──────────────────────────────────────────────────────────────────────────────

SETUP_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Pi Timer - Setup</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #000;
            color: #fff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            background: #1a1a1a;
            padding: 40px;
            border-radius: 12px;
            max-width: 400px;
            width: 100%;
            border: 2px solid #ff4444;
        }
        h1 {
            margin-bottom: 10px;
            font-size: 28px;
        }
        .subtitle {
            color: #aaa;
            margin-bottom: 30px;
            font-size: 14px;
        }
        .error {
            background: #ff444433;
            color: #ff8888;
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 20px;
            font-size: 14px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-size: 14px;
            color: #ccc;
        }
        input[type="text"],
        input[type="password"] {
            width: 100%;
            padding: 12px;
            background: #2a2a2a;
            border: 1px solid #444;
            color: #fff;
            border-radius: 6px;
            font-size: 14px;
        }
        input[type="text"]:focus,
        input[type="password"]:focus {
            outline: none;
            border-color: #ff4444;
        }
        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 25px;
        }
        input[type="checkbox"] {
            width: 18px;
            height: 18px;
            cursor: pointer;
            accent-color: #ff4444;
        }
        .checkbox-group label {
            margin: 0;
            cursor: pointer;
            font-size: 14px;
        }
        button {
            width: 100%;
            padding: 14px;
            background: #ff4444;
            color: #000;
            border: none;
            border-radius: 6px;
            font-weight: bold;
            font-size: 16px;
            cursor: pointer;
            transition: background 0.3s;
        }
        button:hover {
            background: #ff6666;
        }
        button:active {
            background: #cc3333;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Pi Timer</h1>
        <p class="subtitle">First-time setup</p>
        
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        
        <form method="post">
            <div class="form-group">
                <label for="username">Owner Username</label>
                <input type="text" id="username" name="username" placeholder="Choose a username" required>
            </div>
            
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" placeholder="Choose a password" required>
            </div>
            
            <div class="checkbox-group">
                <input type="checkbox" id="enable_login" name="enable_login" value="true" checked>
                <label for="enable_login">Require login (disable for public access)</label>
            </div>
            
            <button type="submit">Create Owner Account</button>
        </form>
    </div>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Pi Timer - Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #000;
            color: #fff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            background: #1a1a1a;
            padding: 40px;
            border-radius: 12px;
            max-width: 400px;
            width: 100%;
            border: 2px solid #ff4444;
        }
        h1 {
            margin-bottom: 10px;
            font-size: 28px;
        }
        .subtitle {
            color: #aaa;
            margin-bottom: 30px;
            font-size: 14px;
        }
        .error {
            background: #ff444433;
            color: #ff8888;
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 20px;
            font-size: 14px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-size: 14px;
            color: #ccc;
        }
        input[type="text"],
        input[type="password"] {
            width: 100%;
            padding: 12px;
            background: #2a2a2a;
            border: 1px solid #444;
            color: #fff;
            border-radius: 6px;
            font-size: 14px;
        }
        input[type="text"]:focus,
        input[type="password"]:focus {
            outline: none;
            border-color: #ff4444;
        }
        button {
            width: 100%;
            padding: 14px;
            background: #ff4444;
            color: #000;
            border: none;
            border-radius: 6px;
            font-weight: bold;
            font-size: 16px;
            cursor: pointer;
            transition: background 0.3s;
        }
        button:hover {
            background: #ff6666;
        }
        button:active {
            background: #cc3333;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Pi Timer</h1>
        <p class="subtitle">Login</p>
        
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        
        <form method="post">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" placeholder="Username" required autofocus>
            </div>
            
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" placeholder="Password" required>
            </div>
            
            <button type="submit">Login</button>
        </form>
    </div>
</body>
</html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Pi Timer</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #000;
            color: #fff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            padding: 20px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
        }
        .header h1 {
            font-size: 32px;
        }
        .header a {
            color: #ff4444;
            text-decoration: none;
            font-size: 14px;
            padding: 8px 16px;
            border: 1px solid #ff4444;
            border-radius: 6px;
            transition: all 0.3s;
        }
        .header a:hover {
            background: #ff4444;
            color: #000;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 30px;
            border-bottom: 2px solid #333;
        }
        .tab-btn {
            padding: 12px 24px;
            background: none;
            border: none;
            color: #777;
            font-size: 16px;
            cursor: pointer;
            border-bottom: 3px solid transparent;
            transition: all 0.3s;
        }
        .tab-btn.active {
            color: #ff4444;
            border-bottom-color: #ff4444;
        }
        .tab-btn:hover {
            color: #fff;
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }
        .control-group {
            background: #1a1a1a;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 20px;
            border: 1px solid #333;
        }
        .control-row {
            margin-bottom: 20px;
        }
        .control-row:last-child {
            margin-bottom: 0;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-size: 14px;
            color: #aaa;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        input[type="number"],
        input[type="text"],
        select {
            width: 100%;
            padding: 12px;
            background: #2a2a2a;
            border: 1px solid #444;
            color: #fff;
            border-radius: 6px;
            font-size: 14px;
        }
        input[type="number"]:focus,
        input[type="text"]:focus,
        select:focus {
            outline: none;
            border-color: #ff4444;
        }
        .button-group {
            display: flex;
            gap: 10px;
            margin-top: 20px;
        }
        button {
            flex: 1;
            padding: 14px;
            background: #ff4444;
            color: #000;
            border: none;
            border-radius: 6px;
            font-weight: bold;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.3s;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        button:hover {
            background: #ff6666;
        }
        button:active {
            background: #cc3333;
        }
        button.secondary {
            background: #333;
            color: #fff;
        }
        button.secondary:hover {
            background: #444;
        }
        .time-display {
            background: #000;
            border: 2px solid #ff4444;
            padding: 40px;
            border-radius: 12px;
            text-align: center;
            font-size: 64px;
            font-weight: bold;
            color: #ff4444;
            font-family: 'Courier New', monospace;
            margin-bottom: 30px;
        }
        .info-text {
            color: #777;
            font-size: 12px;
            margin-top: 8px;
        }
        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-top: 12px;
        }
        input[type="checkbox"] {
            width: 18px;
            height: 18px;
            cursor: pointer;
            accent-color: #ff4444;
        }
        .checkbox-group label {
            margin: 0;
            cursor: pointer;
            font-size: 14px;
            text-transform: none;
            letter-spacing: normal;
            color: #aaa;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🕐 Pi Timer</h1>
        <div>
            {% if login_enabled %}
            <a href="/admin">Admin</a>
            <form method="post" action="/logout" style="display:inline; margin-left: 10px;">
                <button type="submit" style="padding: 8px 16px; margin: 0; width: auto;">Logout</button>
            </form>
            {% endif %}
        </div>
    </div>
    
    <div class="container">
        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('clock')">Clock</button>
            <button class="tab-btn" onclick="switchTab('timer')">Timer</button>
            <button class="tab-btn" onclick="switchTab('stopwatch')">Stopwatch</button>
        </div>
        
        <!-- Clock Tab -->
        <div id="clock" class="tab-content active">
            <div class="control-group">
                <div class="time-display" id="clockDisplay">00:00:00</div>
                <p class="info-text">Current time displayed on fullscreen display</p>
            </div>
        </div>
        
        <!-- Timer Tab -->
        <div id="timer" class="tab-content">
            <div class="control-group">
                <div class="time-display" id="timerDisplay">00:00:00</div>
                
                <div class="control-row">
                    <label for="timerDuration">Duration (seconds)</label>
                    <input type="number" id="timerDuration" value="60" min="1">
                </div>
                
                <div class="control-row">
                    <label for="timerLimit">Limit (optional, 0 = no limit)</label>
                    <input type="number" id="timerLimit" value="0" min="0">
                </div>
                
                <div class="control-row">
                    <label for="timerLimitAction">Limit Action</label>
                    <select id="timerLimitAction">
                        <option value="stop">Stop at limit</option>
                        <option value="blink">Blink at limit</option>
                    </select>
                    <p class="info-text">Blink = background blinks red with white text</p>
                </div>
                
                <div class="button-group">
                    <button onclick="startTimer()">Start</button>
                    <button class="secondary" onclick="pauseTimer()">Pause</button>
                    <button class="secondary" onclick="stopTimer()">Stop</button>
                </div>
            </div>
        </div>
        
        <!-- Stopwatch Tab -->
        <div id="stopwatch" class="tab-content">
            <div class="control-group">
                <div class="time-display" id="stopwatchDisplay">00:00:00</div>
                
                <div class="control-row">
                    <label for="stopwatchLimit">Limit (optional, 0 = no limit)</label>
                    <input type="number" id="stopwatchLimit" value="0" min="0">
                    <p class="info-text">Time in seconds. Stopwatch will stop or blink when limit is reached.</p>
                </div>
                
                <div class="control-row">
                    <label for="stopwatchLimitAction">Limit Action</label>
                    <select id="stopwatchLimitAction">
                        <option value="stop">Stop at limit</option>
                        <option value="blink">Blink at limit</option>
                    </select>
                    <p class="info-text">Blink = background blinks red with white text</p>
                </div>
                
                <div class="button-group">
                    <button onclick="startStopwatch()">Start</button>
                    <button class="secondary" onclick="pauseStopwatch()">Pause</button>
                    <button class="secondary" onclick="stopStopwatch()">Stop</button>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        const STATE_UPDATE_INTERVAL = 100;
        
        function switchTab(tab) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tab).classList.add('active');
            document.querySelector(`[onclick="switchTab('${tab}')"]`).classList.add('active');
        }
        
        function formatTime(seconds) {
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            const s = seconds % 60;
            return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
        }
        
        function updateDisplay() {
            fetch('/api/state')
                .then(r => r.json())
                .then(state => {
                    if (state.mode === 'clock') {
                        fetch('/api/clock').then(r => r.json()).then(data => {
                            const now = new Date(data.timestamp * 1000);
                            const h = String(now.getHours()).padStart(2, '0');
                            const m = String(now.getMinutes()).padStart(2, '0');
                            const s = String(now.getSeconds()).padStart(2, '0');
                            document.getElementById('clockDisplay').textContent = `${h}:${m}:${s}`;
                        });
                    } else if (state.mode === 'timer') {
                        document.getElementById('timerDisplay').textContent = formatTime(state.timer_remaining);
                    } else if (state.mode === 'stopwatch') {
                        document.getElementById('stopwatchDisplay').textContent = formatTime(state.stopwatch_seconds);
                    }
                });
        }
        
        function startTimer() {
            const duration = parseInt(document.getElementById('timerDuration').value) || 60;
            const limit = parseInt(document.getElementById('timerLimit').value) || 0;
            const action = document.getElementById('timerLimitAction').value;
            
            fetch('/api/timer/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    duration: duration,
                    limit_seconds: limit,
                    limit_action: action
                })
            }).then(() => updateDisplay());
        }
        
        function pauseTimer() {
            fetch('/api/timer/pause', { method: 'POST' }).then(() => updateDisplay());
        }
        
        function stopTimer() {
            fetch('/api/timer/stop', { method: 'POST' }).then(() => updateDisplay());
        }
        
        function startStopwatch() {
            const limit = parseInt(document.getElementById('stopwatchLimit').value) || 0;
            const action = document.getElementById('stopwatchLimitAction').value;
            
            fetch('/api/stopwatch/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    limit_seconds: limit,
                    limit_action: action
                })
            }).then(() => updateDisplay());
        }
        
        function pauseStopwatch() {
            fetch('/api/stopwatch/pause', { method: 'POST' }).then(() => updateDisplay());
        }
        
        function stopStopwatch() {
            fetch('/api/stopwatch/stop', { method: 'POST' }).then(() => updateDisplay());
        }
        
        // Update display every 100ms
        setInterval(updateDisplay, STATE_UPDATE_INTERVAL);
        updateDisplay();
    </script>
</body>
</html>
"""

ADMIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Pi Timer - Admin</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #000;
            color: #fff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            padding: 20px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
        }
        .header h1 {
            font-size: 32px;
        }
        .header a {
            color: #ff4444;
            text-decoration: none;
            font-size: 14px;
            padding: 8px 16px;
            border: 1px solid #ff4444;
            border-radius: 6px;
            transition: all 0.3s;
        }
        .header a:hover {
            background: #ff4444;
            color: #000;
        }
        .container {
            max-width: 600px;
        }
        .control-group {
            background: #1a1a1a;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 20px;
            border: 1px solid #333;
        }
        .control-group h2 {
            margin-bottom: 20px;
            font-size: 18px;
        }
        .control-row {
            margin-bottom: 20px;
        }
        .control-row:last-child {
            margin-bottom: 0;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-size: 14px;
            color: #aaa;
        }
        input[type="checkbox"] {
            width: 18px;
            height: 18px;
            cursor: pointer;
            accent-color: #ff4444;
        }
        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .checkbox-group label {
            margin: 0;
            cursor: pointer;
            font-size: 14px;
        }
        button {
            padding: 14px 24px;
            background: #ff4444;
            color: #000;
            border: none;
            border-radius: 6px;
            font-weight: bold;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.3s;
            width: 100%;
        }
        button:hover {
            background: #ff6666;
        }
        button:active {
            background: #cc3333;
        }
        button.danger {
            background: #cc0000;
        }
        button.danger:hover {
            background: #ff0000;
        }
        .info {
            color: #777;
            font-size: 12px;
            margin-top: 8px;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>⚙️ Admin Panel</h1>
        <a href="/">Back to Timer</a>
    </div>
    
    <div class="container">
        <div class="control-group">
            <h2>Login System</h2>
            <div class="control-row">
                <div class="checkbox-group">
                    <input type="checkbox" id="loginEnabled">
                    <label for="loginEnabled">Require login (disable for public access)</label>
                </div>
                <p class="info">When disabled, anyone can access the timer without authentication.</p>
            </div>
            <button onclick="saveLoginSetting()" style="margin-top: 20px;">Save Settings</button>
        </div>
        
        {% if is_owner %}
        <div class="control-group">
            <h2>Reset App</h2>
            <p style="margin-bottom: 20px; color: #aaa; font-size: 14px;">
                This will reset all timers to factory state and remove all user accounts (except owner).
            </p>
            <button class="danger" onclick="resetApp()">Reset to Factory State</button>
        </div>
        {% endif %}
    </div>
    
    <script>
        function loadLoginSetting() {
            fetch('/api/admin/config')
                .then(r => r.json())
                .then(config => {
                    document.getElementById('loginEnabled').checked = config.login_enabled;
                });
        }
        
        function saveLoginSetting() {
            const enabled = document.getElementById('loginEnabled').checked;
            fetch('/api/admin/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ login_enabled: enabled })
            }).then(r => r.json()).then(() => {
                alert('Settings saved');
                loadLoginSetting();
            });
        }
        
        function resetApp() {
            if (confirm('Are you sure? This will reset the app to factory state.')) {
                fetch('/api/admin/reset', { method: 'POST' })
                    .then(r => r.json())
                    .then(() => {
                        alert('App reset complete. Redirecting to setup...');
                        window.location.href = '/setup';
                    });
            }
        }
        
        loadLoginSetting();
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
