$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$AppRoot = Join-Path $Root "app"
if (-not (Test-Path $AppRoot)) { $AppRoot = $Root }

if (-not (Get-Command py -ErrorAction SilentlyContinue) -and -not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.11 or newer is required."
}

$Python = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
if (-not (Test-Path ".venv")) {
    & $Python -m venv .venv
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e $AppRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}
New-Item -ItemType Directory -Force -Path "data", "data\repositories", "data\storage" | Out-Null

if (-not $env:AUTH_DB_PATH) { $env:AUTH_DB_PATH = Join-Path $Root "data\auth.db" }
if (-not $env:REPOSITORY_STORAGE_PATH) { $env:REPOSITORY_STORAGE_PATH = Join-Path $Root "data\repositories" }
if (-not $env:STORAGE_PATH) { $env:STORAGE_PATH = Join-Path $Root "data\storage" }
if (-not $env:HOST) { $env:HOST = "127.0.0.1" }
if (-not $env:PORT) { $env:PORT = "8000" }

Write-Host "Amosclaud Agent Server: http://localhost:$env:PORT"
Set-Location $Root
& $VenvPython -m uvicorn amoscloud_ai.main:app --host $env:HOST --port $env:PORT
