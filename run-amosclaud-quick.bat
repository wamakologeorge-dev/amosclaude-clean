@echo off
setlocal
cd /d "%~dp0"
if defined PYTHON_BIN (
  "%PYTHON_BIN%" -m amoscloud_ai.quickcheck_cli %*
) else (
  py -3 -m amoscloud_ai.quickcheck_cli %*
)
exit /b %ERRORLEVEL%
