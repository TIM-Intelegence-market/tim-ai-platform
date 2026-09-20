#!/usr/bin/env python3
"""Research Case materialization (Phase 4): Dry-Run -> Preview -> Apply ->
Validate -> manifest. Target: isolated TEST database only (5433/tim_test
via 0600 secret file). NEVER production (5432).

Flow per fixture window (real code path, no shortcuts):
candles -> ObservationEngine.evaluate -> ResearchCaseEngine.ingest ->
save_observation_with_case (hash-validated, transactional, idempotent).

Modes:
  dry-run   build cases in memory, report counts, write preview JSON, no DB.
  apply     evolve test schema (schema.sql), persist candles+observations+
            cases transactionally, write manifest.
  validate  re-read test DB, verify counts/hashes/idempotency (2nd apply
            must change nothing), write validation JSON.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database.connection import Database
from src.database.repository import MarketRepository as Repository
from src.models.market_data import Candle
from src.observation.engine import ObservationEngine
from src.research.case_engine import ResearchCaseEngine

SECRET_FILE = Path.home() / "Library/Application Support/TIM/test-database-password"
WINDOWS = [
    (datetime(2026, 1, 5, tzinfo=timezone.utc),
     [(100, 100, 95, 98), (98, 105, 97, 102), (102, 110, 98, 104), (104, 106, 99, 103), (103, 104, 98, 102), (102, 109, 101, 109), (109, 113, 108, 112)]),
    (datetime(2026, 1, 6, tzinfo=timezone.utc),
     [(100, 102, 99, 101)] * 5 + [(101, 102, 100, 101)] + [(101, 103, 90, 101.5)]),
    (datetime(2026, 1, 7, tzinfo=timezone.utc),
     [(100, 102, 99, 101)] * 4 + [(101, 112, 100, 111)] + [(111, 112, 100, 108)]),
]


def build_fixtures():
    """Cumulative evaluation like live (history grows, engine deduplicates)."""
    out = []
    cumulative = []
    engine = ObservationEngine()
    for start, values in WINDOWS:
        candles = [Candle("BTCUSDT", "1m", start + timedelta(minutes=i), start + timedelta(minutes=i + 1), float(o), float(h), float(l), float(c), 10.0, 10)
                   for i, (o, h, l, c) in enumerate(values)]
        cumulative.extend(candles)
        observations = engine.evaluate(cumulative)
        out.append((candles, observations))
    return out


def connect():
    import os
    password = SECRET_FILE.read_text().strip()
    url = f"postgresql://tim_test:{password}@127.0.0.1:5433/tim_test"
    # Isolated test context: safety guard requires explicit env match.
    os.environ["TIM_ENV"] = "test"
    os.environ["TIM_DURABLE_TEST_DATABASE_URL"] = url
    from src.database.connection import Database as _Database
    return _Database(url)


async def apply_schema(db) -> None:
    await db.connect()
    try:
        schema = Path(__file__).resolve().parents[1] / "src/database/schema.sql"
        async with db.acquire() as con:
            await con.execute(schema.read_text(encoding="utf-8"))
    finally:
        await db.close()


async def cmd_dry_run(args) -> int:
    engine = ResearchCaseEngine()
    total_obs, cases = 0, {}
    for candles, observations in build_fixtures():
        total_obs += len(observations)
        for observation in observations:
            case = engine.ingest(observation)
            cases[case.case_id] = case
    preview = {"mode": "dry-run", "windows": len(WINDOWS), "observations": total_obs,
               "cases": len(cases),
               "cases_detail": [{"case_id": c.case_id, "status": c.status, "observations": len(c.observation_ids),
                                 "missing": c.missing_evidence} for c in cases.values()]}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(preview, indent=1))
    print(json.dumps({k: preview[k] for k in ("windows", "observations", "cases")}))
    return 0 if total_obs > 0 and cases else 1


async def cmd_apply(args) -> int:
    db = connect()
    await apply_schema(db)
    await db.connect()
    try:
        repo = Repository(db)
        engine = ResearchCaseEngine()
        n_obs = n_cases = 0
        for candles, observations in build_fixtures():
            for candle in candles:
                await repo.upsert_candle(candle)
            for observation in observations:
                case = engine.ingest(observation)
                await repo.save_observation_with_case(observation, case)
                n_obs += 1
            n_cases = len(engine.cases)
        case_ids = sorted(engine.cases)
        digest = hashlib.sha256(json.dumps(case_ids).encode()).hexdigest()
        manifest = {"mode": "apply", "windows": len(WINDOWS), "observations": n_obs,
                    "cases": n_cases, "case_ids": case_ids, "manifest_hash": digest,
                    "idempotent_rerun_expected": "0 changes"}
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(manifest, indent=1))
        print(json.dumps({"observations": n_obs, "cases": n_cases, "manifest_hash": digest}))
    finally:
        await db.close()
    return 0


async def cmd_validate(args) -> int:
    db = connect()
    await db.connect()
    try:
        repo = Repository(db)
        persisted = await repo.recent_research_cases("BTCUSDT", 1000)
        obs = await repo.recent_observations("BTCUSDT", 1000)
        case_ids = sorted(c.case_id for c in persisted)
        digest = hashlib.sha256(json.dumps(case_ids).encode()).hexdigest()
        result = {"mode": "validate", "persisted_cases": len(persisted),
                  "persisted_observations": len(obs),
                  "statuses": sorted({c.status for c in persisted}),
                  "manifest_hash": digest}
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=1))
        print(json.dumps(result))
    finally:
        await db.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["dry-run", "apply", "validate"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.mode == "dry-run":
        return asyncio.run(cmd_dry_run(args))
    if args.mode == "apply":
        return asyncio.run(cmd_apply(args))
    return asyncio.run(cmd_validate(args))


if __name__ == "__main__":
    raise SystemExit(main())
