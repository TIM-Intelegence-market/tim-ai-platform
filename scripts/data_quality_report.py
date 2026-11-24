from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.market_data import Candle, Observation, ObservationKind, Trade
from src.quality.framework import DataQualityFramework, QualityPolicy


def parse_record(row: dict):
    kind = row.get("record_type")
    value = row.get("data", row)
    if kind == "trade":
        return Trade(value["symbol"], value["price"], value["quantity"], datetime.fromisoformat(value["event_time"]), value.get("trade_id"), value.get("buyer_is_maker"))
    if kind == "candle":
        return Candle(value["symbol"], value["timeframe"], datetime.fromisoformat(value["open_time"]), datetime.fromisoformat(value["close_time"]), value["open"], value["high"], value["low"], value["close"], value["volume"], value["trade_count"], value.get("closed", True))
    if kind == "observation":
        return Observation(ObservationKind(value["kind"]), value["symbol"], value["timeframe"], datetime.fromisoformat(value["observed_at"]), value["summary"], value["confidence"], value.get("evidence", {}), source=value.get("source", "external"), provenance=value.get("provenance", ""), rule_id=value.get("rule_id", "unassigned"), input_hash=value.get("input_hash", ""))
    raise ValueError(f"Unsupported record_type: {kind!r}")


HOLDOUT_FROM = datetime.fromisoformat("2025-01-01T00:00:00+00:00")


def extra_issues(records: list, holdout_from: datetime = HOLDOUT_FROM) -> list[dict]:
    """Checks the framework does not make: records in the locked holdout period and timestamps that run backwards
    (input order). Reported as issues; nothing here changes the framework's own numbers."""
    issues: list[dict] = []
    previous = None
    for record in records:
        stamp = DataQualityFramework._timestamp(record)
        record_id = type(record).__name__
        if stamp.tzinfo is not None and stamp >= holdout_from:
            issues.append({"code": "HOLDOUT_VIOLATION", "severity": "ERROR", "record_type": record_id,
                           "detail": f"Record timestamp {stamp.isoformat()} is in the locked holdout (from {holdout_from.date()})."})
        if previous is not None and stamp.tzinfo is not None and previous.tzinfo is not None and stamp < previous:
            issues.append({"code": "TIMESTAMP_BACKWARD", "severity": "WARNING", "record_type": record_id,
                           "detail": f"Timestamp {stamp.isoformat()} is earlier than the record before it ({previous.isoformat()})."})
        previous = stamp
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a deterministic TIM data-quality report")
    parser.add_argument("input", type=Path)
    parser.add_argument("--as-of", required=True, help="Timezone-aware ISO-8601 report time")
    parser.add_argument("--output", type=Path, default=ROOT / "data/quality/latest.json")
    parser.add_argument("--freshness-seconds", type=int, default=3600)
    args = parser.parse_args()
    as_of = datetime.fromisoformat(args.as_of)
    if as_of.tzinfo is None:
        parser.error("--as-of must include a timezone")
    payload = json.loads(args.input.read_text())
    records = [parse_record(row) for row in payload.get("records", payload)]
    report = DataQualityFramework(QualityPolicy(freshness_seconds=args.freshness_seconds)).validate(records, as_of=as_of).to_dict()
    report["issues"] = list(report["issues"]) + extra_issues(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.output.write_text(encoded)
    print(encoded, end="")
    return 0 if not any(issue["severity"] == "ERROR" for issue in report["issues"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
