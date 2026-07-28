#!/usr/bin/env python3
"""Read-only deterministic TIM v1 pipeline audit.

The fixture is explicitly audit-only. It is never written to TIM's database and
is never represented as live-market evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_ingestion.aggregator import CandleAggregator
from src.data_ingestion.binance_ws import BinanceTradeStream
from src.orderflow.metrics import OrderflowMetricsEngine
from src.orderflow.observations import OrderflowObservationEngine, OrderflowResearchCaseEngine
from src.orderflow.validation import OrderflowValidationEngine


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def raw_trade(trade_id: int, at: datetime, price: str, qty: str, maker: bool) -> str:
    return json.dumps(
        {"e": "aggTrade", "s": "BTCUSDT", "a": trade_id, "p": price, "q": qty, "T": int(at.timestamp() * 1000), "m": maker},
        separators=(",", ":"),
    )


def run_once(run_id: str) -> dict:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    specs = [
        (1, 5, "100.0", "1.0", False),
        (2, 20, "100.2", "1.0", True),
        (3, 65, "100.3", "3.0", False),
        (4, 70, "100.4", "3.0", False),
        (5, 80, "100.1", "0.5", True),
        (6, 370, "101.0", "1.0", False),
        (7, 970, "99.0", "2.0", True),
        (8, 1870, "102.0", "1.0", False),
    ]
    raw = [raw_trade(i, start + timedelta(seconds=sec), price, qty, maker) for i, sec, price, qty, maker in specs]
    trades = [BinanceTradeStream.parse_message(item) for item in raw]

    aggregator = CandleAggregator(("1m", "5m"))
    candles = []
    for trade in trades:
        candles.extend(aggregator.add_trade(trade))
    candle_rows = [
        {
            "symbol": item.symbol, "timeframe": item.timeframe,
            "open_time": item.open_time.isoformat(), "close_time": item.close_time.isoformat(),
            "open": item.open, "high": item.high, "low": item.low, "close": item.close,
            "volume": item.volume, "trade_count": item.trade_count, "closed": item.closed,
        }
        for item in candles
    ]

    metrics = OrderflowMetricsEngine()
    previous = metrics.calculate(trades, start, start + timedelta(minutes=1), opening_cvd=Decimal("0"), symbol="BTCUSDT")
    current = metrics.calculate(trades, start + timedelta(minutes=1), start + timedelta(minutes=2), opening_cvd=previous.cumulative_delta, symbol="BTCUSDT")
    observations = OrderflowObservationEngine().evaluate(previous, current)
    observation_rows = [item.to_dict() for item in observations]
    cases = [OrderflowResearchCaseEngine().create(item).to_dict() for item in observations]
    validations = []
    validator = OrderflowValidationEngine()
    for observation in observation_rows:
        result = validator.validate(observation, trades, start + timedelta(minutes=32))
        validations.append(result.to_dict() if result else None)

    inputs = {"raw_messages": raw}
    outputs = {
        "candles": candle_rows,
        "metrics": [previous.to_dict(), current.to_dict()],
        "observations": observation_rows,
        "cases": cases,
        "validations": validations,
    }
    return {
        "run_id": run_id,
        "input_hash": sha(inputs),
        "dataset_hash": sha(raw),
        "output_hash": sha(outputs),
        "replay_hash": sha({"inputs": inputs, "outputs": outputs}),
        "stage_hashes": {key: sha(value) for key, value in outputs.items()},
        "counts": {key: len(value) for key, value in outputs.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    if args.runs < 10:
        raise SystemExit("At least ten runs are required")
    rows = [run_once(f"TIM-V1-AUDIT-{index + 1:02d}") for index in range(args.runs)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    fields = ("input_hash", "dataset_hash", "output_hash", "replay_hash")
    stable = {field: len({row[field] for row in rows}) == 1 for field in fields}
    result = {
        "status": "PASS" if all(stable.values()) else "FAIL",
        "runs": len(rows),
        "stable": stable,
        "hashes": {field: rows[0][field] for field in fields},
        "stage_hashes": rows[0]["stage_hashes"],
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "fixture_classification": "TEST_ONLY_DETERMINISTIC_FIXTURE_NOT_MARKET_EVIDENCE",
    }
    args.summary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
