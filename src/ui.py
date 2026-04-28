"""
ui.py — system tray icon + main window + settings dialog.
All tkinter work happens on the main thread; pystray runs detached.
"""
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import pystray
from PIL import Image, ImageDraw

from vpn_controller import CISCO, FORTI, GPROT, NONE, VPNController
from config_manager import ConfigManager
from utils import asset_path

# ── palette ────────────────────────────────────────────────────────────────────
BG = "#1e1e2e"
SURFACE = "#2a2a3e"
BORDER = "#3a3a55"
TEXT = "#e0e0f0"
MUTED = "#7878a0"
WHITE = "#ffffff"

C_CISCO = "#b71c1c"       # Oracle red
C_FORTI = "#2e7d32"       # Falabella green
C_GP    = "#1565c0"       # BICE blue (GlobalProtect)
C_NONE = "#555577"
C_SUCCESS = "#4ade80"
C_WARN = "#facc15"
C_ERROR = "#f87171"

C_CISCO_HOVER = "#c62828"
C_FORTI_HOVER = "#388e3c"
C_GP_HOVER    = "#1976d2"
C_NONE_HOVER = "#666688"


# ── helpers ────────────────────────────────────────────────────────────────────

def _load_logo(variant: str = "") -> Image.Image:
    """Load a logo PNG and remove white border pixels.
    variant: '' = logo_cuadrado.png, 'rojo' = logo_cuadrado_rojo.png, 'verde' = logo_cuadrado_verde.png
    """
    name = f"logo_cuadrado_{variant}.png" if variant else "logo_cuadrado.png"
    logo_path = asset_path(name)
    img = Image.open(logo_path).convert("RGBA")
    data = img.getdata()
    new_data = [
        (r, g, b, 0) if (r > 235 and g > 235 and b > 235) else (r, g, b, a)
        for r, g, b, a in data
    ]
    img.putdata(new_data)
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    return img


def _make_tray_icon(state: str) -> Image.Image:
    """Lock icon for the system tray. Grey = no VPN, red = Oracle/Cisco,
    green = Falabella/Forti, blue = BICE/GlobalProtect."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if state == CISCO:
        bg = (183, 28, 28, 255)    # Oracle red
    elif state == FORTI:
        bg = (46, 125, 50, 255)    # Falabella green
    elif state == GPROT:
        bg = (21, 101, 192, 255)   # BICE blue
    else:
        bg = (80, 80, 110, 255)    # grey

    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=14, fill=bg)
    d.rounded_rectangle([20, 32, 44, 52], radius=4, fill=(255, 255, 255, 230))
    d.arc([18, 14, 46, 40], start=0, end=180, fill=(255, 255, 255, 230), width=5)
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
        self.geometry("500x600")
        self.minsize(420, 500)
        self.resizable(True, True)
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
        # ── button bar must be packed FIRST so it anchors to the bottom ──────
        btn_frame = tk.Frame(self, bg=BG, pady=12, padx=20)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X)

        tk.Button(
            btn_frame, text="Cancel",
            bg=SURFACE, fg=MUTED, relief=tk.FLAT,
            font=("Segoe UI", 10), padx=16, pady=6,
            command=self.destroy, cursor="hand2"
        ).pack(side=tk.RIGHT, padx=(6, 0))

        tk.Button(
            btn_frame, text="  Save  ",
            bg=C_CISCO, fg=WHITE, relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"), padx=16, pady=6,
            command=self._save, cursor="hand2"
        ).pack(side=tk.RIGHT)

        # thin separator above buttons
        tk.Frame(self, bg=BORDER, height=1).pack(side=tk.BOTTOM, fill=tk.X)

        # ── scrollable content area ────────────────────────────────────────────
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

        def _on_mousewheel(e):
            try:
                canvas.yview_scroll(-1 * (e.delta // 120), "units")
            except Exception:
                pass
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.bind("<Destroy>", lambda _: canvas.unbind_all("<MouseWheel>"))

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

        self._label(frame, "Sign-in email (auto-filled in the login popup)")
        self._v_forti_user = self._entry(frame, "forti_username")

        self._label(frame, "Sign-in password (encrypted with Windows DPAPI)")
        # Decrypt stored password for display
        from config_manager import decrypt_password
        decrypted = decrypt_password(self.cfg.get("forti_password_enc", ""))
        self._v_forti_pass = tk.StringVar(value=decrypted)
        e = tk.Entry(
            frame, textvariable=self._v_forti_pass, show="●",
            bg=SURFACE, fg=TEXT, insertbackground=TEXT,
            relief=tk.FLAT, font=("Segoe UI", 10),
            highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=C_CISCO
        )
        e.pack(fill=tk.X, ipady=5)

        self._label(frame, "FortiClient.exe path (leave blank to auto-detect)")
        self._v_forti_exe = self._entry(frame, "forti_exe_path")

        self._label(frame, "Custom connect command (optional — overrides launching the app)")
        self._v_forti_conn = self._entry(frame, "forti_connect_cmd")

        self._label(frame, 'Custom disconnect command (optional — e.g. rasdial "VPN Name" /disconnect)')
        self._v_forti_disc = self._entry(frame, "forti_disconnect_cmd")

        # ── BICE VPN (GlobalProtect) ──────────────────────────────────────────
        self._section(frame, "BICE VPN (GlobalProtect)")

        self._label(frame, "Username (e.g. akpadmanabhacharex@bice.cl)")
        self._v_gp_user = self._entry(frame, "gp_username")

        self._label(frame, "Password (encrypted with Windows DPAPI — optional)")
        decrypted_gp = decrypt_password(self.cfg.get("gp_password_enc", ""))
        self._v_gp_pass = tk.StringVar(value=decrypted_gp)
        e_gp = tk.Entry(
            frame, textvariable=self._v_gp_pass, show="●",
            bg=SURFACE, fg=TEXT, insertbackground=TEXT,
            relief=tk.FLAT, font=("Segoe UI", 10),
            highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=C_GP
        )
        e_gp.pack(fill=tk.X, ipady=5)

        self._label(frame, "Portal URL (default: ext.bice.cl)")
        self._v_gp_portal = self._entry(frame, "gp_portal_url")

        self._label(frame, "PanGPA.exe path (leave blank to auto-detect)")
        self._v_gp_exe = self._entry(frame, "gp_exe_path")

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


    def _save(self):
        from config_manager import encrypt_password
        forti_pass_plain = self._v_forti_pass.get()
        gp_pass_plain = self._v_gp_pass.get()
        self.cfg.update({
            "cisco_host": self._v_cisco_host.get().strip(),
            "cisco_username": self._v_cisco_user.get().strip(),
            "cisco_password": self._v_cisco_pass.get(),
            "cisco_cli_path": self._v_cisco_cli.get().strip(),
            "forti_exe_path": self._v_forti_exe.get().strip(),
            "forti_connect_cmd": self._v_forti_conn.get().strip(),
            "forti_disconnect_cmd": self._v_forti_disc.get().strip(),
            "forti_username": self._v_forti_user.get().strip(),
            "forti_password_enc": encrypt_password(forti_pass_plain) if forti_pass_plain else "",
            "gp_username": self._v_gp_user.get().strip(),
            "gp_password_enc": encrypt_password(gp_pass_plain) if gp_pass_plain else "",
            "gp_portal_url": self._v_gp_portal.get().strip() or "ext.bice.cl",
            "gp_exe_path": self._v_gp_exe.get().strip(),
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
        root.resizable(True, True)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self._hide)

        try:
            from PIL import ImageTk
            import tempfile, os
            logo = _load_logo()
            # Save as .ico for Windows taskbar (iconbitmap is more reliable than iconphoto)
            ico_path = os.path.join(tempfile.gettempdir(), "vpnswitcher.ico")
            logo.save(ico_path, format="ICO", sizes=[(256,256),(48,48),(32,32),(16,16)])
            root.iconbitmap(ico_path)
            # Also set iconphoto for the title bar
            logo32 = logo.resize((32, 32), Image.LANCZOS)
            self._tk_icon = ImageTk.PhotoImage(logo32)
            root.iconphoto(True, self._tk_icon)
        except Exception:
            pass

        # Use grid so every row is explicitly placed — no side=BOTTOM surprises
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=0)  # header
        root.rowconfigure(1, weight=0)  # status card
        root.rowconfigure(2, weight=0)  # buttons
        root.rowconfigure(3, weight=1)  # spacer
        root.rowconfigure(4, weight=0)  # update banner
        root.rowconfigure(5, weight=0)  # message
        root.rowconfigure(6, weight=0)  # settings bar

        # ── header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(root, bg=BG, pady=14)
        hdr.grid(row=0, column=0, sticky="ew")
        tk.Label(hdr, text="VPN Switcher", bg=BG, fg=TEXT,
                 font=("Segoe UI", 16, "bold")).pack()

        # ── status card ───────────────────────────────────────────────────────
        card = tk.Frame(root, bg=SURFACE, pady=12, padx=20,
                        highlightthickness=1, highlightbackground=BORDER)
        card.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 14))

        tk.Label(card, text="CURRENT STATUS", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 7, "bold")).pack()
        self._dot = tk.Label(card, text="●", bg=SURFACE, fg=C_NONE,
                             font=("Segoe UI", 16))
        self._dot.pack(pady=(2, 0))
        self._status_lbl = tk.Label(card, text="Checking…", bg=SURFACE, fg=TEXT,
                                    font=("Segoe UI", 11, "bold"))
        self._status_lbl.pack()

        # ── VPN buttons ───────────────────────────────────────────────────────
        btn_area = tk.Frame(root, bg=BG)
        btn_area.grid(row=2, column=0, sticky="ew", padx=20)

        self._btn_cisco = VPNButton(
            btn_area, "Oracle VPN (Cisco Secure Client)", C_CISCO, C_CISCO_HOVER,
            lambda: self._switch(CISCO)
        )
        self._btn_cisco.pack(fill=tk.X, pady=4)

        self._btn_forti = VPNButton(
            btn_area, "Falabella VPN (FortiClient)", C_FORTI, C_FORTI_HOVER,
            lambda: self._switch(FORTI)
        )
        self._btn_forti.pack(fill=tk.X, pady=4)

        self._btn_gp = VPNButton(
            btn_area, "BICE VPN (GlobalProtect)", C_GP, C_GP_HOVER,
            lambda: self._switch(GPROT)
        )
        self._btn_gp.pack(fill=tk.X, pady=4)

        self._btn_none = VPNButton(
            btn_area, "No VPN", C_NONE, C_NONE_HOVER,
            self._disconnect_all
        )
        self._btn_none.pack(fill=tk.X, pady=4)

        # ── FortiClient autofill toggle button ────────────────────────────────
        self._forti_panel_open = False
        self._forti_toggle_btn = tk.Button(
            btn_area, text="▶  FortiClient autofill",
            bg=SURFACE, fg=MUTED, relief=tk.FLAT,
            font=("Segoe UI", 8), pady=5, padx=10, anchor="w",
            command=self._toggle_forti_panel, cursor="hand2"
        )
        self._forti_toggle_btn.pack(fill=tk.X, pady=(4, 0))

        # ── Collapsible autofill panel (hidden by default) ────────────────────
        saved_mode  = self.config.get("forti_flow_mode", "detect")
        saved_steps = self.config.get("forti_flow_steps", ["username", "password", "mfa"])
        self._forti_mode_var     = tk.StringVar(value=saved_mode)
        self._forti_use_username = tk.BooleanVar(value="username" in saved_steps)
        self._forti_use_password = tk.BooleanVar(value="password" in saved_steps)
        self._forti_use_mfa      = tk.BooleanVar(value="mfa"      in saved_steps)

        self._forti_panel = tk.Frame(btn_area, bg=SURFACE, padx=12, pady=10)
        # (not packed — starts collapsed)

        # Auto-detect option
        auto_rb = tk.Radiobutton(
            self._forti_panel, text="Auto-detect",
            variable=self._forti_mode_var, value="detect",
            bg=SURFACE, fg=TEXT, selectcolor=BG, activebackground=SURFACE,
            font=("Segoe UI", 9, "bold"), command=self._on_forti_mode_change
        )
        auto_rb.pack(anchor="w")
        tk.Label(
            self._forti_panel,
            text="Reads each sign-in page and decides automatically\n"
                 "what to type: email, password or MFA.",
            bg=SURFACE, fg=MUTED, font=("Segoe UI", 7), justify="left"
        ).pack(anchor="w", padx=(22, 0), pady=(0, 8))

        # Custom flow option
        custom_rb = tk.Radiobutton(
            self._forti_panel, text="Custom flow",
            variable=self._forti_mode_var, value="custom",
            bg=SURFACE, fg=TEXT, selectcolor=BG, activebackground=SURFACE,
            font=("Segoe UI", 9, "bold"), command=self._on_forti_mode_change
        )
        custom_rb.pack(anchor="w")
        tk.Label(
            self._forti_panel,
            text="Is faster, You define which steps your FortiClient shows.\n"
                 "Uncheck steps that don't appear on your PC.",
            bg=SURFACE, fg=MUTED, font=("Segoe UI", 7), justify="left"
        ).pack(anchor="w", padx=(22, 0), pady=(0, 4))

        # Checkboxes (only visible in custom mode)
        self._forti_custom_row = tk.Frame(self._forti_panel, bg=SURFACE)

        def _chk(text, var):
            return tk.Checkbutton(
                self._forti_custom_row, text=text, variable=var,
                bg=SURFACE, fg=TEXT, selectcolor=BG, activebackground=SURFACE,
                font=("Segoe UI", 8), command=self._save_forti_flow
            )
        _chk("Email",    self._forti_use_username).pack(side=tk.LEFT)
        _chk("Password", self._forti_use_password).pack(side=tk.LEFT, padx=(8, 0))
        _chk("MFA",      self._forti_use_mfa     ).pack(side=tk.LEFT, padx=(8, 0))

        if saved_mode == "custom":
            self._forti_custom_row.pack(anchor="w", padx=(22, 0), pady=(0, 4))

        # ── spacer ────────────────────────────────────────────────────────────
        tk.Frame(root, bg=BG).grid(row=3, column=0)

        # ── update banner (hidden until an update is detected) ───────────────
        self._update_lbl = tk.Label(
            root, text="", bg=BG, fg=C_WARN,
            font=("Segoe UI", 8, "underline"), cursor="hand2"
        )
        self._update_lbl.grid(row=4, column=0, pady=(4, 0))
        self._update_lbl.bind("<Button-1>", self._install_update)

        # ── message area ──────────────────────────────────────────────────────
        self._msg_lbl = tk.Label(root, text="", bg=BG, fg=MUTED,
                                 font=("Segoe UI", 8), wraplength=290)
        self._msg_lbl.grid(row=5, column=0, pady=(2, 0), padx=20)

        # ── settings bar ──────────────────────────────────────────────────────
        bottom = tk.Frame(root, bg=BG, pady=10, padx=20)
        bottom.grid(row=6, column=0, sticky="ew")
        tk.Button(
            bottom, text="⚙  Settings",
            bg=SURFACE, fg=MUTED, relief=tk.FLAT,
            font=("Segoe UI", 9), pady=4, padx=10,
            command=self._open_settings, cursor="hand2"
        ).pack(side=tk.RIGHT)
        tk.Button(
            bottom, text="For Oracle  |  by Diego Pavez Verdi",
            bg=SURFACE, fg=MUTED, relief=tk.FLAT,
            font=("Segoe UI", 9), pady=4, padx=10,
            command=self._open_about, cursor="hand2"
        ).pack(side=tk.LEFT)

    def _center_window(self):
        # Let tkinter measure the real required size after all widgets are built
        self.root.update_idletasks()
        w = int(max(self.root.winfo_reqwidth(), 340) * 1.10)
        h = int(self.root.winfo_reqheight() * 1.10)
        self.root.minsize(w, h)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _open_about(self, *_):
        self.root.after(0, self.__open_about)

    def __open_about(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("About")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        pad = dict(bg=BG)
        tk.Label(dlg, text="Diego Pavez Verdi", bg=BG, fg=TEXT,
                 font=("Segoe UI", 11, "bold")).pack(pady=(20, 2), padx=24)
        tk.Label(dlg, text="IT Consultant", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(pady=(0, 10), padx=24)

        sep = tk.Frame(dlg, bg=BORDER, height=1)
        sep.pack(fill=tk.X, padx=20)

        links = [
            ("GitHub",          "https://github.com/dpv20"),
            ("Oracle mail",     "diego.pavez@oracle.com"),
            ("Personal mail",   "diego.pav3z@gmail.com"),
        ]
        for label, value in links:
            row = tk.Frame(dlg, bg=BG)
            row.pack(fill=tk.X, padx=24, pady=3)
            tk.Label(row, text=f"{label}:", bg=BG, fg=MUTED,
                     font=("Segoe UI", 8), width=12, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text=value, bg=BG, fg=TEXT,
                     font=("Segoe UI", 8), anchor="w").pack(side=tk.LEFT)

        tk.Button(dlg, text="Close", bg=SURFACE, fg=MUTED, relief=tk.FLAT,
                  font=("Segoe UI", 9), padx=16, pady=5,
                  command=dlg.destroy, cursor="hand2").pack(pady=(14, 18))

        dlg.update_idletasks()
        pw = self.root.winfo_rootx()
        ph = self.root.winfo_rooty()
        dw = dlg.winfo_reqwidth()
        dh = dlg.winfo_reqheight()
        x = pw + (self.root.winfo_width() - dw) // 2
        y = ph + (self.root.winfo_height() - dh) // 2
        dlg.geometry(f"+{x}+{y}")

    # ── tray ───────────────────────────────────────────────────────────────────

    def _build_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Open", self._show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Oracle VPN (Cisco)", lambda: self._switch(CISCO)),
            pystray.MenuItem("Falabella VPN (FortiClient)", lambda: self._switch(FORTI)),
            pystray.MenuItem("BICE VPN (GlobalProtect)", lambda: self._switch(GPROT)),
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

    def _update_window_icon(self, state: str):
        try:
            from PIL import ImageTk
            variant = "rojo" if state == CISCO else "verde" if state == FORTI else ""
            logo = _load_logo(variant).resize((32, 32), Image.LANCZOS)
            self._tk_icon = ImageTk.PhotoImage(logo)
            self.root.iconphoto(True, self._tk_icon)
        except Exception:
            pass

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
            dot_color, label = C_CISCO, "Oracle VPN (Cisco Secure Client)"
            self._btn_cisco.set_active(True)
            self._btn_forti.set_active(False)
            self._btn_gp.set_active(False)
            self._btn_none.set_active(False)
        elif s == FORTI:
            dot_color, label = C_FORTI, "Falabella VPN (FortiClient)"
            self._btn_cisco.set_active(False)
            self._btn_forti.set_active(True)
            self._btn_gp.set_active(False)
            self._btn_none.set_active(False)
        elif s == GPROT:
            dot_color, label = C_GP, "BICE VPN (GlobalProtect)"
            self._btn_cisco.set_active(False)
            self._btn_forti.set_active(False)
            self._btn_gp.set_active(True)
            self._btn_none.set_active(False)
        else:
            dot_color, label = C_NONE, "No VPN Connected"
            self._btn_cisco.set_active(False)
            self._btn_forti.set_active(False)
            self._btn_gp.set_active(False)
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
            import vpn_controller as _vc
            _vc._autofill_cancel.clear()
            self._set_busy(True)
            try:
                # Disconnect the other VPN first (VPNs are mutually exclusive)
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

                elif current == GPROT and target != GPROT:
                    self._msg("Disconnecting BICE VPN (GlobalProtect)…")
                    ok, msg = self.controller.disconnect_globalprotect()
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
                    if msg == "__WRONG_PASSWORD__":
                        self._msg("⚠  Contraseña incorrecta — actualízala en Settings.")
                        self.root.after(0, lambda: self._handle_wrong_password(target))
                        return
                elif target == GPROT:
                    self._msg("Connecting to BICE VPN (GlobalProtect)…")
                    ok, msg = self.controller.connect_globalprotect()
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
        # Topmost-toggle trick bypasses Windows' foreground-lock protection
        # (same dance used in _handle_wrong_password).
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.focus_force()
        self.root.update()
        self.root.attributes("-topmost", False)

    def _poll_show_flag(self):
        """Watch for the flag file dropped by a second-instance launch and bring
        the existing window to the front when it appears."""
        try:
            flag = os.path.join(
                os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                "VPNSwitcher",
                "show.flag",
            )
            if os.path.exists(flag):
                try:
                    os.remove(flag)
                except Exception:
                    pass
                self.__show()
        except Exception:
            pass
        self.root.after(400, self._poll_show_flag)

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

    def _handle_wrong_password(self, target: str):
        """Called on the main thread when FortiClient reports wrong credentials.
        Shows a warning, opens Settings, then retries — or cancels if user dismisses."""
        import vpn_controller as _vc
        self._set_busy(False)

        # Bring main window to front
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.focus_force()
        self.root.update()
        self.root.attributes("-topmost", False)

        answer = messagebox.askokcancel(
            "Credenciales incorrectas",
            "El usuario o contraseña guardados para FortiClient fueron rechazados.\n\n"
            "¿Deseas actualizar las credenciales en Settings y reintentar?",
            parent=self.root
        )
        if not answer:
            # User cancelled — stop autofill
            _vc._autofill_cancel.set()
            self._msg("Autofill cancelado.")
            return

        # Open settings
        dlg = SettingsDialog(self.root, self.config_manager)
        self.root.wait_window(dlg)

        # Reload config with updated credentials
        self.config = self.config_manager.load()
        self.controller.config = self.config

        # Small delay so Settings window fully disappears before we steal focus
        self.root.after(300, lambda: self._start_retry(target))

    def _start_retry(self, target: str):
        """Close the sign-in window and restart the full connect flow with
        the updated credentials saved in Settings."""
        import vpn_controller as _vc
        import ctypes
        _vc._autofill_cancel.clear()

        # Close the existing sign-in popup so FortiClient resets to Connect state
        sign_in_win = _vc._find_signin_window()
        if sign_in_win:
            ctypes.windll.user32.PostMessageW(sign_in_win.handle, 0x0010, 0, 0)  # WM_CLOSE
            time.sleep(1.5)

        # Hide main window so it doesn't compete for focus
        self.root.withdraw()

        def _retry():
            self._set_busy(True)
            try:
                # Reload config with the new credentials
                self.config = self.config_manager.load()
                self.controller.config = self.config

                self._msg("Reconectando con nuevas credenciales…")
                ok, msg = self.controller.connect_forti()
                if msg == "__WRONG_PASSWORD__":
                    self._msg("⚠  Contraseña incorrecta — actualízala en Settings.")
                    self.root.after(0, self.root.deiconify)
                    self.root.after(0, lambda: self._handle_wrong_password(target))
                    return

                self._msg(msg)
                # Poll until VPN connects or timeout (90 s for MFA approval)
                deadline = time.time() + 90
                while time.time() < deadline:
                    time.sleep(3)
                    new_status = self.controller.get_status()
                    if new_status != self._status:
                        self._status = new_status
                        self.root.after(0, self._refresh_ui)
                        self._update_tray_icon()
                        break
            finally:
                self._set_busy(False)
                self.root.after(0, self.root.deiconify)

        threading.Thread(target=_retry, daemon=True).start()

    # ── FortiClient flow mode ──────────────────────────────────────────────────

    def _toggle_forti_panel(self):
        self._forti_panel_open = not self._forti_panel_open
        if self._forti_panel_open:
            self._forti_panel.pack(fill=tk.X, pady=(2, 0))
            self._forti_toggle_btn.configure(text="▼  FortiClient autofill")
        else:
            self._forti_panel.pack_forget()
            self._forti_toggle_btn.configure(text="▶  FortiClient autofill")
        # Resize window to fit new content
        self.root.update_idletasks()
        h = int(self.root.winfo_reqheight() * 1.10)
        w = self.root.winfo_width()
        self.root.geometry(f"{w}x{h}")

    def _on_forti_mode_change(self):
        if self._forti_mode_var.get() == "custom":
            self._forti_custom_row.pack(anchor="w", padx=(22, 0), pady=(0, 4))
        else:
            self._forti_custom_row.pack_forget()
        self._save_forti_flow()

    def _save_forti_flow(self):
        steps = []
        if self._forti_use_username.get():
            steps.append("username")
        if self._forti_use_password.get():
            steps.append("password")
        if self._forti_use_mfa.get():
            steps.append("mfa")
        self.config["forti_flow_mode"]  = self._forti_mode_var.get()
        self.config["forti_flow_steps"] = steps
        self.config_manager.save(self.config)
        self.controller.config = self.config

    # ── auto-update check ──────────────────────────────────────────────────────

    def _check_for_update(self):
        """Background thread: compare installed version with origin/main via git."""
        try:
            import os
            import re
            import subprocess
            from version import __version__

            repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
            if not os.path.isdir(os.path.join(repo_dir, ".git")):
                return  # Not a git-based install — skip silently.

            git = self._find_git()
            if not git:
                return

            no_window = 0x08000000  # CREATE_NO_WINDOW

            subprocess.run(
                [git, "-C", repo_dir, "fetch", "origin", "main"],
                check=True, capture_output=True, timeout=20,
                creationflags=no_window,
            )

            result = subprocess.run(
                [git, "-C", repo_dir, "show", "origin/main:src/version.py"],
                check=True, capture_output=True, timeout=10,
                creationflags=no_window,
            )
            remote_src = result.stdout.decode("utf-8", errors="ignore")
            m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', remote_src)
            if not m:
                return
            latest = m.group(1)

            def _ver(v):
                return tuple(int(x) for x in v.split("."))

            if _ver(latest) > _ver(__version__):
                self.root.after(0, lambda: self._update_lbl.configure(
                    text=f"⬆  Update available v{latest} — click to install"
                ))
        except Exception:
            pass  # Network/git issue — silently ignore

    @staticmethod
    def _find_git():
        """Return a usable git.exe path, or None if git isn't available."""
        import os
        import shutil
        found = shutil.which("git")
        if found:
            return found
        for candidate in (
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe"),
            os.path.expandvars(r"%ProgramFiles%\Git\cmd\git.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Git\cmd\git.exe"),
        ):
            if os.path.isfile(candidate):
                return candidate
        return None

    def _install_update(self, *_):
        """Launch update.bat and exit so git can replace files."""
        import os
        import subprocess
        import webbrowser

        repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        updater = os.path.join(repo_dir, "update.bat")
        if not os.path.isfile(updater):
            # Fallback to manual download page for non-git installs.
            webbrowser.open("https://github.com/dpv20/oracle_vpn/releases/latest")
            return

        pythonw = sys.executable
        if pythonw.lower().endswith("python.exe"):
            candidate = pythonw[:-len("python.exe")] + "pythonw.exe"
            if os.path.isfile(candidate):
                pythonw = candidate

        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", updater, pythonw],
                cwd=repo_dir,
                creationflags=0x00000010,  # CREATE_NEW_CONSOLE
            )
        except Exception:
            return
        self.root.after(100, lambda: self.root.destroy())
        sys.exit(0)

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

        # Check for updates in background (5 s delay so UI is ready first)
        def _delayed_update_check():
            time.sleep(5)
            self._check_for_update()
        threading.Thread(target=_delayed_update_check, daemon=True).start()

        # Show window, then enter main loop
        self._center_window()
        self.root.deiconify()

        # Watch for second-instance launches that want us to come to the front
        self.root.after(400, self._poll_show_flag)

        # Initial status
        def _init_status():
            s = self.controller.get_status()
            self._status = s
            self._refresh_ui()
        threading.Thread(target=_init_status, daemon=True).start()

        self.root.mainloop()
