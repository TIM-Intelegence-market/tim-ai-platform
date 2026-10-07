"""ops/debian/install_checkup.sh: static checks plus the --configure parser, run against a temporary env file.

Nothing here runs as root, touches systemd or reads a real key: the script is sourced and only its parser and env
file writer are called, or it is run with arguments that it rejects before any change.
"""
from __future__ import annotations

import re
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
    for mode, action in (('"")', "install_checkup"), ("--app-key)", "store_app_key"),
                         ("--configure)", "configure"), ("--uninstall)", "uninstall_checkup")):
        branch = main.split(mode, 1)[1].split(";;", 1)[0]
        assert branch.index("require_root") < re.search(rf"(?<![\w-]){action}\b", branch).start(), mode


def test_units_are_installed_only_when_present_and_only_the_checkup_timer_is_enabled() -> None:
    assert "UNITS=(tim-checkup.service tim-checkup.timer)" in TEXT
    body = function_body("install_checkup")
    assert '[[ -f "$ROOT/ops/systemd/$unit" ]]' in body
    assert 'install -o root -g root -m 0644 "$ROOT/ops/systemd/$unit" "$UNIT_DIR/$unit"' in body
    assert body.index('systemd-analyze verify "${installed[@]}"') < body.index("systemctl daemon-reload") \
        < body.index("systemctl enable --now tim-checkup.timer")
    assert re.findall(r"systemctl enable[^\n]*", TEXT) == ["systemctl enable --now tim-checkup.timer"]
    # Observe only: the installer never restarts or starts TIM services (printed hints aside).
    actions = [line for line in code_lines() if not line.lstrip().startswith(("echo ", "printf "))]
    assert not re.search(r"systemctl (re)?start|try-restart|restart ", "\n".join(actions))


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


def test_uninstall_keeps_evidence() -> None:
    body = function_body("uninstall_checkup")
    assert "systemctl disable --now tim-checkup.timer" in body
    assert 'rm -f -- "$UNIT_DIR/$unit"' in body and "systemctl daemon-reload" in body
    removals = [line.strip() for line in code_lines(TEXT) if re.search(r"\brm\b", line)]
    assert not any("-r" in line.split() or "$INCIDENTS" in line or "$KEY" in line or "$ETC" in line for line in removals)
    assert "$INCIDENTS" in body and "$KEY" in body  # it says what stays


def test_pr1_has_no_agent_user_setgid_dirs_or_ollama() -> None:
    code = "\n".join(code_lines()).lower()
    for word in ("tim-agent", "useradd", "usermod", "groupadd", "2750", "ollama", "/var/lib/tim-agent"):
        assert word not in code, word


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
