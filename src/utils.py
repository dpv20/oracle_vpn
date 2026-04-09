"""
utils.py — shared helpers used across modules.
"""
import os
import sys


def resource_path(*parts) -> str:
    """Return the absolute path to a resource file.

    Works both in development (running from source) and when bundled
    by PyInstaller (sys._MEIPASS holds the temp extraction directory).
    """
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS          # PyInstaller extraction folder
    else:
        # Running from source: go up one level from src/ to project root
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)
