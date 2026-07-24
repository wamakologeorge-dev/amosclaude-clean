param(
  [switch]$Apply,
  [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackupRoot = Join-Path $env:USERPROFILE '.amosclaud-profile-backup'
$ProfileSource = Join-Path $Root 'Microsoft.PowerShell_profile.ps1'
$ProfileTarget = $PROFILE.CurrentUserAllHosts

function Show-Plan {
  Write-Host 'Amosclaud system profile plan:' -ForegroundColor Cyan
  Write-Host "  Source: $ProfileSource"
  Write-Host "  Target: $ProfileTarget"
  Write-Host "  Backup: $BackupRoot"
}

Show-Plan

if (-not $Apply -and -not $Remove) {
  Write-Host ''
  Write-Host 'Preview only. No settings were changed.' -ForegroundColor Yellow
  Write-Host 'Run with -Apply to install or -Remove to remove the Amosclaud link.'
  exit 0
}

if ($Apply) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ProfileTarget) | Out-Null
  New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null

  if (Test-Path $ProfileTarget) {
    $existing = Get-Item $ProfileTarget -Force
    if (-not ($existing.LinkType -and $existing.Target -contains $ProfileSource)) {
      $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
      Copy-Item $ProfileTarget (Join-Path $BackupRoot "Microsoft.PowerShell_profile.$stamp.ps1")
      Remove-Item $ProfileTarget -Force
    } else {
      Write-Host 'Amosclaud profile is already installed.' -ForegroundColor Green
      exit 0
    }
  }

  New-Item -ItemType SymbolicLink -Path $ProfileTarget -Target $ProfileSource | Out-Null
  Write-Host 'Amosclaud profile installed. Open a new PowerShell window.' -ForegroundColor Green
  exit 0
}

if ($Remove) {
  if (Test-Path $ProfileTarget) {
    $existing = Get-Item $ProfileTarget -Force
    if ($existing.LinkType -and $existing.Target -contains $ProfileSource) {
      Remove-Item $ProfileTarget -Force
      Write-Host 'Amosclaud profile link removed.' -ForegroundColor Green
    } else {
      Write-Host 'Target is not an Amosclaud-managed link; nothing was removed.' -ForegroundColor Yellow
    }
  }
  Write-Host "Backups remain in $BackupRoot for manual restoration."
}
