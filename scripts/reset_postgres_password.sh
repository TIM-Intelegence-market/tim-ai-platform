#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "TIM Python runtime is unavailable." >&2
  exit 2
fi

echo "TIM credential rotation preparation (OBSERVE-only)"
echo "No password will be printed or passed as a command-line argument."
"$PYTHON" "$ROOT/scripts/admin/prepare_tim_credential.py" prepare
echo
echo "POSTGRES ADMIN ACTION REQUIRED"
echo "The existing credential is unchanged until the legitimate administrator applies the private SCRAM handoff."
