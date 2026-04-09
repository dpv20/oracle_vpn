@echo off
setlocal EnableDelayedExpansion
title VPN Switcher — Setup
cd /d "%~dp0"

echo.
echo ============================================================
echo  VPN Switcher — Setup
echo ============================================================
echo.

:: ── 1. Check / install Python ────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [!] Python not found. Downloading and installing Python 3.12...
    powershell -NoProfile -Command ^
        "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe' -OutFile '%TEMP%\python_setup.exe' -UseBasicParsing"
    "%TEMP%\python_setup.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1
    del "%TEMP%\python_setup.exe"
    echo.
    echo [!] Python installed. Please close this window and run setup.bat again.
    pause & exit /b 0
)

for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo [OK] %%v found.

:: ── 2. Install pip dependencies ───────────────────────────────────────────────
echo.
echo [1/3] Installing dependencies...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet

if errorlevel 1 (
    echo [ERROR] Failed to install dependencies. Check your internet connection.
    pause & exit /b 1
)
echo [OK] Dependencies installed.

:: ── 3. Create shortcuts ───────────────────────────────────────────────────────
echo.
echo [2/3] Creating shortcuts...

:: Resolve paths (handle spaces)
set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"
set "SCRIPT=%APP_DIR%\src\main.py"
set "ICON=%APP_DIR%\assets\logo_cuadrado.ico"
set "DESKTOP=%USERPROFILE%\Desktop"

:: Find pythonw.exe (same folder as python.exe, no console window)
for /f "tokens=*" %%p in ('python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYTHONW=%%p"

if not exist "%PYTHONW%" (
    :: Fallback: use python.exe if pythonw.exe not found
    for /f "tokens=*" %%p in ('python -c "import sys; print(sys.executable)"') do set "PYTHONW=%%p"
)

:: Desktop shortcut via PowerShell (single line to avoid ^ passthrough issues)
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut('%DESKTOP%\VPN Switcher.lnk'); $s.TargetPath='%PYTHONW%'; $s.Arguments='\"%SCRIPT%\"'; $s.WorkingDirectory='%APP_DIR%'; $s.IconLocation='%ICON%'; $s.Description='VPN Switcher'; $s.Save()"

echo [OK] Desktop shortcut created: %DESKTOP%\VPN Switcher.lnk

:: Startup registry (optional — app also exposes this toggle in Settings)
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" ^
    /v "VPN Switcher" ^
    /t REG_SZ ^
    /d "\"%PYTHONW%\" \"%SCRIPT%\"" ^
    /f >nul
echo [OK] Added to Windows startup.

:: ── Done ──────────────────────────────────────────────────────────────────────
echo.
echo [3/3] Setup complete!
echo.
echo ============================================================
echo  VPN Switcher is ready!
echo.
echo   Desktop shortcut : VPN Switcher.lnk
echo   Starts with Windows: yes (toggle in Settings)
echo   To uninstall     : run uninstall.bat
echo ============================================================
echo.
pause
