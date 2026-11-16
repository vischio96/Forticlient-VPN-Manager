; Inno Setup script for FortiClient VPN Manager
; Build:  ISCC.exe /DAppVersion=1.0.0 installer\FortiVPNManager.iss
; Input:  dist\FortiVPNManager\  (PyInstaller onedir build, see FortiVPNManager.spec)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "FortiClient VPN Manager"
#define AppExe "FortiVPNManager.exe"
#define AppPublisher "vischio96"
#define AppURL "https://github.com/vischio96/Forticlient-VPN-Manager"

[Setup]
AppId={{6C1F2B7E-4E2B-4C9A-9C3E-5B8E1D2F7A41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\FortiVPN Manager
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; per-user install by default (no admin needed), admin install still possible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
OutputDir=..\dist
OutputBaseFilename=FortiVPNManager-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
CloseApplications=force
RestartApplications=no
ShowLanguageDialog=auto
LicenseFile=..\LICENSE

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
italian.AutoStart=Avvia automaticamente all'accesso a Windows
english.AutoStart=Start automatically when signing in to Windows
italian.LaunchApp=Avvia {#AppName}
english.LaunchApp=Launch {#AppName}

[Tasks]
Name: "autostart"; Description: "{cm:AutoStart}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\FortiVPNManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; clean the previous build's runtime before copying the new one
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; lets the app know it was installed (enables in-app updates)
Root: HKA; Subkey: "Software\FortiVPNManager"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "FortiVPNManager"; ValueData: """{app}\{#AppExe}"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
; interactive install: optional checkbox on the last page
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent
; silent install (in-app update): relaunch the app automatically
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden; RunOnceId: "KillApp"

[Code]
const
  AppMutexName = 'FortiVPNManagerMutex';

{ Wait for the running app to quit (in-app update), otherwise close it. }
procedure CloseRunningApp();
var
  i, rc: Integer;
begin
  for i := 1 to 30 do
  begin
    if not CheckForMutexes(AppMutexName) then
      Exit;
    Sleep(500);
  end;
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, rc);
  Sleep(1000);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  CloseRunningApp();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { the app may have registered itself for autostart from its settings }
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'FortiVPNManager');
  end;
end;
