#!/usr/bin/env python3
"""Research Case materialization (Issue #3, Phase 4).

Builds research cases deterministically from persisted observations with
``src.research.case_builder`` and writes only the derived ``research_cases``
rows. Observations, candles and raw data are read, never written.

Modes:
  dry-run   build in memory, write preview/manifest/counts/exclusions; no DB writes.
  apply     like dry-run, then upsert changed cases in one transaction; the
            observations fingerprint is taken before and after and must match.
  validate  rebuild with the manifest's ``as_of`` and compare against the DB;
            exits 1 on any difference (a second apply would change nothing).

Sources:
  db        persisted observations, cases, gaps and candles (``--database-url``).
  jsonl     observations exported as one ``Observation.to_dict()`` per line
            (offline, dry-run only).
  fixtures  synthetic candle windows through the real ObservationEngine
            (pipeline smoke test, dry-run only; never applied anywhere).

Example on the server (OBSERVE-only, writes research_cases only):
  python scripts/materialize_research_cases.py --source db --mode dry-run
  python scripts/materialize_research_cases.py --source db --mode apply
  python scripts/materialize_research_cases.py --source db --mode validate
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models.market_data import Candle, Observation, ObservationKind  # noqa: E402
from src.observation.engine import ObservationEngine  # noqa: E402
from src.research.case_builder import (  # noqa: E402
    HORIZON_BARS, MaterializationResult, assess, case_window, materialize, parse_timeframe,
)

OUT_DIR = Path(__file__).resolve().parents[1] / "artifacts/research_cases"
FIXTURE_WINDOWS = [
    (datetime(2026, 1, 5, tzinfo=timezone.utc),
     [(100, 100, 95, 98), (98, 105, 97, 102), (102, 110, 98, 104), (104, 106, 99, 103), (103, 104, 98, 102), (102, 109, 101, 109), (109, 113, 108, 112)]),
    (datetime(2026, 1, 6, tzinfo=timezone.utc),
     [(100, 102, 99, 101)] * 5 + [(101, 102, 100, 101)] + [(101, 103, 90, 101.5)]),
    (datetime(2026, 1, 7, tzinfo=timezone.utc),
     [(100, 102, 99, 101)] * 4 + [(101, 112, 100, 111)] + [(111, 112, 100, 108)]),
]


def fixture_inputs() -> tuple[list[Observation], list[Candle]]:
    """Cumulative evaluation like the live runtime (history grows, engine deduplicates)."""
    engine, cumulative, observations = ObservationEngine(), [], []
    for start, values in FIXTURE_WINDOWS:
        cumulative.extend(Candle("BTCUSDT", "1m", start + timedelta(minutes=i), start + timedelta(minutes=i + 1), float(o), float(h), float(low), float(c), 10.0, 10)
                          for i, (o, h, low, c) in enumerate(values))
        observations.extend(engine.evaluate(list(cumulative)))
    return observations, cumulative


def observation_from_dict(row: dict[str, Any]) -> Observation:
    return Observation(
        kind=ObservationKind(row["kind"]), symbol=row["symbol"], timeframe=row["timeframe"],
        observed_at=datetime.fromisoformat(row["observed_at"]), summary=row.get("summary", ""),
        confidence=int(row.get("confidence", 0)), evidence=row.get("evidence") or {},
        source=row.get("source", "deterministic_rules"), provenance=row.get("provenance", "PUBLIC_MARKET_DATA"),
        observation_version=int(row.get("observation_version", 1)), rule_id=row.get("rule_id", "unassigned"),
        rule_version=row.get("rule_version", ""), input_hash=row.get("input_hash", ""),
        observation_id=UUID(str(row["observation_id"])),
        created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else datetime.fromisoformat(row["observed_at"]),
    )


def candle_ranges(result_cases, as_of: datetime) -> dict[tuple[str, str], tuple[datetime, datetime]]:
    ranges: dict[tuple[str, str], tuple[datetime, datetime]] = {}
    for case in result_cases:
        step = parse_timeframe(case.timeframe) or timedelta(minutes=1)
        start, end = case_window(case.opened_at)
        lo, hi = end - step, min(as_of, end + step * HORIZON_BARS)
        key = (case.symbol, case.timeframe)
        old = ranges.get(key)
        ranges[key] = (min(lo, old[0]), max(hi, old[1])) if old else (lo, hi)
    return ranges


def write_outputs(result: MaterializationResult, mode: str, source: str, out_dir: Path, extra: dict[str, Any]) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"mode": mode, "source": source, **result.manifest(), **extra}
    reasons: dict[str, int] = {}
    for case in result.cases:
        for reason in case.missing_evidence:
            reasons[reason] = reasons.get(reason, 0) + 1
    exclusions = {"as_of": manifest["as_of"], "excluded_observations": result.excluded,
                  "missing_evidence_counts": dict(sorted(reasons.items()))}
    counts = {"as_of": manifest["as_of"], "total": len(result.cases), "by_status": result.status_counts()}
    name = "materialization_manifest.json" if mode == "apply" else f"materialization_{mode}.json"
    (out_dir / name).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    (out_dir / "case_status_counts.json").write_text(json.dumps(counts, indent=1, sort_keys=True) + "\n")
    (out_dir / "exclusion_reasons.json").write_text(json.dumps(exclusions, indent=1, sort_keys=True) + "\n")
    return manifest


async def build_from_db(repo, symbol: str, as_of: datetime) -> tuple[MaterializationResult, list]:
    observations = await repo.observations_until(symbol, as_of)
    existing = await repo.observation_research_cases(symbol)
    gaps = await repo.research_case_gaps(symbol)
    draft = materialize(observations, as_of, existing=existing, gaps=gaps, candles_by_key={})
    candles = {key: await repo.candle_closes(key[0], key[1], lo, hi) for key, (lo, hi) in candle_ranges(draft.cases, as_of).items()}
    return materialize(observations, as_of, existing=existing, gaps=gaps, candles_by_key=candles), existing


async def run_db(args, as_of: datetime) -> int:
    from src.database.connection import Database
    from src.database.repository import MarketRepository

    db = Database(args.database_url)
    await db.connect()
    try:
        repo = MarketRepository(db)
        before = await repo.observations_fingerprint(args.symbol)
        result, existing = await build_from_db(repo, args.symbol, as_of)
        if args.mode == "validate":
            persisted = {case.case_id: case.to_dict() for case in existing}
            newer = {case.case_id for case in existing if case.updated_at > as_of}
            diffs = [case.case_id for case in result.cases if case.case_id not in newer and persisted.get(case.case_id) != case.to_dict()]
            report = {"mode": "validate", "as_of": as_of.isoformat(), "cases": len(result.cases), "persisted_cases": len(persisted),
                      "differences": diffs[:50], "difference_count": len(diffs), "skipped_newer": len(newer), "observations": before,
                      "status": "PASS" if not diffs else "FAIL"}
            Path(args.out_dir).mkdir(parents=True, exist_ok=True)
            (Path(args.out_dir) / "validation.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
            print(json.dumps({key: report[key] for key in ("status", "cases", "difference_count")}))
            return 0 if not diffs else 1
        changes = None
        if args.mode == "apply":
            # Short transactions keep row locks brief while the live runtime keeps writing cases.
            changes = {"inserted": 0, "updated": 0, "unchanged": 0, "skipped_newer": 0}
            for start in range(0, len(result.cases), args.batch_size):
                part = await repo.apply_research_cases(result.cases[start:start + args.batch_size], as_of=as_of)
                changes = {key: changes[key] + part[key] for key in changes}
        after = await repo.observations_fingerprint(args.symbol)
        if before != after:
            print(json.dumps({"error": "observations changed during materialization", "before": before, "after": after}))
            return 2
        manifest = write_outputs(result, args.mode, "db", Path(args.out_dir), {"changes": changes, "observations_fingerprint": before})
        print(json.dumps({key: manifest[key] for key in ("mode", "as_of", "cases", "status_counts", "manifest_hash")} | {"changes": changes}))
        return 0
    finally:
        await db.close()


def parse_as_of(value: str | None, manifest_path: Path) -> datetime:
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc).replace(second=0, microsecond=0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", required=True, choices=["dry-run", "apply", "validate"])
    parser.add_argument("--source", default="db", choices=["db", "jsonl", "fixtures"])
    parser.add_argument("--input", help="observations JSONL for --source jsonl")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--as-of", help="data time (ISO, UTC); default: now floored to the minute; validate defaults to the manifest's as_of")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--batch-size", type=int, default=500, help="cases per apply transaction")
    args = parser.parse_args()
    manifest_path = Path(args.out_dir) / "materialization_manifest.json"
    if args.mode == "validate" and not args.as_of and manifest_path.exists():
        args.as_of = json.loads(manifest_path.read_text())["as_of"]
    as_of = parse_as_of(args.as_of, manifest_path)
    if args.source != "db":
        if args.mode != "dry-run":
            parser.error("--source jsonl/fixtures only supports --mode dry-run")
        if args.source == "fixtures":
            observations, candles = fixture_inputs()
            by_key = {("BTCUSDT", "1m"): [{"close_time": c.close_time, "close": c.close} for c in candles]}
        else:
            if not args.input:
                parser.error("--input is required for --source jsonl")
            observations = [observation_from_dict(json.loads(line)) for line in Path(args.input).read_text().splitlines() if line.strip()]
            by_key = None
        result = materialize(observations, as_of, candles_by_key=by_key)
        manifest = write_outputs(result, "dry-run", args.source, Path(args.out_dir), {})
        print(json.dumps({key: manifest[key] for key in ("as_of", "observations_read", "cases", "status_counts", "manifest_hash")}))
        return 0 if result.cases else 1
    if args.database_url is None:
        from config.settings import settings
        args.database_url = settings.database_url
    return asyncio.run(run_db(args, as_of))


if __name__ == "__main__":
    raise SystemExit(main())
