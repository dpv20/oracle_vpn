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
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe' -OutFile '!PYTHON_INSTALLER!' -UseBasicParsing } catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }"
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
:: Last resort: py.exe launcher (always in C:\Windows after Python install)
if not defined PY if exist "%SystemRoot%\py.exe" set "PY=%SystemRoot%\py.exe -3"
if not defined PY (
    echo [ERROR] Python was installed but python.exe was not found in expected locations.
    echo Please close this window and run install.bat again.
    pause & exit /b 1
)
echo [OK] Using Python at: !PY!

:AFTER_PYTHON

:: ── 2. Copy app files to LOCALAPPDATA ────────────────────────────────────────
echo.
echo [1/4] Installing application files...
set "APP_DIR=%~dp0"
if "!APP_DIR:~-1!"=="\" set "APP_DIR=!APP_DIR:~0,-1!"
set "INSTALL_DIR=%LOCALAPPDATA%\VPNSwitcher"
if not exist "!INSTALL_DIR!" mkdir "!INSTALL_DIR!"

robocopy "!APP_DIR!\src" "!INSTALL_DIR!\src" /e /copy:DAT /r:2 /w:5 >nul
if !errorlevel! geq 8 (
    echo [ERROR] Failed to copy src/ to !INSTALL_DIR!.
    pause & exit /b 1
)
robocopy "!APP_DIR!\assets" "!INSTALL_DIR!\assets" /e /copy:DAT /r:2 /w:5 >nul
if !errorlevel! geq 8 (
    echo [ERROR] Failed to copy assets/ to !INSTALL_DIR!.
    pause & exit /b 1
)
echo [OK] Application files copied to !INSTALL_DIR!.

:: ── 3. Install pip dependencies ──────────────────────────────────────────────
echo.
echo [2/4] Installing dependencies (this may take a minute)...
set "PIP_LOG=%TEMP%\vpnswitcher_pip.log"
!PY! -m pip install --upgrade pip > "!PIP_LOG!" 2>&1
if errorlevel 1 (
    echo [WARN] pip upgrade failed, continuing with bundled version...
)
!PY! -m pip install -r "!APP_DIR!\requirements.txt" > "!PIP_LOG!" 2>&1
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

:: ── 4. Create shortcut ───────────────────────────────────────────────────────
echo.
echo [3/4] Creating shortcuts...
set "SCRIPT=!INSTALL_DIR!\src\main.py"
set "ICON=!INSTALL_DIR!\assets\logo_cuadrado.ico"
set "DESKTOP=%USERPROFILE%\Desktop"

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

powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut('!DESKTOP!\VPN Switcher.lnk'); $s.TargetPath='!PYTHONW!'; $s.Arguments='\"!SCRIPT!\"'; $s.WorkingDirectory='!INSTALL_DIR!'; $s.IconLocation='!ICON!'; $s.Description='VPN Switcher'; $s.Save()"
if errorlevel 1 (
    echo [WARN] Could not create desktop shortcut. App is still installed at !INSTALL_DIR!.
) else (
    echo [OK] Desktop shortcut created: !DESKTOP!\VPN Switcher.lnk
)

:: ── Done ─────────────────────────────────────────────────────────────────────
echo.
echo [4/4] Setup complete!
echo.
echo ============================================================
echo  VPN Switcher is ready!
echo.
echo   Desktop shortcut : VPN Switcher.lnk
echo   Starts with Windows: yes (toggle off in Settings)
echo   To uninstall     : run uninstall.bat
echo   You can now delete this setup folder.
echo ============================================================
echo.

echo Launching VPN Switcher...
start "" "!PYTHONW!" "!SCRIPT!"
echo.
pause
