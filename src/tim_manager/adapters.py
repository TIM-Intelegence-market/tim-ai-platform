from __future__ import annotations

import fnmatch
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import PROJECT_ROOT
from .security import is_excluded, normalize_relative


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class FilesystemAdapter:
    source: dict[str, Any]
    root: Path = PROJECT_ROOT

    def health_check(self) -> dict[str, Any]:
        missing = [item for item in self.source["roots"] if not (self.root / item).exists()]
        return {"status": "missing" if missing and self.source.get("required") else "reachable", "missing_roots": missing}

    def list_artifacts(self) -> Iterable[Path]:
        seen: set[str] = set()
        includes = self.source.get("include") or ["**/*"]
        excludes = self.source.get("exclude") or []
        for configured_root in self.source.get("roots", []):
            target = self.root / configured_root
            candidates = [target] if target.is_file() else target.rglob("*") if target.exists() else []
            for path in candidates:
                if not path.is_file() or path.is_symlink():
                    continue
                relative = normalize_relative(path, self.root)
                if relative in seen or is_excluded(relative, excludes):
                    continue
                if not any(fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(path.name, pattern) for pattern in includes):
                    continue
                seen.add(relative)
                yield path

    def read_metadata(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "suffix": path.suffix.lower()}

    def read_content(self, path: Path, max_bytes: int) -> bytes:
        with path.open("rb") as handle:
            return handle.read(max_bytes + 1)

    def compute_fingerprint(self, path: Path) -> str:
        return sha256_file(path)

    def get_change_cursor(self) -> None:
        return None


@dataclass
class GitAdapter:
    root: Path = PROJECT_ROOT

    def health_check(self) -> dict[str, Any]:
        metadata = self.metadata()
        return {
            "status": "reachable" if metadata["authoritative_git_repository"] else "not_found",
            "root": metadata["parent_git_context"]["git_root"],
            "limitation": (
                None
                if metadata["authoritative_git_repository"]
                else "No authoritative Git history exists for the untracked TIM project."
            ),
        }

    def metadata(self) -> dict[str, Any]:
        def run(*args: str) -> str:
            result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)
            return result.stdout.strip() if result.returncode == 0 else ""
        parent_commit = run("rev-parse", "HEAD")
        parent_branch = run("rev-parse", "--abbrev-ref", "HEAD")
        parent_root = run("rev-parse", "--show-toplevel")
        project_tracked = bool(run("ls-files", "--", str(self.root)))
        authoritative = bool(parent_root and parent_commit and project_tracked)
        return {
            "repository_status": "versioned" if authoritative else "unversioned",
            "repository_commit": parent_commit if authoritative else None,
            "authoritative_git_repository": authoritative,
            "repository_dirty": None if not authoritative else bool(
                run("status", "--porcelain=v1", "--untracked-files=all", "--", str(self.root))
            ),
            "project_tracked": project_tracked,
            "parent_git_context": {
                "git_root": parent_root or None,
                "branch": parent_branch or None,
                "commit": parent_commit or None,
                "project_path_tracked": project_tracked,
                "context_only": not authoritative,
            },
        }


def structured_metadata(path: Path, content: bytes) -> tuple[str, dict[str, Any], list[str]]:
    suffix = path.suffix.lower()
    errors: list[str] = []
    metadata: dict[str, Any] = {}
    artifact_type = suffix.lstrip(".") or "binary"
    if suffix == ".json":
        try:
            parsed = json.loads(content.decode("utf-8"))
            metadata["structured_keys"] = sorted(parsed.keys()) if isinstance(parsed, dict) else []
            metadata["valid_json"] = True
            if isinstance(parsed, dict) and isinstance(parsed.get("tim_manager_claims"), list):
                metadata["claims"] = parsed["tim_manager_claims"]
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            metadata["valid_json"] = False
            errors.append(f"JSON_PARSE_ERROR:{exc.__class__.__name__}")
    elif suffix == ".jsonl":
        invalid = 0
        for line in content.decode("utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError:
                invalid += 1
        metadata["invalid_jsonl_lines"] = invalid
        if invalid:
            errors.append(f"JSONL_PARSE_ERROR:{invalid}")
    return artifact_type, metadata, errors
