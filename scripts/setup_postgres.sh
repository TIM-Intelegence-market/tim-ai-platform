#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PSQL="/Library/PostgreSQL/18/bin/psql"

if [[ ! -x "$PSQL" ]]; then
  echo "PostgreSQL 18 psql wurde nicht gefunden: $PSQL" >&2
  exit 1
fi

echo "TIM PostgreSQL Setup (lokal, OBSERVE-only)"
echo "PostgreSQL fragt jetzt sicher nach dem Passwort des Administrators 'postgres'."
echo "Das Passwort wird nicht von TIM gespeichert."

"$PSQL" -h 127.0.0.1 -p 5432 -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
SELECT format('CREATE ROLE tim LOGIN PASSWORD %L', 'tim_local_only')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tim') \gexec
ALTER ROLE tim WITH LOGIN PASSWORD 'tim_local_only' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
SELECT 'CREATE DATABASE tim OWNER tim'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'tim') \gexec
SQL

echo "Prüfe TimescaleDB-Erweiterung ..."
if ! "$PSQL" -h 127.0.0.1 -p 5432 -U postgres -d tim -Atqc \
  "SELECT 1 FROM pg_available_extensions WHERE name='timescaledb'" | grep -q 1; then
  echo "HINWEIS: TimescaleDB ist für diese PostgreSQL-18-Installation nicht verfügbar."
  echo "TIM verwendet den sicheren PostgreSQL-Fallback mit Zeitindizes."
fi

"$PSQL" -h 127.0.0.1 -p 5432 -U postgres -d tim -v ON_ERROR_STOP=1 \
  -f "$ROOT/src/database/schema.sql"

PGPASSWORD=tim_local_only "$PSQL" -h 127.0.0.1 -p 5432 -U tim -d tim -Atqc \
  "SELECT current_database(), current_user, COALESCE((SELECT extversion FROM pg_extension WHERE extname='timescaledb'),'STANDARD_POSTGRES');"

echo "TIM POSTGRES READY"
