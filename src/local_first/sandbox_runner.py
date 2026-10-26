"""Run model-written tests inside an OS sandbox without credentials.

Local Qwen (and its helpers) write the code that ``pytest`` then imports and runs. Without a
sandbox that code runs as the worker's macOS user: it could read the dedicated GitHub login,
ask the Keychain for its token, or send data over the network. This module wraps the test
command so the process

* gets a minimal environment (no tokens, a throwaway HOME),
* cannot read credential folders (gh, ssh, Keychain, Codex/Claude logins, cloud CLIs),
* can write only to its own temporary folder, never to the worktree (code there runs later
  outside the sandbox),
* cannot open network connections except to localhost (and not to Ollama),
* cannot start tools that act outside the sandbox (launchctl, open, osascript, security).

On macOS this uses Seatbelt (``/usr/bin/sandbox-exec``), the same mechanism Anthropic's
sandbox-runtime uses, without a Node dependency. On Linux (the worker on tim-core-01) it uses
bubblewrap: a read-only view of the system, empty folders over credentials and TIM's server data,
and a network namespace with only its own loopback, so Ollama and PostgreSQL are out of reach.
``TIM_TEST_SANDBOX`` selects the mode:
``required`` (block when no sandbox is available), ``auto`` (default: sandbox when available,
otherwise run with the minimal environment only) or ``off``.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
BWRAP = "/usr/bin/bwrap"
MODES = {"required", "auto", "off"}

# Read access to these locations below HOME is denied. Paths are relative to the real HOME.
CREDENTIAL_DIRS = (
    ".config/gh-tim-mac-worker", ".config/gh", ".ssh", ".gnupg", ".aws", ".azure",
    ".config/gcloud", ".kube", ".docker", ".codex", ".claude", ".config/claude",
    ".local/share/claude", "Library/Keychains", "Library/Cookies", ".password-store",
)
CREDENTIAL_FILES = (".netrc", ".git-credentials", ".claude.json", ".npmrc", ".pypirc",
                    ".zsh_history", ".bash_history", ".config/git/credentials")
CREDENTIAL_DIRS_EXTRA = ("Library/LaunchAgents", ".zsh_sessions")
# Programs that hand work to launchd, LaunchServices or the Keychain, outside the sandbox.
ESCAPE_BINARIES = ("/bin/launchctl", "/usr/bin/open", "/usr/bin/osascript", "/usr/bin/security",
                   "/usr/bin/sandbox-exec")
BLOCKED_LOCAL_PORTS = (11434,)  # Ollama: tests must not pull, delete or prompt models
# Mach services that hand out Keychain secrets.
KEYCHAIN_SERVICES = ("com.apple.SecurityServer", "com.apple.securityd.xpc", "com.apple.security.agent")

# Linux server paths that hold TIM's secrets, live data or the production database; the CI runner
# unit hides the same set. /run goes too: a read-only mount still lets a process connect() to the
# Unix sockets there (D-Bus, journald, userdb, PostgreSQL). Missing paths are skipped.
SERVER_HIDDEN_DIRS = ("/run", "/etc/tim", "/opt/tim", "/srv/tim", "/srv/ci", "/var/lib/tim", "/var/lib/tim-agent",
                      "/var/backups", "/srv/postgresql", "/var/lib/postgresql", "/etc/postgresql",
                      "/run/postgresql", "/root")
# Kinds whose test runs count as sandboxed for TIM_TEST_SANDBOX=required.
ENFORCING_KINDS = frozenset({"seatbelt", "bubblewrap"})

PASSTHROUGH_ENV = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "USER", "LOGNAME", "SHELL", "TERM")


class SandboxUnavailable(RuntimeError):
    """``TIM_TEST_SANDBOX=required`` but this platform has no supported sandbox."""


@dataclass(frozen=True, slots=True)
class SandboxPlan:
    argv: list[str]
    env: dict[str, str]
    mode: str
    kind: str  # "seatbelt", "bubblewrap" or "none"
    scratch: Path
    denied_read: list[str] = field(default_factory=list)

    def cleanup(self) -> None:
        shutil.rmtree(self.scratch, ignore_errors=True)


def configured_mode() -> str:
    mode = os.getenv("TIM_TEST_SANDBOX", "auto").strip().lower() or "auto"
    return mode if mode in MODES else "required"  # unknown values fail closed


def _sb_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _real(path: Path) -> str:
    # Seatbelt matches resolved paths (/var -> /private/var on macOS).
    return os.path.realpath(path)


def seatbelt_profile(repo_root: Path, scratch: Path, home: Path) -> tuple[str, list[str]]:
    """Return a Seatbelt profile and the credential paths it hides.

    Later rules override earlier ones, so the broad allow comes first and the denials follow.
    """
    repo = _real(repo_root)
    denied = [_real(home / item) for item in CREDENTIAL_DIRS + CREDENTIAL_DIRS_EXTRA]
    denied_files = [_real(home / item) for item in CREDENTIAL_FILES]
    lines = [
        "(version 1)",
        "(allow default)",
        ";; credentials stay unreadable",
        "(deny file-read* " + " ".join(f"(subpath {_sb_string(p)})" for p in denied)
        + " " + " ".join(f"(literal {_sb_string(p)})" for p in denied_files) + ")",
        "(deny mach-lookup " + " ".join(f"(global-name {_sb_string(s)})" for s in KEYCHAIN_SERVICES) + ")",
        "(deny process-exec " + " ".join(f"(literal {_sb_string(b)})" for b in ESCAPE_BINARIES) + ")",
        ";; writes only to scratch space and devices; the worktree stays read-only because the",
        ";; worker later runs code from it outside the sandbox",
        "(deny file-write*)",
        "(allow file-write* (subpath {}) (literal \"/dev/null\") (literal \"/dev/tty\")"
        " (regex #\"^/dev/fd/\"))".format(_sb_string(_real(scratch))),
        "(deny file-write* (subpath {}))".format(_sb_string(repo)),
        ";; no network except loopback, and not Ollama",
        "(deny network-outbound)",
        "(allow network-outbound (remote ip \"localhost:*\"))",
        *[f"(deny network-outbound (remote ip \"localhost:{port}\"))" for port in BLOCKED_LOCAL_PORTS],
        "(deny network-bind)",
        "(allow network-bind (local ip \"localhost:*\"))",
    ]
    return "\n".join(lines) + "\n", denied + denied_files


def bubblewrap_argv(argv: list[str], repo_root: Path, scratch: Path,
                    home: Path) -> tuple[list[str], list[str]]:
    """Return the bwrap command line and the paths it hides.

    Mounts apply in order, so the read-only root comes first, the hiding mounts follow and the
    repository and the writable scratch folder are bound last.
    """
    hidden: list[str] = []
    mounts: list[str] = []

    def covered(path: str) -> bool:
        return any(path == item or path.startswith(item.rstrip("/") + "/") for item in hidden)

    dirs = {_real(Path(item)) for item in SERVER_HIDDEN_DIRS} \
        | {_real(home / item) for item in CREDENTIAL_DIRS + CREDENTIAL_DIRS_EXTRA}
    for path in sorted(dirs, key=len):  # parents first, so nested paths are already hidden
        if os.path.isdir(path) and not covered(path):
            hidden.append(path)
            mounts += ["--tmpfs", path]
    for path in sorted({_real(home / item) for item in CREDENTIAL_FILES}):
        if os.path.isfile(path) and not covered(path):
            hidden.append(path)
            mounts += ["--ro-bind", "/dev/null", path]
    repo, scratch_path = _real(repo_root), _real(scratch)
    # The Python that runs the tests, read-only again in case a hidden folder holds it (the CI venv lies
    # below /srv/ci). Only an absolute interpreter path counts; a bare name is found on PATH as usual.
    runtime = {_real(Path(sys.prefix)), _real(Path(sys.base_prefix))}
    if argv and os.path.isabs(argv[0]):
        interpreter = Path(argv[0])
        runtime.add(_real(interpreter.parent.parent if interpreter.parent.name == "bin" else interpreter.parent))
    rebinds: list[str] = []
    for path in sorted(runtime):
        if os.path.isdir(path) and covered(path):
            rebinds += ["--ro-bind", path, path]
    command = [
        BWRAP, "--die-with-parent", "--new-session",
        # Own user, PID, IPC, UTS, cgroup and network namespaces: only a private loopback remains.
        "--unshare-all",
        "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        *mounts,
        # The repository again, read-only, in case it lies below /tmp or a hidden folder.
        *rebinds,
        "--ro-bind", repo, repo,
        "--bind", scratch_path, scratch_path,
        "--chdir", repo,
        "--", *argv,
    ]
    return command, hidden


@functools.cache
def bubblewrap_usable() -> bool:
    """True when bwrap can build this sandbox here.

    It needs unprivileged user namespaces and its own /proc, which a hardened service (RestrictNamespaces,
    ProtectProc) or kernel setting can forbid. Checked once per process with the real mounts.
    """
    scratch = Path(tempfile.mkdtemp(prefix="tim-test-sandbox-probe-"))
    try:
        command, _ = bubblewrap_argv(["/bin/true"], scratch, scratch, Path.home())
        return subprocess.run(command, capture_output=True, timeout=20, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def minimal_env(scratch: Path, repo_root: Path, source: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for test processes: no credentials, throwaway HOME and TMPDIR."""
    source = dict(os.environ if source is None else source)
    env = {key: source[key] for key in PASSTHROUGH_ENV if key in source}
    home = scratch / "home"
    tmp = scratch / "tmp"
    home.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    env.update({
        "HOME": str(home), "TMPDIR": str(tmp), "PYTHONPATH": str(repo_root),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0",
        "TIM_LIVE_TRADING": "0", "TIM_EXECUTION_ENABLED": "0",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "NO_PROXY": "*", "no_proxy": "*",
    })
    env.setdefault("PATH", "/usr/bin:/bin")
    return env


def plan(argv: list[str], repo_root: Path, *, mode: str | None = None,
         platform: str | None = None, home: Path | None = None) -> SandboxPlan:
    """Wrap ``argv`` for sandboxed execution. Callers must call ``cleanup()`` afterwards."""
    mode = configured_mode() if mode is None else mode
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else home
    scratch = Path(tempfile.mkdtemp(prefix="tim-test-sandbox-"))
    env = minimal_env(scratch, repo_root)
    if mode == "off":
        return SandboxPlan(list(argv), env, mode, "none", scratch)
    if platform == "darwin" and os.access(SANDBOX_EXEC, os.X_OK):
        profile, denied = seatbelt_profile(repo_root, scratch, home)
        profile_path = scratch / "test.sb"
        profile_path.write_text(profile, encoding="utf-8")
        return SandboxPlan([SANDBOX_EXEC, "-f", str(profile_path), *argv], env, mode, "seatbelt",
                           scratch, denied)
    if platform.startswith("linux") and os.access(BWRAP, os.X_OK) and bubblewrap_usable():
        command, hidden = bubblewrap_argv(list(argv), repo_root, scratch, home)
        return SandboxPlan(command, env, mode, "bubblewrap", scratch, hidden)
    if mode == "required":
        shutil.rmtree(scratch, ignore_errors=True)
        raise SandboxUnavailable(f"test sandbox required but unavailable on {platform}")
    return SandboxPlan(list(argv), env, mode, "none", scratch)


SELFTEST_PROBE = """
import os, socket, sys
home = os.environ["TIM_SELFTEST_HOME"]
problems = []
for item in ("/etc/tim", "/srv/tim", "/opt/tim", os.path.join(home, ".config/gh-tim-mac-worker"),
             os.path.join(home, ".ssh")):
    try:
        if os.listdir(item):
            problems.append("visible: " + item)
    except OSError:
        pass
for path in ("/run/dbus/system_bus_socket", "/run/systemd/journal/socket",
             "/run/postgresql/.s.PGSQL.5432", "/var/run/postgresql/.s.PGSQL.5432"):
    unix = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        unix.connect(path)
        problems.append("reachable: " + path)
    except OSError:
        pass
    finally:
        unix.close()
for host, port in (("127.0.0.1", 11434), ("127.0.0.2", 11434), ("127.0.0.1", 5432), ("1.1.1.1", 443)):
    try:
        socket.create_connection((host, port), timeout=2).close()
        problems.append(f"reachable: {host}:{port}")
    except OSError:
        pass
try:
    open("tim-sandbox-selftest", "w").close()
    problems.append("worktree writable")
except OSError:
    pass
print("\\n".join(problems) or "OK")
sys.exit(1 if problems else 0)
"""


def selftest(repo_root: Path) -> int:
    """Run a probe in the required sandbox and print what it could reach; 0 means sealed."""
    try:
        sandbox = plan([sys.executable, "-c", SELFTEST_PROBE], repo_root, mode="required")
    except SandboxUnavailable as exc:
        print(f"TEST_SANDBOX_UNAVAILABLE: {exc}")
        return 2
    sandbox.env["TIM_SELFTEST_HOME"] = str(Path.home())
    try:
        done = subprocess.run(sandbox.argv, cwd=repo_root, env=sandbox.env, capture_output=True,
                              text=True, timeout=60, check=False)
    finally:
        sandbox.cleanup()
    print(f"sandbox={sandbox.kind}")
    print((done.stdout + done.stderr).strip()[-2000:])
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(selftest(Path(__file__).resolve().parents[2]))
