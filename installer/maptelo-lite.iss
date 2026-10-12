; Maptelo Lite for one person on Windows: records a process and makes its map (steps, SOP,
; BPMN, report); no robot. No administrator rights needed. A prototype: not signed yet.
; Built by CI (.github/workflows/package.yml) from the portable Lite folder:
;   iscc /DAppVersion=0.0.1 /DSource=..\build\MapteloLite /DOutput=..\build installer\maptelo-lite.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef Source
  #define Source "..\build\MapteloLite"
#endif
#ifndef Output
  #define Output "..\build"
#endif

[Setup]
AppId={{97A4A755-23E7-4683-BD5F-1304CE6766C5}
AppName=Maptelo Lite
AppVersion={#AppVersion}
AppPublisher=Maptelo
DefaultDirName={localappdata}\Programs\Maptelo Lite
DefaultGroupName=Maptelo Lite
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#Output}
OutputBaseFilename=Maptelo-Lite-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=Maptelo Lite {#AppVersion}

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#Source}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{userdocs}\Maptelo Lite"

[Icons]
Name: "{group}\Maptelo Lite"; Filename: "{app}\Maptelo Lite.cmd"; WorkingDir: "{userdocs}\Maptelo Lite"
Name: "{group}\Odinstaluj Maptelo Lite"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\Maptelo Lite.cmd"; Description: "Uruchom Maptelo Lite"; Flags: postinstall nowait skipifsilent shellexec

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python\Lib\site-packages\__pycache__"
