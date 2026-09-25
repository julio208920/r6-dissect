; Inno Setup script for the Windows installer: dist\R6MatchStats-Setup.exe.
; build.ps1 compiles it after PyInstaller:  iscc /DAppVersion=1.0.0 /DAppRepo=owner/name desktop\installer.iss
; Installs for the current user only (no admin prompt), adds Start menu and
; desktop shortcuts, and an uninstaller in Settings > Apps.

#ifndef AppRepo
  #define AppRepo "julio208920/r6-dissect"
#endif
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; keep AppId the same forever: it's how a new version finds and replaces the old one
AppId={{A8C74B18-CB05-4182-9520-EA0BAE2BBB9C}
AppName=R6 Match Stats
AppVersion={#AppVersion}
AppVerName=R6 Match Stats {#AppVersion}
AppPublisher=R6 Match Stats
AppPublisherURL=https://github.com/{#AppRepo}
AppUpdatesURL=https://github.com/{#AppRepo}/releases/latest
DefaultDirName={autopf}\R6 Match Stats
DefaultGroupName=R6 Match Stats
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=R6MatchStats-Setup
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\R6MatchStats.exe
UninstallDisplayName=R6 Match Stats
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; closes a running copy before updating it
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; an update replaces the whole app, so files from the old version don't linger
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\R6MatchStats\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\R6 Match Stats"; Filename: "{app}\R6MatchStats.exe"
Name: "{autodesktop}\R6 Match Stats"; Filename: "{app}\R6MatchStats.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\R6MatchStats.exe"; Description: "{cm:LaunchProgram,R6 Match Stats}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; the app's log and window data, in %LOCALAPPDATA%\R6MatchStats
Type: filesandordirs; Name: "{localappdata}\R6MatchStats"
