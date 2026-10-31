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
    python -m src.research_lab.workshop report --bundle data/research/bundles/J-0001 --title "..." [--draft PATH]
    python -m src.research_lab.workshop reflect-month [--month 2026-10] [--write]
    python -m src.research_lab.workshop shadow-start --study S12 --model-id S12-v1 --variant-hash H --code-commit C \\
                                                     --study-version S12/1.0 --cost-rule kosten/1 --min-trades 30 --min-effect 0.05
    python -m src.research_lab.workshop shadow-status
    python -m src.research_lab.workshop rule-from-text --text "Long am Vortages-POC-Retest, Stop unter dem Docht, Ziel 2R"
    python -m src.research_lab.workshop rule-preview --spec regel.json
    python -m src.research_lab.workshop rule-test --spec regel.json [--archive DIR] [--random-runs 200]
    python -m src.research_lab.workshop rule-study --spec regel.json [--run R-0001]
    python -m src.research_lab.workshop rule-log
    python -m src.research_lab.workshop charter

Reads and writes only the idea queue (default data/research/IDEEN.jsonl, on the Mac in ~/TIM-live) and, for
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
    rp = sub.add_parser("report", help="Bericht und Logbuch aus einem geprüften Bündel")
    rp.add_argument("--bundle", required=True, type=Path)
    rp.add_argument("--title", required=True)
    rp.add_argument("--draft")
    rm = sub.add_parser("reflect-month", help="Monats-Reflexion der Forschung")
    rm.add_argument("--month")
    rm.add_argument("--trades-log", type=Path, default=Path("data/research/trade_reflections.jsonl"))
    rm.add_argument("--write", action="store_true", help="Bericht unter docs/research_lab/reports/ ablegen")
    sh = sub.add_parser("shadow-start", help="F7: Kandidat 30 Tage im Schattenbetrieb anmelden")
    sh.add_argument("--study", required=True)
    sh.add_argument("--model-id", required=True)
    sh.add_argument("--variant-hash", required=True)
    sh.add_argument("--code-commit", required=True)
    sh.add_argument("--study-version", required=True)
    sh.add_argument("--cost-rule", required=True)
    sh.add_argument("--min-trades", type=int, required=True)
    sh.add_argument("--min-effect", type=float, required=True)
    sh.add_argument("--horizon-minutes", type=int, default=1440)
    sub.add_parser("shadow-status", help="F7: Stand aller Schatten-Kandidaten (nur lesen)")
    rt = sub.add_parser("rule-from-text", help="F10: Regel in Worten über die Claude-CLI in tim_rule/1 übersetzen")
    rt.add_argument("--text", required=True)
    rt.add_argument("--save-dir", type=Path, default=Path("data/research/rules/specs"))
    rv = sub.add_parser("rule-preview", help="F10: Regel prüfen und in Worten zeigen (nichts wird gerechnet)")
    rv.add_argument("--spec", required=True, type=Path)
    rx = sub.add_parser("rule-test", help="F10: Erkundung auf Training und Validierung (kein Registerplatz)")
    rx.add_argument("--spec", required=True, type=Path)
    rx.add_argument("--archive", type=Path, default=Path("data/research_lab"))
    rx.add_argument("--random-runs", type=int, default=200)
    rx.add_argument("--seed", type=int, default=0)
    rx.add_argument("--by", default="uzi", help="wer die Erkundung angefragt hat")
    rs = sub.add_parser("rule-study", help="F10: Regel als Idee und Generator-Spezifikation für eine echte Studie")
    rs.add_argument("--spec", required=True, type=Path)
    rs.add_argument("--run", help="Erkundung, deren Ergebnis die Studie als Vorbelastung nennen muss")
    rs.add_argument("--out-dir", type=Path, default=Path("data/research/rules/studies"))
    sub.add_parser("rule-log", help="F10: alle Erkundungen")
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
        elif args.command == "report":
            from src.research_lab.workshop.report import report_from_bundle
            print(report_from_bundle(args.bundle, title=args.title, draft=args.draft, logbook=args.logbook))
        elif args.command == "reflect-month":
            from zoneinfo import ZoneInfo
            from src.research_lab.workshop.report import monthly_reflection, render_reflection
            from src.research_lab.workshop.trade_reflection import ReflectionLog
            month = args.month or datetime.now(ZoneInfo(charter.LOCAL_TIMEZONE)).strftime("%Y-%m")
            data = monthly_reflection(month, queue=queue, logbook=load_logbook(args.logbook),
                                      trade_records=ReflectionLog(args.trades_log).records())
            text = render_reflection(data)
            if args.write:
                path = Path("docs/research_lab/reports") / f"forschung_{month}.md"
                path.write_text(text, encoding="utf-8")
                print(path)
            else:
                print(text)
        elif args.command in {"shadow-start", "shadow-status"}:
            from src.research_lab.learning.registry import ModelRegister
            from src.research_lab.workshop import shadow
            register = ModelRegister(shadow.REGISTER_PATH)
            if args.command == "shadow-start":
                entry = shadow.start(register, args.study, model_id=args.model_id, variant_hash=args.variant_hash,
                                     code_commit=args.code_commit, study_version=args.study_version,
                                     cost_rule=args.cost_rule, min_trades=args.min_trades, min_effect=args.min_effect,
                                     horizon_minutes=args.horizon_minutes, at=datetime.now(timezone.utc))
                print(f"{args.model_id}: Fenster {entry['window_start']} bis {entry['window_end']}")
            else:
                print(json.dumps({"head": register.head(), "shadows": shadow.status(register)}, ensure_ascii=False, indent=2))
        elif args.command.startswith("rule-"):
            return _rule_command(args, queue)
        elif args.command == "charter":
            print(f"{charter.CHARTER_VERSION}, Stufe {charter.STAGE}, Budget {charter.MONTHLY_STUDY_BUDGET} Studien/Monat")
            for line in charter.FIXED_LIMITS:
                print(f"- {line}")
    except (IdeaError, DraftError, ValueError) as error:  # LearningError and ShadowError are ValueErrors
        print(f"Fehler: {error}", file=sys.stderr)
        return 2
    return 0


def _ask_claude(prompt: str) -> str:
    from src.local_first.claude_cli_fallback import advise_text
    return advise_text(prompt, timeout=180)


def _rule_command(args: argparse.Namespace, queue: IdeaQueue, ask=None) -> int:
    from src.research_lab.workshop import rules
    if args.command == "rule-log":
        rows = rules.ExplorationLog().records()
        for row in rows:
            print(f"{row['run']}  {row['at']}  {row['status']:<12}  {row['title']}")
        print(rules.exploration_note(rows))
        return 0
    if args.command == "rule-from-text":
        rule = rules.parse_translation((ask or _ask_claude)(rules.translate_prompt(args.text)))
        args.save_dir.mkdir(parents=True, exist_ok=True)
        path = args.save_dir / f"{rules.rule_hash(rule)[:12]}.json"
        path.write_text(json.dumps(rule, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(rules.describe(rule))
        if rule.get("note"):
            print(f"Nicht abbildbar: {rule['note']}")
        print(f"\nGespeichert: {path} (noch nichts gerechnet)")
        return 0
    rule = json.loads(args.spec.read_text(encoding="utf-8"))
    problems = rules.validate(rule)
    if problems:
        print("Regel ungültig:\n- " + "\n- ".join(problems), file=sys.stderr)
        return 2
    if args.command == "rule-preview":
        print(rules.describe(rule))
        print(f"\nRegel-Hash {rules.rule_hash(rule)}. Mindestens {rules.min_cases(rule)['train']} Trades im Training, "
              f"{rules.min_cases(rule)['validation']} in der Validierung.")
        print(rules.exploration_note(rules.ExplorationLog().records()))
        return 0
    if args.command == "rule-test":
        from src.research_lab.data.store import ArchiveStore
        try:
            entry, path = rules.explore(rule, store=ArchiveStore(args.archive), log=rules.ExplorationLog(),
                                        runs_dir=rules.RUNS_DIR, at=_now(), requested_by=args.by,
                                        random_runs=args.random_runs, seed=args.seed)
        except FileNotFoundError as error:
            print(f"Fehler: Archivdaten fehlen unter {args.archive} ({error}); --archive auf den Archiv-Ordner setzen",
                  file=sys.stderr)
            return 2
        print(f"{entry['run']}: {entry['result']}\nBericht: {path}")
        return 0
    if args.run and args.run not in {row["run"] for row in rules.ExplorationLog().records()}:
        print(f"Fehler: Erkundung {args.run} steht nicht im Erkundungs-Log", file=sys.stderr)
        return 2
    spec = rules.study_spec(rule, exploration=args.run)
    idea_id = queue.add(source="uzi", title=rule["title"], hypothesis=spec["question"], data=["archive_usdm_klines"],
                        tags=["regel-anfrage", rule["entry"]["type"], rule["timeframe"]], template="regel_backtest",
                        period=tuple(spec["period"]), counterargument="Kerzenregel; viele ähnliche Regeln sind schon gescheitert.",
                        source_ref=f"rule:{rules.rule_hash(rule)}")
    if not idea_id:
        print("Diese Regel steht schon in der Ideen-Liste", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    path = args.out_dir / f"{idea_id}.json"
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{idea_id} angelegt, Spezifikation {path}. Weiter: `check --record`, dann `draft --idea {idea_id} --spec {path}` "
          "(belegt 1 Registerplatz und 1 Platz im Monatsbudget; Uzi gibt den Entwurf frei).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
