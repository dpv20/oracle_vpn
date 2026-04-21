import os
import subprocess
import threading
import time
from typing import Optional, Tuple

from logger import get_logger

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


def _forti_dismiss_error_dialog() -> bool:
    """Auto-click OK on the Electron crash dialog FortiClient sometimes shows on launch.
    Returns True if a dialog was found and dismissed."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "Error")
        if not hwnd:
            return False
        # Try every locale variant of the OK button text.
        for label in ("OK", "Aceptar", "확인", "Ok"):
            ok_hwnd = user32.FindWindowExW(hwnd, None, "Button", label)
            if ok_hwnd:
                user32.SendMessageW(ok_hwnd, 0x00F5, 0, 0)  # BM_CLICK
                return True
        # Fallback: close via WM_COMMAND IDOK=1
        user32.SendMessageW(hwnd, 0x0111, 1, 0)  # WM_COMMAND, IDOK
        return True
    except Exception:
        return False


def _forti_diagnostics():
    """Dump every Forti-related process + every window containing 'forti' (any case)
    into the log, visible or hidden. Called when normal detection fails so we can
    debug remotely from the log file."""
    log = get_logger()
    # --- Processes ---
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(["pid", "name", "exe"]):
            try:
                name = (p.info.get("name") or "").lower()
                if "forti" in name:
                    procs.append(f"{p.info['pid']}:{p.info['name']}")
            except Exception:
                pass
        log.info(f"forti_diag: processes={procs or 'NONE'}")
    except Exception as e:
        log.warning(f"forti_diag: process enum failed: {e}")

    # --- Windows (all top-level, visible or hidden) ---
    try:
        import ctypes
        user32 = ctypes.windll.user32
        matches = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def _enum(hwnd, _):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                if "forti" in title.lower() or title == "Error":
                    visible = bool(user32.IsWindowVisible(hwnd))
                    cls_buf = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, cls_buf, 256)
                    matches.append(
                        f"hwnd={hwnd} visible={visible} class='{cls_buf.value}' title='{title}'"
                    )
            return True

        user32.EnumWindows(WNDENUMPROC(_enum), 0)
        if matches:
            for m in matches:
                log.info(f"forti_diag: window {m}")
        else:
            log.info("forti_diag: no forti/error windows found")
    except Exception as e:
        log.warning(f"forti_diag: window enum failed: {e}")


def _forti_restore_tray_window() -> bool:
    """Find and restore a hidden FortiClient tray window without launching a new process.
    Returns True if a FortiClient window (visible or hidden) was found and shown."""
    log = get_logger()
    try:
        import ctypes
        user32 = ctypes.windll.user32
        found = [None]
        found_title = [""]

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def _enum(hwnd, _):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if buf.value == FORTI_TITLE:
                    found[0] = hwnd
                    found_title[0] = buf.value
                    return False  # stop enumeration
            return True

        user32.EnumWindows(WNDENUMPROC(_enum), 0)
        if found[0]:
            was_visible = bool(user32.IsWindowVisible(found[0]))
            sw_rc = user32.ShowWindow(found[0], 9)   # SW_RESTORE
            fg_rc = user32.SetForegroundWindow(found[0])
            log.info(f"forti_restore: hwnd={found[0]} title='{found_title[0]}' "
                     f"was_visible={was_visible} ShowWindow={sw_rc} SetForeground={fg_rc}")
            return True
        log.info("forti_restore: no window matching FORTI_TITLE found")
    except Exception as e:
        log.warning(f"forti_restore: exception {e}")
    return False


def _forti_get_window(timeout: float = 1.0):
    """Find the FortiClient Electron window via pywinauto UIA backend.
    Returns the window wrapper or None."""
    try:
        from pywinauto import Desktop
        deadline = time.time() + timeout
        while time.time() < deadline:
            _forti_dismiss_error_dialog()
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
    Matches English, Spanish, and FortiClient-titled popups."""
    try:
        from pywinauto import Desktop
        desktop = Desktop(backend="win32")
        for w in desktop.windows():
            title = w.window_text().lower()
            if ("sign in to your account" in title
                    or "iniciar sesión" in title
                    or ("forticlient" in title and "(" in title)):
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
    """Detect if the password was rejected using red pixel + page text detection.

    Microsoft shows 'Your account or password is incorrect' in bright red.
    However, some verification pages ('We need to verify more') also have red
    elements — so when red pixels are detected we re-read the page text to
    confirm it's an actual password error, not a verification/MFA step.
    """
    # Wait for the page to react (title change or timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.5)
        sign_in_win = _find_signin_window()
        if not sign_in_win:
            return False  # Window gone — success
        if title_before and sign_in_win.window_text() != title_before:
            break  # Page reacted

    time.sleep(2.0)  # Let page fully render

    sign_in_win = _find_signin_window()
    if not sign_in_win:
        return False

    if not _window_has_red_error(sign_in_win.handle):
        return False  # No red pixels — password accepted, moving on

    # Red pixels detected — could be wrong password OR a verification page.
    # Re-read page text to distinguish.
    page = _detect_signin_page(sign_in_win.handle)
    if page == "mfa":
        _click_authenticator_button()
        return False

    text = _get_clipboard_text().lower()
    verification_keywords = [
        "verify", "verificar", "approve", "aprobar", "authenticator",
        "more information", "más información", "we need", "necesitamos",
        "additional", "conditional", "access", "sign-in options",
    ]
    if any(kw in text for kw in verification_keywords):
        # It's a verification/MFA page with red UI elements — not a wrong password
        _click_authenticator_button()
        return False

    return True  # Red pixels + error keywords = actual wrong password


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


def _get_clipboard_text() -> str:
    """Read text from the Windows clipboard via PowerShell Get-Clipboard."""
    try:
        _, out, _ = _run(
            ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard"],
            timeout=5,
        )
        return out.strip()
    except Exception:
        return ""


def _detect_signin_page(hwnd) -> str:
    """Detect which sign-in page is shown by reading text via Ctrl+A + Ctrl+C.

    Works across different PCs, branding, window sizes, and languages.
    After reading, clicks the input field area to restore focus for typing.

    Returns:
        'password' — password entry page
        'email'    — email/username entry page
        'mfa'      — MFA / verify identity page
        'unknown'  — could not determine
    """
    from pywinauto import keyboard
    import ctypes
    user32 = ctypes.windll.user32

    try:
        _force_foreground(hwnd)
        time.sleep(0.3)
        if user32.GetForegroundWindow() != hwnd:
            return "unknown"

        # Click on the banner/logo area at the very top of the page content
        # (~50 px below the window top, above any interactive elements on both pages).
        # This gives Chromium real keyboard focus and blurs any focused input,
        # so Ctrl+A selects ALL page text — not just the focused input field.
        import ctypes.wintypes
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        cx = (rect.left + rect.right) // 2
        cy = rect.top + 50   # just below title bar → banner/logo area, always safe
        user32.SetCursorPos(cx, cy)
        time.sleep(0.05)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
        time.sleep(0.02)
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
        time.sleep(0.2)

        # Select all page text and copy to clipboard
        keyboard.send_keys("^a", pause=0.05)
        time.sleep(0.15)
        keyboard.send_keys("^c", pause=0.05)
        time.sleep(0.2)

        text = _get_clipboard_text().lower()

        # Debug log
        try:
            import os, tempfile
            log_path = os.path.join(tempfile.gettempdir(), "vpnswitcher_page_detect.txt")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"page_text: {repr(text[:300])}\n")
        except Exception:
            pass

        if not text:
            result = "unknown"
        elif any(kw in text for kw in [
            "enter password", "contraseña", "forgot my password",
            "olvidé mi contraseña", "forgot password",
        ]):
            result = "password"
        elif any(kw in text for kw in [
            "verify your identity", "verificar tu identidad",
            "approve sign in", "aprobar solicitud", "authenticator",
        ]):
            result = "mfa"
        else:
            result = "email"

        # Email page:    1 Tab from body → email input
        # Password page: 2 Tabs from body → skip back-arrow button → password input
        tab_count = 2 if result == "password" else 1
        for _ in range(tab_count):
            keyboard.send_keys("{TAB}", pause=0.1)
            time.sleep(0.15)

        return result

    except Exception:
        return "unknown"


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

    Adaptively detects which page is shown (email or password) before typing,
    so it works on PCs that skip the email page or show password directly.

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
            if _autofill_cancel.is_set():
                return "ok"
            sign_in_win = _find_signin_window()
            if sign_in_win:
                break
            time.sleep(0.5)

        if not sign_in_win:
            return "no_popup"

        time.sleep(1.5)  # Let the page fully render

        # Step 2: Detect page — leaves input focused via Tab at the end
        page = _detect_signin_page(sign_in_win.handle)

        if page == "mfa":
            _click_authenticator_button()
            return "ok"

        title_before = ""
        password_typed = False

        # Helper: type into the already-focused input.
        # Uses SetForegroundWindow (not SetFocus) so Chromium keeps its internal
        # focus on the input that Tab already selected. No Ctrl+A — inputs are
        # empty on first load so we just type directly.
        def _type_into_focused(text, press_enter=True) -> bool:
            import ctypes
            from pywinauto import keyboard as kb
            if _autofill_cancel.is_set():
                return False
            # Light re-activation: make the window active without triggering
            # WM_SETFOCUS which would reset Chromium's internal focus to body.
            ctypes.windll.user32.SetForegroundWindow(sign_in_win.handle)
            time.sleep(0.15)
            kb.send_keys(text, with_spaces=True, pause=0.03)
            time.sleep(0.1)
            if press_enter:
                kb.send_keys("{ENTER}", pause=0.05)
            return True

        # Step 3a: Email page — type email, then wait for transition
        if page == "email" and username:
            if _autofill_cancel.is_set():
                return "ok"
            _type_into_focused(username, press_enter=True)

            # Wait for page to transition (up to 9 s, one detection check every 3 s).
            # Don't loop _detect_signin_page rapidly — each call clicks the page.
            for _ in range(3):
                if _autofill_cancel.is_set():
                    return "ok"
                time.sleep(3.0)
                sign_in_win = _find_signin_window()
                if not sign_in_win:
                    return "ok"
                page = _detect_signin_page(sign_in_win.handle)
                if page in ("password", "mfa"):
                    break

        if page == "mfa":
            _click_authenticator_button()
            return "ok"

        # Step 3b: Type password — only when detection confirmed password page.
        # Do NOT use "email" as a fallback: if the page didn't transition it means
        # the email wasn't accepted, and typing the password here would put it in
        # the email field.
        if password and page == "password":
            if _autofill_cancel.is_set():
                return "ok"
            sign_in_win = _find_signin_window()
            if sign_in_win:
                title_before = sign_in_win.window_text()
                if _type_into_focused(password, press_enter=True):
                    password_typed = True

        # Step 4: Check if password was rejected, otherwise click Authenticator
        if password_typed:
            if _check_password_rejected(timeout=10, title_before=title_before):
                return "wrong_password"
            _click_authenticator_button()

        return "ok"

    except Exception:
        return "ok"


def _forti_autofill_custom_flow(username: str, password: str, steps: list) -> str:
    """Execute a user-defined sign-in sequence without page detection.

    steps: ordered subset of ["username", "password", "mfa"]
    Each step is executed in order; unchecked steps are skipped.

    Returns 'ok', 'wrong_password', or 'no_popup'.
    """
    try:
        # Wait for sign-in window
        deadline = time.time() + 20
        sign_in_win = None
        while time.time() < deadline:
            if _autofill_cancel.is_set():
                return "ok"
            sign_in_win = _find_signin_window()
            if sign_in_win:
                break
            time.sleep(0.5)

        if not sign_in_win:
            return "no_popup"

        time.sleep(1.5)

        title_before = ""
        password_typed = False
        # Track if we already typed username so we know the password page
        # will have a back arrow (needs 2 Tabs instead of 1).
        typed_username = False

        def _focus_and_type_step(tab_count: int, text: str, press_enter: bool = True) -> bool:
            """Click banner to give Chromium focus, Tab to input, then type."""
            import ctypes, ctypes.wintypes
            from pywinauto import keyboard as kb
            user32 = ctypes.windll.user32

            nonlocal sign_in_win
            sign_in_win = _find_signin_window()
            if not sign_in_win or _autofill_cancel.is_set():
                return False

            _force_foreground(sign_in_win.handle)
            time.sleep(0.2)
            if user32.GetForegroundWindow() != sign_in_win.handle:
                return False

            # Click banner area (top+50) to give Chromium keyboard focus
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(sign_in_win.handle, ctypes.byref(rect))
            cx = (rect.left + rect.right) // 2
            cy = rect.top + 50
            user32.SetCursorPos(cx, cy)
            time.sleep(0.05)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            time.sleep(0.02)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            time.sleep(0.2)

            for _ in range(tab_count):
                kb.send_keys("{TAB}", pause=0.1)
                time.sleep(0.15)

            # Light re-activation before typing
            user32.SetForegroundWindow(sign_in_win.handle)
            time.sleep(0.15)
            kb.send_keys(text, with_spaces=True, pause=0.03)
            time.sleep(0.1)
            if press_enter:
                kb.send_keys("{ENTER}", pause=0.05)
            return True

        for step in steps:
            if _autofill_cancel.is_set():
                return "ok"

            if step == "username" and username:
                # Email page: 1 Tab from banner → email input
                _focus_and_type_step(tab_count=1, text=username)
                typed_username = True
                time.sleep(3.0)  # Wait for page transition

            elif step == "password" and password:
                # Password page after email: back arrow present → 2 Tabs
                # Password page as first step (no email): no back arrow → 1 Tab
                tab_count = 2 if typed_username else 1
                sign_in_win = _find_signin_window()
                if sign_in_win:
                    title_before = sign_in_win.window_text()
                if _focus_and_type_step(tab_count=tab_count, text=password):
                    password_typed = True

            elif step == "mfa":
                _click_authenticator_button()
                return "ok"

        if password_typed:
            if _check_password_rejected(timeout=10, title_before=title_before):
                return "wrong_password"
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
    log = get_logger()
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for ctrl in win.descendants():
                try:
                    if ctrl.element_info.control_type == "Button":
                        ctrl_text = ctrl.window_text().lower()
                        if any(kw in ctrl_text for kw in keywords):
                            log.info(f"FortiClient: clicking button '{ctrl.window_text()}'")
                            ctrl.click()
                            return True
                except Exception:
                    pass
            time.sleep(0.5)
    except Exception as e:
        log.error(f"FortiClient: _forti_click_button error: {e}")
    log.warning(f"FortiClient: button not found (candidates: {button_texts})")
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
        log = get_logger()
        log.info("connect_cisco: attempt started")
        host = self.config.get("cisco_host", "").strip()
        username = self.config.get("cisco_username", "").strip()
        password = self.config.get("cisco_password", "").strip()

        # If we have full credentials, try the CLI first
        if host and username and password:
            cli = _find_exe(CISCO_CLI_CANDIDATES, self.config.get("cisco_cli_path", ""))
            if cli:
                log.info(f"connect_cisco: trying CLI ({cli}) → {host}")
                stdin_data = f"{username}\n{password}\ny\n"
                rc, out, err = _run([cli, "-s", "connect", host],
                                    input_text=stdin_data, timeout=40)
                combined = (out + err).lower()
                if "state: connected" in combined and "disconnected" not in combined:
                    log.info("connect_cisco: CLI connected")
                    return True, "Connected to Cisco Secure Client."
                log.warning(f"connect_cisco: CLI did not connect (rc={rc}), falling back to GUI")

        # Open the Cisco Secure Client GUI, bring it to front, and click Connect
        ui = _find_exe(CISCO_UI_CANDIDATES)
        if ui:
            log.info("connect_cisco: opening GUI and clicking Connect")
            if not _bring_window_to_front("Cisco Secure Client"):
                _open_gui(ui)
            _cisco_click_connect()
            return True, "Connecting via Cisco Secure Client…"

        log.error("connect_cisco: Cisco Secure Client not found")
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
        log = get_logger()
        log.info("connect_forti: attempt started")
        _forti_diagnostics()

        # 1. Custom command
        cmd = self.config.get("forti_connect_cmd", "").strip()
        if cmd:
            try:
                subprocess.Popen(cmd, shell=True)
                log.info("connect_forti: custom command sent")
                return True, "FortiClient connect command sent."
            except Exception as e:
                log.error(f"connect_forti: custom command failed: {e}")
                return False, f"FortiClient custom command failed: {e}"

        # 2. Try to find and focus the FortiClient window (launch if needed)
        win = _forti_get_window()
        log.info(f"connect_forti: initial _forti_get_window returned win={bool(win)}")
        if not win:
            # FortiClient may be running as a tray process with its window hidden.
            # Restore the hidden window instead of launching a second instance
            # (a second instance causes a JS crash on some versions).
            restored = _forti_restore_tray_window()
            log.info(f"connect_forti: tray restore attempt, found={restored}")
            if restored:
                win = _forti_get_window(timeout=5)
                log.info(f"connect_forti: after restore _forti_get_window returned win={bool(win)}")

        if not win:
            log.info("connect_forti: no existing window found; diagnostics before launch:")
            _forti_diagnostics()
            forti_exe = _find_exe(FORTI_EXE_CANDIDATES, self.config.get("forti_exe_path", ""))
            if not forti_exe:
                log.error("connect_forti: FortiClient exe not found")
                return False, "FortiClient not found. Set the path in Settings."
            log.info(f"connect_forti: launching {forti_exe}")
            _open_gui(forti_exe)
            win = _forti_get_window(timeout=12)
            if not win:
                dismissed = _forti_dismiss_error_dialog()
                log.warning(f"connect_forti: window not found after launch, dismissed_dialog={dismissed}")
                log.info("connect_forti: diagnostics after failed launch:")
                _forti_diagnostics()

        if win:
            log.info("connect_forti: FortiClient window found")
            try:
                win.set_focus()
            except Exception:
                pass
            _forti_click_button(win, ["Connect", "Conectar", "SAML Login"])

            # Auto-fill sign-in credentials if saved
            from config_manager import decrypt_password
            username = self.config.get("forti_username", "").strip()
            password = decrypt_password(self.config.get("forti_password_enc", ""))
            if username or password:
                flow_mode  = self.config.get("forti_flow_mode", "detect")
                flow_steps = self.config.get("forti_flow_steps",
                                             ["username", "password", "mfa"])
                log.info(f"connect_forti: autofill starting (mode={flow_mode})")
                if flow_mode == "custom":
                    result = _forti_autofill_custom_flow(username, password, flow_steps)
                else:
                    result = _forti_autofill_signin(username, password)
                log.info(f"connect_forti: autofill result={result}")
                if result == "wrong_password":
                    return False, "__WRONG_PASSWORD__"
                return True, "Credentials submitted — approve MFA if prompted."

            return True, "Connecting via FortiClient…"

        log.error("connect_forti: window did not appear after launch")
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
        Checks for rejection again so the UI can re-prompt if still wrong."""
        from config_manager import decrypt_password

        if _autofill_cancel.is_set():
            return False, "Cancelled."

        time.sleep(0.8)  # Let Settings window fully close

        sign_in_win = _find_signin_window()
        if not sign_in_win:
            return False, "La ventana de sign-in se cerró. Intenta conectar FortiClient de nuevo."

        password = decrypt_password(self.config.get("forti_password_enc", ""))
        title_before = sign_in_win.window_text()
        _focus_and_type(sign_in_win.handle, password, press_enter=True)

        # Check if the new password was also rejected
        if _check_password_rejected(timeout=10, title_before=title_before):
            return False, "__WRONG_PASSWORD__"

        # Password accepted — try clicking the Authenticator approve button
        _click_authenticator_button()
        return True, "Nueva contraseña enviada — aprueba MFA si se solicita."
