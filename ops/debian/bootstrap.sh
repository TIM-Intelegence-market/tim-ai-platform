#!/usr/bin/env bash
# One-time, idempotent setup of a Debian 13 server for TIM (OBSERVE only).
# Packages P1 and P2 of docs/autonomous_trader/DEBIAN_SERVER_SETUP_TASK_PACKAGE.md
# plus installing the units from ops/systemd. Run as root on the server:
#
#   bash /opt/tim/ops/debian/bootstrap.sh            # prepare only, starts nothing
#   bash /opt/tim/ops/debian/bootstrap.sh --start    # prepare, then enable and start TIM
#   add --with-firewall to enable ufw with only SSH allowed
#
# Expects the repository checked out at /opt/tim (branch platform-main).
# Never prints the database password; it is generated once into /etc/tim/database-password.
set -euo pipefail

ROOT=/opt/tim
ETC=/etc/tim
SECRET="$ETC/database-password"
BACKUPS=/var/backups/tim
START=false
FIREWALL=false
for argument in "$@"; do
  case "$argument" in
    --start) START=true ;;
    --with-firewall) FIREWALL=true ;;
    *) echo "unknown option: $argument" >&2; exit 64 ;;
  esac
done

step() { printf '\n== %s\n' "$1"; }

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
[[ -f "$ROOT/main.py" && -d "$ROOT/ops/systemd" ]] || { echo "TIM checkout missing at $ROOT" >&2; exit 2; }
. /etc/os-release
[[ "${ID:-}" == "debian" ]] || { echo "this script is for Debian (found ${ID:-unknown})" >&2; exit 3; }

step "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q postgresql postgresql-client chrony python3 python3-venv git iproute2 polkitd \
  unattended-upgrades ufw ca-certificates
python3 -c 'import sys; assert sys.version_info >= (3, 13), sys.version' \
  || { echo "Python 3.13 required (Debian 13 ships it)" >&2; exit 4; }

step "time sync"
systemctl enable --now chrony
chronyc -n tracking | grep -E 'Leap status|System time' || true

step "service user"
id tim >/dev/null 2>&1 || useradd --system --home-dir /var/lib/tim --create-home --shell /usr/sbin/nologin tim

step "directories"
install -d -o root -g tim -m 0750 "$ETC"
install -d -o tim -g tim -m 0750 "$ROOT/data" "$ROOT/artifacts" "$BACKUPS"

step "python environment"
[[ -x "$ROOT/.venv/bin/python" ]] || python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install -q --upgrade pip
"$ROOT/.venv/bin/python" -m pip install -q -r "$ROOT/requirements.txt"

step "database password (generated once, never printed)"
if [[ ! -s "$SECRET" ]]; then
  umask 077
  python3 -c 'import secrets, string; a = string.ascii_letters + string.digits; print("".join(secrets.choice(a) for _ in range(40)))' > "$SECRET"
fi
chown tim:tim "$SECRET"
chmod 0600 "$SECRET"

step "postgresql (loopback only)"
systemctl enable --now postgresql
# The password goes in through stdin, never argv. It is alphanumeric, so quoting is safe.
PASSWORD="$(cat "$SECRET")"
runuser -u postgres -- psql -q -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tim') THEN CREATE ROLE tim LOGIN; END IF;
END \$\$;
ALTER ROLE tim WITH LOGIN CREATEDB PASSWORD '${PASSWORD}';
SQL
unset PASSWORD
runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname = 'tim'" | grep -q 1 \
  || runuser -u postgres -- createdb --owner=tim tim
listen="$(runuser -u postgres -- psql -tAc 'SHOW listen_addresses')"
[[ "$listen" == "localhost" || "$listen" == "127.0.0.1" ]] \
  || { echo "PostgreSQL listen_addresses is '$listen'; TIM requires loopback only" >&2; exit 5; }

step "environment file"
[[ -f "$ETC/tim.env" ]] || install -o root -g tim -m 0640 "$ROOT/ops/systemd/tim.env.example" "$ETC/tim.env"

step "systemd units and polkit rule"
install -o root -g root -m 0644 "$ROOT"/ops/systemd/tim-*.service "$ROOT"/ops/systemd/tim-*.timer /etc/systemd/system/
install -d -m 0755 /etc/polkit-1/rules.d
install -o root -g root -m 0644 "$ROOT/ops/systemd/50-tim-runtime.rules" /etc/polkit-1/rules.d/
systemd-analyze verify /etc/systemd/system/tim-*.service /etc/systemd/system/tim-*.timer
systemctl daemon-reload

step "secret provider check"
runuser -u tim -- env $(grep -v '^#' "$ETC/tim.env" | xargs) "$ROOT/.venv/bin/python" -c \
  "import sys; sys.path.insert(0, '$ROOT'); from config.secrets import DatabaseSecretResolver; from config.settings import settings; print(DatabaseSecretResolver().status(settings.database_endpoint))"

if [[ "$FIREWALL" == true ]]; then
  step "firewall (SSH only)"
  ufw allow OpenSSH
  ufw --force enable
fi

if [[ "$START" == true ]]; then
  step "start TIM"
  systemctl enable --now tim-runtime.service
  systemctl enable --now tim-candle-finalizer.timer tim-rolling-liveness.timer tim-maintenance.timer \
    tim-coverage-worker.timer tim-backup.timer tim-restore-test.timer tim-server-health.timer
  systemctl enable --now tim-watchdog.service
  sleep 20
  systemctl --no-pager --lines=0 status tim-runtime.service || true
  systemctl list-timers 'tim-*' --no-pager
  echo "First backup now, so the health check has one:"
  systemctl start tim-backup.service && cat "$ROOT/data/operational/backup_last_run.json"
else
  echo
  echo "Prepared. Nothing started. Run again with --start to enable and start TIM."
fi
