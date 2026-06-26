; Inno Setup script for keycast (see docs/PACKAGING.md and
; docs/adr/006-windows-installer.md).
;
; Wraps the PyInstaller folder build (dist/keycast/, produced by keycast.spec on
; windows-latest) into keycast-setup.exe: a Start Menu shortcut, an
; Add/Remove-Programs uninstall entry, and an optional desktop shortcut. Ships
; ALONGSIDE keycast-windows.zip (the zip stays the portable / no-install option).
;
; The version is injected from CI, not hard-coded, so the tag stays the single
; source of truth (hatch-vcs derives the Python __version__ from the same tag):
;
;     iscc /DMyAppVersion=1.2.3 packaging\keycast.iss
;
; A default (0.0.0) lets the script compile in a PR check without a release tag.
;
; The installer is UNSIGNED (Authenticode signing, #6, is closed as cost-gated),
; so first run still trips SmartScreen exactly like the zip — see README.md. When
; a certificate is acquired, sign both keycast.exe and this keycast-setup.exe.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "keycast"
#define MyAppExeName "keycast.exe"
#define MyAppPublisher "Hasan Sezer Tasan"
#define MyAppURL "https://github.com/hasansezertasan/keycast"

[Setup]
; A fixed AppId is what ties an upgrade/uninstall to a prior install — it must
; never change across versions, or each release would install side-by-side
; instead of upgrading in place.
AppId={{b34f4c46-6969-4e3b-b63d-c715ca4dadbc}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
; Let the user pick per-user (no admin) vs per-machine (admin) at install time;
; `dialog` adds the wizard page, and {auto*} constants below resolve to the
; matching locations. Per-user is the friendlier default for an unsigned app
; (no UAC elevation stacked on top of the SmartScreen prompt).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
; keycast is x64-only (single-arch Astral CPython bundle); refuse to install on
; arches that cannot run it rather than fail mysteriously at first launch. `x64`
; is the value that compiles across all Inno 6.x (the newer `x64compatible` alias
; needs 6.3+, not guaranteed on the runner).
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
OutputDir=.
OutputBaseFilename=keycast-setup
SetupIconFile=keycast.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole PyInstaller folder build. Source paths are relative to this script
; (packaging/), so dist/keycast/ at the repo root is one level up.
Source: "..\dist\keycast\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; Install-source marker: detect_install_source() (keycast.updates.sources) reads
; this beside keycast.exe to recommend the installer/uninstall update path rather
; than a zip re-download. Deliberately NOT part of dist/keycast/, so the .zip
; never carries it and zip installs keep classifying as GITHUB_RELEASE.
Source: "install-source"; DestDir: "{app}"; DestName: ".install-source"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
