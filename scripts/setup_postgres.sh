#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "TIM Python runtime is unavailable." >&2
  exit 2
fi

echo "TIM PostgreSQL secure setup (OBSERVE-only)"
echo "This step prepares a Keychain credential and a private administrator handoff."
echo "It does not print a password, escalate privileges, stop PostgreSQL, or claim completion."
"$PYTHON" "$ROOT/scripts/admin/prepare_tim_credential.py" prepare
echo
echo "POSTGRES ADMIN ACTION REQUIRED"
echo "Follow scripts/admin/README.md. TIM remains fail-closed until the admin apply and verification pass."
