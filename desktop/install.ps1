[CmdletBinding()]
param([switch]$NoShortcuts)
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$desktopOut = Join-Path $repoRoot '.runtime\desktop'
$executable = Join-Path $desktopOut 'EgoAgent.exe'
$installationRoot = $desktopOut
# Never overwrite loaded binaries or force-close an editor with unsaved work.
# Use a fresh release directory when this installation is running; shortcuts
# point to the new build while old windows and backend processes stay alive.
$runningInstallation = @(Get-Process -Name EgoAgent,EgoAgent.next -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and $_.Path.StartsWith($installationRoot + '\', [StringComparison]::OrdinalIgnoreCase)
})
if ($runningInstallation.Count) {
    $release = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
    $desktopOut = Join-Path $installationRoot ('releases\' + $release)
    $executable = Join-Path $desktopOut 'EgoAgent.exe'
    Write-Host 'Installing alongside running windows; no editors or backend services will be stopped.'
}
$sdkCache = Join-Path $repoRoot '.runtime\desktop-sdk'
$sdkVersion = '1.0.4022.49'
$sdkHash = 'EE9DE67E5BB9EF3A96C5689B2EFC8188E2DF160A0E79234C0404243782FDE5FB'
$sdkPackage = Join-Path $sdkCache 'webview2.nupkg'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Windows x64 / .NET Framework 4.8 is required.' }
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot '.venv\Scripts\python.exe'))) { throw 'Install the repository .venv first.' }
New-Item -ItemType Directory -Path $desktopOut,$sdkCache -Force | Out-Null
if (-not (Test-Path -LiteralPath $sdkPackage)) {
    Write-Host 'Downloading the Microsoft WebView2 SDK (not a browser or model)...'
    $downloadFile = $sdkPackage + '.download'
    Invoke-WebRequest -UseBasicParsing -Uri "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/$sdkVersion/microsoft.web.webview2.$sdkVersion.nupkg" -OutFile $downloadFile -TimeoutSec 180
    if ((Get-FileHash -LiteralPath $downloadFile -Algorithm SHA256).Hash -ne $sdkHash) { throw 'WebView2 SDK SHA256 mismatch; not using this download.' }
    Move-Item -LiteralPath $downloadFile -Destination $sdkPackage
}
if ((Get-FileHash -LiteralPath $sdkPackage -Algorithm SHA256).Hash -ne $sdkHash) { throw 'WebView2 SDK cache SHA256 mismatch.' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$sdkZip = [IO.Compression.ZipFile]::OpenRead($sdkPackage)
try {
    $sdkEntries = @{
        'lib/net462/Microsoft.Web.WebView2.Core.dll' = 'Microsoft.Web.WebView2.Core.dll'
        'lib/net462/Microsoft.Web.WebView2.WinForms.dll' = 'Microsoft.Web.WebView2.WinForms.dll'
        'runtimes/win-x64/native/WebView2Loader.dll' = 'WebView2Loader.dll'
        'LICENSE.txt' = 'WebView2-LICENSE.txt'
    }
    foreach ($entryPath in $sdkEntries.Keys) {
        $entry = $sdkZip.GetEntry($entryPath)
        if ($null -eq $entry) { throw "SDK entry missing: $entryPath" }
        $destFile = Join-Path $desktopOut $sdkEntries[$entryPath]
        $inputStream = $entry.Open()
        try {
            $outputStream = [IO.File]::Create($destFile)
            try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose() }
        } finally { $inputStream.Dispose() }
    }
} finally { $sdkZip.Dispose() }

# Render the existing EgoAgent graph icon with a purple application background.
# This is generated application artwork, not a new binary source dependency.
Add-Type -AssemblyName System.Drawing
$iconPath = Join-Path $desktopOut 'egoagent.ico'
$bitmap = New-Object Drawing.Bitmap 128,128
$graphics = [Drawing.Graphics]::FromImage($bitmap)
try {
    $graphics.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.Clear([Drawing.Color]::FromArgb(110,87,239))
    $pen = New-Object Drawing.Pen ([Drawing.Color]::White),7
    try {
        $pen.StartCap = $pen.EndCap = [Drawing.Drawing2D.LineCap]::Round
        foreach ($line in @(@(27,31,62,31),@(27,64,62,64),@(27,97,62,97),@(77,31,91,31),@(91,31,105,48),@(77,64,108,64),@(77,97,91,97),@(91,97,105,80))) {
            $graphics.DrawLine($pen,[single]$line[0],[single]$line[1],[single]$line[2],[single]$line[3])
        }
        foreach ($point in @(@(22,31),@(22,64),@(22,97),@(109,64),@(104,48),@(104,80))) {
            $graphics.FillEllipse([Drawing.Brushes]::White, [single]($point[0]-7), [single]($point[1]-7), 14,14)
        }
        $icon = [Drawing.Icon]::FromHandle($bitmap.GetHicon())
        $iconStream = [IO.File]::Create($iconPath)
        try { $icon.Save($iconStream) } finally { $iconStream.Dispose() }
    } finally { $pen.Dispose() }
} finally { $graphics.Dispose(); $bitmap.Dispose() }

$coreDll = Join-Path $desktopOut 'Microsoft.Web.WebView2.Core.dll'
$formsDll = Join-Path $desktopOut 'Microsoft.Web.WebView2.WinForms.dll'
& $compiler /nologo /target:winexe /platform:x64 /optimize+ /utf8output "/out:$executable" "/win32icon:$iconPath" "/win32manifest:$(Join-Path $PSScriptRoot 'app.manifest')" /r:System.dll /r:System.Core.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll /r:System.Web.dll /r:System.Web.Extensions.dll "/r:$coreDll" "/r:$formsDll" (Join-Path $PSScriptRoot 'DesktopCore.cs') (Join-Path $PSScriptRoot 'DesktopApp.cs')
if ($LASTEXITCODE -ne 0) { throw 'Desktop compilation failed.' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'App.config') -Destination ($executable + '.config') -Force
[IO.File]::WriteAllText((Join-Path $desktopOut 'desktop-config.json'), (@{root=$repoRoot} | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))

# Compile and run pure policy/state tests without opening the application.
$testExe = Join-Path $desktopOut 'DesktopTests.exe'
& $compiler /nologo /target:exe /platform:x64 /utf8output "/out:$testExe" /r:System.dll /r:System.Core.dll /r:System.Web.dll /r:System.Web.Extensions.dll (Join-Path $PSScriptRoot 'DesktopCore.cs') (Join-Path $PSScriptRoot 'DesktopCore.Tests.cs')
if ($LASTEXITCODE -ne 0) { throw 'Desktop test compilation failed.' }
& $testExe
if ($LASTEXITCODE -ne 0) { throw 'Desktop tests failed.' }

if (-not $NoShortcuts) {
    $shortcutShell = New-Object -ComObject WScript.Shell
    $shortcutFolders = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
    foreach ($shortcutFolder in $shortcutFolders) {
        $shortcutPath = Join-Path $shortcutFolder 'EgoAgent.lnk'
        if (Test-Path -LiteralPath $shortcutPath) {
            $existing = $shortcutShell.CreateShortcut($shortcutPath)
            if ($existing.TargetPath -ne $executable) {
                $existingPath = [IO.Path]::GetFullPath($existing.TargetPath)
                $owned = $existingPath.Equals((Join-Path $installationRoot 'EgoAgent.exe'), [StringComparison]::OrdinalIgnoreCase)
                if (-not $owned -and $existingPath.StartsWith((Join-Path $installationRoot 'releases') + '\', [StringComparison]::OrdinalIgnoreCase)) {
                    $existingConfig = Join-Path ([IO.Path]::GetDirectoryName($existingPath)) 'desktop-config.json'
                    if (([IO.Path]::GetFileName($existingPath) -eq 'EgoAgent.exe') -and (Test-Path -LiteralPath $existingConfig)) {
                        $installed = Get-Content -LiteralPath $existingConfig -Raw | ConvertFrom-Json
                        $owned = [IO.Path]::GetFullPath($installed.root).Equals($repoRoot, [StringComparison]::OrdinalIgnoreCase)
                    }
                }
                if (-not $owned) { throw "Shortcut already belongs to another installation: $shortcutPath" }
            }
        }
        $shortcut = $shortcutShell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $executable
        $shortcut.WorkingDirectory = $repoRoot
        $shortcut.IconLocation = "$iconPath,0"
        $shortcut.Description = 'EgoAgent - IDE, Chat and Flow Workbench'
        $shortcut.Save()
        Write-Host "Shortcut: $shortcutPath"
    }
}
Write-Host "Ready: $executable"
