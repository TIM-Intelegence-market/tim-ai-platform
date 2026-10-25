#!/usr/bin/env bash
# Set up the Qwen issue worker for hard issues (agent:qwen-hard) on tim-core-01, beside the CI runner.
#
#   sudo bash ops/linux/setup_issue_worker.sh
#
# What it does, each step skipped when already done:
#   1. checks that the old tim-qwen-worker is retired (docs/TIM_CHECKUP.md, "Einschalten", step 1), that
#      ollama answers with qwen3-coder:30b (never pulls a model), and installs bubblewrap, python3.13-venv, gh,
#      git and curl with apt,
#   2. creates the system user `timworker` (no sudo, no extra groups, no login shell), home /srv/worker (700),
#   3. logs that user in to GitHub as apoman74-art: the token is read from the terminal, never shown, never an
#      argument; the login must have push but neither admin nor maintain on the repository,
#   4. clones the repository to /srv/worker/repo (detached at origin/platform-main) with a venv,
#   5. runs the sandbox self-test and a dry run as timworker, then installs tim-issue-worker.service, .timer and
#      /etc/tim-issue-worker.env. Nothing is started and nothing is enabled.
#
# Switch the Mac to TIM_WORKER_LANE=easy first, then: sudo systemctl enable --now tim-issue-worker.timer
set -euo pipefail

REPO="TIM-Intelegence-market/tim-ai-platform"
WORKER_USER="timworker"
WORKER_LOGIN="apoman74-art"
WORKER_HOME="/srv/worker"
REPO_DIR="${WORKER_HOME}/repo"
GH_DIR="${WORKER_HOME}/.config/gh-tim-mac-worker"
MODEL="qwen3-coder:30b"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nFEHLER: %s\n' "$*" >&2; exit 1; }
as_worker() { sudo -u "$WORKER_USER" -H env HOME="$WORKER_HOME" GH_CONFIG_DIR="$GH_DIR" "$@"; }

[ "$(uname -s)" = "Linux" ] && [ -r /etc/debian_version ] || die "nur für Debian"
[ "$(id -u)" -eq 0 ] || die "bitte mit sudo starten: sudo bash $0"
for file in tim-issue-worker.service tim-issue-worker.timer tim-issue-worker.env; do
  [ -f "${SRC_DIR}/${file}" ] || die "${SRC_DIR}/${file} fehlt; aus einem Checkout des Repos starten"
done
cd /

say "1/5 Voraussetzungen"
if systemctl is-active --quiet tim-qwen-worker.service \
   || pgrep -f '[r]un_local_qwen|[t]im-qwen-worker' >/dev/null; then
  die "der alte tim-qwen-worker läuft noch; erst docs/TIM_CHECKUP.md, Abschnitt Einschalten, Schritt 1"
fi
curl -fsS -m 10 http://127.0.0.1:11434/api/tags | python3 -c "
import json, sys
names = {m.get('name') for m in json.load(sys.stdin).get('models', [])}
sys.exit(0 if '${MODEL}' in names else 1)" || die "ollama antwortet nicht mit ${MODEL} (nie ollama pull hier)"
echo "ollama hat ${MODEL}"
missing=()
for pkg in bubblewrap python3.13-venv gh git curl; do
  dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed" || missing+=("$pkg")
done
if [ "${#missing[@]}" -gt 0 ]; then
  apt-get update -qq
  apt-get install -y --no-install-recommends "${missing[@]}"
else
  echo "alle Pakete vorhanden"
fi
[ -x /usr/bin/bwrap ] || die "/usr/bin/bwrap fehlt"
[ -x /usr/bin/python3.13 ] || die "/usr/bin/python3.13 fehlt"

say "2/5 Benutzer ${WORKER_USER}"
if id "$WORKER_USER" >/dev/null 2>&1; then
  echo "${WORKER_USER} existiert"
else
  useradd --system --user-group --home-dir "$WORKER_HOME" --create-home --shell /usr/sbin/nologin \
    --comment "TIM issue worker (hard lane)" "$WORKER_USER"
  echo "${WORKER_USER} angelegt"
fi
extra_groups="$(id -Gn "$WORKER_USER" | tr ' ' '\n' | grep -vx "$WORKER_USER" || true)"
[ -z "$extra_groups" ] || die "${WORKER_USER} ist in weiteren Gruppen (${extra_groups//$'\n'/, }); das darf der Worker nicht sein"
chown "$WORKER_USER:$WORKER_USER" "$WORKER_HOME"
chmod 700 "$WORKER_HOME"
as_worker mkdir -p "$GH_DIR" "${WORKER_HOME}/state"
chmod 700 "$GH_DIR"

say "3/5 GitHub-Anmeldung als ${WORKER_LOGIN}"
if as_worker gh auth status --hostname github.com >/dev/null 2>&1; then
  echo "bereits angemeldet"
else
  echo "Token des Kontos ${WORKER_LOGIN} (dasselbe wie auf dem Mac oder ein neues mit denselben Rechten)."
  read -rsp "Token einfügen (wird nicht angezeigt): " token </dev/tty
  echo
  [ -n "$token" ] || die "kein Token eingegeben"
  printf '%s\n' "$token" | as_worker gh auth login --hostname github.com --git-protocol https --with-token \
    || { unset token; die "Anmeldung abgelehnt"; }
  unset token
fi
login="$(as_worker gh api user --jq .login)"
[ "${login,,}" = "${WORKER_LOGIN,,}" ] || die "falscher GitHub-Login: ${login}, erwartet ${WORKER_LOGIN}"
perms="$(as_worker gh api "repos/${REPO}" --jq '[.permissions.push, .permissions.maintain, .permissions.admin] | @csv')"
[ "$perms" = "true,false,false" ] || die "Rechte von ${WORKER_LOGIN} sind nicht genau push ohne maintain/admin (${perms})"
echo "angemeldet als ${login}, Rechte geprüft"
chmod -R go-rwx "$GH_DIR"

say "4/5 Checkout und venv"
if [ ! -d "${REPO_DIR}/.git" ]; then
  as_worker gh repo clone "$REPO" "$REPO_DIR" -- --quiet
fi
as_worker git -C "$REPO_DIR" -c credential.helper= -c 'credential.helper=!gh auth git-credential' fetch --quiet origin platform-main
as_worker git -C "$REPO_DIR" checkout --quiet --detach origin/platform-main
[ -x "${REPO_DIR}/.venv/bin/python" ] || as_worker /usr/bin/python3.13 -m venv "${REPO_DIR}/.venv"
as_worker "${REPO_DIR}/.venv/bin/pip" install --quiet --upgrade pip
as_worker "${REPO_DIR}/.venv/bin/pip" install --quiet -r "${REPO_DIR}/requirements.txt"
echo "Checkout $(as_worker git -C "$REPO_DIR" rev-parse --short HEAD)"

say "5/5 Selbsttest, Probelauf, Units"
( cd "$REPO_DIR" && as_worker "${REPO_DIR}/.venv/bin/python" -m src.local_first.sandbox_runner ) \
  || die "Sandbox nicht dicht (Ausgabe oben)"
( cd "$REPO_DIR" && as_worker env TIM_WORKER_LANE=hard "${REPO_DIR}/.venv/bin/python" \
    scripts/run_mac_qwen_issue.py --state-dir "${WORKER_HOME}/state" --dry-run ) \
  || die "Probelauf fehlgeschlagen (Ausgabe oben)"
install -m 644 "${SRC_DIR}/tim-issue-worker.service" /etc/systemd/system/tim-issue-worker.service
install -m 644 "${SRC_DIR}/tim-issue-worker.timer" /etc/systemd/system/tim-issue-worker.timer
[ -f /etc/tim-issue-worker.env ] || install -m 600 "${SRC_DIR}/tim-issue-worker.env" /etc/tim-issue-worker.env
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/tim-issue-worker.service /etc/systemd/system/tim-issue-worker.timer

say "Fertig. Nichts läuft, nichts ist eingeschaltet."
echo "Zuerst den Mac auf TIM_WORKER_LANE=easy stellen (docs/mac-qwen-issue-worker.md)."
echo "Pilot:   in /etc/tim-issue-worker.env TIM_WORKER_ARGS=--pilot-issue <Nummer>, dann sudo systemctl start tim-issue-worker"
echo "Dauer:   TIM_WORKER_ARGS=--merge --self-update, dann sudo systemctl enable --now tim-issue-worker.timer"
echo "Log:     journalctl -u tim-issue-worker -n 50"
