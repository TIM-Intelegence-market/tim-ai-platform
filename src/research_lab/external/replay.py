"""Deterministic replay: one research-ready dataset for one replay time.

The output depends only on the ingested payload, the BTC candles, the config and
the code versions. It never reads the wall clock, the network or randomness. At
replay time T only records, events, candles and quality issues available at or
before T appear, so a later revision cannot change an earlier replay's content.

``content_hash`` covers the research content (rows, events, config). ``output_hash``
also covers provenance (payload hashes, ingestion time), which truthfully differs
between two ingestions of the same archive.
"""
from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.research_lab.data.parse import Kline
from src.research_lab.data.store import HoldoutLocked, HoldoutPermission
from src.research_lab.external.align import HORIZONS, BtcSeries, align_event, align_series
from src.research_lab.external.events import release_events
from src.research_lab.external.pit import PointInTimeStore
from src.research_lab.external.records import TRANSFORM_VERSION, IngestResult, QualityState, iso, require_utc, utc_to_ms
from src.research_lab.protocol import HOLDOUT_START_MS, PROTOCOL_VERSION
from src.research_ops.audit import digest

SCHEMA_VERSION = "1.0.0"
MODE = "RESEARCH"


@dataclass(frozen=True, slots=True)
class ReplayConfig:
    replay_at: datetime
    interval: str = "1h"
    horizons: tuple[str, ...] = tuple(HORIZONS)

    def __post_init__(self) -> None:
        require_utc(self.replay_at, "replay_at")
        unknown = [name for name in self.horizons if name not in HORIZONS]
        if unknown:
            raise ValueError(f"unknown horizon(s): {unknown}")

    def to_dict(self) -> dict[str, Any]:
        return {"replay_at": iso(self.replay_at), "interval": self.interval, "horizons": list(self.horizons)}


def run_replay(
    ingest: IngestResult,
    klines: Sequence[Kline],
    config: ReplayConfig,
    *,
    permission: HoldoutPermission | None = None,
) -> dict[str, Any]:
    at = require_utc(config.replay_at, "replay_at")
    if permission is None and utc_to_ms(at) >= HOLDOUT_START_MS:
        # Protocol 3.2: nothing from the holdout period is replayed before R6, external data included.
        raise HoldoutLocked("replay time lies in the protocol holdout; replay needs the holdout permission")
    spec = ingest.spec
    issues = [item.to_dict() for item in ingest.issues if item.available_at is None or item.available_at <= at]
    header: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "transform_version": TRANSFORM_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "mode": MODE,
        "config": config.to_dict(),
        "source": spec.to_dict(),
    }
    provenance = {
        "payload_sha256": dict(sorted(ingest.payload_hashes.items())),
        "request": copy.deepcopy(ingest.request),
        "ingested_at": iso(ingest.ingested_at),
        "coverage_end": iso(ingest.coverage_end),
    }
    if ingest.state is not QualityState.READY:
        content = {**header, "state": ingest.state.value, "quality_issues": issues, "series_rows": [], "events": []}
        # No inputs were read: the dataset is the payload that failed, so its identity is that payload.
        return _finish(content, provenance, {"state": ingest.state.value, "quality_issues": issues, "payload_sha256": provenance["payload_sha256"]})

    store = PointInTimeStore(ingest)
    btc = BtcSeries.build(klines, config.interval, replay_at=at, permission=permission)
    visible = store.visible_records(at)
    events = release_events(store, until=at)
    aligned = [align_event(event, btc, replay_at=at, horizons=config.horizons, permission=permission) for event in events]
    rows = align_series(store, btc)
    state = QualityState.READY
    if store.latest(at).status.value in {"INSUFFICIENT_DATA", "NOT_AVAILABLE"} or not btc.klines:
        state = QualityState.INSUFFICIENT_DATA
    content = {
        **header,
        "state": state.value,
        "inputs": {
            "external_record_ids": [record.record_id for record in visible],
            "external_records_hash": digest([_content_record(record.to_dict()) for record in visible]),
            # Unusable entries change results (UNKNOWN instead of a value), so they are part of the identity.
            "external_unusable": [
                {"period_start": item.period_start.isoformat(), "vintage": item.vintage.isoformat(), "available_at": iso(item.available_at), "reason": item.reason}
                for item in store.visible_unusable(at)
            ],
            "btc_candles": len(btc.klines),
            "btc_hash": digest([[k.open_time, repr(k.open), repr(k.high), repr(k.low), repr(k.close), repr(k.volume), k.close_time, repr(k.taker_buy_volume)] for k in btc.klines]),
            "btc_completeness": btc.gaps(),
        },
        "quality_issues": issues,
        "latest": store.latest(at).to_dict(),
        "events": [{"event": event.to_dict(), "btc": alignment} for event, alignment in zip(events, aligned)],
        "series_rows": rows,
    }
    identity = {
        "state": state.value,
        # Findings dated at or before T (e.g. a duplicate kept once) are part of what this dataset says.
        "quality_issues": issues,
        # Coverage and missing first prints change results without changing the visible records. The coverage
        # end enters only when it cuts the replay, so re-ingesting the same archive later keeps the identity.
        "coverage_end": iso(ingest.coverage_end) if ingest.coverage_end < at else None,
        "periods_without_first_release": sorted(
            period.isoformat() for period in ingest.periods_without_first_release if store.first_entry(period).available_at <= at
        ),
    }
    return _finish(content, provenance, identity)


def _content_record(record: dict[str, Any]) -> dict[str, Any]:
    # Ingestion time and payload hash are provenance, not research content. vintage_end is left out as
    # well: it describes the next vintage rather than this record.
    return {key: value for key, value in record.items() if key not in {"ingested_at", "payload_sha256", "vintage_end"}}


def _finish(content: dict[str, Any], provenance: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    content_hash = digest(content)
    dataset_id = digest(
        {"config": content["config"], "source": content["source"], "inputs": content.get("inputs"), "transform_version": content["transform_version"], "identity": identity}
    )
    result = {**content, "dataset_id": dataset_id, "content_hash": content_hash, "provenance": provenance}
    result["output_hash"] = digest(result)
    return result


__all__ = ["MODE", "SCHEMA_VERSION", "ReplayConfig", "run_replay"]
