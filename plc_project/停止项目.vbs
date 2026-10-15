' 停止项目（静默）：一键停掉全部 devctl 管理的服务，资源归零
Option Explicit
Dim sh, fso, dir, pyw
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir

pyw = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Python\pythoncore-3.14-64\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw"

sh.Run "cmd /c """ & pyw & """ tools\devctl.py down --all >> .devctl\logs\launcher.log 2>&1", 0, False
