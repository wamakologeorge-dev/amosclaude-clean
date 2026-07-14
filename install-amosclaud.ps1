$ErrorActionPreference = "Stop"
$InstallRoot = $PSScriptRoot
$AppRoot = if (Test-Path (Join-Path $InstallRoot "app\docker-compose.selfhost.yml")) { Join-Path $InstallRoot "app" } else { $InstallRoot }
Set-Location $AppRoot

Write-Host "Amosclaud Server Installer" -ForegroundColor Cyan
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is required. Install it, start it, then run this installer again."
}
docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker Desktop is installed but its engine is not running." }

$WorkspaceRelative = if ($AppRoot -ne $InstallRoot) { "workspace\projects" } else { "AmosclaudWorkspace" }
New-Item -ItemType Directory -Force -Path (Join-Path $InstallRoot $WorkspaceRelative) | Out-Null
if (-not (Test-Path ".env.runner")) { New-Item -ItemType File ".env.runner" | Out-Null }
if (-not (Test-Path ".env")) {
    $owner = Read-Host "Owner email"
    if ([string]::IsNullOrWhiteSpace($owner)) { throw "Owner email is required." }
    $bytes = New-Object byte[] 48
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    $key = [Convert]::ToBase64String($bytes)
    @(
        "AMOSCLAUD_MASTER_KEY=$key"
        "AMOSCLAUD_ADMIN_EMAIL=$owner"
        "AMOSCLAUD_ACCESS_MODE=local"
        "AMOSCLAUD_MODEL=qwen2.5-coder:3b"
    ) | Set-Content -Encoding UTF8 ".env"
}
$workspace = (Resolve-Path (Join-Path $InstallRoot $WorkspaceRelative)).Path
if (-not (Select-String -Quiet -Path ".env" -Pattern '^AMOSCLAUD_WORKSPACE_PATH=')) {
    Add-Content ".env" "AMOSCLAUD_WORKSPACE_PATH=$workspace"
}

$connect = Read-Host "Connect this computer to amosclaud.com as a private runner? (y/N)"
$profile = @()
if ($connect -match '^[Yy]') {
    $runnerId = Read-Host "Runner ID from amosclaud.com/tasks"
    $runnerToken = Read-Host "One-time runner token"
    if ([string]::IsNullOrWhiteSpace($runnerId) -or [string]::IsNullOrWhiteSpace($runnerToken)) {
        throw "Runner ID and token are required for cloud pairing."
    }
    @(
        "AMOSCLAUD_API_URL=https://amosclaud.com"
        "AMOSCLAUD_RUNNER_ID=$runnerId"
        "AMOSCLAUD_RUNNER_TOKEN=$runnerToken"
    ) | Set-Content -Encoding UTF8 ".env.runner"
    if (-not (Select-String -Quiet -Path ".env" -Pattern '^AMOSCLAUD_RUNNER_WORKSPACE=')) {
        Add-Content ".env" "AMOSCLAUD_RUNNER_WORKSPACE=$workspace"
    }
    $profile = @("--profile", "connected-runner")
}

docker compose -f docker-compose.selfhost.yml @profile up -d --build
if ($LASTEXITCODE -ne 0) { throw "The server did not start. Run docker compose logs for details." }

$deadline = (Get-Date).AddMinutes(5)
do {
    try {
        $health = Invoke-RestMethod "http://localhost:8000/health" -TimeoutSec 5
        if ($health) { break }
    } catch {}
    Start-Sleep -Seconds 3
} while ((Get-Date) -lt $deadline)

if ((Get-Date) -ge $deadline) { throw "Server startup timed out. Run docker compose logs." }
Write-Host "Amosclaud is installed and running at http://localhost:8000" -ForegroundColor Green
Start-Process "http://localhost:8000"
