#!/usr/bin/env bash
# Reset the database, seed the demo competitors and print the measured funnel.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

if [ -f .venv/Scripts/python.exe ]; then
  PY=".venv/Scripts/python.exe"
else
  PY=".venv/bin/python"
fi

echo "==> Seeding demo data through the real pipeline"
"$PY" -m app.cli seed --reset

echo
echo "==> Competitors"
"$PY" -m app.cli list

echo
echo "==> Generating the weekly digest"
"$PY" -m app.cli digest
