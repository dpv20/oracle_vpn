@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo  VPN Switcher — Build Script
echo ============================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo         Download it from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/4] Installing / upgrading dependencies...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
python -m pip install pyinstaller --quiet

echo [2/4] Cleaning previous build...
if exist dist\VPNSwitcher rmdir /s /q dist\VPNSwitcher
if exist build\VPNSwitcher rmdir /s /q build\VPNSwitcher

echo [3/4] Building executable with PyInstaller...
python -m PyInstaller ^
    --name VPNSwitcher ^
    --onedir ^
    --windowed ^
    --icon NONE ^
    --hidden-import pystray._win32 ^
    --hidden-import PIL._tkinter_finder ^
    --hidden-import win32api ^
    --hidden-import win32con ^
    --hidden-import win32gui ^
    --add-data "src;src" ^
    --paths src ^
    src\main.py

if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller failed. See output above.
    pause
    exit /b 1
)

echo.
echo [4/4] Build complete!
echo.
echo  Output: dist\VPNSwitcher\VPNSwitcher.exe
echo.
echo  Next step: open installer\setup.iss in Inno Setup 6
echo  to create the installable VPNSwitcher-Setup.exe
echo.
echo  Download Inno Setup from: https://jrsoftware.org/isdl.php
echo ============================================================
pause
