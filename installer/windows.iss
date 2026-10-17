; Inno-Setup-Skript für den Windows-Installer von AkustikMess.
; Wird von tools/release.py aufgerufen:  ISCC /DAppVersion=1.2.3 /DSourceDir=... /DOutputDir=... windows.iss
;
; Installation pro Benutzer (kein Admin nötig) → Updates laufen still ohne Windows-Abfrage.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
; rein numerische Form für die Datei-Eigenschaften (z. B. 0.5.0.1 für 0.5.0-beta.1)
#ifndef NumVersion
  #define NumVersion "0.0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\AkustikMess"
#endif
#ifndef OutputDir
  #define OutputDir "..\release_build"
#endif
#ifndef OutputName
  #define OutputName "AkustikMess-" + AppVersion + "-Windows-Setup"
#endif

[Setup]
AppId={{6F1C2A3E-8B7D-4E5F-9A0B-1C2D3E4F5A6B}
AppName=AkustikMess
AppVersion={#AppVersion}
AppVerName=AkustikMess {#AppVersion}
AppPublisher=Alex Kulow
AppCopyright=© 2026 Alex Kulow. Alle Rechte vorbehalten.
VersionInfoProductName=AkustikMess
DefaultDirName={localappdata}\Programs\AkustikMess
DefaultGroupName=AkustikMess
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\AkustikMess.exe
UninstallDisplayName=AkustikMess
; laufendes Programm vor dem Ersetzen der Dateien schließen (wichtig für Updates)
CloseApplications=force
RestartApplications=no
VersionInfoVersion={#NumVersion}

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\docs\THIRD-PARTY-NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; alte Programmdateien entfernen, damit keine Reste früherer Versionen geladen werden
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\AkustikMess"; Filename: "{app}\AkustikMess.exe"
Name: "{group}\AkustikMess deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\AkustikMess"; Filename: "{app}\AkustikMess.exe"; Tasks: desktopicon

[Run]
; normale Installation: Häkchen „AkustikMess starten“
Filename: "{app}\AkustikMess.exe"; Description: "{cm:LaunchProgram,AkustikMess}"; Flags: nowait postinstall skipifsilent
; stilles Update aus dem Programm heraus: danach automatisch neu starten
Filename: "{app}\AkustikMess.exe"; Flags: nowait; Check: WizardSilent
