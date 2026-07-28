#!/usr/bin/env bash
set -euo pipefail

DATA="/Library/PostgreSQL/18/data"
BIN="/Library/PostgreSQL/18/bin"
SERVICE="system/postgresql-18"

echo "Lokaler PostgreSQL-18-Passwortreset"
echo "Es wird kein Online-Konto benötigt."
echo
password=""
for attempt in 1 2 3; do
  read -r -s -p "Neues Passwort für PostgreSQL-Benutzer postgres: " password
  echo
  read -r -s -p "Passwort exakt wiederholen: " confirmation
  echo
  if [[ "$password" != "$confirmation" ]]; then
    echo "Die Passwörter stimmen nicht überein. Bitte erneut versuchen ($attempt/3)." >&2
    continue
  fi
  if [[ ! "$password" =~ ^[A-Za-z0-9._-]{12,64}$ ]]; then
    echo "Bitte 12–64 Zeichen verwenden: Buchstaben, Zahlen, Punkt, Unterstrich oder Bindestrich." >&2
    continue
  fi
  break
done
if [[ "$password" != "$confirmation" || ! "$password" =~ ^[A-Za-z0-9._-]{12,64}$ ]]; then
  echo "Passwortreset nach drei Versuchen abgebrochen." >&2
  exit 1
fi

echo
echo "macOS fragt jetzt nach deinem Mac-Administratorpasswort."
sudo -v

restart_server() {
  if ! sudo launchctl kickstart "$SERVICE" >/dev/null 2>&1; then
    sudo -u postgres "$BIN/pg_ctl" -D "$DATA" -l "$DATA/logfile" start >/dev/null
  fi
}
trap restart_server EXIT

sudo -u postgres "$BIN/pg_ctl" -D "$DATA" -m fast -w stop
printf "ALTER ROLE postgres WITH PASSWORD '%s';\n" "$password" | \
  sudo -u postgres "$BIN/postgres" --single -D "$DATA" postgres >/dev/null
restart_server
trap - EXIT

for _ in {1..20}; do
  if PGPASSWORD="$password" "$BIN/psql" -h 127.0.0.1 -p 5432 -U postgres -d postgres -Atqc "SELECT current_user" 2>/dev/null | grep -qx postgres; then
    echo "POSTGRES PASSWORD RESET SUCCESSFUL"
    exit 0
  fi
  sleep 1
done

echo "Passwort wurde gesetzt, aber der abschließende Verbindungstest ist fehlgeschlagen." >&2
exit 2
