#!/usr/bin/env bash
# Install the TIM checkup and incident reporter (OBSERVE only) on the Debian server. Idempotent.
# Run as root after the code is deployed to /opt/tim; the steps and their order are in docs/TIM_CHECKUP.md:
#
#   bash /opt/tim/ops/debian/install_checkup.sh [--ollama-cpus LIST]
#       data dir, key placeholder, tim-agent user and exchange dirs, units, timer, authority body. Ollama is left
#       alone unless --ollama-cpus is given (Qwen step 3): LIST (P0, lscpu -e: two physical cores with their HT
#       siblings, e.g. 2-3,6-7) becomes Ollama's AllowedCPUs and the TIM drop-in moves Ollama to 127.0.0.2.
#   bash /opt/tim/ops/debian/install_checkup.sh --app-key     # paste the GitHub App private key (PEM), end with Ctrl-D
#   bash /opt/tim/ops/debian/install_checkup.sh --configure --app-id N --installation-id N --authority-issue N \
#     [--watch-issue N] --reporter-login SLUG[bot] --owner-login LOGIN --reporting off|dry-run|on --diagnosis off|on
#   bash /opt/tim/ops/debian/install_checkup.sh --uninstall   # timers off, units and drop-ins removed; data, key,
#                                                             # tim-agent and /var/lib/tim-agent stay as evidence
#
# Reporting stays off until --configure sets it. The key is never printed and never passed as an argument.
# The Qwen diagnosis (tim-qwen-diagnose.timer, tim-checkup.path) is enabled only while TIM_CHECKUP_DIAGNOSIS=on.
# bootstrap.sh copies tim-checkup.* and tim-qwen-diagnose.* by glob but never enables them; only this script does.
# The checkup never repairs, restarts TIM, fills gaps or empties queues. The only restart here is
# "systemctl try-restart ollama.service", and only when a TIM drop-in of Ollama was added, changed or removed.
# The drop-in is only touched on the Qwen path (--ollama-cpus, or a re-install with the diagnosis on and AllowedCPUs
# already set) and never while the old Qwen worker still runs: everything else keeps Ollama on 127.0.0.1.
set -euo pipefail
export LC_ALL=C   # plain ASCII ranges in the value checks below

ROOT=/opt/tim
ETC=/etc/tim
ENV_FILE="$ETC/tim.env"
KEY="$ETC/github-app.pem"
INCIDENTS="$ROOT/data/incidents"
UNIT_DIR=/etc/systemd/system
UNITS=(tim-checkup.service tim-checkup.timer tim-checkup.path tim-qwen-diagnose.service tim-qwen-diagnose.timer)
DIAGNOSIS_UNITS=(tim-qwen-diagnose.timer tim-checkup.path)   # enabled only with TIM_CHECKUP_DIAGNOSIS=on
AGENT=tim-agent
AGENT_HOME=/var/lib/tim-agent
DROPIN_DIR="$UNIT_DIR/ollama.service.d"
DROPINS=(tim-limits.conf tim-cpus.conf)   # tim-cpus.conf only from --ollama-cpus, never guessed
ATTIC=/root/attic
REPOSITORY=TIM-Intelegence-market/tim-ai-platform
NUMBER_RE='^[1-9][0-9]{0,11}$'
LOGIN_RE='^[A-Za-z0-9][A-Za-z0-9-]{0,38}(\[bot\])?$'   # WORKER_LOGIN in scripts/github_issue_pipeline.py
CPU_LIST_RE='^(0|[1-9][0-9]{0,3})(-(0|[1-9][0-9]{0,3}))?(,(0|[1-9][0-9]{0,3})(-(0|[1-9][0-9]{0,3}))?){0,31}$'

TMP_FILE=""
TTY_STATE=""
OLLAMA_CPUS=""
OLLAMA_CHANGED=0
MISSING=()
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
usage: install_checkup.sh [--ollama-cpus LIST]
                                          install units, enable the timer, print the authority issue body;
                                          only with LIST (like 2-3,6-7): Ollama drop-in and AllowedCPUs
       install_checkup.sh --app-key       store the GitHub App private key (pasted, not shown)
       install_checkup.sh --configure --app-id N --installation-id N --authority-issue N [--watch-issue N]
                          --reporter-login SLUG[bot] --owner-login LOGIN --reporting off|dry-run|on --diagnosis off|on
       install_checkup.sh --uninstall     disable the timers, remove units and drop-ins, keep data, key and tim-agent
EOF
}

# --- --ollama-cpus and TIM_CHECKUP_DIAGNOSIS (no root needed, testable) --------------------------------------

# valid_cpu_list LIST ONLINE: a plain list like 2-3,6-7 of distinct CPUs below ONLINE that covers at most half of
# them, so Ollama can never take every core from tim-runtime and PostgreSQL. No value is ever guessed.
valid_cpu_list() {
  local list="$1" online="$2" part lo hi cpu count=0 seen=" "
  [[ "$list" =~ $CPU_LIST_RE && "$online" =~ ^[1-9][0-9]{0,4}$ ]] || return 1
  for part in ${list//,/ }; do
    lo="${part%-*}"
    hi="${part#*-}"
    (( lo <= hi && hi < online )) || return 1
    for (( cpu = lo; cpu <= hi; cpu++ )); do
      [[ "$seen" != *" $cpu "* ]] || return 1
      seen+="$cpu "
      count=$(( count + 1 ))
    done
  done
  (( count >= 1 && 2 * count <= online ))
}

online_cpus() { getconf _NPROCESSORS_ONLN 2>/dev/null || echo 0; }

parse_install() {
  OLLAMA_CPUS=""
  (( $# )) || return 0
  [[ "$1" == --ollama-cpus ]] || fail "unknown option for install" 64
  (( $# == 2 )) || fail "--ollama-cpus needs exactly one value, e.g. 2-3,6-7" 64
  valid_cpu_list "$2" "$(online_cpus)" \
    || fail "--ollama-cpus must list online CPUs like 2-3,6-7 (from lscpu -e), at most half of them" 64
  OLLAMA_CPUS="$2"
}

# Only exactly "TIM_CHECKUP_DIAGNOSIS=on" as the last such line of $1 (the one systemd would use) counts as on.
diagnosis_on() {
  local file="$1" last
  [[ -f "$file" ]] || return 1
  last="$({ grep -E '^[[:space:]]*TIM_CHECKUP_DIAGNOSIS[[:space:]]*=' "$file" || true; } | tail -n 1)"
  [[ "${last//[[:space:]]/}" == "TIM_CHECKUP_DIAGNOSIS=on" ]]
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
  if [[ "$DIAGNOSIS" == on ]]; then
    # Refuse before the env file changes: "on" with disabled units would only produce UNIT incidents.
    diagnosis_missing
    if (( ${#MISSING[@]} )); then
      echo "--diagnosis on refused, nothing changed; missing: ${MISSING[*]}" >&2
      fail "Run install_checkup.sh --ollama-cpus LIST first (docs/TIM_CHECKUP.md, Qwen), or use --diagnosis off." 2
    fi
  fi
  step "TIM_CHECKUP_* lines in $ENV_FILE"
  write_env_file "$ENV_FILE"
  grep -E '^TIM_CHECKUP_' "$ENV_FILE"
  if [[ "$REPORTING" != off && ! -s "$KEY" ]]; then
    echo "warning: $KEY is empty; the checkup reports key_missing until you run --app-key" >&2
  fi
  if [[ "$REPORTING" == on ]]; then
    echo "reporting=on writes to the production repository: only after 24 h dry-run and the owner's explicit yes."
  fi
  apply_diagnosis
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

# --- install (no argument or --ollama-cpus LIST) -----------------------------------------------------------------

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

  install_agent_user
  install_agent_dirs

  step "GitHub App key placeholder"
  # LoadCredential= fails the unit when the file is missing; with an empty file the checkup reports key_missing.
  [[ ! -L "$KEY" ]] || fail "$KEY is a symlink; refusing" 2
  [[ -e "$KEY" ]] || install -o root -g root -m 0600 /dev/null "$KEY"
  chown root:root "$KEY"
  chmod 0600 "$KEY"

  install_ollama_dropins

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
  if (( OLLAMA_CHANGED )); then
    step "Ollama: drop-in changed, try-restart"
    restart_ollama
    show_ollama
  fi
  if [[ -f "$UNIT_DIR/tim-checkup.service" && -f "$UNIT_DIR/tim-checkup.timer" ]]; then
    systemctl enable --now tim-checkup.timer
    systemctl list-timers tim-checkup.timer --no-pager
  else
    echo "tim-checkup.timer not enabled: service or timer missing" >&2
  fi
  apply_diagnosis

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
  4. Qwen (P6, after the P2 values are merged into config/tim_checkup.json): this script again with
     --ollama-cpus LIST, then the --configure line with --diagnosis on
EOF
}

# --- PR-2: tim-agent, exchange directories, Ollama drop-in, diagnosis switch -----------------------------------

install_agent_user() {
  step "system user $AGENT (no group tim, no systemd-journal)"
  if ! id "$AGENT" >/dev/null 2>&1; then
    if getent group "$AGENT" >/dev/null; then
      useradd --system --gid "$AGENT" --no-create-home --home-dir "$AGENT_HOME" --shell /usr/sbin/nologin "$AGENT"
    else
      useradd --system --user-group --no-create-home --home-dir "$AGENT_HOME" --shell /usr/sbin/nologin "$AGENT"
    fi
  fi
  # The agent holds no secret and must not read the journal or anything of group tim: its only group is its own.
  [[ "$(id -nG "$AGENT")" == "$AGENT" ]] \
    || fail "$AGENT must be in group $AGENT only (not tim, systemd-journal, adm); fix with gpasswd -d $AGENT GROUP" 7
  id "$AGENT"
}

check_owner_mode() {
  [[ "$(stat -c '%U:%G %a' -- "$1")" == "$2" ]] || fail "$1 is not $2 after install; nothing enabled" 7
}

install_agent_dirs() {
  step "exchange directories under $AGENT_HOME"
  local dir
  for dir in "$AGENT_HOME" "$AGENT_HOME/requests" "$AGENT_HOME/results" "$AGENT_HOME/log"; do
    [[ ! -L "$dir" ]] || fail "$dir is a symlink; refusing" 2
  done
  # requests: written by tim (checkup), read by tim-agent; results: written by tim-agent, read by tim.
  # setgid keeps the reading side's group on every new file; files are 0640, nobody else reads them.
  install -d -o root -g root -m 0755 "$AGENT_HOME"
  install -d -o tim -g "$AGENT" -m 2750 "$AGENT_HOME/requests"
  install -d -o "$AGENT" -g tim -m 2750 "$AGENT_HOME/results"
  install -d -o "$AGENT" -g "$AGENT" -m 0700 "$AGENT_HOME/log"
  check_owner_mode "$AGENT_HOME" "root:root 755"
  check_owner_mode "$AGENT_HOME/requests" "tim:$AGENT 2750"
  check_owner_mode "$AGENT_HOME/results" "$AGENT:tim 2750"
  check_owner_mode "$AGENT_HOME/log" "$AGENT:$AGENT 700"
  stat -c '%U:%G %a %n' -- "$AGENT_HOME" "$AGENT_HOME/requests" "$AGENT_HOME/results" "$AGENT_HOME/log"
}

# The only restart in this script: Ollama, and only after a TIM drop-in was added, changed or removed.
restart_ollama() {
  systemctl try-restart ollama.service \
    || echo "warning: ollama.service did not restart cleanly; check journalctl -u ollama" >&2
}

show_ollama() {
  systemctl show ollama.service -p AllowedCPUs,CPUQuotaPerSecUSec,MemoryMax,MemorySwapMax,Nice,IPAddressDeny --no-pager \
    || true
  ss -ltn 'sport = :11434' || true
}

# Copies $1 to $DROPIN_DIR/$2 (root:root 0644) only when the content differs (cmp); then sets OLLAMA_CHANGED.
install_dropin() {
  local source="$1" target="$DROPIN_DIR/$2"
  [[ ! -L "$target" ]] || fail "$target is a symlink; refusing" 2
  if cmp -s -- "$source" "$target"; then
    echo "unchanged $target"
    return 0
  fi
  install -o root -g root -m 0644 "$source" "$target"
  OLLAMA_CHANGED=1
  echo "installed $target"
}

# True while the old Qwen worker (design section 6, F.3/F.4) runs: it expects Ollama on 127.0.0.1.
old_worker_running() {
  systemctl is-active --quiet tim-qwen-worker.service 2>/dev/null \
    || pgrep -f 'run_local_qwen|tim-qwen-worker' >/dev/null 2>&1
}

# The drop-in moves Ollama to 127.0.0.2 and cuts it off the network: only on the Qwen path, i.e. an explicit
# --ollama-cpus, or a re-install with TIM_CHECKUP_DIAGNOSIS=on and tim-cpus.conf already in place (keeps it current).
install_ollama_dropins() {
  step "Ollama drop-in: limits, 127.0.0.2 only, no internet"
  local source="$ROOT/ops/systemd/ollama.service.d/tim-limits.conf"
  if [[ -z "$OLLAMA_CPUS" ]] && ! { diagnosis_on "$ENV_FILE" && [[ -f "$DROPIN_DIR/tim-cpus.conf" ]]; }; then
    echo "Ollama drop-in not installed, Ollama not touched (stays on 127.0.0.1)." \
         "Qwen step 3 installs it: install_checkup.sh --ollama-cpus LIST"
    return 0
  fi
  if [[ ! -f "$source" ]]; then
    echo "not in this checkout, skipped: ollama.service.d/tim-limits.conf" >&2
    return 0
  fi
  if ! systemctl cat ollama.service >/dev/null 2>&1; then
    echo "ollama.service not found: drop-in skipped; the Qwen diagnosis cannot be enabled" >&2
    return 0
  fi
  if old_worker_running; then
    [[ -z "$OLLAMA_CPUS" ]] \
      || fail "the old Qwen worker still runs (tim-qwen-worker); stop and archive it first (docs/TIM_CHECKUP.md F.3/F.4)" 2
    echo "Ollama drop-in skipped, Ollama not touched: the old Qwen worker still runs (F.3/F.4)" >&2
    return 0
  fi
  [[ ! -L "$ATTIC" && ! -L "$DROPIN_DIR" ]] || fail "$ATTIC or $DROPIN_DIR is a symlink; refusing" 2
  install -d -o root -g root -m 0700 "$ATTIC"
  if [[ ! -e "$ATTIC/ollama.service.before" ]]; then
    # Only the first time: Ollama before any TIM drop-in, for the way back (docs/TIM_CHECKUP.md).
    systemctl cat ollama.service >"$ATTIC/ollama.service.before"
    { ss -ltn 'sport = :11434' || true; } >"$ATTIC/ollama.listen.before"
    echo "saved $ATTIC/ollama.service.before and $ATTIC/ollama.listen.before"
  fi
  install -d -o root -g root -m 0755 "$DROPIN_DIR"
  install_dropin "$source" tim-limits.conf
  if [[ -n "$OLLAMA_CPUS" ]]; then
    TMP_FILE="$(mktemp)"
    {
      echo "# Written by ops/debian/install_checkup.sh from --ollama-cpus (P0, lscpu -e). Removed by --uninstall."
      echo "[Service]"
      printf 'AllowedCPUs=%s\n' "$OLLAMA_CPUS"
    } >"$TMP_FILE"
    install_dropin "$TMP_FILE" tim-cpus.conf
    rm -f -- "$TMP_FILE"
    TMP_FILE=""
  elif [[ -f "$DROPIN_DIR/tim-cpus.conf" ]]; then
    echo "kept from an earlier install: $(grep -E '^AllowedCPUs=' "$DROPIN_DIR/tim-cpus.conf" || echo tim-cpus.conf)"
  else
    echo "AllowedCPUs not set (no --ollama-cpus): no tim-cpus.conf written, nothing guessed." >&2
    echo "The Qwen diagnosis stays disabled until: install_checkup.sh --ollama-cpus LIST (P0, lscpu -e)." >&2
  fi
}

# Enables tim-qwen-diagnose.timer and tim-checkup.path only with TIM_CHECKUP_DIAGNOSIS=on and everything in place,
# otherwise disables them. Even when enabled, diagnose stays idle ("not calibrated") until config has the P2 values.
# Fills MISSING with what the Qwen diagnosis still needs (empty: it can be enabled).
diagnosis_missing() {
  local unit
  MISSING=()
  for unit in tim-checkup.service tim-qwen-diagnose.service "${DIAGNOSIS_UNITS[@]}"; do
    [[ -f "$UNIT_DIR/$unit" ]] || MISSING+=("$unit")
  done
  [[ -f "$DROPIN_DIR/tim-limits.conf" ]] || MISSING+=("ollama.service.d/tim-limits.conf")
  [[ -f "$DROPIN_DIR/tim-cpus.conf" ]] || MISSING+=("ollama.service.d/tim-cpus.conf (--ollama-cpus)")
  id "$AGENT" >/dev/null 2>&1 || MISSING+=("user $AGENT")
  [[ -d "$AGENT_HOME/requests" && -d "$AGENT_HOME/results" ]] || MISSING+=("$AGENT_HOME/requests and results")
  # The old worker (design section 6, F.3/F.4) expects Ollama on 127.0.0.1 and must be stopped and archived first.
  if old_worker_running; then
    MISSING+=("old Qwen worker stopped (tim-qwen-worker, docs/TIM_CHECKUP.md F.3/F.4)")
  fi
  return 0
}

apply_diagnosis() {
  step "Qwen diagnosis"
  local unit
  if ! diagnosis_on "$ENV_FILE"; then
    for unit in "${DIAGNOSIS_UNITS[@]}"; do
      if [[ -f "$UNIT_DIR/$unit" ]]; then systemctl disable --now "$unit" 2>/dev/null || true; fi
    done
    echo "TIM_CHECKUP_DIAGNOSIS is not on: tim-qwen-diagnose.timer and tim-checkup.path stay disabled."
    return 0
  fi
  diagnosis_missing
  if (( ${#MISSING[@]} )); then
    echo "TIM_CHECKUP_DIAGNOSIS=on, but the Qwen diagnosis is NOT enabled; missing: ${MISSING[*]}" >&2
    echo "Run install_checkup.sh --ollama-cpus LIST first, then this again; until then set --diagnosis off" \
         "(otherwise the checkup reports the two disabled units as a UNIT incident)." >&2
    return 0
  fi
  systemctl enable --now tim-qwen-diagnose.timer tim-checkup.path
  systemctl list-timers tim-qwen-diagnose.timer --no-pager
  echo "Enabled. diagnose stays idle (not calibrated) until the P2 values are merged into config/tim_checkup.json."
}

# --- --uninstall -----------------------------------------------------------------------------------------------

uninstall_checkup() {
  step "stop and remove the checkup and Qwen units"
  # A running check is stopped; its outbox entries stay pending on disk.
  local unit
  for unit in tim-checkup.timer tim-checkup.path tim-qwen-diagnose.timer; do
    systemctl disable --now "$unit" 2>/dev/null || true
  done
  systemctl stop tim-checkup.service tim-qwen-diagnose.service 2>/dev/null || true
  for unit in tim-checkup.timer tim-checkup.path tim-qwen-diagnose.timer; do
    if systemctl is-active --quiet "$unit"; then
      fail "$unit is still active; nothing removed" 1
    fi
  done
  for unit in "${UNITS[@]}"; do
    rm -f -- "$UNIT_DIR/$unit"
  done
  for unit in timers.target.wants/tim-checkup.timer timers.target.wants/tim-qwen-diagnose.timer \
              paths.target.wants/tim-checkup.path; do
    if [[ -L "$UNIT_DIR/$unit" ]]; then
      rm -f -- "$UNIT_DIR/$unit"
    fi
  done

  step "remove the Ollama drop-ins"
  local dropin
  local removed=0
  for dropin in "${DROPINS[@]}"; do
    if [[ -e "$DROPIN_DIR/$dropin" || -L "$DROPIN_DIR/$dropin" ]]; then
      rm -f -- "$DROPIN_DIR/$dropin"
      removed=1
      echo "removed $DROPIN_DIR/$dropin"
    fi
  done
  if [[ -d "$DROPIN_DIR" && ! -L "$DROPIN_DIR" ]]; then rmdir "$DROPIN_DIR" 2>/dev/null || true; fi  # empty only; GNU --ignore-fail-on-non-empty is not portable
  systemctl daemon-reload
  if (( removed )); then
    # Back to the listener and limits from before the drop-in (compare with the saved copy below).
    restart_ollama
  fi
  systemctl reset-failed tim-checkup.service tim-checkup.timer tim-checkup.path tim-qwen-diagnose.service \
    tim-qwen-diagnose.timer 2>/dev/null || true

  step "kept as evidence (nothing deleted)"
  echo "  $INCIDENTS: state, outbox and outbox/done, registry, evidence"
  echo "  $KEY: revoke the key in the GitHub App settings first, then remove the file by hand"
  echo "  TIM_CHECKUP_* lines in $ENV_FILE"
  echo "  user $AGENT and $AGENT_HOME (requests, results, log)"
  echo "  $ATTIC/ollama.service.before; compare: systemctl cat ollama | diff - $ATTIC/ollama.service.before"
  echo "  issues on GitHub stay as they are; close the authority issue to revoke creation for good"
  echo "Note: bootstrap.sh copies tim-checkup.* and tim-qwen-diagnose.* again on its next run but never enables them."
}

main() {
  case "${1:-}" in
    ""|--ollama-cpus) parse_install "$@"; require_root; install_checkup ;;
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
