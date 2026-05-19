"""
ui.py — system tray icon + main window + settings dialog.
All tkinter work happens on the main thread; pystray runs detached.
"""
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import pystray
from PIL import Image, ImageDraw

from vpn_controller import CISCO, FORTI, GPROT, NONE, VPNController
from config_manager import ConfigManager
from utils import asset_path
from theme import get_theme
import session_manager
from logger import get_logger


WHITE = "#ffffff"


def _mix_hex(a: str, b: str, t: float) -> str:
    """Linear blend between two #rrggbb colors. t=0 → a, t=1 → b."""
    ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    r = int(ar + (br - ar) * t)
    g = int(ag + (bg - ag) * t)
    bl = int(ab + (bb - ab) * t)
    return f"#{r:02x}{g:02x}{bl:02x}"


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
        bg = (220, 38, 38, 255)
    elif state == FORTI:
        bg = (22, 163, 74, 255)
    elif state == GPROT:
        bg = (37, 99, 235, 255)
    else:
        bg = (80, 80, 110, 255)

    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=14, fill=bg)
    d.rounded_rectangle([20, 32, 44, 52], radius=4, fill=(255, 255, 255, 230))
    d.arc([18, 14, 46, 40], start=0, end=180, fill=(255, 255, 255, 230), width=5)
    d.ellipse([29, 38, 35, 44], fill=bg)

    return img


# ── theme toggle (slide switch with sun/moon) ──────────────────────────────────

class ThemeToggle(tk.Canvas):
    """A pill-shaped slide switch with a sun on the left and a moon on the
    right. Clicking anywhere on the widget calls on_toggle, which is expected
    to flip the theme_mode in config and rebuild the main window."""

    W = 58
    H = 26
    PAD = 3   # gap between knob edge and pill edge

    def __init__(self, parent, T, mode, on_toggle):
        super().__init__(
            parent, width=self.W, height=self.H,
            bg=T["bg"], highlightthickness=0, bd=0, cursor="hand2",
        )
        self._T = T
        self._mode = mode
        self._on_toggle = on_toggle
        self._draw()
        self.bind("<Button-1>", lambda _e: self._on_toggle())

    def _draw(self):
        T = self._T
        W, H, PAD = self.W, self.H, self.PAD
        r = H // 2

        # Pill track (smooth polygon approximating a rounded rect)
        pts = [
            r,     0,     W - r, 0,
            W,     0,     W,     r,
            W,     H - r, W,     H,
            W - r, H,     r,     H,
            0,     H,     0,     H - r,
            0,     r,     0,     0,
        ]
        self.create_polygon(
            pts, smooth=True, splinesteps=24,
            fill=T["surface_hi"], outline=T["border"], width=1,
        )

        # Sun / moon glyphs at each end. The side opposite the knob is the
        # one you'd land on if you toggled, so we highlight it.
        sun_color  = T["text"] if self._mode == "light" else T["text_dim"]
        moon_color = T["text"] if self._mode == "dark"  else T["text_dim"]
        self.create_text(r,     H // 2, text="☀", fill=sun_color,
                         font=("Segoe UI", 11))
        self.create_text(W - r, H // 2, text="☾", fill=moon_color,
                         font=("Segoe UI", 11))

        # Knob — circle that lives flush against the active side.
        knob_r = (H - PAD * 2) // 2
        knob_cy = H // 2
        knob_cx = (r if self._mode == "light" else W - r)
        # Subtle shadow ring
        self.create_oval(
            knob_cx - knob_r - 1, knob_cy - knob_r - 1,
            knob_cx + knob_r + 1, knob_cy + knob_r + 1,
            fill=T["border"], outline="",
        )
        self.create_oval(
            knob_cx - knob_r, knob_cy - knob_r,
            knob_cx + knob_r, knob_cy + knob_r,
            fill=T["text"], outline="",
        )


# ── VPN card (grid tile) ───────────────────────────────────────────────────────

class VPNCard(tk.Frame):
    """A card-style button used in the 2x2 grid on the main window.

    The card itself stays on the surface color; the accent color (Oracle red,
    Falabella green, etc.) is shown only as a small colored dot on the top-left.
    When active (the VPN is connected), the card gets a thicker accent border.
    """

    # Constant border thickness — toggling active changes only the color,
    # so the card never grows/shrinks. Visually that reads as the border
    # "thickening inward" because nothing around it moves.
    BORDER_PX = 3

    def __init__(self, parent, T, title, subtitle, accent, command):
        super().__init__(
            parent,
            bg=T["surface"],
            highlightthickness=self.BORDER_PX,
            highlightbackground=T["border"],
            highlightcolor=T["border"],
            cursor="hand2",
        )
        self._T = T
        self._accent = accent
        self._cmd = command
        self._active = False

        inner = tk.Frame(self, bg=T["surface"], padx=14, pady=12)
        inner.pack(fill=tk.BOTH, expand=True)
        self._inner = inner

        # Top row: accent dot only (status is rendered in the hero).
        self._dot = tk.Label(
            inner, text="●", bg=T["surface"], fg=accent,
            font=("Segoe UI", 14)
        )
        self._dot.pack(anchor="w")

        self._title = tk.Label(
            inner, text=title,
            bg=T["surface"], fg=T["text"],
            font=("Segoe UI Semibold", 10), anchor="w", justify="left",
        )
        self._title.pack(anchor="w", fill=tk.X, pady=(6, 0))

        self._sub = tk.Label(
            inner, text=subtitle or "",
            bg=T["surface"], fg=T["text_muted"],
            font=("Segoe UI", 8), anchor="w", justify="left",
        )
        self._sub.pack(anchor="w", fill=tk.X)

        self._bound = [self, self._inner, self._dot, self._title, self._sub]
        for w in self._bound:
            w.bind("<Button-1>", lambda _e: self._cmd())
            w.bind("<Enter>",    lambda _e: self._hover(True))
            w.bind("<Leave>",    lambda _e: self._hover(False))

        # Apply the dimmed-idle palette on construction.
        self.set_active(False)

    def _hover(self, on: bool):
        bg = self._T["surface_hi"] if on else self._T["surface"]
        for w in self._bound:
            w.configure(bg=bg)

    def set_active(self, active: bool):
        self._active = active
        T = self._T
        if active:
            self.configure(
                highlightbackground=self._accent,
                highlightcolor=self._accent,
            )
            self._dot.configure(fg=self._accent)
            self._title.configure(fg=T["text"])
            self._sub.configure(fg=T["text_muted"])
        else:
            self.configure(
                highlightbackground=T["border"],
                highlightcolor=T["border"],
            )
            # Fade the brand dot toward the surface so the accent stays
            # recognizable but takes a clear back seat to the active card.
            self._dot.configure(fg=_mix_hex(self._accent, T["surface"], 0.55))
            self._title.configure(fg=T["text_dim"])
            self._sub.configure(fg=T["text_dim"])


# ── settings dialog ────────────────────────────────────────────────────────────

class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, config_manager: ConfigManager, T: dict):
        super().__init__(parent)
        self.config_manager = config_manager
        self.cfg = config_manager.load()
        self._T = T

        self.title("VPN Switcher — Settings")
        self.geometry("560x660")
        self.minsize(480, 560)
        self.resizable(True, True)
        self.configure(bg=T["bg"])
        self.transient(parent)
        self.grab_set()

        self._build()
        self._center()

    def _center(self):
        self.update_idletasks()
        pw = self.master.winfo_rootx()
        ph = self.master.winfo_rooty()
        x = pw + (self.master.winfo_width() - 560) // 2
        y = ph + (self.master.winfo_height() - 660) // 2
        self.geometry(f"560x660+{x}+{y}")

    # ── helpers ────────────────────────────────────────────────────────────────

    def _label(self, parent, text):
        T = self._T
        tk.Label(parent, text=text, bg=T["bg"], fg=T["text_muted"],
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(10, 2))

    def _entry(self, parent, key, show=""):
        T = self._T
        var = tk.StringVar(value=self.cfg.get(key, ""))
        e = tk.Entry(
            parent, textvariable=var, show=show,
            bg=T["surface"], fg=T["text"], insertbackground=T["text"],
            relief=tk.FLAT, font=("Segoe UI", 10),
            highlightthickness=1, highlightbackground=T["border"],
            highlightcolor=T["accent"],
        )
        e.pack(fill=tk.X, ipady=6)
        return var

    def _section(self, parent, title):
        T = self._T
        tk.Label(parent, text=title.upper(), bg=T["bg"], fg=T["text_muted"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(18, 4))
        tk.Frame(parent, bg=T["border"], height=1).pack(fill=tk.X, pady=(0, 6))

    def _password_entry(self, parent, value):
        T = self._T
        var = tk.StringVar(value=value)
        e = tk.Entry(
            parent, textvariable=var, show="●",
            bg=T["surface"], fg=T["text"], insertbackground=T["text"],
            relief=tk.FLAT, font=("Segoe UI", 10),
            highlightthickness=1, highlightbackground=T["border"],
            highlightcolor=T["accent"],
        )
        e.pack(fill=tk.X, ipady=6)
        return var

    # ── build ──────────────────────────────────────────────────────────────────

    def _build(self):
        T = self._T

        # Bottom button bar (anchored before notebook so it never gets hidden)
        btn_frame = tk.Frame(self, bg=T["bg"], pady=14, padx=22)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X)

        tk.Button(
            btn_frame, text="Cancel",
            bg=T["surface"], fg=T["text_muted"], relief=tk.FLAT,
            font=("Segoe UI", 10), padx=18, pady=7,
            command=self.destroy, cursor="hand2",
            activebackground=T["surface_hi"], activeforeground=T["text"],
        ).pack(side=tk.RIGHT, padx=(8, 0))

        tk.Button(
            btn_frame, text="  Save  ",
            bg=T["accent"], fg=WHITE, relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"), padx=18, pady=7,
            command=self._save, cursor="hand2",
            activebackground=T["accent_hover"], activeforeground=WHITE,
        ).pack(side=tk.RIGHT)

        tk.Frame(self, bg=T["border"], height=1).pack(side=tk.BOTTOM, fill=tk.X)

        # ttk Notebook styling (per-theme)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("VPN.TNotebook", background=T["bg"], borderwidth=0)
        style.configure(
            "VPN.TNotebook.Tab",
            background=T["surface"], foreground=T["text_muted"],
            padding=(16, 8), font=("Segoe UI", 9, "bold"),
            borderwidth=0,
        )
        style.map(
            "VPN.TNotebook.Tab",
            background=[("selected", T["bg"]), ("active", T["surface_hi"])],
            foreground=[("selected", T["text"]), ("active", T["text"])],
        )

        nb = ttk.Notebook(self, style="VPN.TNotebook")
        nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=14, pady=(14, 6))

        tab_gen    = self._new_tab(nb, "Switcher")
        tab_forti  = self._new_tab(nb, "Falabella")
        tab_oracle = self._new_tab(nb, "Oracle")
        tab_gp     = self._new_tab(nb, "BICE")

        self._build_general_tab(tab_gen)
        self._build_forti_tab(tab_forti)
        self._build_oracle_tab(tab_oracle)
        self._build_gp_tab(tab_gp)

    def _new_tab(self, notebook, title):
        T = self._T
        outer = tk.Frame(notebook, bg=T["bg"])
        notebook.add(outer, text=title)

        canvas = tk.Canvas(outer, bg=T["bg"], highlightthickness=0)
        sb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=T["bg"], padx=22, pady=6)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_resize(e):
            canvas.itemconfig(win_id, width=e.width)
        canvas.bind("<Configure>", _on_resize)

        def _on_frame_resize(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_frame_resize)

        def _on_mousewheel(e):
            try:
                canvas.yview_scroll(-1 * (e.delta // 120), "units")
            except Exception:
                pass
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        return inner

    # ── tabs ───────────────────────────────────────────────────────────────────

    def _build_oracle_tab(self, frame):
        self._section(frame, "Cisco Secure Client")

        self._label(frame, "VPN Host (e.g. vpn.company.com)")
        self._v_cisco_host = self._entry(frame, "cisco_host")

        self._label(frame, "Username (leave blank to be prompted by Cisco)")
        self._v_cisco_user = self._entry(frame, "cisco_username")

        self._label(frame, "Password (stored in plain text — leave blank to be prompted)")
        self._v_cisco_pass = self._entry(frame, "cisco_password", show="●")

        self._label(frame, "vpncli.exe path (leave blank to auto-detect)")
        self._v_cisco_cli = self._entry(frame, "cisco_cli_path")

    def _build_forti_tab(self, frame):
        from config_manager import decrypt_password
        T = self._T

        self._section(frame, "FortiClient VPN")

        self._label(frame, "Sign-in email (auto-filled in the login popup)")
        self._v_forti_user = self._entry(frame, "forti_username")

        self._label(frame, "Sign-in password (encrypted with Windows DPAPI)")
        self._v_forti_pass = self._password_entry(
            frame, decrypt_password(self.cfg.get("forti_password_enc", ""))
        )

        self._label(frame, "FortiClient.exe path (leave blank to auto-detect)")
        self._v_forti_exe = self._entry(frame, "forti_exe_path")

        self._label(frame, "Custom connect command (optional — overrides launching the app)")
        self._v_forti_conn = self._entry(frame, "forti_connect_cmd")

        self._label(frame, 'Custom disconnect command (optional — e.g. rasdial "VPN Name" /disconnect)')
        self._v_forti_disc = self._entry(frame, "forti_disconnect_cmd")

        # ── Autofill flow ───────────────────────────────────────────────────
        self._section(frame, "Autofill")

        saved_mode  = self.cfg.get("forti_flow_mode", "detect")
        saved_steps = self.cfg.get("forti_flow_steps", ["username", "password", "mfa"])
        self._v_forti_mode = tk.StringVar(value=saved_mode)
        self._v_forti_step_username = tk.BooleanVar(value="username" in saved_steps)
        self._v_forti_step_password = tk.BooleanVar(value="password" in saved_steps)
        self._v_forti_step_mfa      = tk.BooleanVar(value="mfa"      in saved_steps)

        tk.Radiobutton(
            frame, text="Auto-detect",
            variable=self._v_forti_mode, value="detect",
            bg=T["bg"], fg=T["text"], selectcolor=T["surface"],
            activebackground=T["bg"],
            font=("Segoe UI", 9, "bold"), command=self._on_forti_mode_change
        ).pack(anchor="w", pady=(6, 0))
        tk.Label(
            frame,
            text="Reads each sign-in page and decides automatically\n"
                 "what to type: email, password or MFA.",
            bg=T["bg"], fg=T["text_muted"], font=("Segoe UI", 7), justify="left"
        ).pack(anchor="w", padx=(22, 0), pady=(0, 8))

        tk.Radiobutton(
            frame, text="Custom flow",
            variable=self._v_forti_mode, value="custom",
            bg=T["bg"], fg=T["text"], selectcolor=T["surface"],
            activebackground=T["bg"],
            font=("Segoe UI", 9, "bold"), command=self._on_forti_mode_change
        ).pack(anchor="w")
        tk.Label(
            frame,
            text="Faster. You define which steps your FortiClient shows.\n"
                 "Uncheck steps that don't appear on your PC.",
            bg=T["bg"], fg=T["text_muted"], font=("Segoe UI", 7), justify="left"
        ).pack(anchor="w", padx=(22, 0), pady=(0, 4))

        self._forti_custom_row = tk.Frame(frame, bg=T["bg"])

        def _chk(text, var):
            return tk.Checkbutton(
                self._forti_custom_row, text=text, variable=var,
                bg=T["bg"], fg=T["text"], selectcolor=T["surface"],
                activebackground=T["bg"],
                font=("Segoe UI", 9)
            )
        _chk("Email",    self._v_forti_step_username).pack(side=tk.LEFT)
        _chk("Password", self._v_forti_step_password).pack(side=tk.LEFT, padx=(10, 0))
        _chk("MFA",      self._v_forti_step_mfa     ).pack(side=tk.LEFT, padx=(10, 0))

        if saved_mode == "custom":
            self._forti_custom_row.pack(anchor="w", padx=(22, 0), pady=(0, 6))

    def _build_gp_tab(self, frame):
        from config_manager import decrypt_password

        self._section(frame, "BICE VPN (GlobalProtect)")

        self._label(frame, "Username (e.g. akpadmanabhacharex@bice.cl)")
        self._v_gp_user = self._entry(frame, "gp_username")

        self._label(frame, "Password (encrypted with Windows DPAPI — optional)")
        self._v_gp_pass = self._password_entry(
            frame, decrypt_password(self.cfg.get("gp_password_enc", ""))
        )

        self._label(frame, "Portal URL (default: ext.bice.cl)")
        self._v_gp_portal = self._entry(frame, "gp_portal_url")

        self._label(frame, "PanGPA.exe path (leave blank to auto-detect)")
        self._v_gp_exe = self._entry(frame, "gp_exe_path")

    def _build_general_tab(self, frame):
        T = self._T

        # ── Appearance (theme toggle) ─────────────────────────────────────
        self._section(frame, "Appearance")

        self._v_theme = tk.StringVar(value=self.cfg.get("theme_mode", "dark"))
        theme_row = tk.Frame(frame, bg=T["bg"])
        theme_row.pack(anchor="w", pady=(2, 6))
        tk.Radiobutton(
            theme_row, text="Dark",
            variable=self._v_theme, value="dark",
            bg=T["bg"], fg=T["text"], selectcolor=T["surface"],
            activebackground=T["bg"], font=("Segoe UI", 10)
        ).pack(side=tk.LEFT)
        tk.Radiobutton(
            theme_row, text="Light",
            variable=self._v_theme, value="light",
            bg=T["bg"], fg=T["text"], selectcolor=T["surface"],
            activebackground=T["bg"], font=("Segoe UI", 10)
        ).pack(side=tk.LEFT, padx=(16, 0))
        tk.Label(
            frame, text="The whole app re-skins as soon as you save.",
            bg=T["bg"], fg=T["text_muted"], font=("Segoe UI", 8)
        ).pack(anchor="w", pady=(0, 4))

        # ── Startup ────────────────────────────────────────────────────────
        self._section(frame, "Startup")

        self._v_startup = tk.BooleanVar(value=self.cfg.get("start_with_windows", True))
        tk.Checkbutton(
            frame, text="Start VPN Switcher with Windows",
            variable=self._v_startup,
            bg=T["bg"], fg=T["text"], selectcolor=T["surface"],
            activebackground=T["bg"], activeforeground=T["text"],
            font=("Segoe UI", 10)
        ).pack(anchor="w", pady=(4, 2))

        # ── Show in main window ───────────────────────────────────────────
        self._section(frame, "Show in main window")

        self._v_show_forti = tk.BooleanVar(value=self.cfg.get("show_forti", True))
        tk.Checkbutton(
            frame, text="Show Falabella VPN (FortiClient) tile",
            variable=self._v_show_forti,
            bg=T["bg"], fg=T["text"], selectcolor=T["surface"],
            activebackground=T["bg"], activeforeground=T["text"],
            font=("Segoe UI", 10)
        ).pack(anchor="w", pady=(4, 2))

        self._v_show_gp = tk.BooleanVar(value=self.cfg.get("show_gp", True))
        tk.Checkbutton(
            frame, text="Show BICE VPN (GlobalProtect) tile",
            variable=self._v_show_gp,
            bg=T["bg"], fg=T["text"], selectcolor=T["surface"],
            activebackground=T["bg"], activeforeground=T["text"],
            font=("Segoe UI", 10)
        ).pack(anchor="w", pady=(2, 4))

        # ── Diagnostics ────────────────────────────────────────────────────
        self._section(frame, "Diagnostics")

        tk.Label(
            frame,
            text="Export the diagnostic log to send it for support, "
                 "or clear it before reproducing an issue.",
            bg=T["bg"], fg=T["text_muted"], font=("Segoe UI", 8)
        ).pack(anchor="w", pady=(4, 4))

        log_row = tk.Frame(frame, bg=T["bg"])
        log_row.pack(anchor="w", pady=(0, 8))
        tk.Button(
            log_row, text="💾  Save log to file…",
            bg=T["surface"], fg=T["text"], relief=tk.FLAT,
            font=("Segoe UI", 9), padx=14, pady=7,
            command=self._save_log, cursor="hand2",
            activebackground=T["surface_hi"], activeforeground=T["text"],
        ).pack(side=tk.LEFT)
        tk.Button(
            log_row, text="🗑  Limpiar logs",
            bg=T["surface"], fg=T["text"], relief=tk.FLAT,
            font=("Segoe UI", 9), padx=14, pady=7,
            command=self._clear_log, cursor="hand2",
            activebackground=T["surface_hi"], activeforeground=T["text"],
        ).pack(side=tk.LEFT, padx=(8, 0))

        # ── About ──────────────────────────────────────────────────────────
        self._section(frame, "About")

        try:
            from version import __version__ as _ver
        except Exception:
            _ver = "?"
        tk.Label(
            frame, text=f"VPN Switcher v{_ver}",
            bg=T["bg"], fg=T["text"], font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", pady=(4, 0))
        tk.Label(
            frame, text="github.com/dpv20/oracle_vpn",
            bg=T["bg"], fg=T["text_muted"], font=("Segoe UI", 8)
        ).pack(anchor="w", pady=(0, 8))

    def _on_forti_mode_change(self):
        if self._v_forti_mode.get() == "custom":
            self._forti_custom_row.pack(anchor="w", padx=(22, 0), pady=(0, 6))
        else:
            self._forti_custom_row.pack_forget()

    def _save_log(self):
        import shutil
        from datetime import datetime
        from logger import LOG_FILE

        if not os.path.exists(LOG_FILE):
            messagebox.showwarning(
                "No log yet",
                f"No log file found at:\n{LOG_FILE}\n\n"
                "Try connecting to a VPN first — that produces log entries.",
                parent=self
            )
            return

        default_name = f"vpnswitcher-{datetime.now():%Y%m%d-%H%M%S}.log"
        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Save log as…",
            defaultextension=".log",
            initialfile=default_name,
            filetypes=[("Log files", "*.log"), ("All files", "*.*")],
        )
        if not dest:
            return
        try:
            shutil.copy2(LOG_FILE, dest)
            messagebox.showinfo("Log saved", f"Saved to:\n{dest}", parent=self)
        except Exception as e:
            messagebox.showerror("Could not save log", f"{e}", parent=self)

    def _clear_log(self):
        """Truncate the active log file. The logger keeps its open handle —
        new entries land in the now-empty file without needing a restart."""
        from logger import LOG_FILE, get_logger

        if not os.path.exists(LOG_FILE):
            messagebox.showinfo(
                "Nada que limpiar",
                f"No hay log todavía en:\n{LOG_FILE}",
                parent=self,
            )
            return

        if not messagebox.askokcancel(
            "Limpiar logs",
            "Esto va a borrar todo el contenido del archivo de log.\n"
            "Útil antes de reproducir un problema para que el log nuevo "
            "salga limpio.\n\n¿Continuar?",
            parent=self,
        ):
            return

        try:
            with open(LOG_FILE, "w", encoding="utf-8"):
                pass
            get_logger().info("log cleared from Settings → Limpiar logs")
            messagebox.showinfo(
                "Log limpio",
                "El archivo de log fue vaciado.",
                parent=self,
            )
        except Exception as e:
            messagebox.showerror("No se pudo limpiar el log", f"{e}", parent=self)

    def _save(self):
        from config_manager import encrypt_password
        forti_pass_plain = self._v_forti_pass.get()
        gp_pass_plain = self._v_gp_pass.get()

        forti_steps = []
        if self._v_forti_step_username.get():
            forti_steps.append("username")
        if self._v_forti_step_password.get():
            forti_steps.append("password")
        if self._v_forti_step_mfa.get():
            forti_steps.append("mfa")

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
            "forti_flow_mode": self._v_forti_mode.get(),
            "forti_flow_steps": forti_steps,
            "gp_username": self._v_gp_user.get().strip(),
            "gp_password_enc": encrypt_password(gp_pass_plain) if gp_pass_plain else "",
            "gp_portal_url": self._v_gp_portal.get().strip() or "ext.bice.cl",
            "gp_exe_path": self._v_gp_exe.get().strip(),
            "start_with_windows": self._v_startup.get(),
            "show_forti": self._v_show_forti.get(),
            "show_gp": self._v_show_gp.get(),
            "theme_mode": self._v_theme.get(),
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
        self._T = get_theme(self.config.get("theme_mode", "dark"))

        self._status = NONE
        self._busy = False
        self._tray = None  # type: pystray.Icon

        self.root = tk.Tk()
        self.root.withdraw()
        self._apply_root_chrome()
        self._build_window()

    # ── window ─────────────────────────────────────────────────────────────────

    def _apply_root_chrome(self):
        T = self._T
        self.root.title("VPN Switcher")
        self.root.resizable(True, True)
        self.root.configure(bg=T["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._hide)

        try:
            from PIL import ImageTk
            import tempfile
            logo = _load_logo()
            ico_path = os.path.join(tempfile.gettempdir(), "vpnswitcher.ico")
            logo.save(ico_path, format="ICO", sizes=[(256, 256), (48, 48), (32, 32), (16, 16)])
            self.root.iconbitmap(ico_path)
            logo32 = logo.resize((32, 32), Image.LANCZOS)
            self._tk_icon = ImageTk.PhotoImage(logo32)
            self.root.iconphoto(True, self._tk_icon)
        except Exception:
            pass

    def _build_window(self):
        T = self._T
        root = self.root

        # 3 columns so the grid lays out as 2 columns + scrollbar-less gutter.
        root.columnconfigure(0, weight=1)

        # ── header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(root, bg=T["bg"], pady=14)
        hdr.grid(row=0, column=0, sticky="ew", padx=22)
        tk.Label(hdr, text="VPN Switcher", bg=T["bg"], fg=T["text"],
                 font=("Segoe UI Semibold", 16)).pack(side=tk.LEFT)
        ThemeToggle(hdr, T, T["name"], self._toggle_theme).pack(side=tk.RIGHT)

        # ── status hero ───────────────────────────────────────────────────────
        hero = tk.Frame(
            root, bg=T["surface"], padx=22, pady=20,
            highlightthickness=1, highlightbackground=T["border"],
        )
        hero.grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 18))
        hero.columnconfigure(1, weight=1)

        self._dot = tk.Label(
            hero, text="●", bg=T["surface"], fg=T["text_dim"],
            font=("Segoe UI", 28),
        )
        self._dot.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 16))

        self._status_lbl = tk.Label(
            hero, text="Checking…", bg=T["surface"], fg=T["text"],
            font=("Segoe UI Semibold", 14), anchor="w",
        )
        self._status_lbl.grid(row=0, column=1, sticky="ew")

        self._status_sub = tk.Label(
            hero, text="", bg=T["surface"], fg=T["text_muted"],
            font=("Segoe UI", 9), anchor="w",
        )
        self._status_sub.grid(row=1, column=1, sticky="ew")

        # ── VPN cards (2x2 grid) ──────────────────────────────────────────────
        self._grid = tk.Frame(root, bg=T["bg"])
        self._grid.grid(row=2, column=0, sticky="ew", padx=22)
        self._grid.columnconfigure(0, weight=1, uniform="cards")
        self._grid.columnconfigure(1, weight=1, uniform="cards")

        self._card_cisco = VPNCard(
            self._grid, T,
            title="Oracle", subtitle="Cisco Secure Client",
            accent=T["cisco"], command=lambda: self._switch(CISCO),
        )
        self._card_forti = VPNCard(
            self._grid, T,
            title="Falabella", subtitle="FortiClient",
            accent=T["forti"], command=lambda: self._switch(FORTI),
        )
        self._card_gp = VPNCard(
            self._grid, T,
            title="BICE", subtitle="GlobalProtect",
            accent=T["gp"], command=lambda: self._switch(GPROT),
        )
        self._card_none = VPNCard(
            self._grid, T,
            title="No VPN", subtitle="Disconnect everything",
            accent=T["none_btn"], command=self._disconnect_all,
        )

        self._apply_card_visibility()

        # ── update banner (hidden until detected) ────────────────────────────
        self._update_lbl = tk.Label(
            root, text="", bg=T["bg"], fg=T["warn"],
            font=("Segoe UI", 8, "underline"), cursor="hand2",
        )
        self._update_lbl.grid(row=4, column=0, pady=(14, 0))
        self._update_lbl.bind("<Button-1>", self._install_update)

        # ── message line ─────────────────────────────────────────────────────
        self._msg_lbl = tk.Label(
            root, text="", bg=T["bg"], fg=T["text_muted"],
            font=("Segoe UI", 8), wraplength=420,
        )
        self._msg_lbl.grid(row=5, column=0, pady=(4, 0), padx=22)

        # ── bottom bar (about + settings) ────────────────────────────────────
        bottom = tk.Frame(root, bg=T["bg"], pady=14, padx=22)
        bottom.grid(row=6, column=0, sticky="ew")
        tk.Button(
            bottom, text="⚙  Settings",
            bg=T["surface"], fg=T["text"], relief=tk.FLAT,
            font=("Segoe UI", 9), pady=6, padx=14,
            command=self._open_settings, cursor="hand2",
            activebackground=T["surface_hi"], activeforeground=T["text"],
        ).pack(side=tk.RIGHT)
        tk.Button(
            bottom, text="by Diego Pavez Verdi",
            bg=T["bg"], fg=T["text_muted"], relief=tk.FLAT,
            font=("Segoe UI", 9), pady=6, padx=4,
            command=self._open_about, cursor="hand2",
            activebackground=T["bg"], activeforeground=T["text"],
        ).pack(side=tk.LEFT)

        root.rowconfigure(3, weight=1)

    def _toggle_theme(self):
        """Flip dark <-> light, persist, and rebuild the main window."""
        new_mode = "light" if self._T["name"] == "dark" else "dark"
        self.config["theme_mode"] = new_mode
        self.config_manager.save(self.config)
        self._rebuild_main()

    def _rebuild_main(self):
        """Tear down and rebuild the main window so a theme change takes effect."""
        for w in self.root.winfo_children():
            w.destroy()
        self._T = get_theme(self.config.get("theme_mode", "dark"))
        self._apply_root_chrome()
        self._build_window()
        # Re-render the current status into the new widgets.
        self._refresh_ui()

    def _center_window(self):
        self.root.update_idletasks()
        w = int(max(self.root.winfo_reqwidth(), 420) * 1.05)
        h = int(self.root.winfo_reqheight() * 1.05)
        self.root.minsize(w, h)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ── about dialog ───────────────────────────────────────────────────────────

    def _open_about(self, *_):
        self.root.after(0, self.__open_about)

    def __open_about(self):
        T = self._T
        dlg = tk.Toplevel(self.root)
        dlg.title("About")
        dlg.configure(bg=T["bg"])
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        try:
            from version import __version__ as _ver
        except Exception:
            _ver = "?"

        outer = tk.Frame(dlg, bg=T["bg"], padx=28, pady=22)
        outer.pack(fill=tk.BOTH, expand=True)

        tk.Label(outer, text="VPN Switcher", bg=T["bg"], fg=T["text"],
                 font=("Segoe UI Semibold", 14)).pack(anchor="w")
        tk.Label(outer, text=f"version {_ver}", bg=T["bg"], fg=T["text_muted"],
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 14))

        tk.Frame(outer, bg=T["border"], height=1).pack(fill=tk.X)

        tk.Label(outer, text="Diego Pavez Verdi", bg=T["bg"], fg=T["text"],
                 font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(12, 0))
        tk.Label(outer, text="IT Consultant — Oracle", bg=T["bg"], fg=T["text_muted"],
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 10))

        for label, value in [
            ("GitHub",        "github.com/dpv20"),
            ("Oracle mail",   "diego.pavez@oracle.com"),
            ("Personal mail", "diego.pav3z@gmail.com"),
        ]:
            row = tk.Frame(outer, bg=T["bg"])
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=f"{label}:", bg=T["bg"], fg=T["text_muted"],
                     font=("Segoe UI", 9), width=14, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text=value, bg=T["bg"], fg=T["text"],
                     font=("Segoe UI", 9), anchor="w").pack(side=tk.LEFT)

        tk.Button(
            outer, text="Close",
            bg=T["surface"], fg=T["text"], relief=tk.FLAT,
            font=("Segoe UI", 9), padx=20, pady=6,
            command=dlg.destroy, cursor="hand2",
            activebackground=T["surface_hi"], activeforeground=T["text"],
        ).pack(anchor="e", pady=(18, 0))

        dlg.update_idletasks()
        dw = dlg.winfo_reqwidth()
        dh = dlg.winfo_reqheight()
        pw = self.root.winfo_rootx()
        ph = self.root.winfo_rooty()
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
        log = get_logger()
        last_tick = time.time()
        while True:
            # If the previous sleep(POLL_INTERVAL) stretched far beyond
            # POLL_INTERVAL, the OS suspended us while the PC slept. Any VPN
            # tunnel we had is dead — force a clean state before reporting.
            now = time.time()
            gap = now - last_tick
            if gap > session_manager.SLEEP_THRESHOLD and not self._busy:
                log.info(f"_monitor: detected {gap:.0f}s gap after sleep — forcing disconnect_all")
                self.root.after(0, lambda: self._msg("PC despertando — desconectando VPN…"))
                try:
                    self.controller.disconnect_all()
                except Exception as e:
                    log.warning(f"_monitor: post-sleep disconnect_all failed: {e}")
                self.root.after(0, lambda: self._msg(""))

            if not self._busy:
                try:
                    s = self.controller.get_status()
                    if s != self._status:
                        self._status = s
                        self.root.after(0, self._refresh_ui)
                        self._update_tray_icon()
                except Exception:
                    pass
                session_manager.touch()
            last_tick = time.time()
            time.sleep(self.POLL_INTERVAL)

    def _refresh_ui(self):
        T = self._T
        s = self._status
        if s == CISCO:
            dot, label, sub = T["cisco"], "Connected", "Oracle VPN — Cisco Secure Client"
            self._card_cisco.set_active(True)
            self._card_forti.set_active(False)
            self._card_gp.set_active(False)
            self._card_none.set_active(False)
        elif s == FORTI:
            dot, label, sub = T["forti"], "Connected", "Falabella VPN — FortiClient"
            self._card_cisco.set_active(False)
            self._card_forti.set_active(True)
            self._card_gp.set_active(False)
            self._card_none.set_active(False)
        elif s == GPROT:
            dot, label, sub = T["gp"], "Connected", "BICE VPN — GlobalProtect"
            self._card_cisco.set_active(False)
            self._card_forti.set_active(False)
            self._card_gp.set_active(True)
            self._card_none.set_active(False)
        else:
            dot, label, sub = T["text_dim"], "Disconnected", "Pick a VPN to connect"
            self._card_cisco.set_active(False)
            self._card_forti.set_active(False)
            self._card_gp.set_active(False)
            self._card_none.set_active(True)

        self._dot.configure(fg=dot)
        self._status_lbl.configure(text=label)
        self._status_sub.configure(text=sub)

        if self._tray:
            self._tray.title = f"VPN Switcher — {label}"

    # ── actions ────────────────────────────────────────────────────────────────

    def _switch(self, target: str):
        if self._busy:
            return
        self.config = self.config_manager.load()
        self.controller.config = self.config

        current = self._status

        def _work():
            import vpn_controller as _vc
            _vc._autofill_cancel.clear()
            self._set_busy(True)
            try:
                if current == CISCO and target != CISCO:
                    self._msg("Disconnecting Cisco Secure Client…")
                    ok, msg = self.controller.disconnect_cisco()
                    if not ok:
                        self._msg(f"⚠  {msg}")
                        time.sleep(2)
                    else:
                        time.sleep(1)

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
        self.root.attributes("-topmost", True)
        self.root.focus_force()
        self.root.update()
        self.root.attributes("-topmost", False)

    def _poll_show_flag(self):
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
        old_theme = self.config.get("theme_mode", "dark")
        dlg = SettingsDialog(self.root, self.config_manager, self._T)
        self.root.wait_window(dlg)
        # Reload config after settings saved
        self.config = self.config_manager.load()
        self.controller.config = self.config
        new_theme = self.config.get("theme_mode", "dark")
        if new_theme != old_theme:
            self._rebuild_main()
        else:
            self._apply_card_visibility()

    def _handle_wrong_password(self, target: str):
        import vpn_controller as _vc
        self._set_busy(False)

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
            _vc._autofill_cancel.set()
            self._msg("Autofill cancelado.")
            return

        old_theme = self.config.get("theme_mode", "dark")
        dlg = SettingsDialog(self.root, self.config_manager, self._T)
        self.root.wait_window(dlg)

        self.config = self.config_manager.load()
        self.controller.config = self.config
        new_theme = self.config.get("theme_mode", "dark")
        if new_theme != old_theme:
            self._rebuild_main()

        self.root.after(300, lambda: self._start_retry(target))

    def _start_retry(self, target: str):
        import vpn_controller as _vc
        import ctypes
        _vc._autofill_cancel.clear()

        sign_in_win = _vc._find_signin_window()
        if sign_in_win:
            ctypes.windll.user32.PostMessageW(sign_in_win.handle, 0x0010, 0, 0)  # WM_CLOSE
            time.sleep(1.5)

        self.root.withdraw()

        def _retry():
            self._set_busy(True)
            try:
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

    # ── card visibility ────────────────────────────────────────────────────────

    def _apply_card_visibility(self):
        """Lay out the 2x2 card grid honoring show_forti / show_gp.
        Cisco is always shown; No-VPN sits in the bottom-right.
        Order tried (visible cards in this sequence):
            cisco, [forti], [gp], none
        and they fill row-major positions (0,0) (0,1) (1,0) (1,1).
        """
        show_forti = self.config.get("show_forti", True)
        show_gp    = self.config.get("show_gp", True)

        for c in (self._card_cisco, self._card_forti, self._card_gp, self._card_none):
            c.grid_forget()

        visible = [self._card_cisco]
        if show_forti:
            visible.append(self._card_forti)
        if show_gp:
            visible.append(self._card_gp)
        visible.append(self._card_none)

        for i, card in enumerate(visible):
            r, c = divmod(i, 2)
            card.grid(row=r, column=c, sticky="nsew", padx=5, pady=5, ipadx=2, ipady=4)

    # ── auto-update check ──────────────────────────────────────────────────────

    def _check_for_update(self):
        try:
            import re
            import subprocess
            from version import __version__

            repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
            if not os.path.isdir(os.path.join(repo_dir, ".git")):
                return

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
            pass

    @staticmethod
    def _find_git():
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
        import subprocess
        import webbrowser

        repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        updater = os.path.join(repo_dir, "update.bat")
        if not os.path.isfile(updater):
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
        if self.config_manager.first_run:
            self.root.after(200, self.__open_settings)

        self._build_tray()
        self._tray.run_detached()

        threading.Thread(target=self._monitor, daemon=True).start()

        def _delayed_update_check():
            time.sleep(5)
            self._check_for_update()
        threading.Thread(target=_delayed_update_check, daemon=True).start()

        self._center_window()
        self.root.deiconify()

        self.root.after(400, self._poll_show_flag)

        should_clean, reason = session_manager.should_force_disconnect()
        log = get_logger()
        log.info(f"session_guard: should_force_disconnect={should_clean} reason='{reason}'")
        session_manager.touch()

        def _init_status():
            if should_clean:
                self.root.after(0, lambda: self._msg("Restaurando estado tras reinicio…"))
                try:
                    self.controller.disconnect_all()
                except Exception as e:
                    log.warning(f"session_guard: disconnect_all failed: {e}")
                self.root.after(0, lambda: self._msg(""))
            try:
                s = self.controller.get_status()
            except Exception:
                s = NONE
            self._status = s
            self.root.after(0, self._refresh_ui)
            self._update_tray_icon()
        threading.Thread(target=_init_status, daemon=True).start()

        self.root.mainloop()
