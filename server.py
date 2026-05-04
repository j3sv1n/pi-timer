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

BASE_DIR   = Path(__file__).parent
STATE_FILE = BASE_DIR / "timer_state.json"
AUTH_FILE  = BASE_DIR / "timer_auth.json"
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


def read_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "mode": "clock",
        "timer_seconds": 0,
        "timer_remaining": 0,
        "timer_running": False,
        "timer_limit_seconds": 0,
        "timer_limit_action": "stop",
        "timer_id": 0,
        "stopwatch_seconds": 0,
        "stopwatch_running": False,
        "stopwatch_limit_seconds": 0,
        "stopwatch_limit_action": "stop",
        "stopwatch_id": 0,
    }


def write_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def read_auth():
    if AUTH_FILE.exists():
        try:
            data = json.loads(AUTH_FILE.read_text())
            if "password_hash" in data:
                return data
        except Exception:
            pass
    return {"password_hash": None}


def write_auth(data):
    AUTH_FILE.write_text(json.dumps(data, indent=2))
    try:
        os.chmod(AUTH_FILE, 0o600)
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
    return {"login_enabled": True, "clock_format": "12"}


def write_config(data):
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def is_login_enabled():
    return read_config().get("login_enabled", True)


def is_authenticated():
    if not is_login_enabled():
        return True
    return session.get("authenticated") is True


# ──────────────────────────────────────────────────────────────────────────────
# Auth Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/setup", methods=["GET", "POST"])
def setup():
    auth = read_auth()
    if auth["password_hash"] is not None:
        return redirect(url_for("index"))
    
    if request.method == "POST":
        password = request.form.get("password", "").strip()
        
        if not password or len(password) < 4:
            return render_template_string(SETUP_HTML, error="Password must be at least 4 characters.")
        
        write_auth({"password_hash": generate_password_hash(password)})
        session["authenticated"] = True
        return redirect(url_for("setup_login"))
    
    return render_template_string(SETUP_HTML, error=None)


@app.route("/setup/login", methods=["GET", "POST"])
def setup_login():
    auth = read_auth()
    if auth["password_hash"] is None:
        return redirect(url_for("setup"))
    
    if not session.get("authenticated"):
        return redirect(url_for("setup"))
    
    if request.method == "POST":
        enable_login = request.form.get("enable_login") == "true"
        config = read_config()
        config["login_enabled"] = enable_login
        write_config(config)
        return redirect(url_for("index"))
    
    return render_template_string(SETUP_LOGIN_HTML)


@app.route("/login", methods=["GET", "POST"])
def login():
    if not is_login_enabled():
        return redirect(url_for("index"))
    
    if session.get("authenticated"):
        return redirect(url_for("index"))
    
    if request.method == "POST":
        password = request.form.get("password", "").strip()
        auth = read_auth()
        
        if auth["password_hash"] and check_password_hash(auth["password_hash"], password):
            session["authenticated"] = True
            return redirect(url_for("index"))
        
        return render_template_string(LOGIN_HTML, error="Invalid password.")
    
    return render_template_string(LOGIN_HTML, error=None)


@app.route("/logout", methods=["POST"])
def logout():
    session.pop("authenticated", None)
    return redirect(url_for("login" if is_login_enabled() else "index"))


# ──────────────────────────────────────────────────────────────────────────────
# Main Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    auth = read_auth()
    if auth["password_hash"] is None:
        return redirect(url_for("setup"))
    
    if not is_authenticated():
        return redirect(url_for("login"))
    
    return render_template_string(DASHBOARD_HTML, login_enabled=is_login_enabled())


@app.route("/settings")
def settings():
    auth = read_auth()
    if auth["password_hash"] is None:
        return redirect(url_for("setup"))
    
    if not is_authenticated():
        return redirect(url_for("login"))
    
    return render_template_string(SETTINGS_HTML)


# ──────────────────────────────────────────────────────────────────────────────
# API Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/state", methods=["GET"])
def api_get_state():
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(read_state())


@app.route("/api/state", methods=["POST"])
def api_update_state():
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    data = request.get_json() or {}
    
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
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json() or {}
    duration = data.get("duration", 60)
    limit_seconds = data.get("limit_seconds", 0)
    limit_action = data.get("limit_action", "stop")
    set_mode = data.get("set_mode", True)
    
    state = read_state()
    if set_mode:
        state["mode"] = "timer"
    state["timer_seconds"] = duration
    state["timer_remaining"] = duration
    state["timer_running"] = True
    state["timer_limit_seconds"] = limit_seconds
    state["timer_limit_action"] = limit_action
    state["timer_id"] = time.time()
    write_state(state)
    
    return jsonify(state)


@app.route("/api/timer/pause", methods=["POST"])
def api_timer_pause():
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    state["timer_running"] = False
    write_state(state)
    return jsonify(state)


@app.route("/api/timer/resume", methods=["POST"])
def api_timer_resume():
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    state["timer_running"] = True
    write_state(state)
    return jsonify(state)


@app.route("/api/timer/stop", methods=["POST"])
def api_timer_stop():
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    state["timer_running"] = False
    state["timer_remaining"] = 0
    state["timer_id"] = 0
    write_state(state)
    return jsonify(state)


@app.route("/api/timer/send", methods=["POST"])
def api_timer_send():
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    state["mode"] = "timer"
    write_state(state)
    return jsonify(state)


@app.route("/api/stopwatch/start", methods=["POST"])
def api_stopwatch_start():
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json() or {}
    limit_seconds = data.get("limit_seconds", 0)
    limit_action = data.get("limit_action", "stop")
    set_mode = data.get("set_mode", True)
    
    state = read_state()
    if set_mode:
        state["mode"] = "stopwatch"
    state["stopwatch_running"] = True
    state["stopwatch_seconds"] = 0
    state["stopwatch_limit_seconds"] = limit_seconds
    state["stopwatch_limit_action"] = limit_action
    state["stopwatch_id"] = time.time()
    write_state(state)
    return jsonify(state)


@app.route("/api/stopwatch/pause", methods=["POST"])
def api_stopwatch_pause():
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    state["stopwatch_running"] = False
    write_state(state)
    return jsonify(state)


@app.route("/api/stopwatch/resume", methods=["POST"])
def api_stopwatch_resume():
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    state["stopwatch_running"] = True
    write_state(state)
    return jsonify(state)


@app.route("/api/stopwatch/stop", methods=["POST"])
def api_stopwatch_stop():
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    state["stopwatch_running"] = False
    state["stopwatch_seconds"] = 0
    state["stopwatch_id"] = 0
    write_state(state)
    return jsonify(state)


@app.route("/api/stopwatch/reset", methods=["POST"])
def api_stopwatch_reset():
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    state["mode"] = "stopwatch"
    state["stopwatch_running"] = False
    state["stopwatch_seconds"] = 0
    state["stopwatch_id"] = 0
    write_state(state)
    return jsonify(state)


@app.route("/api/stopwatch/send", methods=["POST"])
def api_stopwatch_send():
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    state["mode"] = "stopwatch"
    write_state(state)
    return jsonify(state)


@app.route("/api/clock", methods=["GET"])
def api_clock():
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    state = read_state()
    state["mode"] = "clock"
    write_state(state)
    return jsonify({"timestamp": time.time()})


# Admin/Settings API Routes

@app.route("/api/password/change", methods=["POST"])
def api_password_change():
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json() or {}
    old_pw = data.get("old_password", "")
    new_pw = data.get("new_password", "")
    
    auth = read_auth()
    if not auth["password_hash"] or not check_password_hash(auth["password_hash"], old_pw):
        return jsonify({"error": "Incorrect old password."}), 400
        
    if len(new_pw) < 4:
        return jsonify({"error": "New password must be at least 4 characters."}), 400
        
    auth["password_hash"] = generate_password_hash(new_pw)
    write_auth(auth)
    return jsonify({"status": "success"})


@app.route("/api/admin/config", methods=["GET", "POST"])
def api_admin_config():
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    if request.method == "GET":
        return jsonify(read_config())
    
    data = request.get_json() or {}
    config = read_config()
    if "login_enabled" in data:
        config["login_enabled"] = data["login_enabled"]
    if "clock_format" in data:
        config["clock_format"] = data["clock_format"]
    write_config(config)
    return jsonify(config)


@app.route("/api/admin/reset", methods=["POST"])
def api_admin_reset():
    if not is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    
    write_state({
        "mode": "clock",
        "timer_seconds": 0,
        "timer_remaining": 0,
        "timer_running": False,
        "timer_limit_seconds": 0,
        "timer_limit_action": "stop",
        "timer_id": 0,
        "stopwatch_seconds": 0,
        "stopwatch_running": False,
        "stopwatch_limit_seconds": 0,
        "stopwatch_limit_action": "stop",
        "stopwatch_id": 0,
    })
    
    write_auth({"password_hash": None})
    write_config({"login_enabled": True, "clock_format": "12"})
    
    session.pop("authenticated", None)
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
:root{--bg:#0d0f14;--surface:#161920;--border:#252830;--accent:#d14242;--text:#e8eaf0;--muted:#6b7280;--danger:#ff8888}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif;padding:24px}
.panel{width:min(460px,100%);background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:28px;box-shadow:0 20px 60px rgba(0,0,0,.35)}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:1.45rem;margin-bottom:4px}
.logo span{color:var(--accent)}
h1{font-family:'Syne',sans-serif;font-size:1rem;margin:0 0 20px;color:var(--muted);font-weight:600}
label{display:block;color:var(--muted);font-size:.82rem;margin:14px 0 6px}
input{width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:7px;padding:10px 12px;font:inherit;outline:none}
input:focus{border-color:var(--accent)}
button{display:inline-flex;justify-content:center;align-items:center;margin-top:18px;width:100%;border:0;border-radius:7px;padding:10px 12px;background:var(--accent);color:#fff;font-weight:700;font:inherit;cursor:pointer}
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
<label>Master Password</label><input name="password" type="password" required minlength="4" autofocus>
<button type="submit">Set Password</button>
</form>
<p class="hint">This password will protect access to your timer controls and settings.</p>
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
<title>Pi Timer - Setup Security</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#0d0f14;--surface:#161920;--border:#252830;--accent:#d14242;--text:#e8eaf0;--muted:#6b7280;--danger:#ff8888}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif;padding:24px}
.panel{width:min(460px,100%);background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:28px;box-shadow:0 20px 60px rgba(0,0,0,.35)}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:1.45rem;margin-bottom:4px}
.logo span{color:var(--accent)}
h1{font-family:'Syne',sans-serif;font-size:1rem;margin:0 0 20px;color:var(--muted);font-weight:600}
label{display:block;color:var(--muted);font-size:.82rem;margin:14px 0 6px}
input[type="checkbox"]{width:18px;height:18px;margin-right:10px}
.checkbox-group{display:flex;align-items:center;margin:16px 0}
button{display:inline-flex;justify-content:center;align-items:center;margin-top:18px;width:100%;border:0;border-radius:7px;padding:10px 12px;background:var(--accent);color:#fff;font-weight:700;font:inherit;cursor:pointer}
.hint{color:var(--muted);font-size:.82rem;line-height:1.45;margin-top:14px}
</style>
</head>
<body>
<div class="panel">
<div class="logo">Pi <span>Timer</span></div>
<h1>Enable Password Protection</h1>
<form method="post">
<div class="checkbox-group">
<input type="checkbox" id="enable_login" name="enable_login" value="true" checked>
<label for="enable_login">Require password for access</label>
</div>
<p class="hint">Enable to protect the timer with the password you just set. Disable to allow public access.</p>
<button type="submit">Complete Setup</button>
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
<title>Pi Timer - Access</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#0d0f14;--surface:#161920;--border:#252830;--accent:#d14242;--text:#e8eaf0;--muted:#6b7280;--danger:#ff8888}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif;padding:24px}
.panel{width:min(460px,100%);background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:28px;box-shadow:0 20px 60px rgba(0,0,0,.35)}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:1.45rem;margin-bottom:4px}
.logo span{color:var(--accent)}
h1{font-family:'Syne',sans-serif;font-size:1rem;margin:0 0 20px;color:var(--muted);font-weight:600}
label{display:block;color:var(--muted);font-size:.82rem;margin:14px 0 6px}
input{width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:7px;padding:10px 12px;font:inherit;outline:none}
input:focus{border-color:var(--accent)}
button{display:inline-flex;justify-content:center;align-items:center;margin-top:18px;width:100%;border:0;border-radius:7px;padding:10px 12px;background:var(--accent);color:#fff;font-weight:700;font:inherit;cursor:pointer}
.msg{margin:0 0 12px;color:var(--danger);font-size:.88rem}
</style>
</head>
<body>
<div class="panel">
<div class="logo">Pi <span>Timer</span></div>
<h1>Access Timer</h1>
{% if error %}<p class="msg">{{ error }}</p>{% endif %}
<form method="post">
<label>Password</label><input name="password" type="password" required autofocus>
<button type="submit">Unlock</button>
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
.icon-btn{display:inline-flex;align-items:center;justify-content:center;color:var(--muted);padding:8px;border-radius:10px;transition:all 0.2s;background:transparent;border:1px solid transparent; cursor:pointer;}
.icon-btn:hover{color:var(--text);background:#17171b;border-color:var(--border);}
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
.button-group button:disabled{background:#5a1f1f;color:#9ca3af;cursor:not-allowed;border-color:transparent;}
.info-text{color:var(--muted);font-size:.82rem;line-height:1.6;margin-top:10px}
.send-btn{display:block;width:100%;margin-top:16px;padding:12px 16px;background:var(--accent);color:#fff;border:0;border-radius:10px;font-weight:700;cursor:pointer}
</style>
</head>
<body>
<header>
  <div class="logo">Pi <span>Timer</span></div>
  <div class="spacer"></div>
  {% if login_enabled %}
  <div style="display:flex; gap:8px;">
    <a href="/settings" class="icon-btn" title="Settings">
      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
    </a>
    <form method="post" action="/logout" style="margin:0;">
      <button type="submit" class="icon-btn" title="Logout">
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>
      </button>
    </form>
  </div>
  {% endif %}
</header>
<main>
<h1>Control panel</h1>
<div class="tabs"><button class="tab-btn active" onclick="switchTab('clock')">Clock</button><button class="tab-btn" onclick="switchTab('timer')">Timer</button><button class="tab-btn" onclick="switchTab('stopwatch')">Stopwatch</button></div>
<div id="clock" class="tab-content active"><div class="card"><div class="time-display" id="clockDisplay">00:00</div><div class="control-row"><label for="clockFormat">Clock Format</label><select id="clockFormat" onchange="changeClockFormat(this.value)"><option value="12">12 Hour</option><option value="24">24 Hour</option></select></div><p class="info-text">Current time displayed on the fullscreen display</p><button class="send-btn" onclick="sendToDisplay('clock')">Send Clock to Display</button></div></div>
<div id="timer" class="tab-content"><div class="card"><div class="time-display" id="timerDisplay">00:00</div><div class="control-row"><label for="timerHours">Duration</label><div class="time-inputs"><input type="number" id="timerHours" placeholder="HH" min="0" max="99"><input type="number" id="timerMinutes" placeholder="MM" min="0" max="59"><input type="number" id="timerSeconds" placeholder="SS" min="0" max="59"></div></div><div class="button-group"><button type="button" id="btnTimerStart" onclick="startTimer()">Start</button><button type="button" id="btnTimerPause" class="secondary" onclick="pauseTimer()">Pause</button><button type="button" class="secondary" onclick="stopTimer()">Reset</button></div><button class="send-btn" onclick="sendToDisplay('timer')">Send Timer to Display</button></div></div>
<div id="stopwatch" class="tab-content"><div class="card"><div class="time-display" id="stopwatchDisplay">00:00</div><div class="control-row"><label for="stopwatchHours">Stopwatch limit (OPTIONAL)</label><div class="time-inputs"><input type="number" id="stopwatchHours" placeholder="HH" min="0" max="99"><input type="number" id="stopwatchMinutes" placeholder="MM" min="0" max="59"><input type="number" id="stopwatchSeconds" placeholder="SS" min="0" max="59"></div></div><div class="control-row"><label for="stopwatchLimitAction">Limit Action</label><select id="stopwatchLimitAction"><option value="stop">Stop at limit</option><option value="blink">Blink at limit</option></select><p class="info-text">Blink means the display background will flash red when the limit is reached.</p></div><div class="button-group"><button type="button" id="btnStopwatchStart" onclick="startStopwatch()">Start</button><button type="button" id="btnStopwatchPause" class="secondary" onclick="pauseStopwatch()">Pause</button><button type="button" class="secondary" onclick="stopStopwatch()">Reset</button></div><button class="send-btn" onclick="sendToDisplay('stopwatch')">Send Stopwatch to Display</button></div></div>
</main>
<script>
const STATE_UPDATE_INTERVAL = 100;
function switchTab(tab){document.querySelectorAll('.tab-content').forEach(el=>el.classList.remove('active'));document.querySelectorAll('.tab-btn').forEach(el=>el.classList.remove('active'));document.getElementById(tab).classList.add('active');document.querySelector(`[onclick="switchTab('${tab}')"]`).classList.add('active');updateDisplay();}
function formatMinutesSeconds(seconds){const m=Math.floor(seconds/60);const s=Math.floor(seconds%60);return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;}
function formatHourMinute(date, format){const h=date.getHours();const m=String(date.getMinutes()).padStart(2,'0');const colon = Math.floor(Date.now()/500) % 2 === 0 ? ':' : ' ';if(format==='12'){const hh=h%12||12;return `${hh}${colon}${m}`;}else{return `${String(h).padStart(2,'0')}${colon}${m}`;}}
function updateDisplay(){
    fetch('/api/state').then(r=>r.json()).then(state=>{
        const now=new Date();
        const format=document.getElementById('clockFormat').value;
        document.getElementById('clockDisplay').textContent=formatHourMinute(now,format);
        
        // Timer UI
        document.getElementById('timerDisplay').textContent=formatMinutesSeconds(state.timer_remaining);
        const btnTStart = document.getElementById('btnTimerStart');
        const btnTPause = document.getElementById('btnTimerPause');
        if(state.timer_running){
            btnTStart.disabled = true;
            btnTPause.textContent = "Pause";
            btnTPause.onclick = pauseTimer;
        } else {
            btnTStart.disabled = false;
            // Use timer_id to determine if it is actively paused vs stopped/cleared
            if(state.timer_id !== 0){
                btnTPause.textContent = "Resume";
                btnTPause.onclick = resumeTimer;
            } else {
                btnTPause.textContent = "Pause";
                btnTPause.onclick = pauseTimer;
            }
        }
        
        // Stopwatch UI
        document.getElementById('stopwatchDisplay').textContent=formatMinutesSeconds(state.stopwatch_seconds);
        const btnSStart = document.getElementById('btnStopwatchStart');
        const btnSPause = document.getElementById('btnStopwatchPause');
        if(state.stopwatch_running){
            btnSStart.disabled = true;
            btnSPause.textContent = "Pause";
            btnSPause.onclick = pauseStopwatch;
        } else {
            btnSStart.disabled = false;
            // Use stopwatch_id to determine if it is actively paused vs stopped/cleared
            if(state.stopwatch_id !== 0){
                btnSPause.textContent = "Resume";
                btnSPause.onclick = resumeStopwatch;
            } else {
                btnSPause.textContent = "Pause";
                btnSPause.onclick = pauseStopwatch;
            }
        }
    });
} 
function changeClockFormat(format){updateDisplay();}
function loadConfig(){fetch('/api/admin/config').then(r=>r.json()).then(config=>{document.getElementById('clockFormat').value=config.clock_format||'12';});}
function sendToDisplay(mode){if(mode==='clock'){const format=document.getElementById('clockFormat').value;fetch('/api/admin/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({clock_format:format})}).then(()=>fetch('/api/clock')).then(()=>updateDisplay());}else if(mode==='timer'){fetch('/api/timer/send',{method:'POST'}).then(()=>updateDisplay());}else if(mode==='stopwatch'){fetch('/api/stopwatch/send',{method:'POST'}).then(()=>updateDisplay());}}
function startTimer(){const h=parseInt(document.getElementById('timerHours').value)||0;const m=parseInt(document.getElementById('timerMinutes').value)||0;const s=parseInt(document.getElementById('timerSeconds').value)||0;const duration=h*3600+m*60+s;if(duration<=0){alert('Set a timer duration before starting.');return;}fetch('/api/timer/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({duration:duration,limit_seconds:0,limit_action:'stop',set_mode:false})}).then(()=>updateDisplay());}
function pauseTimer(){fetch('/api/timer/pause',{method:'POST'}).then(()=>updateDisplay());}
function resumeTimer(){fetch('/api/timer/resume',{method:'POST'}).then(()=>updateDisplay());}
function stopTimer(){fetch('/api/timer/stop',{method:'POST'}).then(()=>updateDisplay());}
function getStopwatchLimit(){const h=parseInt(document.getElementById('stopwatchHours').value)||0;const m=parseInt(document.getElementById('stopwatchMinutes').value)||0;const s=parseInt(document.getElementById('stopwatchSeconds').value)||0;return h*3600+m*60+s;}
function startStopwatch(){const limit=getStopwatchLimit();const action=document.getElementById('stopwatchLimitAction').value;fetch('/api/stopwatch/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({limit_seconds:limit,limit_action:action,set_mode:false})}).then(()=>updateDisplay());}
function pauseStopwatch(){fetch('/api/stopwatch/pause',{method:'POST'}).then(()=>updateDisplay());}
function resumeStopwatch(){fetch('/api/stopwatch/resume',{method:'POST'}).then(()=>updateDisplay());}
function stopStopwatch(){fetch('/api/stopwatch/stop',{method:'POST'}).then(()=>updateDisplay());}
setInterval(updateDisplay,STATE_UPDATE_INTERVAL);loadConfig();updateDisplay();
</script>
</body>
</html>
"""

SETTINGS_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Pi Timer - Settings</title>
    <link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
    <style>
        :root{--bg:#0d0f14;--surface:#161920;--border:#252830;--accent:#d14242;--text:#e8eaf0;--muted:#6b7280;--danger:#ff8888}
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif;min-height:100vh;padding:24px}
        header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}
        .logo{font-family:'Syne',sans-serif;font-weight:800;font-size:1.45rem}
        .logo span{color:var(--accent)}
        a,button{font:inherit;cursor:pointer;text-decoration:none;border:1px solid transparent;border-radius:10px;padding:10px 14px}
        a{color:var(--accent);background:transparent}
        button{background:var(--accent);color:#fff;border-color:var(--accent)}
        .secondary{background:transparent;color:var(--text);border:1px solid var(--border)}
        .secondary:hover{background:#17171b}
        .container{max-width:860px;margin:0 auto;display:grid;gap:20px}
        .control-group{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:24px;box-shadow:0 20px 50px rgba(0,0,0,.25)}
        .control-group h2{margin:0 0 18px;font-family:'Syne',sans-serif;font-size:1rem}
        .control-row{display:grid;gap:14px;margin-bottom:16px}
        .control-row:last-child{margin-bottom:0}
        label{display:block;color:var(--text);font-size:.95rem}
        input{width:100%;border-radius:10px;border:1px solid var(--border);background:var(--bg);color:var(--text);padding:12px 14px;font:inherit;outline:none}
        input:focus{border-color:var(--accent)}
        input[type="checkbox"]{width:18px;height:18px;accent-color:var(--accent)}
        .checkbox-group{display:flex;align-items:center;gap:10px}
        .checkbox-group label{color:var(--text);cursor:pointer}
        .info{color:var(--muted);font-size:.92rem;line-height:1.6;margin-top:10px}
        .danger-zone{background:#181212;border:1px solid rgba(255,0,0,.2);border-radius:16px;padding:22px}
        .danger-zone p{margin:0 0 18px;color:var(--muted);font-size:.92rem;line-height:1.7}
        .danger-zone button{background:#b91c1c;color:#fff;border-color:#b91c1c}
        .danger-zone button:hover{background:#a01818}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Settings</h1>
            <a href="/" class="secondary">Back to Timer</a>
        </header>
    
        <div class="control-group">
            <h2>Access Control</h2>
            <div class="control-row">
                <div class="checkbox-group">
                    <input type="checkbox" id="loginEnabled">
                    <label for="loginEnabled">Require password for access</label>
                </div>
                <p class="info">When disabled, anyone on your network can access and control the timer without a password.</p>
            </div>
            <button onclick="saveLoginSetting()">Save Settings</button>
        </div>

        <div class="control-group">
            <h2>Change Password</h2>
            <div class="control-row">
                <label>Old Password</label>
                <input type="password" id="oldPassword">
            </div>
            <div class="control-row">
                <label>New Password</label>
                <input type="password" id="newPassword">
            </div>
            <div class="control-row">
                <label>Confirm New Password</label>
                <input type="password" id="confirmPassword">
            </div>
            <button style="margin-top: 10px;" onclick="changePassword()">Update Password</button>
        </div>
        
        <div class="control-group danger-zone">
            <h2>Factory Reset</h2>
            <p>
                This will reset all timers to factory state and clear the master password. You will need to setup a new password on the next visit.
            </p>
            <button onclick="resetApp()">Factory Reset Application</button>
        </div>
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
                alert('Access settings saved.');
                loadLoginSetting();
            });
        }
        
        function changePassword() {
            const oldPw = document.getElementById('oldPassword').value;
            const newPw = document.getElementById('newPassword').value;
            const confirmPw = document.getElementById('confirmPassword').value;

            if (!oldPw || !newPw || !confirmPw) {
                alert('Please fill in all password fields.');
                return;
            }
            if (newPw !== confirmPw) {
                alert('The new passwords do not match.');
                return;
            }

            fetch('/api/password/change', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ old_password: oldPw, new_password: newPw })
            }).then(r => r.json()).then(data => {
                if (data.error) {
                    alert(data.error);
                } else {
                    alert('Password successfully updated!');
                    document.getElementById('oldPassword').value = '';
                    document.getElementById('newPassword').value = '';
                    document.getElementById('confirmPassword').value = '';
                }
            });
        }
        
        function resetApp() {
            if (confirm('Are you absolutely sure? This will reset the app and clear your password.')) {
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