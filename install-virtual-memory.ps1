param([switch]$Apply, [ValidateRange(2, 16)][int]$SizeGB = 0)
$ErrorActionPreference = "Stop"
$memory = Get-CimInstance Win32_ComputerSystem
$page = Get-CimInstance Win32_PageFileUsage -ErrorAction SilentlyContinue
$ramGB = [math]::Round($memory.TotalPhysicalMemory / 1GB, 1)
$recommended = if ($ramGB -le 4) { [math]::Ceiling($ramGB * 2) } elseif ($ramGB -le 16) { [math]::Ceiling($ramGB) } else { 8 }
$recommended = [math]::Max(2, [math]::Min(16, $recommended))
Write-Host "Physical RAM: $ramGB GiB"
Write-Host "Current pagefile: $([math]::Round((($page | Measure-Object AllocatedBaseSize -Sum).Sum / 1024), 1)) GiB"
Write-Host "Amosclaud recommendation: $recommended GiB"
if (-not $Apply) { Write-Host "No changes made. Re-run as Administrator with -Apply to configure."; exit 0 }
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "Run PowerShell as Administrator." }
if ($SizeGB -eq 0) { $SizeGB = $recommended }
$computer = Get-CimInstance Win32_ComputerSystem
Set-CimInstance -InputObject $computer -Property @{AutomaticManagedPagefile=$false} | Out-Null
$setting = Get-CimInstance Win32_PageFileSetting -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq 'C:\pagefile.sys' }
$sizeMB = $SizeGB * 1024
if ($setting) { Set-CimInstance $setting -Property @{InitialSize=$sizeMB;MaximumSize=$sizeMB} | Out-Null }
else { New-CimInstance Win32_PageFileSetting -Property @{Name='C:\pagefile.sys';InitialSize=$sizeMB;MaximumSize=$sizeMB} | Out-Null }
Write-Host "Windows pagefile configured to $SizeGB GiB. Restart Windows to activate it."
