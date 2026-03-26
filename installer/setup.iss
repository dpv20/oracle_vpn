; VPN Switcher — Inno Setup 6 script
; Compile this with Inno Setup 6: https://jrsoftware.org/isdl.php

#define AppName "VPN Switcher"
#define AppVersion "1.0"
#define AppExeName "VPNSwitcher.exe"
#define AppPublisher "Oracle IT"

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
SetupIconFile=
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Require the app to be uninstalled before reinstalling
CloseApplications=yes
RestartIfNeededByRun=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startupentry"; Description: "Start VPN Switcher automatically when Windows starts (recommended)"; GroupDescription: "Additional tasks:"; Flags: checked
Name: "desktopicon";  Description: "Create a &desktop shortcut";                                        GroupDescription: "Additional tasks:"; Flags: unchecked

[Files]
; All PyInstaller output files
Source: "..\dist\VPNSwitcher\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";    Filename: "{app}\{#AppExeName}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; Run at Windows startup (per-user)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#AppName}"; \
    ValueData: """{app}\{#AppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: startupentry

[Run]
; Launch the app after installation finishes
Filename: "{app}\{#AppExeName}"; \
    Description: "Launch {#AppName} now"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
; Kill the app before uninstalling
Filename: "taskkill"; Parameters: "/F /IM {#AppExeName}"; Flags: runhidden; RunOnceId: "KillApp"

[Code]
// Remove startup registry entry on uninstall if it was added by the app itself
// (the [Registry] block handles this via uninsdeletevalue, this is just a safety net)
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
  end;
end;
