#!/usr/bin/env python3
"""Probe official Binance Spot aggTrade archives without importing data."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.v2_readiness.backfill import BinanceArchiveRef, MARKET, parse_official_checksum


UTC = timezone.utc


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def date_range(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("end date must not precede start date")
    return [start + timedelta(days=index) for index in range((end - start).days + 1)]


def fetch_text(url: str, timeout: float) -> tuple[str, dict[str, str]]:
    request = Request(url, headers={"User-Agent": "TIM-V2-readiness-audit/1.0"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise HTTPError(url, response.status, "unexpected status", response.headers, None)
        payload = response.read(4096)
        headers = {key.lower(): value for key, value in response.headers.items()}
    return payload.decode("ascii"), headers


def probe(day: date, timeout: float) -> dict[str, Any]:
    reference = BinanceArchiveRef(day)
    base = {
        "trading_date": day.isoformat(),
        "market": MARKET,
        "instrument": reference.symbol,
        "data_type": "BINANCE_SPOT_AGGTRADES_ARCHIVE",
        "archive_url": reference.url,
        "checksum_url": reference.checksum_url,
        "imported": False,
        "readiness_counted": False,
        "governance_disposition": "REVIEW_REQUIRED_BEFORE_ANY_DOWNLOAD_OR_IMPORT",
    }
    try:
        sidecar, headers = fetch_text(reference.checksum_url, timeout)
        digest = parse_official_checksum(sidecar, expected_filename=reference.filename)
    except (HTTPError, URLError, TimeoutError, ValueError, UnicodeDecodeError) as exc:
        return {
            **base,
            "archive_availability": "NOT_PROBED",
            "checksum_sidecar_available": False,
            "checksum_sidecar_status": "UNAVAILABLE_OR_UNVERIFIED",
            "probe_error_type": type(exc).__name__,
            "official_sha256": None,
        }
    return {
        **base,
        "archive_availability": "NOT_PROBED",
        "checksum_sidecar_available": True,
        "checksum_sidecar_status": "AVAILABLE_AND_FILENAME_BOUND_CHECKSUM_PARSED",
        "official_sha256": digest,
        "sidecar_sha256": hashlib.sha256(sidecar.encode("ascii")).hexdigest(),
        "last_modified": headers.get("last-modified"),
        "sidecar_content_length": int(headers["content-length"]) if headers.get("content-length", "").isdigit() else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/v2_readiness/backfill_source_probe.json",
    )
    args = parser.parse_args()
    started = datetime.now(UTC)
    entries = [probe(day, args.timeout) for day in date_range(args.start_date, args.end_date)]
    payload = {
        "schema_version": "1.0.0",
        "probe_started_at_utc": iso(started),
        "probe_finished_at_utc": iso(datetime.now(UTC)),
        "source_authority": "OFFICIAL_BINANCE_PUBLIC_DATA",
        "operation": "CHECKSUM_SIDECAR_PROBE_ONLY",
        "raw_archives_downloaded": 0,
        "database_rows_written": 0,
        "reason_not_imported": "Existing V2 governance requires a prospective window and prohibits retroactive readiness assertions; an explicit human scope decision is required.",
        "entries": entries,
    }
    payload["manifest_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    atomic_write(args.output, payload)
    available = sum(bool(item["checksum_sidecar_available"]) for item in entries)
    print(json.dumps({"available": available, "total": len(entries), "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
