[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install it from https://docs.astral.sh/uv/"
}

$safeRoot = $Root.Replace("'", "''")
$command = "`$Host.UI.RawUI.WindowTitle = 'WhatsApp Commerce and Support'; Set-Location -LiteralPath '$safeRoot'; uv run --with-requirements requirements.txt python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8105"
Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $command
)

Write-Host "WhatsApp Commerce and Support starting at http://127.0.0.1:8105/demo"
Write-Host "API readiness: http://127.0.0.1:8105/ready"
