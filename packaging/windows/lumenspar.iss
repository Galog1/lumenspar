; Inno Setup script for the Lumenspar Windows installer.
; Build after PyInstaller has produced dist\Lumenspar\, from the repository root:
;     iscc /DAppVersion=0.1.0 packaging\windows\lumenspar.iss
; Output: dist\installer\Lumenspar-Setup-<version>.exe

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

[Setup]
; The AppId identifies this application to Windows for upgrades and
; uninstalling. It must never change between releases.
AppId={{04B057B8-5A25-44B5-8D3E-C62F5DBE60DD}
AppName=Lumenspar
AppVersion={#AppVersion}
AppVerName=Lumenspar {#AppVersion}
AppPublisher=Galog1
AppPublisherURL=https://github.com/Galog1/lumenspar
AppSupportURL=https://github.com/Galog1/lumenspar/issues
DefaultDirName={autopf}\Lumenspar
DefaultGroupName=Lumenspar
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
; Installing needs no administrator rights (it goes under the user's own
; Programs folder) unless the user picks "install for all users". The app
; itself always runs elevated -- see uac_admin in lumenspar.spec.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=lumenspar.ico
UninstallDisplayIcon={app}\Lumenspar.exe
OutputDir=..\..\dist\installer
OutputBaseFilename=Lumenspar-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\Lumenspar\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Lumenspar"; Filename: "{app}\Lumenspar.exe"
Name: "{autodesktop}\Lumenspar"; Filename: "{app}\Lumenspar.exe"; Tasks: desktopicon

[Run]
; shellexec is required: the exe asks for administrator rights, and launching
; such a program the plain way fails (error 740) instead of showing the prompt.
Filename: "{app}\Lumenspar.exe"; Description: "{cm:LaunchProgram,Lumenspar}"; Flags: shellexec postinstall skipifsilent nowait

; Settings in %APPDATA%\lumenspar and exports in Documents\Lumenspar are the
; user's data and are deliberately left in place on uninstall.
