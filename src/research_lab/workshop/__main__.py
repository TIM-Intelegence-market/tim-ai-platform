"""Research workshop command line.

    python -m src.research_lab.workshop add --source uzi --title "..." --hypothesis "..." --data archive_spot_klines [--tag x]
                                            [--template regel_backtest] [--period 2020-01-01 2024-12-31] [--derived-from S10]
    python -m src.research_lab.workshop list [--json]
    python -m src.research_lab.workshop check [--record]
    python -m src.research_lab.workshop import --journal-review FILE | --reflection FILE
    python -m src.research_lab.workshop charter

Reads and writes only the idea queue (default docs/research_lab/IDEEN.jsonl).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.research_lab.workshop import charter
from src.research_lab.workshop.check import DATA_CATALOGUE, check_ideas, load_logbook, record
from src.research_lab.workshop.ideas import DEFAULT_PATH, STATUSES, IdeaError, IdeaQueue
from src.research_lab.workshop.sources import import_journal_review, import_reflection


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.research_lab.workshop")
    parser.add_argument("--queue", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--logbook", type=Path, default=Path("docs/research_lab/LOGBUCH.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("--source", required=True, choices=sorted(charter.SOURCES))
    add.add_argument("--title", required=True)
    add.add_argument("--hypothesis", required=True)
    add.add_argument("--data", action="append", default=[], choices=sorted(DATA_CATALOGUE))
    add.add_argument("--tag", action="append", default=[])
    add.add_argument("--template", choices=sorted(charter.TEMPLATES))
    add.add_argument("--period", nargs=2, metavar=("FROM", "TO"))
    add.add_argument("--derived-from")
    add.add_argument("--counterargument", default="")
    show = sub.add_parser("list")
    show.add_argument("--json", action="store_true")
    run = sub.add_parser("check")
    run.add_argument("--record", action="store_true", help="geänderte Ergebnisse in die Liste schreiben")
    imp = sub.add_parser("import")
    group = imp.add_mutually_exclusive_group(required=True)
    group.add_argument("--journal-review", type=Path)
    group.add_argument("--reflection", type=Path)
    sub.add_parser("charter")
    args = parser.parse_args(argv)
    queue = IdeaQueue(args.queue)
    try:
        if args.command == "add":
            idea_id = queue.add(source=args.source, title=args.title, hypothesis=args.hypothesis, data=args.data,
                                tags=args.tag, template=args.template, period=tuple(args.period) if args.period else None,
                                derived_from=args.derived_from, counterargument=args.counterargument)
            print(idea_id)
        elif args.command == "list":
            ideas = list(queue.ideas().values())
            if args.json:
                print(json.dumps(ideas, ensure_ascii=False, indent=2))
            for idea in ideas if not args.json else []:
                print(f"{idea['id']}  {STATUSES[idea['status']]:<36}  {idea['title']}  [{charter.SOURCES[idea['source']]}]")
                for reason in idea["reasons"]:
                    print(f"        - {reason}")
        elif args.command == "check":
            now = _now()
            verdicts = check_ideas(queue, load_logbook(args.logbook), now=now)
            for verdict in verdicts:
                print(f"{verdict.idea_id}  {STATUSES[verdict.status]}")
                for reason in verdict.reasons:
                    print(f"        - {reason}")
            if args.record:
                print(f"{record(queue, verdicts, now=now)} Zeilen geschrieben")
        elif args.command == "import":
            if args.journal_review:
                added = import_journal_review(queue, json.loads(args.journal_review.read_text(encoding="utf-8")))
            else:
                added = import_reflection(queue, json.loads(args.reflection.read_text(encoding="utf-8")))
            print(" ".join(added) if added else "nichts Neues")
        elif args.command == "charter":
            print(f"{charter.CHARTER_VERSION}, Stufe {charter.STAGE}, Budget {charter.MONTHLY_STUDY_BUDGET} Studien/Monat")
            for line in charter.FIXED_LIMITS:
                print(f"- {line}")
    except IdeaError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
