from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from .config import PROJECT_ROOT, load_config


SECRET_NAME = re.compile(r"(^|[._-])(secret|api[_-]?key|private[_-]?key|wallet)([._-]|$)", re.I)
DEFAULT_EXCLUDES = (
    ".git/**", ".venv/**", ".venv-research/**", "venv/**", "node_modules/**",
    "dist/**", "build/**", "coverage/**", "**/__pycache__/**", ".pytest_cache/**",
    "backups/**", "artifacts/tim_manager/**", "docs/tim_manager/**",
)


def normalize_relative(path: Path, root: Path = PROJECT_ROOT) -> str:
    resolved = path.resolve(strict=False)
    root_resolved = root.resolve()
    try:
        relative = resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"path escapes project root: {path}") from exc
    return relative.as_posix()


def is_sensitive(relative_path: str) -> bool:
    name = Path(relative_path).name
    return name == ".env" or name.startswith(".env.") or bool(SECRET_NAME.search(name))


def is_excluded(relative_path: str, extra: list[str] | tuple[str, ...] = ()) -> bool:
    patterns = DEFAULT_EXCLUDES + tuple(extra)
    return is_sensitive(relative_path) or any(fnmatch.fnmatch(relative_path, pattern) for pattern in patterns)


def assert_write_allowed(path: Path) -> None:
    relative = normalize_relative(path)
    rules = load_config("protected_paths.yaml")
    if any(fnmatch.fnmatch(relative, pattern) for pattern in rules["protected_paths"]):
        raise PermissionError(f"protected TIM V1 path: {relative}")
    if not any(fnmatch.fnmatch(relative, pattern) for pattern in rules["write_allowlist"]):
        raise PermissionError(f"path outside TIM-IM write allowlist: {relative}")


def safe_output_path(relative: str) -> Path:
    path = PROJECT_ROOT / relative
    assert_write_allowed(path)
    return path

