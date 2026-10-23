"""Append-only hash-chained event log: idempotent appends, verified chain, tolerated crash tail."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.dashboard import journal_log as jl


def _events(*ids: str) -> list[dict]:
    return [{"event_id": i, "kind": "X", "payload": {"n": i}} for i in ids]


def test_append_is_idempotent_and_read_verifies_the_chain(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    assert jl.read(path).events == [] and jl.read(path).head == jl.GENESIS
    written = jl.append(path, _events("a", "b"))
    assert [e["seq"] for e in written] == [0, 1] and written[0]["previous"] == jl.GENESIS and written[1]["previous"] == written[0]["hash"]
    assert jl.append(path, _events("a", "b")) == []
    assert [e["event_id"] for e in jl.append(path, _events("b", "c"))] == ["c"]
    state = jl.read(path)
    assert [e["event_id"] for e in state.events] == ["a", "b", "c"] and state.head == state.events[-1]["hash"]
    assert all(e["log_version"] == jl.LOG_VERSION for e in state.events)


@pytest.mark.parametrize("damage", ["edit", "delete", "reorder", "duplicate"])
def test_edited_logs_are_refused(tmp_path: Path, damage: str) -> None:
    path = tmp_path / "log.jsonl"
    jl.append(path, _events("a", "b", "c"))
    lines = path.read_text().splitlines()
    if damage == "edit":
        lines[1] = lines[1].replace('"n": "b"', '"n": "B"')
    elif damage == "delete":
        del lines[0]
    elif damage == "reorder":
        lines = lines[::-1]
    else:
        lines.append(lines[2])
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(jl.LogError):
        jl.read(path)
    with pytest.raises(jl.LogError):
        jl.append(path, _events("d"))


def test_truncated_last_line_is_dropped_and_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    jl.append(path, _events("a", "b"))
    good = path.read_bytes()
    path.write_bytes(good + b'{"event_id": "c", "kind": "X", "payload": {"n": "c"}, "seq": 2, "previous": "x", "hash": "y"'[:50])
    state = jl.read(path)
    assert [e["event_id"] for e in state.events] == ["a", "b"] and state.dropped_tail and state.valid_bytes == len(good)
    jl.append(path, _events("c"))
    state = jl.read(path)
    assert [e["event_id"] for e in state.events] == ["a", "b", "c"] and state.dropped_tail is None
    assert path.read_bytes().startswith(good)


def test_events_need_identity_and_kind(tmp_path: Path) -> None:
    with pytest.raises(jl.LogError):
        jl.append(tmp_path / "log.jsonl", [{"kind": "X"}])
    assert jl.event_id("a", {"b": 1}) == jl.event_id("a", {"b": 1}) != jl.event_id("a", {"b": 2})
    assert jl.content_hash([1, 2]) != jl.content_hash([2, 1])
