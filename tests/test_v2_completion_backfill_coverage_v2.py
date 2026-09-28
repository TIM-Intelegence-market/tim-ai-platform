"""Program 3 — data-quality coverage for the backfill candidate builder.

Covers the pure CSV/hash/validation logic with local fixtures and mocked
network responses only. No real network access; no mutation of V2 evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta, date
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import zipfile

import pytest

from src.v2_completion import backfill_candidate as bc
from src.v2_completion.backfill_candidate import (
    GapWindow,
    add_fixed_window_coverage,
    build_candidate,
    file_hash,
    gap_minutes,
    iso,
    load_gap_windows,
    minute_floor,
    parse_time,
    required_archive_days,
    stable_hash,
    timestamp_from_binance,
)

UTC = timezone.utc


class FakeResponse:
    status = 200
    headers = {}

    def __init__(self, body: bytes = b"[]", *, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self._buffer = io.BytesIO(body)
        self.status = status
        if headers:
            self.headers = headers

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _gap(start: str, end: str, name: str = "g1") -> GapWindow:
    return GapWindow(
        gap_id=name,
        start=datetime.fromisoformat(start.replace("Z", "+00:00")),
        end=datetime.fromisoformat(end.replace("Z", "+00:00")),
        severity="P1",
        root_cause="PROCESS_DOWNTIME",
    )


def _archive(tmp_path: Path, day: date, rows: list[list[str]], name: str | None = None) -> Path:
    reference = bc.BinanceArchiveRef(day)
    filename = name or reference.filename
    target = tmp_path / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    csv_name = filename.removesuffix(".zip") + ".csv"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(csv_name, "\n".join(",".join(row) for row in rows) + "\n")
    target.write_bytes(buffer.getvalue())
    return target


def _row(aggregate_id: int, minute: datetime) -> list[str]:
    trade_time = int(minute.timestamp() * 1000)
    return [
        str(aggregate_id),
        "100.5",
        "0.25",
        str(aggregate_id * 10),
        str(aggregate_id * 10),
        str(trade_time),
        "true",
        "true",
    ]


# --- datetime + hash helpers ---


def test_iso_always_returns_utc_z() -> None:
    aware = datetime(2026, 7, 23, 12, 30, 45, tzinfo=timezone(timedelta(hours=2)))
    assert iso(aware) == "2026-07-23T10:30:45Z"


def test_parse_time_requires_aware_input() -> None:
    with pytest.raises(ValueError):
        parse_time("2026-07-23T12:00:00")


def test_minute_floor_utc() -> None:
    value = datetime(2026, 7, 23, 12, 30, 45, 123456, tzinfo=UTC)
    assert minute_floor(value) == datetime(2026, 7, 23, 12, 30, tzinfo=UTC)


def test_stable_hash_is_deterministic_and_order_independent() -> None:
    assert stable_hash({"a": 1, "b": [2, 3]}) == stable_hash({"b": [2, 3], "a": 1})


def test_file_hash_matches_manual_digest(tmp_path: Path) -> None:
    path = tmp_path / "blob"
    payload = b"x" * (1024 * 1024 + 7)
    path.write_bytes(payload)
    assert file_hash(path) == hashlib.sha256(payload).hexdigest()


# --- GapWindow validation ---


def test_gap_window_rejects_naive_or_inverted_bounds() -> None:
    with pytest.raises(ValueError):
        GapWindow("x", datetime(2026, 1, 1), datetime(2026, 1, 2, tzinfo=UTC), "P1", "c")
    with pytest.raises(ValueError):
        GapWindow(
            "x",
            datetime(2026, 1, 2, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
            "P1",
            "c",
        )


def test_gap_window_minutes_include_start_exclude_end() -> None:
    item = _gap("2026-07-23T23:59:30Z", "2026-07-24T00:02:00Z")
    assert len(item.minutes) == 3
    assert datetime(2026, 7, 23, 23, 59, tzinfo=UTC) in item.minutes
    assert datetime(2026, 7, 24, 0, 2, tzinfo=UTC) not in item.minutes


def test_required_archive_days_covers_multiple_days() -> None:
    item = _gap("2026-07-23T23:59:00Z", "2026-07-25T00:00:00Z")
    assert required_archive_days([item]) == [
        date(2026, 7, 23),
        date(2026, 7, 24),
    ]


def test_gap_minutes_union() -> None:
    values = gap_minutes(
        [_gap("2026-07-23T00:00:00Z", "2026-07-23T00:02:00Z"), _gap("2026-07-23T00:01:00Z", "2026-07-23T00:03:00Z")]
    )
    assert len(values) == 3


# --- load_gap_windows ---


def test_load_gap_windows_parses_valid_ledger(tmp_path: Path) -> None:
    path = tmp_path / "gaps.jsonl"
    path.write_text(
        json.dumps(
            {"gap_id": "a", "start_utc": "2026-07-23T00:00:00Z", "end_utc": "2026-07-23T00:01:00Z", "severity": "P1", "root_cause_class": "X"}
        )
        + "\n\n"
    )
    assert len(load_gap_windows(path)) == 1


def test_load_gap_windows_rejects_malformed_row(tmp_path: Path) -> None:
    path = tmp_path / "gaps.jsonl"
    path.write_text('{"gap_id": "broken"}\n')
    with pytest.raises(ValueError, match="invalid gap-ledger row 1"):
        load_gap_windows(path)


# --- _write_candidate_rows (local archive fixture, no network) ---


def test_candidate_rows_are_written_from_archive(tmp_path: Path) -> None:
    day = date(2026, 7, 23)
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    archive = _archive(tmp_path, day, [_row(1000, minute), _row(1001, minute + timedelta(seconds=30))])
    target = tmp_path / "out.csv.gz"
    result = bc._write_candidate_rows(archive, target, frozenset([minute]), day)
    assert result["archive_rows"] == 2
    assert result["candidate_rows"] == 2
    assert result["candidate_minute_count"] == 1
    assert result["first_aggregate_trade_id"] == 1000
    assert result["last_aggregate_trade_id"] == 1001
    assert result["invalid_rows"] == 0
    assert target.exists()
    with gzip.open(target, "rt", encoding="utf-8") as handle:
        lines = list(csv.reader(handle))
    assert lines[0][0] == "aggregate_trade_id"
    assert lines[1][0] == "1000"


def test_candidate_rows_skip_non_required_minutes(tmp_path: Path) -> None:
    day = date(2026, 7, 23)
    other = datetime(2026, 7, 23, 13, 0, tzinfo=UTC)
    archive = _archive(tmp_path, day, [_row(2000, other)])
    target = tmp_path / "out.csv.gz"
    result = bc._write_candidate_rows(archive, target, frozenset([datetime(2026, 7, 23, 12, 0, tzinfo=UTC)]), day)
    assert result["candidate_rows"] == 0
    assert result["candidate_minute_count"] == 0


def test_candidate_rows_reject_duplicate_ids(tmp_path: Path) -> None:
    day = date(2026, 7, 23)
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    archive = _archive(tmp_path, day, [_row(3000, minute), _row(3000, minute + timedelta(seconds=1))])
    target = tmp_path / "out.csv.gz"
    with pytest.raises(ValueError, match="duplicate/out-of-order"):
        bc._write_candidate_rows(archive, target, frozenset([minute]), day)


def test_candidate_rows_reject_invalid_row_count(tmp_path: Path) -> None:
    day = date(2026, 7, 23)
    reference = bc.BinanceArchiveRef(day)
    target = tmp_path / reference.filename
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(reference.filename.removesuffix(".zip") + ".csv", "1,2,3\n")
    target.write_bytes(buffer.getvalue())
    out = tmp_path / "out.csv.gz"
    with pytest.raises(ValueError, match="invalid archive row 1"):
        bc._write_candidate_rows(target, out, frozenset(), day)


def test_candidate_rows_reject_archive_with_extra_members(tmp_path: Path) -> None:
    day = date(2026, 7, 23)
    reference = bc.BinanceArchiveRef(day)
    target = tmp_path / reference.filename
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(reference.filename.removesuffix(".zip") + ".csv", "")
        bundle.writestr("extra.txt", "")
    target.write_bytes(buffer.getvalue())
    with pytest.raises(ValueError, match="exactly the expected CSV member"):
        bc._write_candidate_rows(target, tmp_path / "o.csv.gz", frozenset(), day)


def test_candidate_rows_existing_target_must_match(tmp_path: Path) -> None:
    day = date(2026, 7, 23)
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    archive = _archive(tmp_path, day, [_row(4000, minute)])
    target = tmp_path / "out.csv.gz"
    bc._write_candidate_rows(archive, target, frozenset([minute]), day)
    first = file_hash(target)
    second = bc._write_candidate_rows(archive, target, frozenset([minute]), day)
    assert file_hash(target) == first
    assert second["candidate_payload_sha256"] == first


def test_candidate_rows_reject_existing_target_with_diff(tmp_path: Path) -> None:
    day = date(2026, 7, 23)
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    archive = _archive(tmp_path, day, [_row(5000, minute)])
    target = tmp_path / "out.csv.gz"
    bc._write_candidate_rows(archive, target, frozenset([minute]), day)
    target.write_bytes(b"corrupted")
    with pytest.raises(FileExistsError, match="immutable candidate payload differs"):
        bc._write_candidate_rows(archive, target, frozenset([minute]), day)


# --- _api_request / _write_api_candidate_rows (mocked transport) ---


def test_api_request_retries_on_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            error = bc.HTTPError(request.full_url, 429, "rate limited", {"Retry-After": "1"}, None)
            raise error
        return FakeResponse(b"[]")

    monkeypatch.setattr(bc, "time", type("T", (), {"sleep": staticmethod(lambda _: None)})())
    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    body, headers = bc._api_request({"symbol": "BTCUSDT"}, 1.0)
    assert body == b"[]"
    assert len(calls) == 2


def test_api_request_reraises_non_429(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout):
        raise bc.HTTPError(request.full_url, 500, "boom", {}, None)

    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    with pytest.raises(bc.HTTPError):
        bc._api_request({"symbol": "BTCUSDT"}, 1.0)


def test_write_api_candidate_rows_single_page(monkeypatch: pytest.MonkeyPatch) -> None:
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    trade_ms = int(minute.timestamp() * 1000)
    page = [
        {
            "a": 7000,
            "p": "100.5",
            "q": "0.25",
            "f": 70000,
            "l": 70000,
            "T": str(trade_ms),
            "m": True,
            "M": True,
        }
    ]

    def fake_urlopen(request, timeout):
        return FakeResponse(json.dumps(page).encode(), headers={"x-mbx-used-weight-1m": "5"})

    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    target = Path("/tmp/tim-test-api-out.csv.gz")
    target.unlink(missing_ok=True)
    result = bc._write_api_candidate_rows(target=target, required_minutes=frozenset([minute]), timeout=1.0)
    assert result["api_pages"] == 1
    assert result["candidate_rows"] == 1
    assert result["api_used_weight_1m_max_observed"] == 5
    assert result["candidate_payload_sha256"] == file_hash(target)
    target.unlink(missing_ok=True)


def test_write_api_candidate_rows_paginates_until_small_page(monkeypatch: pytest.MonkeyPatch) -> None:
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    trade_ms = int(minute.timestamp() * 1000)
    pages = [
        [
            {"a": 8000 + i, "p": "1", "q": "1", "f": 8, "l": 8, "T": str(trade_ms), "m": True, "M": True}
            for i in range(1000)
        ],
        [
            {"a": 9000, "p": "1", "q": "1", "f": 9, "l": 9, "T": str(trade_ms), "m": True, "M": True}
        ],
    ]

    def fake_urlopen(request, timeout):
        return FakeResponse(json.dumps(pages.pop(0)).encode())

    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    target = Path("/tmp/tim-test-api-out2.csv.gz")
    target.unlink(missing_ok=True)
    result = bc._write_api_candidate_rows(target=target, required_minutes=frozenset([minute]), timeout=1.0)
    assert result["api_pages"] == 2
    assert result["candidate_rows"] == 1001
    assert result["duplicate_or_out_of_order_ids"] == 0
    target.unlink(missing_ok=True)


def test_write_api_candidate_rows_rejects_empty_required(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one missing minute"):
        bc._write_api_candidate_rows(target=tmp_path / "o.csv.gz", required_minutes=frozenset(), timeout=1.0)


def test_write_api_candidate_rows_rejects_non_contiguous_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    trade_ms = int(minute.timestamp() * 1000)
    page = [
        {"a": 9001, "p": "1", "q": "1", "f": 9, "l": 9, "T": str(trade_ms), "m": True, "M": True},
        {"a": 9005, "p": "1", "q": "1", "f": 9, "l": 9, "T": str(trade_ms), "m": True, "M": True},
    ]

    def fake_urlopen(request, timeout):
        return FakeResponse(json.dumps(page).encode())

    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    target = Path("/tmp/tim-test-api-out3.csv.gz")
    target.unlink(missing_ok=True)
    with pytest.raises(ValueError, match="aggregate-ID contiguous"):
        bc._write_api_candidate_rows(target=target, required_minutes=frozenset([minute]), timeout=1.0)
    target.unlink(missing_ok=True)


# --- build_candidate (mocked network + local archive) ---


def test_build_candidate_archive_success_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    day = date(2026, 7, 23)
    reference = bc.BinanceArchiveRef(day)
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    archive = _archive(tmp_path / "quarantine", day, [_row(100, minute)])

    def fake_fetch_small(url, timeout):
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        return f"{digest} *{reference.filename}".encode(), {"last-modified": "now"}

    def fake_download(url, target, timeout):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read_bytes())
        return archive.stat().st_size, file_hash(target)

    monkeypatch.setattr(bc, "_fetch_small", fake_fetch_small)
    monkeypatch.setattr(bc, "_download", fake_download)
    result = build_candidate(
        gaps=[_gap("2026-07-23T12:00:00Z", "2026-07-23T12:01:00Z")],
        quarantine_root=tmp_path / "quarantine",
        candidate_root=tmp_path / "candidate",
        timeout=1.0,
    )
    assert result["archives"][0]["status"] == "IMPORTED_TO_IMMUTABLE_CANDIDATE"
    assert result["gap_minutes"] == 1
    assert result["candidate_minutes"] == 1
    assert result["candidate_gap_recovery_coverage"] == 1.0
    assert result["governance_disposition"].startswith("CANDIDATE_READY_FOR_HUMAN")
    assert result["frozen_rows_modified"] == 0
    assert result["database_rows_written"] == 0
    assert result["readiness_counted"] is False


def test_build_candidate_api_fallback_when_archive_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    trade_ms = int(minute.timestamp() * 1000)
    page = [{"a": 42, "p": "1", "q": "1", "f": 4, "l": 4, "T": str(trade_ms), "m": True, "M": True}]

    def fake_fetch_small(url, timeout):
        raise bc.URLError("archive not reachable")

    def fake_download(url, target, timeout):
        raise bc.URLError("archive not reachable")

    def fake_urlopen(request, timeout):
        return FakeResponse(json.dumps(page).encode())

    monkeypatch.setattr(bc, "_fetch_small", fake_fetch_small)
    monkeypatch.setattr(bc, "_download", fake_download)
    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    result = build_candidate(
        gaps=[_gap("2026-07-23T12:00:00Z", "2026-07-23T12:01:00Z")],
        quarantine_root=tmp_path / "quarantine",
        candidate_root=tmp_path / "candidate",
        timeout=1.0,
    )
    assert result["archives"][0]["status"] == "ARCHIVE_UNAVAILABLE_PUBLIC_API_FALLBACK_IMPORTED"
    assert result["candidate_minutes"] == 1


def test_build_candidate_both_sources_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_fetch(url, timeout):
        raise bc.URLError("down")

    def fail_download(url, target, timeout):
        raise bc.URLError("down")

    def fail_api(parameters, timeout):
        raise bc.URLError("api down")

    monkeypatch.setattr(bc, "_fetch_small", fail_fetch)
    monkeypatch.setattr(bc, "_download", fail_download)
    monkeypatch.setattr(bc, "_api_request", fail_api)
    result = build_candidate(
        gaps=[_gap("2026-07-23T12:00:00Z", "2026-07-23T12:01:00Z")],
        quarantine_root=tmp_path / "quarantine",
        candidate_root=tmp_path / "candidate",
        timeout=1.0,
    )
    entry = result["archives"][0]
    assert entry["status"] == "SOURCE_UNAVAILABLE_OR_VALIDATION_FAILED"
    assert entry["archive_error_type"] == "URLError"
    assert result["candidate_minutes"] == 0
    assert result["gap_mapping"][0]["status"] == "CANDIDATE_PARTIAL_OR_UNAVAILABLE"


# --- add_fixed_window_coverage ---


def test_add_fixed_window_coverage_gate_status(tmp_path: Path) -> None:
    manifest = {"candidate_minutes": 950, "gap_minutes": 1000, "candidate_gap_recovery_coverage": 0.95, "readiness_counted": False}
    baseline = {
        "coverage": {
            "product_calculation": {
                "window_start_utc": "2026-01-01T00:00:00Z",
                "window_end_utc": "2026-01-01T16:40:00Z",
                "expected_observations": 1000,
                "valid_observations": 40,
                "coverage": 0.04,
            }
        }
    }
    add_fixed_window_coverage(manifest, baseline)
    metrics = manifest["coverage_metrics"]
    assert metrics["frozen_live_capture"]["coverage"] == 0.04
    assert metrics["backfill_candidate"]["candidate_gap_minutes"] == 950
    assert metrics["backfill_eligible_if_governance_approved"]["coverage"] == 0.99
    assert metrics["backfill_eligible_if_governance_approved"]["gate_status"] == "PASS"
    assert metrics["prospective_qualification"]["status"] == "NOT_STARTED_SECURITY_GATE_FAILED"
    assert manifest["readiness_counted"] is False
    assert "manifest_hash" in manifest
    # a recompute must be stable (hash excludes its own field)
    first = manifest["manifest_hash"]
    add_fixed_window_coverage(manifest, baseline)
    assert manifest["manifest_hash"] == first

# --- _fetch_small / _download (real code, mocked transport) ---


def test_fetch_small_returns_body_and_lowercased_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse(b"sidecar", headers={"Last-Modified": "Tue, 22 Jul 2026", "X-Foo": "bar"})

    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    body, headers = bc._fetch_small("https://example.test/checksum", 1.0)
    assert body == b"sidecar"
    assert headers == {"last-modified": "Tue, 22 Jul 2026", "x-foo": "bar"}


def test_fetch_small_raises_on_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout):
        raise bc.HTTPError(request.full_url, 404, "missing", {}, None)

    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    with pytest.raises(bc.HTTPError):
        bc._fetch_small("https://example.invalid/checksum", 1.0)


def test_download_writes_target_and_returns_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"archive-bytes-" * (1024 * 1024 // 14)

    def fake_urlopen(request, timeout):
        return FakeResponse(payload, headers={})

    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    target = tmp_path / "sub" / "download.zip"
    size, digest = bc._download("https://example.invalid/data.zip", target, 1.0)
    assert size == len(payload)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert target.read_bytes() == payload


def test_download_matches_existing_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"same-content"
    target = tmp_path / "existing.zip"
    target.write_bytes(payload)

    def fake_urlopen(request, timeout):
        return FakeResponse(payload)

    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    size, digest = bc._download("https://example.invalid/data.zip", target, 1.0)
    assert size == len(payload)


def test_download_rejects_immutable_target_difference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "existing.zip"
    target.write_bytes(b"original-content")

    def fake_urlopen(request, timeout):
        return FakeResponse(b"different-content")

    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    with pytest.raises(FileExistsError, match="immutable quarantine archive differs"):
        bc._download("https://example.invalid/data.zip", target, 1.0)


def test_download_raises_on_http_error_and_cleans_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout):
        raise bc.HTTPError(request.full_url, 500, "boom", {}, None)

    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    target = tmp_path / "download.zip"
    with pytest.raises(bc.HTTPError):
        bc._download("https://example.invalid/data.zip", target, 1.0)
    assert not target.exists()
    assert not list(tmp_path.glob("*.part"))


# --- remaining archive validation branches ---


def test_candidate_rows_skips_header_line(tmp_path: Path) -> None:
    day = date(2026, 7, 23)
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    reference = bc.BinanceArchiveRef(day)
    archive = tmp_path / reference.filename
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(
            reference.filename.removesuffix(".zip") + ".csv",
            "aggregate_trade_id,price,quantity\n"
            + ",".join(_row(1234, minute)) + "\n",
        )
    archive.write_bytes(buffer.getvalue())
    result = bc._write_candidate_rows(archive, tmp_path / "o.csv.gz", frozenset([minute]), day)
    assert result["archive_rows"] == 1
    assert result["candidate_rows"] == 1


def test_write_candidate_rows_rejects_bad_fields(tmp_path: Path) -> None:
    day = date(2026, 7, 23)
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    trade_ms = str(int(minute.timestamp() * 1000))
    cases = {
        "negative_price": ["6000", "-1", "0.25", "6", "6", trade_ms, "true", "true"],
        "bad_id_bounds": ["6000", "1", "0.25", "9", "6", trade_ms, "true", "true"],
        "bad_boolean": ["6000", "1", "0.25", "6", "6", trade_ms, "truthy", "true"],
        "out_of_day_minute": ["6000", "1", "0.25", "6", "6", str(int(datetime(2026, 7, 24, 0, 0, tzinfo=UTC).timestamp() * 1000)), "true", "true"],
    }
    for case, row in cases.items():
        archive = tmp_path / (case + ".zip")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            bundle.writestr(case + ".csv", ",".join(row) + "\n")
        archive.write_bytes(buffer.getvalue())
        with pytest.raises(ValueError, match="invalid archive row"):
            bc._write_candidate_rows(archive, tmp_path / f"{case}.csv.gz", frozenset([minute]), day)


# --- remaining public-API branches ---


def test_api_request_raises_on_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout):
        raise bc.HTTPError(request.full_url, 403, "forbidden", {}, None)

    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    with pytest.raises(bc.HTTPError):
        bc._api_request({"symbol": "BTCUSDT"}, 1.0)


def test_write_api_candidate_rows_rejects_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)

    def fake_urlopen(request, timeout):
        return FakeResponse(b"{not json")

    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    with pytest.raises(ValueError, match="invalid JSON"):
        bc._write_api_candidate_rows(target=Path("/tmp/api-bad-json.csv.gz"), required_minutes=frozenset([minute]), timeout=1.0)


def test_write_api_candidate_rows_rejects_non_list(monkeypatch: pytest.MonkeyPatch) -> None:
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)

    def fake_urlopen(request, timeout):
        return FakeResponse(b'{"a": 1}')

    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    with pytest.raises(ValueError, match="must be a list"):
        bc._write_api_candidate_rows(target=Path("/tmp/api-not-list.csv.gz"), required_minutes=frozenset([minute]), timeout=1.0)


def test_write_api_candidate_rows_empty_page_breaks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)

    def fake_urlopen(request, timeout):
        return FakeResponse(b"[]")

    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    target = tmp_path / "api-empty.csv.gz"
    result = bc._write_api_candidate_rows(target=target, required_minutes=frozenset([minute]), timeout=1.0)
    assert result["api_pages"] == 1
    assert result["candidate_rows"] == 0


def test_write_api_candidate_rows_rejects_bad_value_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    trade_ms = str(int(minute.timestamp() * 1000))
    bad_rows = [
        {"a": 1, "p": "0", "q": "1", "f": 1, "l": 1, "T": trade_ms, "m": True, "M": True},
        {"a": 1, "p": "1", "q": "1", "f": 9, "l": 1, "T": trade_ms, "m": True, "M": True},
        {"a": 1, "p": "1", "q": "1", "f": 1, "l": 1, "T": trade_ms, "m": "not-bool", "M": True},
    ]
    for idx, bad in enumerate(bad_rows):
        def fake_urlopen(request, timeout, row=bad):
            return FakeResponse(json.dumps([row]).encode())

        monkeypatch.setattr(bc, "urlopen", fake_urlopen)
        with pytest.raises(ValueError, match="invalid public aggTrades API row"):
            bc._write_api_candidate_rows(target=Path(f"/tmp/api-bad-row-{idx}.csv.gz"), required_minutes=frozenset([minute]), timeout=1.0)


def test_write_api_candidate_rows_stops_at_end_and_rejects_before_start(monkeypatch: pytest.MonkeyPatch) -> None:
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    end_ms = int((minute + timedelta(minutes=1)).timestamp() * 1000)
    before_ms = int((minute - timedelta(minutes=1)).timestamp() * 1000)
    page_at_end = [{"a": 5, "p": "1", "q": "1", "f": 5, "l": 5, "T": str(end_ms), "m": True, "M": True}]
    page_before = [{"a": 5, "p": "1", "q": "1", "f": 5, "l": 5, "T": str(before_ms), "m": True, "M": True}]

    monkeypatch.setattr(bc, "urlopen", lambda req, timeout: FakeResponse(json.dumps(page_at_end).encode()))
    result = bc._write_api_candidate_rows(target=Path("/tmp/api-end.csv.gz"), required_minutes=frozenset([minute]), timeout=1.0)
    assert result["candidate_rows"] == 0

    monkeypatch.setattr(bc, "urlopen", lambda req, timeout: FakeResponse(json.dumps(page_before).encode()))
    with pytest.raises(ValueError, match="before requested start"):
        bc._write_api_candidate_rows(target=Path("/tmp/api-before.csv.gz"), required_minutes=frozenset([minute]), timeout=1.0)


def test_write_api_candidate_rows_skips_non_required_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    m0 = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    m6 = datetime(2026, 7, 23, 12, 6, tzinfo=UTC)
    mid = datetime(2026, 7, 23, 12, 3, tzinfo=UTC)
    page = [
        {"a": 100, "p": "1", "q": "1", "f": 1, "l": 1, "T": str(int(mid.timestamp() * 1000)), "m": True, "M": True},
        {"a": 101, "p": "1", "q": "1", "f": 1, "l": 1, "T": str(int(m0.timestamp() * 1000)), "m": True, "M": True},
    ]

    monkeypatch.setattr(bc, "urlopen", lambda req, timeout: FakeResponse(json.dumps(page).encode()))
    target = Path("/tmp/api-skip-nonreq.csv.gz")
    target.unlink(missing_ok=True)
    result = bc._write_api_candidate_rows(target=target, required_minutes=frozenset([m0, m6]), timeout=1.0)
    assert result["api_rows"] == 2
    assert result["candidate_rows"] == 1
    assert result["candidate_minute_count"] == 1
    target.unlink(missing_ok=True)


def test_write_api_candidate_rows_rejects_existing_target_difference(monkeypatch: pytest.MonkeyPatch) -> None:
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    trade_ms = str(int(minute.timestamp() * 1000))
    page_a = [{"a": 1, "p": "1", "q": "1", "f": 1, "l": 1, "T": trade_ms, "m": True, "M": True}]
    page_b = [{"a": 2, "p": "2", "q": "2", "f": 2, "l": 2, "T": trade_ms, "m": True, "M": True}]

    monkeypatch.setattr(bc, "urlopen", lambda req, timeout: FakeResponse(json.dumps(page_a).encode()))
    target = Path("/tmp/api-exists.csv.gz")
    target.unlink(missing_ok=True)
    bc._write_api_candidate_rows(target=target, required_minutes=frozenset([minute]), timeout=1.0)
    monkeypatch.setattr(bc, "urlopen", lambda req, timeout: FakeResponse(json.dumps(page_b).encode()))
    with pytest.raises(FileExistsError, match="immutable API candidate payload differs"):
        bc._write_api_candidate_rows(target=target, required_minutes=frozenset([minute]), timeout=1.0)
    target.unlink(missing_ok=True)


def test_build_candidate_rejects_checksum_mismatch_then_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    day = date(2026, 7, 23)
    reference = bc.BinanceArchiveRef(day)
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    trade_ms = str(int(minute.timestamp() * 1000))
    page = [{"a": 77, "p": "1", "q": "1", "f": 7, "l": 7, "T": trade_ms, "m": True, "M": True}]

    def fake_fetch_small(url, timeout):
        wrong = hashlib.sha256(b"not-the-archive").hexdigest()
        return f"{wrong} *{reference.filename}".encode(), {}

    def fake_download(url, target, timeout):
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = b"real-archive-bytes"
        target.write_bytes(payload)
        return len(payload), hashlib.sha256(payload).hexdigest()

    def fake_urlopen(request, timeout):
        return FakeResponse(json.dumps(page).encode())

    monkeypatch.setattr(bc, "_fetch_small", fake_fetch_small)
    monkeypatch.setattr(bc, "_download", fake_download)
    monkeypatch.setattr(bc, "urlopen", fake_urlopen)
    result = build_candidate(
        gaps=[_gap("2026-07-23T12:00:00Z", "2026-07-23T12:01:00Z")],
        quarantine_root=tmp_path / "quarantine",
        candidate_root=tmp_path / "candidate",
        timeout=1.0,
    )
    assert result["archives"][0]["status"] == "ARCHIVE_UNAVAILABLE_PUBLIC_API_FALLBACK_IMPORTED"
    assert result["archives"][0]["archive_error_type"] == "ValueError"


# --- response status branches + true duplicate ---


def test_fetch_small_raises_on_response_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bc, "urlopen", lambda req, timeout: FakeResponse(b"", status=404))
    with pytest.raises(bc.HTTPError, match="unexpected status"):
        bc._fetch_small("https://example.invalid/x", 1.0)


def test_download_raises_on_response_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bc, "urlopen", lambda req, timeout: FakeResponse(b"", status=500))
    with pytest.raises(bc.HTTPError, match="unexpected status"):
        bc._download("https://example.invalid/x", tmp_path / "x.zip", 1.0)


def test_api_request_raises_on_response_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bc, "urlopen", lambda req, timeout: FakeResponse(b"", status=503))
    with pytest.raises(bc.HTTPError, match="unexpected status"):
        bc._api_request({"symbol": "BTCUSDT"}, 1.0)


def test_write_api_candidate_rows_detects_true_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    minute = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    trade_ms = str(int(minute.timestamp() * 1000))
    page = [
        {"a": 101, "p": "1", "q": "1", "f": 1, "l": 1, "T": trade_ms, "m": True, "M": True},
        {"a": 101, "p": "1", "q": "1", "f": 1, "l": 1, "T": trade_ms, "m": True, "M": True},
    ]

    monkeypatch.setattr(bc, "urlopen", lambda req, timeout: FakeResponse(json.dumps(page).encode()))
    with pytest.raises(ValueError, match="aggregate-ID contiguous"):
        bc._write_api_candidate_rows(target=Path("/tmp/api-true-dup.csv.gz"), required_minutes=frozenset([minute]), timeout=1.0)
