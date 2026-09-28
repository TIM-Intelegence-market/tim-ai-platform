"""Accounting for a frozen persisted-event collection, never inferred ingress.

Raw rows prove storage, not how many messages arrived. Lifetime counters and
inventory deltas are retained as context and cannot supply collection ingress.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping, Sequence


STATUSES = ("COMPLETED", "PENDING", "PROCESSING", "RETRY", "QUARANTINED")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def baseline_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, int]:
    """Subtract only two observations of the exact same run and counter scope.

    This function is for monotonic counters, not queue gauges. A reset, missing
    counter, or a different run is not interpreted as a zero delta.
    """
    if any(before.get(k) != after.get(k) or before.get(k) is None for k in ("collection_id", "scope")):
        raise ValueError("baseline scope/collection mismatch")
    if set(before["counters"]) != set(after["counters"]):
        raise ValueError("baseline counter set changed")
    result = {}
    for key, value in before["counters"].items():
        end = after["counters"][key]
        if any(type(n) is not int or n < 0 for n in (value, end)) or end < value:
            raise ValueError("counter reset or invalid counter")
        result[key] = end - value
    return result


def persisted_accounting(collection_id: str, rows: Sequence[Mapping[str, Any]], *, max_events: int,
                         requested_start: int | None, requested_end: int | None,
                         captured_at: str) -> dict[str, Any]:
    """Freeze membership from raw rows selected without an outbox-status filter."""
    ids = [int(row["aggregate_trade_id"]) for row in rows]
    if type(max_events) is not int or not 0 < max_events <= 10000:
        raise ValueError("max_events must be between 1 and 10000")
    if len(ids) > max_events or ids != sorted(set(ids)):
        raise ValueError("unbounded or duplicate collection membership")
    if any((requested_start is not None and i < requested_start) or
           (requested_end is not None and i > requested_end) for i in ids):
        raise ValueError("event outside requested boundary")
    statuses = {key: 0 for key in STATUSES}
    completed_ids, missing_ids = [], []
    for row in rows:
        status = row["status"]
        if status in statuses:
            statuses[status] += 1
        if (status == "COMPLETED" and row.get("completed_at") is not None
                and row.get("output_hash") is not None):
            completed_ids.append(int(row["aggregate_trade_id"]))
        elif status is None:
            missing_ids.append(int(row["aggregate_trade_id"]))
    membership_hash = digest(ids)
    contract = {
        "collection_id": collection_id, "kind": "PERSISTED_SNAPSHOT_AUDIT",
        "boundary_axis": "aggregate_trade_id", "bounds": "inclusive",
        "requested_start": requested_start, "requested_end": requested_end,
        "actual_start": min(ids) if ids else None, "actual_end": max(ids) if ids else None,
        "selection": "latest raw events within requested bounds, independent of worker status",
        "max_events": max_events, "captured_at": captured_at,
        "event_ids": ids, "event_ids_hash": membership_hash,
        "first_event": dict(rows[0]) if rows else None,
        "last_event": dict(rows[-1]) if rows else None,
    }
    return {
        "version": 2, "contract": contract,
        "counts": {"events_received": None, "events_unique": len(ids),
                   "events_processed": len(completed_ids), "duplicates": None,
                   "invalid_events": None, "rejected_events": None},
        "status_counts": statuses, "completed_event_ids": completed_ids,
        "missing_outbox_event_ids": missing_ids,
        "collection_baseline": {"collection_id": collection_id,
            "scope": {"event_ids_hash": membership_hash, "worker": "CANDLE_V1"},
            "captured_at": captured_at, "status_counts": statuses.copy()},
        "ingress_evidence": "UNAVAILABLE: no per-collection receipt ledger or historical baseline",
        "processed_definition": "CANDLE_V1 outbox COMPLETED with completed_at and output_hash; not candle closure or downstream finalization",
    }


def accounting_checks(accounting: Mapping[str, Any], counts: Mapping[str, Any],
                      collection_id: str) -> dict[str, str]:
    contract = accounting.get("contract", {})
    ids = contract.get("event_ids", [])
    completed = accounting.get("completed_event_ids", [])
    boundary = (contract.get("collection_id") == collection_id and bool(ids)
                and ids == sorted(set(ids)) and len(ids) <= contract.get("max_events", 0)
                and digest(ids) == contract.get("event_ids_hash")
                and contract.get("actual_start") == min(ids)
                and contract.get("actual_end") == max(ids)
                and all((contract.get("requested_start") is None or i >= contract["requested_start"])
                        and (contract.get("requested_end") is None or i <= contract["requested_end"]) for i in ids))
    baseline = accounting.get("collection_baseline", {})
    boundary = boundary and baseline.get("collection_id") == collection_id and baseline.get("scope", {}).get("event_ids_hash") == digest(ids)
    # Matching cardinalities alone do not prove the same events were processed.
    processed = (boundary and counts["events_unique"] == len(ids)
                 and len(completed) == len(set(completed)) and set(completed) == set(ids)
                 and counts["events_processed"] == len(completed))
    # Optional independently captured ingress evidence must be bound to this
    # exact contract. A persisted snapshot alone deliberately fails this gate.
    ingress = accounting.get("ingress", {})
    names = ("events_received", "events_unique", "duplicates", "invalid_events", "rejected_events")
    known = all(type(counts.get(k)) is int and counts[k] >= 0 for k in names)
    ingress_bound = receipt_evidence_matches(ingress, counts, collection_id, ids)
    balanced = (known and counts["events_received"] == sum(counts[k] for k in names[1:]))
    return {"collection_boundary": "PASS" if boundary else "FAIL",
            "counts_accounted": "PASS" if boundary and ingress_bound and balanced else "FAIL",
            "all_unique_events_processed": "PASS" if processed else "FAIL"}


def receipt_evidence_matches(ingress: Mapping[str, Any], counts: Mapping[str, Any],
                             collection_id: str, ids: list[int]) -> bool:
    """Require disjoint receipt dispositions and exact accepted-event membership.

    A receipt is a message occurrence; an event ID is an immutable market event.
    Rejected/invalid receipts need not have an event ID, but must have a receipt
    ID and a timestamp inside the same [start,end) capture interval.
    """
    if (ingress.get("collection_id") != collection_id or ingress.get("event_ids_hash") != digest(ids)
            or ingress.get("evidence_kind") != "COLLECTION_RECEIPT_LEDGER"):
        return False
    try:
        start, end = (datetime.fromisoformat(ingress[k]) for k in ("requested_start", "requested_end"))
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            return False
        receipts = ingress["receipts"]
        receipt_ids, accepted = set(), set()
        disposition_counts = {"UNIQUE": 0, "DUPLICATE": 0, "INVALID": 0, "REJECTED": 0}
        for item in receipts:
            timestamp = datetime.fromisoformat(item["received_at"])
            key, outcome = item["receipt_id"], item["disposition"]
            if (item["collection_id"] != collection_id or not key or key in receipt_ids
                    or timestamp.tzinfo is None or not start <= timestamp < end
                    or outcome not in disposition_counts):
                return False
            receipt_ids.add(key)
            disposition_counts[outcome] += 1
            if outcome in {"UNIQUE", "DUPLICATE"} and item.get("event_id") not in ids:
                return False
            if outcome == "UNIQUE":
                if item["event_id"] in accepted:
                    return False
                accepted.add(item["event_id"])
        return (accepted == set(ids) and len(receipts) == counts["events_received"]
                and disposition_counts == {"UNIQUE": counts["events_unique"], "DUPLICATE": counts["duplicates"],
                    "INVALID": counts["invalid_events"], "REJECTED": counts["rejected_events"]})
    except (KeyError, TypeError, ValueError):
        return False
