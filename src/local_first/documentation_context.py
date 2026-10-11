"""Small, local-only documentation retrieval for Qwen prompts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

MAX_DOCUMENTS = 3
MAX_FILE_BYTES = 200_000
MAX_SNIPPET_CHARS = 1_200
MAX_TOTAL_CHARS = 3_600
TOKEN = re.compile(r"[a-zA-Z0-9_]{3,}")
SENSITIVE_NAME = re.compile(r"(?i)(secret|credential|private|\.env|token|password|key)")
SENSITIVE_LINE = re.compile(r"(?i)(api[_-]?key|token|password|secret|authorization)\s*[:=]")


def documentation_for(repo_root: Path, task: dict[str, Any]) -> list[dict[str, Any]]:
    """Return bounded relevant Markdown excerpts; never follow links or leave the repo."""
    root = repo_root.resolve()
    docs = root / "docs"
    if not docs.is_dir() or docs.is_symlink():
        return []
    query = " ".join(str(task.get(field, "")) for field in
                     ("objective", "next_action", "blocker_reason"))
    allowed_paths = task.get("allowed_paths")
    if isinstance(allowed_paths, list):
        query += " " + " ".join(str(path) for path in allowed_paths if isinstance(path, str))
    terms = {word.lower() for word in TOKEN.findall(query)}
    if not terms:
        return []
    candidates: list[tuple[int, str, Path, list[str]]] = []
    for path in docs.rglob("*.md"):
        if path.is_symlink() or any(SENSITIVE_NAME.search(part) for part in path.relative_to(root).parts):
            continue
        if root not in path.resolve().parents or not path.is_file():
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        relative = path.relative_to(root).as_posix()
        name_hits = len(terms.intersection(word.lower() for word in TOKEN.findall(relative)))
        line_hits = sum(bool(terms.intersection(word.lower() for word in TOKEN.findall(line)))
                        for line in lines[:500] if not SENSITIVE_LINE.search(line))
        score = 5 * name_hits + min(line_hits, 8)
        if score:
            candidates.append((score, relative, path, lines))
    result: list[dict[str, Any]] = []
    remaining = MAX_TOTAL_CHARS
    for _, relative, _, lines in sorted(candidates, key=lambda item: (-item[0], item[1]))[:MAX_DOCUMENTS]:
        ranked = sorted(
            (index for index, line in enumerate(lines)
             if terms.intersection(word.lower() for word in TOKEN.findall(line))
             and not SENSITIVE_LINE.search(line)),
            key=lambda index: (-len(terms.intersection(word.lower() for word in TOKEN.findall(lines[index]))), index),
        )
        if not ranked:
            continue
        excerpt: list[str] = []
        seen: set[int] = set()
        for hit in ranked:
            for index in (hit, hit + 1):
                if index >= len(lines) or index in seen:
                    continue
                seen.add(index)
                line = lines[index].strip()
                if len(line) > 300 or SENSITIVE_LINE.search(line):
                    continue
                piece = f"L{index + 1}: {line}"
                if len("\n".join(excerpt)) + len(piece) > min(MAX_SNIPPET_CHARS, remaining):
                    break
                excerpt.append(piece)
                if len(excerpt) >= 8:
                    break
            if len(excerpt) >= 8:
                break
        if excerpt:
            content = "\n".join(excerpt)
            remaining -= len(content)
            result.append({"path": relative, "excerpt": content, "trust": "UNTRUSTED_REFERENCE"})
        if remaining <= 0:
            break
    return result
