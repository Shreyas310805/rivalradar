<#
.SYNOPSIS
    Start the RivalRadar API (FastAPI + Uvicorn) on http://localhost:8000
.DESCRIPTION
    Activates the backend virtual environment and runs Uvicorn with reload.
    Run .\setup.ps1 first if the virtual environment does not exist yet.
#>

param(
    [int]$Port = 8000,
    [string]$ApiHost = "127.0.0.1",
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "backend")

$venvPython = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Virtual environment not found." -ForegroundColor Red
    Write-Host "Run .\setup.ps1 from the project root first." -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created backend\.env from the example." -ForegroundColor Yellow
}

Write-Host "RivalRadar API  ->  http://$ApiHost`:$Port" -ForegroundColor Cyan
Write-Host "Swagger docs    ->  http://$ApiHost`:$Port/docs" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop.`n" -ForegroundColor DarkGray

$uvicornArgs = @("-m", "uvicorn", "app.main:app", "--host", $ApiHost, "--port", $Port)
if (-not $NoReload) { $uvicornArgs += "--reload" }

& $venvPython @uvicornArgs
