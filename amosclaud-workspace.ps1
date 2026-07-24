param([ValidateSet('doctor','start','stop','status','logs')][string]$Command = 'doctor')
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$app = if (Test-Path (Join-Path $root 'app\docker-compose.selfhost.yml')) { Join-Path $root 'app' } else { $root }
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw 'Python 3.11 or newer is required for workspace controls.' }
Set-Location $root
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$app;$env:PYTHONPATH" } else { $app }
& $python.Source -m amoscloud_ai.workspace_control $Command
exit $LASTEXITCODE
