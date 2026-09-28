from __future__ import annotations

import pytest

from scripts.legacy_gap_recovery import (
    BATCH_UPDATE_SQL,
    OPEN_IN_RANGE_SQL,
    plan_batches,
    range_fingerprint,
    run_batch,
    verify_range,
)


def test_plan_batches_deterministic_and_bounded():
    items = ["g%d" % i for i in range(450)]
    batches = plan_batches(items, 200)
    assert [len(b) for b in batches] == [200, 200, 50]
    assert batches[0][0] == "g0" and batches[-1][-1] == "g449"
    # resume skips completed prefix
    resumed = plan_batches(items, 200, skip_batches=1)
    assert [len(b) for b in resumed] == [200, 50]
    assert resumed[0][0] == "g200"
    with pytest.raises(ValueError):
        plan_batches(items, 0)


def test_batch_sql_is_concurrency_safe_and_bounded():
    assert "status='OPEN'" in BATCH_UPDATE_SQL
    assert "gap_id = ANY($1)" in BATCH_UPDATE_SQL
    assert "RESOLVED" in BATCH_UPDATE_SQL
    assert "DELETE" not in BATCH_UPDATE_SQL
    # selection is deterministic oldest-first
    assert "ORDER BY detected_at" in OPEN_IN_RANGE_SQL


def test_range_fingerprint_stable():
    assert range_fingerprint("BTCUSDT", 1, 100, 100) == range_fingerprint("BTCUSDT", 1, 100, 100)
    assert range_fingerprint("BTCUSDT", 1, 100, 100) != range_fingerprint("BTCUSDT", 1, 100, 99)


class FakeConn:
    def __init__(self, rows=None, status="UPDATE 2"):
        self.rows = rows or []
        self.status = status
        self.executed = []

    async def fetchrow(self, _sql, *_a):
        return self.rows[0]

    async def execute(self, sql, batch):
        self.executed.append((sql, list(batch)))
        return self.status


@pytest.mark.asyncio
async def test_verify_range_requires_exact_triple():
    good = FakeConn([{"n": 10, "mn": 5, "mx": 14}])
    assert (await verify_range(good, "BTCUSDT", 5, 14, 10))["complete"] is True
    short = FakeConn([{"n": 9, "mn": 5, "mx": 14}])
    assert (await verify_range(short, "BTCUSDT", 5, 14, 10))["complete"] is False
    shifted = FakeConn([{"n": 10, "mn": 6, "mx": 15}])
    assert (await verify_range(shifted, "BTCUSDT", 5, 14, 10))["complete"] is False


@pytest.mark.asyncio
async def test_run_batch_returns_rowcount_for_concurrency_check():
    conn = FakeConn(status="UPDATE 2")
    assert await run_batch(conn, ["a", "b"]) == 2
    assert "status='OPEN'" in conn.executed[0][0]
    assert conn.executed[0][1] == ["a", "b"]


def test_manifest_hash_detects_tampering():
    import hashlib
    import json

    manifest = {"recovery_id": "x", "ranges": [{"merged_range_id": "a"}]}
    good = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    manifest["manifest_hash"] = good
    check = hashlib.sha256(
        json.dumps({k: v for k, v in manifest.items() if k != "manifest_hash"}, sort_keys=True).encode()
    ).hexdigest()
    assert check == manifest["manifest_hash"]
    manifest["ranges"].append({"merged_range_id": "b"})
    check2 = hashlib.sha256(
        json.dumps({k: v for k, v in manifest.items() if k != "manifest_hash"}, sort_keys=True).encode()
    ).hexdigest()
    assert check2 != manifest["manifest_hash"]
