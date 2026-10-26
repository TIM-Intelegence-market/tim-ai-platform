"""Keep the Obsidian vault and the TIM graph current without a human step.

One run (launchd `com.tim.obsidian-refresh`, hourly on the Mac):
1. Graph clone: `git fetch` and fast-forward to `origin/platform-main`.
   Local changes to tracked files are never touched; the run then keeps the
   old code and reports `pull: local_changes`.
2. Vault: one note per ISO week with the PRs merged into platform-main
   (title, link, date, wikilinks to the system notes their files touch),
   plus the overview note `TIM Stand automatisch`. All of them live in
   `TIM/90 Berichte/Automatisch/` and carry the tag `automatisch`; a file
   there without that tag is never overwritten. Unchanged notes are not
   rewritten, so Obsidian and the vault git see no churn.
3. Graph MCP database: `refresh-all` (code + docs + runtime, read-only)
   when platform-main moved, otherwise only the cheap `refresh-docs`.
4. Graphify view (only when platform-main moved): `graphify update` and a copy of `graph.html` to
   `~/Documents/TIM/TIM Graph Ansicht/`; the tracked `graphify-out/` in
   the clone is restored afterwards so the next fast-forward is not blocked.
5. Vault git: commits only the automatic folder, never other changes.

Status goes to `~/Library/Application Support/TIM/obsidian-refresh/status.json`.

Usage:
  python -m src.obsidian_vault.auto_refresh --repo ~/Documents/TIM/tim-graph
  add --dry-run to print what would change, --skip-graph / --skip-graphify
  to leave those steps out.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.obsidian_vault.schema import DEFAULT_VAULT, load_schema, vault_path  # noqa: E402

BRANCH = "platform-main"
_MERGE_SUBJECT = re.compile(r"^Merge pull request #(\d+)(.*)$")
_SQUASH_SUBJECT = re.compile(r"^(.+?) \(#(\d+)\)$")
AUTO_DIR = Path("90 Berichte") / "Automatisch"
TAG = "automatisch"
OVERVIEW = "TIM Stand automatisch"
SINCE = "2026-10-01"  # older PRs are in the master draft and the PR reports
REPO_URL = "https://github.com/TIM-Intelegence-market/tim-ai-platform"
STATUS_DIR = Path.home() / "Library/Application Support/TIM/obsidian-refresh"
VIEW_DIR = Path.home() / "Documents/TIM/TIM Graph Ansicht"

# Path fragment -> existing vault note. First match per rule, all rules apply.
LINK_RULES: tuple[tuple[str, str], ...] = (
    ("src/graph_mcp/", "TIM Graph MCP"),
    ("src/obsidian_vault/", "Obsidian"),
    ("docs/obsidian/", "Obsidian"),
    ("src/research", "Research Engine"),
    ("src/orderflow", "Research Architecture"),
    ("src/paper/", "Research Architecture"),
    ("src/data_ingestion/", "Data Ingestion"),
    ("src/market_data/", "Data Ingestion"),
    ("src/sources/", "Data Ingestion"),
    ("outbox", "Durable Outbox"),
    ("candle", "Candle Engine"),
    ("src/quality/", "Data QA MOC"),
    ("deploy/", "Server Infrastructure"),
    ("src/server_readiness/", "Server Infrastructure"),
    ("src/agents/", "AI Agent Architecture"),
    ("src/agent_infra/", "AI Agent Architecture"),
    ("src/repair_", "Qwen Repair Worker"),
    ("src/bugfixer/", "Qwen Repair Worker"),
    ("tools/mac-worker", "Qwen Repair Worker"),
    ("src/dashboard/", "System Architecture"),
    ("src/control_portal/", "System Architecture"),
    ("src/operational/", "System Architecture"),
    ("ai-resources/", "AI Tooling Architecture"),
    (".claude/", "AI Tooling Architecture"),
)


@dataclass(frozen=True)
class MergedPr:
    number: int
    title: str
    merged_on: str  # YYYY-MM-DD
    files: tuple[str, ...] = ()

    @property
    def url(self) -> str:
        return f"{REPO_URL}/pull/{self.number}"

    @property
    def links(self) -> tuple[str, ...]:
        return links_for(self.files)


@dataclass
class Report:
    pull: str = "skipped"
    head: str = ""
    prs: int = 0
    notes_written: list[str] = field(default_factory=list)
    notes_unchanged: int = 0
    notes_refused: list[str] = field(default_factory=list)
    graph: str = "skipped"
    graphify: str = "skipped"
    vault_commit: str = "skipped"
    errors: list[str] = field(default_factory=list)


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                            text=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def links_for(files: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    found = {note for path in files for fragment, note in LINK_RULES if fragment in path}
    return tuple(sorted(found))


def parse_merge_log(log: str) -> list[tuple[str, int, str, str]]:
    """`git log --format=%H%x1f%cs%x1f%s%x1f%b%x1e` -> (sha, number, date, title).

    Merge commits come as `Merge pull request #N: title` or
    `Merge pull request #N from owner/branch` (title in the body); squash
    merges as `title (#N)`. Other commits are ignored."""
    out: list[tuple[str, int, str, str]] = []
    for record in log.split("\x1e"):
        parts = record.strip("\n").split("\x1f")
        if len(parts) < 4:
            continue
        sha, day, subject, body = parts[0].strip(), parts[1], parts[2], parts[3]
        match = _MERGE_SUBJECT.match(subject)
        squash = _SQUASH_SUBJECT.match(subject)
        if squash and not match:
            out.append((sha, int(squash.group(2)), day, squash.group(1).strip()))
            continue
        if not match:
            continue
        digits, tail = match.group(1), match.group(2)
        if tail.startswith(":"):
            title = tail[1:].strip()
        else:
            title = next((line.strip() for line in body.splitlines() if line.strip()), "")
        out.append((sha, int(digits), day, title or f"PR {digits}"))
    return out


def merged_prs(repo: Path, ref: str, since: str = SINCE) -> list[MergedPr]:
    log = git(repo, "log", ref, "--first-parent", f"--since={since}",
              "--format=%H%x1f%cs%x1f%s%x1f%b%x1e")
    prs = []
    for sha, number, day, title in parse_merge_log(log):
        if day < since:
            continue
        files = git(repo, "diff", "--name-only", f"{sha}^1", sha).split()
        prs.append(MergedPr(number, title, day, tuple(files)))
    return sorted(prs, key=lambda pr: pr.number)


def week_of(day: str) -> str:
    year, week, _ = date.fromisoformat(day).isocalendar()
    return f"{year}-W{week:02d}"


def _frontmatter(updated: str) -> str:
    return ("---\ntype: report\nstatus: active\nproject: TIM\n"
            f"updated: {updated}\ntags:\n  - {TAG}\n---\n")


def _clean(title: str) -> str:
    return " ".join(title.replace("[[", "(").replace("]]", ")").split())


def render_week(week: str, prs: list[MergedPr]) -> str:
    updated = max(pr.merged_on for pr in prs)
    lines = [_frontmatter(updated) + f"# PRs {week}", "",
             f"Automatisch aus platform-main, {len(prs)} gemergte PRs. "
             f"Übersicht: [[{OVERVIEW}]]. Diese Datei nicht von Hand ändern.", ""]
    for pr in sorted(prs, key=lambda item: item.number):
        links = ", ".join(f"[[{name}]]" for name in pr.links)
        lines.append(f"- [#{pr.number}]({pr.url}) {pr.merged_on}: {_clean(pr.title)}"
                     + (f" · {links}" if links else ""))
    return "\n".join(lines) + "\n"


def render_overview(head: str, prs: list[MergedPr], weeks: list[str]) -> str:
    updated = max((pr.merged_on for pr in prs), default=SINCE)
    counts: dict[str, int] = {}
    for pr in prs:
        for name in pr.links:
            counts[name] = counts.get(name, 0) + 1
    lines = [_frontmatter(updated) + f"# {OVERVIEW}", "",
             f"Stand platform-main: `{head[:7] or 'unbekannt'}`, letzter Merge {updated}. "
             f"Gemergte PRs seit {SINCE}: {len(prs)}.", "",
             "Wird stündlich vom Mac neu geschrieben (launchd `com.tim.obsidian-refresh`). "
             "Gate-Stand und Entscheidungen bleiben in [[TIM Current Status]] und "
             "[[Decision Log]]; diese Notiz ersetzt keine Prüfung.", "",
             "## Wochen", ""]
    lines += [f"- [[PRs {week}]]" for week in sorted(weeks, reverse=True)]
    lines += ["", "## Betroffene Bereiche", ""]
    lines += [f"- [[{name}]]: {count} PRs"
              for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    lines += ["", "## Letzte PRs", ""]
    lines += [f"- [#{pr.number}]({pr.url}) {pr.merged_on}: {_clean(pr.title)}"
              for pr in sorted(prs, key=lambda item: item.number, reverse=True)[:15]]
    return "\n".join(lines) + "\n"


def write_notes(vault: Path, notes: dict[str, str], report: Report,
                dry_run: bool = False) -> None:
    folder = vault / load_schema().content_root / AUTO_DIR
    for name, text in notes.items():
        path = folder / f"{name}.md"
        if path.exists():
            current = path.read_text(encoding="utf-8")
            if current == text:
                report.notes_unchanged += 1
                continue
            if f"  - {TAG}\n" not in current:
                report.notes_refused.append(str(path))  # someone else's note
                continue
        if not dry_run:
            folder.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        report.notes_written.append(str(path))


def pull(repo: Path, report: Report) -> str:
    git(repo, "fetch", "--quiet", "origin", BRANCH)
    target = f"origin/{BRANCH}"
    if git(repo, "rev-parse", "HEAD").strip() == git(repo, "rev-parse", target).strip():
        report.pull = "up_to_date"
    elif git(repo, "status", "--porcelain", "--untracked-files=no").strip():
        report.pull = "local_changes"
    else:
        result = subprocess.run(["git", "-C", str(repo), "merge", "--ff-only", "--quiet", target],
                                capture_output=True, text=True, check=False)
        report.pull = "updated" if result.returncode == 0 else "not_fast_forward"
    return target


def refresh_graph(repo: Path, vault: Path, report: Report, mode: str = "refresh-all") -> None:
    db = repo / ".runtime/graph/graph.sqlite"
    env = dict(os.environ, PYTHONPATH=str(repo), TIM_OBSIDIAN_VAULT=str(vault))
    result = subprocess.run([sys.executable, "-m", "src.graph_mcp.cli", "--root", str(repo),
                             "--db", str(db), "--vault", str(vault), mode],
                            cwd=repo, env=env, capture_output=True, text=True, check=False)
    report.graph = f"ok {mode}" if result.returncode == 0 else f"error {result.returncode}"
    if result.returncode != 0:
        report.errors.append(result.stderr.strip()[-500:])


def refresh_graphify(repo: Path, view_dir: Path, report: Report) -> None:
    binary = shutil.which("graphify") or str(Path.home() / ".local/bin/graphify")
    if not Path(binary).exists():
        report.graphify = "not_installed"
        return
    result = subprocess.run([binary, "update", str(repo)], cwd=repo, capture_output=True,
                            text=True, check=False)
    html = repo / "graphify-out/graph.html"
    if result.returncode == 0 and html.exists():
        view_dir.mkdir(parents=True, exist_ok=True)
        for name in ("graph.html", "GRAPH_REPORT.md", "graph.json"):
            if (repo / "graphify-out" / name).exists():
                shutil.copy2(repo / "graphify-out" / name, view_dir / name)
        report.graphify = "ok"
    else:
        report.graphify = f"error {result.returncode}"
        report.errors.append((result.stderr or result.stdout).strip()[-500:])
    # graphify-out/ is tracked: restore it so the next fast-forward is not blocked
    git(repo, "checkout", "--", "graphify-out", check=False)
    git(repo, "clean", "-fdq", "--", "graphify-out", check=False)


def commit_vault(vault: Path, report: Report) -> None:
    if not (vault / ".git").exists():
        report.vault_commit = "no_git"
        return
    rel = str(Path(load_schema().content_root) / AUTO_DIR)
    git(vault, "add", "--", rel)
    if not git(vault, "diff", "--cached", "--name-only", "--", rel).strip():
        report.vault_commit = "nothing"
        return
    git(vault, "commit", "--quiet", "-m", "Automatisch: PR-Wochen und TIM-Stand", "--", rel)
    report.vault_commit = "committed"


def run(repo: Path, vault: Path, dry_run: bool = False, skip_graph: bool = False,
        skip_graphify: bool = False, view_dir: Path = VIEW_DIR,
        previous: dict | None = None) -> Report:
    """`previous` is the last status: code-heavy steps (full graph rebuild,
    graphify) only run when platform-main moved or the last run failed them."""
    previous = previous or {}
    report = Report()
    ref = "HEAD"
    try:
        if not dry_run:
            pull(repo, report)
        else:
            git(repo, "fetch", "--quiet", "origin", BRANCH, check=False)
            ref = f"origin/{BRANCH}"
    except RuntimeError as exc:
        report.pull = "fetch_failed"
        report.errors.append(str(exc))
    report.head = git(repo, "rev-parse", ref).strip()
    prs = merged_prs(repo, ref)
    report.prs = len(prs)
    weeks: dict[str, list[MergedPr]] = {}
    for pr in prs:
        weeks.setdefault(week_of(pr.merged_on), []).append(pr)
    notes = {f"PRs {week}": render_week(week, items) for week, items in weeks.items()}
    notes[OVERVIEW] = render_overview(report.head, prs, list(weeks))
    write_notes(vault, notes, report, dry_run)
    if dry_run:
        return report
    same_head = previous.get("head") == report.head
    if not skip_graph:
        full = not (same_head and str(previous.get("graph", "")).startswith("ok"))
        refresh_graph(repo, vault, report, "refresh-all" if full else "refresh-docs")
    if not skip_graphify:
        if same_head and previous.get("graphify") in ("ok", "unchanged"):
            report.graphify = "unchanged"
        else:
            refresh_graphify(repo, view_dir, report)
    commit_vault(vault, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help="Klon, der platform-main folgt")
    parser.add_argument("--vault")
    parser.add_argument("--status", default=str(STATUS_DIR / "status.json"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-graph", action="store_true")
    parser.add_argument("--skip-graphify", action="store_true")
    args = parser.parse_args(argv)
    vault = vault_path(args.vault) or DEFAULT_VAULT
    status = Path(args.status).expanduser()
    try:
        previous = json.loads(status.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    report = run(Path(args.repo).expanduser().resolve(), vault, args.dry_run,
                 args.skip_graph, args.skip_graphify, previous=previous)
    payload = dict(report.__dict__, finished_at=datetime.now(timezone.utc).isoformat(
        timespec="seconds"), dry_run=args.dry_run)
    if not args.dry_run:
        status.parent.mkdir(parents=True, exist_ok=True)
        status.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if not report.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
