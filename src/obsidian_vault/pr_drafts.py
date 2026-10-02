"""Return path TIM -> vault: merged pull requests become inbox drafts.

Input is the JSON that `gh pr list --state merged --json number,title,url,mergedAt`
prints (from a file or stdin), so this module never talks to the network.
Every draft goes through the draft writer (inbox only, never overwriting,
`review: pending`). A PR is skipped when its URL already appears anywhere
in the vault, so repeated runs and the master draft never cause duplicates.

Usage:
  gh pr list --state merged --limit 50 --json number,title,url,mergedAt \\
    | python -m src.obsidian_vault.pr_drafts --prs-json - [--since 2026-10-01]
  add --dry-run to list what would be written.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.obsidian_vault.draft_writer import Draft, write_draft  # noqa: E402
from src.obsidian_vault.schema import DEFAULT_VAULT, vault_path  # noqa: E402

_PR_URL = re.compile(r"^https://github\.com/[^/\s]+/[^/\s]+/pull/(\d+)$")
_ISSUE_REF = re.compile(r"\s*\(#\d+\)")
NOTICE = "Automatisch aus GitHub übernommen; vor Freigabe gegen den PR prüfen."


@dataclass(frozen=True)
class MergedPr:
    number: int
    title: str
    url: str
    merged_on: str  # YYYY-MM-DD


def parse_prs(payload: str) -> list[MergedPr]:
    prs: list[MergedPr] = []
    for item in json.loads(payload or "[]"):
        url = str(item.get("url", "")).strip()
        match = _PR_URL.match(url)
        merged = str(item.get("mergedAt") or "")[:10]
        if not match or not merged:
            continue  # open/closed-unmerged PRs and foreign URLs are ignored
        number = int(item.get("number") or match.group(1))
        prs.append(MergedPr(number, str(item.get("title", "")).strip(), url, merged))
    return sorted(prs, key=lambda pr: pr.number)


def known_urls(vault: Path) -> set[str]:
    """Every PR URL already mentioned somewhere in the vault."""
    found: set[str] = set()
    for path in vault.rglob("*.md"):
        if any(part.startswith(".") for part in path.relative_to(vault).parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found.update(m.group(0) for m in re.finditer(
            r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+(?!\d)", text))
    return found


def render_body(pr: MergedPr) -> str:
    return (f"PR #{pr.number} wurde am {pr.merged_on} gemergt: {pr.title}\n\n"
            f"Quelle: {pr.url}\n\n{NOTICE}\n")


def run(vault: Path, prs: list[MergedPr], since: str = "", today: date | None = None,
        dry_run: bool = False) -> dict[str, list[str]]:
    seen = known_urls(vault)
    report: dict[str, list[str]] = {"written": [], "skipped_known": [], "skipped_old": [],
                                    "skipped_exists": []}
    for pr in prs:
        if since and pr.merged_on < since:
            report["skipped_old"].append(pr.url)
            continue
        if pr.url in seen:
            report["skipped_known"].append(pr.url)
            continue
        title = _ISSUE_REF.sub("", f"PR {pr.number} {pr.title}")
        draft = Draft("report", title, render_body(pr), pr.url, today)
        try:
            path, _ = write_draft(vault, draft, dry_run=dry_run)
        except FileExistsError:  # same title already in the inbox: never overwrite
            report["skipped_exists"].append(pr.url)
            continue
        seen.add(pr.url)
        report["written"].append(str(path))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prs-json", required=True, help="Datei oder - für stdin")
    parser.add_argument("--since", default="", help="nur PRs ab YYYY-MM-DD")
    parser.add_argument("--date")
    parser.add_argument("--vault")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    payload = (sys.stdin.read() if args.prs_json == "-"
               else Path(args.prs_json).read_text(encoding="utf-8"))
    vault = vault_path(args.vault) or DEFAULT_VAULT
    today = date.fromisoformat(args.date) if args.date else None
    report = run(vault, parse_prs(payload), args.since, today, args.dry_run)
    print(json.dumps({key: len(value) for key, value in report.items()}))
    for path in report["written"]:
        print(("Würde schreiben: " if args.dry_run else "Entwurf geschrieben: ") + path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
