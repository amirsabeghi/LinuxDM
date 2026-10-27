Unicode True
!include "MUI2.nsh"
!include "LogicLib.nsh"
Name "LinuxDM"
OutFile "../dist/LinuxDM-0.5.0-Setup-x64.exe"
InstallDir "$LOCALAPPDATA\Programs\LinuxDM"
RequestExecutionLevel user
SetCompressor /SOLID lzma
Var PythonDir
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
Section "LinuxDM" SEC_MAIN
  SetRegView 64
  SetOutPath "$INSTDIR"
  File /r "../.build/windows-payload/*"
  ReadRegStr $PythonDir HKCU "Software\Python\PythonCore\3.13\InstallPath" ""
  ${If} $PythonDir == ""
    ReadRegStr $PythonDir HKLM "Software\Python\PythonCore\3.13\InstallPath" ""
  ${EndIf}
  ${If} $PythonDir == ""
    SetOutPath "$TEMP\LinuxDM-setup"
    File /oname=python-3.13.16-amd64.exe "../.build/python-runtime-verified.exe"
    ExecWait '"$TEMP\LinuxDM-setup\python-3.13.16-amd64.exe" /quiet InstallAllUsers=0 Include_launcher=0 Include_test=0 Include_doc=0 Include_tcltk=1 Include_pip=1 PrependPath=0 Shortcuts=0' $0
    ${If} $0 != 0
    ${AndIf} $0 != 3010
      MessageBox MB_ICONSTOP "Python installation failed (code $0). Install Python 3.13 x64 with Tkinter, then rerun setup."
      Abort
    ${EndIf}
    ReadRegStr $PythonDir HKCU "Software\Python\PythonCore\3.13\InstallPath" ""
    Delete "$TEMP\LinuxDM-setup\python-3.13.16-amd64.exe"
    RMDir "$TEMP\LinuxDM-setup"
  ${EndIf}
  IfFileExists "$PythonDir\pythonw.exe" +3 0
    MessageBox MB_ICONSTOP "Python 3.13 x64 was not found. Install it with Tkinter and rerun setup."
    Abort
  SetOutPath "$INSTDIR"
  ExecWait '"$PythonDir\python.exe" -m linuxdm.windows_install' $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "Browser bridge registration failed (code $0)."
    Abort
  ${EndIf}
  CreateDirectory "$SMPROGRAMS\LinuxDM"
  CreateShortcut "$SMPROGRAMS\LinuxDM\LinuxDM.lnk" "$PythonDir\pythonw.exe" '$\"$INSTDIR\launch.pyw$\"'
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LinuxDM" "DisplayName" "LinuxDM"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LinuxDM" "DisplayVersion" "0.5.0"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LinuxDM" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
SectionEnd
Section "Uninstall"
  SetRegView 64
  DeleteRegKey HKCU "Software\Google\Chrome\NativeMessagingHosts\io.linuxdm.bridge"
  DeleteRegKey HKCU "Software\Mozilla\NativeMessagingHosts\io.linuxdm.bridge"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "LinuxDM"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LinuxDM"
  Delete "$SMPROGRAMS\LinuxDM\LinuxDM.lnk"
  RMDir "$SMPROGRAMS\LinuxDM"
  RMDir /r "$INSTDIR\linuxdm"
  RMDir /r "$INSTDIR\vendor"
  RMDir /r "$INSTDIR\chrome-extension"
  RMDir /r "$INSTDIR\firefox-extension"
  RMDir /r "$INSTDIR\bin"
  Delete "$INSTDIR\launch.pyw"
  Delete "$INSTDIR\native_host_entry.py"
  Delete "$INSTDIR\native-host.cmd"
  Delete "$INSTDIR\chrome-native-host.json"
  Delete "$INSTDIR\firefox-native-host.json"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
SectionEnd
