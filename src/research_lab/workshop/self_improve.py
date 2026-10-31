"""F11 Selbst-Verbesserung: TIM turns the lessons of its own paper trades into rule changes and tests them.

Uzi, 31.10.2026: "TIM soll seine trades reflektieren koennen, um einfach besser zu traden".

The loop, run by the weekly task of the timetable (F6):

1. **Filters from lessons.** Every repeated lesson of the trade reflection has one fixed filter ("leave
   such trades out"). Filters read only what was known when the plan was made (direction, TIM's market
   state, setup grade, missing confirmations, entry and stop). Thresholds are fixed here and never fitted
   to the trades.
2. **Look back.** Each filter is applied to all closed trades of the plan journals: what did the trades it
   would have dropped bring? This is in-sample, because the lessons came from the same trades. It only
   decides whether a filter is worth watching.
3. **Watch forward.** A filter whose lesson repeats (at least 30 % of at least 20 trades) and whose dropped
   trades lost money starts a 30-day observation. Only trades planned after the start count. Nothing in
   TIM changes; the observation never counts in the net R.
4. **Judge once.** After the window, with enough new trades, the filter passes only if the dropped trades
   lost money with a bootstrap interval entirely below zero (Bonferroni over all filters). A passed filter
   is "bereit für Uzis Entscheidung"; only his yes changes TIM's rule, by pull request. Too few trades start
   a new window; each window is judged exactly once.

Everything is written to ``data/research/self_improve/log.jsonl`` (hash chain). The journals are only read.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.research_lab.workshop.shadow import bootstrap_interval

VERSION = "self-improve/1.0"
LOG_PATH = Path("data/research/self_improve/log.jsonl")
GENESIS = "0" * 64
WINDOW_DAYS = 30
LESSON_MIN_TRADES = 20       # as the trade reflection's idea rule
LESSON_MIN_SHARE = 0.30
LOOKBACK_MIN_TRADES = 20
LOOKBACK_MIN_DROPPED = 8
FORWARD_MIN_TRADES = 20
FORWARD_MIN_DROPPED = 5
ALPHA = 0.05
MAX_PLANNED_COST_R = 0.15    # stricter than the journal's own 0.25 R cut
# Costs per side as in the plan journal (protocol/1.1): fee 0.05 %, slippage 0.03 %, stop slippage 0.05 %.
ROUND_TRIP_COST = 2 * 0.0005 + 0.0003 + 0.0005


def planned_cost_r(entry: Mapping[str, Any]) -> float | None:
    """Round-trip costs of a stopped-out trade in R, from the planned entry and stop."""
    try:
        price, stop = float(entry["entry"]), float(entry["stop"])
    except (KeyError, TypeError, ValueError):
        return None
    risk = abs(price - stop)
    return ROUND_TRIP_COST * price / risk if risk > 0 else None


def _against(entry: Mapping[str, Any]) -> bool:
    from src.dashboard.plan_journal import counter_trend
    return counter_trend(entry.get("direction"), entry.get("market_state"))


def _costly(entry: Mapping[str, Any]) -> bool:
    cost = planned_cost_r(entry)
    return cost is not None and cost > MAX_PLANNED_COST_R


@dataclass(frozen=True)
class Filter:
    key: str
    lessons: tuple[str, ...]
    text: str
    drops: Callable[[Mapping[str, Any]], bool]


FILTERS: dict[str, Filter] = {f.key: f for f in (
    Filter("MIT_TREND", ("AGAINST_TREND",), "Trades gegen TIMs Marktzustand auslassen", _against),
    Filter("KOSTEN_DECKEL", ("COSTS_ATE_PROFIT",),
           f"Trades mit geplanten Kosten über {str(MAX_PLANNED_COST_R).replace('.', ',')} R auslassen (Stop zu eng)", _costly),
    Filter("OHNE_GRADE_C", ("WRONG_AT_ONCE", "INVALIDATED"), "Setups mit Grade C auslassen",
           lambda e: str(e.get("setup_grade") or "") == "C"),
    Filter("NUR_BESTAETIGT", ("WRONG_AT_ONCE", "INVALIDATED"), "Setups mit fehlender Bestätigung auslassen",
           lambda e: bool(e.get("missing_confirmations"))),
)}


def closed(journals: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Closed, non-excluded trades of all journals, tagged with their journal."""
    out = []
    for name, journal in sorted(journals.items()):
        for entry in journal.get("entries") or []:
            if entry.get("status") == "CLOSED" and not entry.get("excluded") and entry.get("net_r") is not None \
                    and not entry.get("data_gap"):
                out.append({**entry, "_journal": name})
    return out


def _time(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def assess(trades: Sequence[Mapping[str, Any]], key: str, *, level: float = 0.95, seed: int = 0) -> dict[str, Any]:
    """What the trades the filter drops brought (net R after costs)."""
    rule = FILTERS[key]
    dropped = [float(t["net_r"]) for t in trades if rule.drops(t)]
    kept = [float(t["net_r"]) for t in trades if not rule.drops(t)]
    low, high = bootstrap_interval(dropped, level=level, seed=seed) if dropped else (0.0, 0.0)
    return {"trades": len(trades), "dropped": len(dropped), "dropped_net_r": round(sum(dropped), 3),
            "dropped_mean_r": round(sum(dropped) / len(dropped), 3) if dropped else 0.0,
            "kept_net_r": round(sum(kept), 3), "all_net_r": round(sum(dropped) + sum(kept), 3),
            "interval": [round(low, 3), round(high, 3)], "level": level}


def lesson_shares(records: Iterable[Mapping[str, Any]]) -> tuple[int, dict[str, float]]:
    records = list(records)
    n = len(records)
    counts: dict[str, int] = {}
    for record in records:
        for lesson in record.get("lessons") or []:
            counts[lesson] = counts.get(lesson, 0) + 1
    return n, {k: c / n for k, c in counts.items()} if n else {}


def filter_hash(key: str) -> str:
    rule = FILTERS[key]
    body = {"key": key, "text": rule.text, "version": VERSION, "max_cost": MAX_PLANNED_COST_R, "window": WINDOW_DAYS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class LearningLog:
    def __init__(self, path: Path | str = LOG_PATH) -> None:
        self.path = Path(path)

    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        previous = GENESIS
        for number, row in enumerate(rows, 1):
            body = {k: v for k, v in row.items() if k != "hash"}
            digest = hashlib.sha256((previous + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()
            if body.get("previous") != previous or row.get("hash") != digest:
                raise ValueError(f"Hash-Kette in {self.path} bricht in Zeile {number}")
            previous = row["hash"]
        return rows

    def append(self, event: Mapping[str, Any]) -> dict[str, Any]:
        rows = self.events()
        previous = rows[-1]["hash"] if rows else GENESIS
        body = {**event, "previous": previous}
        row = {**body, "hash": hashlib.sha256((previous + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        return row


def windows(events: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Per filter, its observation windows in order, each with its verdict if judged."""
    result: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event["event"] == "watch_start":
            result.setdefault(event["filter"], []).append({**event, "verdict": None})
        elif event["event"] == "verdict":
            for window in result.get(event["filter"], []):
                if window["window"] == event["window"]:
                    window["verdict"] = event
    return result


def judge(trades: Sequence[Mapping[str, Any]], window: Mapping[str, Any]) -> dict[str, Any]:
    """Forward verdict of one window: only trades planned inside it count."""
    start, end = _time(window["start"]), _time(window["end"])
    fresh = [t for t in trades if t.get("created_at") and start <= _time(t["created_at"]) < end]
    figures = assess(fresh, window["filter"], level=1 - ALPHA / len(FILTERS))
    if figures["trades"] < FORWARD_MIN_TRADES or figures["dropped"] < FORWARD_MIN_DROPPED:
        verdict = "zu_wenig"
    elif figures["interval"][1] < 0:
        verdict = "bestanden"
    else:
        verdict = "nicht_bestanden"
    return {"verdict": verdict, "figures": figures}


VERDICT_WORDS = {"bestanden": "bestanden: bereit für Uzis Entscheidung", "nicht_bestanden": "nicht bestanden",
                 "zu_wenig": "zu wenige neue Trades, neues Fenster"}


def step(journals: Mapping[str, Mapping[str, Any]], reflections: Sequence[Mapping[str, Any]], log: LearningLog,
         now: datetime, *, write: bool = True) -> dict[str, Any]:
    """One weekly pass: look back, start observations, judge finished windows. Changes nothing in TIM."""
    trades = closed(journals)
    events = log.events()
    open_windows = windows(events)
    n_reflected, shares = lesson_shares(reflections)
    report: dict[str, Any] = {"at": _iso(now), "trades": len(trades), "reflected": n_reflected, "filters": {}}
    for key, rule in FILTERS.items():
        look = assess(trades, key)
        mine = open_windows.get(key, [])
        current = mine[-1] if mine and mine[-1]["verdict"] is None else None
        done = [w["verdict"] for w in mine if w["verdict"]]
        frequent = n_reflected >= LESSON_MIN_TRADES and max((shares.get(l, 0.0) for l in rule.lessons), default=0.0) >= LESSON_MIN_SHARE
        entry: dict[str, Any] = {"text": rule.text, "lookback": look, "lesson_frequent": frequent, "status": "beobachtet nicht"}
        if current is not None and now >= _time(current["end"]):
            outcome = judge(trades, current)
            entry["status"] = outcome["verdict"]
            if write:
                log.append({"event": "verdict", "filter": key, "window": current["window"], "at": _iso(now), **outcome})
            current = None
            done.append(outcome)
        elif current is not None:
            entry["status"] = "beobachtung"
            entry["window_end"] = current["end"]
        passed = any(d["verdict"] == "bestanden" for d in done)
        if passed:
            entry["status"] = "bestanden"
        elif current is None and frequent and look["trades"] >= LOOKBACK_MIN_TRADES \
                and look["dropped"] >= LOOKBACK_MIN_DROPPED and look["dropped_net_r"] < 0 \
                and not any(d["verdict"] == "nicht_bestanden" for d in done):
            start = now.astimezone(timezone.utc).replace(microsecond=0)
            window = {"event": "watch_start", "filter": key, "window": len(mine) + 1, "filter_hash": filter_hash(key),
                      "start": _iso(start), "end": _iso(start + timedelta(days=WINDOW_DAYS)), "lookback": look,
                      "rule": VERSION, "changes_tim": False}
            if write:
                log.append(window)
            entry["status"] = "beobachtung"
            entry["window_end"] = window["end"]
            entry["started"] = True
        report["filters"][key] = entry
    return report


def status(journals: Mapping[str, Mapping[str, Any]], reflections: Sequence[Mapping[str, Any]], log: LearningLog,
           now: datetime) -> dict[str, Any]:
    """Read-only view of the loop for the Forschung screen."""
    trades = closed(journals)
    mine = windows(log.events())
    out = {"trades": len(trades), "filters": []}
    for key, rule in FILTERS.items():
        look = assess(trades, key)
        history = mine.get(key, [])
        last = history[-1] if history else None
        state, detail = "beobachtet nicht", ""
        if last and last["verdict"] is None:
            start, end = _time(last["start"]), _time(last["end"])
            fresh = [t for t in trades if t.get("created_at") and start <= _time(t["created_at"]) < end]
            state, detail = "beobachtung", f"{len(fresh)} neue Trades im Fenster"
        elif last:
            state = last["verdict"]["verdict"]
        if any(w["verdict"] and w["verdict"]["verdict"] == "bestanden" for w in history):
            state = "bestanden"
        out["filters"].append({"key": key, "text": rule.text, "state": state, "detail": detail,
                               "dropped": look["dropped"], "dropped_net_r": look["dropped_net_r"],
                               "window_end": last["end"] if last and last["verdict"] is None else None})
    return out
