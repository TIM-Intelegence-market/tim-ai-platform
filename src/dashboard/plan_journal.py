"""Paper journal of TIM's Setup-Pfad plans (long and short), with outcomes.

Each time a 15m candle closes, the plans shown on the Setup-Pfad page are
written down: entry, stop, invalidation and the three targets from TIM's
TradePlanBuilder. Afterwards every plan is followed on 1m candles:

- OPEN: waiting for the limit entry. Ends as FILLED, INVALIDATED (15m close
  beyond the invalidation level first), REPLACED (TIM now proposes other
  levels in the same direction) or EXPIRED (24 h without fill). A plan that
  TIM stops showing stays OPEN like a resting limit order.
- FILLED: followed with TIM's management plan: one third out at each target,
  stop to break-even after target 1, the last third at target 3 (the
  structural trailing stop is not modelled). A 15m close beyond the
  invalidation level closes the rest at that close. Ends as CLOSED with a
  result in R.

Paper only. Nothing here places or suggests an order; it records what TIM's
rules would have done. When a 1m candle touches the stop and a target, the
stop counts first. No new entries inside the NY-open block.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.dashboard.chart_model import _time, build_chart_model, clean_candles, ny_open_windows

SCHEMA = "tim_plan_journal/1"
SOURCE = "Setup-Pfad 15m (80 Kerzen), TIM-Regeln, nur Papier"
PLAN_TIMEFRAME = "15m"
PLAN_VISIBLE = 80  # same window as the Setup-Pfad page (views.SETUP_CHART_CANDLES)
PENDING_HOURS = 24
MAX_HOLD_HOURS = 48
THIRD = 1.0 / 3.0
OPEN, FILLED = "OPEN", "FILLED"
DONE = {"CLOSED", "INVALIDATED", "REPLACED", "EXPIRED"}


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def empty_journal() -> dict[str, Any]:
    return {"schema": SCHEMA, "source": SOURCE, "last_plan_candle": None, "entries": []}


def load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_journal()
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("entries"), list):
        return empty_journal()
    return data


def save(journal: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(journal, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _same_levels(entry: Mapping[str, Any], plan: Mapping[str, Any]) -> bool:
    def level(item: Mapping[str, Any], key: str) -> float | None:
        return None if item.get(key) is None else round(float(item[key]), 2)

    return all(level(entry, key) == level(plan, key) for key in ("entry", "stop", "entry_low", "entry_high"))


def plans_from_model(model: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Plans with entry, stop and targets from a chart model (Setup-Pfad)."""
    analysis = model.get("analysis") or {}
    result = []
    for scenario in analysis.get("scenarios") or []:
        preview = scenario.get("preview") or {}
        direction = scenario.get("direction")
        targets = [t for t in preview.get("targets") or [] if t is not None]
        if direction not in {"LONG", "SHORT"} or not scenario.get("plan_text") or preview.get("entry") is None or preview.get("stop") is None or len(targets) < 3:
            continue
        entry, stop = float(preview["entry"]), float(preview["stop"])
        if (direction == "LONG" and stop >= entry) or (direction == "SHORT" and stop <= entry):
            continue
        invalid = scenario.get("invalidation_level") or {}
        result.append({
            "scenario_id": scenario.get("id"),
            "direction": direction,
            "entry_model": scenario.get("entry_model"),
            "plan_text": scenario.get("plan_text"),
            "entry_low": scenario.get("entry_low"),
            "entry_high": scenario.get("entry_high"),
            "entry": entry,
            "stop": stop,
            "targets": [float(t) for t in targets[:3]],
            "invalidation_level": invalid.get("level"),
            "invalidation_side": invalid.get("side"),
            "scenario_state": scenario.get("state"),
            "score": scenario.get("score"),
            "missing_confirmations": list(scenario.get("missing_confirmations") or []),
            "decision": (analysis.get("decision") or {}).get("status"),
            "market_state": analysis.get("market_state"),
        })
    return result


def record_plans(journal: dict[str, Any], plans: Sequence[Mapping[str, Any]], at: datetime, timeframe: str = PLAN_TIMEFRAME) -> list[dict[str, Any]]:
    """Add new plans; close OPEN ones whose levels TIM changed. Returns the new entries."""
    entries = journal.setdefault("entries", [])
    added = []
    by_direction = {plan["direction"]: plan for plan in plans}
    for entry in entries:
        if entry.get("status") != OPEN or entry.get("timeframe") != timeframe:
            continue
        plan = by_direction.get(entry["direction"])
        if plan is None:
            continue  # a resting limit stays until invalidation, replacement or expiry
        if not _same_levels(entry, plan):
            entry.update(status="REPLACED", closed_at=_iso(at), note="TIM hat neue Marken für diese Richtung.")
        else:
            entry["last_seen_at"] = _iso(at)
    # One plan per direction: no second entry while one waits or is in the trade.
    open_directions = {e["direction"] for e in entries if e.get("status") in {OPEN, FILLED} and e.get("timeframe") == timeframe}
    for plan in plans:
        if plan["direction"] in open_directions:
            continue
        key = f"{timeframe}|{plan['direction']}|{_iso(at)}|{plan['entry']}|{plan['stop']}"
        entry = {
            "id": hashlib.sha256(key.encode()).hexdigest()[:12],
            "timeframe": timeframe,
            "created_at": _iso(at),
            "last_seen_at": _iso(at),
            **dict(plan),
            "status": OPEN,
            "evaluated_through": _iso(at),
            "tp_hits": [],
            "result_r": None,
        }
        entries.append(entry)
        added.append(entry)
    return added


def _blocked(moment: datetime, windows: Sequence[Mapping[str, Any]]) -> bool:
    return any(_time(w["start"]) <= moment < _time(w["end"]) for w in windows)


def _r(entry: Mapping[str, Any], price: float) -> float:
    risk = abs(entry["entry"] - entry["stop"])
    move = price - entry["entry"] if entry["direction"] == "LONG" else entry["entry"] - price
    return move / risk if risk else 0.0


def _close(entry: dict[str, Any], at: datetime, price: float, reason: str) -> None:
    """Close the rest of the position; earlier thirds stay booked."""
    realised = sum(THIRD * _r(entry, entry["targets"][i]) for i in range(len(entry["tp_hits"])))
    rest = 1.0 - THIRD * len(entry["tp_hits"])
    entry.update(status="CLOSED", closed_at=_iso(at), exit_reason=reason, exit_price=price,
                 result_r=round(realised + rest * _r(entry, price), 3))


def _follow(entry: dict[str, Any], candle: Mapping[str, Any]) -> None:
    """One 1m candle for a FILLED position (stop first, then targets in order)."""
    long = entry["direction"] == "LONG"
    stop = entry["entry"] if entry["tp_hits"] else entry["stop"]
    entry["max_favorable_r"] = round(max(entry.get("max_favorable_r", 0.0), _r(entry, candle["high"] if long else candle["low"])), 3)
    entry["max_adverse_r"] = round(min(entry.get("max_adverse_r", 0.0), _r(entry, candle["low"] if long else candle["high"])), 3)
    if (long and candle["low"] <= stop) or (not long and candle["high"] >= stop):
        _close(entry, candle["close_time"], stop, "BREAK_EVEN" if entry["tp_hits"] else "STOP")
        return
    for index in range(len(entry["tp_hits"]), 3):
        target = entry["targets"][index]
        if (long and candle["high"] >= target) or (not long and candle["low"] <= target):
            entry["tp_hits"].append(_iso(candle["close_time"]))
        else:
            break
    if len(entry["tp_hits"]) == 3:
        _close(entry, candle["close_time"], entry["targets"][2], "TP3")


def evaluate(journal: dict[str, Any], minute_candles: Sequence[Mapping[str, Any]], plan_candles: Sequence[Mapping[str, Any]], now: datetime) -> None:
    """Follow OPEN and FILLED entries on candles after their last evaluation."""
    minutes = clean_candles(minute_candles, "1m")
    closes = clean_candles(plan_candles, PLAN_TIMEFRAME)
    for entry in journal.get("entries", []):
        if entry.get("status") not in {OPEN, FILLED}:
            continue
        through = _time(entry["evaluated_through"])
        fresh = [c for c in minutes if c["open_time"] >= through]
        if fresh and fresh[0]["open_time"] > through + timedelta(minutes=1) and not entry.get("data_gap"):
            entry["data_gap"] = f"1m-Kerzen fehlen zwischen {_iso(through)} und {_iso(fresh[0]['open_time'])}"
        windows = ny_open_windows(through - timedelta(days=1), now + timedelta(days=1)) if fresh else []
        long = entry["direction"] == "LONG"
        level, side = entry.get("invalidation_level"), entry.get("invalidation_side")
        seen = through
        for candle in fresh:
            # 15m closes that completed since the previous 1m candle.
            broken = [c for c in closes if seen < c["close_time"] <= candle["open_time"] and level is not None
                      and ((side == "<" and c["close"] < level) or (side == ">" and c["close"] > level))]
            seen = candle["open_time"]
            if broken and entry["status"] == OPEN:
                entry.update(status="INVALIDATED", closed_at=_iso(broken[0]["close_time"]), note="15m-Schluss jenseits der Ungültigkeitsmarke vor dem Einstieg.")
                break
            if broken:
                _close(entry, broken[0]["close_time"], broken[0]["close"], "INVALIDATION")
                break
            if entry["status"] == OPEN:
                if candle["open_time"] >= _time(entry["created_at"]) + timedelta(hours=PENDING_HOURS):
                    entry.update(status="EXPIRED", closed_at=_iso(candle["open_time"]), note=f"{PENDING_HOURS} h ohne Einstieg.")
                    break
                touched = candle["low"] <= entry["entry"] if long else candle["high"] >= entry["entry"]
                if touched and not _blocked(candle["open_time"], windows):
                    entry.update(status=FILLED, filled_at=_iso(candle["open_time"]), fill_price=entry["entry"])
                    # Fill candle: only the stop can trigger (order inside the candle is unknown).
                    stop_hit = candle["low"] <= entry["stop"] if long else candle["high"] >= entry["stop"]
                    if stop_hit:
                        _close(entry, candle["close_time"], entry["stop"], "STOP")
                        break
                continue
            if candle["open_time"] >= _time(entry["filled_at"]) + timedelta(hours=MAX_HOLD_HOURS):
                _close(entry, candle["open_time"], candle["open"], "TIMEOUT")
                break
            _follow(entry, candle)
            if entry["status"] != FILLED:
                break
        if fresh and entry["status"] in {OPEN, FILLED}:
            entry["evaluated_through"] = _iso(fresh[-1]["close_time"])
        elif fresh:
            entry["evaluated_through"] = entry.get("closed_at", entry["evaluated_through"])


def _minute_ceil(value: datetime) -> datetime:
    """15m close times may end in :59.999; journal times start at the full minute."""
    floor = value.replace(second=0, microsecond=0)
    return floor if floor == value else floor + timedelta(minutes=1)


AGAINST_TREND = {"LONG": "TREND_DOWN", "SHORT": "TREND_UP"}


def counter_trend(direction: Any, market_state: Any) -> bool:
    """True when a plan trades against TIM's market state (LONG in TREND_DOWN, SHORT in TREND_UP)."""
    return AGAINST_TREND.get(str(direction)) == str(market_state)


def summary(journal: Mapping[str, Any]) -> dict[str, Any]:
    entries = list(journal.get("entries") or [])
    closed = [e for e in entries if e.get("status") == "CLOSED" and e.get("result_r") is not None]
    wins = [e for e in closed if e["result_r"] > 0]
    by_direction = {}
    for direction in ("LONG", "SHORT"):
        mine = [e for e in closed if e["direction"] == direction]
        by_direction[direction] = {"closed": len(mine), "sum_r": round(sum(e["result_r"] for e in mine), 3)}
    against = [e for e in closed if counter_trend(e.get("direction"), e.get("market_state"))]
    return {
        "plans": len(entries),
        "open": sum(e.get("status") == OPEN for e in entries),
        "filled": sum(e.get("status") == FILLED for e in entries),
        "closed": len(closed),
        "wins": len(wins),
        "win_rate": round(len(wins) / len(closed), 3) if closed else None,
        "sum_r": round(sum(e["result_r"] for e in closed), 3),
        "by_direction": by_direction,
        "counter_trend": {
            "plans": sum(counter_trend(e.get("direction"), e.get("market_state")) for e in entries),
            "closed": len(against),
            "sum_r": round(sum(e["result_r"] for e in against), 3),
        },
    }


def update(path: Path, series: Mapping[str, Sequence[Mapping[str, Any]]], now: datetime | None = None) -> dict[str, Any]:
    """One journal step: follow outcomes, then record plans at a new 15m close."""
    now = now or datetime.now(timezone.utc)
    journal = load(path)
    evaluate(journal, series.get("1m") or [], series.get(PLAN_TIMEFRAME) or [], now)
    closed_15m = [c for c in clean_candles(series.get(PLAN_TIMEFRAME) or [], PLAN_TIMEFRAME) if c["close_time"] <= now]
    if closed_15m:
        latest = _minute_ceil(closed_15m[-1]["close_time"])
        if journal.get("last_plan_candle") != _iso(latest):
            model = build_chart_model(series, PLAN_TIMEFRAME, now=latest, visible=PLAN_VISIBLE)
            record_plans(journal, plans_from_model(model), latest)
            journal["last_plan_candle"] = _iso(latest)
    journal["updated_at"] = _iso(now)
    save(journal, path)
    return journal
