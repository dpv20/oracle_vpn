# FortiClient Automation Plan

## What we know
- Window title: **"FortiClient - Zero Trust Fabric Agent"**
- App type: **Electron** (Chromium-based) — needs UIA backend, not win32
- VPN profile name: **"Falabella_VPN"** (saved in dropdown)
- Auth flow: **SAML via Microsoft Entra ID** (browser popup)
- MFA: **Microsoft Authenticator** (phone approval, can't automate)

---

## Step 1 — Open the FortiClient window

**Problem:** FortiClient is Electron. `subprocess.Popen(exe)` does nothing if already running.
**Solution (confirmed working):** `explorer.exe FortiClient.exe` opens the window.

- If window already visible → bring it to front
- If not → launch via explorer.exe, wait, then bring to front

Window title to search: `"FortiClient - Zero Trust Fabric Agent"`

---

## Step 2 — Click the Connect button

**Problem:** Electron apps expose UIA accessibility tree via Chromium.
**Approach:**
1. Try `pywinauto` with `uia` backend, searching for a Button with text "Connect"
2. The Electron window class is `Chrome_WidgetWin_1` — use that to find the right window
3. Retry loop (up to 8s) same as Cisco approach

**What happens after click:**
- FortiClient contacts the VPN server
- A browser-style popup appears: "Sign in to your account (NNN)"

---

## Step 3 — Handle the sign-in browser popup

The popup is a Chromium WebAuthenticationBroker or WebView window.
Title pattern: `"Sign in to your account"` (with changing number suffix)

**3a. Username field**
- If username is saved in Settings → auto-type it into the Email field → click Next
- If not saved → leave for the user to fill

**3b. Password field**
- If password is saved in Settings → auto-type it → click Sign in
- If not saved → leave for the user to fill

**3c. MFA (Authenticator)**
- Shows a number (e.g. "30") the user enters in the phone app
- Nothing to automate — user approves on phone
- We just wait

**3d. "Unsafe site" browser warning**
- Sometimes a Chrome/Edge window shows a certificate warning
- Detect window with text "Your connection is not private" or similar
- Click "Advanced" → "Proceed anyway" (or just ignore — FortiClient handles it)

---

## Step 4 — Wait for connection

After MFA approval, FortiClient shows **"VPN Connected"**.
The Fortinet SSL VPN adapter (`Ethernet 3`) status changes to **"Up"**.
Our existing `_forti_connected()` detection catches this.

---

## Step 5 — Disconnect

When user clicks "No VPN" or switches to Cisco while FortiClient is active:

1. Find `"FortiClient - Zero Trust Fabric Agent"` window
2. Bring to front
3. Find button with text `"Disconnect"` (same UIA approach)
4. Click it → FortiClient disconnects cleanly

---

## Settings additions needed

| Field | Purpose |
|---|---|
| FortiClient username (email) | Auto-fill in the sign-in popup |
| FortiClient password | Auto-fill (optional, user may prefer to type) |

---

## Implementation order

1. **Step 1** — open/bring FortiClient window to front (already partially done)
2. **Step 2** — click Connect via UIA on the Electron window
3. **Step 5** — click Disconnect via UIA (same mechanism)
4. **Step 3a/3b** — auto-fill credentials in the sign-in popup (optional, later)

---

## Technical notes

- Electron window class: `Chrome_WidgetWin_1`
- pywinauto backend: `uia` (NOT win32 — Electron controls aren't standard Win32)
- The sign-in popup may also be Chromium-based
- MFA and "unsafe site" warnings are out of scope for automation — user handles them
