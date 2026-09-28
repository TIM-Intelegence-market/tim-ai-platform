#!/usr/bin/env python3
"""Run a deterministic, read-only stratified orderflow replay at a fixed cut-off."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncpg

from config.settings import settings
from src.models.market_data import Trade
from src.orderflow.metrics import OrderflowMetricsEngine
from src.orderflow.observations import OrderflowObservationEngine
from src.orderflow.validation import OrderflowValidationEngine


UTC = timezone.utc


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("cut-off must be timezone-aware")
    return parsed.astimezone(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def trade(row: asyncpg.Record) -> Trade:
    return Trade(
        str(row["symbol"]),
        float(row["price"]),
        float(row["quantity"]),
        row["trade_time"].astimezone(UTC),
        int(row["aggregate_trade_id"]),
        bool(row["buyer_is_maker"]),
    )


def contiguous(values: list[Trade]) -> bool:
    ids = sorted({int(item.trade_id) for item in values if item.trade_id is not None})
    return bool(ids) and all(right == left + 1 for left, right in zip(ids, ids[1:]))


async def candidates(connection: asyncpg.Connection, cutoff: datetime) -> list[asyncpg.Record]:
    return list(await connection.fetch(
        """
        WITH ranked AS (
          SELECT o.observation_id,o.kind,o.symbol,o.observed_at,o.input_hash,
                 v.outcome,v.validation_hash,v.validated_through,
                 row_number() OVER (
                   PARTITION BY o.kind,v.outcome
                   ORDER BY o.observation_id
                 ) AS rank_in_stratum
          FROM orderflow_observations o
          JOIN orderflow_validations v USING(observation_id)
          WHERE v.complete=true AND v.validated_through <= $1
            AND v.outcome IS NOT NULL
            AND v.horizons @> '[{"minutes":5},{"minutes":15},{"minutes":30}]'::jsonb
        )
        SELECT * FROM ranked WHERE rank_in_stratum <= 25
        ORDER BY kind,outcome,rank_in_stratum
        """,
        cutoff,
    ))


async def replay_candidate(connection: asyncpg.Connection, row: asyncpg.Record) -> dict[str, Any] | None:
    observed_at = row["observed_at"].astimezone(UTC)
    metric_rows = await connection.fetch(
        """SELECT symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker
           FROM agg_trades WHERE symbol=$1 AND trade_time >= $2 AND trade_time < $3
           ORDER BY trade_time,aggregate_trade_id""",
        row["symbol"], observed_at - timedelta(minutes=2), observed_at,
    )
    outcome_rows = await connection.fetch(
        """(SELECT symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker
             FROM agg_trades WHERE symbol=$1 AND trade_time <= $2
             ORDER BY trade_time DESC,aggregate_trade_id DESC LIMIT 1)
           UNION ALL
           (SELECT symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker
             FROM agg_trades WHERE symbol=$1 AND trade_time > $2 AND trade_time <= $3
             ORDER BY trade_time,aggregate_trade_id)""",
        row["symbol"], observed_at, observed_at + timedelta(minutes=30),
    )
    metric_trades = [trade(item) for item in metric_rows]
    outcome_trades = [trade(item) for item in outcome_rows]
    if not contiguous(metric_trades + outcome_trades):
        return None
    metrics = OrderflowMetricsEngine().series(
        metric_trades,
        observed_at - timedelta(minutes=2),
        observed_at,
        60,
        symbol=str(row["symbol"]),
    )
    if len(metrics) != 2:
        return None
    observations = OrderflowObservationEngine().evaluate(metrics[0], metrics[1])
    match = next((item for item in observations if item.observation_id == row["observation_id"]), None)
    if match is None:
        return None
    reverse_metrics = OrderflowMetricsEngine().series(
        list(reversed(metric_trades)),
        observed_at - timedelta(minutes=2),
        observed_at,
        60,
        symbol=str(row["symbol"]),
    )
    reverse_observations = OrderflowObservationEngine().evaluate(reverse_metrics[0], reverse_metrics[1])
    observation_replay_equal = observations == reverse_observations
    validation_input = {
        "observation_id": match.observation_id,
        "symbol": match.symbol,
        "observed_at": match.observed_at.isoformat(),
        "input_hash": match.input_hash,
    }
    engine = OrderflowValidationEngine()
    validation = engine.validate(validation_input, outcome_trades, observed_at + timedelta(minutes=30))
    reverse_validation = engine.validate(validation_input, list(reversed(outcome_trades)), observed_at + timedelta(minutes=30))
    pre_cutoff = engine.validate(validation_input, outcome_trades, observed_at + timedelta(minutes=29))
    if validation is None:
        return None
    result = {
        "observation_id": match.observation_id,
        "kind": match.kind,
        "outcome": validation.outcome,
        "observed_at_utc": iso(observed_at),
        "input_hash_expected": str(row["input_hash"]),
        "input_hash_replayed": match.input_hash,
        "validation_hash_expected": str(row["validation_hash"]),
        "validation_hash_replayed": validation.validation_hash,
        "observation_replay_equal_under_reversed_input": observation_replay_equal,
        "validation_replay_equal_under_reversed_input": validation == reverse_validation,
        "pre_30m_cutoff_complete": bool(pre_cutoff and pre_cutoff.complete),
        "source_sequence_contiguous": True,
        "mode": match.mode,
    }
    result["pass"] = all((
        result["input_hash_expected"] == result["input_hash_replayed"],
        result["validation_hash_expected"] == result["validation_hash_replayed"],
        result["outcome"] == row["outcome"],
        result["observation_replay_equal_under_reversed_input"],
        result["validation_replay_equal_under_reversed_input"],
        not result["pre_30m_cutoff_complete"],
        result["mode"] == "OBSERVE",
    ))
    return result if result["pass"] else None


async def collect(args: argparse.Namespace) -> dict[str, Any]:
    cutoff = parse_time(args.cutoff)
    connection = await asyncpg.connect(args.database_url, timeout=10, command_timeout=120)
    transaction = connection.transaction(isolation="repeatable_read", readonly=True)
    await transaction.start()
    try:
        snapshot = str(await connection.fetchval("SELECT txid_current_snapshot()"))
        selected: dict[tuple[str, str], dict[str, Any]] = {}
        for row in await candidates(connection, cutoff):
            key = (str(row["kind"]), str(row["outcome"]))
            if key in selected:
                continue
            result = await replay_candidate(connection, row)
            if result is not None:
                selected[key] = result
    finally:
        await transaction.rollback()
        await connection.close()
    results = [selected[key] for key in sorted(selected)]
    expected_strata = 24
    deterministic = {
        "cutoff_utc": iso(cutoff),
        "selection_rule": "LEXICOGRAPHIC_FIRST_PASSING_QUALITY_CASE_PER_KIND_OUTCOME_FROM_FIRST_25",
        "expected_strata": expected_strata,
        "selected_strata": len(results),
        "results": results,
    }
    replay_hash = canonical_hash(deterministic)
    return {
        "schema_version": "1.0.0",
        "mode": "OBSERVE",
        "database_snapshot": snapshot,
        **deterministic,
        "replay_hash": replay_hash,
        "gate_status": "PASS" if len(results) == expected_strata and all(item["pass"] for item in results) else "FAIL",
        "trading_actions_emitted": 0,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = await collect(args)
    atomic_write(args.output, payload)
    print(json.dumps({"gate_status": payload["gate_status"], "selected_strata": payload["selected_strata"], "replay_hash": payload["replay_hash"], "output": str(args.output)}, sort_keys=True))
    return 0 if payload["gate_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
