"""
ui.py — system tray icon + main window + settings dialog.
All tkinter work happens on the main thread; pystray runs detached.
"""
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import pystray
from PIL import Image, ImageDraw

from vpn_controller import CISCO, FORTI, NONE, VPNController
from config_manager import ConfigManager

# ── palette ────────────────────────────────────────────────────────────────────
BG = "#1e1e2e"
SURFACE = "#2a2a3e"
BORDER = "#3a3a55"
TEXT = "#e0e0f0"
MUTED = "#7878a0"
WHITE = "#ffffff"

C_CISCO = "#0078d4"
C_FORTI = "#e84545"
C_NONE = "#555577"
C_SUCCESS = "#4ade80"
C_WARN = "#facc15"
C_ERROR = "#f87171"

C_CISCO_HOVER = "#1a8fe0"
C_FORTI_HOVER = "#f05555"
C_NONE_HOVER = "#666688"


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_tray_icon(state: str) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if state == CISCO:
        bg = (0, 120, 212, 255)
    elif state == FORTI:
        bg = (232, 69, 69, 255)
    else:
        bg = (80, 80, 110, 255)

    # Rounded square background
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=14, fill=bg)

    # Lock body
    d.rounded_rectangle([20, 32, 44, 52], radius=4, fill=(255, 255, 255, 230))
    # Lock shackle
    d.arc([18, 14, 46, 40], start=0, end=180, fill=(255, 255, 255, 230), width=5)
    # Keyhole dot
    d.ellipse([29, 38, 35, 44], fill=bg)

    return img


# ── modern button widget ───────────────────────────────────────────────────────

class VPNButton(tk.Frame):
    def __init__(self, parent, title: str, color: str, hover: str, command, **kw):
        super().__init__(parent, bg=color, cursor="hand2", **kw)
        self._color = color
        self._hover = hover
        self._cmd = command
        self._active = False

        inner = tk.Frame(self, bg=color, padx=16, pady=13)
        inner.pack(fill=tk.X)
        self._inner = inner

        self._title_lbl = tk.Label(
            inner, text=title, bg=color, fg=WHITE,
            font=("Segoe UI", 11, "bold"), anchor="w"
        )
        self._title_lbl.pack(fill=tk.X)

        self._status_lbl = tk.Label(
            inner, text="", bg=color, fg="#cccccc",
            font=("Segoe UI", 8), anchor="w"
        )
        self._status_lbl.pack(fill=tk.X)

        self._bind_all()

    def _bind_all(self):
        for w in [self, self._inner, self._title_lbl, self._status_lbl]:
            w.bind("<Button-1>", lambda e: self._cmd())
            w.bind("<Enter>", lambda e: self._set_bg(self._hover))
            w.bind("<Leave>", lambda e: self._set_bg(self._color))

    def _set_bg(self, c):
        for w in [self, self._inner, self._title_lbl, self._status_lbl]:
            w.configure(bg=c)

    def set_sub(self, text: str):
        self._status_lbl.configure(text=text)

    def set_active(self, active: bool):
        self._active = active
        if active:
            self.configure(highlightthickness=2, highlightbackground=WHITE)
        else:
            self.configure(highlightthickness=0)

    def set_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.configure(cursor="hand2" if enabled else "watch")


# ── settings dialog ────────────────────────────────────────────────────────────

class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, config_manager: ConfigManager):
        super().__init__(parent)
        self.config_manager = config_manager
        self.cfg = config_manager.load()

        self.title("VPN Switcher — Settings")
        self.geometry("480x560")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.transient(parent)
        self.grab_set()

        self._build()
        self._center()

    def _center(self):
        self.update_idletasks()
        pw = self.master.winfo_rootx()
        ph = self.master.winfo_rooty()
        x = pw + (self.master.winfo_width() - 480) // 2
        y = ph + (self.master.winfo_height() - 560) // 2
        self.geometry(f"480x560+{x}+{y}")

    def _label(self, parent, text):
        tk.Label(parent, text=text, bg=BG, fg=MUTED,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(8, 1))

    def _entry(self, parent, key, show=""):
        var = tk.StringVar(value=self.cfg.get(key, ""))
        e = tk.Entry(
            parent, textvariable=var, show=show,
            bg=SURFACE, fg=TEXT, insertbackground=TEXT,
            relief=tk.FLAT, font=("Segoe UI", 10),
            highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=C_CISCO
        )
        e.pack(fill=tk.X, ipady=5)
        return var

    def _section(self, parent, title):
        tk.Label(parent, text=title, bg=BG, fg=TEXT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(14, 2))
        sep = tk.Frame(parent, bg=BORDER, height=1)
        sep.pack(fill=tk.X, pady=(0, 4))

    def _build(self):
        canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        frame = tk.Frame(canvas, bg=BG, padx=20)
        win_id = canvas.create_window((0, 0), window=frame, anchor="nw")

        def _on_resize(e):
            canvas.itemconfig(win_id, width=e.width)
        canvas.bind("<Configure>", _on_resize)

        def _on_frame_resize(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        frame.bind("<Configure>", _on_frame_resize)

        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        # ── Cisco ──────────────────────────────────────────────────────────────
        self._section(frame, "Cisco Secure Client")

        self._label(frame, "VPN Host (e.g. vpn.company.com)")
        self._v_cisco_host = self._entry(frame, "cisco_host")

        self._label(frame, "Username (leave blank to be prompted by Cisco)")
        self._v_cisco_user = self._entry(frame, "cisco_username")

        self._label(frame, "Password (stored in plain text — leave blank to be prompted)")
        self._v_cisco_pass = self._entry(frame, "cisco_password", show="●")

        self._label(frame, "vpncli.exe path (leave blank to auto-detect)")
        self._v_cisco_cli = self._entry(frame, "cisco_cli_path")

        # ── FortiClient ────────────────────────────────────────────────────────
        self._section(frame, "FortiClient VPN")

        self._label(frame, "FortiClientVPN.exe path (leave blank to auto-detect)")
        self._v_forti_exe = self._entry(frame, "forti_exe_path")

        self._label(frame, "Custom connect command (optional — overrides launching the app)")
        self._v_forti_conn = self._entry(frame, "forti_connect_cmd")

        self._label(frame, 'Custom disconnect command (optional — e.g. rasdial "VPN Name" /disconnect)')
        self._v_forti_disc = self._entry(frame, "forti_disconnect_cmd")

        # ── General ───────────────────────────────────────────────────────────
        self._section(frame, "General")

        self._v_startup = tk.BooleanVar(value=self.cfg.get("start_with_windows", True))
        chk = tk.Checkbutton(
            frame, text="Start VPN Switcher with Windows",
            variable=self._v_startup,
            bg=BG, fg=TEXT, selectcolor=SURFACE,
            activebackground=BG, activeforeground=TEXT,
            font=("Segoe UI", 10)
        )
        chk.pack(anchor="w", pady=6)

        # ── buttons ────────────────────────────────────────────────────────────
        btn_frame = tk.Frame(self, bg=BG, pady=12, padx=20)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        tk.Button(
            btn_frame, text="Cancel",
            bg=SURFACE, fg=MUTED, relief=tk.FLAT,
            font=("Segoe UI", 10), padx=16, pady=6,
            command=self.destroy, cursor="hand2"
        ).pack(side=tk.RIGHT, padx=(6, 0))

        tk.Button(
            btn_frame, text="Save",
            bg=C_CISCO, fg=WHITE, relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"), padx=16, pady=6,
            command=self._save, cursor="hand2"
        ).pack(side=tk.RIGHT)

    def _save(self):
        self.cfg.update({
            "cisco_host": self._v_cisco_host.get().strip(),
            "cisco_username": self._v_cisco_user.get().strip(),
            "cisco_password": self._v_cisco_pass.get(),
            "cisco_cli_path": self._v_cisco_cli.get().strip(),
            "forti_exe_path": self._v_forti_exe.get().strip(),
            "forti_connect_cmd": self._v_forti_conn.get().strip(),
            "forti_disconnect_cmd": self._v_forti_disc.get().strip(),
            "start_with_windows": self._v_startup.get(),
        })
        self.config_manager.save(self.cfg)
        self.destroy()


# ── main application ───────────────────────────────────────────────────────────

class VPNSwitcherApp:
    POLL_INTERVAL = 6  # seconds between status checks

    def __init__(self):
        self.config_manager = ConfigManager()
        self.config = self.config_manager.load()
        self.controller = VPNController(self.config)

        self._status = NONE
        self._busy = False
        self._tray = None  # type: pystray.Icon

        # Build root window (hidden until ready)
        self.root = tk.Tk()
        self.root.withdraw()
        self._build_window()

    # ── window ─────────────────────────────────────────────────────────────────

    def _build_window(self):
        root = self.root
        root.title("VPN Switcher")
        root.geometry("330x400")
        root.resizable(False, False)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self._hide)

        # Try to set window icon
        try:
            ico = _make_tray_icon(NONE)
            from PIL import ImageTk
            self._tk_icon = ImageTk.PhotoImage(ico)
            root.iconphoto(True, self._tk_icon)
        except Exception:
            pass

        # ── header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(root, bg=BG, pady=18)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="VPN Switcher", bg=BG, fg=TEXT,
                 font=("Segoe UI", 16, "bold")).pack()

        # ── status card ───────────────────────────────────────────────────────
        card = tk.Frame(root, bg=SURFACE, pady=14, padx=20,
                        highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill=tk.X, padx=20, pady=(0, 18))

        tk.Label(card, text="CURRENT STATUS", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 7, "bold")).pack()

        self._dot = tk.Label(card, text="●", bg=SURFACE, fg=C_NONE,
                             font=("Segoe UI", 18))
        self._dot.pack(pady=(2, 0))

        self._status_lbl = tk.Label(card, text="Checking…", bg=SURFACE, fg=TEXT,
                                    font=("Segoe UI", 11, "bold"))
        self._status_lbl.pack()

        # ── VPN buttons ───────────────────────────────────────────────────────
        btn_area = tk.Frame(root, bg=BG)
        btn_area.pack(fill=tk.X, padx=20)

        self._btn_cisco = VPNButton(
            btn_area, "Cisco Secure Client", C_CISCO, C_CISCO_HOVER,
            lambda: self._switch(CISCO)
        )
        self._btn_cisco.pack(fill=tk.X, pady=4)

        self._btn_forti = VPNButton(
            btn_area, "FortiClient VPN", C_FORTI, C_FORTI_HOVER,
            lambda: self._switch(FORTI)
        )
        self._btn_forti.pack(fill=tk.X, pady=4)

        self._btn_none = VPNButton(
            btn_area, "No VPN", C_NONE, C_NONE_HOVER,
            self._disconnect_all
        )
        self._btn_none.pack(fill=tk.X, pady=4)

        # ── message area ──────────────────────────────────────────────────────
        self._msg_lbl = tk.Label(root, text="", bg=BG, fg=MUTED,
                                 font=("Segoe UI", 8), wraplength=290)
        self._msg_lbl.pack(pady=(6, 0), padx=20)

        # ── bottom bar ────────────────────────────────────────────────────────
        bottom = tk.Frame(root, bg=BG, pady=10, padx=20)
        bottom.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Button(
            bottom, text="⚙  Settings",
            bg=SURFACE, fg=MUTED, relief=tk.FLAT,
            font=("Segoe UI", 9), pady=4, padx=10,
            command=self._open_settings, cursor="hand2"
        ).pack(side=tk.RIGHT)

    def _center_window(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 330) // 2
        y = (sh - 400) // 2
        self.root.geometry(f"330x400+{x}+{y}")

    # ── tray ───────────────────────────────────────────────────────────────────

    def _build_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Open", self._show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Cisco Secure Client", lambda: self._switch(CISCO)),
            pystray.MenuItem("FortiClient VPN", lambda: self._switch(FORTI)),
            pystray.MenuItem("No VPN", self._disconnect_all),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings", self._open_settings),
            pystray.MenuItem("Exit", self._quit),
        )
        icon_img = _make_tray_icon(self._status)
        self._tray = pystray.Icon("VPNSwitcher", icon_img, "VPN Switcher", menu)

    def _update_tray_icon(self):
        if self._tray:
            self._tray.icon = _make_tray_icon(self._status)

    # ── status monitor ─────────────────────────────────────────────────────────

    def _monitor(self):
        while True:
            if not self._busy:
                try:
                    s = self.controller.get_status()
                    if s != self._status:
                        self._status = s
                        self.root.after(0, self._refresh_ui)
                        self._update_tray_icon()
                except Exception:
                    pass
            time.sleep(self.POLL_INTERVAL)

    def _refresh_ui(self):
        s = self._status
        if s == CISCO:
            dot_color, label = C_CISCO, "Cisco Secure Client"
            self._btn_cisco.set_active(True)
            self._btn_forti.set_active(False)
            self._btn_none.set_active(False)
        elif s == FORTI:
            dot_color, label = C_FORTI, "FortiClient VPN"
            self._btn_cisco.set_active(False)
            self._btn_forti.set_active(True)
            self._btn_none.set_active(False)
        else:
            dot_color, label = C_NONE, "No VPN Connected"
            self._btn_cisco.set_active(False)
            self._btn_forti.set_active(False)
            self._btn_none.set_active(True)

        self._dot.configure(fg=dot_color)
        self._status_lbl.configure(text=label)

        # Update tray tooltip
        if self._tray:
            self._tray.title = f"VPN Switcher — {label}"

    # ── actions ────────────────────────────────────────────────────────────────

    def _switch(self, target: str):
        if self._busy:
            return
        # Re-load config in case settings changed
        self.config = self.config_manager.load()
        self.controller.config = self.config

        current = self._status

        def _work():
            self._set_busy(True)
            try:
                # Disconnect the other VPN first
                if current == CISCO and target != CISCO:
                    self._msg("Disconnecting Cisco Secure Client…")
                    ok, msg = self.controller.disconnect_cisco()
                    if not ok:
                        self._msg(f"⚠  {msg}")
                        time.sleep(2)
                    else:
                        time.sleep(1)  # Give OS a moment

                elif current == FORTI and target != FORTI:
                    self._msg("Disconnecting FortiClient VPN…")
                    ok, msg = self.controller.disconnect_forti()
                    if not ok:
                        self._msg(f"⚠  {msg}")
                        time.sleep(2)
                    else:
                        time.sleep(1)

                # Connect target
                if target == CISCO:
                    self._msg("Connecting to Cisco Secure Client…")
                    ok, msg = self.controller.connect_cisco()
                elif target == FORTI:
                    self._msg("Connecting to FortiClient VPN…")
                    ok, msg = self.controller.connect_forti()
                else:
                    ok, msg = True, "Disconnected."

                self._msg(msg)

                # Force a status refresh
                time.sleep(3)
                new_status = self.controller.get_status()
                self._status = new_status
                self.root.after(0, self._refresh_ui)
                self._update_tray_icon()

            finally:
                self._set_busy(False)

        threading.Thread(target=_work, daemon=True).start()

    def _disconnect_all(self):
        if self._busy:
            return

        def _work():
            self._set_busy(True)
            try:
                self._msg("Disconnecting…")
                ok, msg = self.controller.disconnect_all()
                self._msg(msg)
                time.sleep(2)
                new_status = self.controller.get_status()
                self._status = new_status
                self.root.after(0, self._refresh_ui)
                self._update_tray_icon()
            finally:
                self._set_busy(False)

        threading.Thread(target=_work, daemon=True).start()

    # ── window show/hide ───────────────────────────────────────────────────────

    def _show(self, *_):
        self.root.after(0, self.__show)

    def __show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _hide(self):
        self.root.withdraw()

    def _quit(self, *_):
        if self._tray:
            self._tray.stop()
        self.root.after(0, self.root.destroy)

    def _open_settings(self, *_):
        self.root.after(0, self.__open_settings)

    def __open_settings(self):
        self.__show()
        dlg = SettingsDialog(self.root, self.config_manager)
        self.root.wait_window(dlg)
        # Reload config after settings saved
        self.config = self.config_manager.load()
        self.controller.config = self.config

    # ── helpers ────────────────────────────────────────────────────────────────

    def _msg(self, text: str):
        self.root.after(0, lambda: self._msg_lbl.configure(text=text))

    def _set_busy(self, busy: bool):
        self._busy = busy
        cursor = "watch" if busy else "arrow"
        self.root.after(0, lambda: self.root.configure(cursor=cursor))

    # ── run ────────────────────────────────────────────────────────────────────

    def run(self):
        # First-run prompt if nothing is configured yet
        if not self.config_manager.is_configured():
            self.root.after(200, self.__open_settings)

        # Build & start tray (non-blocking)
        self._build_tray()
        self._tray.run_detached()

        # Start polling thread
        threading.Thread(target=self._monitor, daemon=True).start()

        # Show window, then enter main loop
        self._center_window()
        self.root.deiconify()

        # Initial status
        def _init_status():
            s = self.controller.get_status()
            self._status = s
            self._refresh_ui()
        threading.Thread(target=_init_status, daemon=True).start()

        self.root.mainloop()
