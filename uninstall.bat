@echo off
title VPN Switcher — Uninstall

echo.
echo Uninstalling VPN Switcher...

:: Kill the app if running
taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq VPN Switcher" >nul 2>&1

:: Remove startup registry entry
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "VPN Switcher" /f >nul 2>&1
echo [OK] Removed from Windows startup.

:: Remove desktop shortcut
if exist "%USERPROFILE%\Desktop\VPN Switcher.lnk" (
    del "%USERPROFILE%\Desktop\VPN Switcher.lnk"
    echo [OK] Desktop shortcut removed.
)

:: Remove installed app data folder
if exist "%LOCALAPPDATA%\VPNSwitcher" (
    rmdir /s /q "%LOCALAPPDATA%\VPNSwitcher"
    echo [OK] Removed %LOCALAPPDATA%\VPNSwitcher.
)

echo.
echo VPN Switcher uninstalled.
echo You can now delete this folder.
echo.
pause
