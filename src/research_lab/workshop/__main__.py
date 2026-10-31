"""Research workshop command line.

    python -m src.research_lab.workshop add --source uzi --title "..." --hypothesis "..." --data archive_spot_klines [--tag x]
                                            [--template regel_backtest] [--period 2020-01-01 2024-12-31] [--derived-from S10]
    python -m src.research_lab.workshop list [--json]
    python -m src.research_lab.workshop check [--record]
    python -m src.research_lab.workshop import --journal-review FILE | --reflection FILE
    python -m src.research_lab.workshop draft --idea I-0001 --spec spec.json [--dry-run]
    python -m src.research_lab.workshop reflect-trades --journal ~/TIM-live/data/journal/tim_plan_journal.json [--dry-run] [--ideas]
    python -m src.research_lab.workshop approve --study S12 --reference "Uzi 31.10. 16:00 im Thread" [--register]
    python -m src.research_lab.workshop submit --study S12 [--host mac|server] [--input DIR] -- scripts/research_lab_s12.py --count
    python -m src.research_lab.workshop run (--job J-0001 | --pending) [--ssh tim-research@host --remote-dir DIR]
    python -m src.research_lab.workshop verify --bundle data/research/bundles/J-0001
    python -m src.research_lab.workshop jobs
    python -m src.research_lab.workshop charter

Reads and writes only the idea queue (default docs/research_lab/IDEEN.jsonl) and, for
``draft``, one new pre-registration draft under docs/research_lab/studien/.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.research_lab.workshop import charter
from src.research_lab.workshop.generator import DraftError, create_draft
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
    draft = sub.add_parser("draft")
    draft.add_argument("--idea", required=True)
    draft.add_argument("--spec", required=True, type=Path)
    draft.add_argument("--studies-dir", type=Path, default=Path("docs/research_lab/studien"))
    draft.add_argument("--register", type=Path, default=Path("docs/research_lab/REGISTER.jsonl"))
    draft.add_argument("--dry-run", action="store_true", help="Entwurf nur anzeigen, nichts schreiben")
    trades = sub.add_parser("reflect-trades", help="jeden geschlossenen Papier-Trade reflektieren")
    trades.add_argument("--journal", action="append", required=True, type=Path)
    trades.add_argument("--log", type=Path, default=Path("data/research/trade_reflections.jsonl"))
    trades.add_argument("--dry-run", action="store_true")
    trades.add_argument("--ideas", action="store_true", help="wiederkehrende Muster als Ideen eintragen")
    ok = sub.add_parser("approve", help="Uzis Freigabe einer Studie festhalten")
    ok.add_argument("--study", required=True)
    ok.add_argument("--reference", required=True)
    ok.add_argument("--register", action="store_true")
    sm = sub.add_parser("submit")
    sm.add_argument("--study", required=True)
    sm.add_argument("--host", default="mac", choices=["mac", "server"])
    sm.add_argument("--input", action="append", default=[])
    sm.add_argument("job_command", nargs=argparse.REMAINDER)
    rn = sub.add_parser("run")
    which = rn.add_mutually_exclusive_group(required=True)
    which.add_argument("--job")
    which.add_argument("--pending", action="store_true")
    rn.add_argument("--ssh", help="Rechenhost, z. B. tim-research@tim-core-01")
    rn.add_argument("--remote-dir")
    vf = sub.add_parser("verify")
    vf.add_argument("--bundle", required=True, type=Path)
    sub.add_parser("jobs")
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
        elif args.command == "draft":
            path, text = create_draft(queue, args.idea, json.loads(args.spec.read_text(encoding="utf-8")), now=_now(),
                                      studies_dir=args.studies_dir, register_path=args.register,
                                      logbook_path=args.logbook, write=not args.dry_run)
            print(text if args.dry_run else path)
        elif args.command == "reflect-trades":
            from src.dashboard.plan_journal import load_view
            from src.research_lab.workshop.trade_reflection import ReflectionLog, patterns, propose_ideas, reflect_journal
            log = ReflectionLog(args.log)
            for path in args.journal:
                fresh = reflect_journal(load_view(path), log, name=path.stem, write=not args.dry_run)
                print(f"{path.stem}: {len(fresh)} neue Trades reflektiert")
                for item in fresh:
                    print(f"  {item['trade_id']}  {item['summary']}")
                    for text in item["lesson_text"]:
                        print(f"        - {text}")
            if not args.dry_run:
                print(json.dumps(patterns(log.records()), ensure_ascii=False))
                if args.ideas:
                    added = propose_ideas(log.records(), queue)
                    print("Neue Ideen: " + (" ".join(added) if added else "keine"))
        elif args.command in {"approve", "submit", "run", "verify", "jobs"}:
            from src.research_lab.workshop import runner
            jobs = runner.JobQueue()
            if args.command == "approve":
                jobs.approve(args.study, by="uzi", reference=args.reference, register=args.register)
                print(f"{args.study} freigegeben")
            elif args.command == "submit":
                command = [c for c in args.job_command if c != "--"]
                print(jobs.submit(args.study, command, host=args.host, inputs=args.input))
            elif args.command == "run":
                targets = [args.job] if args.job else [j["job"] for j in jobs.pending("server" if args.ssh else "mac")]
                executor = runner.ssh_executor(args.ssh, args.remote_dir) if args.ssh else None
                for job_id in targets:
                    manifest = runner.run_job(jobs, job_id, executor=executor)
                    print(f"{job_id}: Exit {manifest['exit_code']}, Inhalt {manifest['content_hash'][:16]}")
            elif args.command == "verify":
                manifest = runner.verify_bundle(args.bundle)
                print(f"{manifest['job']} geprüft, Inhalt {manifest['content_hash']}")
            else:
                for job in jobs.jobs().values():
                    print(f"{job['job']}  {job['study']}  {job['host']}  {job['status']}  {' '.join(job['command'])}")
        elif args.command == "charter":
            print(f"{charter.CHARTER_VERSION}, Stufe {charter.STAGE}, Budget {charter.MONTHLY_STUDY_BUDGET} Studien/Monat")
            for line in charter.FIXED_LIMITS:
                print(f"- {line}")
    except (IdeaError, DraftError, ValueError) as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
