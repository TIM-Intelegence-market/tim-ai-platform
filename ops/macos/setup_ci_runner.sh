#!/usr/bin/env bash
# Set up the self-hosted GitHub Actions runner for TIM on the Mac mini (docs/CI_SELF_HOSTED_RUNNER.md).
#
#   sudo bash ops/macos/setup_ci_runner.sh
#
# What it does, each step skipped when already done:
#   1. installs postgresql@16, gh and python@3.13 (python3 for the PR gate) with Homebrew (as the calling admin user, not root),
#   2. creates the hidden standard user `timrunner` (no admin rights, random password nobody knows),
#   3. creates an isolated PostgreSQL 16 cluster for tests owned by timrunner on 127.0.0.1:5434
#      (role tim, password tim_ci_only, database tim_test) and starts it as LaunchDaemon,
#   4. downloads the GitHub Actions runner, checks its SHA-256 against the release notes, registers it
#      for TIM-Intelegence-market/tim-ai-platform with the label tim-ci and starts it as LaunchDaemon.
#
# The registration token is read from the terminal and never written to disk. PR code that the runner
# executes runs as timrunner, never as the admin user.
set -euo pipefail

REPO_URL="https://github.com/TIM-Intelegence-market/tim-ai-platform"
RUNNER_USER="timrunner"
RUNNER_NAME="mac-mini-tim"
RUNNER_LABELS="tim-ci"
PG_PORT=5434
PG_VERSION=16
RUNNER_HOME="/Users/${RUNNER_USER}"
RUNNER_DIR="${RUNNER_HOME}/actions-runner"
PG_DATA="${RUNNER_HOME}/ci-postgres"
LOG_DIR="${RUNNER_HOME}/Library/Logs"
RUNNER_PLIST="/Library/LaunchDaemons/com.tim.ci-runner.plist"
PG_PLIST="/Library/LaunchDaemons/com.tim.ci-postgres.plist"

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nFEHLER: %s\n' "$*" >&2; exit 1; }
as_runner() { sudo -u "$RUNNER_USER" -H "$@"; }

[ "$(uname -s)" = "Darwin" ] || die "nur für macOS"
[ "$(id -u)" -eq 0 ] || die "bitte mit sudo starten: sudo bash $0"
ADMIN_USER="${SUDO_USER:-}"
[ -n "$ADMIN_USER" ] && [ "$ADMIN_USER" != "root" ] || die "mit sudo aus dem eigenen Konto starten, nicht als root einloggen"

# Commands run as timrunner must not start in the admin's home, which timrunner cannot read.
cd /

case "$(uname -m)" in
  arm64) RUNNER_ARCH="osx-arm64" ;;
  x86_64) RUNNER_ARCH="osx-x64" ;;
  *) die "unbekannte Architektur $(uname -m)" ;;
esac

BREW=""
for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  [ -x "$candidate" ] && BREW="$candidate" && break
done
[ -n "$BREW" ] || die "Homebrew fehlt (https://brew.sh), danach erneut starten"
BREW_PREFIX="$(sudo -u "$ADMIN_USER" "$BREW" --prefix)"
PG_BIN="${BREW_PREFIX}/opt/postgresql@${PG_VERSION}/bin"
SERVICE_PATH="${BREW_PREFIX}/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

say "1/4 Homebrew-Pakete (postgresql@${PG_VERSION}, gh, python@3.13)"
for formula in "postgresql@${PG_VERSION}" gh python@3.13; do
  if sudo -u "$ADMIN_USER" "$BREW" list --versions "$formula" >/dev/null 2>&1; then
    echo "$formula ist vorhanden"
  else
    sudo -u "$ADMIN_USER" "$BREW" install "$formula"
  fi
done
[ -x "${PG_BIN}/initdb" ] || die "initdb nicht gefunden unter ${PG_BIN}"

say "2/4 Benutzer ${RUNNER_USER}"
if id "$RUNNER_USER" >/dev/null 2>&1; then
  echo "${RUNNER_USER} existiert"
else
  sysadminctl -addUser "$RUNNER_USER" -fullName "TIM CI Runner" -home "$RUNNER_HOME" \
    -password "$(openssl rand -base64 32)" >/dev/null 2>&1
  createhomedir -c -u "$RUNNER_USER" >/dev/null
  dscl . -create "/Users/${RUNNER_USER}" IsHidden 1
  echo "${RUNNER_USER} angelegt (versteckt, kein Admin)"
fi
id -Gn "$RUNNER_USER" | tr ' ' '\n' | grep -qx admin && die "${RUNNER_USER} ist Admin; das darf der Runner nicht sein"
chmod 700 "$RUNNER_HOME"
as_runner mkdir -p "$LOG_DIR"
admin_home="$(dscl . -read "/Users/${ADMIN_USER}" NFSHomeDirectory | awk '{print $2}')"
if [ -n "$admin_home" ] && [ "$(stat -f '%Lp' "$admin_home" | cut -c3)" -ge 4 ]; then
  echo "WARNUNG: ${admin_home} ist für andere Benutzer lesbar. Empfohlen: sudo chmod 750 ${admin_home}"
fi

say "3/4 Test-Datenbank auf 127.0.0.1:${PG_PORT}"
if [ ! -f "${PG_DATA}/PG_VERSION" ]; then
  as_runner "${PG_BIN}/initdb" -D "$PG_DATA" -U "$RUNNER_USER" --auth-local=trust --auth-host=scram-sha-256 \
    --encoding=UTF8 >/dev/null
  {
    echo "listen_addresses = '127.0.0.1'"
    echo "port = ${PG_PORT}"
    echo "unix_socket_directories = '${PG_DATA}'"
  } | as_runner tee -a "${PG_DATA}/postgresql.conf" >/dev/null
fi
cat > "$PG_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.tim.ci-postgres</string>
  <key>UserName</key><string>${RUNNER_USER}</string>
  <key>ProgramArguments</key>
  <array><string>${PG_BIN}/postgres</string><string>-D</string><string>${PG_DATA}</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>LC_ALL</key><string>en_US.UTF-8</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${LOG_DIR}/ci-postgres.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/ci-postgres.log</string>
</dict>
</plist>
PLIST
chmod 644 "$PG_PLIST"
launchctl bootout system "$PG_PLIST" >/dev/null 2>&1 || true
launchctl bootstrap system "$PG_PLIST"
for _ in $(seq 1 30); do
  as_runner "${PG_BIN}/pg_isready" -h "$PG_DATA" -p "$PG_PORT" >/dev/null 2>&1 && break
  sleep 1
done
as_runner "${PG_BIN}/pg_isready" -h "$PG_DATA" -p "$PG_PORT" >/dev/null || die "PostgreSQL startet nicht, siehe ${LOG_DIR}/ci-postgres.log"
psql_admin() { as_runner "${PG_BIN}/psql" -h "$PG_DATA" -p "$PG_PORT" -d postgres -v ON_ERROR_STOP=1 -qtA "$@"; }
if [ "$(psql_admin -c "SELECT 1 FROM pg_roles WHERE rolname = 'tim'")" != "1" ]; then
  psql_admin -c "CREATE ROLE tim LOGIN PASSWORD 'tim_ci_only'"
fi
if [ "$(psql_admin -c "SELECT 1 FROM pg_database WHERE datname = 'tim_test'")" != "1" ]; then
  psql_admin -c "CREATE DATABASE tim_test OWNER tim"
fi
echo "tim_test läuft auf 127.0.0.1:${PG_PORT}"

say "4/4 GitHub-Actions-Runner"
if [ ! -f "${RUNNER_DIR}/.runner" ]; then
  release_json="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest)"
  version="$(printf '%s' "$release_json" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"].lstrip("v"))')"
  expected="$(printf '%s' "$release_json" | /usr/bin/python3 -c '
import json, re, sys
body = json.load(sys.stdin)["body"]
m = re.search(r"<!-- BEGIN SHA " + sys.argv[1] + r" -->([0-9a-f]{64})<!-- END SHA", body)
print(m.group(1) if m else "")' "$RUNNER_ARCH")"
  [ -n "$expected" ] || die "keine Prüfsumme für ${RUNNER_ARCH} in den Release-Notizen von ${version}"
  archive="actions-runner-${RUNNER_ARCH}-${version}.tar.gz"
  as_runner mkdir -p "$RUNNER_DIR"
  as_runner curl -fsSL -o "${RUNNER_DIR}/${archive}" \
    "https://github.com/actions/runner/releases/download/v${version}/${archive}"
  actual="$(shasum -a 256 "${RUNNER_DIR}/${archive}" | awk '{print $1}')"
  [ "$actual" = "$expected" ] || { rm -f "${RUNNER_DIR}/${archive}"; die "Prüfsumme stimmt nicht (${archive})"; }
  as_runner tar -xzf "${RUNNER_DIR}/${archive}" -C "$RUNNER_DIR"
  rm -f "${RUNNER_DIR}/${archive}"
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
cat > "$RUNNER_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.tim.ci-runner</string>
  <key>UserName</key><string>${RUNNER_USER}</string>
  <key>WorkingDirectory</key><string>${RUNNER_DIR}</string>
  <key>ProgramArguments</key><array><string>${RUNNER_DIR}/run.sh</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>${SERVICE_PATH}</string>
    <key>HOME</key><string>${RUNNER_HOME}</string>
    <key>LC_ALL</key><string>en_US.UTF-8</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>${LOG_DIR}/ci-runner.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/ci-runner.log</string>
</dict>
</plist>
PLIST
chmod 644 "$RUNNER_PLIST"
launchctl bootout system "$RUNNER_PLIST" >/dev/null 2>&1 || true
launchctl bootstrap system "$RUNNER_PLIST"
sleep 5
if tail -n 20 "${LOG_DIR}/ci-runner.log" 2>/dev/null | grep -q "Listening for Jobs"; then
  say "Fertig: Runner ${RUNNER_NAME} wartet auf Jobs."
else
  say "Runner gestartet; Status prüfen mit: sudo tail -n 30 ${LOG_DIR}/ci-runner.log"
fi
