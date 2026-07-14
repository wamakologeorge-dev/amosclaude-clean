@echo off
setlocal
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
  echo Docker Desktop is required to run Amosclaud locally.
  echo Install Docker Desktop, restart Windows if requested, then run this file again.
  pause
  exit /b 1
)

docker info >nul 2>nul
if errorlevel 1 (
  echo Docker Desktop is installed but not running.
  echo Start Docker Desktop, wait until it is ready, then run this file again.
  pause
  exit /b 1
)

if not exist "AmosclaudWorkspace" mkdir "AmosclaudWorkspace"

if not exist ".env" (
  echo First-time Amosclaud owner setup.
  set /p AMOS_OWNER_EMAIL=Enter the email address you will use for the owner account: 
  if "%AMOS_OWNER_EMAIL%"=="" (
    echo Owner email is required. No configuration was created.
    pause
    exit /b 1
  )
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$key=[Convert]::ToBase64String((1..48|ForEach-Object{Get-Random -Maximum 256})); @('AMOSCLAUD_MASTER_KEY='+$key,'AMOSCLAUD_ADMIN_EMAIL=%AMOS_OWNER_EMAIL%','AMOSCLAUD_ACCESS_MODE=local','AMOSCLAUD_MODEL=qwen2.5-coder:3b') | Set-Content -Encoding UTF8 .env"
  echo Created a private local configuration for %AMOS_OWNER_EMAIL%.
)

echo Starting Amosclaud, the folder workspace, and the local model runtime...
docker compose -f docker-compose.selfhost.yml up -d --build
if errorlevel 1 (
  echo Amosclaud could not start. Review the Docker output above.
  pause
  exit /b 1
)

echo Waiting for the Amosclaud server...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; 1..90 | ForEach-Object { try { $r=Invoke-WebRequest -UseBasicParsing http://localhost:8000/health -TimeoutSec 3; if($r.StatusCode -eq 200){$ok=$true; break} } catch {}; Start-Sleep -Seconds 2 }; if(-not $ok){exit 1}"
if errorlevel 1 (
  echo Amosclaud server startup failed.
  echo Run: docker compose -f docker-compose.selfhost.yml logs -f
  pause
  exit /b 1
)

echo Verifying the agent, workspace, token authority, and local model response...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; 1..120 | ForEach-Object { try { $r=Invoke-RestMethod http://localhost:8000/api/v1/agent/readiness -TimeoutSec 125; if($r.ready -eq $true){$ok=$true; break}; Write-Host ('Agent starting: ' + ($r.checks.model.detail)); } catch { Write-Host 'Agent readiness check is waiting...' }; Start-Sleep -Seconds 3 }; if(-not $ok){exit 1}"
if errorlevel 1 (
  echo Amosclaud server is running, but the agent did not produce a verified local-model response.
  echo Review: http://localhost:8000/api/v1/agent/readiness
  echo Logs: docker compose -f docker-compose.selfhost.yml logs -f model model-init app
  pause
  exit /b 1
)

echo Amosclaud agent is verified and ready.
start "" "http://localhost:8000"
exit /b 0
