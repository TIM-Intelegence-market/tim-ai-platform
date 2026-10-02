"""Deterministic-replay checks on a real research bundle (2017-2024).

Every check compares replays of the same stored bundle; nothing reads the network
except optional BTC archive downloads through the research lab's ArchiveStore
(checksum-verified and holdout-locked).

- repeat: the same inputs twice give the same dataset_id, content_hash and output_hash;
- order: reversing observation rows and calendar entries (same facts, other bytes)
  keeps dataset_id and content_hash;
- leakage: at the final replay time every event, record and aligned value was
  available at or before its decision time;
- as-of: for earlier replay times, the full archive and the archive as it stood on
  that day give the same content_hash, so later vintages and releases leak nothing.
  An archive of that day may instead be INSUFFICIENT_DATA (it ends before a date it
  cannot classify yet); then both must agree at its coverage end, and it must never
  give a different answer.
  The as-of archive is derived from the stored download (rows and calendar dates
  after the cut removed, still-valid rows clipped to the cut as the API clips to
  ``realtime_end``); it is a reconstruction, not a second download.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.research_lab.data.archive import ArchiveRef, Dataset, Market
from src.research_lab.data.store import ArchiveStore, months
from src.research_lab.external.alfred import LAST_REALTIME, RawBundle, parse_bundle
from src.research_lab.external.records import AvailabilityBasis, IngestResult, source_spec
from src.research_lab.external.replay import ReplayConfig, run_replay

FINAL_REPLAY_AT = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)  # last instant before the holdout
AS_OF_CUTS = (date(2020, 1, 31), date(2020, 2, 12), date(2022, 6, 30))  # before/around annual revisions
BTC_MONTHS = ((2017, 8), (2024, 12))  # spot archive starts 2017-08 (PROTOKOLL O3)
BTC_INTERVAL = "1h"


def btc_refs() -> list[ArchiveRef]:
    return [ArchiveRef(Market.SPOT, Dataset.KLINES, year, month, BTC_INTERVAL) for year, month in months(*BTC_MONTHS)]


def load_btc(root: Path, *, fetch: bool) -> list:
    store = ArchiveStore(root)
    refs = btc_refs()
    if fetch:
        for ref in refs:
            store.fetch(ref)
    return store.load_klines(refs)


def reordered(bundle: RawBundle) -> RawBundle:
    """Same facts, other bytes: observation rows and calendar entries reversed."""
    payloads = dict(bundle.payloads)
    observations = json.loads(payloads["observations"])
    observations["observations"] = list(reversed(observations["observations"]))
    payloads["observations"] = json.dumps(observations).encode()
    if "release_dates" in payloads:
        calendar = json.loads(payloads["release_dates"])
        calendar["release_dates"] = list(reversed(calendar["release_dates"]))
        payloads["release_dates"] = json.dumps(calendar).encode()
    return replace(bundle, payloads=payloads)


def as_of(bundle: RawBundle, cut: date) -> RawBundle:
    """The archive as a download with realtime_end=cut would have returned it (reconstructed)."""
    end = cut.isoformat()
    payloads = dict(bundle.payloads)
    observations = json.loads(payloads["observations"])
    rows = []
    for row in observations["observations"]:
        if row["realtime_start"] > end:
            continue
        clipped = dict(row)
        if row["realtime_end"] == LAST_REALTIME or row["realtime_end"] > end:
            clipped["realtime_end"] = end
        rows.append(clipped)
    observations.update({"observations": rows, "count": len(rows), "realtime_end": end})
    payloads["observations"] = json.dumps(observations).encode()
    if "release_dates" in payloads:
        calendar = json.loads(payloads["release_dates"])
        calendar["release_dates"] = [item for item in calendar["release_dates"] if item["date"] <= end]
        calendar["count"] = len(calendar["release_dates"])
        payloads["release_dates"] = json.dumps(calendar).encode()
    requests = json.loads(json.dumps(bundle.requests))
    for request in requests.values():
        if "realtime_end" in request:
            request["realtime_end"] = end
    # Downloaded at the end of the cut day in the publisher's time zone: every vintage dated on or
    # before the cut (also end-of-day ones) is available by then, nothing later is.
    spec = source_spec(bundle.source, bundle.source_identifier)
    ingested = spec.available_at(cut, AvailabilityBasis.END_OF_VINTAGE_DAY)
    return replace(bundle, payloads=payloads, requests=requests, ingested_at=min(bundle.ingested_at, ingested))


def leakage(result: dict[str, Any], at: datetime) -> list[str]:
    problems = []
    stamp = at.isoformat()
    for item in result["events"]:
        if item["event"]["available_at"] > stamp:
            problems.append(f"event {item['event']['event_id']} after replay time")
    for row in result["series_rows"]:
        seen = row["external"]["available_at"]
        if seen is not None and seen > row["decision_time"]:
            problems.append(f"row {row['open_time']} uses a value available after its decision time")
    return problems


def _hashes(result: dict[str, Any]) -> dict[str, str]:
    return {key: result[key] for key in ("dataset_id", "content_hash", "output_hash")}


def replay_checks(bundle: RawBundle, ingest: IngestResult, *, btc_root: Path, fetch_btc: bool) -> dict[str, Any]:
    klines = load_btc(btc_root, fetch=fetch_btc)
    # The real spot archive holds defective candles (outages, off-grid opens): research runs exclude and list them.
    config = ReplayConfig(FINAL_REPLAY_AT, BTC_INTERVAL, invalid_candles="exclude")
    first = run_replay(ingest, klines, config)
    second = run_replay(parse_bundle(bundle), klines, config)
    shuffled = run_replay(parse_bundle(reordered(bundle)), klines, config)
    checks: dict[str, Any] = {
        "repeat_identical": _hashes(first) == _hashes(second),
        "reordered_same_dataset_and_content": (first["dataset_id"], first["content_hash"]) == (shuffled["dataset_id"], shuffled["content_hash"]),
        "reordered_output_hash_differs_only_by_payload_provenance": first["provenance"]["payload_sha256"] != shuffled["provenance"]["payload_sha256"],
        "leakage_at_final": leakage(first, FINAL_REPLAY_AT),
    }
    as_of_results = []
    for cut in AS_OF_CUTS:
        at = datetime(cut.year, cut.month, cut.day, 23, 0, tzinfo=timezone.utc)
        cfg = ReplayConfig(at, BTC_INTERVAL, invalid_candles="exclude")
        past_ingest = parse_bundle(as_of(bundle, cut))
        full = run_replay(ingest, klines, cfg)
        past = run_replay(past_ingest, klines, cfg)
        item = {
            "cut": cut.isoformat(),
            "replay_at": at.isoformat(),
            "as_of_coverage_end": past_ingest.coverage_end.isoformat(),
            "content_hash_full": full["content_hash"],
            "content_hash_as_of": past["content_hash"],
            "dataset_id_equal": full["dataset_id"] == past["dataset_id"],
            "leakage": leakage(full, at),
            "events": len(full["events"]),
        }
        if full["content_hash"] == past["content_hash"]:
            item["outcome"] = "EQUAL"
        elif past["state"] == "INSUFFICIENT_DATA" and past_ingest.coverage_end < at:
            # The archive of that day could not answer yet (e.g. a revision date inside its lead); it must
            # agree with the full archive up to its own coverage end and never give a different answer.
            edge = ReplayConfig(past_ingest.coverage_end, BTC_INTERVAL, invalid_candles="exclude")
            same_at_edge = run_replay(ingest, klines, edge)["content_hash"] == run_replay(past_ingest, klines, edge)["content_hash"]
            item["outcome"] = "INSUFFICIENT_DATA" if same_at_edge else "DIFFERENT"
            item["equal_at_coverage_end"] = same_at_edge
        else:
            item["outcome"] = "DIFFERENT"
        item["equal"] = item["outcome"] != "DIFFERENT"
        as_of_results.append(item)
    checks["as_of"] = as_of_results
    # A check without an answer proves nothing: the final replay must be READY, with BTC candles and events.
    checks["answered"] = first["state"] == "READY" and len(klines) > 0 and len(first["events"]) > 0
    passed = (
        checks["answered"]
        and checks["repeat_identical"]
        and checks["reordered_same_dataset_and_content"]
        and not checks["leakage_at_final"]
        and all(item["equal"] and not item["leakage"] for item in as_of_results)
    )
    return {
        "replay_at": FINAL_REPLAY_AT.isoformat(),
        "interval": BTC_INTERVAL,
        "btc_candles": len(klines),
        "btc_completeness": first["inputs"]["btc_completeness"] if "inputs" in first else None,
        "btc_excluded": dict(Counter(item["reason"] for item in first["inputs"].get("btc_excluded", []))) if "inputs" in first else None,
        "state": first["state"],
        "hashes": _hashes(first),
        "events": len(first["events"]),
        "event_status": dict(Counter(item["event"]["status"] for item in first["events"])),
        "series_rows": len(first["series_rows"]),
        "quality_issue_codes": dict(Counter(item["code"] for item in first["quality_issues"])),
        "checks": checks,
        "all_checks_pass": passed,
    }


__all__ = ["AS_OF_CUTS", "FINAL_REPLAY_AT", "as_of", "leakage", "reordered", "replay_checks"]
