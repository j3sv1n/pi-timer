#!/usr/bin/env python3
"""
Pi Timer - Fullscreen Display
Runs on DISPLAY:1 (or fallback to DISPLAY:0 if :1 doesn't exist.
Shows clock, timer, or stopwatch in fullscreen. Control is web-server only.
"""

import sys
import json
import threading
import pygame
import time
import os
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "timer_state.json"
CONFIG_FILE = BASE_DIR / "timer_config.json"

BG_COLOR = (0, 0, 0)
TEXT_COLOR = (255, 0, 0)  # Red text on black
TEXT_COLOR_WHITE = (255, 255, 255)
BLINK_BG_COLOR = (255, 0, 0)  # Red background for blink
FPS = 30

# ── Helpers ───────────────────────────────────────────────────────────────────


def load_state():
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


def read_config():
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            return data
        except Exception:
            pass
    return {"login_enabled": True, "clock_format": "12"}


def format_time(seconds):
    """Convert seconds to MM:SS format."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def get_current_time(blink=True):
    """Get current time as HH:MM or 12hr with a blinking colon."""
    config = read_config()
    now = datetime.now()
    sep = ':' if blink else ' '
    if config.get("clock_format") == "12":
        h = now.hour % 12 or 12
        return f"{h:02d}{sep}{now.minute:02d}"
    else:
        return f"{now.hour:02d}{sep}{now.minute:02d}"


# ── Filesystem watcher ────────────────────────────────────────────────────────


class StateWatcher(FileSystemEventHandler):
    def __init__(self, callback):
        self.callback = callback

    def on_any_event(self, event):
        if str(event.src_path).endswith("timer_state.json"):
            self.callback()


# ── Main loop ─────────────────────────────────────────────────────────────────


def main():
    pygame.init()
    pygame.mouse.set_visible(False)

    # Try DISPLAY:1 first, fall back to DISPLAY:0
    original_display = os.environ.get("DISPLAY")
    displays_to_try = [":1", ":0"]
    
    screen = None
    for display in displays_to_try:
        try:
            os.environ["DISPLAY"] = display
            info = pygame.display.Info()
            SW, SH = info.current_w, info.current_h
            screen = pygame.display.set_mode((SW, SH), pygame.FULLSCREEN | pygame.NOFRAME)
            print(f"Display initialized on {display}: {SW}x{SH}")
            break
        except Exception as e:
            print(f"Failed to initialize display on {display}: {e}")
            continue

    if screen is None:
        print("Failed to initialize any display")
        sys.exit(1)

    pygame.display.set_caption("Pi Timer")
    clock = pygame.time.Clock()

    # State tracking
    state = load_state()
    last_update_time = time.time()
    blink_state = True
    blink_timer = 0
    clock_colon = True
    clock_blink_timer = 0
    BLINK_INTERVAL = 0.5  # seconds between blinks

    def on_state_changed():
        nonlocal state
        new_state = load_state()
        
        # If the session ID matches, preserve the display's internal elapsed time
        if state.get("timer_id") and state.get("timer_id") == new_state.get("timer_id"):
            new_state["timer_remaining"] = state.get("timer_remaining", 0)
            
        if state.get("stopwatch_id") and state.get("stopwatch_id") == new_state.get("stopwatch_id"):
            new_state["stopwatch_seconds"] = state.get("stopwatch_seconds", 0)
            
        state = new_state

    # Start filesystem watcher
    watcher = StateWatcher(on_state_changed)
    observer = Observer()
    observer.schedule(watcher, str(BASE_DIR), recursive=False)
    observer.start()

    # Main loop
    try:
        running = True
        while running:
            dt = clock.tick(FPS) / 1000.0
            current_time = time.time()

            # Handle events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                        
            # Update state based on running timers/stopwatches
            if state["timer_running"]:
                elapsed = current_time - last_update_time
                state["timer_remaining"] = max(0, state["timer_remaining"] - elapsed)

                # Check limits
                if state["timer_limit_seconds"] > 0:
                    if state["timer_remaining"] <= state["timer_limit_seconds"]:
                        if state["timer_limit_action"] == "stop":
                            state["timer_running"] = False
                        # blink action: just set flag, will render with blink

                # Stop when timer reaches 0
                if state["timer_remaining"] <= 0:
                    state["timer_running"] = False
                    state["timer_remaining"] = 0

            if state["stopwatch_running"]:
                elapsed = current_time - last_update_time
                state["stopwatch_seconds"] += elapsed

                # Check limits
                if state["stopwatch_limit_seconds"] > 0:
                    if state["stopwatch_seconds"] >= state["stopwatch_limit_seconds"]:
                        if state["stopwatch_limit_action"] == "stop":
                            state["stopwatch_running"] = False
                        # blink action: keep running, will render with blink

            last_update_time = current_time

            # Determine if we should blink
            should_blink = False
            
            if state["mode"] == "timer":
                if (state["timer_limit_seconds"] > 0 and
                    state["timer_remaining"] <= state["timer_limit_seconds"] and
                    state["timer_limit_action"] == "blink"):
                    should_blink = True

            if state["mode"] == "stopwatch":
                if (state["stopwatch_limit_seconds"] > 0 and
                    state["stopwatch_seconds"] >= state["stopwatch_limit_seconds"] and
                    state["stopwatch_limit_action"] == "blink"):
                    should_blink = True

            # Update blink state
            blink_timer += dt
            if blink_timer >= BLINK_INTERVAL:
                blink_timer = 0
                blink_state = not blink_state

            clock_blink_timer += dt
            if clock_blink_timer >= BLINK_INTERVAL:
                clock_blink_timer = 0
                clock_colon = not clock_colon

            # Render
            if should_blink and not blink_state:
                screen.fill(BLINK_BG_COLOR)
                display_color = TEXT_COLOR_WHITE
            else:
                screen.fill(BG_COLOR)
                display_color = TEXT_COLOR

            # Display based on mode
            if state["mode"] == "clock":
                time_str = get_current_time(clock_colon)
            elif state["mode"] == "timer":
                time_str = format_time(state["timer_remaining"])
            elif state["mode"] == "stopwatch":
                time_str = format_time(state["stopwatch_seconds"])
            else:
                time_str = get_current_time(clock_colon)

            # Render time text as large as possible within screen margins
            base_font_size = min(int(SW * 0.5), int(SH * 0.95))
            font_time = pygame.font.SysFont("timesnewroman", base_font_size, bold=False)
            time_surface = font_time.render(time_str, True, display_color)

            if time_surface.get_width() > SW * 0.94:
                scale = (SW * 0.94) / time_surface.get_width()
                scaled_size = max(48, int(base_font_size * scale))
                font_time = pygame.font.SysFont("timesnewroman", scaled_size, bold=False)
                time_surface = font_time.render(time_str, True, display_color)

            time_rect = time_surface.get_rect(center=(SW // 2, SH // 2))
            screen.blit(time_surface, time_rect)

            pygame.display.flip()

    finally:
        observer.stop()
        observer.join()
        pygame.quit()


if __name__ == "__main__":
    main()