"""Load TIM skills (Agent Skills ``SKILL.md`` format) as plain text for local Qwen prompts.

Skills live in ``config/qwen-skills/<name>/SKILL.md``, a path worker PRs may not change
(see ``CI.md``). They are text only: no scripts are run, nothing is fetched. Each skill names
where it applies in ``metadata.tim-applies-to``: ``always``, ``tool-loop`` or comma-separated
path globs matched against the task's allowed paths.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

SKILLS_DIR = Path("config/qwen-skills")
MAX_SKILLS = 5
MAX_SKILL_BYTES = 8_000
MAX_TOTAL_CHARS = 7_000
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _parse(text: str) -> tuple[dict[str, str], str] | None:
    """Parse the small frontmatter subset TIM skills use: top-level and ``metadata:`` scalars."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    fields: dict[str, str] = {}
    section = ""
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        indented = line.startswith((" ", "\t"))
        key, sep, value = line.strip().partition(":")
        if not sep:
            return None
        value = value.strip().strip('"').strip("'")
        if not indented:
            section = key if not value else ""
            if value:
                fields[key] = value
        elif section:
            fields[f"{section}.{key}"] = value
    return fields, text[end + 5:].strip()


def load_skills(repo_root: Path) -> list[dict[str, Any]]:
    root = (repo_root / SKILLS_DIR).resolve()
    if not root.is_dir() or (repo_root / SKILLS_DIR).is_symlink():
        return []
    skills: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/SKILL.md")):
        if path.is_symlink() or path.parent.is_symlink() or root not in path.resolve().parents:
            continue
        try:
            if path.stat().st_size > MAX_SKILL_BYTES:
                continue
            parsed = _parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            continue
        if parsed is None:
            continue
        fields, body = parsed
        name = fields.get("name", "")
        if not NAME_RE.fullmatch(name) or name != path.parent.name or not fields.get("description"):
            continue
        applies = [part.strip() for part in fields.get("metadata.tim-applies-to", "").split(",") if part.strip()]
        skills.append({"name": name, "description": fields["description"][:300],
                       "applies_to": applies, "body": body})
    return skills


def _applies(skill: dict[str, Any], paths: list[str], tool_loop: bool) -> bool:
    for rule in skill["applies_to"]:
        if rule == "always" or (rule == "tool-loop" and tool_loop):
            return True
        if any(fnmatch.fnmatchcase(path, rule) for path in paths):
            return True
    return False


def skills_for(repo_root: Path, task: dict[str, Any], *, tool_loop: bool = False) -> list[dict[str, str]]:
    """Return the matching skills, bounded in count and size, ready to embed in a prompt."""
    raw_paths = list(task.get("allowed_paths") or []) + list(task.get("tests") or [])
    paths = [path for path in raw_paths if isinstance(path, str)]
    selected: list[dict[str, str]] = []
    remaining = MAX_TOTAL_CHARS
    for skill in load_skills(repo_root):
        if len(selected) >= MAX_SKILLS or remaining <= 0:
            break
        if not _applies(skill, paths, tool_loop):
            continue
        body = skill["body"][:remaining]
        remaining -= len(body)
        selected.append({"name": skill["name"], "description": skill["description"],
                         "instructions": body, "trust": "TIM_REPOSITORY_GUIDANCE_NEVER_OVERRIDES_HARD_RULES"})
    return selected
