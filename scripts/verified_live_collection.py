"""Explicit Mission-06 entrypoint: gate, ONE bounded collection, stop, audit.

Production PostgreSQL is accessed only through the read-only audit snapshot.
All new writes belong to a separately named collection journal/artifact folder.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.audit_collection_accounting import snapshot
from src.collection_reporting.verified import (
    LEGACY_WARNING, SOURCE, VerifiedJournal, bounded_live_gate, build_verified_report, digest, utc,
)
from src.collection_reporting.verified_runtime import PUBLIC_ENDPOINT, consume_bounded
from src.data_ingestion.durable import cursor_hash
from src.bugfixer.readiness import evaluate_readiness


def code_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
        "src/collection_reporting/verified.py", "src/collection_reporting/verified_runtime.py",
        "src/data_ingestion/aggregator.py", "scripts/verified_live_collection.py")}


def runtime():
    text = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/com.tim.runtime"],
        check=True, capture_output=True, text=True, timeout=5).stdout
    pid = int(re.search(r"\bpid = (\d+)", text).group(1))
    runs = int(re.search(r"\bruns = (\d+)", text).group(1))
    processes = subprocess.run(["ps", "-axo", "pid=,command="], check=True,
                              capture_output=True, text=True, timeout=5).stdout.splitlines()
    mains = [line for line in processes if "main.py" in line and "TIM" in line]
    jobs = [line for line in processes if any(s in line for s in
        ("recover_quarantined.py", "scaled_quarantine_drain.py", "backfill_gaps.py", "drain_queue.py"))]
    usage = subprocess.run(["ps", "-p", str(pid), "-o", "%cpu=,rss="], check=True,
                           capture_output=True, text=True, timeout=5).stdout.split()
    with (ROOT / "data/operational/queue.jsonl").open("rb") as handle:
        handle.seek(max(0, os.fstat(handle.fileno()).st_size - 65536))
        lines = handle.read().splitlines()
    latest = json.loads(lines[-1])
    observe_only = (latest.get("mode") == "OBSERVE" and latest.get("trading_actions") == 0
                    and (datetime.now(timezone.utc) - datetime.fromisoformat(latest["timestamp"])).total_seconds() < 120)
    return {"pid": pid, "runs": runs, "running": "state = running" in text and len(mains) == 1 and not jobs,
            "legacy_stream_disabled": "TIM_BINANCE_WS_URL => ws://127.0.0.1:1" in text,
            "observe_only": observe_only,
            "resources_ok": float(usage[0]) < 75 and int(usage[1]) < 1024 * 1024}


def cursor_valid(data):
    keys = ("symbol", "last_aggregate_trade_id", "last_event_time", "last_trade_time", "last_persisted_at", "recovery_state")
    return bool(data["cursors"]) and all(cursor_hash(**{key: c[key] for key in keys}) == c["cursor_hash"]
                                        and c["cursor_version"] == 1 for c in data["cursors"])


def queue_clean(data):
    return all(row["status"] == "COMPLETED" or row["n"] == 0 for row in data["outbox"])


def write_new(path: Path, value):
    payload = json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def legacy_evidence(data, old):
    m = data["metrics"]
    total = sum(row["n"] for row in data["coverage"])
    completed = sum(row["completed"] for row in data["coverage"])
    return {"classification": "LEGACY_UNVERIFIED_INGRESS", "status": "INCOMPLETE",
        "raw_trades_total": total, "durable_completed": completed,
        "duplicates": int(m["duplicate_total"]), "capacity_rejections": int(m["reject_reason:OUTBOX_CAPACITY"]),
        "unproven_ingress_count": total,
        "unproven_ingress_count_definition": "Persisted legacy raw events without full collection receipt lineage; NOT a count of unknown message occurrences.",
        "unknown_message_occurrences": None, "unproven_worker_completion_count": total - completed,
        "evidence_start": old["started_at"], "evidence_end": old["ended_at"],
        "scope": {"symbol": "BTCUSDT", "event_ids": old["expected_period"]},
        "reason": "No prospective collection contract, receipt journal or equivalent historical collection baseline exists.",
        "impact": "Legacy historical analyses remain usable with LEGACY_EVIDENCE_INCOMPLETE; not proof of historical ingress or completion. Does not block independent verified collections.",
        "remediation_possible": "NO", "gaps": data["gaps"],
        "source_evidence": "Mission-04 immutable report plus current read-only PostgreSQL snapshot"}


async def run(args):
    # Refuse before any historical/full-database audit or network collection.
    current = runtime()
    readiness = evaluate_readiness(getattr(args, 'readiness_manifest', None), repo_root=ROOT,
        runtime_id=f"{current['pid']}:{current['runs']}")
    if readiness['live_data_release_allowed'] is not True:
        print(json.dumps(readiness, sort_keys=True), flush=True)
        return readiness
    root = ROOT / "artifacts/verified_collections"
    root.mkdir(parents=True, exist_ok=True)
    lock = (root / "collector.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        proof = json.loads(args.test_proof.read_text())
        tested = (proof.get("passed", 0) >= 16 and proof.get("failures") == 0
                  and proof.get("code_sha256") == code_hashes())
        if not tested:
            raise RuntimeError("current source files require a passing, hash-bound test proof")
        old_path = ROOT / "artifacts/collections/orchestrated-d45357132c0ef6037a77/collection_result.json"
        old = json.loads(old_path.read_text())
        orchestrator_path = ROOT / "artifacts/orchestration/state.json"
        orchestrator_hash = hashlib.sha256(orchestrator_path.read_bytes()).hexdigest()
        old_hash = hashlib.sha256(old_path.read_bytes()).hexdigest()
        first, last = old["expected_period"]["first_trade_id"], old["expected_period"]["last_trade_id"]
        rt = runtime()
        before = await snapshot(first, last)
        rt_again = runtime()
        legacy = legacy_evidence(before, old)
        legacy_path = ROOT / "artifacts/collections/legacy_evidence_status.json"
        if legacy_path.exists():
            if json.loads(legacy_path.read_text()) != json.loads(json.dumps(legacy, default=str)):
                raise RuntimeError("legacy evidence changed; refusing to overwrite historical sidecar")
        else:
            write_new(legacy_path, legacy)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        collection_id = f"verified-btcusdt-{stamp}"
        folder = root / collection_id
        contract = {"collection_id": collection_id, "source": SOURCE, "symbol": "BTCUSDT",
            "max_events": args.max_events, "max_duration_seconds": args.duration,
            "boundary": "first N application-delivered WebSocket frames; close earlier at duration budget",
            "source_endpoint": PUBLIC_ENDPOINT, "created_at": utc(),
            "trading_actions": 0, "live_trading": False,
            "code_sha256": code_hashes(), "legacy_evidence_hash": digest(legacy),
            "automatic_stops": ["MAX_EVENTS", "DURATION", "SOURCE_IDLE_TIMEOUT", "SOURCE_LAG_EXCEEDED",
                "REJECTED_FRAME", "INTRA_COLLECTION_GAP", "PROCESSOR_FAILURE", "RUNTIME_SAFETY_CHANGED", "UNKNOWN_RECEIPT"],
            "network_reconnect_allowed": False,
            "processing_scope": "COLLECTION_CANDLE_V1; native TIM CandleAggregator; no downstream trading intelligence"}
        journal = VerifiedJournal(folder / "journal.sqlite3", contract)
        gate = bounded_live_gate({"runtime_stable": rt["running"] and rt_again["running"] and rt["pid"] == rt_again["pid"] and rt["runs"] == rt_again["runs"] and rt_again["resources_ok"],
            "queue_clean": queue_clean(before), "cursor_valid": cursor_valid(before),
            "journal_active": journal.db.execute("PRAGMA synchronous").fetchone()[0] == 2 and journal.get("state") == "PREPARED",
            "hard_boundary_active": 1 <= args.max_events <= 10000 and 1 <= args.duration <= 300,
            "automatic_stops_active": True, "tests_passed": tested, "trading_disabled": rt_again["observe_only"],
            "legacy_stream_disabled": rt_again["legacy_stream_disabled"], "single_collector": True,
            "repair_readiness_passed": evaluate_readiness(args.readiness_manifest, repo_root=ROOT,
                runtime_id=f"{rt_again['pid']}:{rt_again['runs']}")['live_data_release_allowed']})
        write_new(folder / "gate.json", gate)
        write_new(folder / "production_before.json", before)
        write_new(folder / "legacy_evidence_status.json", legacy)
        write_new(folder / "test_proof.json", proof)
        print(json.dumps({"collection_id": collection_id, "folder": str(folder), **gate}), flush=True)
        if gate["SAFE_TO_ENABLE_BOUNDED_LIVE_INGESTION"] != "YES":
            journal.stop("PRESTART_GATE_FAILED", safe=True)
        elif args.run:
            async def health_probe():
                current = runtime()
                return (current["running"] and current["resources_ok"] and current["pid"] == rt["pid"]
                        and current["runs"] == rt["runs"] and current["legacy_stream_disabled"] and current["observe_only"]
                        and evaluate_readiness(args.readiness_manifest, repo_root=ROOT,
                            runtime_id=f"{current['pid']}:{current['runs']}")['live_data_release_allowed'])
            await consume_bounded(journal, health_probe=health_probe)
        else:
            journal.stop("LIVE_RUN_NOT_REQUESTED", safe=True)
        after = await snapshot(first, last)
        rt_after = runtime()
        core_stable = all(before[k] == after[k] for k in ("coverage", "cursors", "gaps", "outbox", "table_write_statistics"))
        safe_after = (core_stable and queue_clean(after) and cursor_valid(after) and rt_after["pid"] == rt["pid"]
                      and rt_after["runs"] == rt["runs"] and rt_after["legacy_stream_disabled"] and rt_after["observe_only"]
                      and hashlib.sha256(old_path.read_bytes()).hexdigest() == old_hash
                      and hashlib.sha256(orchestrator_path.read_bytes()).hexdigest() == orchestrator_hash)
        if not safe_after:
            journal.stop("POST_COLLECTION_SAFETY_FAILED", safe=True)
        report = build_verified_report(journal, legacy)
        assert build_verified_report(journal, legacy) == report
        write_new(folder / "production_after.json", after)
        write_new(folder / "safety_after.json", {"legacy_core_data_unchanged": core_stable,
            "all_postchecks_passed": safe_after, "runtime": rt_after, "trading_actions": 0,
            "live_trading": False, "old_report_hash": old_hash, "orchestrator_state_hash": orchestrator_hash})
        write_new(folder / "collection_result.json", report)
        rows = [dict(r) for r in journal.db.execute("SELECT seq,measured_at,payload FROM telemetry ORDER BY seq")]
        write_new(folder / "telemetry.json", rows)
        management = (f"# TIM — {collection_id}\n\n"
            f"Current collection: **{report['CURRENT_COLLECTION_DATA_QUALITY']}**. Legacy: **{report['GLOBAL_LEGACY_DATA_QUALITY']}**.\n\n"
            f"{LEGACY_WARNING}\n\n{report['current_evidence_statement']}\n\n"
            f"Received: {report['counts']['received']}; accepted: {report['counts']['accepted_unique']}; "
            f"duplicates: {report['counts']['duplicates']}; rejected: {report['counts']['rejected']}; "
            f"completed: {report['counts']['statuses']['COMPLETED']}.\n\n"
            f"Boundary: {args.max_events} received frames / {args.duration} seconds, then stop. "
            f"Stop reason: {report['stop_reason']}.\n\n"
            "SHORT / MID / LONG: LIMITED; no trading authorization. Legacy gaps are not repaired. "
            "First/last candle windows may be partial.\n\n"
            f"Result hash: `{report['RESULT_HASH']}`\n")
        (folder / "management_summary.md").write_text(management)
        (folder / "technical_report.md").write_text("# Technical evidence\n\n" + management +
            "\nThe durable SQLite journal includes every application-delivered receipt, exact public payload hash, "
            "raw trade, disposition, per-event candle output hash and telemetry. OS/WebSocket-buffered frames "
            "not delivered to recv after close are not part of the collection. No network reconnect or historical catch-up occurred.\n")
        journal.close()
        manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}
        write_new(folder / "manifest.json", manifest)
        print(json.dumps({"folder": str(folder), "result": report}, default=str), flush=True)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Perform the explicitly authorized one bounded live session")
    parser.add_argument("--max-events", type=int, default=10000)
    parser.add_argument("--duration", type=int, default=300)
    parser.add_argument("--test-proof", type=Path, required=True)
    parser.add_argument("--readiness-manifest", type=Path, required=True,
                        help="Fresh, current-source-bound safety/quality verifier manifest")
    outcome = asyncio.run(run(parser.parse_args()))
    if isinstance(outcome, dict) and outcome.get('LIVE_DATA_READINESS') == 'SAFE_STOP':
        raise SystemExit(2)
