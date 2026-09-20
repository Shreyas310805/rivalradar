#!/usr/bin/env bash
# Run the Wayback evaluation suite and write a report to data/reports/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

if [ -f .venv/Scripts/python.exe ]; then
  PY=".venv/Scripts/python.exe"
else
  PY=".venv/bin/python"
fi

echo "==> Running the evaluation suite against the Internet Archive"
echo "    This makes live network requests and takes a few minutes."
"$PY" -m app.cli evaluate "$@"
