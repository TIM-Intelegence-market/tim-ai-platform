from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FORBIDDEN_PATH_PARTS = {".env", ".git", "secrets", "keychain", "credentials", "production", "prod"}
FORBIDDEN_CONTENT = (
    "tim_live_trading=1",
    '"tim_live_trading": "1"',
    "tim_execution_enabled=1",
    '"tim_execution_enabled": "1"',
    "live_trading = true",
    "execution_enabled = true",
    "shell=true",
    "os.system(",
)
MAX_FILES = 6
MAX_FILE_BYTES = 256_000


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes()) if path.exists() else "MISSING"


@dataclass(frozen=True, slots=True)
class PatchResult:
    status: str
    proposal_id: str
    changed: list[dict[str, str]]
    tests: dict[str, Any]
    rollback: bool
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "proposal_id": self.proposal_id,
            "changed": self.changed,
            "tests": self.tests,
            "rollback": self.rollback,
            "reason": self.reason,
        }


class SafePatchExecutor:
    """Apply model-proposed UTF-8 replacements only in an explicit sandbox worktree.

    The model never supplies shell commands. Verification is derived only from test paths and
    always runs through ``python -m pytest -q``. Failed verification rolls every file back.
    """

    def __init__(self, repo_root: Path, state_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.state_root = state_root.resolve()

    def apply(self, proposal: dict[str, Any], allowed_paths: list[str]) -> PatchResult:
        proposal_id = str(proposal.get("proposal_id") or "qwen-proposal")[:80]
        if os.getenv("TIM_LOCAL_PATCH_SANDBOX") != "1":
            return PatchResult("BLOCKED", proposal_id, [], {}, False, "sandbox env gate is closed")
        marker = self.repo_root / ".tim" / "local-first" / "PATCH_SANDBOX_ALLOWED"
        if not marker.exists():
            return PatchResult("BLOCKED", proposal_id, [], {}, False, "sandbox marker missing")

        patches = proposal.get("patches")
        if not isinstance(patches, list) or not patches or len(patches) > MAX_FILES:
            return PatchResult("BLOCKED", proposal_id, [], {}, False, "invalid patch count")

        validated: list[tuple[Path, str, bytes]] = []
        for item in patches:
            if not isinstance(item, dict):
                return PatchResult("BLOCKED", proposal_id, [], {}, False, "invalid patch entry")
            relative = str(item.get("path", ""))
            expected = str(item.get("expected_sha256", ""))
            content = item.get("content")
            if not relative or not isinstance(content, str):
                return PatchResult("BLOCKED", proposal_id, [], {}, False, "patch requires path/content")
            path = self._safe_path(relative, allowed_paths)
            if path is None:
                return PatchResult("BLOCKED", proposal_id, [], {}, False, f"path not allowed: {relative}")
            raw = content.encode("utf-8")
            if len(raw) > MAX_FILE_BYTES:
                return PatchResult("BLOCKED", proposal_id, [], {}, False, f"file too large: {relative}")
            lowered = content.lower().replace(" ", "")
            normalized = content.lower()
            if any(token.replace(" ", "") in lowered or token in normalized for token in FORBIDDEN_CONTENT):
                return PatchResult("BLOCKED", proposal_id, [], {}, False, f"forbidden code intent: {relative}")
            current = _sha256(path)
            if expected != current:
                return PatchResult("BLOCKED", proposal_id, [], {}, False, f"hash mismatch: {relative}")
            validated.append((path, relative, raw))

        backup_root = self.state_root / "patch-backups" / proposal_id
        backup_root.mkdir(parents=True, exist_ok=True)
        changed: list[dict[str, str]] = []
        originals: list[tuple[Path, bool, bytes]] = []
        try:
            for path, relative, raw in validated:
                existed = path.exists()
                old = path.read_bytes() if existed else b""
                originals.append((path, existed, old))
                backup = backup_root / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                if existed:
                    backup.write_bytes(old)
                self._atomic_write(path, raw)
                changed.append({
                    "path": relative,
                    "before_sha256": _sha256_bytes(old) if existed else "MISSING",
                    "after_sha256": _sha256(path),
                })

            tests = self._run_tests(proposal.get("tests", []))
            if tests.get("returncode") != 0:
                self._rollback(originals)
                return PatchResult("BLOCKED", proposal_id, changed, tests, True, "verification failed; rolled back")
            return PatchResult("VERIFYING", proposal_id, changed, tests, False)
        except Exception as exc:
            self._rollback(originals)
            return PatchResult("BLOCKED", proposal_id, changed, {}, True, f"{type(exc).__name__}: {exc}")

    def _safe_path(self, relative: str, allowed_paths: list[str]) -> Path | None:
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts or any(part.lower() in FORBIDDEN_PATH_PARTS for part in rel.parts):
            return None
        candidate = (self.repo_root / rel).resolve()
        if candidate != self.repo_root and self.repo_root not in candidate.parents:
            return None
        normalized = relative.replace("\\", "/")
        allowed = False
        for prefix in allowed_paths:
            clean = str(prefix).replace("\\", "/").rstrip("/")
            if clean and (normalized == clean or normalized.startswith(clean + "/")):
                allowed = True
                break
        return candidate if allowed else None

    def _pytest_python(self) -> str | None:
        candidates: list[str] = []
        configured = os.getenv("PYTHON")
        if configured:
            candidates.append(configured)
        venv = self.repo_root / ".venv" / "bin" / "python"
        if venv.is_file():
            candidates.append(str(venv))
        candidates.append(sys.executable)
        for name in ("python3", "python"):
            resolved = shutil.which(name)
            if resolved:
                candidates.append(resolved)

        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                check = subprocess.run(
                    [candidate, "-c", "import pytest"],
                    cwd=self.repo_root,
                    env={**os.environ, "TIM_LIVE_TRADING": "0", "TIM_EXECUTION_ENABLED": "0"},
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if check.returncode == 0:
                return candidate
        return None

    def _run_tests(self, tests: Any) -> dict[str, Any]:
        if not isinstance(tests, list) or not tests or len(tests) > 8:
            return {"returncode": 2, "stderr": "proposal must name 1-8 targeted test files"}
        paths: list[str] = []
        for value in tests:
            relative = str(value).replace("\\", "/")
            if not relative.startswith("tests/") or ".." in Path(relative).parts or not relative.endswith(".py"):
                return {"returncode": 2, "stderr": f"invalid test path: {relative}"}
            if not (self.repo_root / relative).is_file():
                return {"returncode": 2, "stderr": f"test missing: {relative}"}
            paths.append(relative)

        python = self._pytest_python()
        if python is None:
            return {
                "returncode": 2,
                "stderr": "no local Python interpreter with pytest available",
                "tests": paths,
            }

        completed = subprocess.run(
            [python, "-m", "pytest", "-q", *paths],
            cwd=self.repo_root,
            env={**os.environ, "TIM_LIVE_TRADING": "0", "TIM_EXECUTION_ENABLED": "0"},
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout[-12000:],
            "stderr": completed.stderr[-12000:],
            "tests": paths,
            "python": python,
        }

    @staticmethod
    def _atomic_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
            handle.write(raw)
            temp = Path(handle.name)
        temp.replace(path)

    @staticmethod
    def _rollback(originals: list[tuple[Path, bool, bytes]]) -> None:
        for path, existed, old in reversed(originals):
            if existed:
                SafePatchExecutor._atomic_write(path, old)
            else:
                path.unlink(missing_ok=True)
