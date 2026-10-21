"""Weekly reflection report.

    python -m src.reflection.cli --week 2026-W48 --input export.json --out reports/reflection
    python -m src.reflection.cli --week last --database --out reports/reflection
    python -m src.reflection.cli --week 2026-W48 --input export.json --check

The database path connects read-only (PostgreSQL ``default_transaction_read_only``).
Output goes only to ``--out``; nothing else is written.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .reader import load_database, load_export
from .report import build_report, iso_week_window, previous_iso_week, to_json, to_markdown


def _cases(args: argparse.Namespace, start: datetime, end: datetime):
    if args.input:
        return load_export(Path(args.input), start, end)
    from config.settings import settings

    return asyncio.run(load_database(settings.database_url, start, end))


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tim-reflection", description="Wöchentliche Reflexion, nur lesend.")
    parser.add_argument("--week", required=True, help="ISO-Woche wie 2026-W48, oder 'last' für die letzte volle Woche")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="JSON-Export mit observations und validations")
    source.add_argument("--database", action="store_true", help="aus der TIM-Datenbank lesen (nur lesend)")
    parser.add_argument("--out", help="Zielordner für Markdown und JSON")
    parser.add_argument("--check", action="store_true", help="zweimal bauen, Hash und Schutzregeln prüfen, nichts schreiben")
    args = parser.parse_args(argv)
    if not args.check and not args.out:
        parser.error("--out is required unless --check is given")

    week = previous_iso_week(datetime.now(timezone.utc)) if args.week == "last" else args.week
    start, end = iso_week_window(week)
    previous_start = start - timedelta(days=7)
    cases = _cases(args, start, end)
    previous = _cases(args, previous_start, start)
    label = "export" if args.input else "database (read-only)"
    report = build_report(week, cases, previous, source=label)

    if args.check:
        again = build_report(week, cases, previous, source=label)
        problems = []
        if to_json(again) != to_json(report):
            problems.append("report is not deterministic")
        if report["automatic_rule_change"] or (report["proposal"] and report["proposal"]["automatic_rule_change"]):
            problems.append("automatic_rule_change must be false")
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        print(f"{'FAIL' if problems else 'OK'} {week} cases={report['case_count']} hash={report['report_hash']}")
        return 1 if problems else 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"reflection-{week}.json").write_text(to_json(report), encoding="utf-8")
    (out / f"reflection-{week}.md").write_text(to_markdown(report), encoding="utf-8")
    print(f"{week} cases={report['case_count']} proposal={'yes' if report['proposal'] else 'no'} hash={report['report_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
