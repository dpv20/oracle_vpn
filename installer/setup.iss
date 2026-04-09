; VPN Switcher — Inno Setup 6 script
; Compile via build.bat or manually with Inno Setup 6: https://jrsoftware.org/isdl.php

#define AppName "VPN Switcher"
#define AppVersion "1.0.0"
#define AppExeName "VPNSwitcher.exe"
#define AppPublisher "Oracle IT — Diego Pavez Verdi"

[Setup]
AppId={{A3F2C8D1-4B5E-4F9A-8C3D-2E7B1A6F0E4D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\Output
OutputBaseFilename=VPNSwitcher-Setup
SetupIconFile=..\logo_cuadrado.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartIfNeededByRun=no
; Minimum Windows 10
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startupentry"; Description: "Start VPN Switcher automatically when Windows starts (recommended)"; GroupDescription: "Additional tasks:"; Flags: checked
Name: "desktopicon";  Description: "Create a &desktop shortcut"; GroupDescription: "Additional tasks:"; Flags: checked

[Files]
; Single-file PyInstaller output
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}";         Filename: "{app}\{#AppExeName}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; Run at Windows startup (per-user)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#AppName}"; \
    ValueData: """{app}\{#AppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: startupentry

[Run]
Filename: "{app}\{#AppExeName}"; \
    Description: "Launch {#AppName} now"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM {#AppExeName}"; Flags: runhidden; RunOnceId: "KillApp"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
end;
