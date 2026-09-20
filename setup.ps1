<#
.SYNOPSIS
    One-time setup for RivalRadar on Windows.

.DESCRIPTION
    Creates the backend virtual environment, installs Python and Node
    dependencies, creates .env files from the examples, initialises the
    SQLite database and loads demo data.

    No Docker required. No OpenAI API key required.

.EXAMPLE
    .\setup.ps1
#>

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Write-Step { param($Message) Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Write-Ok   { param($Message) Write-Host "    $Message" -ForegroundColor Green }
function Write-Warn { param($Message) Write-Host "    $Message" -ForegroundColor Yellow }

# --- Prerequisites ---------------------------------------------------------
Write-Step "Checking prerequisites"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw "Python not found on PATH. Install Python 3.11+ from https://python.org" }
$pyVersion = (& python --version 2>&1)
Write-Ok "$pyVersion"

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { throw "Node.js not found on PATH. Install Node 18+ from https://nodejs.org" }
Write-Ok "Node $(& node --version)"

# --- Backend ---------------------------------------------------------------
Write-Step "Setting up the backend"
Set-Location (Join-Path $root "backend")

if (-not (Test-Path ".venv")) {
    & python -m venv .venv
    Write-Ok "Created virtual environment"
} else {
    Write-Ok "Virtual environment already exists"
}

$venvPython = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw "Virtual environment looks broken: $venvPython not found" }

Write-Ok "Installing Python dependencies (this takes a few minutes)"
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r requirements.txt --quiet
& $venvPython -m pip install -e . --quiet
Write-Ok "Python dependencies installed"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Ok "Created backend\.env from the example"
} else {
    Write-Ok "backend\.env already exists (left untouched)"
}

Write-Step "Initialising the database and loading demo data"
& $venvPython -m app.cli init
& $venvPython -m app.cli seed
# Generate a digest so the Digest page has content on first open.
& $venvPython -m app.cli digest | Out-Null
Write-Ok "Demo data and weekly digest ready"

# --- Frontend --------------------------------------------------------------
Write-Step "Setting up the frontend"
Set-Location (Join-Path $root "frontend")

if (-not (Test-Path ".env.local")) {
    Copy-Item ".env.example" ".env.local"
    Write-Ok "Created frontend\.env.local from the example"
} else {
    Write-Ok "frontend\.env.local already exists (left untouched)"
}

Write-Ok "Installing Node dependencies (this can take several minutes)"
& npm install --no-audit --no-fund
Write-Ok "Node dependencies installed"

Set-Location $root

# --- Done ------------------------------------------------------------------
Write-Host "`n" -NoNewline
Write-Host "Setup complete." -ForegroundColor Green
Write-Host @"

Start RivalRadar with two terminals:

  Terminal 1 (backend):    .\start-backend.ps1
  Terminal 2 (frontend):   .\start-frontend.ps1

Then open:

  Dashboard   http://localhost:3000
  API docs    http://localhost:8000/docs

RivalRadar runs fully offline with demo data. Add an OPENAI_API_KEY to
backend\.env only if you want richer LLM-written analysis.
"@
