"""Validation helpers for bounded unified diffs."""

import ntpath
import os
import re
from collections.abc import Iterable


_HEADER_RE = re.compile(r"^diff --git a/.* b/(.*)$")


def _invalid_path(path: str) -> bool:
    parts = re.split(r"[/\\]", path)
    return os.path.isabs(path) or ntpath.isabs(path) or ".." in parts


def check_diff(
    diff_text: str,
    allowed_paths: Iterable[str],
    *,
    max_files: int = 5,
    max_changed_lines: int = 200,
) -> dict:
    """Check a unified diff against path and size limits."""
    if not isinstance(diff_text, str) or not diff_text:
        return {
            "ok": False,
            "files": [],
            "changed_lines": 0,
            "violations": ["empty diff"],
        }

    allowed = {str(path) for path in allowed_paths}
    files = set()
    violations = set()
    changed_lines = 0
    in_hunk = False

    for line in diff_text.splitlines():
        header = _HEADER_RE.match(line)
        if header:
            path = header.group(1)
            files.add(path)
            in_hunk = False
            if path not in allowed:
                violations.add(f"path not allowed: {path}")
            if _invalid_path(path):
                violations.add(f"invalid path: {path}")
            continue

        if line.startswith("@@") and line.endswith("@@"):
            in_hunk = True
            continue

        if line.startswith(("GIT binary patch", "Binary files")):
            violations.add("binary patch")
        if line.startswith("deleted file mode"):
            violations.add("deleted file")
        if line.startswith("rename from"):
            violations.add("rename")
        if line.startswith("new mode"):
            violations.add("new mode")

        if in_hunk and (line.startswith("+") or line.startswith("-")):
            if not line.startswith(("+++", "---")):
                changed_lines += 1

    if len(files) > max_files:
        violations.add(f"too many files: limit {max_files}")
    if changed_lines > max_changed_lines:
        violations.add(f"too many changed lines: limit {max_changed_lines}")

    ordered_files = sorted(files)
    ordered_violations = sorted(violations)
    return {
        "ok": not ordered_violations,
        "files": ordered_files,
        "changed_lines": changed_lines,
        "violations": ordered_violations,
    }
