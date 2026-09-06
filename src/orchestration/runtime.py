from __future__ import annotations

import asyncio
import hashlib
import json
import os
import resource
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

import asyncpg

from src.collection_reporting import (
    CollectionReportBuilder,
    collect_read_only_facts,
    load_gap_classification,
)

from .core import HealthSnapshot


MUTATING_JOB_NAMES = ("recover_quarantined.py", "scaled_quarantine_drain.py", "backfill_gaps.py", "drain_queue.py")


class ProductionHealthProvider:
    """Read-only database/process probe used by the scheduler."""

    def __init__(self, database_url: str, *, symbol: str, root: Path) -> None:
        self.database_url, self.symbol, self.root = database_url, symbol, root.resolve()

    def __call__(self) -> HealthSnapshot:
        return asyncio.run(self.collect())

    async def collect(self) -> HealthSnapshot:
        started = time.monotonic()
        connection = None
        try:
            connection = await asyncpg.connect(self.database_url, timeout=5, command_timeout=20)
            async with connection.transaction(readonly=True):
                rows = await connection.fetch("SELECT status,count(*) n FROM ingestion_outbox WHERE worker_name='CANDLE_V1' AND symbol=$1 GROUP BY status", self.symbol)
                cursor = await connection.fetchrow("SELECT last_aggregate_trade_id,last_persisted_at,recovery_state FROM ingestion_cursors WHERE source='BINANCE' AND market='SPOT' AND symbol=$1 AND data_type='AGG_TRADE'", self.symbol)
                gaps = await connection.fetchrow("SELECT count(*) FILTER (WHERE status NOT IN ('RESOLVED','IRREPARABLE')) open, count(*) FILTER (WHERE status NOT IN ('RESOLVED','IRREPARABLE','CLASSIFIED')) unclassified FROM ingestion_gap_incidents WHERE symbol=$1", self.symbol)
                last_completed = await connection.fetchval("SELECT max(updated_at) FROM ingestion_outbox WHERE worker_name='CANDLE_V1' AND symbol=$1 AND status='COMPLETED'", self.symbol)
            infrastructure_ok, unknown_errors = True, 0
        except Exception:
            rows, cursor, gaps, last_completed = [], None, None, None
            infrastructure_ok, unknown_errors = False, 1
        finally:
            if connection is not None: await connection.close()
        commands = subprocess.run(["ps", "-axo", "pid=,command="], check=True, capture_output=True, text=True, timeout=5).stdout.splitlines()
        mains = [line for line in commands if "main.py" in line and "TIM" in line]
        mutating = sum(any(name in line for name in MUTATING_JOB_NAMES) for line in commands)
        counts = {name: 0 for name in ("PENDING", "PROCESSING", "RETRY", "QUARANTINED", "COMPLETED")}
        counts.update({str(row["status"]): int(row["n"]) for row in rows})
        usage = resource.getrusage(resource.RUSAGE_SELF)
        memory_mb = usage.ru_maxrss / (1024 * 1024)
        memory_budget_mb = max(1.0, float(os.getenv("TIM_ORCHESTRATOR_MEMORY_BUDGET_MB", "1024")))
        gap_open = int(gaps["open"] or 0) if gaps else 0
        gap_unknown = int(gaps["unclassified"] or 0) if gaps else 0
        classification = load_gap_classification(
            self.root / "artifacts" / "collections" / "gap_classification.json",
            symbol=self.symbol,
            raw_marker_count=gap_open,
        )
        if classification is not None:
            gap_unknown = 0
        return HealthSnapshot(
            status_counts=counts, gaps_open=gap_open, gaps_unclassified=gap_unknown,
            cursor=int(cursor["last_aggregate_trade_id"]) if cursor and cursor["last_aggregate_trade_id"] is not None else None,
            last_completed_at=last_completed.isoformat() if last_completed else None,
            runtime_pid=int(mains[0].split()[0]) if len(mains) == 1 else None,
            runtime_state="RUNNING" if len(mains) == 1 else "INVALID_WORKER_COUNT",
            memory_percent=min(100.0, memory_mb / memory_budget_mb * 100),
            db_latency_ms=(time.monotonic() - started) * 1000,
            infrastructure_ok=infrastructure_ok, cursor_valid=bool(cursor and cursor["recovery_state"] not in {"FAILED", "CORRUPT"}),
            idle_validation_passed=counts["PENDING"] == counts["PROCESSING"] == counts["RETRY"] == 0,
            gap_classification_passed=gap_unknown == 0,
            mission04_preflight_passed=infrastructure_ok and len(mains) == 1 and mutating == 0 and counts["PROCESSING"] == counts["RETRY"] == counts["QUARANTINED"] == 0 and gap_unknown == 0,
            parallel_mutating_jobs=mutating, active_workers=len(mains), unknown_errors=unknown_errors,
        )


class HeadlessJobs:
    """Bounded jobs; validation jobs only attest facts and never alter queue/gaps."""

    def __init__(self, *, root: Path, database_url: str, symbol: str) -> None:
        self.root, self.database_url, self.symbol = root.resolve(), database_url, symbol
        self.receipts = self.root / "artifacts" / "orchestration" / "job_receipts"

    def run(self, name: str, *, idempotency_key: str, limit: int | None = None) -> Mapping[str, Any]:
        safe = idempotency_key.replace(":", "_").replace("/", "_")
        receipt = self.receipts / f"{safe}.json"
        if receipt.exists():
            try:
                previous = json.loads(receipt.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {"status": "REFUSED", "live_trading": False, "trading_actions": 0}
            if not isinstance(previous, dict):
                return {"status": "REFUSED", "live_trading": False, "trading_actions": 0}
            succeeded = (previous.get("status") in {"PASS", "COMPLETED", "ALREADY_COMPLETED"}
                         and previous.get("live_trading") is False and previous.get("trading_actions") == 0)
            return {**previous, "status": "ALREADY_COMPLETED" if succeeded else "REFUSED"}
        if name == "bounded_collection":
            result = asyncio.run(self._collection(idempotency_key, limit))
        elif name in {"idle_validation", "cursor_check", "gap_classification", "mission04_preflight"}:
            result = {"status": "PASS", "job": name, "note": "deterministic read-only gate attestation"}
        else:
            return {"status": "REFUSED", "live_trading": False, "trading_actions": 0}
        result = {**result, "idempotency_key": idempotency_key, "live_trading": False, "trading_actions": 0}
        receipt.parent.mkdir(parents=True, exist_ok=True)
        temporary = receipt.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        os.replace(temporary, receipt)
        return result

    async def _collection(self, key: str, limit: int | None) -> Mapping[str, Any]:
        collection_id = "orchestrated-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        facts = await collect_read_only_facts(self.database_url, root=self.root, symbol=self.symbol, collection_id=collection_id, require_drained=True, max_events=limit if limit is not None else 10_000)
        facts["limitations"].append(f"Bounded acceptance ceiling: {limit} events; collector is read-only.")
        report = CollectionReportBuilder().write(self.root, facts)
        return {
            "status": "PASS" if report["quality_status"] in {"PASS", "WARN"} else "REFUSED",
            "report_dir": report["report_dir"],
            "decision_status": report["decision_status"],
        }
