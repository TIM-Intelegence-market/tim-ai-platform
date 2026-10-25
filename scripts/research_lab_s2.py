"""Study S2: fetch the aggTrades days, run the outcome-blind count, run the power gate (section 3).

    python scripts/research_lab_s2.py fetch --from 2019-12-30 --to 2024-12-29 [--verify-days 3] [--keep-raw]
    python scripts/research_lab_s2.py count --out docs/research_lab/reports
    python scripts/research_lab_s2.py power --count-file docs/research_lab/reports/s2_count_<stamp>.json --out docs/research_lab/reports

`fetch` needs network access to data.binance.vision (blocked in the cloud, run it
where the archives may be downloaded). Each day is verified against Binance's
checksum, reduced to per-minute aggregates (``agg/``, no prices) and per-minute
prices (``px/``), and the raw archive is dropped unless ``--keep-raw``. Days from
2025-01-01 on are refused (holdout).

`count` reads ``agg/`` only and writes s2_count_<stamp>.json/.md: weekly case and
control numbers per kind, no hit rate, no price. `power` reads that file and
writes s2_power_<stamp>.json/.md with the registered simulation (10 000
replications, B = 19 999, seed 20261023); it needs numpy and runs for hours.
``--replications``/``--bootstrap`` exist for smoke runs and are recorded in the
report; a run with smaller values is not a gate result.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json  # noqa: E402

from src.research_lab.data.aggtrades import DEFAULT_ROOT, AggTradeDayStore, days_between, fast_available  # noqa: E402
from src.research_lab.studies import s2_power  # noqa: E402
from src.research_lab.studies.s2_orderflow import DIRECTIONAL, SECTIONS, build_count_report, count_weeks, render_count_markdown  # noqa: E402

DEFAULT_FIRST = date(2019, 12, 30)  # Monday before the training start, so the first window has a previous one
DEFAULT_LAST = date(2024, 12, 29)   # last Sunday before the holdout


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")


def fetch(store: AggTradeDayStore, first: date, last: date, *, verify_days: int, keep_raw: bool) -> int:
    days = days_between(first, last)
    if not fast_available():
        print("numpy/pandas not installed: using the pure Python reduction (slow, about 30 s per day)")
    failures: list[str] = []
    started = time.time()
    for index, day in enumerate(days):
        try:
            entry = store.fetch(day, keep_raw=keep_raw, verify=index < verify_days)
        except Exception as error:  # noqa: BLE001 - one bad day must not stop the run; it is reported
            failures.append(f"{day}: {error}")
            print(f"{day}: FAILED {error}")
            continue
        if index % 25 == 0 or index == len(days) - 1:
            elapsed = time.time() - started
            print(f"{day}: {entry['rows']} rows ({index + 1}/{len(days)}, {elapsed / 60:.1f} min)")
    if failures:
        print(f"{len(failures)} days failed:")
        for line in failures:
            print("  " + line)
    print(f"{len(days) - len(failures)} days present under {store.root}")
    return 1 if failures else 0


def count(store: AggTradeDayStore, out_dir: Path) -> int:
    present = store.present_days()
    if not present:
        print("no days fetched"); return 1
    expected = days_between(present[0], present[-1])
    missing = [day.isoformat() for day in expected if day not in set(present)]

    def days():
        for day in present:
            yield day, store.load_aggregates(day)

    weeks = count_weeks(days())
    report = build_count_report(weeks, commit=_commit(), dataset_hash=store.dataset_hash(present), days=len(present), missing_days=missing)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    (out_dir / f"s2_count_{stamp}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    (out_dir / f"s2_count_{stamp}.md").write_text(render_count_markdown(report))
    for name, section in report["sections"].items():
        print(f"{name}: {section['complete_weeks']}/{section['calendar_weeks']} complete weeks")
        for kind, row in section["kinds"].items():
            print(f"  {kind:32s} cases {row['cases']:7d}  controls {row['controls']:9d}  weeks {row['usable_weeks']:4d}  {'minimum met' if row['minimum_met'] else 'below minimum'}")
    print(f"written {out_dir / f's2_count_{stamp}.json'}")
    return 0


def power(count_file: Path, out_dir: Path, *, replications: int, b: int, seed: int, kinds: list[str] | None) -> int:
    report_in = json.loads(count_file.read_text())
    if report_in.get("study") != "S2" or not report_in.get("outcome_blind"):
        print("not an S2 count report"); return 1
    weeks = {}
    for row in report_in["weeks"]:
        year, week = row["week"].split("-W")
        weeks[(int(year), int(week))] = row
    selected = kinds or list(DIRECTIONAL)
    results: dict[str, dict[str, list[s2_power.PowerResult]]] = {}
    started = time.time()
    for section in SECTIONS:
        results[section] = {}
        for kind in selected:
            series = _series_from_report(weeks, section, kind)
            items = []
            for scenario in s2_power.scenarios():
                result = s2_power.simulate_power(series, scenario, replications=replications, seed=seed, b=b)
                items.append(result)
                print(f"{section:10s} {kind:32s} {scenario.id}: power {result.power:.3f} ({(time.time() - started) / 60:.1f} min)")
            results[section][kind] = items
    out = s2_power.build_power_report(results, count_report=report_in, commit=_commit(), replications=replications, b=b, seed=seed,
                                      created=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    out["count_file"] = count_file.name
    out["registered_parameters"] = replications == s2_power.REPLICATIONS and b == s2_power.BOOTSTRAP_B and seed == s2_power.SEED and not kinds
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    (out_dir / f"s2_power_{stamp}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    (out_dir / f"s2_power_{stamp}.md").write_text(s2_power.render_power_markdown(out))
    print(out["gate"])
    if not out["registered_parameters"]:
        print("NOTE: parameters differ from the registration; this is a smoke run, not a gate result")
    print(f"written {out_dir / f's2_power_{stamp}.json'}")
    return 0


def _series_from_report(weeks: dict, section: str, kind: str) -> list[tuple[int, int]]:
    from src.research_lab.studies.s2_orderflow import calendar_weeks

    out = []
    for key in calendar_weeks(section):
        row = weeks.get(key)
        if row is None or not row["complete"]:
            out.append((0, 0)); continue
        cell = row["kinds"][kind]
        out.append((cell["kept"], cell["controls"]) if cell["kept"] >= 1 and cell["controls"] >= 1 else (0, 0))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    f.add_argument("--from", dest="first", type=date.fromisoformat, default=DEFAULT_FIRST)
    f.add_argument("--to", dest="last", type=date.fromisoformat, default=DEFAULT_LAST)
    f.add_argument("--verify-days", type=int, default=3, help="run fast and reference reduction on the first N days")
    f.add_argument("--keep-raw", action="store_true")
    c = sub.add_parser("count")
    c.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    c.add_argument("--out", type=Path, default=Path("docs/research_lab/reports"))
    p = sub.add_parser("power")
    p.add_argument("--count-file", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("docs/research_lab/reports"))
    p.add_argument("--replications", type=int, default=s2_power.REPLICATIONS)
    p.add_argument("--bootstrap", type=int, default=s2_power.BOOTSTRAP_B)
    p.add_argument("--seed", type=int, default=s2_power.SEED)
    p.add_argument("--kind", action="append", choices=sorted(DIRECTIONAL), help="restrict to kinds (smoke runs only)")
    args = parser.parse_args(argv)
    if args.command == "fetch":
        return fetch(AggTradeDayStore(args.root), args.first, args.last, verify_days=args.verify_days, keep_raw=args.keep_raw)
    if args.command == "count":
        return count(AggTradeDayStore(args.root), args.out)
    return power(args.count_file, args.out, replications=args.replications, b=args.bootstrap, seed=args.seed, kinds=args.kind)


if __name__ == "__main__":
    raise SystemExit(main())
