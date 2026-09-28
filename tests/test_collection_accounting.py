from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from src.collection_reporting.accounting import accounting_checks, baseline_delta, digest, persisted_accounting
from src.collection_reporting.reporter import CollectionReportBuilder
from src.orchestration import HealthSnapshot, MissionPhase, OrchestrationConfig, Orchestrator


NOW = "2026-09-06T10:00:00+00:00"


def rows(ids=(100, 101)):
    return [{"aggregate_trade_id": i, "trade_time": NOW, "status": "COMPLETED",
             "completed_at": NOW, "output_hash": "a" * 64} for i in ids]


def evidence(collection_id="A", ids=(100, 101), dispositions=()):
    value = persisted_accounting(collection_id, rows(ids), max_events=10,
        requested_start=min(ids), requested_end=max(ids), captured_at=NOW)
    counts = value["counts"]
    counts.update(events_received=len(ids) + len(dispositions), duplicates=dispositions.count("DUPLICATE"),
                  invalid_events=dispositions.count("INVALID"), rejected_events=dispositions.count("REJECTED"))
    receipts = [{"receipt_id": f"receipt-{n}", "collection_id": collection_id,
                 "received_at": NOW, "event_id": i, "disposition": "UNIQUE"} for n, i in enumerate(ids)]
    receipts.extend({"receipt_id": f"extra-{n}", "collection_id": collection_id, "received_at": NOW,
                     "event_id": ids[0] if outcome == "DUPLICATE" else None, "disposition": outcome}
                    for n, outcome in enumerate(dispositions))
    value["ingress"] = {"collection_id": collection_id, "event_ids_hash": digest(list(ids)),
        "evidence_kind": "COLLECTION_RECEIPT_LEDGER", "requested_start": "2026-09-06T09:00:00+00:00",
        "requested_end": "2026-09-06T11:00:00+00:00", "receipts": receipts}
    return value


def facts(value):
    return {"collection_id": value["contract"]["collection_id"], "started_at": NOW, "ended_at": NOW,
        "mode": "OBSERVE", "live_trading": False, "trading_actions": 0, "counts": deepcopy(value["counts"]),
        "status_counts": deepcopy(value["status_counts"]), "accounting": value, "metrics_scoped": True,
        "preflight": {"database": "PASS", "main_processes": 1, "parallel_jobs": 0,
                      "logs": "PASS", "storage": "PASS", "orphaned_leases": 0},
        "determinism": {"status": "PASS", "first_hash": "a", "second_hash": "a"}, "gaps": []}


def test_lifetime_counts_do_not_contaminate_collection():
    source = facts(evidence())
    source["metrics"] = {"lifetime_metrics": {"received_total": 9_000_000, "raw_rows": 12_000_000}}
    result = CollectionReportBuilder().build(source)
    assert result["counts"]["events_unique"] == 2
    assert result["checks"]["counts_accounted"] == "PASS"


def test_collection_a_does_not_affect_b_and_cannot_supply_its_receipts():
    a, b = evidence("A"), evidence("B", (200, 201))
    before = CollectionReportBuilder().build(facts(b))
    a["counts"]["events_received"] = 1000
    assert CollectionReportBuilder().build(facts(b)) == before
    b["ingress"] = a["ingress"]
    assert accounting_checks(b, b["counts"], "B")["counts_accounted"] == "FAIL"


def test_baseline_delta_and_scope_reset_missing_counter_rejection():
    before = {"collection_id": "A", "scope": {"symbol": "BTCUSDT"}, "counters": {"received": 100}}
    after = {**before, "counters": {"received": 105}}
    assert baseline_delta(before, after) == {"received": 5}
    for bad in ({**after, "collection_id": "B"}, {**after, "scope": "global"},
                {**after, "counters": {"received": 99}}, {**after, "counters": {}}):
        with pytest.raises(ValueError):
            baseline_delta(before, bad)


@pytest.mark.parametrize("dispositions", [("DUPLICATE",), ("INVALID",), ("REJECTED",),
                                          ("DUPLICATE", "INVALID", "REJECTED")])
def test_disjoint_duplicate_invalid_rejected_accounting(dispositions):
    value = evidence(dispositions=dispositions)
    result = CollectionReportBuilder().build(facts(value))
    assert result["checks"]["counts_accounted"] == "PASS"
    assert result["checks"]["all_unique_events_processed"] == "PASS"


def test_complete_collection_passes_both_gates():
    result = CollectionReportBuilder().build(facts(evidence()))
    assert result["quality_status"] == "PASS"
    assert result["checks"]["counts_accounted"] == result["checks"]["all_unique_events_processed"] == "PASS"


def test_missing_outbox_and_same_count_wrong_event_fail():
    raw = rows()
    raw[1].update(status=None, completed_at=None, output_hash=None)
    value = persisted_accounting("A", raw, max_events=10, requested_start=100, requested_end=101, captured_at=NOW)
    assert value["missing_outbox_event_ids"] == [101]
    assert accounting_checks(value, value["counts"], "A")["all_unique_events_processed"] == "FAIL"
    value["completed_event_ids"] = [100, 999]
    value["counts"]["events_processed"] = 2
    assert accounting_checks(value, value["counts"], "A")["all_unique_events_processed"] == "FAIL"


def test_missing_receipt_still_fails_even_when_declared_totals_balance():
    value = evidence()
    value["ingress"]["receipts"].pop()
    assert accounting_checks(value, value["counts"], "A")["counts_accounted"] == "FAIL"


def test_unknown_historical_ingress_is_not_zero_or_pass():
    value = persisted_accounting("A", rows(), max_events=10, requested_start=100, requested_end=101, captured_at=NOW)
    result = CollectionReportBuilder().build(facts(value))
    assert result["counts"]["events_received"] is None
    assert result["checks"]["counts_accounted"] == "FAIL"
    assert result["checks"]["all_unique_events_processed"] == "PASS"
    assert result["tim_autonomous_collection_ready"] is False


@pytest.mark.parametrize("mutation", ["outside_time", "outside_id", "duplicate_receipt", "wrong_baseline"])
def test_boundaries_are_enforced(mutation):
    value = evidence()
    if mutation == "outside_time":
        value["ingress"]["receipts"][0]["received_at"] = "2026-09-06T11:00:00+00:00"
    elif mutation == "outside_id":
        value["ingress"]["receipts"][0]["event_id"] = 999
    elif mutation == "duplicate_receipt":
        value["ingress"]["receipts"][1]["receipt_id"] = "receipt-0"
    else:
        value["collection_baseline"]["collection_id"] = "B"
    assert accounting_checks(value, value["counts"], "A")["counts_accounted"] == "FAIL"


def test_raw_membership_cannot_exceed_limit_or_requested_bounds():
    with pytest.raises(ValueError):
        persisted_accounting("A", rows(), max_events=1, requested_start=100, requested_end=101, captured_at=NOW)
    with pytest.raises(ValueError):
        persisted_accounting("A", rows(), max_events=2, requested_start=100, requested_end=100, captured_at=NOW)


def test_accounting_failure_keeps_orchestrator_safe_stop(tmp_path):
    class Jobs:
        def run(self, *args, **kwargs):
            value = evidence()
            value["counts"]["events_received"] += 1
            result = CollectionReportBuilder().build(facts(value))
            return {"status": "REFUSED" if result["quality_status"] == "FAIL" else "PASS"}
    health = HealthSnapshot(status_counts={}, active_workers=1, gaps_open=0, gaps_unclassified=0,
                            cursor=101, last_completed_at=NOW, runtime_pid=123, runtime_state="RUNNING")
    runner = Orchestrator(OrchestrationConfig(tmp_path), lambda: health, Jobs())
    state = runner.load()
    state.phase = MissionPhase.M04_COLLECTION
    runner._persist(state, health, "TEST")
    assert runner.tick().phase is MissionPhase.SAFE_STOP
    assert runner.tick().phase is MissionPhase.SAFE_STOP


@pytest.mark.parametrize("status", ["REFUSED", "FAIL", "PARTIAL"])
def test_failed_persisted_receipt_cannot_become_already_completed(tmp_path, status):
    import json
    from src.orchestration.runtime import HeadlessJobs
    jobs = HeadlessJobs(root=tmp_path, database_url="postgresql://unused/test", symbol="BTCUSDT")
    jobs.receipts.mkdir(parents=True)
    receipt = jobs.receipts / "A.json"
    receipt.write_text(json.dumps({"status": status, "live_trading": False, "trading_actions": 0}))
    original = receipt.read_bytes()
    assert jobs.run("bounded_collection", idempotency_key="A", limit=2)["status"] == "REFUSED"
    assert receipt.read_bytes() == original


def test_bounded_job_passes_real_limit_to_collector(monkeypatch, tmp_path):
    from src.orchestration import runtime
    called = []
    async def collect(*args, **kwargs):
        called.append(kwargs)
        value = facts(evidence(kwargs["collection_id"]))
        value["limitations"] = []
        return value
    monkeypatch.setattr(runtime, "collect_read_only_facts", collect)
    jobs = runtime.HeadlessJobs(root=tmp_path, database_url="postgresql://unused/test", symbol="BTCUSDT")
    assert asyncio.run(jobs._collection("bounded-test", 2))["status"] == "PASS"
    assert called[0]["max_events"] == 2


def test_collector_is_read_only_and_enforces_sql_limit(monkeypatch, tmp_path):
    from src.collection_reporting import collector
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    calls, transactions = [], []
    class Transaction:
        async def __aenter__(self): pass
        async def __aexit__(self, *args): pass
    class Connection:
        def transaction(self, **kwargs):
            assert kwargs == {"isolation": "repeatable_read", "readonly": True}
            transactions.append(kwargs)
            return Transaction()
        async def close(self): pass
        async def fetchval(self, query, *args):
            calls.append(query)
            return now if "clock_timestamp()" in query else 2
        async def fetchrow(self, query, *args):
            calls.append(query)
            if "count(*) AS n" in query:
                return {"n": 7_000_000, "first_at": now, "last_at": now, "first_id": 1, "last_id": 101}
            return None
        async def fetch(self, query, *args):
            calls.append(query)
            if "SELECT t.*" in query:
                assert "LEFT JOIN" in query and "LIMIT $4" in query
                assert "status='COMPLETED'" not in query
                assert args == ("BTCUSDT", 100, 101, 2)
                return [{**row, "trade_time": now} for row in rows()]
            if "SELECT metric_name" in query:
                return [{"metric_name": k, "numeric_value": 9_000_000} for k in
                        ("received_total", "raw_persisted_total", "duplicate_total", "rejected_total")]
            if "GROUP BY status" in query:
                return [{"status": "COMPLETED", "n": 123456}]
            return []
    async def connect(*args, **kwargs):
        assert kwargs["server_settings"]["default_transaction_read_only"] == "on"
        return Connection()
    monkeypatch.setattr(collector.asyncpg, "connect", connect)
    monkeypatch.setattr(collector, "_process_inventory", lambda: (1, 0))
    monkeypatch.setattr(collector, "_filesystem_preflight", lambda root: ("PASS", "PASS"))
    monkeypatch.setattr(collector, "_git_revision", lambda root: "test")
    # Orphaned leases must be zero; no connection has an execute/mutation API.
    original = Connection.fetchval
    async def fetchval(self, query, *args):
        if "lease_expires_at" in query:
            calls.append(query)
            return 0
        return await original(self, query, *args)
    monkeypatch.setattr(Connection, "fetchval", fetchval)
    result = asyncio.run(collector.collect_read_only_facts("postgresql://unused/test", root=tmp_path,
        symbol="BTCUSDT", collection_id="A", max_events=2, requested_start=100, requested_end=101))
    assert result["counts"]["events_unique"] == 2
    assert result["counts"]["events_received"] is None
    assert result["accounting"]["lifetime_baseline_delta"]["values"]["received_total"] == 0
    assert len(transactions) == 2 and all(query.lstrip().startswith("SELECT") for query in calls)
