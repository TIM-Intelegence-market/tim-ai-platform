#!/usr/bin/env bash
set -euo pipefail
umask 077

CONFIG_FILE=""
HBA_FILE=""
DATA_DIRECTORY=""
HANDOFF="${HOME}/Library/Application Support/TIM/postgres-admin-handoff.json"
CLASSIFICATION=""
SERVICE="system/postgresql-18"
PSQL_BIN="${TIM_ADMIN_PSQL:-/Library/PostgreSQL/18/bin/psql}"
ADMIN_USER="${TIM_ADMIN_DATABASE_USER:-postgres}"
ADMIN_DATABASE="${TIM_ADMIN_DATABASE_NAME:-postgres}"

usage() {
  echo "Usage: apply_postgres_hardening.sh --config-file PATH --hba-file PATH --data-directory PATH --classification TIM_DEDICATED [--handoff PATH] [--service system/postgresql-18]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config-file) CONFIG_FILE="${2:-}"; shift 2 ;;
    --hba-file) HBA_FILE="${2:-}"; shift 2 ;;
    --data-directory) DATA_DIRECTORY="${2:-}"; shift 2 ;;
    --handoff) HANDOFF="${2:-}"; shift 2 ;;
    --classification) CLASSIFICATION="${2:-}"; shift 2 ;;
    --service) SERVICE="${2:-}"; shift 2 ;;
    *) usage; exit 2 ;;
  esac
done

if [[ "$CLASSIFICATION" != "TIM_DEDICATED" ]]; then
  echo '{"status":"BLOCKED","reason":"explicit TIM_DEDICATED classification required"}' >&2
  exit 2
fi
if [[ "$(id -u)" -ne 0 ]]; then
  echo '{"status":"BLOCKED","reason":"legitimate macOS administrator execution required; script does not escalate privileges"}' >&2
  exit 2
fi
for path in "$CONFIG_FILE" "$HBA_FILE" "$HANDOFF"; do
  if [[ -z "$path" || ! -f "$path" ]]; then
    echo '{"status":"BLOCKED","reason":"an explicit inspected input file is missing"}' >&2
    exit 2
  fi
done
if [[ -z "$DATA_DIRECTORY" || ! -d "$DATA_DIRECTORY" || ! -x "$PSQL_BIN" ]]; then
  echo '{"status":"BLOCKED","reason":"data directory or psql binary is unavailable"}' >&2
  exit 2
fi
if [[ "$SERVICE" != "system/postgresql-18" ]]; then
  echo '{"status":"BLOCKED","reason":"service identity differs from inspected system/postgresql-18"}' >&2
  exit 2
fi
if [[ "$CONFIG_FILE" != "$DATA_DIRECTORY"/* || "$HBA_FILE" != "$DATA_DIRECTORY"/* ]]; then
  echo '{"status":"BLOCKED","reason":"configuration paths are outside the inspected data directory"}' >&2
  exit 2
fi

SERVER_METADATA="$("$PSQL_BIN" -X -v ON_ERROR_STOP=1 -U "$ADMIN_USER" -d "$ADMIN_DATABASE" -AtF '|' -c \
  "SELECT current_setting('config_file'),current_setting('hba_file'),current_setting('data_directory'),current_setting('server_version'),(SELECT rolsuper::int FROM pg_roles WHERE rolname=current_user),(SELECT count(*) FROM pg_database WHERE datname NOT IN ('template0','template1','postgres','tim')),(SELECT count(*) FROM pg_roles WHERE rolname !~ '^pg_' AND rolname NOT IN ('postgres','tim')),(SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid() AND COALESCE(datname,'') NOT IN ('','tim'))")" || {
  echo '{"status":"BLOCKED","reason":"authoritative PostgreSQL admin inspection failed"}' >&2
  exit 2
}
IFS='|' read -r SERVER_CONFIG SERVER_HBA SERVER_DATA SERVER_VERSION ADMIN_SUPERUSER OTHER_DATABASES OTHER_ROLES OTHER_SESSIONS <<<"$SERVER_METADATA"
if [[ "$SERVER_CONFIG" != "$CONFIG_FILE" || "$SERVER_HBA" != "$HBA_FILE" || "$SERVER_DATA" != "$DATA_DIRECTORY" ]]; then
  echo '{"status":"BLOCKED","reason":"provided paths differ from authoritative PostgreSQL settings"}' >&2
  exit 2
fi
if [[ "$SERVER_VERSION" != 18.* || "$ADMIN_SUPERUSER" != "1" ]]; then
  echo '{"status":"BLOCKED","reason":"PostgreSQL 18 superuser session required"}' >&2
  exit 2
fi
if [[ "$OTHER_DATABASES" != "0" || "$OTHER_ROLES" != "0" || "$OTHER_SESSIONS" != "0" ]]; then
  echo '{"status":"BLOCKED","reason":"shared-instance indicators contradict TIM_DEDICATED"}' >&2
  exit 2
fi

BUNDLE_ID="$(/usr/bin/python3 - "$HANDOFF" <<'PY'
import json,re,sys
value=json.load(open(sys.argv[1], encoding='utf-8'))
bundle=value.get('bundle_id','')
verifier=value.get('scram_verifier','')
if value.get('status')!='PENDING_POSTGRES_ADMIN_APPLY' or value.get('database_role')!='tim': raise SystemExit(2)
if not re.fullmatch(r'tim-credential-[a-f0-9]{32}',bundle): raise SystemExit(2)
if not re.fullmatch(r'SCRAM-SHA-256\$[0-9]+:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+',verifier): raise SystemExit(2)
print(bundle)
PY
)" || {
  echo '{"status":"BLOCKED","reason":"credential handoff is invalid"}' >&2
  exit 2
}

BACKUP_DIRECTORY="$DATA_DIRECTORY/tim-hardening-backups/$BUNDLE_ID"
MANAGED_CONFIG="$(dirname "$CONFIG_FILE")/tim-observe-hardening.conf"
MANAGED_HBA="$(dirname "$HBA_FILE")/tim-observe-hba.conf"
CONFIG_INCLUDE="include_if_exists = 'tim-observe-hardening.conf'"
HBA_INCLUDE="include 'tim-observe-hba.conf'"
CONFIG_UID="$(stat -f '%u' "$CONFIG_FILE")"
CONFIG_GID="$(stat -f '%g' "$CONFIG_FILE")"
HBA_UID="$(stat -f '%u' "$HBA_FILE")"
HBA_GID="$(stat -f '%g' "$HBA_FILE")"
HBA_MODE="$(stat -f '%Lp' "$HBA_FILE")"
BASELINE_CONFIG_HASH="$(shasum -a 256 "$CONFIG_FILE" | awk '{print $1}')"
BASELINE_HBA_HASH="$(shasum -a 256 "$HBA_FILE" | awk '{print $1}')"

mkdir -p "$BACKUP_DIRECTORY"
chmod 700 "$BACKUP_DIRECTORY"
if [[ ! -f "$BACKUP_DIRECTORY/postgresql.conf" ]]; then
  cp -p "$CONFIG_FILE" "$BACKUP_DIRECTORY/postgresql.conf"
fi
if [[ ! -f "$BACKUP_DIRECTORY/pg_hba.conf" ]]; then
  cp -p "$HBA_FILE" "$BACKUP_DIRECTORY/pg_hba.conf"
fi
if [[ ! -e "$BACKUP_DIRECTORY/managed-files-inventoried" ]]; then
  if [[ -f "$MANAGED_CONFIG" ]]; then
    cp -p "$MANAGED_CONFIG" "$BACKUP_DIRECTORY/tim-observe-hardening.conf"
  fi
  if [[ -f "$MANAGED_HBA" ]]; then
    cp -p "$MANAGED_HBA" "$BACKUP_DIRECTORY/tim-observe-hba.conf"
  fi
  touch "$BACKUP_DIRECTORY/managed-files-inventoried"
fi

ROLLBACK_REQUIRED=true
rollback_on_error() {
  if [[ "$ROLLBACK_REQUIRED" == true ]]; then
    cp -p "$BACKUP_DIRECTORY/postgresql.conf" "$CONFIG_FILE"
    cp -p "$BACKUP_DIRECTORY/pg_hba.conf" "$HBA_FILE"
    if [[ -f "$BACKUP_DIRECTORY/tim-observe-hardening.conf" ]]; then
      cp -p "$BACKUP_DIRECTORY/tim-observe-hardening.conf" "$MANAGED_CONFIG"
    else
      rm -f "$MANAGED_CONFIG"
    fi
    if [[ -f "$BACKUP_DIRECTORY/tim-observe-hba.conf" ]]; then
      cp -p "$BACKUP_DIRECTORY/tim-observe-hba.conf" "$MANAGED_HBA"
    else
      rm -f "$MANAGED_HBA"
    fi
    /bin/launchctl kickstart -k "$SERVICE" >/dev/null 2>&1 || true
  fi
}
trap rollback_on_error ERR INT TERM

cat >"$MANAGED_CONFIG" <<'CONF'
# TIM OBSERVE-only managed PostgreSQL boundary.
listen_addresses = '127.0.0.1,::1'
password_encryption = 'scram-sha-256'
CONF
chmod 600 "$MANAGED_CONFIG"
chown "$CONFIG_UID:$CONFIG_GID" "$MANAGED_CONFIG"

cat >"$MANAGED_HBA" <<'HBA'
# TIM OBSERVE-only managed rules. Included before all legacy rules.
local   tim   tim                         scram-sha-256
host    tim   tim   127.0.0.1/32          scram-sha-256
host    tim   tim   ::1/128               scram-sha-256
host    all   all   0.0.0.0/0             reject
host    all   all   ::/0                  reject
HBA
chmod 600 "$MANAGED_HBA"
chown "$HBA_UID:$HBA_GID" "$MANAGED_HBA"

if ! grep -Fqx "$CONFIG_INCLUDE" "$CONFIG_FILE"; then
  printf '\n%s\n' "$CONFIG_INCLUDE" >>"$CONFIG_FILE"
fi
if ! grep -Fqx "$HBA_INCLUDE" "$HBA_FILE"; then
  temporary_hba="$(mktemp "$(dirname "$HBA_FILE")/.tim-hba.XXXXXX")"
  {
    printf '%s\n' "$HBA_INCLUDE"
    cat "$HBA_FILE"
  } >"$temporary_hba"
  chmod "$HBA_MODE" "$temporary_hba"
  chown "$HBA_UID:$HBA_GID" "$temporary_hba"
  mv "$temporary_hba" "$HBA_FILE"
fi

/usr/bin/python3 - "$HANDOFF" <<'PY' | "$PSQL_BIN" -X -v ON_ERROR_STOP=1 -U "$ADMIN_USER" -d "$ADMIN_DATABASE"
import json,re,sys
value=json.load(open(sys.argv[1], encoding='utf-8'))
verifier=value['scram_verifier']
if not re.fullmatch(r'SCRAM-SHA-256\$[0-9]+:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+',verifier): raise SystemExit(2)
print("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='tim') THEN RAISE EXCEPTION 'TIM role missing'; END IF; END $$;")
print("ALTER ROLE tim WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '"+verifier+"';")
PY

/bin/launchctl kickstart -k "$SERVICE"
PG_ISREADY_BIN="$(dirname "$PSQL_BIN")/pg_isready"
if [[ ! -x "$PG_ISREADY_BIN" ]]; then
  echo '{"status":"FAIL","reason":"pg_isready is unavailable after restart"}' >&2
  false
fi
for _ in {1..30}; do
  if "$PG_ISREADY_BIN" -q -d "$ADMIN_DATABASE"; then
    break
  fi
  sleep 1
done
if ! "$PG_ISREADY_BIN" -q -d "$ADMIN_DATABASE"; then
  echo '{"status":"FAIL","reason":"PostgreSQL did not become ready after restart"}' >&2
  false
fi

VERIFY_OUTPUT="$("$PSQL_BIN" -X -v ON_ERROR_STOP=1 -U "$ADMIN_USER" -d "$ADMIN_DATABASE" -At <<'SQL'
SELECT CASE WHEN current_setting('listen_addresses') IN ('127.0.0.1,::1','::1,127.0.0.1') THEN 'LISTENER_PASS' ELSE 'LISTENER_FAIL' END;
SELECT CASE WHEN current_setting('password_encryption')='scram-sha-256' THEN 'SCRAM_PASS' ELSE 'SCRAM_FAIL' END;
SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM pg_hba_file_rules WHERE error IS NOT NULL) THEN 'HBA_PASS' ELSE 'HBA_FAIL' END;
SQL
)"
if [[ "$VERIFY_OUTPUT" != *LISTENER_PASS* || "$VERIFY_OUTPUT" != *SCRAM_PASS* || "$VERIFY_OUTPUT" != *HBA_PASS* ]]; then
  echo '{"status":"FAIL","reason":"PostgreSQL post-restart validation failed"}' >&2
  false
fi

ROLLBACK_REQUIRED=false
trap - ERR INT TERM
CONFIG_HASH="$(shasum -a 256 "$CONFIG_FILE" | awk '{print $1}')"
HBA_HASH="$(shasum -a 256 "$HBA_FILE" | awk '{print $1}')"
MANAGED_CONFIG_HASH="$(shasum -a 256 "$MANAGED_CONFIG" | awk '{print $1}')"
MANAGED_HBA_HASH="$(shasum -a 256 "$MANAGED_HBA" | awk '{print $1}')"
printf '{"status":"ADMIN_APPLY_PASS","service":"%s","server_version":"%s","backup_directory":"%s","config_sha256_before":"%s","config_sha256_after":"%s","hba_sha256_before":"%s","hba_sha256_after":"%s","managed_config_sha256":"%s","managed_hba_sha256":"%s","secret_printed":false}\n' "$SERVICE" "$SERVER_VERSION" "$BACKUP_DIRECTORY" "$BASELINE_CONFIG_HASH" "$CONFIG_HASH" "$BASELINE_HBA_HASH" "$HBA_HASH" "$MANAGED_CONFIG_HASH" "$MANAGED_HBA_HASH"
