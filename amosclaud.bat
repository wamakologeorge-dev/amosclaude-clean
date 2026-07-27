@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "AMOSCLAUD_PYTHON=python"
where python >nul 2>&1
if errorlevel 1 set "AMOSCLAUD_PYTHON=py -3"

%AMOSCLAUD_PYTHON% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
  echo Amosclaud requires Python 3.11 or newer.
  exit /b 2
)

if "%~1"=="" goto usage

%AMOSCLAUD_PYTHON% scripts\agent_guard_cli.py %*
exit /b %errorlevel%

:usage
echo Amosclaud local commands:
echo   amosclaud test
echo   amosclaud guard-test
echo   amosclaud build
echo   amosclaud guard-build
echo   amosclaud serve
echo.
echo Add --workspace "C:\path\to\project" to target another registered folder.
exit /b 1
