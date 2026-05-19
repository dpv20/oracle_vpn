"""session_manager.py — detect fresh-boot / long-sleep to force VPN cleanup.

Stores a tiny `session.json` at %LOCALAPPDATA%\\VPNSwitcher\\ with the OS boot
time and the last time the app was alive. On startup we compare:

  - If boot_time changed → the PC was rebooted → any prior VPN tunnel is dead.
  - If now - last_seen > SLEEP_THRESHOLD → the PC slept (or the app was closed
    for a long time) → assume the tunnel won't survive a resume.

In either case the UI calls disconnect_all() before showing the status, so the
user never sees a stale "connected" indicator that doesn't match reality.
"""
import json
import os
import time
from typing import Tuple

LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
SESSION_DIR = os.path.join(LOCALAPPDATA, "VPNSwitcher")
SESSION_FILE = os.path.join(SESSION_DIR, "session.json")

# Cutoff above which we treat the gap as "the PC slept or was off". The
# status poll updates last_seen every 6s, so 120s is comfortably above any
# normal foreground gap.
SLEEP_THRESHOLD = 120


def _boot_time() -> int:
    try:
        import psutil
        return int(psutil.boot_time())
    except Exception:
        return 0


def _read() -> dict:
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write(data: dict) -> None:
    try:
        os.makedirs(SESSION_DIR, exist_ok=True)
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def should_force_disconnect() -> Tuple[bool, str]:
    """Return (should_disconnect, reason). reason is a short human-readable
    string used for logging and the UI banner."""
    prev = _read()
    cur_boot = _boot_time()
    now = int(time.time())

    if not prev:
        return True, "first launch on this machine"

    prev_boot = prev.get("boot_time", 0)
    prev_seen = prev.get("last_seen", 0)

    if cur_boot and prev_boot and cur_boot != prev_boot:
        return True, "fresh boot detected"

    gap = now - prev_seen
    if gap > SLEEP_THRESHOLD:
        return True, f"woke after {gap}s of inactivity (sleep or app closed)"

    return False, ""


def touch() -> None:
    """Update last_seen + boot_time. Call once at startup and from the poll loop."""
    _write({"boot_time": _boot_time(), "last_seen": int(time.time())})
