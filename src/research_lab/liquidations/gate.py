"""Outcome-blind count of valid S12 windows (package L3; pre-registration 3.3 and 6).

A window [t, t + 6 h) is valid when

1. its frozen heatmap state exists and is valid (``snapshots.compute``),
2. the primary feed (Binance) was covered for at least 99 % of the window, and
3. at least one counted Binance BTCUSDT liquidation (``X = FILLED``, duplicates once) has its
   exchange time ``T`` inside the window.

Only these counts are computed. Where the liquidations fell relative to the heatmap (the
measure D of section 5) is never read here.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import events, snapshots, store

PRIMARY = events.BINANCE
MIN_COVERAGE = 0.99
PLANNED_DAYS = 56
EXTENDED_DAYS = 84
GATE_DAY = 14
MIN_VALID_WINDOWS = 150
WINDOWS_PER_DAY = 24 // snapshots.WINDOW_HOURS
RECEIVE_SLACK = timedelta(minutes=5)
NS = store.NS_PER_S


@dataclass
class WindowCount:
    t: str
    valid: bool
    reasons: list[str] = field(default_factory=list)
    coverage: float = 0.0
    events: int = 0
    not_filled: int = 0


def window_events(root: Path, t: datetime, venue: str = PRIMARY,
                  not_counted: list[events.LiquidationEvent] | None = None) -> list[events.LiquidationEvent]:
    """Counted events of ``venue`` (BTCUSDT) with exchange time inside the window.

    Events in the window that do not count (status other than ``FILLED``) go to ``not_counted``.
    """
    start_ms = int(t.timestamp() * 1000)
    end_ms = start_ms + snapshots.WINDOW_HOURS * 3_600_000
    lo = int((t - RECEIVE_SLACK).timestamp() * NS)
    hi = int((t + timedelta(hours=snapshots.WINDOW_HOURS) + RECEIVE_SLACK).timestamp() * NS)
    found = []
    for record in store.records_between(root, venue, lo, hi):
        if record["kind"] != "message" or not store.check_payload(record):
            continue
        try:
            parsed = events.PARSERS[venue](json.loads(record["payload"]))
        except (ValueError, events.EventFormatError):
            continue
        inside = [e for e in parsed if e.symbol == snapshots.SYMBOL and start_ms <= e.time_ms < end_ms]
        found.extend(e for e in inside if e.counts)
        if not_counted is not None:
            not_counted.extend(e for e in inside if not e.counts)
    return events.dedupe(found)


def count_window(root: Path, t: datetime) -> WindowCount:
    count = WindowCount(t=t.isoformat(), valid=False)
    path = snapshots.snapshot_path(root, t)
    if not path.exists():
        count.reasons.append("no heatmap state")
    else:
        state = snapshots.compute(snapshots.load(path))
        count.reasons.extend(f"state: {r}" for r in state["reasons"])
    start_ns = int(t.timestamp() * NS)
    end_ns = start_ns + snapshots.WINDOW_HOURS * 3600 * NS
    records = store.records_between(root, PRIMARY, start_ns - store.MAX_PROOF_GAP_NS, end_ns + store.MAX_PROOF_GAP_NS)
    count.coverage = round(store.coverage(store.connected_intervals(records), start_ns, end_ns), 6)
    if count.coverage < MIN_COVERAGE:
        count.reasons.append(f"coverage {count.coverage:.4f} < {MIN_COVERAGE}")
    skipped: list[events.LiquidationEvent] = []
    count.events = len(window_events(root, t, not_counted=skipped))
    count.not_filled = len(events.dedupe(skipped))
    if count.events == 0:
        count.reasons.append("no counted liquidation")
    count.valid = not count.reasons
    return count


def run(root: Path, start: datetime, now: datetime | None = None) -> dict[str, Any]:
    """Count all closed windows since ``start`` and apply the gate rule once day 14 is over."""
    start = start.astimezone(timezone.utc)
    if start != start.replace(hour=0, minute=0, second=0, microsecond=0):
        raise ValueError("start must be 00:00 UTC")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    windows = []
    t = start
    while t + timedelta(hours=snapshots.WINDOW_HOURS) <= now and t < start + timedelta(days=EXTENDED_DAYS):
        windows.append(count_window(root, t))
        t += timedelta(hours=snapshots.WINDOW_HOURS)
    gate_windows = [w for w in windows if datetime.fromisoformat(w.t) < start + timedelta(days=GATE_DAY)]
    valid_gate = sum(w.valid for w in gate_windows)
    result: dict[str, Any] = {
        "study": "S12", "start": start.isoformat(), "as_of": now.isoformat(),
        "windows_closed": len(windows), "windows_valid": sum(w.valid for w in windows),
        "events_not_filled": sum(w.not_filled for w in windows),
        "gate_windows": len(gate_windows), "gate_valid": valid_gate,
        "reasons": _reason_counts(windows), "windows": [asdict(w) for w in windows],
    }
    if len(gate_windows) < GATE_DAY * WINDOWS_PER_DAY:
        result["gate"] = "pending"
        return result
    rate = valid_gate / len(gate_windows)
    result["projected_56"] = round(rate * PLANNED_DAYS * WINDOWS_PER_DAY, 1)
    result["projected_84"] = round(rate * EXTENDED_DAYS * WINDOWS_PER_DAY, 1)
    if result["projected_56"] >= MIN_VALID_WINDOWS:
        result["gate"] = "continue_56_days"
        result["end"] = (start + timedelta(days=PLANNED_DAYS)).isoformat()
    elif result["projected_84"] >= MIN_VALID_WINDOWS:
        result["gate"] = "extend_84_days"
        result["end"] = (start + timedelta(days=EXTENDED_DAYS)).isoformat()
    else:
        result["gate"] = "stop_not_assessable"
    return result


def _reason_counts(windows: list[WindowCount]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for window in windows:
        for reason in window.reasons:
            key = reason.split(" ")[0] if reason.startswith("coverage") else reason
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
