; 脚本由 Inno Setup 脚本向导生成。
; 有关创建 Inno Setup 脚本文件的详细信息，请参阅帮助文档！

#define MyAppName "小树时钟"
#define MyAppVersion "0.18.1"
#define MyAppPublisher "小树工作室"
#define MyAppURL "https://clock.zsxiaoshu.cn/"
#define MyAppExeName "小树时钟.exe"
#define MyAppAssocName MyAppName + "插件文件"
#define MyAppAssocExt ".ltcplugin"
#define MyAppAssocKey StringChange(MyAppAssocName, " ", "") + MyAppAssocExt
#define MyAppAssocName2 MyAppName + "配置文件"
#define MyAppAssocExt2 ".ltcconfig"
#define MyAppAssocKey2 StringChange(MyAppAssocName2, " ", "") + MyAppAssocExt2
#define MyAppAssocName3 MyAppName + "布局文件"
#define MyAppAssocExt3 ".ltlayout"
#define MyAppAssocKey3 StringChange(MyAppAssocName3, " ", "") + MyAppAssocExt3

[Setup]
; 注意：AppId 的值唯一标识此应用程序。不要在其他应用程序的安装程序中使用相同的 AppId 值。
; (若要生成新的 GUID，请在 IDE 中单击 "工具|生成 GUID"。)
AppId={{28391675-B322-4CC4-98C0-55A3774787B7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
;AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\Little Tree Clock
UninstallDisplayIcon={app}\{#MyAppExeName}
; "ArchitecturesAllowed=x64compatible" 指定
; 安装程序只能在 x64 和 Windows 11 on Arm 上运行。
ArchitecturesAllowed=x64compatible
; "ArchitecturesInstallIn64BitMode=x64compatible" 要求
; 在 X64 或 Windows 11 on Arm 上以 "64-位模式" 进行安装，
; 这意味着它应该使用本地 64 位 Program Files 目录
; 和注册表的 64 位视图。
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
DisableProgramGroupPage=yes
LicenseFile=D:\下载\gpl-3.0.rtf
; 取消注释以下行以在非管理安装模式下运行 (仅为当前用户安装)。
;PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=D:\下载
OutputBaseFilename=Little_Tree_Clock_{#MyAppVersion}_Installer_win_amd64
SetupIconFile=D:\Users\张秫\onedrive\OneDrive - 小树科技\图片\小树时钟.ico
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"
Name: "english"; MessagesFile: "compiler:Languages\English.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "D:\下载\小树时钟\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "D:\下载\小树时钟\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 注意：不要在任何共享系统文件上使用 "Flags: ignoreversion" 

[Registry]
; 注册 .ltcplugin 文件类型
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocExt}\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppAssocKey}"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey}"; ValueType: string; ValueName: ""; ValueData: "{#MyAppAssocName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
; 注册 .ltcconfig 文件类型
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocExt2}\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppAssocKey2}"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey2}"; ValueType: string; ValueName: ""; ValueData: "{#MyAppAssocName2}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey2}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey2}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
; 注册 .ltlayout 文件类型
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocExt3}\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppAssocKey3}"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey3}"; ValueType: string; ValueName: ""; ValueData: "{#MyAppAssocName3}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey3}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey3}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

