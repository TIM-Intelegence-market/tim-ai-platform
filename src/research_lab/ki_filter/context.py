"""What the AI may see about a plan: only what was known when the plan was recorded.

Plan fields come from a whitelist (never fill, exit, result or verdict fields). History counts only
entries closed strictly before the plan was created. Market rows must end at or before that moment;
market_context() drops anything later instead of trusting the caller.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

UTC = timezone.utc
# Fields fixed when the plan is recorded (src/dashboard/plan_journal.py). Outcome fields are never here.
PLAN_FIELDS = (
    "id", "timeframe", "direction", "created_at", "close_at_record", "entry", "entry_low", "entry_high",
    "stop", "invalidation_level", "targets", "market_state", "scenario_type", "scenario_state", "entry_model",
    "setup_grade", "grade_reasons", "missing_confirmations", "data_quality", "plan_text", "score",
    "pipeline_decision_reasons", "evidence_status",
)
HISTORY_LAST = 10
TIMEFRAME_MINUTES = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def plan_context(entry: Mapping[str, Any]) -> dict[str, Any]:
    plan = {key: entry[key] for key in PLAN_FIELDS if key in entry}
    entry_price, stop = _num(entry.get("entry")), _num(entry.get("stop"))
    if entry_price and stop and entry_price != stop:
        risk = abs(entry_price - stop)
        plan["risk_pct"] = round(risk / entry_price * 100, 3)
        targets = [t for t in (entry.get("targets") or []) if _num(t) is not None]
        plan["targets_r"] = [round(abs(float(t) - entry_price) / risk, 2) for t in targets]
        close = _num(entry.get("close_at_record"))
        if close:
            plan["entry_distance_pct"] = round((entry_price - close) / close * 100, 3)
    return plan


def history_context(entries: Sequence[Mapping[str, Any]], before: datetime) -> dict[str, Any]:
    """Results of this journal closed strictly before ``before`` (no look-ahead)."""
    closed = []
    for item in entries:
        at = parse_time(item.get("closed_at"))
        if item.get("excluded") or item.get("status") != "CLOSED" or at is None or at >= before:
            continue
        if _num(item.get("net_r")) is None:
            continue
        closed.append((at, item))
    closed.sort(key=lambda pair: pair[0])
    last = [{"direction": item.get("direction"), "net_r": round(float(item["net_r"]), 3),
             "exit_reason": item.get("exit_reason"), "setup_grade": item.get("setup_grade"),
             "market_state": item.get("market_state")} for _, item in closed[-HISTORY_LAST:]]
    net = [float(item["net_r"]) for _, item in closed]
    return {"closed_before": len(closed), "sum_net_r": round(sum(net), 3),
            "wins": sum(r > 0 for r in net), "last": last}


def market_context(candles: Sequence[Mapping[str, Any]], cutoff: datetime, timeframe: str) -> dict[str, Any]:
    """Compact market picture from closed candles ending at or before ``cutoff``.

    Each row: open_time, open, high, low, close, volume, optional delta (taker buy minus taker sell
    volume). Rows whose candle closes after the cutoff are dropped here as a second guard.
    """
    step = timedelta(minutes=TIMEFRAME_MINUTES.get(timeframe, 15))
    rows = []
    for row in candles:
        start = parse_time(row.get("open_time"))
        if start is None or start + step > cutoff:
            continue
        rows.append((start, row))
    rows.sort(key=lambda pair: pair[0])
    if not rows:
        return {"candles": 0}
    closes = [float(r["close"]) for _, r in rows]
    volumes = [float(r.get("volume") or 0.0) for _, r in rows]
    deltas = [_num(r.get("delta")) for _, r in rows]
    known = [d for d in deltas if d is not None]
    mean_volume = sum(volumes) / len(volumes)
    table = []
    for (start, row), delta in zip(rows, deltas):
        table.append({"t": start.isoformat().replace("+00:00", "Z"), "o": round(float(row["open"]), 2),
                      "h": round(float(row["high"]), 2), "l": round(float(row["low"]), 2),
                      "c": round(float(row["close"]), 2), "v": round(float(row.get("volume") or 0.0), 3),
                      "d": None if delta is None else round(delta, 3)})
    return {
        "candles": len(rows), "timeframe": timeframe,
        "change_pct": round((closes[-1] - float(rows[0][1]["open"])) / float(rows[0][1]["open"]) * 100, 3),
        "high": round(max(float(r["high"]) for _, r in rows), 2), "low": round(min(float(r["low"]) for _, r in rows), 2),
        "last_volume_vs_mean": round(volumes[-1] / mean_volume, 2) if mean_volume else None,
        "cum_delta": round(sum(known), 3) if known else None,
        "delta_coverage": f"{len(known)}/{len(rows)}",
        "rows": table,
    }


PEER_FIELDS = ("direction", "created_at", "entry", "stop", "setup_grade", "scenario_type", "market_state", "timeframe")
PEER_HOURS = 24
PEER_LAST = 3


def peers_context(peers: Mapping[str, Sequence[Mapping[str, Any]]], cutoff: datetime) -> dict[str, Any]:
    """What TIM's other rules (struct, level, vp, 30m, other horizons) said up to ``cutoff``.

    Only fields fixed at recording; never a status, fill or result of a plan that may have changed
    after the cutoff. Their track record counts only results closed before the cutoff.
    """
    out: dict[str, Any] = {}
    for name, entries in peers.items():
        recent = []
        for item in entries:
            at = parse_time(item.get("created_at"))
            if item.get("excluded") or at is None or at > cutoff or at < cutoff - timedelta(hours=PEER_HOURS):
                continue
            recent.append((at, {key: item[key] for key in PEER_FIELDS if key in item}))
        recent.sort(key=lambda pair: pair[0])
        record = history_context(entries, cutoff)
        out[name] = {"plans_last_24h": [plan for _, plan in recent[-PEER_LAST:]],
                     "closed_before": record["closed_before"], "sum_net_r": record["sum_net_r"],
                     "wins": record["wins"]}
    return out
