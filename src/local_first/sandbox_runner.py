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
sandbox-runtime uses, without a Node dependency. ``TIM_TEST_SANDBOX`` selects the mode:
``required`` (block when no sandbox is available), ``auto`` (default: sandbox when available,
otherwise run with the minimal environment only) or ``off``.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
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

PASSTHROUGH_ENV = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "USER", "LOGNAME", "SHELL", "TERM")


class SandboxUnavailable(RuntimeError):
    """``TIM_TEST_SANDBOX=required`` but this platform has no supported sandbox."""


@dataclass(frozen=True, slots=True)
class SandboxPlan:
    argv: list[str]
    env: dict[str, str]
    mode: str
    kind: str  # "seatbelt" or "none"
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
    if mode == "required":
        shutil.rmtree(scratch, ignore_errors=True)
        raise SandboxUnavailable(f"test sandbox required but unavailable on {platform}")
    return SandboxPlan(list(argv), env, mode, "none", scratch)
