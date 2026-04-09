# VPN Switcher — Implementation Plan

## Goal
A system-tray Windows app that lets users switch between **FortiClient VPN** and **Cisco Secure Client** with a single click, ensuring only one VPN is active at a time.

---

## Requirements
- [x] UI with 3 buttons: Cisco | FortiClient | No VPN
- [x] If connecting to VPN A while VPN B is active → disconnect B first
- [x] Can never be connected to both simultaneously
- [x] Lives in the Windows system tray (notification area icons)
- [x] Single installer — bundles Python + all dependencies
- [x] Distributable via Git for coworkers

---

## File Structure
```
vpn/
├── PLAN.md               ← this file
├── src/
│   ├── main.py           ← entry point
│   ├── vpn_controller.py ← VPN state detection & connect/disconnect logic
│   ├── config_manager.py ← read/write config.json in %APPDATA%
│   └── ui.py             ← system tray + main window + settings dialog
├── requirements.txt
├── build.bat             ← builds the .exe with PyInstaller
├── installer/
│   └── setup.iss         ← Inno Setup script → produces VPNSwitcher-Setup.exe
├── .gitignore
└── README.md
```

---

## Tech Stack
| Concern | Library |
|---|---|
| System tray | `pystray` |
| UI window | `tkinter` (built-in) |
| Icon generation | `Pillow` |
| Process / network detection | `psutil` |
| Bundling | `PyInstaller` |
| Installer | Inno Setup 6 |

---

## VPN Detection Strategy

### Cisco Secure Client
- **Primary**: `vpncli.exe state` — output contains `"state: Connected"`
- **Fallback**: check network interface names for "AnyConnect" or "Cisco"

### FortiClient VPN
- **Primary**: check network interfaces for "Fortinet", "FortiClient", "FortiSSL"
- **Fallback**: check running processes for `FortiSSLVPN.exe`

---

## VPN Connect / Disconnect

### Cisco Secure Client
- **Connect**: `vpncli.exe connect <host>` — feeds credentials from config via stdin if configured
- **Disconnect**: `vpncli.exe disconnect`

### FortiClient VPN
- **Connect**: Launch `FortiClientVPN.exe` (no public CLI for standalone free version); OR run a user-configured custom command
- **Disconnect**: Try in order:
  1. User-configured custom disconnect command
  2. Kill `FortiSSLVPN.exe` process
  3. PowerShell `Disconnect-VpnConnection` for named connections
- **Note**: FortiClient standalone has no official CLI. The settings allow custom commands for full automation.

---

## Config (stored in %APPDATA%\VPNSwitcher\config.json)
```json
{
  "cisco_cli_path": "",           // auto-detected if blank
  "cisco_host": "vpn.company.com",
  "cisco_username": "",
  "cisco_password": "",
  "forti_exe_path": "",           // auto-detected if blank
  "forti_connect_cmd": "",        // custom shell command to connect
  "forti_disconnect_cmd": "",     // custom shell command to disconnect
  "start_with_windows": true
}
```

---

## Build Process (for the developer / CI)
1. Run `build.bat` → creates `dist/VPNSwitcher/VPNSwitcher.exe` via PyInstaller
2. Open `installer/setup.iss` in Inno Setup 6 → compile → produces `Output/VPNSwitcher-Setup.exe`
3. Commit & push `VPNSwitcher-Setup.exe` (or attach to a GitHub Release)
4. Coworkers download and run `VPNSwitcher-Setup.exe` → installs, starts with Windows, shows in tray

---

## UI Flow
```
[Tray Icon] double-click or left-click → opens main window

Main Window:
┌──────────────────────────────┐
│        VPN Switcher          │
│                              │
│  Status: ● No VPN Connected  │
│                              │
│  ┌──────────────────────────┐│
│  │  Cisco Secure Client     ││  ← click → disconnect Forti (if active), connect Cisco
│  └──────────────────────────┘│
│  ┌──────────────────────────┐│
│  │  FortiClient VPN         ││  ← click → disconnect Cisco (if active), connect Forti
│  └──────────────────────────┘│
│  ┌──────────────────────────┐│
│  │  No VPN                  ││  ← click → disconnect whichever is active
│  └──────────────────────────┘│
│                              │
│  [message area]              │
│                        ⚙     │
└──────────────────────────────┘
```

Tray icon color reflects state:
- Gray = no VPN
- Blue = Cisco connected
- Orange = FortiClient connected
