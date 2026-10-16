import json

import pytest

from src.bugfixer.processing import parse_line
from src.bugfixer.store import IncidentStore
from src.bugfixer.worker import ErrorLogWorker, ObservationBlocked


@pytest.fixture
def env(tmp_path):
    store = IncidentStore(tmp_path / "s.db")
    log = tmp_path / "app.log"
    worker = ErrorLogWorker(store, log)
    try:
        yield store, log, worker
    finally:
        store.close()


def _evidence(row):
    return json.loads(row["evidence"])


def test_truncated_json_non_dict_json_and_invalid_utf8_become_legacy_events(env):
    store, log, worker = env
    log.write_bytes(b'{"level":"ERROR"\n' + b"[1,2]\n" + b"\xff\xfe garbage\n")

    result = worker.poll()

    assert result["events_ingested"] == 3
    evidence = [_evidence(row) for row in store.list()]
    assert evidence
    assert all(item["component"] == "legacy" for item in evidence)
    assert any("\ufffd" in item["message"] for item in evidence)


def test_blank_lines_are_ignored_without_incidents(env):
    store, log, worker = env
    log.write_bytes(b"\n   \n")

    result = worker.poll()

    assert result["events_ingested"] == 0
    assert result["records_ignored"] == 2
    assert store.list() == []


def test_invalid_structured_timestamp_blocks_without_progress(env):
    store, log, worker = env
    log.write_bytes(
        b'{"level":"ERROR","component":"svc","message":"boom"}\n'
    )
    assert worker.poll()["events_ingested"] == 1
    offset = store.checkpoint(worker.source_id)["offset"]
    assert len(store.list()) == 1

    with log.open("ab") as handle:
        handle.write(
            b'{"level":"ERROR","component":"svc2","message":"second"}\n'
            b'{"level":"ERROR","message":"m","timestamp":"nope"}\n'
        )

    with pytest.raises(ObservationBlocked):
        worker.poll()
    assert store.checkpoint(worker.source_id)["offset"] == offset
    assert len(store.list()) == 1

    with pytest.raises(ObservationBlocked):
        worker.poll()
    assert store.checkpoint(worker.source_id)["offset"] == offset
    assert len(store.list()) == 1


def test_empty_structured_message_blocks(env):
    store, log, worker = env
    log.write_bytes(b'{"level":"ERROR","message":""}\n')

    with pytest.raises(ObservationBlocked):
        worker.poll()


def test_secret_in_truncated_json_is_redacted_before_persistence(env, tmp_path):
    store, log, worker = env
    secret = "hun" + "ter2"
    line = '{"level":"ERROR","message":"pass' + "word=" + secret + "\n"
    log.write_bytes(line.encode("utf-8"))

    worker.poll()

    assert len(store.list()) == 1
    assert secret not in json.dumps(store.list())
    assert secret.encode("utf-8") not in (tmp_path / "s.db").read_bytes()


def test_parse_line_direct_cases():
    observed = "2026-01-01T00:00:00+00:00"

    assert parse_line("", observed) is None
    assert parse_line("   ", observed) is None
    assert parse_line('{"level":"INFO","message":"x"}', observed) is None
    assert parse_line("null", observed).component == "legacy"
    with pytest.raises(ValueError):
        parse_line(
            '{"level":"ERROR","message":"x","timestamp":"nope"}', observed
        )
