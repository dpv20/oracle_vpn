@echo off
setlocal EnableDelayedExpansion
title VPN Switcher — Build
cd /d "%~dp0"

echo.
echo ============================================================
echo  VPN Switcher — Build Script
echo ============================================================
echo.

:: ── 1. Install Python if missing ─────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [!] Python not found. Downloading and installing Python 3.12...
    powershell -NoProfile -Command ^
        "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe' -OutFile '%TEMP%\python_installer.exe'"
    "%TEMP%\python_installer.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1
    del "%TEMP%\python_installer.exe"
    echo [!] Python installed. Please re-run this script.
    pause & exit /b 0
)
echo [OK] Python found.
python --version

:: ── 2. Install pip dependencies ───────────────────────────────────────────────
echo.
echo [1/4] Installing dependencies...
python -m pip install --upgrade pip --quiet
python -m pip install --upgrade --quiet ^
    pillow ^
    pywinauto ^
    pystray ^
    comtypes ^
    pyinstaller

if errorlevel 1 (
    echo [ERROR] pip install failed. Check your internet connection.
    pause & exit /b 1
)
echo [OK] Dependencies ready.

:: ── 3. PyInstaller bundle ─────────────────────────────────────────────────────
echo.
echo [2/4] Building executable...
if exist dist\VPNSwitcher.exe del /q dist\VPNSwitcher.exe
if exist build rmdir /s /q build

python -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name VPNSwitcher ^
    --icon assets\logo_cuadrado.ico ^
    --add-data "assets\logo_cuadrado.png;assets" ^
    --add-data "assets\logo_cuadrado_rojo.png;assets" ^
    --add-data "assets\logo_cuadrado_verde.png;assets" ^
    --paths src ^
    --hidden-import pywinauto.backends.win32_hooks ^
    --hidden-import comtypes.stream ^
    --hidden-import pystray._win32 ^
    --hidden-import PIL._tkinter_finder ^
    --hidden-import win32api ^
    --hidden-import win32con ^
    --hidden-import win32gui ^
    src\main.py

if not exist dist\VPNSwitcher.exe (
    echo [ERROR] PyInstaller failed. See output above.
    pause & exit /b 1
)
echo [OK] dist\VPNSwitcher.exe created.

:: ── 4. Inno Setup installer ───────────────────────────────────────────────────
echo.
echo [3/4] Looking for Inno Setup 6...
set ISCC=
for %%P in (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    "C:\Program Files\Inno Setup 6\ISCC.exe"
) do (
    if exist %%P set ISCC=%%~P
)

if not defined ISCC (
    echo [!] Inno Setup 6 not found — skipping installer creation.
    echo     Download it free from: https://jrsoftware.org/isdl.php
    echo     Then re-run this script to also produce the .exe installer.
    goto :done
)

echo [4/4] Creating installer with Inno Setup...
if not exist Output mkdir Output
"%ISCC%" installer\setup.iss
if errorlevel 1 (
    echo [ERROR] Inno Setup failed.
    pause & exit /b 1
)

:done
echo.
echo ============================================================
echo  Build complete!
if exist dist\VPNSwitcher.exe (
    echo   Standalone EXE : dist\VPNSwitcher.exe
)
if exist Output\VPNSwitcher-Setup.exe (
    echo   Installer      : Output\VPNSwitcher-Setup.exe
)
echo ============================================================
echo.
pause
