#!/bin/bash
cd "$(dirname "$0")" || exit 1
./scripts/reset_postgres_password.sh
status=$?
echo
if [[ $status -eq 0 ]]; then
  echo "Starte jetzt TIM_Postgres_Setup.command erneut."
else
  echo "Reset wurde mit Status $status beendet. Die Fehlermeldung bleibt sichtbar."
fi
echo
read -r -p "Enter drücken, um das Fenster zu schließen ..."
exit "$status"
