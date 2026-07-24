@echo off
setlocal
cd /d "%~dp0"
where docker >nul 2>nul
if errorlevel 1 (
  echo Docker is not installed or is not available in PATH.
  pause
  exit /b 1
)
docker compose -f docker-compose.selfhost.yml down
if errorlevel 1 (
  echo Amosclaud could not be stopped cleanly.
  pause
  exit /b 1
)
echo Amosclaud stopped. Persistent data and downloaded models were preserved.
pause
