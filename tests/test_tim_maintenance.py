from pathlib import Path

from scripts import tim_maintenance


def test_oversized_logs_only_returns_external_logs_over_limit(tmp_path: Path, monkeypatch) -> None:
    small = tmp_path / "small.log"
    large = tmp_path / "large.err.log"
    small.write_bytes(b"a" * 10)
    large.write_bytes(b"a" * 11)
    monkeypatch.setattr(tim_maintenance, "EXTERNAL_LOGS", (small, large))
    assert tim_maintenance.oversized_logs(10) == [large]


def test_rotation_does_not_stop_runtime_when_no_external_log_is_oversized(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(tim_maintenance, "EXTERNAL_LOGS", (tmp_path / "missing.log",))
    monkeypatch.setattr(tim_maintenance, "local", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not run")))
    assert tim_maintenance.rotate_external_logs(1024) == {"status": "NOT_NEEDED", "oversized_logs": []}


def test_small_gap_filter_excludes_large_historical_ranges() -> None:
    small = {"missing_from_id": 10, "missing_to_id": 20}
    large = {"missing_from_id": 10, "missing_to_id": 10_011}
    assert small["missing_to_id"] - small["missing_from_id"] + 1 <= 10_000
    assert not large["missing_to_id"] - large["missing_from_id"] + 1 <= 10_000
