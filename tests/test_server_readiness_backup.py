from datetime import datetime, timedelta, timezone

from src.server_readiness.backup import evaluate_backup


NOW = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
HASH = "a" * 64


def receipt(**changes):
    value = {
        "archive_sha256": HASH,
        "restored_sha256": HASH,
        "offsite_restored_sha256": HASH,
        "backup_at": "2026-01-02T11:00:00+00:00",
        "restore_at": "2026-01-02T11:10:00+00:00",
        "offsite_restore_at": "2026-01-02T11:20:00+00:00",
        "offsite_encrypted": True,
        "timer_enabled": True,
        "evidence_refs": {
            "backup": f"sha256:{HASH}",
            "restore": f"sha256:{HASH}",
            "offsite": f"sha256:{HASH}",
            "timer": f"sha256:{HASH}",
        },
    }
    value.update(changes)
    return value


def test_accepts_valid_receipt():
    assert evaluate_backup(receipt(), now=NOW, max_age_seconds=86400) == {
        "status": "PASS",
        "reasons": [],
        "executed": False,
    }


def test_reports_hash_mismatch_as_fail():
    result = evaluate_backup(receipt(restored_sha256="b" * 64, timer_enabled=False), now=NOW)
    assert result["status"] == "FAIL"
    assert result["executed"] is False
    assert "hashes do not match" in result["reasons"]


def test_blocks_missing_keys_and_evidence():
    value = receipt()
    del value["timer_enabled"]
    value["evidence_refs"] = {"backup": "bad"}
    assert evaluate_backup(value, now=NOW)["status"] == "BLOCKED"


def test_requires_exact_booleans():
    result = evaluate_backup(receipt(offsite_encrypted=1), now=NOW)
    assert result["status"] == "BLOCKED"
    assert "offsite_encrypted must be a bool" in result["reasons"]


def test_blocks_naive_future_stale_and_out_of_order_timestamps():
    assert evaluate_backup(receipt(backup_at="2026-01-02T11:00:00"), now=NOW)["status"] == "BLOCKED"
    assert evaluate_backup(receipt(backup_at="2026-01-02T13:00:00+00:00"), now=NOW)["status"] == "BLOCKED"
    old = (NOW - timedelta(days=2)).isoformat()
    assert evaluate_backup(receipt(backup_at=old), now=NOW, max_age_seconds=86400)["status"] == "BLOCKED"
    assert evaluate_backup(receipt(restore_at="2026-01-02T10:00:00+00:00"), now=NOW)["status"] == "BLOCKED"


def test_accepts_exact_age_boundary():
    value = receipt(backup_at=(NOW - timedelta(seconds=86400)).isoformat())
    assert evaluate_backup(value, now=NOW, max_age_seconds=86400)["status"] == "PASS"


def test_blocks_invalid_now_and_age():
    assert evaluate_backup(receipt(), now="2026-01-02T12:00:00+00:00")["status"] == "BLOCKED"
    assert evaluate_backup(receipt(), now=NOW, max_age_seconds=-1)["status"] == "BLOCKED"
    assert evaluate_backup(receipt(), now=NOW, max_age_seconds=True)["status"] == "BLOCKED"
