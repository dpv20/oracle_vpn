import base64
import json
import os
import sys
import winreg

APPDATA = os.getenv("APPDATA", os.path.expanduser("~"))
CONFIG_DIR = os.path.join(APPDATA, "VPNSwitcher")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "VPNSwitcher"

DEFAULTS = {
    "cisco_cli_path": "",
    "cisco_host": "",
    "cisco_username": "",
    "cisco_password": "",
    "forti_exe_path": "",
    "forti_connect_cmd": "",
    "forti_disconnect_cmd": "",
    "forti_username": "",
    "forti_password_enc": "",
    "gp_exe_path": "",
    "gp_username": "",
    "gp_password_enc": "",
    "gp_portal_url": "ext.bice.cl",
    "start_with_windows": True,
}


def encrypt_password(plain: str) -> str:
    """Encrypt using Windows DPAPI — only this Windows user can decrypt."""
    if not plain:
        return ""
    try:
        import win32crypt
        blob = win32crypt.CryptProtectData(
            plain.encode("utf-8"), "VPNSwitcher", None, None, None, 0
        )
        return base64.b64encode(blob).decode("ascii")
    except Exception:
        return ""


def decrypt_password(enc: str) -> str:
    """Decrypt a DPAPI-encrypted password."""
    if not enc:
        return ""
    try:
        import win32crypt
        blob = base64.b64decode(enc.encode("ascii"))
        _, data = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
        return data.decode("utf-8")
    except Exception:
        return ""


class ConfigManager:
    def __init__(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)

    def load(self) -> dict:
        if not os.path.exists(CONFIG_FILE):
            self.save(DEFAULTS.copy())
            return DEFAULTS.copy()
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Fill in any missing keys from defaults
            for k, v in DEFAULTS.items():
                data.setdefault(k, v)
            # Always sync startup registry on load so it survives reinstalls
            self._apply_startup(data.get("start_with_windows", True))
            return data
        except Exception:
            return DEFAULTS.copy()

    def save(self, config: dict):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        self._apply_startup(config.get("start_with_windows", True))

    def is_configured(self) -> bool:
        """Returns True if the user has set at least the Cisco host or FortiClient path."""
        cfg = self.load()
        return bool(cfg.get("cisco_host") or cfg.get("forti_exe_path") or cfg.get("forti_connect_cmd"))

    def _get_startup_cmd(self) -> str:
        """Return the full command to launch this app from Windows startup."""
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}"'
        # sys.prefix always points to the real Python install dir,
        # even when launched via py.exe or pythonw.exe launchers.
        pythonw = os.path.join(sys.prefix, "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = os.path.join(sys.prefix, "python.exe")
        script = os.path.abspath(sys.argv[0])
        return f'"{pythonw}" "{script}"'

    def _apply_startup(self, enabled: bool):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0, winreg.KEY_SET_VALUE
            )
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, self._get_startup_cmd())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass
