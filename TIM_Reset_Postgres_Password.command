#!/bin/bash
cd "$(dirname "$0")" || exit 1
./scripts/reset_postgres_password.sh
status=$?
echo
if [[ $status -eq 0 ]]; then
  echo "Das private Rotations-Handoff ist vorbereitet."
  echo "Die Rotation ist erst nach dem legitimen Admin-Schritt abgeschlossen."
else
  echo "Reset wurde mit Status $status beendet. Die Fehlermeldung bleibt sichtbar."
fi
echo
read -r -p "Enter drücken, um das Fenster zu schließen ..."
exit "$status"
