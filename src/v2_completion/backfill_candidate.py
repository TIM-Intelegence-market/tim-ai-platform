"""Immutable, non-promoting historical backfill candidate construction."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import zipfile

from src.v2_readiness.backfill import (
    BinanceArchiveRef,
    MARKET,
    parse_official_checksum,
)


UTC = timezone.utc
DATASET_ID = "V2_BACKFILL_CANDIDATE_V1"
SCHEMA_VERSION = "1.0.0"
PARSER_VERSION = "TIM_BINANCE_AGGTRADES_CSV_V1"
IMPORT_VERSION = "TIM_V2_BACKFILL_IMPORT_V1"
USER_AGENT = "TIM-V2-finish-first-backfill/1.0"
PUBLIC_API = "https://api.binance.com/api/v3/aggTrades"


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("gap timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def minute_floor(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(second=0, microsecond=0)


def timestamp_from_binance(value: str) -> datetime:
    raw = int(value)
    divisor = 1_000_000 if raw >= 10**15 else 1_000
    return datetime.fromtimestamp(raw / divisor, tz=UTC)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class GapWindow:
    gap_id: str
    start: datetime
    end: datetime
    severity: str
    root_cause: str

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("gap window timestamps must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("gap window end must follow start")

    @property
    def minutes(self) -> frozenset[datetime]:
        current = minute_floor(self.start)
        end = minute_floor(self.end)
        values: set[datetime] = set()
        while current < end:
            values.add(current)
            current += timedelta(minutes=1)
        return frozenset(values)


def load_gap_windows(path: Path) -> list[GapWindow]:
    values: list[GapWindow] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            values.append(
                GapWindow(
                    gap_id=str(row["gap_id"]),
                    start=parse_time(str(row["start_utc"])),
                    end=parse_time(str(row["end_utc"])),
                    severity=str(row["severity"]),
                    root_cause=str(row["root_cause_class"]),
                )
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid gap-ledger row {line_number}") from exc
    if len({item.gap_id for item in values}) != len(values):
        raise ValueError("gap ledger contains duplicate gap IDs")
    return values


def required_archive_days(gaps: Iterable[GapWindow]) -> list[date]:
    values: set[date] = set()
    for gap in gaps:
        current = gap.start.date()
        last = (gap.end - timedelta(microseconds=1)).date()
        while current <= last:
            values.add(current)
            current += timedelta(days=1)
    return sorted(values)


def gap_minutes(gaps: Iterable[GapWindow]) -> frozenset[datetime]:
    return frozenset(minute for gap in gaps for minute in gap.minutes)


def _fetch_small(url: str, timeout: float) -> tuple[bytes, dict[str, str]]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise HTTPError(url, response.status, "unexpected status", response.headers, None)
        body = response.read(4096)
        headers = {key.lower(): value for key, value in response.headers.items()}
    return body, headers


def _download(url: str, target: Path, timeout: float) -> tuple[int, str]:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    size = 0
    descriptor, name = tempfile.mkstemp(prefix=target.name + ".", suffix=".part", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as output, urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise HTTPError(url, response.status, "unexpected status", response.headers, None)
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
                digest.update(block)
                size += len(block)
            output.flush()
            os.fsync(output.fileno())
        temporary = Path(name)
        if target.exists():
            if target.stat().st_size != size or file_hash(target) != digest.hexdigest():
                raise FileExistsError(f"immutable quarantine archive differs: {target}")
            temporary.unlink()
        else:
            os.replace(temporary, target)
    except Exception:
        Path(name).unlink(missing_ok=True)
        raise
    return size, digest.hexdigest()


def _write_candidate_rows(
    archive: Path,
    target: Path,
    required_minutes: frozenset[datetime],
    expected_day: date,
) -> dict[str, Any]:
    start = datetime.combine(expected_day, datetime.min.time(), tzinfo=UTC)
    end = start + timedelta(days=1)
    selected_minutes: set[datetime] = set()
    selected_ids: set[int] = set()
    archive_rows = 0
    candidate_rows = 0
    invalid_rows = 0
    duplicate_or_out_of_order_ids = 0
    first_id: int | None = None
    last_id: int | None = None
    prior_id: int | None = None
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=target.name + ".", suffix=".part", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as raw_output:
            with gzip.GzipFile(fileobj=raw_output, mode="wb", mtime=0, filename="") as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text_output:
                    writer = csv.writer(text_output, lineterminator="\n")
                    writer.writerow(
                        (
                            "aggregate_trade_id",
                            "price",
                            "quantity",
                            "first_trade_id",
                            "last_trade_id",
                            "trade_time_utc",
                            "buyer_is_maker",
                            "best_price_match",
                            "source_archive",
                        )
                    )
                    with zipfile.ZipFile(archive) as bundle:
                        bad = bundle.testzip()
                        if bad is not None:
                            raise ValueError(f"archive CRC failure: {bad}")
                        members = [item for item in bundle.namelist() if not item.endswith("/")]
                        expected_member = archive.name.removesuffix(".zip") + ".csv"
                        if members != [expected_member]:
                            raise ValueError("archive must contain exactly the expected CSV member")
                        with bundle.open(expected_member) as binary:
                            reader = csv.reader(io.TextIOWrapper(binary, encoding="utf-8", newline=""))
                            for row_number, row in enumerate(reader, 1):
                                if row_number == 1 and row and not row[0].isdigit():
                                    continue
                                archive_rows += 1
                                try:
                                    if len(row) != 8:
                                        raise ValueError("unexpected aggTrades field count")
                                    aggregate_id = int(row[0])
                                    price = Decimal(row[1])
                                    quantity = Decimal(row[2])
                                    first_trade = int(row[3])
                                    last_trade = int(row[4])
                                    trade_time = timestamp_from_binance(row[5])
                                    if price <= 0 or quantity <= 0:
                                        raise ValueError("non-positive market value")
                                    if first_trade > last_trade or aggregate_id < 0:
                                        raise ValueError("invalid trade ID bounds")
                                    if not start <= trade_time < end:
                                        raise ValueError("trade timestamp outside archive day")
                                    if row[6].lower() not in {"true", "false"} or row[7].lower() not in {"true", "false"}:
                                        raise ValueError("invalid boolean field")
                                except (InvalidOperation, ValueError, OverflowError) as exc:
                                    invalid_rows += 1
                                    raise ValueError(
                                        f"invalid archive row {row_number}: {type(exc).__name__}"
                                    ) from exc
                                if prior_id is not None and aggregate_id <= prior_id:
                                    duplicate_or_out_of_order_ids += 1
                                prior_id = aggregate_id
                                first_id = aggregate_id if first_id is None else first_id
                                last_id = aggregate_id
                                minute = minute_floor(trade_time)
                                if minute not in required_minutes:
                                    continue
                                if aggregate_id in selected_ids:
                                    duplicate_or_out_of_order_ids += 1
                                    continue
                                selected_ids.add(aggregate_id)
                                selected_minutes.add(minute)
                                candidate_rows += 1
                                writer.writerow(
                                    (
                                        aggregate_id,
                                        format(price, "f"),
                                        format(quantity, "f"),
                                        first_trade,
                                        last_trade,
                                        iso(trade_time),
                                        row[6].lower(),
                                        row[7].lower(),
                                        archive.name,
                                    )
                                )
            raw_output.flush()
            os.fsync(raw_output.fileno())
        temporary = Path(name)
        candidate_sha = file_hash(temporary)
        candidate_size = temporary.stat().st_size
        if target.exists():
            if file_hash(target) != candidate_sha:
                raise FileExistsError(f"immutable candidate payload differs: {target}")
            temporary.unlink()
        else:
            os.replace(temporary, target)
    except Exception:
        Path(name).unlink(missing_ok=True)
        raise
    if invalid_rows or duplicate_or_out_of_order_ids:
        raise ValueError("archive validation found invalid or duplicate/out-of-order rows")
    return {
        "archive_rows": archive_rows,
        "candidate_rows": candidate_rows,
        "candidate_minutes": sorted(iso(value) for value in selected_minutes),
        "candidate_minute_count": len(selected_minutes),
        "first_aggregate_trade_id": first_id,
        "last_aggregate_trade_id": last_id,
        "invalid_rows": invalid_rows,
        "duplicate_or_out_of_order_ids": duplicate_or_out_of_order_ids,
        "candidate_payload": str(target),
        "candidate_payload_size_bytes": candidate_size,
        "candidate_payload_sha256": candidate_sha,
    }


def _api_request(parameters: dict[str, int | str], timeout: float) -> tuple[bytes, dict[str, str]]:
    url = PUBLIC_API + "?" + urlencode(parameters)
    for attempt in range(4):
        request = Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise HTTPError(url, response.status, "unexpected status", response.headers, None)
                return response.read(), {
                    key.lower(): value for key, value in response.headers.items()
                }
        except HTTPError as exc:
            if exc.code != 429 or attempt == 3:
                raise
            retry = exc.headers.get("Retry-After", "1") if exc.headers else "1"
            time.sleep(min(10.0, max(0.1, float(retry))))
    raise RuntimeError("unreachable API retry state")


def _write_api_candidate_rows(
    *,
    target: Path,
    required_minutes: frozenset[datetime],
    timeout: float,
) -> dict[str, Any]:
    if not required_minutes:
        raise ValueError("API candidate requires at least one missing minute")
    start = min(required_minutes)
    end = max(required_minutes) + timedelta(minutes=1)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000) - 1
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=target.name + ".", suffix=".part", dir=target.parent)
    selected_minutes: set[datetime] = set()
    selected_ids: set[int] = set()
    page_count = 0
    api_rows = 0
    candidate_rows = 0
    duplicate_or_out_of_order_ids = 0
    first_id: int | None = None
    last_id: int | None = None
    prior_id: int | None = None
    response_chain = hashlib.sha256()
    fetched_at = datetime.now(UTC)
    used_weight_max: int | None = None
    try:
        with os.fdopen(descriptor, "wb") as raw_output:
            with gzip.GzipFile(fileobj=raw_output, mode="wb", mtime=0, filename="") as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text_output:
                    writer = csv.writer(text_output, lineterminator="\n")
                    writer.writerow(
                        (
                            "aggregate_trade_id",
                            "price",
                            "quantity",
                            "first_trade_id",
                            "last_trade_id",
                            "trade_time_utc",
                            "buyer_is_maker",
                            "best_price_match",
                            "source_api",
                        )
                    )
                    parameters: dict[str, int | str] = {
                        "symbol": "BTCUSDT",
                        "startTime": start_ms,
                        "endTime": end_ms,
                        "limit": 1000,
                    }
                    while True:
                        body, headers = _api_request(parameters, timeout)
                        page_count += 1
                        response_chain.update(hashlib.sha256(body).digest())
                        weight = headers.get("x-mbx-used-weight-1m")
                        if weight and weight.isdigit():
                            used_weight_max = max(used_weight_max or 0, int(weight))
                        try:
                            page = json.loads(body)
                        except json.JSONDecodeError as exc:
                            raise ValueError("public API returned invalid JSON") from exc
                        if not isinstance(page, list):
                            raise ValueError("public API response must be a list")
                        if not page:
                            break
                        stop = False
                        for row in page:
                            try:
                                aggregate_id = int(row["a"])
                                price = Decimal(str(row["p"]))
                                quantity = Decimal(str(row["q"]))
                                first_trade = int(row["f"])
                                last_trade = int(row["l"])
                                trade_time = timestamp_from_binance(str(row["T"]))
                                buyer_maker = row["m"]
                                best_match = row["M"]
                                if price <= 0 or quantity <= 0:
                                    raise ValueError("non-positive market value")
                                if first_trade > last_trade or aggregate_id < 0:
                                    raise ValueError("invalid API trade ID bounds")
                                if not isinstance(buyer_maker, bool) or not isinstance(best_match, bool):
                                    raise ValueError("invalid API boolean")
                            except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
                                raise ValueError("invalid public aggTrades API row") from exc
                            if trade_time >= end:
                                stop = True
                                break
                            if trade_time < start:
                                raise ValueError("public API returned a row before requested start")
                            if prior_id is not None and aggregate_id != prior_id + 1:
                                duplicate_or_out_of_order_ids += 1
                            prior_id = aggregate_id
                            first_id = aggregate_id if first_id is None else first_id
                            last_id = aggregate_id
                            api_rows += 1
                            minute = minute_floor(trade_time)
                            if minute not in required_minutes:
                                continue
                            if aggregate_id in selected_ids:
                                duplicate_or_out_of_order_ids += 1
                                continue
                            selected_ids.add(aggregate_id)
                            selected_minutes.add(minute)
                            candidate_rows += 1
                            writer.writerow(
                                (
                                    aggregate_id,
                                    format(price, "f"),
                                    format(quantity, "f"),
                                    first_trade,
                                    last_trade,
                                    iso(trade_time),
                                    str(buyer_maker).lower(),
                                    str(best_match).lower(),
                                    "api.binance.com/api/v3/aggTrades",
                                )
                            )
                        if stop or len(page) < 1000:
                            break
                        next_id = int(page[-1]["a"]) + 1
                        parameters = {"symbol": "BTCUSDT", "fromId": next_id, "limit": 1000}
                        if page_count > 10000:
                            raise RuntimeError("public API pagination safety bound exceeded")
            raw_output.flush()
            os.fsync(raw_output.fileno())
        if duplicate_or_out_of_order_ids:
            raise ValueError("public API pagination was not aggregate-ID contiguous")
        temporary = Path(name)
        candidate_sha = file_hash(temporary)
        candidate_size = temporary.stat().st_size
        if target.exists():
            if file_hash(target) != candidate_sha:
                raise FileExistsError(f"immutable API candidate payload differs: {target}")
            temporary.unlink()
        else:
            os.replace(temporary, target)
    except Exception:
        Path(name).unlink(missing_ok=True)
        raise
    return {
        "api_endpoint": PUBLIC_API,
        "api_query_scope": {
            "symbol": "BTCUSDT",
            "start_time_utc": iso(start),
            "end_time_utc": iso(end),
        },
        "api_fetched_at_utc": iso(fetched_at),
        "api_pages": page_count,
        "api_rows": api_rows,
        "api_response_sha256_chain": response_chain.hexdigest(),
        "api_used_weight_1m_max_observed": used_weight_max,
        "candidate_rows": candidate_rows,
        "candidate_minutes": sorted(iso(value) for value in selected_minutes),
        "candidate_minute_count": len(selected_minutes),
        "first_aggregate_trade_id": first_id,
        "last_aggregate_trade_id": last_id,
        "invalid_rows": 0,
        "duplicate_or_out_of_order_ids": duplicate_or_out_of_order_ids,
        "candidate_payload": str(target),
        "candidate_payload_size_bytes": candidate_size,
        "candidate_payload_sha256": candidate_sha,
    }


def build_candidate(
    *,
    gaps: list[GapWindow],
    quarantine_root: Path,
    candidate_root: Path,
    timeout: float = 60.0,
) -> dict[str, Any]:
    started = datetime.now(UTC)
    required = gap_minutes(gaps)
    recovered: set[datetime] = set()
    entries: list[dict[str, Any]] = []
    for trading_day in required_archive_days(gaps):
        reference = BinanceArchiveRef(trading_day)
        base: dict[str, Any] = {
            "url": reference.url,
            "filename": reference.filename,
            "period_start_utc": iso(datetime.combine(trading_day, datetime.min.time(), tzinfo=UTC)),
            "period_end_utc": iso(datetime.combine(trading_day + timedelta(days=1), datetime.min.time(), tzinfo=UTC)),
            "market": MARKET,
            "symbol": reference.symbol,
            "data_type": "BINANCE_SPOT_AGGTRADES",
            "schema": SCHEMA_VERSION,
            "parser_version": PARSER_VERSION,
            "import_version": IMPORT_VERSION,
            "readiness_counted": False,
        }
        try:
            sidecar_bytes, sidecar_headers = _fetch_small(reference.checksum_url, timeout)
            sidecar = sidecar_bytes.decode("ascii")
            official_sha = parse_official_checksum(sidecar, expected_filename=reference.filename)
            archive_path = quarantine_root / reference.filename
            downloaded_at = datetime.now(UTC)
            size, archive_sha = _download(reference.url, archive_path, timeout)
            if archive_sha != official_sha:
                raise ValueError("archive SHA-256 differs from official checksum")
            target = candidate_root / (reference.filename.removesuffix(".zip") + ".gap_rows.csv.gz")
            parsed = _write_candidate_rows(archive_path, target, required, trading_day)
            recovered.update(parse_time(value) for value in parsed.pop("candidate_minutes"))
            entries.append(
                {
                    **base,
                    "status": "IMPORTED_TO_IMMUTABLE_CANDIDATE",
                    "downloaded_at_utc": iso(downloaded_at),
                    "file_size_bytes": size,
                    "sha256": archive_sha,
                    "official_checksum": official_sha,
                    "checksum_validation": "PASS",
                    "sidecar_last_modified": sidecar_headers.get("last-modified"),
                    "quarantine_path": str(archive_path),
                    **parsed,
                }
            )
        except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, ValueError, OSError, zipfile.BadZipFile) as exc:
            missing_for_day = frozenset(
                minute for minute in required if minute.date() == trading_day
            )
            try:
                target = candidate_root / (
                    reference.filename.removesuffix(".zip") + ".api_gap_rows.csv.gz"
                )
                parsed = _write_api_candidate_rows(
                    target=target,
                    required_minutes=missing_for_day,
                    timeout=timeout,
                )
                recovered.update(parse_time(value) for value in parsed.pop("candidate_minutes"))
                entries.append(
                    {
                        **base,
                        "status": "ARCHIVE_UNAVAILABLE_PUBLIC_API_FALLBACK_IMPORTED",
                        "archive_error_type": type(exc).__name__,
                        "downloaded_at_utc": parsed["api_fetched_at_utc"],
                        "file_size_bytes": None,
                        "sha256": None,
                        "official_checksum": None,
                        "checksum_validation": "NOT_APPLICABLE_API_RESPONSE_HASH_CHAIN_USED",
                        **parsed,
                    }
                )
            except (HTTPError, URLError, TimeoutError, ValueError, OSError, RuntimeError) as api_exc:
                entries.append(
                    {
                        **base,
                        "status": "SOURCE_UNAVAILABLE_OR_VALIDATION_FAILED",
                        "downloaded_at_utc": None,
                        "file_size_bytes": None,
                        "sha256": None,
                        "official_checksum": None,
                        "checksum_validation": "NOT_VERIFIED",
                        "archive_error_type": type(exc).__name__,
                        "api_error_type": type(api_exc).__name__,
                    }
                )
    mapping = []
    for gap in gaps:
        present = gap.minutes & recovered
        mapping.append(
            {
                "gap_id": gap.gap_id,
                "expected_minutes": len(gap.minutes),
                "candidate_minutes": len(present),
                "remaining_minutes": len(gap.minutes - recovered),
                "status": "CANDIDATE_COMPLETE" if present == gap.minutes else "CANDIDATE_PARTIAL_OR_UNAVAILABLE",
                "severity": gap.severity,
                "root_cause": gap.root_cause,
            }
        )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "created_at_utc": iso(started),
        "completed_at_utc": iso(datetime.now(UTC)),
        "dataset_properties": [
            "IMMUTABLE",
            "APPEND_ONLY",
            "SEPARATE_FROM_FROZEN_V1",
            "NO_AUTOMATIC_PROMOTION",
        ],
        "source_authority": [
            "OFFICIAL_BINANCE_VISION_PUBLIC_SPOT_ARCHIVES",
            "OFFICIAL_BINANCE_PUBLIC_MARKET_DATA_API",
        ],
        "market": MARKET,
        "symbol": "BTCUSDT",
        "data_type": "AGGTRADES_FOR_MISSING_CLOSED_ONE_MINUTE_WINDOWS",
        "gap_ledger_rows": len(gaps),
        "gap_minutes": len(required),
        "candidate_minutes": len(recovered),
        "remaining_gap_minutes": len(required - recovered),
        "candidate_gap_recovery_coverage": round(len(recovered) / len(required), 6) if required else 1.0,
        "archives": entries,
        "gap_mapping": mapping,
        "frozen_rows_modified": 0,
        "database_rows_written": 0,
        "readiness_counted": False,
        "governance_disposition": "CANDIDATE_READY_FOR_HUMAN_DATASET_GOVERNANCE_REVIEW_NOT_PROMOTED",
    }
    payload["manifest_hash"] = stable_hash(payload)
    return payload


def add_fixed_window_coverage(manifest: dict[str, Any], baseline: dict[str, Any]) -> None:
    live = baseline["coverage"]["product_calculation"]
    expected = int(live["expected_observations"])
    live_valid = int(live["valid_observations"])
    candidate = int(manifest["candidate_minutes"])
    combined = min(expected, live_valid + candidate)
    manifest["coverage_metrics"] = {
        "window_start_utc": live["window_start_utc"],
        "window_end_utc": live["window_end_utc"],
        "frozen_live_capture": {
            "valid_minutes": live_valid,
            "expected_minutes": expected,
            "coverage": float(live["coverage"]),
        },
        "backfill_candidate": {
            "candidate_gap_minutes": candidate,
            "gap_minutes": int(manifest["gap_minutes"]),
            "gap_recovery_coverage": manifest["candidate_gap_recovery_coverage"],
        },
        "backfill_eligible_if_governance_approved": {
            "valid_minutes": combined,
            "expected_minutes": expected,
            "coverage": round(combined / expected, 6) if expected else 0.0,
            "gate_status": "PASS" if expected and combined / expected >= 0.95 else "FAIL",
        },
        "prospective_qualification": {
            "status": "NOT_STARTED_SECURITY_GATE_FAILED",
            "coverage": None,
        },
    }
    manifest["manifest_hash"] = stable_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )
