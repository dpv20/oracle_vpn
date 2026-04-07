import os
import subprocess
import threading
import time
from typing import Optional, Tuple

# Global cancellation flag — set to cancel any in-progress autofill
_autofill_cancel = threading.Event()

CISCO = "cisco"
FORTI = "forti"
NONE = "disconnected"

CISCO_CLI_CANDIDATES = [
    r"C:\Program Files (x86)\Cisco\Cisco Secure Client\vpncli.exe",
    r"C:\Program Files (x86)\Cisco\Cisco AnyConnect Secure Mobility Client\vpncli.exe",
    r"C:\Program Files\Cisco\Cisco Secure Client\vpncli.exe",
]

CISCO_UI_CANDIDATES = [
    r"C:\Program Files (x86)\Cisco\Cisco Secure Client\UI\csc_ui.exe",
    r"C:\Program Files (x86)\Cisco\Cisco Secure Client\vpnui.exe",
    r"C:\Program Files (x86)\Cisco\Cisco AnyConnect Secure Mobility Client\vpnui.exe",
]

FORTI_EXE_CANDIDATES = [
    r"C:\Program Files\Fortinet\FortiClient\FortiClient.exe",
    r"C:\Program Files\Fortinet\FortiClientVPN\FortiClientVPN.exe",
    r"C:\Program Files (x86)\Fortinet\FortiClient\FortiClient.exe",
]

NO_WINDOW = subprocess.CREATE_NO_WINDOW


def _find_exe(candidates: list, override: str = "") -> Optional[str]:
    if override and os.path.exists(override):
        return override
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _run(cmd, input_text=None, timeout=20) -> Tuple[int, str, str]:
    """Run a CLI command (hidden window). For GUI apps use _open_gui instead."""
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
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


def _open_gui(exe_path: str) -> bool:
    """Open a GUI application via explorer.exe (works for protected/Electron apps)."""
    try:
        subprocess.Popen(["explorer.exe", exe_path])
        return True
    except Exception:
        return False


def _find_visible_hwnd(title_fragment: str):
    """Return the hwnd of the first visible window whose title contains title_fragment."""
    import ctypes
    import ctypes.wintypes
    user32 = ctypes.windll.user32
    target = [None]

    def enum_callback(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if title_fragment.lower() in buf.value.lower():
                if user32.IsWindowVisible(hwnd):
                    target[0] = hwnd
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )
    user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
    return target[0]


def _force_foreground(hwnd) -> bool:
    """Force a window to the foreground, bypassing Windows restrictions."""
    import ctypes
    import ctypes.wintypes
    user32 = ctypes.windll.user32

    # Get the thread of the current foreground window
    fg_hwnd = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
    our_thread = user32.GetWindowThreadProcessId(hwnd, None)

    # Attach our thread input to the foreground thread — this lets us steal focus
    if fg_thread != our_thread:
        user32.AttachThreadInput(fg_thread, our_thread, True)

    user32.ShowWindow(hwnd, 9)          # SW_RESTORE
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.SetFocus(hwnd)

    if fg_thread != our_thread:
        user32.AttachThreadInput(fg_thread, our_thread, False)

    return True


def _bring_window_to_front(title_fragment: str) -> bool:
    """Find a visible window and force it to the foreground."""
    hwnd = _find_visible_hwnd(title_fragment)
    if hwnd:
        return _force_foreground(hwnd)
    return False


def _wait_and_bring_to_front(title_fragment: str, timeout: float = 12.0) -> bool:
    """Poll until a window with title_fragment appears, then force it to front."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = _find_visible_hwnd(title_fragment)
        if hwnd:
            return _force_foreground(hwnd)
        time.sleep(0.4)
    return False


FORTI_TITLE = "FortiClient - Zero Trust Fabric Agent"


def _forti_get_window(timeout: float = 1.0):
    """Find the FortiClient Electron window via pywinauto UIA backend.
    Returns the window wrapper or None."""
    try:
        from pywinauto import Desktop
        deadline = time.time() + timeout
        while time.time() < deadline:
            desktop = Desktop(backend="uia")
            wins = [w for w in desktop.windows()
                    if w.window_text() == FORTI_TITLE]
            if wins:
                return wins[0]
            time.sleep(0.5)
    except Exception:
        pass
    return None


def _find_signin_window():
    """Find the FortiClient SAML sign-in popup (Chromium window).
    Matches English and Spanish titles."""
    try:
        from pywinauto import Desktop
        desktop = Desktop(backend="win32")
        for w in desktop.windows():
            title = w.window_text().lower()
            if "sign in to your account" in title or "iniciar sesión" in title:
                return w
    except Exception:
        pass
    return None


def _focus_and_type(hwnd, text, press_enter=True):
    """Force-focus a window, clear the field, type text, optionally press Enter.
    Retries focus for up to 10 seconds. Only types if we actually have focus.
    Aborts immediately if _autofill_cancel is set."""
    from pywinauto import keyboard
    import ctypes
    user32 = ctypes.windll.user32

    if _autofill_cancel.is_set():
        return False

    # Keep trying to get focus for up to 10 seconds
    deadline = time.time() + 10
    got_focus = False
    while time.time() < deadline:
        if _autofill_cancel.is_set():
            return False
        _force_foreground(hwnd)
        time.sleep(0.5)
        if user32.GetForegroundWindow() == hwnd:
            got_focus = True
            break
        time.sleep(0.8)

    if not got_focus or _autofill_cancel.is_set():
        return False

    time.sleep(0.3)
    if user32.GetForegroundWindow() != hwnd or _autofill_cancel.is_set():
        return False

    keyboard.send_keys("^a", pause=0.05)
    time.sleep(0.15)
    keyboard.send_keys(text, with_spaces=True, pause=0.02)
    time.sleep(0.2)
    if press_enter:
        keyboard.send_keys("{ENTER}", pause=0.05)
    return True


def _get_signin_page_text() -> str:
    """Try to read all visible text from the sign-in Chromium window via UIA.
    Returns concatenated lowercase text of all accessible elements.
    Also writes to a debug log for troubleshooting."""
    import os, tempfile
    result = ""
    try:
        from pywinauto import Desktop
        desktop = Desktop(backend="uia")
        for w in desktop.windows():
            title = w.window_text().lower()
            if "sign in to your account" in title or "iniciar sesión" in title:
                texts = []
                for ctrl in w.descendants():
                    try:
                        t = ctrl.window_text().strip()
                        if t:
                            texts.append(t.lower())
                    except Exception:
                        pass
                result = " ".join(texts)
                break
    except Exception as e:
        result = f"[ERROR: {e}]"

    # Write debug log
    try:
        log_path = os.path.join(tempfile.gettempdir(), "vpnswitcher_uia_debug.txt")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(result)
    except Exception:
        pass

    return result


def _check_password_rejected(timeout: float = 8.0, title_before: str = "") -> bool:
    """Detect if the password was rejected using red pixel detection.

    Microsoft shows 'Your account or password is incorrect' in bright red.
    The MFA page has no red error text.

    Waits for the page to react (title change or timeout), then captures
    the window and counts red pixels.
    """
    # Wait for the page to react (title changes when page navigates/reloads)
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.5)
        sign_in_win = _find_signin_window()
        if not sign_in_win:
            return False  # Window gone — success
        if title_before and sign_in_win.window_text() != title_before:
            break  # Page reacted — stop waiting early

    # Let the page fully render before taking screenshot
    time.sleep(2.0)

    sign_in_win = _find_signin_window()
    if not sign_in_win:
        return False  # Window gone — success

    return _window_has_red_error(sign_in_win.handle)


def _window_has_red_error(hwnd) -> bool:
    """Capture the sign-in window and check for red error text pixels.
    Microsoft's error color is approx R>180, G<90, B<90.
    Returns True if enough red pixels found (error visible)."""
    import ctypes, ctypes.wintypes
    try:
        from PIL import ImageGrab
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
        w = right - left
        h = bottom - top

        # Capture the middle region of the window where error text appears
        region = (
            left + w // 6,
            top + h // 4,
            right - w // 6,
            top + (h * 2) // 3,
        )
        img = ImageGrab.grab(bbox=region)

        red_count = sum(
            1 for r, g, b in img.getdata()
            if r > 180 and g < 90 and b < 90
        )
        return red_count > 50

    except Exception:
        return False


def _click_authenticator_button(timeout: float = 8.0):
    """After password accepted, 'Verify your identity' page may appear with
    multiple MFA options. Click 'Approve a request on my Microsoft Authenticator app'.
    If already on 'Approve sign in request' page (push already sent), does nothing."""
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            sign_in_win = _find_signin_window()
            if not sign_in_win:
                return True  # Window closed — done

            page_text = _get_signin_page_text()

            # Already on the waiting-for-push page — nothing to click
            waiting_keywords = ["approve sign in request", "aprobar solicitud de inicio",
                                "open your authenticator app", "abre tu aplicación",
                                "enter the number", "ingresa el número"]
            if any(kw in page_text for kw in waiting_keywords):
                return True

            # On "Verify your identity / choose method" page — click Authenticator option
            choose_keywords = ["approve a request", "aprobar una solicitud",
                               "authenticator app", "aplicación authenticator",
                               "verify your identity", "verificar tu identidad"]
            if any(kw in page_text for kw in choose_keywords):
                from pywinauto import Desktop
                desktop = Desktop(backend="uia")
                for w in desktop.windows():
                    wtitle = w.window_text().lower()
                    if "sign in to your account" in wtitle or "iniciar sesión" in wtitle:
                        for ctrl in w.descendants():
                            try:
                                ctrl_text = ctrl.window_text().lower()
                                if ("approve a request" in ctrl_text
                                        or "aprobar una solicitud" in ctrl_text
                                        or ("authenticator" in ctrl_text and len(ctrl_text) < 80)):
                                    ctrl.click_input()
                                    return True
                            except Exception:
                                pass
                        break

            time.sleep(0.5)
    except Exception:
        pass
    return False


def _forti_autofill_signin(username: str, password: str) -> str:
    """Wait for the FortiClient SAML sign-in popup and auto-fill credentials.
    The window is Chromium-based so we use keyboard input.
    Re-finds and re-focuses the window before each step.
    Only fills password if we successfully filled the username first.
    After password, clicks the Authenticator approve button if it appears.

    Returns:
        'ok'             — credentials submitted (or no popup appeared)
        'wrong_password' — password was rejected by the sign-in page
        'no_popup'       — no sign-in popup appeared
    """
    try:
        # Step 1: Wait for the sign-in window to appear (up to 20s)
        deadline = time.time() + 20
        sign_in_win = None
        while time.time() < deadline:
            sign_in_win = _find_signin_window()
            if sign_in_win:
                break
            time.sleep(0.5)

        if not sign_in_win:
            return "no_popup"  # No popup — maybe session cached or auto-connected

        time.sleep(1.5)  # Let the page fully render

        # Step 2: Fill username
        username_ok = False
        password_ok = False
        if username:
            sign_in_win = _find_signin_window()
            if not sign_in_win:
                return "ok"

            for _ in range(3):
                sign_in_win = _find_signin_window()
                if not sign_in_win:
                    return "ok"
                if _focus_and_type(sign_in_win.handle, username, press_enter=True):
                    username_ok = True
                    break
                time.sleep(1)

            # Step 3: Wait for password page — only if WE filled the username
            if password and username_ok:
                time.sleep(1.5)

                sign_in_win = _find_signin_window()
                if not sign_in_win:
                    return "ok"

                time.sleep(1.5)

                for _ in range(3):
                    sign_in_win = _find_signin_window()
                    if not sign_in_win:
                        return "ok"
                    # Capture title BEFORE submitting password
                    title_before = sign_in_win.window_text()
                    if _focus_and_type(sign_in_win.handle, password, press_enter=True):
                        password_ok = True
                        break
                    time.sleep(1)

        elif password:
            for _ in range(3):
                sign_in_win = _find_signin_window()
                if not sign_in_win:
                    return "ok"
                title_before = sign_in_win.window_text()
                if _focus_and_type(sign_in_win.handle, password, press_enter=True):
                    password_ok = True
                    break
                time.sleep(1)

        # Step 4: Check if password was rejected, otherwise click Authenticator
        if password_ok:
            if _check_password_rejected(timeout=10, title_before=title_before):
                return "wrong_password"
            # Password accepted — try clicking the Authenticator approve button
            _click_authenticator_button()

        return "ok"

    except Exception:
        return "ok"


def _forti_click_button(win, button_texts, timeout: float = 5.0) -> bool:
    """Find and click a button in the FortiClient Electron window via UIA.
    button_texts can be a string or list of strings (e.g. English + Spanish).
    Matches buttons that contain any of the keywords (case-insensitive)."""
    if isinstance(button_texts, str):
        button_texts = [button_texts]
    keywords = [t.lower() for t in button_texts]
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for ctrl in win.descendants():
                try:
                    if ctrl.element_info.control_type == "Button":
                        ctrl_text = ctrl.window_text().lower()
                        if any(kw in ctrl_text for kw in keywords):
                            ctrl.click()
                            return True
                except Exception:
                    pass
            time.sleep(0.5)
    except Exception:
        pass
    return False


def _cisco_click_connect():
    """Find the Cisco Secure Client window and click its Connect button.
    Retries for up to 8 seconds to give the window time to fully render."""
    try:
        from pywinauto import Desktop
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                desktop = Desktop(backend="win32")
                wins = [w for w in desktop.windows() if w.window_text() == "Cisco Secure Client"]
                for win in wins:
                    for ctrl in win.descendants():
                        try:
                            if (ctrl.window_text().lower() in ("connect", "conectar")
                                    and ctrl.friendly_class_name() == "Button"
                                    and ctrl.is_enabled()):
                                ctrl.click()
                                return True
                        except Exception:
                            pass
            except Exception:
                pass
            time.sleep(0.5)
    except Exception:
        pass
    return False


def _get_adapter_status() -> dict:
    """Use PowerShell Get-NetAdapter to check adapter states.
    Returns dict like {'cisco': 'Up', 'forti': 'Disabled', ...}
    """
    result = {}
    try:
        rc, out, err = _run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-NetAdapter | Select-Object InterfaceDescription, Status | "
             "Format-List"],
            timeout=10,
        )
        current_desc = ""
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("InterfaceDescription"):
                current_desc = line.split(":", 1)[1].strip().lower()
            elif line.startswith("Status"):
                status = line.split(":", 1)[1].strip()
                if "cisco" in current_desc or "anyconnect" in current_desc:
                    result["cisco"] = status
                elif "fortinet" in current_desc and "ssl" in current_desc:
                    result["forti_ssl"] = status
                elif "fortinet" in current_desc:
                    result["forti_ndis"] = status
    except Exception:
        pass
    return result


class VPNController:
    def __init__(self, config: dict):
        self.config = config

    # ── status detection ──────────────────────────────────────────────────────

    def get_status(self) -> str:
        cisco = self._cisco_connected()
        forti = self._forti_connected()
        if cisco:
            return CISCO
        if forti:
            return FORTI
        return NONE

    def _cisco_connected(self) -> bool:
        """Use vpncli state — the authoritative and fast source."""
        cli = _find_exe(CISCO_CLI_CANDIDATES, self.config.get("cisco_cli_path", ""))
        if cli:
            rc, out, err = _run([cli, "state"], timeout=8)
            combined = out + err
            for line in combined.splitlines():
                low = line.strip().lower()
                if "state: connected" in low and "disconnected" not in low:
                    return True
        return False

    def _forti_connected(self) -> bool:
        """Check if the Fortinet SSL VPN adapter is Up via PowerShell."""
        adapters = _get_adapter_status()
        # The SSL VPN adapter (Ethernet 3) goes to "Up" when tunnel is active
        ssl_status = adapters.get("forti_ssl", "")
        return ssl_status.lower() == "up"

    # ── Cisco connect / disconnect ────────────────────────────────────────────

    def connect_cisco(self) -> Tuple[bool, str]:
        host = self.config.get("cisco_host", "").strip()
        username = self.config.get("cisco_username", "").strip()
        password = self.config.get("cisco_password", "").strip()

        # If we have full credentials, try the CLI first
        if host and username and password:
            cli = _find_exe(CISCO_CLI_CANDIDATES, self.config.get("cisco_cli_path", ""))
            if cli:
                stdin_data = f"{username}\n{password}\ny\n"
                rc, out, err = _run([cli, "-s", "connect", host],
                                    input_text=stdin_data, timeout=40)
                combined = (out + err).lower()
                if "state: connected" in combined and "disconnected" not in combined:
                    return True, "Connected to Cisco Secure Client."
                # If CLI fails (e.g. "another application acquired it"), fall through to GUI

        # Open the Cisco Secure Client GUI, bring it to front, and click Connect
        ui = _find_exe(CISCO_UI_CANDIDATES)
        if ui:
            if not _bring_window_to_front("Cisco Secure Client"):
                _open_gui(ui)
            _cisco_click_connect()
            return True, "Connecting via Cisco Secure Client…"

        return False, "Cisco Secure Client not found on this PC."

    def disconnect_cisco(self) -> Tuple[bool, str]:
        cli = _find_exe(CISCO_CLI_CANDIDATES, self.config.get("cisco_cli_path", ""))
        if not cli:
            return False, "Cisco VPN CLI not found."
        _run([cli, "disconnect"], timeout=20)
        time.sleep(2)
        if not self._cisco_connected():
            return True, "Cisco Secure Client disconnected."
        return False, "Cisco disconnect may have failed — check the Cisco app."

    # ── FortiClient connect / disconnect ──────────────────────────────────────

    def connect_forti(self) -> Tuple[bool, str]:
        # 1. Custom command
        cmd = self.config.get("forti_connect_cmd", "").strip()
        if cmd:
            try:
                subprocess.Popen(cmd, shell=True)
                return True, "FortiClient connect command sent."
            except Exception as e:
                return False, f"FortiClient custom command failed: {e}"

        # 2. Try to find and focus the FortiClient window (launch if needed)
        win = _forti_get_window()
        if not win:
            # Launch via explorer and wait
            forti_exe = _find_exe(FORTI_EXE_CANDIDATES, self.config.get("forti_exe_path", ""))
            if not forti_exe:
                return False, "FortiClient not found. Set the path in Settings."
            _open_gui(forti_exe)
            win = _forti_get_window(timeout=10)

        if win:
            try:
                win.set_focus()
            except Exception:
                pass
            _forti_click_button(win, ["Connect", "Conectar"])

            # Auto-fill sign-in credentials if saved
            from config_manager import decrypt_password
            username = self.config.get("forti_username", "").strip()
            password = decrypt_password(self.config.get("forti_password_enc", ""))
            if username or password:
                result = _forti_autofill_signin(username, password)
                if result == "wrong_password":
                    return False, "__WRONG_PASSWORD__"
                return True, "Credentials submitted — approve MFA if prompted."

            return True, "Connecting via FortiClient…"

        return False, "FortiClient launched but window did not appear. Try again."

    def disconnect_forti(self) -> Tuple[bool, str]:
        # 1. Custom command
        cmd = self.config.get("forti_disconnect_cmd", "").strip()
        if cmd:
            try:
                subprocess.run(cmd, shell=True, timeout=15, creationflags=NO_WINDOW)
                time.sleep(2)
                if not self._forti_connected():
                    return True, "FortiClient disconnected."
            except Exception as e:
                return False, f"Custom disconnect failed: {e}"

        # 2. Find the FortiClient window and click Disconnect
        win = _forti_get_window()
        if not win:
            forti_exe = _find_exe(FORTI_EXE_CANDIDATES, self.config.get("forti_exe_path", ""))
            if forti_exe:
                _open_gui(forti_exe)
                win = _forti_get_window(timeout=10)

        if win:
            try:
                win.set_focus()
            except Exception:
                pass
            if _forti_click_button(win, ["Disconnect", "Desconectar"]):
                time.sleep(3)
                if not self._forti_connected():
                    return True, "FortiClient disconnected."
                return True, "Disconnect clicked — waiting for FortiClient to finish."
            return False, "Could not find Disconnect button in FortiClient."

        return False, "FortiClient window not found."

    def disconnect_all(self) -> Tuple[bool, str]:
        status = self.get_status()
        if status == CISCO:
            return self.disconnect_cisco()
        if status == FORTI:
            return self.disconnect_forti()
        return True, "No VPN was active."

    def retry_forti_credentials(self, failed_step: str = "password") -> Tuple[bool, str]:
        """Retry the password after a rejection (username is assumed correct).
        The sign-in window must still be open on the password page.
        Just focuses and types — no re-detection, user sees result on screen."""
        from config_manager import decrypt_password

        if _autofill_cancel.is_set():
            return False, "Cancelled."

        time.sleep(0.8)  # Let Settings window fully close

        sign_in_win = _find_signin_window()
        if not sign_in_win:
            return False, "La ventana de sign-in se cerró. Intenta conectar FortiClient de nuevo."

        password = decrypt_password(self.config.get("forti_password_enc", ""))
        _focus_and_type(sign_in_win.handle, password, press_enter=True)
        return True, "Nueva contraseña enviada — aprueba MFA si se solicita."
