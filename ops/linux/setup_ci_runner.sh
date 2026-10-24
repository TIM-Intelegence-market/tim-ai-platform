#!/usr/bin/env bash
# Set up the CI runner for TIM on tim-core-01 (Debian), next to the Mac mini runner (docs/CI_SELF_HOSTED_RUNNER.md).
#
#   sudo bash ops/linux/setup_ci_runner.sh
#
# The server runs either live TIM or CI, never both (switch with `sudo tim-mode ci|live`, see ops/linux/README.md).
# What it does, each step skipped when already done:
#   1. installs postgresql-16 (pgdg repository), python3.13-venv, gh, git and curl with apt,
#   2. creates the system user `timrunner` (no sudo, no extra groups, no login shell), home /srv/ci (mode 700),
#   3. creates an isolated PostgreSQL 16 cluster in /srv/ci/pg16 on 127.0.0.1:5434
#      (role tim, password tim_ci_only, database tim_test) with the unit tim-ci-postgres.service,
#   4. downloads the GitHub Actions runner, checks its SHA-256 against the release notes and registers it
#      for TIM-Intelegence-market/tim-ai-platform as tim-core-01-ci with the label in RUNNER_LABELS,
#   5. installs tim-ci-runner.service and /usr/local/sbin/tim-mode. Nothing is started and nothing is enabled:
#      the server stays in live mode until `sudo tim-mode ci`.
#
# The registration token is read from the terminal and never written to disk. Existing TIM services, /opt/tim,
# backups and the production PostgreSQL 18 cluster are not changed.
set -euo pipefail

REPO_URL="https://github.com/TIM-Intelegence-market/tim-ai-platform"
RUNNER_USER="timrunner"
RUNNER_NAME="tim-core-01-ci"
# tim-ci-linux only for the probe run; add tim-ci once ci.yml uses [self-hosted, tim-ci] (ops/linux/README.md).
RUNNER_LABELS="${RUNNER_LABELS:-tim-ci-linux}"
PG_PORT=5434
PG_VERSION=16
CI_HOME="/srv/ci"
RUNNER_DIR="${CI_HOME}/actions-runner"
PG_DATA="${CI_HOME}/pg16"
PG_BIN="/usr/lib/postgresql/${PG_VERSION}/bin"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nFEHLER: %s\n' "$*" >&2; exit 1; }
as_runner() { sudo -u "$RUNNER_USER" -H "$@"; }

[ "$(uname -s)" = "Linux" ] && [ -r /etc/debian_version ] || die "nur für Debian"
[ "$(id -u)" -eq 0 ] || die "bitte mit sudo starten: sudo bash $0"
[ "$(uname -m)" = "x86_64" ] || die "unbekannte Architektur $(uname -m)"
for file in tim-ci-postgres.service tim-ci-runner.service tim-mode; do
  [ -f "${SRC_DIR}/${file}" ] || die "${SRC_DIR}/${file} fehlt; aus einem Checkout des Repos starten"
done
cd /

say "1/5 Pakete (postgresql-${PG_VERSION}, python3.13-venv, gh, git, curl)"
missing=()
for pkg in "postgresql-${PG_VERSION}" python3.13-venv gh git curl; do
  dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed" || missing+=("$pkg")
done
if [ "${#missing[@]}" -gt 0 ]; then
  clusters_before="$(pg_lsclusters -h 2>/dev/null | awk '{print $1"/"$2}' || true)"
  apt-get update -qq
  apt-get install -y --no-install-recommends "${missing[@]}"
  # Debian creates and starts a default 16/main cluster on install. CI uses its own cluster, so drop that new,
  # empty one again; any cluster that existed before (the production 18/main) is left alone.
  if ! printf '%s\n' "$clusters_before" | grep -qx "${PG_VERSION}/main" \
     && pg_lsclusters -h 2>/dev/null | awk '{print $1"/"$2}' | grep -qx "${PG_VERSION}/main"; then
    pg_dropcluster --stop "$PG_VERSION" main
    echo "frisch angelegten Standard-Cluster ${PG_VERSION}/main wieder entfernt"
  fi
else
  echo "alle Pakete vorhanden"
fi
[ -x "${PG_BIN}/initdb" ] || die "initdb nicht gefunden unter ${PG_BIN}"
[ -x /usr/bin/python3.13 ] || die "/usr/bin/python3.13 fehlt"

say "2/5 Benutzer ${RUNNER_USER}"
if id "$RUNNER_USER" >/dev/null 2>&1; then
  echo "${RUNNER_USER} existiert"
else
  useradd --system --user-group --home-dir "$CI_HOME" --create-home --shell /usr/sbin/nologin \
    --comment "TIM CI runner" "$RUNNER_USER"
  echo "${RUNNER_USER} angelegt"
fi
extra_groups="$(id -Gn "$RUNNER_USER" | tr ' ' '\n' | grep -vx "$RUNNER_USER" || true)"
[ -z "$extra_groups" ] || die "${RUNNER_USER} ist in weiteren Gruppen (${extra_groups//$'\n'/, }); das darf der Runner nicht sein"
chown "$RUNNER_USER:$RUNNER_USER" "$CI_HOME"
chmod 700 "$CI_HOME"
if as_runner test -r /opt/tim 2>/dev/null && as_runner ls /opt/tim >/dev/null 2>&1; then
  echo "WARNUNG: ${RUNNER_USER} kann /opt/tim lesen. Die Runner-Unit sperrt den Pfad zusätzlich (InaccessiblePaths)."
fi

say "3/5 Test-Datenbank auf 127.0.0.1:${PG_PORT}"
install -m 644 "${SRC_DIR}/tim-ci-postgres.service" /etc/systemd/system/tim-ci-postgres.service
systemctl daemon-reload
if [ ! -f "${PG_DATA}/PG_VERSION" ]; then
  as_runner "${PG_BIN}/initdb" -D "$PG_DATA" -U "$RUNNER_USER" --auth-local=peer --auth-host=scram-sha-256 \
    --encoding=UTF8 --locale=C.UTF-8 >/dev/null
  {
    echo "listen_addresses = '127.0.0.1'"
    echo "port = ${PG_PORT}"
    echo "unix_socket_directories = '${PG_DATA}'"
  } | as_runner tee -a "${PG_DATA}/postgresql.conf" >/dev/null
fi
pg_was_active="$(systemctl is-active tim-ci-postgres.service 2>/dev/null || true)"
systemctl start tim-ci-postgres.service
for _ in $(seq 1 30); do
  as_runner "${PG_BIN}/pg_isready" -h "$PG_DATA" -p "$PG_PORT" >/dev/null 2>&1 && break
  sleep 1
done
as_runner "${PG_BIN}/pg_isready" -h "$PG_DATA" -p "$PG_PORT" >/dev/null \
  || die "PostgreSQL startet nicht, siehe: journalctl -u tim-ci-postgres -n 30"
psql_admin() { as_runner "${PG_BIN}/psql" -h "$PG_DATA" -p "$PG_PORT" -d postgres -v ON_ERROR_STOP=1 -qtA "$@"; }
if [ "$(psql_admin -c "SELECT 1 FROM pg_roles WHERE rolname = 'tim'")" != "1" ]; then
  psql_admin -c "CREATE ROLE tim LOGIN PASSWORD 'tim_ci_only'"
fi
if [ "$(psql_admin -c "SELECT 1 FROM pg_database WHERE datname = 'tim_test'")" != "1" ]; then
  psql_admin -c "CREATE DATABASE tim_test OWNER tim"
fi
as_runner "${PG_BIN}/psql" "postgresql://tim:tim_ci_only@127.0.0.1:${PG_PORT}/tim_test" -qtAc 'select 1' >/dev/null \
  || die "Anmeldung als tim an tim_test scheitert"
echo "tim_test bereit auf 127.0.0.1:${PG_PORT}"
# The test database belongs to CI mode; leave it as it was before this step.
[ "$pg_was_active" = "active" ] || systemctl stop tim-ci-postgres.service

say "4/5 GitHub-Actions-Runner"
if [ ! -f "${RUNNER_DIR}/.runner" ]; then
  release_json="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest)"
  version="$(printf '%s' "$release_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"].lstrip("v"))')"
  expected="$(printf '%s' "$release_json" | python3 -c '
import json, re, sys
body = json.load(sys.stdin)["body"]
m = re.search(r"<!-- BEGIN SHA linux-x64 -->([0-9a-f]{64})<!-- END SHA", body)
print(m.group(1) if m else "")')"
  [ -n "$expected" ] || die "keine Prüfsumme für linux-x64 in den Release-Notizen von ${version}"
  archive="actions-runner-linux-x64-${version}.tar.gz"
  as_runner mkdir -p "$RUNNER_DIR"
  as_runner curl -fsSL -o "${RUNNER_DIR}/${archive}" \
    "https://github.com/actions/runner/releases/download/v${version}/${archive}"
  actual="$(sha256sum "${RUNNER_DIR}/${archive}" | awk '{print $1}')"
  [ "$actual" = "$expected" ] || { rm -f "${RUNNER_DIR}/${archive}"; die "Prüfsumme stimmt nicht (${archive})"; }
  as_runner tar -xzf "${RUNNER_DIR}/${archive}" -C "$RUNNER_DIR"
  rm -f "${RUNNER_DIR}/${archive}"
  # Shared libraries the runner needs (libicu and friends), installed by the runner's own script with apt.
  "${RUNNER_DIR}/bin/installdependencies.sh"
  echo
  echo "Registrierungs-Token: GitHub → ${REPO_URL}/settings/actions/runners/new → den Wert hinter --token kopieren."
  read -rsp "Token einfügen (wird nicht angezeigt): " token </dev/tty
  echo
  [ -n "$token" ] || die "kein Token eingegeben"
  ( cd "$RUNNER_DIR" && as_runner ./config.sh --unattended --replace --url "$REPO_URL" --token "$token" \
      --name "$RUNNER_NAME" --labels "$RUNNER_LABELS" --work _work )
  unset token
else
  echo "Runner ist bereits registriert ($(grep -o '"agentName": *"[^"]*"' "${RUNNER_DIR}/.runner" || true))"
fi

say "5/5 Units und tim-mode"
install -m 644 "${SRC_DIR}/tim-ci-runner.service" /etc/systemd/system/tim-ci-runner.service
install -m 755 "${SRC_DIR}/tim-mode" /usr/local/sbin/tim-mode
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/tim-ci-runner.service /etc/systemd/system/tim-ci-postgres.service

say "Fertig. Der Server ist weiter im Live-Modus."
echo "CI-Modus:   sudo tim-mode ci        (zurück nach 6 h automatisch, --hours N ändert das)"
echo "Live-Modus: sudo tim-mode live"
echo "Status:     tim-mode status"
