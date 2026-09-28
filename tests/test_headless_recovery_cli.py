from __future__ import annotations

import asyncio
import socket
from types import SimpleNamespace

import pytest

import scripts.recover_quarantined as cli
import src.data_ingestion.recovery as recovery


class DatabaseStub:
    def __init__(self, _url):
        self.connected = False

    async def connect(self):
        self.connected = True

    async def close(self):
        self.connected = False


class StoreStub:
    def __init__(self, _database):
        self.inspected = []

    async def inspect_recovery_target(self, outbox_id):
        self.inspected.append(outbox_id)
        return {"status": "RECOVERABLE", "outbox_id": outbox_id, "recoverable": True}


class WorkerStub:
    def __init__(self, _store, _name, _handler, **_kwargs):
        self.recovered = []

    async def recover_one(self, outbox_id):
        self.recovered.append(outbox_id)
        return {"status": "COMPLETED", "outbox_id": outbox_id}


@pytest.fixture
def headless(monkeypatch):
    monkeypatch.setattr(recovery, "settings", SimpleNamespace(database_url="postgresql://test"))
    monkeypatch.setattr(recovery, "Database", DatabaseStub)
    monkeypatch.setattr(recovery, "MarketRepository", lambda database: SimpleNamespace(database=database))
    monkeypatch.setattr(recovery, "DurableIngestionStore", StoreStub)
    monkeypatch.setattr(recovery, "DurableOutboxWorker", WorkerStub)
    return recovery.TIMRecoveryContext()


def test_context_has_no_dashboard_listener_stream_or_worker_loop(headless):
    assert not hasattr(headless, "dashboard")
    assert not hasattr(headless, "stream")
    assert not hasattr(headless, "worker_stop")
    assert not hasattr(headless, "run")


def test_context_initializes_while_a_tcp_port_is_already_occupied(headless):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        assert listener.getsockname()[1] > 0
        assert headless.database is not None


@pytest.mark.asyncio
async def test_recovery_and_dry_run_use_only_the_explicit_id(headless):
    target = "a" * 64
    assert (await headless.inspect(target))["status"] == "RECOVERABLE"
    assert headless.store.inspected == [target]
    result = await headless.recover(target)
    assert result["status"] == "COMPLETED"
    assert result["timing"]["recovery_total_seconds"] >= 0
    assert headless.worker.recovered == [target]


def test_cli_requires_explicit_outbox_id():
    with pytest.raises(SystemExit) as error:
        cli.main([])
    assert error.value.code == 2


def test_cli_dry_run_requests_inspection_only(monkeypatch, capsys):
    calls = []

    async def fake_run(outbox_id, *, dry_run=False):
        calls.append((outbox_id, dry_run))
        return {"status": "RECOVERABLE", "outbox_id": outbox_id, "recoverable": True}

    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main(["--outbox-id", "b" * 64, "--dry-run"]) == 0
    assert calls == [("b" * 64, True)]
    assert '"status": "RECOVERABLE"' in capsys.readouterr().out
