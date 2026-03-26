import os
import subprocess
import time
from typing import Optional, Tuple

import psutil

CISCO = "cisco"
FORTI = "forti"
NONE = "disconnected"

# Common install paths
CISCO_CLI_CANDIDATES = [
    r"C:\Program Files (x86)\Cisco\Cisco Secure Client\vpncli.exe",
    r"C:\Program Files (x86)\Cisco\Cisco AnyConnect Secure Mobility Client\vpncli.exe",
    r"C:\Program Files\Cisco\Cisco Secure Client\vpncli.exe",
    r"C:\Program Files\Cisco\Cisco AnyConnect Secure Mobility Client\vpncli.exe",
]

FORTI_EXE_CANDIDATES = [
    r"C:\Program Files\Fortinet\FortiClientVPN\FortiClientVPN.exe",
    r"C:\Program Files\Fortinet\FortiClient\FortiClient.exe",
    r"C:\Program Files (x86)\Fortinet\FortiClient\FortiClient.exe",
]

# Network interface name fragments used to detect active tunnels
CISCO_IFACE_KEYWORDS = ["anyconnect", "cisco secure", "vpn0", "csc-"]
FORTI_IFACE_KEYWORDS = ["fortinet", "forticlient", "fortissl", "forticlientsslvpn"]

NO_WINDOW = subprocess.CREATE_NO_WINDOW


def _find_exe(candidates: list, override: str = "") -> Optional[str]:
    if override and os.path.exists(override):
        return override
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _iface_connected(keywords: list) -> bool:
    try:
        stats = psutil.net_if_stats()
        for name, s in stats.items():
            if s.isup:
                low = name.lower()
                if any(kw in low for kw in keywords):
                    return True
    except Exception:
        pass
    return False


def _proc_running(name_fragments: list) -> bool:
    try:
        for p in psutil.process_iter(["name"]):
            n = (p.info.get("name") or "").lower()
            if any(f in n for f in name_fragments):
                return True
    except Exception:
        pass
    return False


def _kill_procs(name_fragments: list) -> bool:
    killed = False
    try:
        for p in psutil.process_iter(["name", "pid"]):
            n = (p.info.get("name") or "").lower()
            if any(f in n for f in name_fragments):
                try:
                    p.kill()
                    killed = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
    except Exception:
        pass
    return killed


def _run(cmd, input_text=None, timeout=20) -> Tuple[int, str, str]:
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if input_text else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=NO_WINDOW,
        )
        stdout, stderr = proc.communicate(input=input_text, timeout=timeout)
        return proc.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        proc.kill()
        return -1, "", "Timed out"
    except Exception as e:
        return -1, "", str(e)


class VPNController:
    def __init__(self, config: dict):
        self.config = config

    # ------------------------------------------------------------------ status

    def get_status(self) -> str:
        cisco = self._cisco_connected()
        forti = self._forti_connected()
        if cisco:
            return CISCO
        if forti:
            return FORTI
        return NONE

    def _cisco_connected(self) -> bool:
        cli = _find_exe(CISCO_CLI_CANDIDATES, self.config.get("cisco_cli_path", ""))
        if cli:
            rc, out, err = _run([cli, "state"], timeout=6)
            combined = (out + err).lower()
            if "state: connected" in combined:
                return True
            if "state: disconnected" in combined or "not connected" in combined:
                return False
            # If vpncli answered at all but didn't say connected, treat as disconnected
            if rc == 0 or "state:" in combined:
                return False
        return _iface_connected(CISCO_IFACE_KEYWORDS)

    def _forti_connected(self) -> bool:
        if _iface_connected(FORTI_IFACE_KEYWORDS):
            return True
        return _proc_running(["fortissl", "sslvpndaemon"])

    # ----------------------------------------------------------------- connect

    def connect_cisco(self) -> Tuple[bool, str]:
        cli = _find_exe(CISCO_CLI_CANDIDATES, self.config.get("cisco_cli_path", ""))
        if not cli:
            return False, "Cisco VPN CLI (vpncli.exe) not found. Set the path in Settings."

        host = self.config.get("cisco_host", "").strip()
        if not host:
            return False, "Cisco VPN host not set. Please configure it in Settings."

        username = self.config.get("cisco_username", "").strip()
        password = self.config.get("cisco_password", "").strip()
        stdin_data = f"{username}\n{password}\ny\n" if username and password else None

        rc, out, err = _run([cli, "connect", host], input_text=stdin_data, timeout=40)
        combined = (out + err).lower()

        if "state: connected" in combined or "connected" in combined and rc == 0:
            return True, "Connected to Cisco Secure Client."
        if rc == 0:
            return True, "Cisco connection initiated. Check Cisco VPN status."
        return False, f"Cisco connect failed: {(err or out).strip()[:200]}"

    def connect_forti(self) -> Tuple[bool, str]:
        # 1. Try custom command
        cmd = self.config.get("forti_connect_cmd", "").strip()
        if cmd:
            try:
                subprocess.Popen(cmd, shell=True, creationflags=NO_WINDOW)
                return True, "FortiClient connection command sent."
            except Exception as e:
                return False, f"FortiClient custom command failed: {e}"

        # 2. Launch the FortiClient GUI
        exe = _find_exe(FORTI_EXE_CANDIDATES, self.config.get("forti_exe_path", ""))
        if exe:
            try:
                subprocess.Popen([exe], creationflags=NO_WINDOW)
                return True, "FortiClient launched — connect from the app window."
            except Exception as e:
                return False, f"Could not launch FortiClient: {e}"

        return False, (
            "FortiClient not found. Set the path in Settings, "
            "or configure a custom connect command."
        )

    # -------------------------------------------------------------- disconnect

    def disconnect_cisco(self) -> Tuple[bool, str]:
        cli = _find_exe(CISCO_CLI_CANDIDATES, self.config.get("cisco_cli_path", ""))
        if not cli:
            return False, "Cisco VPN CLI not found."
        rc, out, err = _run([cli, "disconnect"], timeout=20)
        if rc == 0:
            return True, "Cisco Secure Client disconnected."
        return False, f"Cisco disconnect issue: {(err or out).strip()[:200]}"

    def disconnect_forti(self) -> Tuple[bool, str]:
        # 1. Custom command
        cmd = self.config.get("forti_disconnect_cmd", "").strip()
        if cmd:
            try:
                subprocess.run(cmd, shell=True, timeout=15, creationflags=NO_WINDOW)
                return True, "FortiClient disconnected via custom command."
            except Exception as e:
                return False, f"Custom disconnect failed: {e}"

        # 2. Kill tunnel process
        if _kill_procs(["fortissl", "sslvpndaemon"]):
            time.sleep(1)
            return True, "FortiClient VPN tunnel terminated."

        # 3. PowerShell named VPN connection
        ps_cmd = (
            "Get-VpnConnection | "
            "Where-Object { $_.ConnectionStatus -eq 'Connected' -and "
            "$_.Name -match 'Forti' } | "
            "Disconnect-VpnConnection -Force"
        )
        rc, out, err = _run(["powershell", "-NoProfile", "-Command", ps_cmd], timeout=12)
        if rc == 0:
            return True, "FortiClient VPN disconnected."

        return False, (
            "Could not auto-disconnect FortiClient. "
            "Please disconnect manually, or set a custom disconnect command in Settings."
        )

    def disconnect_all(self) -> Tuple[bool, str]:
        status = self.get_status()
        if status == CISCO:
            return self.disconnect_cisco()
        if status == FORTI:
            return self.disconnect_forti()
        return True, "No VPN was active."
