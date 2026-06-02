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
import threading
import urllib.request
from datetime import datetime
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


def get_default_state():
    return {
        "mode": "clock",
        "timer_seconds": 0,
        "timer_remaining": 0,
        "timer_running": False,
        "timer_limit_seconds": 0,
        "timer_limit_action": "stop",
        "timer_id": 0,
        "timer_last_update": 0,
        "stopwatch_seconds": 0,
        "stopwatch_running": False,
        "stopwatch_limit_seconds": 0,
        "stopwatch_limit_action": "stop",
        "stopwatch_id": 0,
        "stopwatch_last_update": 0,
        "companion_timer": 0,        
        "companion_stopwatch": 0,    
    }


def read_state():
    state = get_default_state()
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            state.update(data)
        except Exception:
            pass
            
    # Calculate live exact time elapsed on-the-fly
    now = time.time()
    
    if state.get("timer_running"):
        elapsed = now - state.get("timer_last_update", now)
        state["timer_remaining"] = max(0, state.get("timer_remaining", 0) - elapsed)
        state["timer_last_update"] = now
        
        if state.get("timer_limit_seconds", 0) > 0 and state["timer_remaining"] <= state["timer_limit_seconds"]:
            if state.get("timer_limit_action") == "stop":
                state["timer_running"] = False
                state["timer_remaining"] = state["timer_limit_seconds"]
                
        if state["timer_remaining"] <= 0:
            state["timer_running"] = False
            state["timer_remaining"] = 0
            
    if state.get("stopwatch_running"):
        elapsed = now - state.get("stopwatch_last_update", now)
        state["stopwatch_seconds"] = state.get("stopwatch_seconds", 0) + elapsed
        state["stopwatch_last_update"] = now
        
        if state.get("stopwatch_limit_seconds", 0) > 0 and state["stopwatch_seconds"] >= state["stopwatch_limit_seconds"]:
            if state.get("stopwatch_limit_action") == "stop":
                state["stopwatch_running"] = False
                state["stopwatch_seconds"] = state["stopwatch_limit_seconds"]

    # --- COMPANION SETUP VARIABLES ---
    state["comp_t_h"] = f"{(state.get('companion_timer', 0) // 3600):02d}"
    state["comp_t_m"] = f"{((state.get('companion_timer', 0) % 3600) // 60):02d}"
    state["comp_t_s"] = f"{(state.get('companion_timer', 0) % 60):02d}"

    state["comp_s_h"] = f"{(state.get('companion_stopwatch', 0) // 3600):02d}"
    state["comp_s_m"] = f"{((state.get('companion_stopwatch', 0) % 3600) // 60):02d}"
    state["comp_s_s"] = f"{(state.get('companion_stopwatch', 0) % 60):02d}"

    state["comp_t_play"] = "PAUSE" if state.get("timer_running") else ("RESUME" if state.get("timer_id") != 0 else "PAUSE")
    state["comp_s_play"] = "PAUSE" if state.get("stopwatch_running") else ("RESUME" if state.get("stopwatch_id") != 0 else "PAUSE")

    fmt = read_config().get('clock_format', '12')
    state["comp_clk_fmt"] = f"MODE:\\n{fmt}H"
    state["comp_sw_limit"] = f"LIMIT:\\n{state.get('stopwatch_limit_action', 'stop').upper()}"

    # --- COMPANION LIVE PREVIEW & FEEDBACK VARIABLES ---
    mode = state.get("mode", "clock")
    state["comp_active_mode"] = mode
    
    if mode == "clock":
        dt = datetime.now()
        h = dt.hour
        if fmt == "12":
            h = h % 12 or 12
        state["comp_live_1"] = f"{h:02d}"
        state["comp_live_2"] = f"{dt.minute:02d}"
        state["comp_live_blink"] = "normal"
        
    elif mode == "timer":
        rem = int(state.get("timer_remaining", 0))
        state["comp_live_1"] = f"{(rem // 60):02d}"
        state["comp_live_2"] = f"{(rem % 60):02d}"
        l_sec = state.get("timer_limit_seconds", 0)
        l_act = state.get("timer_limit_action", "stop")
        if l_act == "blink" and l_sec > 0 and rem <= l_sec and state.get("timer_id") != 0 and not state.get("timer_running"):
            state["comp_live_blink"] = "blink"
        else:
            state["comp_live_blink"] = "normal"
            
    elif mode == "stopwatch":
        sec = int(state.get("stopwatch_seconds", 0))
        state["comp_live_1"] = f"{(sec // 60):02d}"
        state["comp_live_2"] = f"{(sec % 60):02d}"
        l_sec = state.get("stopwatch_limit_seconds", 0)
        l_act = state.get("stopwatch_limit_action", "stop")
        if l_act == "blink" and l_sec > 0 and sec >= l_sec:
            state["comp_live_blink"] = "blink"
        else:
            state["comp_live_blink"] = "normal"

    return state


def write_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def read_auth():
    if AUTH_FILE.exists():
        try:
            data = json.loads(AUTH_FILE.read_text())
            if "password_hash" in data: return data
        except Exception:
            pass
    return {"password_hash": None}


def write_auth(data):
    AUTH_FILE.write_text(json.dumps(data, indent=2))
    try: os.chmod(AUTH_FILE, 0o600)
    except Exception: pass


def read_config():
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            if "login_enabled" in data: return data
        except Exception:
            pass
    return {"login_enabled": True, "clock_format": "12", "companion_ip": ""}


def write_config(data):
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def is_login_enabled():
    return read_config().get("login_enabled", True)


def is_authenticated():
    if not is_login_enabled(): return True
    return session.get("authenticated") is True

# ──────────────────────────────────────────────────────────────────────────────
# Companion Sync Background Thread
# ──────────────────────────────────────────────────────────────────────────────

def companion_sync_loop():
    last_pushed = {}
    while True:
        time.sleep(0.2)
        config = read_config()
        comp_target = config.get("companion_ip", "").strip()
        if not comp_target:
            continue
            
        if not comp_target.startswith("http"):
            comp_target = "http://" + comp_target
            
        state = read_state()
        updates = {
            "comp_t_h": state["comp_t_h"],
            "comp_t_m": state["comp_t_m"],
            "comp_t_s": state["comp_t_s"],
            "comp_s_h": state["comp_s_h"],
            "comp_s_m": state["comp_s_m"],
            "comp_s_s": state["comp_s_s"],
            "comp_t_play": state["comp_t_play"],
            "comp_s_play": state["comp_s_play"],
            "comp_clk_fmt": state["comp_clk_fmt"],
            "comp_sw_limit": state["comp_sw_limit"],
            "comp_live_1": state["comp_live_1"],
            "comp_live_2": state["comp_live_2"],
            "comp_live_blink": state["comp_live_blink"],
            "comp_active_mode": state["comp_active_mode"]
        }
        
        for key, val in updates.items():
            if last_pushed.get(key) == val:
                continue
                
            url = f"{comp_target}/api/custom-variable/{key}/value"
            data = json.dumps(str(val)).encode('utf-8') 
            req = urllib.request.Request(url, method="POST", data=data)
            req.add_header("Content-Type", "application/json")
            try:
                urllib.request.urlopen(req, timeout=0.2)
                last_pushed[key] = val
            except Exception:
                pass

threading.Thread(target=companion_sync_loop, daemon=True).start()

# ──────────────────────────────────────────────────────────────────────────────
# Main Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    auth = read_auth()
    if auth["password_hash"] is None: return redirect(url_for("setup"))
    if not is_authenticated(): return redirect(url_for("login"))
    return render_template_string(DASHBOARD_HTML, login_enabled=is_login_enabled())

@app.route("/settings")
def settings():
    auth = read_auth()
    if auth["password_hash"] is None: return redirect(url_for("setup"))
    if not is_authenticated(): return redirect(url_for("login"))
    return render_template_string(SETTINGS_HTML)

# Auth Routes
@app.route("/setup", methods=["GET", "POST"])
def setup():
    auth = read_auth()
    if auth["password_hash"] is not None: return redirect(url_for("index"))
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
    if auth["password_hash"] is None: return redirect(url_for("setup"))
    if not session.get("authenticated"): return redirect(url_for("setup"))
    if request.method == "POST":
        config = read_config()
        config["login_enabled"] = request.form.get("enable_login") == "true"
        write_config(config)
        return redirect(url_for("index"))
    return render_template_string(SETUP_LOGIN_HTML)

@app.route("/login", methods=["GET", "POST"])
def login():
    if not is_login_enabled(): return redirect(url_for("index"))
    if session.get("authenticated"): return redirect(url_for("index"))
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
# API Routes (Web UI)
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/state", methods=["GET"])
def api_get_state():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    return jsonify(read_state())

@app.route("/api/state", methods=["POST"])
def api_update_state():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    data = request.get_json() or {}
    for key in ["mode", "timer_seconds", "timer_remaining", "timer_running",
                "timer_limit_seconds", "timer_limit_action",
                "stopwatch_seconds", "stopwatch_running",
                "stopwatch_limit_seconds", "stopwatch_limit_action"]:
        if key in data: state[key] = data[key]
    state["timer_last_update"] = time.time()
    state["stopwatch_last_update"] = time.time()
    write_state(state)
    return jsonify(state)

@app.route("/api/timer/start", methods=["POST"])
def api_timer_start():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    state = read_state()
    # Only set mode if explicitly requested by Web UI
    if data.get("set_mode", False): state["mode"] = "timer" 
    state["timer_seconds"] = data.get("duration", 60)
    state["timer_remaining"] = data.get("duration", 60)
    state["timer_running"] = True
    state["timer_limit_seconds"] = data.get("limit_seconds", 0)
    state["timer_limit_action"] = data.get("limit_action", "stop")
    state["timer_id"] = time.time()
    state["timer_last_update"] = state["timer_id"]
    write_state(state)
    return jsonify(state)

@app.route("/api/timer/pause", methods=["POST"])
def api_timer_pause():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    state["timer_running"] = False
    write_state(state)
    return jsonify(state)

@app.route("/api/timer/resume", methods=["POST"])
def api_timer_resume():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    state["timer_running"] = True
    state["timer_last_update"] = time.time()
    write_state(state)
    return jsonify(state)

@app.route("/api/timer/stop", methods=["POST"])
def api_timer_stop():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    state["timer_running"] = False
    state["timer_remaining"] = 0
    state["timer_id"] = 0
    write_state(state)
    return jsonify(state)

@app.route("/api/timer/send", methods=["POST"])
def api_timer_send():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    state["mode"] = "timer"
    write_state(state)
    return jsonify(state)

@app.route("/api/stopwatch/start", methods=["POST"])
def api_stopwatch_start():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    state = read_state()
    # Only set mode if explicitly requested by Web UI
    if data.get("set_mode", False): state["mode"] = "stopwatch"
    state["stopwatch_running"] = True
    state["stopwatch_seconds"] = 0
    state["stopwatch_limit_seconds"] = data.get("limit_seconds", 0)
    state["stopwatch_limit_action"] = data.get("limit_action", "stop")
    state["stopwatch_id"] = time.time()
    state["stopwatch_last_update"] = state["stopwatch_id"]
    write_state(state)
    return jsonify(state)

@app.route("/api/stopwatch/pause", methods=["POST"])
def api_stopwatch_pause():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    state["stopwatch_running"] = False
    write_state(state)
    return jsonify(state)

@app.route("/api/stopwatch/resume", methods=["POST"])
def api_stopwatch_resume():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    state["stopwatch_running"] = True
    state["stopwatch_last_update"] = time.time()
    write_state(state)
    return jsonify(state)

@app.route("/api/stopwatch/stop", methods=["POST"])
def api_stopwatch_stop():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    state["stopwatch_running"] = False
    state["stopwatch_seconds"] = 0
    state["stopwatch_id"] = 0
    write_state(state)
    return jsonify(state)

@app.route("/api/stopwatch/reset", methods=["POST"])
def api_stopwatch_reset():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    state["stopwatch_running"] = False
    state["stopwatch_seconds"] = 0
    state["stopwatch_id"] = 0
    write_state(state)
    return jsonify(state)

@app.route("/api/stopwatch/send", methods=["POST"])
def api_stopwatch_send():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    state["mode"] = "stopwatch"
    write_state(state)
    return jsonify(state)

@app.route("/api/clock", methods=["GET", "POST"])
def api_clock():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    state["mode"] = "clock"
    write_state(state)
    return jsonify({"timestamp": time.time()})

# ──────────────────────────────────────────────────────────────────────────────
# Companion API Routes (Specifically for Bitfocus Companion)
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/comp/timer/adj", methods=["POST"])
def api_comp_timer_adj():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    state = read_state()
    val = state.get("companion_timer", 0)
    if "add" in data: val += data["add"]
    if "sub" in data: val -= data["sub"]
    state["companion_timer"] = max(0, val)
    write_state(state)
    return jsonify(state)

@app.route("/api/comp/timer/start", methods=["POST"])
def api_comp_timer_start():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    dur = state.get("companion_timer", 0)
    if dur > 0:
        state["timer_seconds"] = dur
        state["timer_remaining"] = dur
        state["timer_running"] = True
        state["timer_id"] = time.time()
        state["timer_last_update"] = state["timer_id"]
        write_state(state)
    return jsonify(state)

@app.route("/api/comp/timer/toggle", methods=["POST"])
def api_comp_timer_toggle():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    if state.get("timer_running", False):
        state["timer_running"] = False
    elif state.get("timer_id", 0) != 0:
        state["timer_running"] = True
        state["timer_last_update"] = time.time()
    write_state(state)
    return jsonify(state)

@app.route("/api/comp/sw/adj", methods=["POST"])
def api_comp_sw_adj():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    state = read_state()
    val = state.get("companion_stopwatch", 0)
    if "add" in data: val += data["add"]
    if "sub" in data: val -= data["sub"]
    state["companion_stopwatch"] = max(0, val)
    write_state(state)
    return jsonify(state)

@app.route("/api/comp/sw/start", methods=["POST"])
def api_comp_sw_start():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    state["stopwatch_running"] = True
    state["stopwatch_seconds"] = 0
    state["stopwatch_limit_seconds"] = state.get("companion_stopwatch", 0)
    state["stopwatch_id"] = time.time()
    state["stopwatch_last_update"] = state["stopwatch_id"]
    write_state(state)
    return jsonify(state)

@app.route("/api/comp/sw/toggle", methods=["POST"])
def api_comp_sw_toggle():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    if state.get("stopwatch_running", False):
        state["stopwatch_running"] = False
    elif state.get("stopwatch_id", 0) != 0:
        state["stopwatch_running"] = True
        state["stopwatch_last_update"] = time.time()
    write_state(state)
    return jsonify(state)

@app.route("/api/comp/sw/toggle_action", methods=["POST"])
def api_comp_sw_toggle_action():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    state = read_state()
    cur = state.get("stopwatch_limit_action", "stop")
    if cur == "stop": state["stopwatch_limit_action"] = "blink"
    elif cur == "blink": state["stopwatch_limit_action"] = "none"
    else: state["stopwatch_limit_action"] = "stop"
    write_state(state)
    return jsonify(state)

@app.route("/api/comp/clock/toggle_fmt", methods=["POST"])
def api_comp_clock_toggle_fmt():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    config = read_config()
    config["clock_format"] = "24" if config.get("clock_format", "12") == "12" else "12"
    write_config(config)
    return jsonify({"status": "success"})


# ──────────────────────────────────────────────────────────────────────────────
# Admin/Settings
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/password/change", methods=["POST"])
def api_password_change():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    old_pw, new_pw = data.get("old_password", ""), data.get("new_password", "")
    auth = read_auth()
    if not auth["password_hash"] or not check_password_hash(auth["password_hash"], old_pw):
        return jsonify({"error": "Incorrect old password."}), 400
    if len(new_pw) < 4: return jsonify({"error": "New password must be at least 4 characters."}), 400
    auth["password_hash"] = generate_password_hash(new_pw)
    write_auth(auth)
    return jsonify({"status": "success"})

@app.route("/api/admin/config", methods=["GET", "POST"])
def api_admin_config():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    if request.method == "GET": return jsonify(read_config())
    data = request.get_json() or {}
    config = read_config()
    if "login_enabled" in data: config["login_enabled"] = data["login_enabled"]
    if "clock_format" in data: config["clock_format"] = data["clock_format"]
    if "companion_ip" in data: config["companion_ip"] = data["companion_ip"]
    write_config(config)
    return jsonify(config)

@app.route("/api/admin/reset", methods=["POST"])
def api_admin_reset():
    if not is_authenticated(): return jsonify({"error": "Unauthorized"}), 401
    write_state(get_default_state())
    write_auth({"password_hash": None})
    write_config({"login_enabled": True, "clock_format": "12", "companion_ip": ""})
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
h1{font-family:'Syne',sans-serif;font-size:1.1rem;margin:0 0 18px; display: flex; align-items: center;}
.badge { font-size: 0.7rem; padding: 4px 8px; border-radius: 6px; background: var(--border); color: var(--text); margin-left: 12px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700;}
.badge.mode-clock { background: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); }
.badge.mode-timer { background: rgba(56, 189, 248, 0.2); color: #7dd3fc; border: 1px solid rgba(56, 189, 248, 0.3); }
.badge.mode-stopwatch { background: rgba(168, 85, 247, 0.2); color: #d8b4fe; border: 1px solid rgba(168, 85, 247, 0.3); }
.tabs{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:24px}
.tab-btn{border:1px solid var(--border);border-radius:10px;padding:12px 16px;background:var(--surface);color:var(--muted);font:inherit;cursor:pointer}
.tab-btn.active{color:var(--text);border-color:var(--accent);background:#17171b}
.tab-content{display:none}
.tab-content.active{display:block}
.card{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:26px;box-shadow:0 20px 60px rgba(0,0,0,.25)}
.time-display{width:100%;min-height:180px;display:flex;align-items:center;justify-content:center;border-radius:18px;background:#080808;border:1px solid rgba(185,28,28,.25);color:#b91c1c;font-family:'Syne',sans-serif;font-size:clamp(4rem,10vw,8rem);font-weight:800;text-align:center;margin-bottom:24px;padding:30px 24px}

@keyframes alertBlink {
  0%, 49% { background: #b91c1c; color: #fff; border-color: #b91c1c; }
  50%, 100% { background: #080808; color: #b91c1c; border-color: rgba(185,28,28,.25); }
}
.time-display.blink-active { animation: alertBlink 1s infinite; }

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
<h1>Control panel <span id="displayModeBadge" class="badge"></span></h1>
<div class="tabs"><button class="tab-btn active" onclick="switchTab('clock')">Clock</button><button class="tab-btn" onclick="switchTab('timer')">Timer</button><button class="tab-btn" onclick="switchTab('stopwatch')">Stopwatch</button></div>
<div id="clock" class="tab-content active"><div class="card"><div class="time-display" id="clockDisplay">00:00</div><div class="control-row"><label for="clockFormat">Clock Format</label><select id="clockFormat" onchange="changeClockFormat(this.value)"><option value="12">12 Hour</option><option value="24">24 Hour</option></select></div><p class="info-text">Current time displayed on the fullscreen display</p><button class="send-btn" onclick="sendToDisplay('clock')">Send Clock to Display</button></div></div>
<div id="timer" class="tab-content"><div class="card"><div class="time-display" id="timerDisplay">00:00</div><div class="control-row"><label for="timerHours">Duration</label><div class="time-inputs"><input type="number" id="timerHours" placeholder="HH" min="0" max="99"><input type="number" id="timerMinutes" placeholder="MM" min="0" max="59"><input type="number" id="timerSeconds" placeholder="SS" min="0" max="59"></div></div><div class="button-group"><button type="button" id="btnTimerStart" onclick="startTimer()">Start</button><button type="button" id="btnTimerPause" class="secondary" onclick="pauseTimer()">Pause</button><button type="button" class="secondary" onclick="stopTimer()">Reset</button></div><button class="send-btn" onclick="sendToDisplay('timer')">Send Timer to Display</button></div></div>
<div id="stopwatch" class="tab-content"><div class="card"><div class="time-display" id="stopwatchDisplay">00:00</div><div class="control-row"><label for="stopwatchHours">Stopwatch limit (OPTIONAL)</label><div class="time-inputs"><input type="number" id="stopwatchHours" placeholder="HH" min="0" max="99"><input type="number" id="stopwatchMinutes" placeholder="MM" min="0" max="59"><input type="number" id="stopwatchSeconds" placeholder="SS" min="0" max="59"></div></div><div class="control-row"><label for="stopwatchLimitAction">Limit Action</label><select id="stopwatchLimitAction"><option value="stop">Stop at limit</option><option value="blink">Blink at limit</option></select><p class="info-text">Blink means the display background will flash red when the limit is reached.</p></div><div class="button-group"><button type="button" id="btnStopwatchStart" onclick="startStopwatch()">Start</button><button type="button" id="btnStopwatchPause" class="secondary" onclick="pauseStopwatch()">Pause</button><button type="button" class="secondary" onclick="stopStopwatch()">Reset</button></div><button class="send-btn" onclick="sendToDisplay('stopwatch')">Send Stopwatch to Display</button></div></div>
</main>
<script>
const STATE_UPDATE_INTERVAL = 200;
function switchTab(tab){document.querySelectorAll('.tab-content').forEach(el=>el.classList.remove('active'));document.querySelectorAll('.tab-btn').forEach(el=>el.classList.remove('active'));document.getElementById(tab).classList.add('active');document.querySelector(`[onclick="switchTab('${tab}')"]`).classList.add('active');updateDisplay();}
function formatMinutesSeconds(seconds){const m=Math.floor(seconds/60);const s=Math.floor(seconds%60);return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;}
function formatHourMinute(date, format){const h=date.getHours();const m=String(date.getMinutes()).padStart(2,'0');const colon = Math.floor(Date.now()/500) % 2 === 0 ? ':' : ' ';if(format==='12'){const hh=h%12||12;return `${hh}${colon}${m}`;}else{return `${String(h).padStart(2,'0')}${colon}${m}`;}}
function updateDisplay(){
    fetch('/api/state').then(r=>r.json()).then(state=>{
        
        const badge = document.getElementById('displayModeBadge');
        if(badge) {
            badge.textContent = "On Display: " + state.mode;
            badge.className = "badge mode-" + state.mode;
        }

        const now=new Date();
        const format=document.getElementById('clockFormat').value;
        document.getElementById('clockDisplay').textContent=formatHourMinute(now,format);
        
        const timerDisplay = document.getElementById('timerDisplay');
        timerDisplay.textContent = formatMinutesSeconds(state.timer_remaining);
        if (state.timer_limit_action === 'blink' && state.timer_limit_seconds > 0 && state.timer_remaining <= state.timer_limit_seconds && !state.timer_running && state.timer_id !== 0) {
            timerDisplay.classList.add('blink-active');
        } else {
            timerDisplay.classList.remove('blink-active');
        }

        const btnTStart = document.getElementById('btnTimerStart');
        const btnTPause = document.getElementById('btnTimerPause');
        if(state.timer_running){
            btnTStart.disabled = true;
            btnTPause.textContent = "Pause";
            btnTPause.onclick = pauseTimer;
        } else {
            btnTStart.disabled = false;
            if(state.timer_id !== 0){
                btnTPause.textContent = "Resume";
                btnTPause.onclick = resumeTimer;
            } else {
                btnTPause.textContent = "Pause";
                btnTPause.onclick = pauseTimer;
            }
        }
        
        const stopwatchDisplay = document.getElementById('stopwatchDisplay');
        stopwatchDisplay.textContent = formatMinutesSeconds(state.stopwatch_seconds);
        if (state.stopwatch_limit_action === 'blink' && state.stopwatch_limit_seconds > 0 && state.stopwatch_seconds >= state.stopwatch_limit_seconds) {
            stopwatchDisplay.classList.add('blink-active');
        } else {
            stopwatchDisplay.classList.remove('blink-active');
        }

        const btnSStart = document.getElementById('btnStopwatchStart');
        const btnSPause = document.getElementById('btnStopwatchPause');
        if(state.stopwatch_running){
            btnSStart.disabled = true;
            btnSPause.textContent = "Pause";
            btnSPause.onclick = pauseStopwatch;
        } else {
            btnSStart.disabled = false;
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
        input[type="text"], input[type="password"]{width:100%;border-radius:10px;border:1px solid var(--border);background:var(--bg);color:var(--text);padding:12px 14px;font:inherit;outline:none}
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
            <h2>Companion Integration</h2>
            <div class="control-row">
                <label>Companion IP & Port</label>
                <input type="text" id="companionIp" placeholder="e.g. 192.168.1.10:8000">
                <p class="info">Enter the IP and Port of your Bitfocus Companion to push variables automatically. Ensure the HTTP API is enabled in Companion.</p>
            </div>
            <button onclick="saveCompanionSetting()">Save Companion IP</button>
        </div>
    
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
        function loadSettings() {
            fetch('/api/admin/config')
                .then(r => r.json())
                .then(config => {
                    document.getElementById('loginEnabled').checked = config.login_enabled;
                    document.getElementById('companionIp').value = config.companion_ip || '';
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
                loadSettings();
            });
        }

        function saveCompanionSetting() {
            const ip = document.getElementById('companionIp').value;
            fetch('/api/admin/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ companion_ip: ip })
            }).then(r => r.json()).then(() => {
                alert('Companion IP saved.');
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
        
        loadSettings();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    from waitress import serve
    serve(app, host="0.0.0.0", port=5001, threads=16)
    #app.run(host="0.0.0.0", port=5001, debug=False)