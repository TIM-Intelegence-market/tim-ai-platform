from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import scripts.recover_quarantined as cli
from src.data_ingestion.durable import OutboxItem
from src.data_ingestion.durable import _canonical_hash
from src.data_ingestion.recovery import PersistedTradeReplayService, TIMRecoveryContext
from src.models.market_data import Trade


NOW = datetime(2026, 9, 3, 12, tzinfo=timezone.utc)


def item(index: int, *, status: str = "QUARANTINED", attempts: int = 5) -> OutboxItem:
    return OutboxItem(
        outbox_id=f"{index:064x}",
        worker_name="CANDLE_V1",
        idempotency_key=f"{index + 10_000:064x}",
        symbol="BTCUSDT",
        aggregate_trade_id=40_301_762_990 + index,
        status=status,
        attempts=attempts,
        max_attempts=5,
        input_hash=f"{index + 20_000:064x}",
        worker_version="1.0.0",
        created_at=NOW + timedelta(microseconds=index),
        started_at=None,
        last_error="ValueError: Out-of-order trade rejected",
    )


def trade(work: OutboxItem) -> Trade:
    return Trade(
        work.symbol,
        100_000.0 + work.aggregate_trade_id % 100,
        1.0,
        NOW + timedelta(milliseconds=work.aggregate_trade_id % 10_000),
        work.aggregate_trade_id,
        False,
    )


class BatchStore:
    """In-memory outbox double with the same per-record commit boundary as PostgreSQL."""

    def __init__(self, records: list[OutboxItem], *, fail_at: int | None = None) -> None:
        self.records = {record.outbox_id: record for record in records}
        self.states = {record.outbox_id: record.status for record in records}
        self.original_attempts = {record.outbox_id: record.attempts for record in records}
        self.fail_at = fail_at
        self.claims: list[str] = []
        self.acks: list[str] = []
        self.requarantines: list[str] = []

    async def list_quarantined_batch(self, worker_name: str, limit: int):
        candidates = sorted(
            (
                record
                for record in self.records.values()
                if record.worker_name == worker_name and self.states[record.outbox_id] != "COMPLETED"
            ),
            key=lambda record: (record.aggregate_trade_id, record.created_at, record.outbox_id),
        )
        selected = []
        for record in candidates:
            # Strict order never jumps across a non-quarantined head record.
            if self.states[record.outbox_id] != "QUARANTINED":
                break
            selected.append(record)
            if len(selected) == limit:
                break
        return selected

    async def claim_quarantined(self, outbox_id: str, **_kwargs):
        if self.states.get(outbox_id) != "QUARANTINED":
            return None
        self.states[outbox_id] = "PROCESSING"
        self.claims.append(outbox_id)
        return replace(self.records[outbox_id], status="PROCESSING")

    async def load_trade(self, symbol: str, aggregate_trade_id: int):
        record = next(
            record for record in self.records.values()
            if record.symbol == symbol and record.aggregate_trade_id == aggregate_trade_id
        )
        return trade(record)

    async def acknowledge(self, outbox_id: str, _output_hash: str):
        index = list(self.records).index(outbox_id) + 1
        if self.fail_at == index:
            return False
        assert self.states[outbox_id] == "PROCESSING"
        self.states[outbox_id] = "COMPLETED"
        self.acks.append(outbox_id)
        return True

    async def requarantine(self, outbox_id: str, _error, _previous_error):
        self.states[outbox_id] = "QUARANTINED"
        self.requarantines.append(outbox_id)
        return True


class CrashStore(BatchStore):
    def __init__(self, records: list[OutboxItem], crash_at_claim: int) -> None:
        super().__init__(records)
        self.crash_at_claim = crash_at_claim

    async def claim_quarantined(self, outbox_id: str, **kwargs):
        if len(self.claims) + 1 == self.crash_at_claim:
            raise RuntimeError("simulated process crash between records")
        return await super().claim_quarantined(outbox_id, **kwargs)


class BatchReplay:
    def __init__(self, *, fail_trade_id: int | None = None) -> None:
        self.fail_trade_id = fail_trade_id
        self.calls: list[list[int]] = []
        self.prepared = 0
        self.last_metrics = {
            "historical_reconstruction_count": 1,
            "database_read_seconds": 0.01,
            "replay_total_seconds": 0.02,
            "write_seconds": 0.01,
        }

    async def prepare_batch(self, records):
        self.prepared += 1
        trade_ids = [record.aggregate_trade_id for record in records]
        self.calls.append(trade_ids)
        return PreparedReplay(self, records)


class PreparedReplay:
    def __init__(self, replay: BatchReplay, records: list[OutboxItem]) -> None:
        self.replay = replay
        self.records = records
        self.next_index = 0
        self.metrics = replay.last_metrics

    async def replay_one(self, work: OutboxItem):
        expected = self.records[self.next_index]
        assert work.outbox_id == expected.outbox_id
        self.next_index += 1
        if work.aggregate_trade_id == self.replay.fail_trade_id:
            raise RuntimeError("poison")
        return {
            "mode": "OBSERVE",
            "idempotency_key": work.idempotency_key,
            "aggregate_trade_id": work.aggregate_trade_id,
            "completed_candles": [],
            "trading_actions": 0,
        }


def context(store: BatchStore, replay: BatchReplay) -> TIMRecoveryContext:
    recovery = TIMRecoveryContext.__new__(TIMRecoveryContext)
    recovery.store = store
    recovery.replay = replay
    recovery.worker = SimpleNamespace(worker_name="CANDLE_V1", lease_seconds=300)
    return recovery


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [10, 100])
async def test_batch_completes_requested_strict_order_prefix(limit: int) -> None:
    records = [item(index) for index in range(limit + 2)]
    store = BatchStore(records)
    result = await context(store, BatchReplay()).recover_batch(limit)

    assert result["status"] == "COMPLETED"
    assert result["completed"] == limit
    assert store.claims == [record.outbox_id for record in records[:limit]]
    assert store.acks == store.claims
    assert all(store.states[record.outbox_id] == "COMPLETED" for record in records[:limit])
    assert all(store.states[record.outbox_id] == "QUARANTINED" for record in records[limit:])
    assert all(record.attempts == store.original_attempts[record.outbox_id] for record in records)
    assert result["timing"]["historical_reconstruction_count"] == 1


@pytest.mark.asyncio
async def test_batch_stops_at_failure_and_resume_starts_at_same_record() -> None:
    records = [item(index) for index in range(8)]
    failed_id = records[3].outbox_id
    store = BatchStore(records)

    first = await context(store, BatchReplay(fail_trade_id=records[3].aggregate_trade_id)).recover_batch(8)
    assert first["status"] in {"PARTIAL", "QUARANTINED"}
    assert first["completed"] == 3
    assert store.states[failed_id] == "QUARANTINED"
    assert store.claims == [record.outbox_id for record in records[:4]]
    assert all(store.states[record.outbox_id] == "QUARANTINED" for record in records[4:])

    resumed = await context(store, BatchReplay()).recover_batch(8)
    assert resumed["status"] == "COMPLETED"
    assert store.claims[4] == failed_id
    assert all(state == "COMPLETED" for state in store.states.values())
    assert all(record.attempts == store.original_attempts[record.outbox_id] for record in records)


@pytest.mark.asyncio
async def test_committed_prefix_survives_later_ack_failure_without_duplicate_commit() -> None:
    records = [item(index) for index in range(6)]
    store = BatchStore(records, fail_at=4)
    result = await context(store, BatchReplay()).recover_batch(6)

    assert result["completed"] == 3
    assert store.acks == [record.outbox_id for record in records[:3]]
    assert store.states[records[3].outbox_id] == "QUARANTINED"
    assert all(store.states[record.outbox_id] == "QUARANTINED" for record in records[4:])

    store.fail_at = None
    await context(store, BatchReplay()).recover_batch(6)
    assert len(store.acks) == len(set(store.acks)) == 6


@pytest.mark.asyncio
async def test_pending_or_retry_head_is_not_pulled_into_quarantine_batch() -> None:
    records = [item(0), item(1, status="PENDING"), item(2), item(3, status="RETRY")]
    store = BatchStore(records)
    preview = await context(store, BatchReplay()).inspect_batch(10)

    assert preview["count"] == 1
    assert preview["records"][0]["outbox_id"] == records[0].outbox_id
    assert store.states == {record.outbox_id: record.status for record in records}


@pytest.mark.asyncio
async def test_batch_dry_run_preview_has_no_claims_or_writes() -> None:
    records = [item(index) for index in range(10)]
    store = BatchStore(records)
    preview = await context(store, BatchReplay()).inspect_batch(10)

    assert preview["count"] == 10
    assert preview["first_trade_id"] == records[0].aggregate_trade_id
    assert preview["last_trade_id"] == records[-1].aggregate_trade_id
    assert preview["status_counts"] == {"QUARANTINED": 10}
    assert not store.claims
    assert not store.acks
    assert all(state == "QUARANTINED" for state in store.states.values())


@pytest.mark.asyncio
async def test_empty_batch_is_a_noop_and_does_not_prepare_history() -> None:
    replay = BatchReplay()
    result = await context(BatchStore([]), replay).recover_batch(10)
    assert result == {"status": "EMPTY", "requested": 10, "completed": 0, "records": []}
    assert replay.prepared == 0


@pytest.mark.asyncio
async def test_batch_stops_if_selected_record_is_no_longer_quarantined() -> None:
    records = [item(index) for index in range(4)]
    store = BatchStore(records)
    original_claim = store.claim_quarantined

    async def vanish_at_second(outbox_id: str, **kwargs):
        if outbox_id == records[1].outbox_id:
            store.states[outbox_id] = "COMPLETED"
            return None
        return await original_claim(outbox_id, **kwargs)

    store.claim_quarantined = vanish_at_second
    result = await context(store, BatchReplay()).recover_batch(4)
    assert result["status"] == "PARTIAL"
    assert result["completed"] == 1
    assert result["records"][-1]["status"] == "NOT_QUARANTINED"
    assert store.claims == [records[0].outbox_id]
    assert store.states[records[2].outbox_id] == "QUARANTINED"


@pytest.mark.asyncio
async def test_crash_between_records_keeps_committed_prefix_and_resume_is_unique() -> None:
    records = [item(index) for index in range(6)]
    store = CrashStore(records, crash_at_claim=4)
    with pytest.raises(RuntimeError, match="simulated process crash"):
        await context(store, BatchReplay()).recover_batch(6)
    assert store.acks == [record.outbox_id for record in records[:3]]
    assert all(store.states[record.outbox_id] == "COMPLETED" for record in records[:3])
    assert all(store.states[record.outbox_id] == "QUARANTINED" for record in records[3:])

    store.crash_at_claim = 99
    resumed = await context(store, BatchReplay()).recover_batch(6)
    assert resumed["completed"] == 3
    assert len(store.acks) == len(set(store.acks)) == 6


def test_lightweight_record_guard_preserves_per_record_invariants() -> None:
    records = [item(0), item(1)]
    baseline = {"cursor_hash": "a" * 64, "recovery_state": "CATCHING_UP", "open_gaps": 3}
    current = {
        **baseline,
        "processing": 0,
        "targets": {
            records[0].outbox_id: {"status": "COMPLETED", "attempts": 5},
            records[1].outbox_id: {"status": "QUARANTINED", "attempts": 5},
        },
    }
    assert TIMRecoveryContext._record_guard_error(baseline, current, records[0], records[1:]) is None
    current["targets"][records[1].outbox_id]["attempts"] = 0
    assert "later target changed" in TIMRecoveryContext._record_guard_error(baseline, current, records[0], records[1:])


def test_batch_boundary_guard_detects_foreign_mutation() -> None:
    records = [item(0), item(1)]
    before = {
        "processing": 0, "queue_depth": 12, "cursor_hash": "a" * 64,
        "recovery_state": "CATCHING_UP", "open_gaps": 3,
        "status_counts": {"PENDING": 5, "PROCESSING": 0, "RETRY": 1, "COMPLETED": 10, "QUARANTINED": 6},
        "foreign_status_updated_at": {"PENDING": NOW, "PROCESSING": None, "RETRY": NOW, "COMPLETED": NOW, "QUARANTINED": NOW},
    }
    after = {
        **before, "queue_depth": 10,
        "status_counts": {**before["status_counts"], "COMPLETED": 12, "QUARANTINED": 4},
        "targets": {record.outbox_id: {"status": "COMPLETED", "attempts": 5} for record in records},
    }
    assert TIMRecoveryContext._batch_transition_guard_error(before, after, records, []) is None
    after["foreign_status_updated_at"] = {**before["foreign_status_updated_at"], "PENDING": NOW + timedelta(seconds=1)}
    assert TIMRecoveryContext._batch_transition_guard_error(before, after, records, []) == "foreign outbox record changed during quarantine recovery"


class CandleRows:
    def __init__(self, rows: list[Trade], targets: list[OutboxItem]) -> None:
        self.rows = rows
        self.targets = targets
        self.current_single_index = 0
        self.batch_reads = 0

    async def load_trade(self, _symbol: str, aggregate_trade_id: int) -> Trade:
        return next(value for value in self.rows if value.trade_id == aggregate_trade_id)

    async def replay_input(self, _work: OutboxItem, _since):
        allowed = {entry.aggregate_trade_id for entry in self.targets[: self.current_single_index + 1]}
        return [value for value in self.rows if value.trade_id not in self.target_ids or value.trade_id in allowed]

    async def batch_replay_input(self, _items, _since):
        self.batch_reads += 1
        by_trade_id = {entry.aggregate_trade_id: entry.outbox_id for entry in self.targets}
        return [(value, by_trade_id.get(value.trade_id)) for value in self.rows]

    @property
    def target_ids(self):
        return {entry.aggregate_trade_id for entry in self.targets}


class CapturingCandles:
    def __init__(self) -> None:
        self.rows = {}

    async def upsert_candle(self, candle) -> None:
        self.rows[(candle.symbol, candle.timeframe, candle.open_time)] = candle


@pytest.mark.asyncio
async def test_batch_output_and_candles_match_sequential_single_reference(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.data_ingestion.recovery.settings",
        SimpleNamespace(timeframes=("1m",)),
    )
    targets = [item(index) for index in range(5)]
    target_trades = [
        Trade("BTCUSDT", 101.0 + index, 0.1, NOW + timedelta(seconds=10 + index), target.aggregate_trade_id, False)
        for index, target in enumerate(targets)
    ]
    base = [
        Trade("BTCUSDT", 100.0, 0.1, NOW + timedelta(seconds=5), 1, False),
        Trade("BTCUSDT", 110.0, 3.0, NOW + timedelta(seconds=65), 2, False),
    ]
    all_rows = sorted([*base, *target_trades], key=lambda value: (value.event_time, value.trade_id))

    single_store = CandleRows(all_rows, targets)
    single_repo = CapturingCandles()
    single = PersistedTradeReplayService(single_store, single_repo)
    single_hashes = []
    for index, (work, value) in enumerate(zip(targets, target_trades)):
        single_store.current_single_index = index
        completed = await single.replay(work, value)
        result = {
            "mode": "OBSERVE",
            "idempotency_key": work.idempotency_key,
            "aggregate_trade_id": value.trade_id,
            "completed_candles": completed,
            "trading_actions": 0,
        }
        single_hashes.append(_canonical_hash({"result": result, "worker": "CANDLE_V1"}))

    batch_store = CandleRows(all_rows, targets)
    batch_repo = CapturingCandles()
    prepared = await PersistedTradeReplayService(batch_store, batch_repo).prepare_batch(targets)
    batch_hashes = []
    for work in targets:
        result = await prepared.replay_one(work)
        batch_hashes.append(_canonical_hash({"result": result, "worker": "CANDLE_V1"}))

    assert batch_hashes == single_hashes
    assert batch_repo.rows == single_repo.rows
    assert batch_store.batch_reads == 1
    assert prepared.metrics["historical_reconstruction_count"] == 1


def test_cli_requires_exactly_one_single_or_bounded_batch_mode() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    with pytest.raises(SystemExit):
        parser.parse_args(["--outbox-id", "a" * 64, "--batch-limit", "10"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--batch-limit", "0"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--batch-limit", "1001"])
    assert parser.parse_args(["--outbox-id", "a" * 64]).outbox_id == "a" * 64
    assert parser.parse_args(["--batch-limit", "100"]).batch_limit == 100


def test_single_record_cli_remains_compatible(monkeypatch, capsys) -> None:
    calls = []

    async def fake_run(outbox_id=None, *, batch_limit=None, dry_run=False):
        calls.append((outbox_id, batch_limit, dry_run))
        return {"status": "COMPLETED", "outbox_id": outbox_id}

    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main(["--outbox-id", "a" * 64]) == 0
    assert calls == [("a" * 64, None, False)]
    assert '"status": "COMPLETED"' in capsys.readouterr().out


def test_batch_cli_dry_run_routes_to_preview_without_recovery(monkeypatch, capsys) -> None:
    calls = []

    async def fake_run(outbox_id=None, *, batch_limit=None, dry_run=False):
        calls.append((outbox_id, batch_limit, dry_run))
        return {"status": "PREVIEW", "count": batch_limit}

    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main(["--batch-limit", "10", "--dry-run"]) == 0
    assert calls == [(None, 10, True)]
    assert '"count": 10' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_runtime_guard_stops_before_first_claim_without_writes() -> None:
    records = [item(index) for index in range(3)]
    store = BatchStore(records)
    recovery = context(store, BatchReplay())

    def stop() -> None:
        raise RuntimeError("runtime unsafe")

    recovery.runtime_guard = stop
    with pytest.raises(RuntimeError, match="runtime unsafe"):
        await recovery.recover_batch(3)
    assert store.claims == []
    assert store.acks == []


@pytest.mark.asyncio
async def test_runtime_guard_failure_after_commit_never_requarantines_completed_record() -> None:
    records = [item(index) for index in range(3)]
    store = BatchStore(records)
    recovery = context(store, BatchReplay())
    calls = 0

    def stop_after_first_commit() -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise RuntimeError("runtime changed")

    recovery.runtime_guard = stop_after_first_commit
    result = await recovery.recover_batch(3)
    assert result["status"] == "PARTIAL"
    assert result["completed"] == 1
    assert store.acks == [records[0].outbox_id]
    assert store.requarantines == []
    assert store.states[records[0].outbox_id] == "COMPLETED"
    assert all(store.states[record.outbox_id] == "QUARANTINED" for record in records[1:])


def test_production_runtime_guard_validates_launchd_live_block_and_parallel_maintenance(monkeypatch) -> None:
    monkeypatch.delenv("TIM_RUNTIME_ENV", raising=False)
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    launchd = "active count = 1\nstate = running\nTIM_BINANCE_WS_URL => ws://127.0.0.1:1\n"

    def safe_run(command, **_kwargs):
        output = launchd if command[0] == "/bin/launchctl" else "35231 Python /opt/python main.py\n"
        return SimpleNamespace(stdout=output)

    monkeypatch.setattr(cli.subprocess, "run", safe_run)
    cli.validate_batch_runtime()

    def unsafe_run(command, **_kwargs):
        output = launchd if command[0] == "/bin/launchctl" else "999 Python /opt/python drain_queue.py\n"
        return SimpleNamespace(stdout=output)

    monkeypatch.setattr(cli.subprocess, "run", unsafe_run)
    with pytest.raises(RuntimeError, match="parallel maintenance"):
        cli.validate_batch_runtime()


@pytest.mark.asyncio
async def test_runtime_guard_failure_before_claim_stops_without_any_write() -> None:
    records = [item(index) for index in range(4)]
    store = BatchStore(records)
    recovery = context(store, BatchReplay())
    calls = 0

    def guard() -> None:
        nonlocal calls
        calls += 1
        # start, after read-only preparation, then immediately before first claim
        if calls == 3:
            raise RuntimeError("runtime became unsafe")

    recovery.runtime_guard = guard
    with pytest.raises(RuntimeError, match="runtime became unsafe"):
        await recovery.recover_batch(4)

    assert not store.claims
    assert not store.acks
    assert not store.requarantines
    assert all(state == "QUARANTINED" for state in store.states.values())


@pytest.mark.asyncio
async def test_runtime_guard_failure_after_commit_stops_without_requarantine_or_duplicate() -> None:
    records = [item(index) for index in range(4)]
    store = BatchStore(records)
    recovery = context(store, BatchReplay())
    calls = 0

    def guard() -> None:
        nonlocal calls
        calls += 1
        # First record was acknowledged before the fourth guard invocation.
        if calls == 4:
            raise RuntimeError("launchd stopped")

    recovery.runtime_guard = guard
    result = await recovery.recover_batch(4)

    assert result["status"] == "PARTIAL"
    assert result["completed"] == 1
    assert "runtime guard failed after commit" in result["safety_stop"]
    assert store.acks == [records[0].outbox_id]
    assert not store.requarantines
    assert store.states[records[0].outbox_id] == "COMPLETED"
    assert all(store.states[record.outbox_id] == "QUARANTINED" for record in records[1:])


def launchd_state(*, active: int = 1, state: str = "running", live_disabled: bool = True) -> str:
    endpoint = "TIM_BINANCE_WS_URL => ws://127.0.0.1:1\n" if live_disabled else ""
    return f"active count = {active}\nstate = {state}\n{endpoint}"


def install_process_mocks(monkeypatch, launchd_output: str, ps_output: str = "") -> None:
    monkeypatch.delenv("TIM_RUNTIME_ENV", raising=False)
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli.os, "getuid", lambda: 501)
    monkeypatch.setattr(cli.os, "getpid", lambda: 900)
    outputs = iter([launchd_output, ps_output])

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(stdout=next(outputs))

    monkeypatch.setattr(cli.subprocess, "run", fake_run)


@pytest.mark.parametrize(
    ("state", "message"),
    [
        (launchd_state(active=2), "active count is not exactly one"),
        (launchd_state(state="waiting"), "process is not running"),
    ],
)
def test_production_validator_rejects_invalid_launchd_state(monkeypatch, state, message) -> None:
    install_process_mocks(monkeypatch, state)
    with pytest.raises(RuntimeError, match=message):
        cli.validate_batch_runtime()


def test_production_validator_rejects_enabled_live_ingestion(monkeypatch) -> None:
    install_process_mocks(monkeypatch, launchd_state(live_disabled=False))
    with pytest.raises(RuntimeError, match="live ingestion is not pinned"):
        cli.validate_batch_runtime()


@pytest.mark.parametrize("maintenance_script", ["recover_quarantined.py", "drain_queue.py", "backfill_gaps.py"])
def test_production_validator_rejects_parallel_maintenance_process(monkeypatch, maintenance_script) -> None:
    install_process_mocks(
        monkeypatch,
        launchd_state(),
        f"777 /usr/bin/python3 python3 scripts/{maintenance_script} --batch-limit 10\n",
    )
    with pytest.raises(RuntimeError, match="parallel maintenance process detected: pid=777"):
        cli.validate_batch_runtime()
