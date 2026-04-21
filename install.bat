@echo off
setlocal EnableDelayedExpansion
title VPN Switcher - Setup
cd /d "%~dp0"

echo.
echo ============================================================
echo  VPN Switcher - Setup
echo ============================================================
echo.

:: ── 1. Check / install Python ────────────────────────────────────────────────
:: PY = command/path used to invoke Python for the rest of this script.
set "PY=python"
python --version >nul 2>&1
if errorlevel 1 goto :INSTALL_PYTHON

:: Check version >= 3.8
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
for /f "tokens=1,2 delims=." %%a in ("!PYVER!") do (
    set "PYMAJOR=%%a"
    set "PYMINOR=%%b"
)
if !PYMAJOR! lss 3 goto :PYTHON_TOO_OLD
if !PYMAJOR! equ 3 if !PYMINOR! lss 8 goto :PYTHON_TOO_OLD
echo [OK] Python !PYVER! found.
goto :AFTER_PYTHON

:PYTHON_TOO_OLD
echo.
echo [ERROR] Python !PYVER! is too old. This app requires Python 3.8 or newer.
echo Please uninstall your current Python and run install.bat again.
pause & exit /b 1

:INSTALL_PYTHON
echo Python not found. Downloading and installing Python 3.12...
set "PYTHON_INSTALLER=%TEMP%\python_setup_!RANDOM!!RANDOM!.exe"
powershell -NoProfile -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe' -OutFile '!PYTHON_INSTALLER!' -UseBasicParsing } catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }"
if errorlevel 1 (
    echo [ERROR] Failed to download Python installer. Check internet connection / proxy / firewall.
    if exist "!PYTHON_INSTALLER!" del /f /q "!PYTHON_INSTALLER!" >nul 2>&1
    pause & exit /b 1
)
"!PYTHON_INSTALLER!" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
set "PY_RC=!errorlevel!"
if !PY_RC! neq 0 (
    echo [ERROR] Python installer failed with exit code !PY_RC!.
    if exist "!PYTHON_INSTALLER!" del /f /q "!PYTHON_INSTALLER!" >nul 2>&1
    pause & exit /b 1
)
del /f /q "!PYTHON_INSTALLER!" >nul 2>&1
echo [OK] Python installed.

:: PATH update won't apply to this cmd session. Find python.exe directly
:: so the rest of the script works without requiring a restart.
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%ProgramFiles%\Python312\python.exe"        set "PY=%ProgramFiles%\Python312\python.exe"
if not defined PY if exist "%ProgramFiles(x86)%\Python312\python.exe" set "PY=%ProgramFiles(x86)%\Python312\python.exe"
:: Last resort: py.exe launcher
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Launcher\py.exe -3"
if not defined PY if exist "%SystemRoot%\py.exe" set "PY=%SystemRoot%\py.exe -3"
if not defined PY (
    echo [ERROR] Python was installed but python.exe was not found in expected locations.
    echo Please close this window and run install.bat again.
    pause & exit /b 1
)
echo [OK] Using Python at: !PY!

:AFTER_PYTHON

:: ── 2. Check / install Git ───────────────────────────────────────────────────
:: GIT = command/path used to invoke git for the rest of this script.
set "GIT="
where git >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%g in ('where git') do (
        if not defined GIT set "GIT=%%g"
    )
    echo [OK] Git found at !GIT!.
    goto :AFTER_GIT
)

echo Git not found. Downloading and installing Git (per-user, no admin)...
set "GIT_INSTALLER=%TEMP%\git_setup_!RANDOM!!RANDOM!.exe"
powershell -NoProfile -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://github.com/git-for-windows/git/releases/download/v2.45.2.windows.1/Git-2.45.2-64-bit.exe' -OutFile '!GIT_INSTALLER!' -UseBasicParsing } catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }"
if errorlevel 1 (
    echo [ERROR] Failed to download Git installer. Check internet connection / proxy / firewall.
    if exist "!GIT_INSTALLER!" del /f /q "!GIT_INSTALLER!" >nul 2>&1
    pause & exit /b 1
)

:: Per-user silent install — no UAC. PathOption=CmdTools adds Git to user PATH.
"!GIT_INSTALLER!" /VERYSILENT /NORESTART /SP- /CLOSEAPPLICATIONS /NOCANCEL /COMPONENTS="icons,ext\reg\shellhere,assoc,assoc_sh" /o:PathOption=CmdTools /o:BashTerminalOption=ConHost /o:DefaultBranchOption=main
set "GIT_RC=!errorlevel!"
if !GIT_RC! neq 0 (
    echo [ERROR] Git installer failed with exit code !GIT_RC!.
    if exist "!GIT_INSTALLER!" del /f /q "!GIT_INSTALLER!" >nul 2>&1
    pause & exit /b 1
)
del /f /q "!GIT_INSTALLER!" >nul 2>&1
echo [OK] Git installed.

:: PATH won't refresh in this cmd session; locate git.exe directly.
if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe"    set "GIT=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"
if not defined GIT if exist "%ProgramFiles%\Git\cmd\git.exe"       set "GIT=%ProgramFiles%\Git\cmd\git.exe"
if not defined GIT if exist "%ProgramFiles(x86)%\Git\cmd\git.exe" set "GIT=%ProgramFiles(x86)%\Git\cmd\git.exe"
if not defined GIT (
    echo [ERROR] Git was installed but git.exe was not found in expected locations.
    echo Please close this window and run install.bat again.
    pause & exit /b 1
)
echo [OK] Using Git at: !GIT!

:AFTER_GIT

:: ── 3. Clone / update repo in LOCALAPPDATA ──────────────────────────────────
echo.
echo [1/4] Fetching application files from GitHub...
set "APP_DIR=%~dp0"
if "!APP_DIR:~-1!"=="\" set "APP_DIR=!APP_DIR:~0,-1!"
set "INSTALL_DIR=%LOCALAPPDATA%\VPNSwitcher"
set "REPO_DIR=!INSTALL_DIR!\app"
set "REPO_URL=https://github.com/dpv20/oracle_vpn.git"

if not exist "!INSTALL_DIR!" mkdir "!INSTALL_DIR!"

:: Kill any running instance so git can overwrite files.
taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq VPN Switcher" >nul 2>&1
taskkill /F /IM python.exe  /FI "WINDOWTITLE eq VPN Switcher" >nul 2>&1
timeout /t 1 /nobreak >nul

if exist "!REPO_DIR!\.git" (
    echo Repo already cloned. Updating to latest main...
    "!GIT!" -C "!REPO_DIR!" fetch origin main
    if errorlevel 1 (
        echo [ERROR] git fetch failed. Check internet / firewall / proxy.
        pause & exit /b 1
    )
    "!GIT!" -C "!REPO_DIR!" reset --hard origin/main
    if errorlevel 1 (
        echo [ERROR] git reset --hard failed.
        pause & exit /b 1
    )
) else (
    if exist "!REPO_DIR!" rmdir /s /q "!REPO_DIR!"
    "!GIT!" clone --depth 1 --branch main "!REPO_URL!" "!REPO_DIR!"
    if errorlevel 1 (
        echo [ERROR] git clone failed. Check internet / firewall / proxy.
        echo Repo URL: !REPO_URL!
        pause & exit /b 1
    )
    :: Unshallow so future fetches can compare commits cleanly.
    "!GIT!" -C "!REPO_DIR!" fetch --unshallow origin main >nul 2>&1
)
echo [OK] Repo ready at !REPO_DIR!.

:: ── 4. Install pip dependencies ──────────────────────────────────────────────
echo.
echo [2/4] Installing dependencies (this may take a minute)...
set "PIP_LOG=%TEMP%\vpnswitcher_pip_install.log"
!PY! -m pip install -r "!REPO_DIR!\requirements.txt" > "!PIP_LOG!" 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install dependencies. Details:
    echo ------------------------------------------------------------
    type "!PIP_LOG!"
    echo ------------------------------------------------------------
    echo Full log: !PIP_LOG!
    pause & exit /b 1
)
del /f /q "!PIP_LOG!" >nul 2>&1
echo [OK] Dependencies installed.

:: ── 5. Create shortcut ───────────────────────────────────────────────────────
echo.
echo [3/4] Creating shortcut...
set "SCRIPT=!REPO_DIR!\src\main.py"
set "ICON=!REPO_DIR!\assets\logo_cuadrado.ico"

:: Resolve real Desktop path (handles OneDrive / corporate GPO redirection)
set "DESK_TMP=%TEMP%\vpnsw_desktop.txt"
powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')" > "!DESK_TMP!" 2>nul
set /p DESKTOP=<"!DESK_TMP!"
del /f /q "!DESK_TMP!" >nul 2>&1
if not defined DESKTOP set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "!DESKTOP!" set "DESKTOP=%USERPROFILE%\Desktop"

:: Find pythonw.exe via a temp file (avoids cmd quoting issues with accented paths)
set "PYPATH_TMP=%TEMP%\vpnsw_pypath.txt"
!PY! -c "import sys,os; print(os.path.join(sys.prefix,'pythonw.exe'))" > "!PYPATH_TMP!" 2>nul
set /p PYTHONW=<"!PYPATH_TMP!"
del /f /q "!PYPATH_TMP!" >nul 2>&1
if not exist "!PYTHONW!" (
    !PY! -c "import sys,os; print(os.path.join(sys.prefix,'python.exe'))" > "!PYPATH_TMP!" 2>nul
    set /p PYTHONW=<"!PYPATH_TMP!"
    del /f /q "!PYPATH_TMP!" >nul 2>&1
)
if not exist "!PYTHONW!" (
    echo [ERROR] Could not locate pythonw.exe or python.exe in Python install.
    pause & exit /b 1
)

set "LNK_PATH=!DESKTOP!\VPN Switcher.lnk"
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut('!LNK_PATH!'); $s.TargetPath='!PYTHONW!'; $s.Arguments='\"!SCRIPT!\"'; $s.WorkingDirectory='!REPO_DIR!'; $s.IconLocation='!ICON!'; $s.Description='VPN Switcher'; $s.Save()"
if errorlevel 1 (
    echo [WARN] Could not create desktop shortcut. App is still installed at !REPO_DIR!.
) else (
    echo [OK] Desktop shortcut created: !LNK_PATH!
    powershell -NoProfile -ExecutionPolicy Bypass -File "!REPO_DIR!\tools\set_aumid.ps1" -LnkPath "!LNK_PATH!" -AUMID "Oracle.VPNSwitcher.1" >nul 2>&1
    if errorlevel 1 (
        echo [WARN] Could not set AppUserModelID on shortcut; taskbar pin may show Python icon.
    ) else (
        echo [OK] Shortcut AppUserModelID set.
    )
)

:: ── Done ─────────────────────────────────────────────────────────────────────
echo.
echo [4/4] Setup complete!
echo.
echo ============================================================
echo  VPN Switcher is ready!
echo.
echo   Desktop shortcut  : VPN Switcher.lnk
echo   Installed at      : !REPO_DIR!
echo   Auto-update       : enabled (git pull on new version)
echo   Starts with Windows: yes (toggle off in Settings)
echo   To uninstall      : run uninstall.bat
echo   You can now delete this setup folder.
echo ============================================================
echo.

echo Launching VPN Switcher...
start "" "!PYTHONW!" "!SCRIPT!"
echo.
pause
