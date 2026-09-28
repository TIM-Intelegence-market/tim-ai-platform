#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIRECTORY=""
CONFIG_FILE=""
HBA_FILE=""
SERVICE="system/postgresql-18"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backup-directory) BACKUP_DIRECTORY="${2:-}"; shift 2 ;;
    --config-file) CONFIG_FILE="${2:-}"; shift 2 ;;
    --hba-file) HBA_FILE="${2:-}"; shift 2 ;;
    --service) SERVICE="${2:-}"; shift 2 ;;
    *) exit 2 ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo '{"status":"BLOCKED","reason":"legitimate macOS administrator execution required; script does not escalate privileges"}' >&2
  exit 2
fi
if [[ "$SERVICE" != "system/postgresql-18" || ! -f "$BACKUP_DIRECTORY/postgresql.conf" || ! -f "$BACKUP_DIRECTORY/pg_hba.conf" ]]; then
  echo '{"status":"BLOCKED","reason":"validated backup and inspected service are required"}' >&2
  exit 2
fi
if [[ -z "$CONFIG_FILE" || -z "$HBA_FILE" ]]; then
  echo '{"status":"BLOCKED","reason":"explicit target paths are required"}' >&2
  exit 2
fi

cp -p "$BACKUP_DIRECTORY/postgresql.conf" "$CONFIG_FILE"
cp -p "$BACKUP_DIRECTORY/pg_hba.conf" "$HBA_FILE"
MANAGED_CONFIG="$(dirname "$CONFIG_FILE")/tim-observe-hardening.conf"
MANAGED_HBA="$(dirname "$HBA_FILE")/tim-observe-hba.conf"
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
/bin/launchctl kickstart -k "$SERVICE"
echo '{"status":"ROLLBACK_PASS","credential_rollback":false,"reason":"rotated credentials are intentionally not reverted"}'
