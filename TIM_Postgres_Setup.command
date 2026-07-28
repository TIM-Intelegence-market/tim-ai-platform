#!/bin/bash
cd "$(dirname "$0")" || exit 1
./scripts/setup_postgres.sh
status=$?
echo
if [[ $status -eq 0 ]]; then
  echo "PostgreSQL ist bereit. TIM kann jetzt mit folgendem Befehl gestartet werden:"
  echo ".venv/bin/python main.py --init-schema"
else
  echo "Setup wurde mit Status $status beendet. Die Meldung oben bleibt sichtbar."
fi
echo
read -r -p "Enter drücken, um das Fenster zu schließen ..."
exit "$status"
