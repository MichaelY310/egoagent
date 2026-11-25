[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonWindowless = Join-Path $repoRoot '.venv\Scripts\pythonw.exe'
$launcher = Join-Path $PSScriptRoot 'browser_launcher.py'
if (-not (Test-Path -LiteralPath $pythonWindowless)) { throw 'Install the repository .venv first.' }
if (-not (Test-Path -LiteralPath $launcher)) { throw 'Browser launcher source is missing.' }
$shortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'EgoAgent 浏览器版.lnk'
$shortcutShell = New-Object -ComObject WScript.Shell
$shortcut = $shortcutShell.CreateShortcut($shortcutPath)
$launcherArguments = '"' + $launcher + '"'
if ((Test-Path -LiteralPath $shortcutPath) -and
    (($shortcut.TargetPath -ne $pythonWindowless) -or ($shortcut.Arguments -ne $launcherArguments))) {
    throw "Shortcut already belongs to another installation: $shortcutPath"
}
$shortcut.TargetPath = $pythonWindowless
$shortcut.Arguments = $launcherArguments
$shortcut.WorkingDirectory = $repoRoot
$shortcut.WindowStyle = 7
$icon = Join-Path $repoRoot '.runtime\desktop\egoagent.ico'
if (Test-Path -LiteralPath $icon) { $shortcut.IconLocation = "$icon,0" }
else { $shortcut.IconLocation = (Join-Path $env:WINDIR 'System32\shell32.dll') + ',14' }
$shortcut.Description = '启动或复用 EgoAgent 后台并打开默认浏览器；不打开桌面版窗口。'
$shortcut.Save()
Write-Host "Ready: $shortcutPath"
