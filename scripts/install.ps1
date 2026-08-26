param(
  [switch]$Offline
)
$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Venv = Join-Path $Repo ".runtime\venv"
if (-not (Test-Path $Venv)) { python -m venv $Venv }
$Python = Join-Path $Venv "Scripts\python.exe"
$PipArgs = @("-m", "pip", "install", "--requirement", (Join-Path $Repo "requirements.txt"))
if ($Offline) { $PipArgs += "--no-index" }
& $Python @PipArgs
Push-Location (Join-Path $Repo "harness_editor")
try {
  if ($Offline) { npm ci --offline } else { npm ci }
  npm run build
} finally { Pop-Location }
& $Python (Join-Path $Repo "scripts\egoagent.py") doctor
Write-Host "Installed. Start with: $Python $Repo\scripts\egoagent.py start"
