from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

from src.operational.logging import RotationPolicy, StructuredLog


def read_rows(path: Path) -> list[dict]:
    rows = []
    for candidate in [path, *sorted(path.parent.glob(path.name + ".*.gz"))]:
        opener = gzip.open if candidate.suffix == ".gz" else open
        with opener(candidate, "rt", encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    return rows


def test_rotation_preserves_every_entry_compresses_and_redacts_secrets(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = StructuredLog(path, RotationPolicy(max_bytes=280, backup_count=20, retention_days=7))
    for index in range(12):
        log.write(
            "ROTATION_TEST",
            index=index,
            database_url="postgresql://tim:do-not-log@127.0.0.1/tim",
            authorization="Bearer do-not-log",
        )
    rows = read_rows(path)
    assert sorted(row["index"] for row in rows) == list(range(12))
    combined = json.dumps(rows)
    assert "do-not-log" not in combined
    assert "[REDACTED]" in combined
    assert list(tmp_path.glob("events.jsonl.*.gz"))
    assert stat_mode(path) == 0o600


def test_structured_log_rate_limits_and_reports_suppressed_count(
    tmp_path: Path, monkeypatch
) -> None:
    ticks = iter((10.0, 11.0, 21.0))
    monkeypatch.setattr("src.operational.logging.time.monotonic", lambda: next(ticks))
    path = tmp_path / "events.jsonl"
    log = StructuredLog(path)

    assert log.write("REPEATED", rate_limit_seconds=10.0)
    assert not log.write("REPEATED", rate_limit_seconds=10.0)
    assert log.write("REPEATED", rate_limit_seconds=10.0)

    rows = read_rows(path)
    assert len(rows) == 2
    assert rows[-1]["suppressed_since_last"] == 1


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777
