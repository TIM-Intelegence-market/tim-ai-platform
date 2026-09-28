#!/usr/bin/env python3
"""Capture a read-only TIM V2 runtime/ingestion observability snapshot."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncpg

from config.settings import settings
from src.v2_readiness.coverage import CoverageDefinition, calculate_coverage
from src.v2_readiness.monitor import evaluate_observe_alerts


UTC = timezone.utc
FROZEN_START = datetime(2026, 7, 22, 20, 14, tzinfo=UTC)


def iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


def json_default(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(type(value).__name__)


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")
    temporary.replace(path)


def health(url: str) -> dict:
    with urlopen(url, timeout=3) as response:
        return json.loads(response.read())


async def collect(args: argparse.Namespace) -> dict:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    dashboard = await asyncio.to_thread(health, args.health_url)
    connection = await asyncpg.connect(args.database_url, timeout=10, command_timeout=60)
    transaction = connection.transaction(isolation="repeatable_read", readonly=True)
    await transaction.start()
    try:
        snapshot = str(await connection.fetchval("SELECT txid_current_snapshot()"))
        raw = dict(await connection.fetchrow(
            """
            WITH scoped AS (
              SELECT *, lag(trade_time) OVER (ORDER BY aggregate_trade_id) AS prior_time
              FROM agg_trades WHERE symbol='BTCUSDT' AND trade_time >= $1 AND trade_time < $2
            )
            SELECT count(*) AS received_events,
                   count(DISTINCT aggregate_trade_id) AS distinct_events,
                   count(*) FILTER (WHERE price<=0 OR quantity<=0 OR source<>'BINANCE_SPOT_AGGTRADE') AS invalid_events,
                   count(*) FILTER (WHERE prior_time IS NOT NULL AND trade_time<prior_time) AS out_of_order_events,
                   count(*) FILTER (WHERE ingest_timestamp+interval '5 seconds'<trade_time) AS clock_skew_rows,
                   count(*) FILTER (WHERE ingest_timestamp-trade_time>interval '5 minutes') AS very_late_events,
                   percentile_cont(0.50) WITHIN GROUP (ORDER BY extract(epoch FROM ingest_timestamp-trade_time)) AS source_to_store_p50_seconds,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM ingest_timestamp-trade_time)) AS source_to_store_p95_seconds,
                   percentile_cont(0.99) WITHIN GROUP (ORDER BY extract(epoch FROM ingest_timestamp-trade_time)) AS source_to_store_p99_seconds,
                   max(extract(epoch FROM ingest_timestamp-trade_time)) AS source_to_store_max_seconds,
                   max(trade_time) AS last_source_event_utc
            FROM scoped
            """,
            FROZEN_START,
            now,
        ))
        candle_rows = await connection.fetch(
            """SELECT DISTINCT open_time FROM candles
               WHERE symbol='BTCUSDT' AND timeframe='1m' AND closed=true
                 AND open_time >= $1 AND open_time < $2 ORDER BY open_time""",
            FROZEN_START,
            now,
        )
        invalid_candles = int(await connection.fetchval(
            """SELECT count(*) FROM candles WHERE symbol='BTCUSDT' AND timeframe='1m'
               AND open_time >= $1 AND open_time < $2
               AND (close_time<=open_time OR open<=0 OR high<=0 OR low<=0 OR close<=0 OR volume<0 OR trade_count<0)""",
            FROZEN_START,
            now,
        ))
    finally:
        await transaction.rollback()
        await connection.close()
    observed = [row["open_time"].astimezone(UTC) for row in candle_rows]
    definition = CoverageDefinition(
        metric_name="tim_closed_1m_continuous_coverage",
        metric_version="2.0.0",
        market="BINANCE_SPOT",
        instrument="BTCUSDT",
        data_type="CLOSED_1M_CANDLE_DERIVED_FROM_AGGTRADE",
        window_start_utc=FROZEN_START,
        window_end_utc=now,
    )
    coverage = calculate_coverage(definition, observed)
    latest = raw.get("last_source_event_utc")
    operational = dashboard.get("operational", {})
    alert_input = {
        "coverage": float(coverage.coverage),
        "open_p0_gaps": 0,
        "open_p1_gaps": 1 if coverage.missing_minutes else 0,
        "data_age_seconds": int((datetime.now(UTC) - latest).total_seconds()) if latest else 10**9,
        "stale_after_seconds": 180,
        "collector_status": operational.get("stream", "UNKNOWN"),
        "persistence_invalid_rows": invalid_candles + int(raw.get("invalid_events") or 0),
        "clock_skew_rows": int(raw.get("clock_skew_rows") or 0),
        "dashboard_bind": "LOOPBACK_ONLY" if settings.dashboard_host in {"127.0.0.1", "::1", "localhost"} else "UNSAFE_OR_UNKNOWN",
        "execution_active": False if dashboard.get("governance", {}).get("observe_only") is True else None,
    }
    return {
        "schema_version": "1.0.0",
        "captured_at_utc": iso(datetime.now(UTC)),
        "mode": dashboard.get("mode"),
        "database_snapshot": snapshot,
        "measurement_window": {"start_utc": iso(FROZEN_START), "end_utc": iso(now)},
        "coverage": coverage.to_dict(),
        "collector": {
            "status": operational.get("stream"),
            "runtime_started_at": operational.get("runtime_started_at"),
            "source_uptime": "NOT_INSTRUMENTED",
            "restart_count": "NOT_INSTRUMENTED",
            "recovery_status": args.recovery_status,
        },
        "ingestion": {
            **raw,
            "clock_skew_threshold_seconds": 5,
            "valid_events": int(raw.get("received_events") or 0) - int(raw.get("invalid_events") or 0),
            "expected_event_count": "NOT_DEFINED_FOR_AGGTRADE_EVENT_RATE",
            "discarded_events": "NOT_INSTRUMENTED",
            "discard_reasons": "NOT_INSTRUMENTED",
            "duplicate_attempts": "NOT_INSTRUMENTED_PRIMARY_KEY_PREVENTS_PERSISTED_DUPLICATES",
            "queue_depth": operational.get("queue_depth"),
            "queue_model": operational.get("queue_model"),
            "backpressure": "NOT_INSTRUMENTED",
            "parse_latency": "NOT_INSTRUMENTED",
            "write_latency": "NOT_INSTRUMENTED",
        },
        "persistence_invalid_rows": invalid_candles + int(raw.get("invalid_events") or 0),
        "alerts": evaluate_observe_alerts(alert_input),
        "trading_actions_emitted": 0,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--health-url", default="http://127.0.0.1:8765/api/health")
    parser.add_argument("--recovery-status", default="NOT_INDEPENDENTLY_VERIFIED")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/v2_readiness/runtime_observability_snapshot.json")
    args = parser.parse_args()
    payload = await collect(args)
    atomic_write(args.output, payload)
    print(json.dumps({"output": str(args.output), "alerts": len(payload["alerts"]), "coverage": payload["coverage"]["coverage"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
