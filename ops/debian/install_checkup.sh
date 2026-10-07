#!/usr/bin/env bash
# Install the TIM checkup and incident reporter (OBSERVE only) on the Debian server. Idempotent.
# Run as root after the code is deployed to /opt/tim; the steps and their order are in docs/TIM_CHECKUP.md:
#
#   bash /opt/tim/ops/debian/install_checkup.sh               # data dir, key placeholder, units, timer, authority body
#   bash /opt/tim/ops/debian/install_checkup.sh --app-key     # paste the GitHub App private key (PEM), end with Ctrl-D
#   bash /opt/tim/ops/debian/install_checkup.sh --configure --app-id N --installation-id N --authority-issue N \
#     [--watch-issue N] --reporter-login SLUG[bot] --owner-login LOGIN --reporting off|dry-run|on --diagnosis off|on
#   bash /opt/tim/ops/debian/install_checkup.sh --uninstall   # timer off, units removed; data and key stay as evidence
#
# Reporting stays off until --configure sets it. The key is never printed and never passed as an argument.
# bootstrap.sh copies tim-checkup.* by glob but never enables them; only this script does.
# The checkup never repairs, restarts, fills gaps or empties queues.
set -euo pipefail
export LC_ALL=C   # plain ASCII ranges in the value checks below

ROOT=/opt/tim
ETC=/etc/tim
ENV_FILE="$ETC/tim.env"
KEY="$ETC/github-app.pem"
INCIDENTS="$ROOT/data/incidents"
UNIT_DIR=/etc/systemd/system
UNITS=(tim-checkup.service tim-checkup.timer)
REPOSITORY=TIM-Intelegence-market/tim-ai-platform
NUMBER_RE='^[1-9][0-9]{0,11}$'
LOGIN_RE='^[A-Za-z0-9][A-Za-z0-9-]{0,38}(\[bot\])?$'   # WORKER_LOGIN in scripts/github_issue_pipeline.py

TMP_FILE=""
TTY_STATE=""
cleanup() {
  if [[ -n "$TTY_STATE" ]]; then stty "$TTY_STATE" 2>/dev/null || true; fi
  if [[ -n "$TMP_FILE" ]]; then rm -f -- "$TMP_FILE"; fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

step() { printf '\n== %s\n' "$1"; }
fail() { echo "$1" >&2; exit "${2:-1}"; }
require_root() { [[ $EUID -eq 0 ]] || fail "run as root" 1; }

usage() {
  cat <<'EOF'
usage: install_checkup.sh                 install units, enable the timer, print the authority issue body
       install_checkup.sh --app-key       store the GitHub App private key (pasted, not shown)
       install_checkup.sh --configure --app-id N --installation-id N --authority-issue N [--watch-issue N]
                          --reporter-login SLUG[bot] --owner-login LOGIN --reporting off|dry-run|on --diagnosis off|on
       install_checkup.sh --uninstall     disable the timer, remove the units, keep data and key
EOF
}

# --- --configure: parse and validate (no root needed, testable with a temporary env file) ------------------

parse_configure() {
  APP_ID="" INSTALLATION_ID="" AUTHORITY_ISSUE="" WATCH_ISSUE=""
  REPORTER_LOGIN="" OWNER_LOGIN="" REPORTING="" DIAGNOSIS=""
  local seen=" "
  while (( $# )); do
    case "$1" in
      --app-id|--installation-id|--authority-issue|--watch-issue|--reporter-login|--owner-login|--reporting|--diagnosis) ;;
      --*) [[ "$1" =~ ^--[a-z-]{1,32}$ ]] && fail "unknown option for --configure: $1" 64
           fail "unknown option for --configure" 64 ;;
      *) fail "unexpected argument for --configure (values follow their option)" 64 ;;
    esac
    (( $# >= 2 )) || fail "$1 needs a value" 64
    [[ "$seen" != *" $1 "* ]] || fail "$1 given twice" 64
    seen+="$1 "
    case "$1" in
      --app-id) APP_ID="$2" ;;
      --installation-id) INSTALLATION_ID="$2" ;;
      --authority-issue) AUTHORITY_ISSUE="$2" ;;
      --watch-issue) WATCH_ISSUE="$2" ;;
      --reporter-login) REPORTER_LOGIN="$2" ;;
      --owner-login) OWNER_LOGIN="$2" ;;
      --reporting) REPORTING="$2" ;;
      --diagnosis) DIAGNOSIS="$2" ;;
    esac
    shift 2
  done
  [[ "$APP_ID" =~ $NUMBER_RE ]] || fail "--app-id must be a positive number" 64
  [[ "$INSTALLATION_ID" =~ $NUMBER_RE ]] || fail "--installation-id must be a positive number" 64
  [[ "$AUTHORITY_ISSUE" =~ $NUMBER_RE ]] || fail "--authority-issue must be a positive number" 64
  [[ -z "$WATCH_ISSUE" || "$WATCH_ISSUE" =~ $NUMBER_RE ]] || fail "--watch-issue must be a positive number" 64
  [[ "$WATCH_ISSUE" != "$AUTHORITY_ISSUE" ]] || fail "--watch-issue must differ from --authority-issue" 64
  [[ "$REPORTER_LOGIN" =~ $LOGIN_RE && "$REPORTER_LOGIN" == *"[bot]" ]] \
    || fail "--reporter-login must be the App's login <slug>[bot]" 64
  [[ "$OWNER_LOGIN" =~ $LOGIN_RE && "$OWNER_LOGIN" != *"[bot]" ]] \
    || fail "--owner-login must be the owner's own GitHub login (a person, not an App)" 64
  [[ "${REPORTER_LOGIN,,}" != "${OWNER_LOGIN,,}" ]] || fail "--reporter-login must not be the owner" 64
  case "$REPORTING" in off|dry-run|on) ;; *) fail "--reporting must be off, dry-run or on" 64 ;; esac
  case "$DIAGNOSIS" in off|on) ;; *) fail "--diagnosis must be off or on" 64 ;; esac
}

# Rewrites only the TIM_CHECKUP_* lines of $1, atomically; every other line, the mode and the owner stay.
write_env_file() {
  local file="$1"
  [[ -f "$file" && ! -L "$file" ]] || fail "$file is missing or a symlink; run ops/debian/bootstrap.sh first" 2
  TMP_FILE="$(mktemp "$(dirname "$file")/.tim.env.XXXXXX")"
  { grep -v -E '^[[:space:]]*TIM_CHECKUP_[A-Za-z0-9_]*[[:space:]]*=' "$file" || [[ $? -eq 1 ]]; } >"$TMP_FILE"
  {
    printf 'TIM_CHECKUP_REPORTING=%s\n' "$REPORTING"
    printf 'TIM_CHECKUP_DIAGNOSIS=%s\n' "$DIAGNOSIS"
    printf 'TIM_CHECKUP_APP_ID=%s\n' "$APP_ID"
    printf 'TIM_CHECKUP_INSTALLATION_ID=%s\n' "$INSTALLATION_ID"
    printf 'TIM_CHECKUP_AUTHORITY_ISSUE=%s\n' "$AUTHORITY_ISSUE"
    if [[ -n "$WATCH_ISSUE" ]]; then printf 'TIM_CHECKUP_WATCH_ISSUE=%s\n' "$WATCH_ISSUE"; fi
    printf 'TIM_CHECKUP_REPORTER_LOGIN=%s\n' "$REPORTER_LOGIN"
    printf 'TIM_CHECKUP_OWNER_LOGIN=%s\n' "$OWNER_LOGIN"
  } >>"$TMP_FILE"
  chown --reference="$file" "$TMP_FILE"
  chmod --reference="$file" "$TMP_FILE"
  mv -f -- "$TMP_FILE" "$file"
  TMP_FILE=""
}

configure() {
  step "TIM_CHECKUP_* lines in $ENV_FILE"
  write_env_file "$ENV_FILE"
  grep -E '^TIM_CHECKUP_' "$ENV_FILE"
  if [[ "$REPORTING" != off && ! -s "$KEY" ]]; then
    echo "warning: $KEY is empty; the checkup reports key_missing until you run --app-key" >&2
  fi
  if [[ "$REPORTING" == on ]]; then
    echo "reporting=on writes to the production repository: only after 24 h dry-run and the owner's explicit yes."
  fi
  if [[ "$DIAGNOSIS" == on ]]; then
    echo "note: diagnosis=on has no effect yet; the Qwen diagnosis comes with a later release."
  fi
  echo "Takes effect at the next run (at most 15 min). To run now: systemctl start tim-checkup.service"
}

# --- --app-key -----------------------------------------------------------------------------------------------

store_app_key() {
  [[ -d "$ETC" && ! -L "$ETC" ]] || fail "$ETC missing; run ops/debian/bootstrap.sh first" 2
  [[ ! -L "$KEY" ]] || fail "$KEY is a symlink; refusing" 2
  command -v openssl >/dev/null || fail "openssl missing (apt-get install openssl)" 2
  umask 077
  TMP_FILE="$(mktemp "$ETC/.github-app.pem.XXXXXX")"
  echo "Paste the private key of the GitHub App (PEM), then press Ctrl-D on an empty line. The input is not shown." >&2
  if [[ -t 0 ]]; then
    TTY_STATE="$(stty -g)"
    stty -echo
  fi
  cat >"$TMP_FILE"
  if [[ -n "$TTY_STATE" ]]; then
    stty "$TTY_STATE"
    TTY_STATE=""
  fi
  [[ -s "$TMP_FILE" ]] || fail "no key received, nothing changed" 65
  # -passin pass: makes an encrypted key fail instead of prompting; nothing is written to stdout.
  openssl pkey -in "$TMP_FILE" -noout -passin pass: 2>/dev/null || fail "not a readable private key, nothing changed" 65
  chown root:root "$TMP_FILE"
  chmod 0600 "$TMP_FILE"
  mv -f -- "$TMP_FILE" "$KEY"
  TMP_FILE=""
  echo "Stored $KEY (root:root 0600); the next run reads it. Delete the downloaded .pem file on the Mac now."
}

# --- install (no argument) -------------------------------------------------------------------------------------

install_checkup() {
  [[ -f "$ROOT/main.py" && -d "$ROOT/ops/systemd" ]] || fail "TIM checkout missing at $ROOT" 2
  id tim >/dev/null 2>&1 || fail "user tim missing; run ops/debian/bootstrap.sh first" 2
  [[ -d "$ROOT/data" && -f "$ENV_FILE" ]] || fail "$ROOT/data or $ENV_FILE missing; run ops/debian/bootstrap.sh first" 2
  [[ -f "$ROOT/scripts/tim_checkup.py" ]] || fail "$ROOT/scripts/tim_checkup.py missing; deploy the code first" 2

  step "preflight: $ROOT belongs to root"
  # The checkup holds the App key while it runs code from $ROOT: only root may change that code.
  local loose
  loose="$(find "$ROOT" -xdev \( -path "$ROOT/data" -o -path "$ROOT/artifacts" \) -prune \
    -o ! -type l \( ! -user root -o -perm /022 \) -print -quit)"
  [[ -z "$loose" ]] || fail "$loose is not owned by root or is group/world-writable; fix $ROOT first (docs/TIM_CHECKUP.md)" 7

  step "incident data directory"
  [[ ! -L "$INCIDENTS" ]] || fail "$INCIDENTS is a symlink; refusing" 2
  install -d -o tim -g tim -m 0700 "$INCIDENTS"

  step "GitHub App key placeholder"
  # LoadCredential= fails the unit when the file is missing; with an empty file the checkup reports key_missing.
  [[ ! -L "$KEY" ]] || fail "$KEY is a symlink; refusing" 2
  [[ -e "$KEY" ]] || install -o root -g root -m 0600 /dev/null "$KEY"
  chown root:root "$KEY"
  chmod 0600 "$KEY"

  step "systemd units"
  local unit
  local installed=()
  for unit in "${UNITS[@]}"; do
    if [[ -f "$ROOT/ops/systemd/$unit" ]]; then
      install -o root -g root -m 0644 "$ROOT/ops/systemd/$unit" "$UNIT_DIR/$unit"
      installed+=("$UNIT_DIR/$unit")
    else
      echo "not in this checkout, skipped: $unit" >&2
    fi
  done
  (( ${#installed[@]} )) || fail "no checkup units in $ROOT/ops/systemd; deploy the code first" 2
  systemd-analyze verify "${installed[@]}"
  systemctl daemon-reload
  if [[ -f "$UNIT_DIR/tim-checkup.service" && -f "$UNIT_DIR/tim-checkup.timer" ]]; then
    systemctl enable --now tim-checkup.timer
    systemctl list-timers tim-checkup.timer --no-pager
  else
    echo "tim-checkup.timer not enabled: service or timer missing" >&2
  fi

  step "authority issue body"
  echo "Open an issue with your own GitHub account (not the App), label governance, with exactly this body:"
  echo
  (cd "$ROOT" && runuser -u tim -- "$ROOT/.venv/bin/python" -m src.task_governance.create_authority body \
    --registry "$INCIDENTS/registry.sqlite" --repo "$REPOSITORY")

  step "next steps (docs/TIM_CHECKUP.md)"
  grep -E '^TIM_CHECKUP_REPORTING=' "$ENV_FILE" || echo "TIM_CHECKUP_REPORTING is not set: reporting is off"
  cat <<'EOF'
  1. bash /opt/tim/ops/debian/install_checkup.sh --app-key
  2. bash /opt/tim/ops/debian/install_checkup.sh --configure ... --reporting dry-run --diagnosis off
  3. after 24 h dry-run and the owner's explicit yes: the same line with --reporting on
EOF
}

# --- --uninstall -----------------------------------------------------------------------------------------------

uninstall_checkup() {
  step "stop and remove the checkup units"
  # A running check is stopped; its outbox entries stay pending on disk.
  systemctl disable --now tim-checkup.timer 2>/dev/null || true
  systemctl stop tim-checkup.service 2>/dev/null || true
  if systemctl is-active --quiet tim-checkup.timer; then
    fail "tim-checkup.timer is still active; nothing removed" 1
  fi
  local unit
  for unit in "${UNITS[@]}"; do
    rm -f -- "$UNIT_DIR/$unit"
  done
  if [[ -L "$UNIT_DIR/timers.target.wants/tim-checkup.timer" ]]; then
    rm -f -- "$UNIT_DIR/timers.target.wants/tim-checkup.timer"
  fi
  systemctl daemon-reload
  systemctl reset-failed tim-checkup.service tim-checkup.timer 2>/dev/null || true

  step "kept as evidence (nothing deleted)"
  echo "  $INCIDENTS: state, outbox and outbox/done, registry, evidence"
  echo "  $KEY: revoke the key in the GitHub App settings first, then remove the file by hand"
  echo "  TIM_CHECKUP_* lines in $ENV_FILE"
  echo "  issues on GitHub stay as they are; close the authority issue to revoke creation for good"
  echo "Note: bootstrap.sh copies tim-checkup.* again on its next run but never enables them."
}

main() {
  case "${1:-}" in
    "") require_root; install_checkup ;;
    --app-key) (( $# == 1 )) || fail "--app-key takes no value; paste the key when asked" 64
               require_root; store_app_key ;;
    --configure) shift; parse_configure "$@"; require_root; configure ;;
    --uninstall) (( $# == 1 )) || fail "--uninstall takes no value" 64
                 require_root; uninstall_checkup ;;
    -h|--help) usage ;;
    *) usage >&2; exit 64 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
