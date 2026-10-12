; Maptelo Lite for one person on Windows: records a process and makes its map (steps, SOP,
; BPMN, report); no robot. Installed where the person chooses (the Desktop unless they say
; otherwise) and nothing in Windows' own folders or registry: the processes, the sign-ins
; and the settings stay in that folder too. No administrator rights. A prototype: not
; code-signed yet. Built by CI from the portable Lite folder:
;   iscc /DAppVersion=0.1.0 /DSource=..\build\MapteloLite /DOutput=..\build installer\maptelo-lite.iss
; Its pictures (installer\lite) come from tools\package\lite_pictures.py.

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
AppVerName=Maptelo Lite {#AppVersion}
AppPublisher=Maptelo
AppPublisherURL=https://maptelo.dev
AppSupportURL=https://github.com/krapcys1-maker/maptelo-lite/issues
AppUpdatesURL=https://github.com/krapcys1-maker/maptelo-lite/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Maptelo Lite
VersionInfoDescription=Maptelo Lite
; where the person says, the Desktop first; for this person only, no administrator
DefaultDirName={userdesktop}\Maptelo Lite
; not the folder of an earlier install (an older Lite kept it in the registry)
UsePreviousAppDir=no
DisableDirPage=no
AppendDefaultDirName=yes
DirExistsWarning=no
DisableWelcomePage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
; nothing in the registry: the folder holds the program and its uninstaller, and deleting
; the folder removes Maptelo Lite whole
CreateUninstallRegKey=no
UninstallFilesDir={app}\uninstall
SetupIconFile=lite\maptelo-lite.ico
WizardStyle=modern
WizardImageFile=lite\wizard-202.bmp,lite\wizard-336.bmp,lite\wizard-430.bmp
WizardSmallImageFile=lite\small-58.bmp,lite\small-97.bmp,lite\small-124.bmp
ShowLanguageDialog=auto
OutputDir={#Output}
OutputBaseFilename=Maptelo-Lite-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
polish.WorkFolder=Procesy
english.WorkFolder=Processes
polish.Uninstall=Odinstaluj Maptelo Lite
english.Uninstall=Uninstall Maptelo Lite
polish.Shortcuts=Skróty poza folderem programu (skrót „Maptelo Lite” jest zawsze tworzony w folderze programu):
english.Shortcuts=Shortcuts outside the program folder (the “Maptelo Lite” shortcut is always created in the program folder):
polish.DesktopIcon=Skrót na pulpicie
english.DesktopIcon=Desktop shortcut
polish.StartMenuIcon=Skrót w menu Start
english.StartMenuIcon=Start menu shortcut
polish.Launch=Uruchom Maptelo Lite
english.Launch=Start Maptelo Lite
polish.About=Dokumentacja procesu z jednego nagrania
english.About=Process documentation from a single recording

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:Shortcuts}"; Flags: unchecked
Name: "startmenu"; Description: "{cm:StartMenuIcon}"; GroupDescription: "{cm:Shortcuts}"; Flags: unchecked

[InstallDelete]
; An update starts from a clean Python: what the earlier version installed must not stay (an
; old package's metadata would give its version, an old module would still import). The
; person's processes and sign-ins are in other folders.
Type: filesandordirs; Name: "{app}\python"

[Files]
Source: "{#Source}\*"; Excludes: "Maptelo Lite.cmd,maptelo-lite.ico"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Source}\maptelo-lite.ico"; DestDir: "{app}"; Attribs: hidden; Flags: ignoreversion

[Dirs]
Name: "{app}\{cm:WorkFolder}"
Name: "{app}\data"

[Icons]
Name: "{app}\Maptelo Lite"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m maptelo.lite studio --workspace ""{app}\{cm:WorkFolder}"" --data ""{app}\data"""; WorkingDir: "{app}"; IconFilename: "{app}\maptelo-lite.ico"; Comment: "{cm:About}"
Name: "{app}\{cm:Uninstall}"; Filename: "{uninstallexe}"; IconFilename: "{app}\maptelo-lite.ico"
Name: "{userdesktop}\Maptelo Lite"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m maptelo.lite studio --workspace ""{app}\{cm:WorkFolder}"" --data ""{app}\data"""; WorkingDir: "{app}"; IconFilename: "{app}\maptelo-lite.ico"; Comment: "{cm:About}"; Tasks: desktopicon
Name: "{userprograms}\Maptelo Lite"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m maptelo.lite studio --workspace ""{app}\{cm:WorkFolder}"" --data ""{app}\data"""; WorkingDir: "{app}"; IconFilename: "{app}\maptelo-lite.ico"; Comment: "{cm:About}"; Tasks: startmenu

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-m maptelo.lite studio --workspace ""{app}\{cm:WorkFolder}"" --data ""{app}\data"""; WorkingDir: "{app}"; Description: "{cm:Launch}"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; the program and what it keeps for the person (sign-ins: cookies, settings, its log); their
; processes and maps stay, and so the folder with them
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\data"
Type: dirifempty; Name: "{app}\{cm:WorkFolder}"
Type: dirifempty; Name: "{app}"
