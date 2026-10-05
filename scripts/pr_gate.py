#!/usr/bin/env python3
"""Fail-closed path and mode gate for pipeline pull requests.

Runs from the base checkout (see .github/workflows/pr-gate.yml) and reads the PR
head only as git objects: nothing from the PR is checked out or executed. The
policy file must therefore come from the base branch, never from the PR.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Sequence

REGULAR = "100644"
MAX_SIZED_ENTRIES = 500  # beyond this the file-count limit already rejects the diff; skip per-file git calls
ABSENT = "000000"


class GateError(RuntimeError):
    """The gate could not reach a safe verdict; treated as a failure."""


@dataclass(frozen=True)
class Entry:
    old_mode: str
    new_mode: str
    status: str
    path: str
    new_sha: str = field(default="", compare=False)
    size: int | None = field(default=None, compare=False)  # filled by diff_entries for A/M


def parse_raw(data: str) -> list[Entry]:
    """Parse `git diff --raw -z --no-renames` output."""
    tokens = data.split("\0")
    if tokens and tokens[-1] == "":
        tokens.pop()
    entries: list[Entry] = []
    index = 0
    while index < len(tokens):
        meta = tokens[index]
        fields = meta[1:].split(" ") if meta.startswith(":") else []
        if len(fields) != 5 or index + 1 >= len(tokens):
            raise GateError(f"unparseable diff record: {meta!r}")
        old_mode, new_mode, _old_sha, new_sha, status = fields
        entries.append(Entry(old_mode, new_mode, status, tokens[index + 1], new_sha))
        index += 2
    return entries


def _bad_path(path: str) -> str | None:
    if not path or path.startswith("/") or "\\" in path or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in path):
        return "unsafe path characters"
    if any(part in {"", ".", ".."} for part in path.split("/")):
        return "non-canonical path"
    return None


def evaluate(entries: Sequence[Entry], policy: dict) -> list[str]:
    """Return every violation; an empty list means the diff is within policy."""
    violations: list[str] = []
    if not entries:
        return ["diff is empty"]
    if len(entries) > int(policy["max_files"]):
        violations.append(f"{len(entries)} files changed, limit is {policy['max_files']}")
    deny_prefixes = tuple(prefix.casefold() for prefix in policy["deny_prefixes"])
    allow_prefixes = tuple(prefix.casefold() for prefix in policy["allow_prefixes"])
    deny_names = {name.casefold() for name in policy["deny_names"]}
    deny_deleted = tuple(prefix.casefold() for prefix in policy["deny_deleted_prefixes"])
    for entry in entries:
        path, folded = entry.path, entry.path.casefold()
        problem = _bad_path(path)
        if problem:
            violations.append(f"{path!r}: {problem}")
            continue
        parts = tuple(part.casefold() for part in PurePosixPath(path).parts)
        if entry.status not in {"A", "M", "D"}:
            violations.append(f"{path}: change type {entry.status!r} is not allowed")
        elif entry.status == "A" and entry.new_mode != REGULAR:
            violations.append(f"{path}: new file must be a regular non-executable file (mode {entry.new_mode})")
        elif entry.status == "M" and not (entry.old_mode == entry.new_mode and entry.new_mode in {REGULAR, "100755"}):
            violations.append(f"{path}: mode change {entry.old_mode} -> {entry.new_mode}")
        elif entry.status == "D" and entry.old_mode not in {REGULAR, "100755"}:
            violations.append(f"{path}: deleting a non-regular entry (mode {entry.old_mode})")
        if folded.startswith(deny_prefixes) or ".git" in parts or ".github" in parts or parts[-1] in deny_names:
            violations.append(f"{path}: protected path")
        elif not folded.startswith(allow_prefixes):
            violations.append(f"{path}: outside the allowed paths")
        if entry.status == "D" and folded.startswith(deny_deleted):
            violations.append(f"{path}: deleting files here is not allowed")
        if entry.size is not None and entry.size > int(policy["max_file_bytes"]):
            violations.append(f"{path}: {entry.size} bytes exceeds the limit of {policy['max_file_bytes']}")
    return violations


def load_policy(path: Path) -> dict:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
        for key in ("applies_to_branch_regex", "max_files", "max_file_bytes", "allow_prefixes", "deny_prefixes",
                    "deny_names", "deny_deleted_prefixes"):
            policy[key]
    except (OSError, ValueError, KeyError) as error:
        raise GateError(f"policy unreadable or incomplete: {error!r}") from error
    return policy


def diff_entries(repository: Path, base: str, head: str) -> list[Entry]:
    command = ["git", "diff", "--raw", "-z", "--no-abbrev", "--no-renames", "--no-ext-diff",
               "--no-textconv", f"{base}...{head}", "--"]
    try:
        completed = subprocess.run(command, cwd=repository, check=True, text=True,
                                   capture_output=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
        raise GateError(f"git diff failed: {getattr(error, 'stderr', '') or error}") from error
    entries = parse_raw(completed.stdout)
    sized: list[Entry] = []
    for entry in entries:
        if entry.status in {"A", "M"} and len(entries) <= MAX_SIZED_ENTRIES:
            try:
                size = int(subprocess.run(["git", "cat-file", "-s", entry.new_sha], cwd=repository, check=True,
                                          text=True, capture_output=True, timeout=60).stdout.strip())
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError) as error:
                raise GateError(f"object size unavailable for {entry.path!r}: {error!r}") from error
            entry = replace(entry, size=size)
        sized.append(entry)
    return sized


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--policy", type=Path, required=True, help="policy file taken from the base branch")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--branch", required=True, help="PR head branch name")
    args = parser.parse_args(argv)
    try:
        policy = load_policy(args.policy)
        if not re.fullmatch(policy["applies_to_branch_regex"], args.branch):
            print(f"PR gate not applicable to branch {args.branch!r}; human review rules apply.")
            return 0
        violations = evaluate(diff_entries(args.repository, args.base, args.head), policy)
    except GateError as error:
        print(f"PR gate failed closed: {error}", file=sys.stderr)
        return 1
    if violations:
        print("PR gate rejected this pull request:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1
    print("PR gate passed: every changed path and mode is within policy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
