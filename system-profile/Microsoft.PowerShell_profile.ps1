$env:AMOSCLAUD_HOME = Split-Path -Parent $PSScriptRoot

function Start-Amosclaud {
  & (Join-Path $env:AMOSCLAUD_HOME 'start-amosclaud.bat')
}

function Stop-Amosclaud {
  Push-Location $env:AMOSCLAUD_HOME
  try {
    docker compose -f docker-compose.selfhost.yml down
  } finally {
    Pop-Location
  }
}

function Open-Amosclaud {
  Start-Process 'http://localhost:8000'
}

Set-Alias amos-start Start-Amosclaud
Set-Alias amos-stop Stop-Amosclaud
Set-Alias amos-open Open-Amosclaud
