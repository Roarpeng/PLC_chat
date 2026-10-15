' 启动项目（静默）：双击运行，不弹任何终端窗口
' 实际逻辑在 tools\quiet_start.py（pythonw 无窗口执行：网关→前端→打开界面）
Option Explicit
Dim sh, fso, dir, pyw
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir

pyw = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Python\pythoncore-3.14-64\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw"

sh.Run "cmd /c """ & pyw & """ tools\quiet_start.py >> .devctl\logs\launcher.log 2>&1", 0, False
