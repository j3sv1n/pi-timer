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
        session["user_id"] = username
        return redirect(url_for("setup_login"))
    
    return render_template_string(SETUP_HTML, error=None)


@app.route("/setup/login", methods=["GET", "POST"])
def setup_login():
    """Setup login preference after owner creation."""
    users = read_users()
    if users["owner"] is None:
        return redirect(url_for("setup"))
    
    if not session.get("user_id"):
        return redirect(url_for("setup"))
    
    if request.method == "POST":
        enable_login = request.form.get("enable_login") == "true"
        write_config({"login_enabled": enable_login})
        return redirect(url_for("index"))
    
    return render_template_string(SETUP_LOGIN_HTML)


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
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Pi Timer - Setup</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#0d0f14;--surface:#161920;--border:#252830;--accent:#b91c1c;--text:#e8eaf0;--muted:#6b7280;--danger:#ff8888}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif;padding:24px}
.panel{width:min(460px,100%);background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:28px;box-shadow:0 20px 60px rgba(0,0,0,.35)}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:1.45rem;margin-bottom:4px}
.logo span{color:var(--accent)}
h1{font-family:'Syne',sans-serif;font-size:1rem;margin:0 0 20px;color:var(--muted);font-weight:600}
label{display:block;color:var(--muted);font-size:.82rem;margin:14px 0 6px}
input{width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:7px;padding:10px 12px;font:inherit;outline:none}
input:focus{border-color:var(--accent)}
button,.link-btn{display:inline-flex;justify-content:center;align-items:center;margin-top:18px;width:100%;border:0;border-radius:7px;padding:10px 12px;background:var(--accent);color:var(--bg);font-weight:700;font:inherit;text-decoration:none;cursor:pointer}
.secondary{background:transparent;color:var(--muted);border:1px solid var(--border)}
.msg{margin:0 0 12px;color:var(--danger);font-size:.88rem}
.hint{color:var(--muted);font-size:.82rem;line-height:1.45;margin-top:14px}
</style>
</head>
<body>
<div class="panel">
<div class="logo">Pi <span>Timer</span></div>
<h1>First-time setup</h1>
{% if error %}<p class="msg">{{ error }}</p>{% endif %}
<form method="post">
<label>Owner username</label><input name="username" autocomplete="username" required autofocus>
<label>Password</label><input name="password" type="password" autocomplete="new-password" required minlength="8">
<button type="submit">Create Owner Account</button>
</form>
<p class="hint">This first account becomes the protected owner account.</p>
</div>
</body>
</html>
"""

SETUP_LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Pi Timer - Setup Login</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#0d0f14;--surface:#161920;--border:#252830;--accent:#b91c1c;--text:#e8eaf0;--muted:#6b7280;--danger:#ff8888}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif;padding:24px}
.panel{width:min(460px,100%);background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:28px;box-shadow:0 20px 60px rgba(0,0,0,.35)}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:1.45rem;margin-bottom:4px}
.logo span{color:var(--accent)}
h1{font-family:'Syne',sans-serif;font-size:1rem;margin:0 0 20px;color:var(--muted);font-weight:600}
label{display:block;color:var(--muted);font-size:.82rem;margin:14px 0 6px}
input[type="checkbox"]{width:18px;height:18px;margin-right:10px}
.checkbox-group{display:flex;align-items:center;margin:16px 0}
button,.link-btn{display:inline-flex;justify-content:center;align-items:center;margin-top:18px;width:100%;border:0;border-radius:7px;padding:10px 12px;background:var(--accent);color:var(--bg);font-weight:700;font:inherit;text-decoration:none;cursor:pointer}
.secondary{background:transparent;color:var(--muted);border:1px solid var(--border)}
.msg{margin:0 0 12px;color:var(--danger);font-size:.88rem}
.hint{color:var(--muted);font-size:.82rem;line-height:1.45;margin-top:14px}
</style>
</head>
<body>
<div class="panel">
<div class="logo">Pi <span>Timer</span></div>
<h1>Enable Login System</h1>
<form method="post">
<div class="checkbox-group">
<input type="checkbox" id="enable_login" name="enable_login" value="true" checked>
<label for="enable_login">Require login for access</label>
</div>
<p class="hint">Enable to protect the timer with authentication. Disable for public access.</p>
<button type="submit">Continue</button>
</form>
</div>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Pi Timer - Login</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#0d0f14;--surface:#161920;--border:#252830;--accent:#ff0000;--text:#e8eaf0;--muted:#6b7280;--danger:#ff8888}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif;padding:24px}
.panel{width:min(460px,100%);background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:28px;box-shadow:0 20px 60px rgba(0,0,0,.35)}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:1.45rem;margin-bottom:4px}
.logo span{color:var(--accent)}
h1{font-family:'Syne',sans-serif;font-size:1rem;margin:0 0 20px;color:var(--muted);font-weight:600}
label{display:block;color:var(--muted);font-size:.82rem;margin:14px 0 6px}
input{width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:7px;padding:10px 12px;font:inherit;outline:none}
input:focus{border-color:var(--accent)}
button,.link-btn{display:inline-flex;justify-content:center;align-items:center;margin-top:18px;width:100%;border:0;border-radius:7px;padding:10px 12px;background:var(--accent);color:var(--bg);font-weight:700;font:inherit;text-decoration:none;cursor:pointer}
.secondary{background:transparent;color:var(--muted);border:1px solid var(--border)}
.msg{margin:0 0 12px;color:var(--danger);font-size:.88rem}
</style>
</head>
<body>
<div class="panel">
<div class="logo">Pi <span>Timer</span></div>
<h1>Login</h1>
{% if error %}<p class="msg">{{ error }}</p>{% endif %}
<form method="post">
<label>Username</label><input name="username" autocomplete="username" required autofocus>
<label>Password</label><input name="password" type="password" autocomplete="current-password" required>
<button type="submit">Log In</button>
</form>
</div>
</body>
</html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Pi Timer</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#0d0f14;--surface:#161920;--border:#252830;--accent:#d14242;--text:#e8eaf0;--muted:#9ca3af;--success:#22c55e}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif}
header{display:flex;align-items:center;gap:14px;padding:22px 28px;background:var(--surface);border-bottom:1px solid var(--border)}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:1.35rem}.logo span{color:var(--accent)}
.spacer{flex:1}
a,button{color:var(--accent);text-decoration:none;font:inherit;border:1px solid transparent;border-radius:7px;padding:9px 12px;background:transparent;cursor:pointer}
button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
button.secondary{background:transparent;color:var(--muted);border:1px solid var(--border)}
main{max-width:860px;margin:0 auto;padding:30px 22px}
h1{font-family:'Syne',sans-serif;font-size:1.1rem;margin:0 0 18px}
.tabs{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:24px}
.tab-btn{border:1px solid var(--border);border-radius:10px;padding:12px 16px;background:var(--surface);color:var(--muted);font:inherit;cursor:pointer}
.tab-btn.active{color:var(--text);border-color:var(--accent);background:#17171b}
.tab-content{display:none}
.tab-content.active{display:block}
.card{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:26px;box-shadow:0 20px 60px rgba(0,0,0,.25)}
.time-display{width:100%;min-height:180px;display:flex;align-items:center;justify-content:center;border-radius:18px;background:#080808;border:1px solid rgba(185,28,28,.25);color:#b91c1c;font-family:'Syne',sans-serif;font-size:clamp(4rem,10vw,8rem);font-weight:800;text-align:center;margin-bottom:24px;padding:30px 24px}
.control-row{margin-bottom:20px}
label{display:block;margin-bottom:10px;color:var(--muted);font-size:.82rem;text-transform:uppercase;letter-spacing:.08em}
input,select{width:100%;border-radius:10px;border:1px solid var(--border);background:var(--bg);color:var(--text);padding:12px 14px;font:inherit;outline:none}
input:focus,select:focus{border-color:var(--accent)}
.time-inputs{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.button-group{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:16px}
.button-group button{border:1px solid var(--border);border-radius:10px;padding:14px 16px;font:inherit;font-weight:700;cursor:pointer;background:var(--accent);color:#fff}
.button-group button.secondary{background:transparent;color:var(--text);border-color:var(--border)}
.button-group button.secondary:hover{background:#17171b}
.info-text{color:var(--muted);font-size:.82rem;line-height:1.6;margin-top:10px}
.send-btn{margin-top:16px;padding:12px 16px;background:var(--accent);color:#fff;border:0;border-radius:10px;font-weight:700;cursor:pointer}
</style>
</head>
<body>
<header><div class="logo">Pi <span>Timer</span></div><div class="spacer"></div>{% if login_enabled %}<a href="/admin">Admin</a><form method="post" action="/logout" style="display:inline"><button class="primary" type="submit">Logout</button></form>{% endif %}</header>
<main>
<h1>Control panel</h1>
<div class="tabs"><button class="tab-btn active" onclick="switchTab('clock')">Clock</button><button class="tab-btn" onclick="switchTab('timer')">Timer</button><button class="tab-btn" onclick="switchTab('stopwatch')">Stopwatch</button></div>
<div id="clock" class="tab-content active"><div class="card"><div class="time-display" id="clockDisplay">00:00</div><p class="info-text">Current time displayed on the fullscreen display</p><button class="send-btn" onclick="sendToDisplay('clock')">Send Clock to Display</button></div></div>
<div id="timer" class="tab-content"><div class="card"><div class="time-display" id="timerDisplay">00:00</div><div class="control-row"><label for="timerHours">Duration</label><div class="time-inputs"><input type="number" id="timerHours" placeholder="HH" min="0" max="99"><input type="number" id="timerMinutes" placeholder="MM" min="0" max="59"><input type="number" id="timerSeconds" placeholder="SS" min="0" max="59"></div></div><div class="button-group"><button type="button" onclick="startTimer()">Start</button><button type="button" class="secondary" onclick="pauseTimer()">Pause</button><button type="button" class="secondary" onclick="stopTimer()">Stop</button></div><button class="send-btn" onclick="sendToDisplay('timer')">Send Timer to Display</button></div></div>
<div id="stopwatch" class="tab-content"><div class="card"><div class="time-display" id="stopwatchDisplay">00:00</div><div class="control-row"><label for="stopwatchHours">Stopwatch limit</label><div class="time-inputs"><input type="number" id="stopwatchHours" placeholder="HH" min="0" max="99"><input type="number" id="stopwatchMinutes" placeholder="MM" min="0" max="59"><input type="number" id="stopwatchSeconds" placeholder="SS" min="0" max="59"></div><p class="info-text">Set a required stopwatch limit before starting.</p></div><div class="control-row"><label for="stopwatchLimitAction">Limit Action</label><select id="stopwatchLimitAction"><option value="stop">Stop at limit</option><option value="blink">Blink at limit</option></select><p class="info-text">Blink means the display background will flash red when the limit is reached.</p></div><div class="button-group"><button type="button" onclick="startStopwatch()">Start</button><button type="button" class="secondary" onclick="pauseStopwatch()">Pause</button><button type="button" class="secondary" onclick="stopStopwatch()">Stop</button></div><button class="send-btn" onclick="sendToDisplay('stopwatch')">Send Stopwatch to Display</button></div></div>
</main>
<script>
const STATE_UPDATE_INTERVAL = 100;
function switchTab(tab){document.querySelectorAll('.tab-content').forEach(el=>el.classList.remove('active'));document.querySelectorAll('.tab-btn').forEach(el=>el.classList.remove('active'));document.getElementById(tab).classList.add('active');document.querySelector(`[onclick="switchTab('${tab}')"]`).classList.add('active');if(tab==='clock'){fetch('/api/clock').then(()=>updateDisplay());}else{updateDisplay();}}
function formatMinutesSeconds(seconds){const m=Math.floor(seconds/60);const s=Math.floor(seconds%60);return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;}
function formatHourMinute(date){const h=String(date.getHours()).padStart(2,'0');const m=String(date.getMinutes()).padStart(2,'0');const colon = Math.floor(Date.now()/500) % 2 === 0 ? ':' : ' ';return `${h}${colon}${m}`;}
function updateDisplay(){fetch('/api/state').then(r=>r.json()).then(state=>{if(state.mode==='clock'){fetch('/api/clock').then(()=>{const now=new Date();document.getElementById('clockDisplay').textContent=formatHourMinute(now);});}else if(state.mode==='timer'){document.getElementById('timerDisplay').textContent=formatMinutesSeconds(state.timer_remaining);}else if(state.mode==='stopwatch'){document.getElementById('stopwatchDisplay').textContent=formatMinutesSeconds(state.stopwatch_seconds);}});} 
function sendToDisplay(mode){if(mode==='clock'){fetch('/api/clock',{method:'GET'}).then(()=>updateDisplay());}else if(mode==='timer'){startTimer();}else if(mode==='stopwatch'){startStopwatch();}}
function startTimer(){const h=parseInt(document.getElementById('timerHours').value)||0;const m=parseInt(document.getElementById('timerMinutes').value)||0;const s=parseInt(document.getElementById('timerSeconds').value)||0;const duration=h*3600+m*60+s;if(duration<=0){alert('Set a timer duration before starting.');return;}fetch('/api/timer/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({duration:duration,limit_seconds:0,limit_action:'stop'})}).then(()=>updateDisplay());}
function pauseTimer(){fetch('/api/timer/pause',{method:'POST'}).then(()=>updateDisplay());}
function stopTimer(){fetch('/api/timer/stop',{method:'POST'}).then(()=>updateDisplay());}
function getStopwatchLimit(){const h=parseInt(document.getElementById('stopwatchHours').value)||0;const m=parseInt(document.getElementById('stopwatchMinutes').value)||0;const s=parseInt(document.getElementById('stopwatchSeconds').value)||0;return h*3600+m*60+s;}
function startStopwatch(){const limit=getStopwatchLimit();const action=document.getElementById('stopwatchLimitAction').value;if(limit<=0){alert('Set a stopwatch limit before starting.');return;}fetch('/api/stopwatch/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({limit_seconds:limit,limit_action:action})}).then(()=>updateDisplay());}
function pauseStopwatch(){fetch('/api/stopwatch/pause',{method:'POST'}).then(()=>updateDisplay());}
function stopStopwatch(){fetch('/api/stopwatch/stop',{method:'POST'}).then(()=>updateDisplay());}
setInterval(updateDisplay,STATE_UPDATE_INTERVAL);updateDisplay();
</script>
</body>
</html>
"""

ADMIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Pi Timer - Admin</title>
    <link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
    <style>
        :root{--bg:#0d0f14;--surface:#161920;--border:#252830;--accent:#b91c1c;--text:#e8eaf0;--muted:#6b7280;--danger:#ff4d4d}
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif;min-height:100vh;padding:24px}
        header{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:14px;margin-bottom:24px}
        .logo{font-family:'Syne',sans-serif;font-weight:800;font-size:1.45rem}
        .logo span{color:var(--accent)}
        a,button{font:inherit;cursor:pointer;text-decoration:none;border:1px solid transparent;border-radius:10px;padding:10px 14px}
        a{color:var(--accent);background:transparent}
        button{background:var(--accent);color:var(--bg);border-color:var(--accent)}
        .container{max-width:860px;margin:0 auto;display:grid;gap:20px}
        .control-group{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:24px;box-shadow:0 20px 50px rgba(0,0,0,.25)}
        .control-group h2{margin:0 0 18px;font-family:'Syne',sans-serif;font-size:1rem}
        .control-row{display:grid;gap:14px;margin-bottom:16px}
        .control-row:last-child{margin-bottom:0}
        label{display:block;color:var(--text);font-size:.95rem}
        input[type="checkbox"]{width:18px;height:18px;accent-color:var(--accent)}
        .checkbox-group{display:flex;align-items:center;gap:10px}
        .checkbox-group label{color:var(--text);cursor:pointer}
        .info{color:var(--muted);font-size:.92rem;line-height:1.6;margin-top:10px}
        .danger-zone{background:#181212;border:1px solid rgba(255,0,0,.2);border-radius:16px;padding:22px}
        .danger-zone p{margin:0 0 18px;color:var(--muted);font-size:.92rem;line-height:1.7}
        .danger-zone button{background:#7d1515;color:#fff;border-color:#7d1515}
        .danger-zone button:hover{background:#a11515}
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
            <button onclick="saveLoginSetting()">Save Settings</button>
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
