"""Color palettes for VPN Switcher.

Two themes (dark / light) exposed through `get_theme(mode)`. UI modules
should read every color from the returned dict instead of hard-coding,
so toggling the mode at runtime re-skins the whole app.

The brand colors (Oracle red, Falabella green, BICE blue) are intentionally
identical across themes — they're the VPN identifiers, not chrome.
"""

# Brand colors — shared across both themes.
BRAND_CISCO = "#dc2626"        # Oracle red
BRAND_CISCO_HOVER = "#ef4444"
BRAND_FORTI = "#16a34a"        # Falabella green
BRAND_FORTI_HOVER = "#22c55e"
BRAND_GP = "#2563eb"           # BICE blue
BRAND_GP_HOVER = "#3b82f6"


DARK = {
    "name": "dark",
    "bg": "#0f1115",            # main background — near-black
    "surface": "#1a1d24",       # cards / inputs
    "surface_hi": "#23272f",    # hover / elevated
    "border": "#2a2f3a",
    "border_strong": "#3a4150",
    "text": "#f4f5f8",
    "text_muted": "#8a92a3",
    "text_dim": "#5d6470",

    "accent": "#7c8cff",        # links, focus rings
    "accent_hover": "#9aa6ff",
    "success": "#4ade80",
    "warn": "#facc15",
    "error": "#f87171",

    "none_btn": "#2a3040",
    "none_btn_hover": "#363d50",

    # Brand colors (echoed here so callers only need one dict)
    "cisco":       BRAND_CISCO,
    "cisco_hover": BRAND_CISCO_HOVER,
    "forti":       BRAND_FORTI,
    "forti_hover": BRAND_FORTI_HOVER,
    "gp":          BRAND_GP,
    "gp_hover":    BRAND_GP_HOVER,
}


LIGHT = {
    "name": "light",
    "bg": "#f5f6fa",
    "surface": "#ffffff",
    "surface_hi": "#eef0f6",
    "border": "#e1e4ed",
    "border_strong": "#c8cdda",
    "text": "#15181f",
    "text_muted": "#5b6273",
    "text_dim": "#8a92a3",

    "accent": "#4f5dff",
    "accent_hover": "#3845ec",
    "success": "#15803d",
    "warn": "#a16207",
    "error": "#dc2626",

    "none_btn": "#dbe0ed",
    "none_btn_hover": "#c4cbdc",

    "cisco":       BRAND_CISCO,
    "cisco_hover": BRAND_CISCO_HOVER,
    "forti":       BRAND_FORTI,
    "forti_hover": BRAND_FORTI_HOVER,
    "gp":          BRAND_GP,
    "gp_hover":    BRAND_GP_HOVER,
}


def get_theme(mode: str) -> dict:
    return LIGHT if (mode or "").lower() == "light" else DARK
