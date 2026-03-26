"""
VPN Switcher — entry point.
Ensures only one instance runs and starts the application.
"""
import os
import sys

# Make sure the src/ folder is on the path when running from source
sys.path.insert(0, os.path.dirname(__file__))


def _single_instance_guard():
    """Use a named mutex to prevent multiple instances on Windows."""
    try:
        import ctypes
        ctypes.windll.kernel32.CreateMutexW(None, False, "VPNSwitcher_SingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("VPN Switcher", "VPN Switcher is already running.\nCheck the system tray.")
            sys.exit(0)
    except Exception:
        pass


def main():
    _single_instance_guard()

    from ui import VPNSwitcherApp
    app = VPNSwitcherApp()
    app.run()


if __name__ == "__main__":
    main()
