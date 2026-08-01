#!/usr/bin/env python3
"""Generate fixed-cutoff, read-only TIM V2 coverage and case evidence."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncpg

from config.settings import settings
from src.v2_readiness.case_audit import ValidatedCaseRecord, audit_validated_cases
from src.v2_readiness.coverage import (
    CoverageDefinition,
    audit_calculate_coverage,
    build_gap_records,
    calculate_coverage,
    rolling_coverage,
)


UTC = timezone.utc
FROZEN_START = datetime(2026, 7, 22, 20, 14, tzinfo=UTC)
FROZEN_END = datetime(2026, 7, 23, 14, 27, tzinfo=UTC)
FROZEN_CASE_CUTOFF = datetime(2026, 7, 23, 14, 27, 42, 127641, tzinfo=UTC)
ONE_MINUTE = timedelta(minutes=1)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def stable_json(value: Any) -> str:
    return json.dumps(
        value,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        default=json_default,
    ) + "\n"


def json_default(value: Any) -> str:
    """Encode database-native scalar values without losing decimal precision."""
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def compact_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=json_default,
    ).encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def safe_database_identity(url: str) -> dict[str, str | int | None]:
    parsed = urlsplit(url)
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "database": parsed.path.lstrip("/"),
    }


def definition(start: datetime, end: datetime) -> CoverageDefinition:
    return CoverageDefinition(
        metric_name="tim_closed_1m_continuous_coverage",
        metric_version="2.0.0",
        market="BINANCE_SPOT",
        instrument="BTCUSDT",
        data_type="CLOSED_1M_CANDLE_DERIVED_FROM_AGGTRADE",
        window_start_utc=start,
        window_end_utc=end,
    )


def load_downtime(
    path: Path | None,
) -> tuple[
    list[tuple[datetime, datetime]],
    list[tuple[datetime, datetime]],
    list[str],
]:
    if path is None:
        return [], [], []
    payload = json.loads(path.read_text(encoding="utf-8"))
    confirmed = []
    evidence = [path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)]
    for item in payload.get("intervals", []):
        if item.get("root_cause_status") == "CONFIRMED":
            confirmed.append((parse_time(item["start_utc"]), parse_time(item["end_utc"])))
    probable = []
    scope = payload.get("scope", {})
    if payload.get("final_disposition", {}).get("all_ranges_have_supported_technical_cause_class"):
        probable.append(
            (
                parse_time(scope["start_inclusive_utc"]),
                parse_time(scope["end_exclusive_utc"]),
            )
        )
    return confirmed, probable, evidence


def daily_partitions(
    metric: CoverageDefinition, observed: set[datetime]
) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    cursor = metric.window_start_utc
    while cursor < metric.window_end_utc:
        next_day = datetime.combine(
            cursor.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC
        )
        end = min(next_day, metric.window_end_utc)
        expected = int((end - cursor) / ONE_MINUTE)
        present = sum(1 for item in observed if cursor <= item < end)
        values.append(
            {
                "utc_date": cursor.date().isoformat(),
                "start_utc": iso(cursor),
                "end_utc": iso(end),
                "expected": expected,
                "observed": present,
                "missing": expected - present,
                "coverage": round(present / expected, 6) if expected else 0.0,
            }
        )
        cursor = end
    return values


def overlaps_gap(
    start: datetime,
    end: datetime,
    gap_intervals: list[tuple[datetime, datetime]],
) -> bool:
    return any(start < gap_end and gap_start < end for gap_start, gap_end in gap_intervals)


def case_record(
    row: asyncpg.Record,
    cases: dict[str, asyncpg.Record],
    gap_intervals: list[tuple[datetime, datetime]],
) -> ValidatedCaseRecord:
    observation_id = str(row["observation_id"])
    case_id = "ofcase_" + hashlib.sha256(observation_id.encode("utf-8")).hexdigest()[:20]
    case = cases.get(case_id)
    horizons = json_value(row["horizons"], [])
    horizon_minutes = tuple(
        sorted(
            {
                int(item["minutes"])
                for item in horizons
                if isinstance(item, dict) and str(item.get("minutes", "")).isdigit()
            }
        )
    )
    evidence = json_value(row["evidence"], [])
    provenance_complete = bool(
        row["provenance"] == "BINANCE_SPOT_AGGTRADE_DETERMINISTIC"
        and row["input_hash"]
        and isinstance(evidence, list)
        and len(evidence) >= 2
    )
    observed_at = row["observed_at"].astimezone(UTC)
    validated_through = row["validated_through"].astimezone(UTC)
    return ValidatedCaseRecord(
        observation_id=observation_id,
        observed_at=observed_at,
        validated_through=validated_through,
        kind=str(row["kind"]),
        outcome=str(row["outcome"]),
        input_hash=str(row["input_hash"]),
        horizon_minutes=horizon_minutes,
        source_gap_overlap=overlaps_gap(
            observed_at - timedelta(minutes=2), validated_through, gap_intervals
        ),
        case_present=case is not None,
        case_closed=case is not None and case["status"] == "CLOSED",
        case_outcome_matches=case is not None and case["outcome"] == row["outcome"],
        provenance_complete=provenance_complete,
    )


async def collect(args: argparse.Namespace) -> dict[str, Any]:
    start = parse_time(args.start)
    end = parse_time(args.end)
    metric = definition(start, end)
    downtime, probable_downtime, downtime_refs = load_downtime(args.downtime_evidence)
    connection = await asyncpg.connect(args.database_url, timeout=10, command_timeout=120)
    transaction = connection.transaction(isolation="repeatable_read", readonly=True)
    await transaction.start()
    try:
        snapshot = str(await connection.fetchval("SELECT txid_current_snapshot()"))
        database_version = str(await connection.fetchval("SELECT version()"))
        candle_rows = await connection.fetch(
            """
            SELECT open_time
            FROM candles
            WHERE symbol=$1 AND timeframe='1m' AND closed=true
              AND open_time >= $2 AND open_time < $3
            ORDER BY open_time
            """,
            metric.instrument,
            start,
            end,
        )
        observed = [row["open_time"].astimezone(UTC) for row in candle_rows]
        raw_rows = await connection.fetch(
            """
            SELECT DISTINCT date_trunc('minute', trade_time) AS minute
            FROM agg_trades
            WHERE symbol=$1 AND trade_time >= $2 AND trade_time < $3
            ORDER BY minute
            """,
            metric.instrument,
            start,
            end,
        )
        raw_minutes = [row["minute"].astimezone(UTC) for row in raw_rows]
        quality = dict(
            await connection.fetchrow(
                """
                SELECT count(*) AS total_rows,
                       count(DISTINCT open_time) AS distinct_open_times,
                       count(*) FILTER (
                         WHERE close_time <= open_time OR open <= 0 OR high <= 0
                            OR low <= 0 OR close <= 0 OR volume < 0 OR trade_count < 0
                            OR high < GREATEST(open, close) OR low > LEAST(open, close)
                       ) AS invalid_rows,
                       count(*) FILTER (WHERE closed=false) AS non_closed_rows
                FROM candles
                WHERE symbol=$1 AND timeframe='1m'
                  AND open_time >= $2 AND open_time < $3
                """,
                metric.instrument,
                start,
                end,
            )
        )
        raw_quality = dict(
            await connection.fetchrow(
                """
                SELECT count(*) AS rows,
                       count(DISTINCT aggregate_trade_id) AS distinct_ids,
                       min(aggregate_trade_id) AS min_id,
                       max(aggregate_trade_id) AS max_id,
                       min(trade_time) AS first_time,
                       max(trade_time) AS last_time,
                       count(*) FILTER (
                         WHERE price <= 0 OR quantity <= 0
                            OR source <> 'BINANCE_SPOT_AGGTRADE'
                       ) AS invalid_rows,
                       count(*) FILTER (WHERE ingest_timestamp < trade_time) AS clock_skew_rows,
                       count(*) FILTER (
                         WHERE ingest_timestamp - trade_time > interval '5 minutes'
                       ) AS over_five_minute_lag_rows,
                       max(extract(epoch FROM ingest_timestamp-trade_time)) AS max_lag_seconds
                FROM agg_trades
                WHERE symbol=$1 AND trade_time >= $2 AND trade_time < $3
                """,
                metric.instrument,
                start,
                end,
            )
        )
        sequence_rows = await connection.fetch(
            """
            WITH ordered AS (
              SELECT aggregate_trade_id, trade_time,
                     lag(aggregate_trade_id) OVER (ORDER BY aggregate_trade_id) AS prior_id,
                     lag(trade_time) OVER (ORDER BY aggregate_trade_id) AS prior_time
              FROM agg_trades
              WHERE symbol=$1 AND trade_time >= $2 AND trade_time < $3
            )
            SELECT prior_id, aggregate_trade_id, prior_time, trade_time,
                   aggregate_trade_id-prior_id-1 AS missing_ids
            FROM ordered
            WHERE aggregate_trade_id > prior_id + 1
            ORDER BY aggregate_trade_id
            """,
            metric.instrument,
            start,
            end,
        )
        gap_intervals = [
            (row["prior_time"].astimezone(UTC), row["trade_time"].astimezone(UTC))
            for row in sequence_rows
        ]
        validation_rows = await connection.fetch(
            """
            SELECT v.observation_id,v.observed_at,v.validated_through,v.complete,
                   v.outcome,v.horizons,o.kind,o.input_hash,o.evidence,o.provenance
            FROM orderflow_validations v
            JOIN orderflow_observations o USING (observation_id)
            WHERE v.complete=true AND v.validated_through <= $1
            ORDER BY v.validated_through,v.observation_id
            """,
            end,
        )
        case_rows = await connection.fetch(
            """
            SELECT case_id,status,outcome
            FROM research_cases
            WHERE case_id LIKE 'ofcase_%' AND updated_at <= $1
            """,
            end,
        )
        cases = {str(row["case_id"]): row for row in case_rows}
        records = [case_record(row, cases, gap_intervals) for row in validation_rows]
    finally:
        await transaction.rollback()
        await connection.close()

    product = calculate_coverage(metric, observed)
    audit = audit_calculate_coverage(metric, observed)
    if (
        product.coverage != audit.coverage
        or product.missing_minutes != audit.missing_minutes
        or product.valid_observations != audit.valid_observations
    ):
        raise RuntimeError("product and independent audit coverage calculations differ")

    frozen_metric = definition(FROZEN_START, FROZEN_END)
    frozen_observed = [item for item in observed if item < FROZEN_END]
    frozen_product = calculate_coverage(frozen_metric, frozen_observed)
    frozen_audit = audit_calculate_coverage(frozen_metric, frozen_observed)

    evidence_refs = [
        "PostgreSQL repeatable-read snapshot " + snapshot,
        "docs/v2_readiness/data_coverage_methodology.md",
        *downtime_refs,
    ]
    gap_records = build_gap_records(
        metric,
        product.missing_minutes,
        raw_minutes=raw_minutes,
        confirmed_downtime=downtime,
        probable_downtime=probable_downtime,
        evidence_refs=evidence_refs,
    )
    observed_set = set(observed)
    raw_set = set(raw_minutes)
    e2e = observed_set & raw_set
    raw_expected_ids = (
        int(raw_quality["max_id"] - raw_quality["min_id"] + 1)
        if raw_quality.get("min_id") is not None
        else 0
    )
    raw_distinct_ids = int(raw_quality.get("distinct_ids") or 0)
    data_manifest = {
        "snapshot": snapshot,
        "database": safe_database_identity(args.database_url),
        "coverage_window": {"start_utc": iso(start), "end_utc": iso(end)},
        "candle_quality": quality,
        "raw_quality": {
            **raw_quality,
            "first_time": iso(raw_quality["first_time"]) if raw_quality.get("first_time") else None,
            "last_time": iso(raw_quality["last_time"]) if raw_quality.get("last_time") else None,
        },
        "raw_sequence_gap_ranges": len(sequence_rows),
        "raw_sequence_missing_ids": sum(int(row["missing_ids"]) for row in sequence_rows),
        "case_rows": len(records),
    }
    data_manifest_hash = hashlib.sha256(compact_json(data_manifest)).hexdigest()
    code_hash = sha256(ROOT / "src/v2_readiness/coverage.py")
    definition_payload = metric.to_dict()
    definition_payload.update(
        {
            "authoritative_source": "TIM_COVERAGE_VALIDATION.md and TIM_V2_READINESS_CHECKLIST.md",
            "rounding_rule": "DECIMAL_HALF_EVEN_3DP_FOR_DISPLAY",
            "timezone": "UTC",
            "duplicates": "EXCLUDED",
            "synthetic_data": "PROHIBITED_AND_EXCLUDED",
            "forward_fill": "PROHIBITED",
            "backfill_rule": "SEPARATELY_VERSIONED_AUTHORITATIVE_AGGTRADE_ONLY; GOVERNANCE_REVIEW_REQUIRED BEFORE READINESS USE",
            "calculation_code_hash": code_hash,
            "data_manifest_hash": data_manifest_hash,
            "frozen_published_window": frozen_metric.to_dict(),
            "valid_observations": product.valid_observations,
            "duplicates_excluded": product.duplicates_excluded,
            "synthetic_observations": product.synthetic_observations,
            "invalid_observations": product.invalid_observations,
            "missing_observations": len(product.missing_minutes),
            "coverage": float(product.coverage),
            "coverage_percent": product.to_dict()["coverage_percent"],
            "gate_status": product.status,
        }
    )
    coverage_payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "generated_at_utc": iso(datetime.now(UTC)),
        "evidence_cutoff_utc": iso(end),
        "database_snapshot": snapshot,
        "database_version": database_version,
        "mode": "OBSERVE",
        "product_calculation": product.to_dict(),
        "independent_audit_calculation": audit.to_dict(),
        "audit_tolerance": 0.0,
        "audit_agreement": True,
        "frozen_published_reproduction": {
            "product": frozen_product.to_dict(),
            "audit": frozen_audit.to_dict(),
            "expected_published_percent": "60.659",
            "reproduced": frozen_product.to_dict()["coverage_percent"] == "60.659",
        },
        "dimensions": {
            "temporal": product.to_dict(),
            "date_partitions": daily_partitions(metric, observed_set),
            "event_sequence": {
                "expected_aggregate_trade_ids_between_bounds": raw_expected_ids,
                "distinct_persisted_aggregate_trade_ids": raw_distinct_ids,
                "missing_aggregate_trade_ids": max(0, raw_expected_ids - raw_distinct_ids),
                "gap_ranges": len(sequence_rows),
                "coverage": round(raw_distinct_ids / raw_expected_ids, 6) if raw_expected_ids else 0.0,
            },
            "schema_validated": {
                "valid_closed_candles": int(quality["total_rows"]) - int(quality["invalid_rows"]),
                "invalid_candles": int(quality["invalid_rows"]),
                "coverage": round((int(quality["total_rows"]) - int(quality["invalid_rows"])) / metric.expected_observations, 6),
            },
            "field_completeness": {
                "candle_invalid_rows": int(quality["invalid_rows"]),
                "raw_invalid_rows": int(raw_quality["invalid_rows"]),
                "raw_clock_skew_rows": int(raw_quality["clock_skew_rows"]),
            },
            "source_availability": {
                "minutes_with_persisted_aggtrades": len(raw_set),
                "expected_minutes": metric.expected_observations,
                "coverage": round(len(raw_set) / metric.expected_observations, 6),
            },
            "persistence": {
                "distinct_closed_candle_minutes": len(observed_set),
                "duplicates": int(quality["total_rows"]) - int(quality["distinct_open_times"]),
                "coverage": float(product.coverage),
            },
            "end_to_end": {
                "candle_minutes_with_raw_aggtrade_evidence": len(e2e),
                "expected_minutes": metric.expected_observations,
                "coverage": round(len(e2e) / metric.expected_observations, 6),
            },
            "rolling": rolling_coverage(
                metric,
                observed,
                [timedelta(hours=1), timedelta(hours=24), timedelta(days=7)],
            ),
        },
        "data_manifest": data_manifest,
        "data_manifest_hash": data_manifest_hash,
        "calculation_code_hash": code_hash,
        "gap_summary": {
            "ranges": len(gap_records),
            "missing_minutes": len(product.missing_minutes),
            "severity": dict(sorted(Counter(str(item["severity"]) for item in gap_records).items())),
            "root_cause_class": dict(sorted(Counter(str(item["root_cause_class"]) for item in gap_records).items())),
            "root_cause_status": dict(sorted(Counter(str(item["root_cause_status"]) for item in gap_records).items())),
        },
        "gate_status": product.status,
        "v2_approved": False,
        "trading_approved": False,
    }

    frozen_cases = [item for item in records if item.validated_through <= FROZEN_CASE_CUTOFF]
    case_payload = {
        "schema_version": "1.0.0",
        "generated_at_utc": coverage_payload["generated_at_utc"],
        "mode": "OBSERVE",
        "frozen_snapshot_cutoff_utc": iso(FROZEN_CASE_CUTOFF),
        "frozen_published_count": 1339,
        "frozen_cutoff_audit": audit_validated_cases(frozen_cases),
        "current_cutoff_utc": iso(end),
        "current_cutoff_audit": audit_validated_cases(records),
        "regime_analysis_status": "DESCRIPTIVE_ONLY_NOT_PRE_REGISTERED",
        "market_regime_labels": "ABSENT",
        "volatility_regime_labels": "ABSENT",
        "liquidity_regime_labels": "ABSENT",
        "manual_review_status": "PENDING",
        "gate_status": "FAIL",
        "gate_reason": "The frozen 1,339-case evidence and current evidence do not contain 1,000 strict non-overlapping 30-minute quality-screened windows; reviewer and inter-rater evidence are absent.",
        "v2_approved": False,
    }
    case_payload["artifact_hash"] = hashlib.sha256(compact_json(case_payload)).hexdigest()
    return {
        "definition": definition_payload,
        "coverage": coverage_payload,
        "gaps": gap_records,
        "cases": case_payload,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="UTC start, inclusive")
    parser.add_argument("--end", required=True, help="UTC end, exclusive")
    parser.add_argument("--label", choices=("baseline", "final"), default="baseline")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/v2_readiness")
    parser.add_argument("--downtime-evidence", type=Path)
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    result = await collect(args)
    if not args.no_write:
        atomic_write(args.output_dir / "coverage_definition.json", stable_json(result["definition"]))
        atomic_write(args.output_dir / f"coverage_{args.label}.json", stable_json(result["coverage"]))
        atomic_write(
            args.output_dir / "data_gap_ledger.jsonl",
            "".join(
                json.dumps(
                    item,
                    sort_keys=True,
                    ensure_ascii=False,
                    default=json_default,
                )
                + "\n"
                for item in result["gaps"]
            ),
        )
        atomic_write(args.output_dir / "validated_case_audit.json", stable_json(result["cases"]))
    summary = {
        "label": args.label,
        "coverage": result["coverage"]["product_calculation"]["coverage"],
        "audit_agreement": result["coverage"]["audit_agreement"],
        "gap_ranges": len(result["gaps"]),
        "frozen_case_gate": result["cases"]["frozen_cutoff_audit"]["gate_status"],
        "current_case_gate": result["cases"]["current_cutoff_audit"]["gate_status"],
        "output_dir": str(args.output_dir),
    }
    print(stable_json(summary), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
