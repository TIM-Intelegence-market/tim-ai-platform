from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from src.collection_reporting.verified import (
    CollectionStop, SOURCE, VerifiedJournal, bounded_live_gate, build_verified_report,
)
from src.collection_reporting import verified_runtime

NOW = "2026-09-06T12:00:00+00:00"
MILLIS = int(datetime.fromisoformat(NOW).timestamp() * 1000)
LEGACY = {"status": "INCOMPLETE", "raw_trades_total": 7_572_705, "gaps": {"OPEN": 1694}}


def raw(event_id=100, **updates):
    return json.dumps({"e": "aggTrade", "E": MILLIS, "T": MILLIS, "a": event_id,
                       "s": "BTCUSDT", "p": "100.50", "q": "0.1", "m": False, **updates})


def create(tmp_path, name="A", limit=2):
    contract = {"collection_id": name, "symbol": "BTCUSDT", "source": SOURCE,
        "max_events": limit, "max_duration_seconds": 300, "live_trading": False, "trading_actions": 0}
    return VerifiedJournal(tmp_path / name / "journal.sqlite3", contract)


def receive(j, payload):
    seq = j.receive(payload, NOW)
    result = j.classify(seq)
    j.drain()
    return result


def complete(j, messages):
    j.begin(NOW)
    for payload in messages:
        receive(j, payload)
    j.stop("MAX_EVENTS")
    j.finish(len(messages))
    return build_verified_report(j, LEGACY)


def test_legacy_missing_evidence_visible_but_not_current_blocker(tmp_path):
    j = create(tmp_path)
    result = complete(j, [raw(100), raw(101)])
    assert result["GLOBAL_LEGACY_DATA_QUALITY"] == "WARN"
    assert result["CURRENT_COLLECTION_DATA_QUALITY"] == "PASS"
    assert result["classification"] == "VERIFIED_COLLECTION"
    assert result["TIM_AUTONOMOUS_COLLECTION_READY"] == "YES"
    assert "incomplete" in result["legacy_limitation"]
    assert "complete ingress and processing" in result["current_evidence_statement"]
    j.close()


def test_legacy_debt_distinguishes_ingress_and_worker_evidence():
    from scripts.verified_live_collection import legacy_evidence
    data = {"metrics": {"duplicate_total": 3, "reject_reason:OUTBOX_CAPACITY": 1},
            "coverage": [{"n": 600, "completed": 0}, {"n": 100, "completed": 100}], "gaps": []}
    old = {"started_at": NOW, "ended_at": NOW, "expected_period": {"first_trade_id": 1, "last_trade_id": 700}}
    result = legacy_evidence(data, old)
    assert result["classification"] == "LEGACY_UNVERIFIED_INGRESS"
    assert result["unproven_ingress_count"] == 700
    assert result["unproven_worker_completion_count"] == 600
    assert result["unknown_message_occurrences"] is None
    assert result["remediation_possible"] == "NO"


def test_journal_commits_before_validation_and_contains_lineage(tmp_path):
    j = create(tmp_path, limit=1)
    j.begin(NOW)
    seq = j.receive(raw(), NOW)
    row = dict(j.db.execute("SELECT * FROM receipts").fetchone())
    assert row["disposition"] == "UNKNOWN"
    assert row["raw_payload"] == raw() and len(row["raw_payload_hash"]) == 64
    j.classify(seq)
    row = dict(j.db.execute("SELECT * FROM receipts").fetchone())
    for key in ("collection_id", "source", "symbol", "event_id", "received_at", "source_timestamp",
                "raw_payload_hash", "validation_result", "disposition", "durable_record_id"):
        assert row[key] is not None
    assert row["rejection_reason"] is None
    j.close()


def test_hard_limit_refuses_next_event_assignment(tmp_path):
    j = create(tmp_path, limit=1)
    j.begin(NOW)
    receive(j, raw())
    with pytest.raises(CollectionStop):
        j.receive(raw(101), NOW)
    assert j.counts()["received"] == 1 and j.get("state") == "DRAINING"
    j.close()


def test_received_duplicate_rejected_accepted_and_processed_equations(tmp_path):
    j = create(tmp_path, limit=4)
    result = complete(j, [raw(), raw(), "not json", raw(101)])
    c = result["counts"]
    assert c["received"] == 4
    assert c["accepted_unique"] == 2 and c["duplicates"] == 1 and c["rejected"] == 1
    assert c["received"] == c["accepted_unique"] + c["duplicates"] + c["rejected"]
    assert c["accepted_unique"] == sum(c["statuses"].values()) == c["statuses"]["COMPLETED"]
    assert result["COUNTS_ACCOUNTED"] == result["ALL_UNIQUE_EVENTS_PROCESSED"] == "PASS"
    j.close()


@pytest.mark.parametrize("payload", ["no-json", raw(p="NaN"), raw(q="0"), raw(s="ETHUSDT"), b"\xff\xfe"])
def test_invalid_frame_is_journaled_and_rejected_never_silently_skipped(tmp_path, payload):
    j = create(tmp_path, limit=1)
    j.begin(NOW)
    assert receive(j, payload) == "REJECTED"
    row = j.db.execute("SELECT * FROM receipts").fetchone()
    assert row["raw_payload"] == payload and row["rejection_reason"]
    assert j.counts()["received"] == 1 and j.counts()["rejected"] == 1
    j.close()


def test_collections_do_not_contaminate_each_other(tmp_path):
    a, b = create(tmp_path, "A", 1), create(tmp_path, "B", 1)
    ra = complete(a, [raw()])
    rb = complete(b, [raw()])
    assert ra["counts"] == rb["counts"]
    assert ra["RESULT_HASH"] != rb["RESULT_HASH"]
    assert a.db.execute("SELECT collection_id FROM receipts").fetchone()[0] == "A"
    assert b.db.execute("SELECT collection_id FROM receipts").fetchone()[0] == "B"
    a.close(); b.close()


def test_closed_resume_is_idempotent_and_cannot_reopen_network(tmp_path):
    j = create(tmp_path)
    before = complete(j, [raw(), raw(101)])
    path = j.path
    j.close()
    resumed = VerifiedJournal(path)
    resumed.drain()
    assert build_verified_report(resumed, LEGACY) == before
    with pytest.raises(CollectionStop):
        resumed.begin()
    with pytest.raises(CollectionStop):
        resumed.receive(raw(102), NOW)
    resumed.close()


def test_unclean_resume_does_not_invent_receipt_continuity(tmp_path):
    j = create(tmp_path)
    j.begin(NOW)
    j.receive(raw(), NOW)
    path = j.path
    j.close()
    resumed = VerifiedJournal(path)
    assert resumed.get("state") == "SAFE_STOP"
    assert resumed.verify()["COUNTS_ACCOUNTED"] == "FAIL"
    resumed.close()


def test_unknown_accounting_forces_safe_stop(tmp_path):
    j = create(tmp_path, limit=1)
    j.begin(NOW)
    j.receive(raw(), NOW)
    j.stop("MAX_EVENTS")
    assert not j.finish(1)
    assert j.get("state") == "SAFE_STOP"
    assert build_verified_report(j, LEGACY)["COUNTS_ACCOUNTED"] == "FAIL"
    j.close()


def test_application_receipt_counter_mismatch_fails(tmp_path):
    j = create(tmp_path, limit=1)
    j.begin(NOW)
    receive(j, raw())
    j.stop("MAX_EVENTS")
    assert not j.finish(2)
    assert j.verify()["COUNTS_ACCOUNTED"] == "FAIL"
    j.close()


def test_unknown_worker_completion_not_hidden_by_empty_queue(tmp_path):
    j = create(tmp_path)
    complete(j, [raw(), raw(101)])
    with j.db:
        j.db.execute("DELETE FROM events WHERE event_id=101")
    result = build_verified_report(j, LEGACY)
    assert result["ALL_UNIQUE_EVENTS_PROCESSED"] == "FAIL"
    assert result["TIM_AUTONOMOUS_COLLECTION_READY"] == "NO"
    j.close()


def test_trading_contract_is_rejected_and_success_remains_observe_only(tmp_path):
    j = create(tmp_path, limit=1)
    bad = dict(j.contract, live_trading=True)
    with pytest.raises(CollectionStop):
        VerifiedJournal(tmp_path / "bad.sqlite3", bad)
    result = complete(j, [raw()])
    assert result["TRADING_ACTIONS"] == 0 and result["LIVE_TRADING"] == "DISABLED"
    assert result["LIVE_INGESTION_AFTER"] == "DISABLED"
    j.close()


def test_actual_replay_and_result_hash_reproducible(tmp_path):
    j = create(tmp_path)
    j.begin(NOW)
    receive(j, raw())
    seq = j.receive(raw(101, T=MILLIS+61000, E=MILLIS+61000), "2026-09-06T12:01:01+00:00")
    j.classify(seq); j.drain(); j.stop("MAX_EVENTS"); j.finish(2)
    first = build_verified_report(j, LEGACY)
    assert first["DETERMINISM"] == "PASS"
    candles = [json.loads(r[0]) for r in j.db.execute("SELECT payload FROM candles")]
    assert any(c["closed"] for c in candles)
    assert build_verified_report(j, LEGACY)["RESULT_HASH"] == first["RESULT_HASH"]
    j.close()


def test_transport_duration_closes_without_waiting_for_max_events(tmp_path, monkeypatch):
    from types import SimpleNamespace
    j = create(tmp_path, limit=10)
    monkeypatch.setattr(verified_runtime, "utc", lambda: NOW)
    moments = iter([0, 1, 2, 3, 301, 302])
    monkeypatch.setattr(verified_runtime, "time", SimpleNamespace(monotonic=lambda: next(moments)))
    class Socket:
        calls = 0
        closed = False
        async def recv(self):
            self.calls += 1
            return raw()
        async def close(self): self.closed = True
    socket = Socket()
    class Context:
        async def __aenter__(self): return socket
        async def __aexit__(self, *args): pass
    summary = asyncio.run(verified_runtime.consume_bounded(j, connector=lambda *args, **kwargs: Context()))
    assert socket.calls == 1 and socket.closed
    assert j.get("state") == "CLOSED" and j.get("stop_reason") == "DURATION"
    assert summary["received"] == 1
    j.close()


def test_stored_candle_tamper_fails_determinism(tmp_path):
    j = create(tmp_path, limit=1)
    complete(j, [raw()])
    with j.db:
        j.db.execute("UPDATE candles SET payload='{}'")
    assert j.verify()["DETERMINISM"] == "FAIL"
    j.close()


def test_intra_collection_gap_stops_without_recovery(tmp_path):
    j = create(tmp_path)
    j.begin(NOW)
    receive(j, raw(100))
    receive(j, raw(102))
    assert j.get("state") == "SAFE_STOP"
    assert j.get("gaps") == [{"missing_from_id": 101, "missing_to_id": 101}]
    j.close()


def test_gate_ignores_legacy_warning_but_requires_every_current_control():
    required = ("runtime_stable", "queue_clean", "cursor_valid", "journal_active", "hard_boundary_active",
                "automatic_stops_active", "tests_passed", "trading_disabled", "legacy_stream_disabled", "single_collector", "repair_readiness_passed")
    checks = {name: True for name in required}
    checks["legacy_quality"] = "WARN"
    assert bounded_live_gate(checks)["SAFE_TO_ENABLE_BOUNDED_LIVE_INGESTION"] == "YES"
    for name in required:
        assert bounded_live_gate({**checks, name: False})["SAFE_TO_ENABLE_BOUNDED_LIVE_INGESTION"] == "NO"


def test_transport_stops_at_limit_without_extra_recv_or_reconnect(tmp_path, monkeypatch):
    j = create(tmp_path)
    monkeypatch.setattr(verified_runtime, "utc", lambda: NOW)
    class Socket:
        calls = 0
        closed = False
        async def recv(self):
            self.calls += 1
            return raw(99 + self.calls)
        async def close(self): self.closed = True
    socket = Socket()
    class Context:
        async def __aenter__(self): return socket
        async def __aexit__(self, *args): pass
    connections = []
    def connector(url, **kwargs):
        connections.append(url)
        assert "binance.com:443/ws/btcusdt@aggTrade" in url
        assert kwargs["max_queue"] == 1
        return Context()
    summary = asyncio.run(verified_runtime.consume_bounded(j, connector=connector))
    assert socket.calls == 2 and socket.closed and len(connections) == 1
    assert j.get("state") == "CLOSED" and j.get("stop_reason") == "MAX_EVENTS"
    assert summary["received"] == 2 and summary["reconnections"] == 0
    j.close()
