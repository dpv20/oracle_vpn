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
    set "PYTHON_INSTALLER=%TEMP%\python_setup_%RANDOM%_%RANDOM%.exe"
    powershell -NoProfile -Command ^
        "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe' -OutFile '%PYTHON_INSTALLER%' -UseBasicParsing"
    if errorlevel 1 (
        echo [ERROR] Failed to download Python installer.
        if exist "%PYTHON_INSTALLER%" del /f /q "%PYTHON_INSTALLER%" >nul 2>&1
        pause & exit /b 1
    )
    "%PYTHON_INSTALLER%" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1
    if errorlevel 1 (
        echo [ERROR] Python installer failed.
        if exist "%PYTHON_INSTALLER%" del /f /q "%PYTHON_INSTALLER%" >nul 2>&1
        pause & exit /b 1
    )
    del /f /q "%PYTHON_INSTALLER%" >nul 2>&1
    echo.
    echo [!] Python installed. Please close this window and run setup.bat again.
    pause & exit /b 0
)

for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo [OK] %%v found.

:: ── 2. Copy app files to LOCALAPPDATA and install pip dependencies ─────────
echo.
echo [1/4] Installing application files...
set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"
set "INSTALL_DIR=%LOCALAPPDATA%\VPNSwitcher"
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
robocopy "%APP_DIR%\src" "%INSTALL_DIR%\src" /e /copyall /r:2 /w:5 >nul
set "RC=%ERRORLEVEL%"
if %RC% geq 8 (
    echo [ERROR] Failed to copy application files to %INSTALL_DIR%.
    pause & exit /b 1
)
robocopy "%APP_DIR%\assets" "%INSTALL_DIR%\assets" /e /copyall /r:2 /w:5 >nul
set "RC=%ERRORLEVEL%"
if %RC% geq 8 (
    echo [ERROR] Failed to copy application files to %INSTALL_DIR%.
    pause & exit /b 1
)

echo [OK] Application files copied to %INSTALL_DIR%.

echo.
echo [2/4] Installing dependencies...
python -m pip install --upgrade pip --quiet
python -m pip install -r "%APP_DIR%\requirements.txt" --quiet

if errorlevel 1 (
    echo [ERROR] Failed to install dependencies. Check your internet connection.
    pause & exit /b 1
)
echo [OK] Dependencies installed.

:: ── 3. Create shortcuts ───────────────────────────────────────────────────────
echo.
echo [3/4] Creating shortcuts...

:: Resolve paths (handle spaces)
set "INSTALL_DIR=%LOCALAPPDATA%\VPNSwitcher"
set "SCRIPT=%INSTALL_DIR%\src\main.py"
set "ICON=%INSTALL_DIR%\assets\logo_cuadrado.ico"
set "DESKTOP=%USERPROFILE%\Desktop"

:: Find pythonw.exe via sys.prefix (works even when launched via py.exe launcher)
for /f "tokens=*" %%p in ('python -c "import sys,os; print(os.path.join(sys.prefix,'pythonw.exe'))"') do set "PYTHONW=%%p"

if not exist "%PYTHONW%" (
    for /f "tokens=*" %%p in ('python -c "import sys,os; print(os.path.join(sys.prefix,'python.exe'))"') do set "PYTHONW=%%p"
)

:: Desktop shortcut via PowerShell (single line to avoid ^ passthrough issues)
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut('%DESKTOP%\VPN Switcher.lnk'); $s.TargetPath='%PYTHONW%'; $s.Arguments='\"%SCRIPT%\"'; $s.WorkingDirectory='%INSTALL_DIR%'; $s.IconLocation='%ICON%'; $s.Description='VPN Switcher'; $s.Save()"

echo [OK] Desktop shortcut created: %DESKTOP%\VPN Switcher.lnk

:: ── Done ──────────────────────────────────────────────────────────────────────
echo.
echo [4/4] Setup complete!
echo.
echo ============================================================
echo  VPN Switcher is ready!
echo.
echo   Desktop shortcut : VPN Switcher.lnk
echo   Starts with Windows: yes (toggle off in Settings)
echo   To uninstall     : run uninstall.bat
echo ============================================================
echo.

:: Launch the app now
echo Launching VPN Switcher...
start "" "%PYTHONW%" "%SCRIPT%"
timeout /t 2 /nobreak >nul
