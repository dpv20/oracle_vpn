"""
VPN Switcher — entry point.
Ensures only one instance runs and starts the application.
"""
import os
import sys

# Running from source: add src/ to path.
# Running frozen (PyInstaller): modules are at the root of sys._MEIPASS.
sys.path.insert(0, os.path.dirname(__file__))


def _set_dpi_aware():
    """Tell Windows not to scale this app — lets tkinter control its own size."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _set_app_user_model_id():
    """Set AppUserModelID so Windows taskbar shows our icon instead of python.exe."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Oracle.VPNSwitcher.1")
    except Exception:
        pass


SHOW_FLAG_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "VPNSwitcher",
    "show.flag",
)


def _single_instance_guard():
    """Named mutex + flag-file signaling. A second launch drops a flag file that
    the running instance polls for, then exits silently instead of popping a
    'already running' dialog."""
    try:
        import ctypes
        ctypes.windll.kernel32.CreateMutexW(None, False, "VPNSwitcher_SingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            try:
                os.makedirs(os.path.dirname(SHOW_FLAG_PATH), exist_ok=True)
                with open(SHOW_FLAG_PATH, "w", encoding="utf-8") as f:
                    f.write("show")
            except Exception:
                pass
            sys.exit(0)
    except Exception:
        pass


def main():
    _set_dpi_aware()
    _set_app_user_model_id()
    _single_instance_guard()

    from ui import VPNSwitcherApp
    app = VPNSwitcherApp()
    app.run()


if __name__ == "__main__":
    main()
