"""ops/debian/install_checkup.sh: static checks plus the --configure parser, run against a temporary env file.

Nothing here runs as root, touches systemd or reads a real key: the script is sourced and only its parser and env
file writer are called, or it is run with arguments that it rejects before any change. The PR-2 steps (Ollama
drop-ins, diagnosis switch, uninstall) run sourced against temporary directories, with systemctl, ss, id and
install replaced by shell functions that only log.
"""
from __future__ import annotations

import re
import shlex
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops/debian/install_checkup.sh"
TEXT = SCRIPT.read_text(encoding="utf-8")
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="bash is not installed")


def function_body(name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}\n", TEXT, re.MULTILINE | re.DOTALL)
    assert match, f"function {name} not found"
    return match.group(1)


def code_lines(text: str = TEXT) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _gnu_coreutils() -> bool:
    try:
        result = subprocess.run(["chmod", "--version"], capture_output=True, text=True, timeout=10)
    except OSError:
        return False
    return result.returncode == 0 and "GNU" in result.stdout


needs_gnu = pytest.mark.skipif(BASH is None or not _gnu_coreutils(), reason="needs bash and GNU coreutils (Debian)")


# --- static ------------------------------------------------------------------------------------------------------

def test_header_strict_mode_root_check_and_no_tracing() -> None:
    assert TEXT.startswith("#!/usr/bin/env bash\n")
    assert "\nset -euo pipefail\n" in TEXT
    assert 'require_root() { [[ $EUID -eq 0 ]] || fail "run as root" 1; }' in TEXT
    assert not re.search(r"^\s*set -[a-z]*x", TEXT, re.MULTILINE)  # tracing would print values
    assert 'if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then\n  main "$@"\nfi\n' in TEXT


@needs_bash
def test_bash_syntax() -> None:
    result = subprocess.run([BASH, "-n", str(SCRIPT)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_every_mode_needs_root_before_it_changes_anything() -> None:
    main = function_body("main")
    for mode, action in (('""|--ollama-cpus)', "install_checkup"), ("--app-key)", "store_app_key"),
                         ("--configure)", "configure"), ("--uninstall)", "uninstall_checkup")):
        branch = main.split(mode, 1)[1].split(";;", 1)[0]
        assert branch.index("require_root") < re.search(rf"(?<![\w-]){action}\b", branch).start(), mode
    # --ollama-cpus is validated before root and before any change.
    install = main.split('""|--ollama-cpus)', 1)[1].split(";;", 1)[0]
    assert install.index('parse_install "$@"') < install.index("require_root")


def test_units_are_installed_only_when_present_and_enabled_only_by_the_installer() -> None:
    assert ("UNITS=(tim-checkup.service tim-checkup.timer tim-checkup.path tim-qwen-diagnose.service "
            "tim-qwen-diagnose.timer)") in TEXT
    body = function_body("install_checkup")
    assert '[[ -f "$ROOT/ops/systemd/$unit" ]]' in body
    assert 'install -o root -g root -m 0644 "$ROOT/ops/systemd/$unit" "$UNIT_DIR/$unit"' in body
    assert body.index("install_ollama_dropins") < body.index('systemd-analyze verify "${installed[@]}"') \
        < body.index("systemctl daemon-reload") < body.index("restart_ollama") \
        < body.index("systemctl enable --now tim-checkup.timer") < body.index("apply_diagnosis")
    assert sorted(re.findall(r"systemctl enable[^\n]*", TEXT)) == [
        "systemctl enable --now tim-checkup.timer", "systemctl enable --now tim-qwen-diagnose.timer tim-checkup.path"]
    # The Qwen units are enabled only in apply_diagnosis, after the TIM_CHECKUP_DIAGNOSIS check.
    apply = function_body("apply_diagnosis")
    assert apply.index('if ! diagnosis_on "$ENV_FILE"; then') < apply.index("systemctl enable --now tim-qwen")
    # Observe only: the installer never starts or restarts TIM; the one restart is Ollama after a drop-in change.
    actions = [line for line in code_lines() if not line.lstrip().startswith(("echo ", "printf "))]
    restarts = re.findall(r"systemctl (?:re)?start[^\n]*|systemctl try-restart[^\n]*", "\n".join(actions))
    assert restarts == ["systemctl try-restart ollama.service \\"]
    assert "systemctl try-restart ollama.service" in function_body("restart_ollama")
    assert "if (( OLLAMA_CHANGED )); then" in body and "if (( removed )); then" in function_body("uninstall_checkup")
    assert len(re.findall(r"^\s*restart_ollama$", TEXT, re.MULTILINE)) == 2


def test_incident_dir_key_placeholder_and_root_owned_checkout() -> None:
    assert 'INCIDENTS="$ROOT/data/incidents"' in TEXT and "ROOT=/opt/tim" in TEXT
    body = function_body("install_checkup")
    assert 'install -d -o tim -g tim -m 0700 "$INCIDENTS"' in body
    assert 'install -o root -g root -m 0600 /dev/null "$KEY"' in body
    assert 'chown root:root "$KEY"' in body and 'chmod 0600 "$KEY"' in body
    assert 'KEY="$ETC/github-app.pem"' in TEXT and "ETC=/etc/tim" in TEXT
    # /opt/tim must belong to root outside data/ and artifacts/ (the checkup runs that code with the key).
    assert "! -user root -o -perm /022" in body and 'fail "$loose is not owned by root' in body


def test_authority_body_is_printed_as_tim_from_the_checkout() -> None:
    body = function_body("install_checkup")
    assert ('(cd "$ROOT" && runuser -u tim -- "$ROOT/.venv/bin/python" -m src.task_governance.create_authority body \\\n'
            '    --registry "$INCIDENTS/registry.sqlite" --repo "$REPOSITORY")') in body
    assert "REPOSITORY=TIM-Intelegence-market/tim-ai-platform" in TEXT


def test_app_key_is_read_hidden_checked_and_moved_never_printed() -> None:
    body = function_body("store_app_key")
    assert body.index("umask 077") < body.index('mktemp "$ETC/') < body.index("stty -echo")
    assert 'TTY_STATE="$(stty -g)"' in body and 'stty "$TTY_STATE"' in function_body("cleanup")
    assert "trap cleanup EXIT" in TEXT and "trap 'exit 130' INT TERM HUP" in TEXT
    assert 'cat >"$TMP_FILE"' in body
    assert 'openssl pkey -in "$TMP_FILE" -noout' in body
    assert body.index("openssl pkey") < body.index('mv -f -- "$TMP_FILE" "$KEY"')
    code = "\n".join(code_lines())
    # The key file is only ever written, checked with -noout and renamed: never shown, copied out or put in a variable.
    readers = r"\b(cat|head|tail|less|more|base64|xxd|od|strings|tee|cp|grep|sed|awk)\b"
    key_code = "\n".join(code_lines(body))
    for path, lines in (("$KEY", code.splitlines()), ("$TMP_FILE", key_code.splitlines())):
        for line in lines:
            if path in line and re.search(readers, line):
                assert line.strip() == 'cat >"$TMP_FILE"', line
    assert not re.search(r"\$\(\s*(<|cat\b)", code)
    assert not re.search(r"^\s*(IFS=\S*\s+)?read\b", code, re.MULTILINE)
    assert "-text" not in code and "-out " not in code
    # --app-key never takes a value, so the key can never arrive through argv.
    assert '(( $# == 1 )) || fail "--app-key takes no value' in function_body("main")


def test_configure_rewrites_only_checkup_lines_atomically() -> None:
    body = function_body("write_env_file")
    assert "grep -v -E '^[[:space:]]*TIM_CHECKUP_" in body
    assert 'chown --reference="$file" "$TMP_FILE"' in body and 'chmod --reference="$file" "$TMP_FILE"' in body
    assert body.rstrip().endswith('mv -f -- "$TMP_FILE" "$file"\n  TMP_FILE=""'.strip())
    assert 'ENV_FILE="$ETC/tim.env"' in TEXT


def test_uninstall_keeps_evidence_and_covers_the_new_units() -> None:
    body = function_body("uninstall_checkup")
    assert "for unit in tim-checkup.timer tim-checkup.path tim-qwen-diagnose.timer; do" in body
    assert 'systemctl disable --now "$unit"' in body
    assert "systemctl stop tim-checkup.service tim-qwen-diagnose.service" in body
    assert 'rm -f -- "$UNIT_DIR/$unit"' in body and "systemctl daemon-reload" in body
    assert "paths.target.wants/tim-checkup.path" in body and "timers.target.wants/tim-qwen-diagnose.timer" in body
    assert 'for dropin in "${DROPINS[@]}"; do' in body and "DROPINS=(tim-limits.conf tim-cpus.conf)" in TEXT
    assert body.index("systemctl daemon-reload") < body.index("restart_ollama")
    removals = [line.strip() for line in code_lines(TEXT) if re.search(r"\brm\b", line)]
    assert not any("-r" in line.split() or "$INCIDENTS" in line or "$KEY" in line or "$ETC" in line
                   or "$AGENT_HOME" in line or "$ATTIC" in line for line in removals)
    assert not re.search(r"\b(userdel|groupdel|deluser)\b", TEXT)
    assert "$INCIDENTS" in body and "$KEY" in body and "$AGENT_HOME" in body and "$ATTIC" in body  # says what stays


def test_agent_user_has_only_its_own_group() -> None:
    body = function_body("install_agent_user")
    code = "\n".join(code_lines())
    # Never added to tim, systemd-journal or any other group, and the result is asserted.
    assert not re.search(r"\b(usermod|gpasswd|adduser)\b", code.replace("fix with gpasswd -d", ""))
    useradds = re.findall(r"useradd[^\n]*", code)
    assert len(useradds) == 2
    for line in useradds:
        assert "-G" not in line.split() and "--groups" not in line and "--gid tim " not in line, line
        assert "--system" in line and "--shell /usr/sbin/nologin" in line and '--home-dir "$AGENT_HOME"' in line
        assert "--no-create-home" in line
    assert '[[ "$(id -nG "$AGENT")" == "$AGENT" ]]' in body
    assert body.index("useradd") < body.index('id -nG "$AGENT"')
    assert "AGENT=tim-agent" in TEXT and "AGENT_HOME=/var/lib/tim-agent" in TEXT
    install = function_body("install_checkup")
    assert install.index("install_agent_user") < install.index("install_agent_dirs") < install.index("apply_diagnosis")


def test_exchange_dirs_have_exact_owners_and_setgid_modes() -> None:
    body = function_body("install_agent_dirs")
    for line in ('install -d -o root -g root -m 0755 "$AGENT_HOME"',
                 'install -d -o tim -g "$AGENT" -m 2750 "$AGENT_HOME/requests"',
                 'install -d -o "$AGENT" -g tim -m 2750 "$AGENT_HOME/results"',
                 'install -d -o "$AGENT" -g "$AGENT" -m 0700 "$AGENT_HOME/log"',
                 'check_owner_mode "$AGENT_HOME" "root:root 755"',
                 'check_owner_mode "$AGENT_HOME/requests" "tim:$AGENT 2750"',
                 'check_owner_mode "$AGENT_HOME/results" "$AGENT:tim 2750"',
                 'check_owner_mode "$AGENT_HOME/log" "$AGENT:$AGENT 700"'):
        assert line in body, line
    assert body.index('[[ ! -L "$dir" ]]') < body.index("install -d")
    assert "stat -c '%U:%G %a'" in function_body("check_owner_mode")


def test_ollama_dropin_saved_once_compared_and_cpus_never_guessed() -> None:
    body = function_body("install_ollama_dropins")
    assert 'if [[ ! -e "$ATTIC/ollama.service.before" ]]; then' in body
    assert body.index('systemctl cat ollama.service >"$ATTIC/ollama.service.before"') \
        < body.index('install_dropin "$source" tim-limits.conf')
    assert "ss -ltn 'sport = :11434'" in body
    assert 'if cmp -s -- "$source" "$target"; then' in function_body("install_dropin")
    assert "OLLAMA_CHANGED=1" in function_body("install_dropin")
    # tim-cpus.conf only from a validated --ollama-cpus; OLLAMA_CPUS is set nowhere else.
    assert body.index('if [[ -n "$OLLAMA_CPUS" ]]; then') < body.index('install_dropin "$TMP_FILE" tim-cpus.conf')
    assert re.findall(r'OLLAMA_CPUS="[^"]*"', TEXT) == ['OLLAMA_CPUS=""', 'OLLAMA_CPUS=""', 'OLLAMA_CPUS="$2"']
    parse = function_body("parse_install")
    assert parse.index('valid_cpu_list "$2"') < parse.index('OLLAMA_CPUS="$2"')
    limits = (ROOT / "ops/systemd/ollama.service.d/tim-limits.conf").read_text(encoding="utf-8")
    assert "AllowedCPUs" not in "\n".join(code_lines(limits))


def test_env_example_lists_the_same_keys_as_comments_only() -> None:
    example = (ROOT / "ops/systemd/tim.env.example").read_text(encoding="utf-8")
    commented = set(re.findall(r"^# (TIM_CHECKUP_[A-Z_]+)=", example, re.MULTILINE))
    written = set(re.findall(r"printf '(TIM_CHECKUP_[A-Z_]+)=%s", function_body("write_env_file")))
    assert commented == written == {
        "TIM_CHECKUP_REPORTING", "TIM_CHECKUP_DIAGNOSIS", "TIM_CHECKUP_APP_ID", "TIM_CHECKUP_INSTALLATION_ID",
        "TIM_CHECKUP_AUTHORITY_ISSUE", "TIM_CHECKUP_WATCH_ISSUE", "TIM_CHECKUP_REPORTER_LOGIN",
        "TIM_CHECKUP_OWNER_LOGIN",
    }
    assert not re.search(r"^TIM_CHECKUP_", example, re.MULTILINE)


# --- behaviour: rejected before any change -----------------------------------------------------------------------

@needs_bash
@pytest.mark.parametrize("arguments", [
    ["--app-key", "-----BEGIN RSA PRIVATE KEY-----"],
    ["--uninstall", "now"],
    ["--unknown"],
    ["--configure", "--app-id", "x"],
])
def test_bad_arguments_exit_64_and_never_echo_values(arguments: list[str]) -> None:
    result = subprocess.run([BASH, str(SCRIPT), *arguments], capture_output=True, text=True, timeout=30)
    assert result.returncode == 64, result.stderr
    assert "BEGIN" not in result.stdout + result.stderr and "now" not in result.stderr.split()


# --- behaviour: --configure against a temporary env file ---------------------------------------------------------

VALID = ["--app-id", "123456", "--installation-id", "7654321", "--authority-issue", "140",
         "--reporter-login", "tim-reporter[bot]", "--owner-login", "uezeyiraydin-cell",
         "--reporting", "dry-run", "--diagnosis", "off"]

EXISTING = (
    "# Copy to /etc/tim/tim.env (root:tim, 0640).\n"
    "TIM_DATABASE_SECRET_PROVIDER=file\n"
    "TIM_DATABASE_SECRET_FILE=/etc/tim/database-password\n"
    "# TIM_CHECKUP_REPORTING=off\n"
    "TIM_CHECKUP_REPORTING=on\n"
    "  TIM_CHECKUP_WATCH_ISSUE = 9\n"
    "TIM_ENABLE_OLLAMA=false"
)


def run_configure(env_file: Path, *arguments: str) -> subprocess.CompletedProcess:
    # $0 is "bash", so the sourced script does not run main.
    command = 'source "$1"; parse_configure "${@:3}"; write_env_file "$2"'
    return subprocess.run([BASH, "-c", command, "bash", str(SCRIPT), str(env_file), *arguments],
                          capture_output=True, text=True, timeout=30)


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    path = tmp_path / "tim.env"
    path.write_text(EXISTING, encoding="utf-8")
    path.chmod(0o640)
    return path


@needs_gnu
def test_configure_replaces_checkup_lines_and_keeps_everything_else(env_file: Path) -> None:
    result = run_configure(env_file, *VALID)
    assert result.returncode == 0, result.stderr
    assert env_file.read_text(encoding="utf-8").splitlines() == [
        "# Copy to /etc/tim/tim.env (root:tim, 0640).",
        "TIM_DATABASE_SECRET_PROVIDER=file",
        "TIM_DATABASE_SECRET_FILE=/etc/tim/database-password",
        "# TIM_CHECKUP_REPORTING=off",
        "TIM_ENABLE_OLLAMA=false",
        "TIM_CHECKUP_REPORTING=dry-run",
        "TIM_CHECKUP_DIAGNOSIS=off",
        "TIM_CHECKUP_APP_ID=123456",
        "TIM_CHECKUP_INSTALLATION_ID=7654321",
        "TIM_CHECKUP_AUTHORITY_ISSUE=140",
        "TIM_CHECKUP_REPORTER_LOGIN=tim-reporter[bot]",
        "TIM_CHECKUP_OWNER_LOGIN=uezeyiraydin-cell",
    ]
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o640
    assert [p.name for p in env_file.parent.iterdir()] == ["tim.env"]  # no temp file left behind


@needs_gnu
def test_configure_twice_is_stable_and_watch_issue_is_optional(env_file: Path) -> None:
    assert run_configure(env_file, *VALID, "--watch-issue", "141").returncode == 0
    first = env_file.read_text(encoding="utf-8")
    assert "TIM_CHECKUP_WATCH_ISSUE=141\n" in first
    assert run_configure(env_file, *VALID, "--watch-issue", "141").returncode == 0
    assert env_file.read_text(encoding="utf-8") == first
    switched = [*VALID[:-4], "--reporting", "on", "--diagnosis", "off"]
    assert run_configure(env_file, *switched).returncode == 0
    text = env_file.read_text(encoding="utf-8")
    assert re.findall(r"^TIM_CHECKUP_REPORTING=.*$", text, re.MULTILINE) == ["TIM_CHECKUP_REPORTING=on"]
    assert "TIM_CHECKUP_WATCH_ISSUE" not in text


@needs_gnu
@pytest.mark.parametrize("reporting", ["off", "dry-run", "on"])
def test_configured_env_file_is_accepted_by_load_settings(env_file: Path, reporting: str) -> None:
    from src.tim_incident.policy import load_settings

    arguments = [*VALID[:-4], "--reporting", reporting, "--diagnosis", "on", "--watch-issue", "141"]
    assert run_configure(env_file, *arguments).returncode == 0
    environ = dict(line.split("=", 1) for line in env_file.read_text(encoding="utf-8").splitlines()
                   if line and not line.startswith("#"))
    settings = load_settings(environ)
    assert settings.problems == () and settings.requested == settings.reporting == reporting
    assert (settings.app_id, settings.installation_id, settings.authority_issue, settings.watch_issue) == \
        (123456, 7654321, 140, 141)
    assert (settings.reporter_login, settings.owner_login) == ("tim-reporter[bot]", "uezeyiraydin-cell")
    assert settings.diagnosis == "on" and settings.complete


def _replace(option: str, value: str) -> list[str]:
    arguments = list(VALID)
    arguments[arguments.index(option) + 1] = value
    return arguments


@needs_gnu
@pytest.mark.parametrize("arguments", [
    _replace("--app-id", "0"),
    _replace("--app-id", "12a"),
    _replace("--app-id", "0123"),
    _replace("--installation-id", "-5"),
    _replace("--authority-issue", "1 2"),
    _replace("--reporter-login", "tim reporter"),
    _replace("--reporter-login", "tim-reporter[bot];id"),
    _replace("--reporter-login", "-dash"),
    _replace("--reporter-login", "uezeyiraydin-cell"),
    _replace("--reporter-login", "tim-reporter"),
    _replace("--owner-login", "tim-owner[bot]"),
    _replace("--owner-login", "a" * 40),
    _replace("--reporting", "yes"),
    _replace("--reporting", "on\nTIM_DATABASE_SECRET_FILE=/tmp/x"),
    _replace("--diagnosis", "dry-run"),
    [*VALID, "--watch-issue", "140"],
    [*VALID, "--watch-issue", "x"],
    [*VALID, "--reporting", "on"],
    [*VALID, "--token", "ghp_0123456789abcdefghijklmnopqrstuvwxyz"],
    [*VALID, "stray"],
    [*VALID, "--diagnosis"],
    VALID[2:],
])
def test_configure_rejects_bad_values_and_leaves_the_file_alone(env_file: Path, arguments: list[str]) -> None:
    result = run_configure(env_file, *arguments)
    assert result.returncode == 64, result.stderr
    assert env_file.read_text(encoding="utf-8") == EXISTING
    assert "ghp_" not in result.stderr and "/tmp/x" not in result.stderr


@needs_gnu
def test_configure_refuses_a_missing_or_linked_env_file(tmp_path: Path, env_file: Path) -> None:
    assert run_configure(tmp_path / "absent.env", *VALID).returncode == 2
    link = tmp_path / "link.env"
    link.symlink_to(env_file)
    assert run_configure(link, *VALID).returncode == 2
    assert env_file.read_text(encoding="utf-8") == EXISTING


# --- behaviour: --ollama-cpus validation ----------------------------------------------------------------------------

def valid_cpu_list(cpus: str, online: str) -> int:
    command = 'source "$1"; valid_cpu_list "$2" "$3"'
    return subprocess.run([BASH, "-c", command, "bash", str(SCRIPT), cpus, online],
                          capture_output=True, text=True, timeout=30).returncode


@needs_bash
@pytest.mark.parametrize(("cpus", "online"), [("2-3,6-7", "8"), ("2,6", "8"), ("1", "2"), ("4-7", "8"), ("0-1", "4")])
def test_ollama_cpus_accepts_plain_lists_of_at_most_half(cpus: str, online: str) -> None:
    assert valid_cpu_list(cpus, online) == 0


@needs_bash
@pytest.mark.parametrize(("cpus", "online"), [
    ("", "8"), ("0-7", "8"), ("0-4", "8"), ("2-3,6-8", "8"), ("8", "8"), ("3-2", "8"), ("2,2", "8"),
    ("2-3,3", "8"), ("02", "8"), ("2-3,", "8"), (",2", "8"), ("2 3", "8"), ("2-3;id", "8"), ("$(id)", "8"),
    ("2-3\n6-7", "8"), ("-1", "8"), ("a-b", "8"), ("2-3,6-7", "0"), ("2-3,6-7", ""), ("2-3,6-7", "x"),
    ("0-9999", "8"), ("1", "1"),
])
def test_ollama_cpus_rejects_everything_else(cpus: str, online: str) -> None:
    assert valid_cpu_list(cpus, online) != 0


@needs_bash
@pytest.mark.parametrize("arguments", [
    ["--ollama-cpus"], ["--ollama-cpus", "0-99999"], ["--ollama-cpus", "two-three"],
    ["--ollama-cpus", "0", "--uninstall"], ["--ollama-cpus", "0-1023"],
])
def test_install_rejects_bad_ollama_cpus_before_root(arguments: list[str]) -> None:
    result = subprocess.run([BASH, str(SCRIPT), *arguments], capture_output=True, text=True, timeout=30)
    assert result.returncode == 64, result.stderr
    assert "run as root" not in result.stderr and "two-three" not in result.stderr


# --- behaviour: diagnosis switch, Ollama drop-ins and uninstall with stubbed system commands -----------------------

STUBS = r'''
source "$1"
set +e
SANDBOX="$2"
ROOT="$3"
UNIT_DIR="$SANDBOX/units"
DROPIN_DIR="$UNIT_DIR/ollama.service.d"
AGENT_HOME="$SANDBOX/agent"
ENV_FILE="$SANDBOX/tim.env"
ATTIC="$SANDBOX/attic"
CALLS="$SANDBOX/calls.log"
export TMPDIR="$SANDBOX"
systemctl() {
  echo "systemctl $*" >>"$CALLS"
  case "$1" in
    cat) [[ -e "$SANDBOX/no-ollama" ]] && return 1; printf '[Service]\nExecStart=/usr/bin/ollama serve\n' ;;
    is-active) return 1 ;;
  esac
  return 0
}
ss() { echo "LISTEN 0 4096 127.0.0.1:11434"; }
pgrep() { echo "pgrep $*" >>"$CALLS"; [[ -e "$SANDBOX/old-worker" ]]; }
id() { [[ ! -e "$SANDBOX/no-agent" ]]; }
install() {
  local args=()
  while (( $# )); do case "$1" in -o|-g) shift 2 ;; *) args+=("$1"); shift ;; esac; done
  command install "${args[@]}"
}
set -e
shift 3
"$@"
'''


def run_stubbed(sandbox: Path, *call: str) -> subprocess.CompletedProcess:
    return subprocess.run([BASH, "-c", STUBS, "bash", str(SCRIPT), str(sandbox), str(ROOT), *call],
                          capture_output=True, text=True, timeout=60)


def calls(sandbox: Path) -> list[str]:
    log = sandbox / "calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    (tmp_path / "units/ollama.service.d").mkdir(parents=True)
    (tmp_path / "agent/requests").mkdir(parents=True)
    (tmp_path / "agent/results").mkdir()
    for unit in ("tim-checkup.service", "tim-checkup.timer", "tim-checkup.path", "tim-qwen-diagnose.service",
                 "tim-qwen-diagnose.timer"):
        (tmp_path / "units" / unit).write_text("[Unit]\n", encoding="utf-8")
    (tmp_path / "tim.env").write_text("TIM_CHECKUP_DIAGNOSIS=on\n", encoding="utf-8")
    return tmp_path


@needs_bash
@pytest.mark.parametrize(("text", "expected"), [
    ("TIM_CHECKUP_DIAGNOSIS=on\n", True),
    ("  TIM_CHECKUP_DIAGNOSIS = on \n", True),
    ("TIM_CHECKUP_DIAGNOSIS=off\nTIM_CHECKUP_DIAGNOSIS=on\n", True),
    ("TIM_CHECKUP_DIAGNOSIS=on\nTIM_CHECKUP_DIAGNOSIS=off\n", False),
    ("# TIM_CHECKUP_DIAGNOSIS=on\n", False),
    ("TIM_CHECKUP_DIAGNOSIS=onn\n", False),
    ("TIM_CHECKUP_DIAGNOSIS=ON\n", False),
    ("TIM_CHECKUP_DIAGNOSIS_X=on\n", False),
    ("", False),
])
def test_diagnosis_on_reads_only_the_last_exact_line(tmp_path: Path, text: str, expected: bool) -> None:
    env = tmp_path / "tim.env"
    env.write_text(text, encoding="utf-8")
    result = subprocess.run([BASH, "-c", 'source "$1"; diagnosis_on "$2"', "bash", str(SCRIPT), str(env)],
                            capture_output=True, text=True, timeout=30)
    assert (result.returncode == 0) is expected


@needs_bash
def test_apply_diagnosis_enables_only_when_on_and_complete(sandbox: Path) -> None:
    dropins = sandbox / "units/ollama.service.d"
    # on, but no drop-ins: nothing enabled, the reason is said.
    result = run_stubbed(sandbox, "apply_diagnosis")
    assert result.returncode == 0, result.stderr
    assert not any("enable" in line for line in calls(sandbox))
    assert "NOT enabled" in result.stderr and "tim-cpus.conf" in result.stderr and "tim-limits.conf" in result.stderr
    # only the limits drop-in: still not enabled, AllowedCPUs is required.
    (dropins / "tim-limits.conf").write_text("[Service]\n", encoding="utf-8")
    result = run_stubbed(sandbox, "apply_diagnosis")
    assert not any("enable" in line for line in calls(sandbox)) and "--ollama-cpus" in result.stderr
    # everything in place: both enabled.
    (dropins / "tim-cpus.conf").write_text("[Service]\nAllowedCPUs=2-3\n", encoding="utf-8")
    (sandbox / "no-agent").touch()
    result = run_stubbed(sandbox, "apply_diagnosis")
    assert not any("enable" in line for line in calls(sandbox)) and "user tim-agent" in result.stderr
    (sandbox / "no-agent").unlink()
    (sandbox / "old-worker").touch()                  # the old tim-qwen-worker still runs (F.3/F.4 not done)
    result = run_stubbed(sandbox, "apply_diagnosis")
    assert not any("enable" in line for line in calls(sandbox)) and "old Qwen worker" in result.stderr
    (sandbox / "old-worker").unlink()
    assert run_stubbed(sandbox, "apply_diagnosis").returncode == 0
    assert "systemctl enable --now tim-qwen-diagnose.timer tim-checkup.path" in calls(sandbox)
    # off: disabled again.
    (sandbox / "calls.log").unlink()
    (sandbox / "tim.env").write_text("TIM_CHECKUP_DIAGNOSIS=off\n", encoding="utf-8")
    result = run_stubbed(sandbox, "apply_diagnosis")
    assert result.returncode == 0 and "stay disabled" in result.stdout
    assert calls(sandbox) == ["systemctl disable --now tim-qwen-diagnose.timer",
                              "systemctl disable --now tim-checkup.path"]


@needs_bash
def test_ollama_dropins_installed_on_change_only_and_attic_saved_once(sandbox: Path) -> None:
    dropins = sandbox / "units/ollama.service.d"
    source = ROOT / "ops/systemd/ollama.service.d/tim-limits.conf"
    probe = 'install_ollama_dropins; echo "changed=$OLLAMA_CHANGED"'
    # Install without --ollama-cpus (diagnosis on, but no AllowedCPUs yet): Ollama is not touched.
    result = run_stubbed(sandbox, "eval", probe)
    assert result.returncode == 0, result.stderr
    assert "changed=0" in result.stdout and "Ollama not touched" in result.stdout
    assert list(dropins.iterdir()) == [] and not (sandbox / "attic").exists()
    # With --ollama-cpus: limits and tim-cpus.conf, attic saved first.
    result = run_stubbed(sandbox, "eval", f'OLLAMA_CPUS=2-3,6-7; {probe}')
    assert "changed=1" in result.stdout, result.stderr
    assert (dropins / "tim-limits.conf").read_bytes() == source.read_bytes()
    cpus = (dropins / "tim-cpus.conf").read_text(encoding="utf-8")
    assert cpus.splitlines()[1:] == ["[Service]", "AllowedCPUs=2-3,6-7"]
    before = sandbox / "attic/ollama.service.before"
    assert before.read_text(encoding="utf-8").startswith("[Service]")
    assert "127.0.0.1:11434" in (sandbox / "attic/ollama.listen.before").read_text(encoding="utf-8")
    # Second install, unchanged: no restart wanted, attic untouched.
    before.write_text("original\n", encoding="utf-8")
    result = run_stubbed(sandbox, "eval", f'OLLAMA_CPUS=2-3,6-7; {probe}')
    assert "changed=0" in result.stdout and before.read_text(encoding="utf-8") == "original\n"
    # Later install without the option (diagnosis on, AllowedCPUs in place) keeps the earlier value.
    result = run_stubbed(sandbox, "eval", probe)
    assert "changed=0" in result.stdout and "AllowedCPUs=2-3,6-7" in result.stdout
    assert (dropins / "tim-cpus.conf").read_text(encoding="utf-8") == cpus
    # ... and keeps the limits current after a deploy.
    (dropins / "tim-limits.conf").write_text("[Service]\n# old\n", encoding="utf-8")
    result = run_stubbed(sandbox, "eval", probe)
    assert "changed=1" in result.stdout and (dropins / "tim-limits.conf").read_bytes() == source.read_bytes()
    assert not [p for p in sandbox.rglob("*") if p.name.startswith("tmp.")]


@needs_bash
def test_plain_install_or_running_old_worker_never_touches_ollama(sandbox: Path) -> None:
    dropins = sandbox / "units/ollama.service.d"
    probe = 'install_ollama_dropins; if (( OLLAMA_CHANGED )); then restart_ollama; fi; echo "changed=$OLLAMA_CHANGED"'
    # Part-1 step 2: plain install, diagnosis off.
    (sandbox / "tim.env").write_text("TIM_CHECKUP_DIAGNOSIS=off\n", encoding="utf-8")
    result = run_stubbed(sandbox, "eval", probe)
    assert result.returncode == 0 and "changed=0" in result.stdout and "Ollama not touched" in result.stdout
    assert list(dropins.iterdir()) == [] and "systemctl try-restart ollama.service" not in calls(sandbox)
    # The old worker still runs: a re-install skips, an explicit --ollama-cpus refuses (exit 2), nothing changes.
    (sandbox / "tim.env").write_text("TIM_CHECKUP_DIAGNOSIS=on\n", encoding="utf-8")
    (dropins / "tim-cpus.conf").write_text("[Service]\nAllowedCPUs=2-3\n", encoding="utf-8")
    (sandbox / "old-worker").touch()
    result = run_stubbed(sandbox, "eval", probe)
    assert result.returncode == 0 and "changed=0" in result.stdout and "old Qwen worker" in result.stderr
    result = run_stubbed(sandbox, "eval", f'OLLAMA_CPUS=2-3,6-7; {probe}')
    assert result.returncode == 2 and "old Qwen worker" in result.stderr
    assert sorted(p.name for p in dropins.iterdir()) == ["tim-cpus.conf"]
    assert "systemctl try-restart ollama.service" not in calls(sandbox) and not (sandbox / "attic").exists()
    # install_checkup calls the gate before any unit is installed; the restart only follows a change.
    body = function_body("install_checkup")
    assert body.index("install_ollama_dropins") < body.index("if (( OLLAMA_CHANGED )); then")


@needs_gnu
def test_configure_diagnosis_on_refused_before_the_env_file_changes(sandbox: Path) -> None:
    env = sandbox / "tim.env"
    env.write_text("TIM_DATABASE_URL=x\nTIM_CHECKUP_DIAGNOSIS=off\n", encoding="utf-8")
    on = " ".join(shlex.quote(arg) for arg in [*VALID[:VALID.index("--diagnosis")], "--diagnosis", "on"])
    result = run_stubbed(sandbox, "eval", f"parse_configure {on}; configure")
    assert result.returncode == 2 and "refused, nothing changed" in result.stderr and "tim-cpus.conf" in result.stderr
    assert env.read_text(encoding="utf-8") == "TIM_DATABASE_URL=x\nTIM_CHECKUP_DIAGNOSIS=off\n"
    assert not any("enable" in line for line in calls(sandbox))
    dropins = sandbox / "units/ollama.service.d"
    (dropins / "tim-limits.conf").write_text("[Service]\n", encoding="utf-8")
    (dropins / "tim-cpus.conf").write_text("[Service]\nAllowedCPUs=2-3\n", encoding="utf-8")
    result = run_stubbed(sandbox, "eval", f"parse_configure {on}; configure")
    assert result.returncode == 0, result.stderr
    assert "TIM_CHECKUP_DIAGNOSIS=on" in env.read_text(encoding="utf-8")
    assert "systemctl enable --now tim-qwen-diagnose.timer tim-checkup.path" in calls(sandbox)


@needs_bash
def test_ollama_dropins_skipped_without_ollama(sandbox: Path) -> None:
    (sandbox / "no-ollama").touch()
    result = run_stubbed(sandbox, "eval", 'OLLAMA_CPUS=2-3; install_ollama_dropins; echo "changed=$OLLAMA_CHANGED"')
    assert result.returncode == 0 and "changed=0" in result.stdout and "ollama.service not found" in result.stderr
    assert list((sandbox / "units/ollama.service.d").iterdir()) == [] and not (sandbox / "attic").exists()


@needs_bash
def test_uninstall_removes_units_and_dropins_restarts_ollama_and_keeps_data(sandbox: Path) -> None:
    dropins = sandbox / "units/ollama.service.d"
    (dropins / "tim-limits.conf").write_text("[Service]\n", encoding="utf-8")
    (dropins / "tim-cpus.conf").write_text("[Service]\n", encoding="utf-8")
    (dropins / "owner.conf").write_text("[Service]\n", encoding="utf-8")  # not ours: stays
    (sandbox / "units/paths.target.wants").mkdir()
    (sandbox / "units/paths.target.wants/tim-checkup.path").symlink_to(sandbox / "units/tim-checkup.path")
    (sandbox / "agent/results/r.json").write_text("{}", encoding="utf-8")
    result = run_stubbed(sandbox, "uninstall_checkup")
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in (sandbox / "units").iterdir()) == ["ollama.service.d", "paths.target.wants"]
    assert [p.name for p in dropins.iterdir()] == ["owner.conf"]
    assert not list((sandbox / "units/paths.target.wants").iterdir())
    assert (sandbox / "agent/results/r.json").exists() and (sandbox / "tim.env").exists()
    log = calls(sandbox)
    for unit in ("tim-checkup.timer", "tim-checkup.path", "tim-qwen-diagnose.timer"):
        assert f"systemctl disable --now {unit}" in log
    assert log.index("systemctl daemon-reload") < log.index("systemctl try-restart ollama.service")
    assert log.count("systemctl try-restart ollama.service") == 1
    # Second uninstall: no drop-in left, so Ollama is not restarted again; the empty drop-in dir is removed.
    dropins.joinpath("owner.conf").unlink()
    (sandbox / "calls.log").unlink()
    assert run_stubbed(sandbox, "uninstall_checkup").returncode == 0
    assert "systemctl try-restart ollama.service" not in calls(sandbox) and not dropins.exists()
