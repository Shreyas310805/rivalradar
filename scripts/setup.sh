#!/usr/bin/env bash
# One-shot local setup: backend venv, dependencies, database and demo data.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

echo "==> Creating virtual environment"
python -m venv .venv

if [ -f .venv/Scripts/python.exe ]; then
  PY=".venv/Scripts/python.exe"   # Windows (Git Bash)
else
  PY=".venv/bin/python"           # macOS / Linux
fi

echo "==> Installing backend dependencies"
"$PY" -m pip install --upgrade pip --quiet
"$PY" -m pip install -r requirements.txt
"$PY" -m pip install -e .

if [ ! -f .env ]; then
  echo "==> Creating .env from .env.example"
  cp .env.example .env
fi

echo "==> Initialising the database and seeding demo data"
"$PY" -m app.cli init
"$PY" -m app.cli seed

echo "==> Installing frontend dependencies"
cd "$ROOT/frontend"
npm install --no-audit --no-fund

cat <<'MSG'

Setup complete.

  Backend:   cd backend && .venv/Scripts/python -m app.cli serve    (Windows)
             cd backend && .venv/bin/python -m app.cli serve        (macOS/Linux)
  Frontend:  cd frontend && npm run dev

  Dashboard: http://localhost:3000
  API docs:  http://localhost:8000/docs
MSG
