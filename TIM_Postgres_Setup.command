#!/bin/bash
cd "$(dirname "$0")" || exit 1
./scripts/setup_postgres.sh
status=$?
echo
if [[ $status -eq 0 ]]; then
  echo "Das private Credential-Handoff ist vorbereitet."
  echo "PostgreSQL ist noch nicht freigegeben; jetzt scripts/admin/README.md abarbeiten."
else
  echo "Setup wurde mit Status $status beendet. Die Meldung oben bleibt sichtbar."
fi
echo
read -r -p "Enter drücken, um das Fenster zu schließen ..."
exit "$status"
