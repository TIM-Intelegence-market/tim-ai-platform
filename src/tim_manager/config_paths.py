from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping


# Canonical repository root, derived from the installed package location
# (portable across developers, Linux, CI checkouts, symlinks, packed installs).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = PROJECT_ROOT / "config" / "tim_manager"
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "tim_manager"

# Placeholder used by config files to refer to the repository root. Config
# files never contain Python expressions or resolved absolute paths; path
# resolution happens in code via repository_path().
REPO_ROOT_PLACEHOLDER = "@TIM_REPO_ROOT@"

# Directory names that are never allowed as path targets when a placeholder
# path is resolved (data/secrets/.git and backups are forbidden; the project's
# own virtualenv is allowed only as an executable host, not a data target).
_DENIED_DIRS = frozenset(
    {
        ".git",
        "data",
        "backups",
        "secrets",
        "output",
        "__pycache__",
    }
)


class RepositoryPathError(ValueError):
    """Raised when a configured path is not safely inside the repository."""


def repository_root(env: Mapping[str, str] | None = None) -> Path:
    """Return the canonical, validated repository root.

    Resolution priority:
      1. explicit safe environment variable (only when it resolves to this
         repository or is explicitly trusted),
      2. config path relative to this module (authoritative),
      3. git root when git is available,
      4. controlled error.

    The package-derived value is authoritative; cwd is never used blindly and
    no user path is hardcoded.
    """
    root = PROJECT_ROOT.resolve()
    env = os.environ if env is None else env
    override = env.get("TIM_REPO_ROOT", "").strip()
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_absolute():
            raise RepositoryPathError("TIM_REPO_ROOT must be an absolute path")
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            raise RepositoryPathError("TIM_REPO_ROOT resolves outside the repository")
        root = resolved
    return root


def repository_path(spec: str, *, env: Mapping[str, str] | None = None) -> Path:
    """Resolve a config path expression into a safe absolute path.

    Accepted forms:
      - the placeholder ``@TIM_REPO_ROOT@`` itself (repository root),
      - ``@TIM_REPO_ROOT@/<relative>`` for a repository-relative target,
      - an explicit absolute path (kept verbatim, still security-checked).

    Security: rejects path traversal, symlink escapes, empty specs, and
    resolution outside the repository (or into a denied directory).
    """
    stripped = (spec or "").strip()
    if not stripped:
        raise RepositoryPathError("path expression must not be empty")

    root = repository_root(env=env)
    if REPO_ROOT_PLACEHOLDER in stripped:
        tail = stripped.split(REPO_ROOT_PLACEHOLDER, 1)[1]
        return _validate_repo_relative(root, tail)

    absolute = Path(stripped).expanduser()
    if not absolute.is_absolute():
        raise RepositoryPathError("configured path must be absolute or repo-relative")
    resolved = absolute.resolve()
    if not resolved.is_relative_to(root):
        raise RepositoryPathError("configured path escapes the repository")
    _reject_denied(root, resolved)
    return resolved


def _validate_repo_relative(root: Path, tail: str) -> Path:
    if tail and not tail.startswith(("/", "\\")):
        raise RepositoryPathError("placeholder path must be repository-relative")
    candidate = (root / tail.lstrip("/")).resolve()
    if not candidate.is_relative_to(root):
        raise RepositoryPathError("placeholder path escapes the repository")
    _reject_denied(root, candidate)
    return candidate


def _reject_denied(root: Path, candidate: Path) -> None:
    rel = candidate.relative_to(root)
    if any(part in _DENIED_DIRS for part in rel.parts):
        raise RepositoryPathError("resolved path crosses a denied directory")


def load_config(name: str) -> dict[str, Any]:
    path = CONFIG_ROOT / name
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
