<#
.SYNOPSIS
    Start the RivalRadar dashboard (Next.js) on http://localhost:3000
.DESCRIPTION
    Runs the Next.js dev server. Requires the backend to be running on
    port 8000 for the dashboard to show data.
#>

param(
    [int]$Port = 3000,
    [switch]$Production
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "frontend")

if (-not (Test-Path "node_modules")) {
    Write-Host "Node dependencies not installed." -ForegroundColor Red
    Write-Host "Run .\setup.ps1 from the project root first." -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path ".env.local")) {
    Copy-Item ".env.example" ".env.local"
    Write-Host "Created frontend\.env.local from the example." -ForegroundColor Yellow
}

Write-Host "RivalRadar dashboard  ->  http://localhost:$Port" -ForegroundColor Cyan
Write-Host "Backend expected at   ->  http://127.0.0.1:8000" -ForegroundColor DarkGray
Write-Host "Press Ctrl+C to stop.`n" -ForegroundColor DarkGray

if ($Production) {
    & npm run build
    & npx next start -p $Port
} else {
    & npx next dev -p $Port
}
