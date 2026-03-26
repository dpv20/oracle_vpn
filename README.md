# VPN Switcher

A Windows system-tray app that lets you switch between **Cisco Secure Client** and **FortiClient VPN** with a single click — ensuring you can never be connected to both at the same time.

---

## For end users (coworkers)

1. Download `VPNSwitcher-Setup.exe` from the shared location / Git releases.
2. Run it and follow the wizard.
3. On first launch the **Settings** dialog will open — fill in:
   - **Cisco host** (e.g. `vpn.company.com`)
   - Optionally: username / password (stored locally on your machine)
4. The app icon appears in the system tray (bottom-right, "show hidden icons").
5. Click the icon → open the window → choose your VPN.

> **Tip:** check "Start with Windows" in Settings so it's always available.

---

## For developers — how to build

### Prerequisites
| Tool | Download |
|---|---|
| Python 3.11+ | https://www.python.org/downloads/ |
| Inno Setup 6 | https://jrsoftware.org/isdl.php |

### Steps

```bat
# 1 — build the executable
build.bat

# 2 — open installer\setup.iss in Inno Setup and press Ctrl+F9 (Build)
#     → produces Output\VPNSwitcher-Setup.exe
```

Upload `Output\VPNSwitcher-Setup.exe` to Git (or a network share) for coworkers.

---

## FortiClient note

FortiClient VPN standalone does **not** expose a CLI for connecting.
Default behaviour: clicking the FortiClient button **launches the FortiClient app** — connect from there.

If your team uses the **enterprise** FortiClient or a specific CLI/script, put the command in Settings → *Custom connect command* / *Custom disconnect command*.

Example custom disconnect command that works if FortiClient creates a named Windows VPN:
```
rasdial "FortiClient VPN" /disconnect
```

---

## Config file location

`%APPDATA%\VPNSwitcher\config.json` — per-user, never committed to Git.
