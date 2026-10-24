"""Trader journal: the trader's own paper trades, with Broncx' gate and review.

The trader writes down a trade idea before taking it: direction, entry, stop,
target, the thesis and which confluences are present. Broncx' flowchart is the
gate in front of it:

1. Is this trade in my plan?
2. Did I see exactly what I wanted to see?
3. Is the timing right?
4. Does it follow my rules?

One "no" and the entry is booked as NO_TRADE: written down, never followed.
That is the point of the flowchart, a skipped trade is a result too.

TIM attaches its own context at the moment of the entry (HTF bias, location
against yesterday's value, NY-open block, weekend) and follows TRADE entries
on 1m candles: limit fill at the entry, then stop or target, whichever comes
first (stop first inside one candle). Afterwards the trader answers Broncx'
four review questions. Paper only: nothing here places an order.
"""

from __future__ import annotations

import json
import math
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.dashboard.chart_model import _time, clean_candles, ny_open_windows

SCHEMA = "tim_trader_journal/1"
SOURCE = "Trader-Eingabe im Control Center, TIM-Kontext, nur Papier"
PENDING_HOURS = 24
MAX_HOLD_HOURS = 72
MAX_ENTRIES = 5000
MAX_TEXT = 1000
MAX_PRICE = 10_000_000.0
OPEN, FILLED, NO_TRADE = "OPEN", "FILLED", "NO_TRADE"
DONE = {"CLOSED", "EXPIRED", "CANCELLED"}

GATE = (
    ("in_plan", "Ist der Trade in meinem Plan?"),
    ("saw_setup", "Habe ich genau das gesehen, was ich sehen wollte?"),
    ("timing", "Stimmt das Timing?"),
    ("rules", "Folgt der Trade meinen Regeln?"),
)
CONFLUENCES = (
    ("htf_bias", "HTF-Bias passt"),
    ("value_edge", "Value-Kante (VAH/VAL/POC)"),
    ("naked_poc", "naked POC"),
    ("order_block", "Order Block"),
    ("fvg", "Fair Value Gap"),
    ("sfp", "Swing Failure / Liquidität genommen"),
    ("trapped", "gefangene Trader"),
    ("oi_cvd", "OI / CVD"),
    ("footprint", "Footprint / Absorption"),
    ("vwap", "VWAP"),
)
REVIEW = (
    ("happened", "Was ist passiert?"),
    ("why", "Warum ist es passiert?"),
    ("again", "Würde ich den Trade wieder nehmen?"),
    ("learned", "Was habe ich gelernt?"),
)
_LOCK = threading.Lock()


class JournalError(ValueError):
    """Invalid trader input; the message is shown on the page."""


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def empty_journal() -> dict[str, Any]:
    return {"schema": SCHEMA, "source": SOURCE, "entries": []}


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


def _text(form: Mapping[str, str], key: str, label: str, required: bool = False) -> str:
    value = " ".join(str(form.get(key, "")).split())
    if len(value) > MAX_TEXT:
        raise JournalError(f"{label}: höchstens {MAX_TEXT} Zeichen.")
    if required and not value:
        raise JournalError(f"{label} fehlt.")
    return value


def _price(form: Mapping[str, str], key: str, label: str) -> float:
    raw = str(form.get(key, "")).strip().replace(" ", "").replace("'", "")
    if "," in raw and "." in raw:  # 83.250,5 or 83,250.5
        raw = raw.replace(".", "").replace(",", ".") if raw.rfind(",") > raw.rfind(".") else raw.replace(",", "")
    else:
        raw = raw.replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        raise JournalError(f"{label}: bitte eine Zahl eingeben.") from None
    if not math.isfinite(value) or value <= 0 or value > MAX_PRICE:
        raise JournalError(f"{label}: Preis außerhalb des gültigen Bereichs.")
    return value


def _yes(form: Mapping[str, str], key: str) -> bool | None:
    value = str(form.get(key, "")).strip().lower()
    return True if value == "ja" else False if value == "nein" else None


def context_snapshot(model: Mapping[str, Any] | None, now: datetime) -> dict[str, Any]:
    """What TIM saw at the moment of the entry (from the preparation map)."""
    windows = ny_open_windows(now - timedelta(days=1), now + timedelta(days=1))
    context: dict[str, Any] = {
        "weekend": now.astimezone(timezone.utc).weekday() >= 5,
        "ny_open_block": any(_time(w["start"]) <= now < _time(w["end"]) for w in windows),
    }
    if model:
        from src.dashboard.session_map import summary_line

        context.update(
            bias=(model.get("bias") or {}).get("bias"),
            location=(model.get("location") or {}).get("state"),
            last=model.get("last"),
            summary=summary_line(model),
        )
    return context


def warnings(entry: Mapping[str, Any]) -> list[str]:
    """Plain hints where the entry goes against TIM's context; never a block."""
    result = []
    context = entry.get("context") or {}
    bias = context.get("bias")
    if bias in {"LONG", "SHORT"} and entry.get("direction") != bias:
        result.append(f"gegen den HTF-Bias ({bias})")
    if context.get("weekend"):
        result.append("Wochenende: Broncx handelt am Wochenende nicht")
    if context.get("ny_open_block"):
        result.append("im NY-Open-Block")
    if entry.get("planned_r") is not None and entry["planned_r"] < 1.5:
        result.append(f"Chance-Risiko nur {entry['planned_r']:.2f} R")
    return result


def build_entry(form: Mapping[str, str], context: Mapping[str, Any], now: datetime, number: int) -> dict[str, Any]:
    """Validate the form and build one journal entry (TRADE or NO_TRADE)."""
    direction = str(form.get("direction", "")).strip().upper()
    if direction not in {"LONG", "SHORT"}:
        raise JournalError("Richtung fehlt: Long oder Short.")
    gate = {}
    for key, question in GATE:
        answer = _yes(form, key)
        if answer is None:
            raise JournalError(f"Flussdiagramm: „{question}“ ist nicht beantwortet.")
        gate[key] = answer
    entry_price = _price(form, "entry", "Einstieg")
    stop = _price(form, "stop", "Stop")
    target = _price(form, "target", "Ziel")
    if direction == "LONG" and not stop < entry_price < target:
        raise JournalError("Long: Stop unter dem Einstieg und Ziel darüber.")
    if direction == "SHORT" and not target < entry_price < stop:
        raise JournalError("Short: Stop über dem Einstieg und Ziel darunter.")
    thesis = _text(form, "thesis", "These", required=True)
    confluences = [key for key, _ in CONFLUENCES if str(form.get(f"c_{key}", "")) == "1"]
    failed = [key for key, _ in GATE if not gate[key]]
    entry = {
        "id": f"TJ-{number:04d}",
        "created_at": _iso(now),
        "kind": "NO_TRADE" if failed else "TRADE",
        "status": NO_TRADE if failed else OPEN,
        "direction": direction,
        "entry": entry_price,
        "stop": stop,
        "target": target,
        "planned_r": round(abs(target - entry_price) / abs(entry_price - stop), 3),
        "thesis": thesis,
        "confluences": confluences,
        "gate": gate,
        "gate_failed": failed,
        "context": dict(context),
        "evaluated_through": _iso(now),
        "review": None,
    }
    entry["warnings"] = warnings(entry)
    return entry


def add_entry(path: Path, form: Mapping[str, str], model: Mapping[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    with _LOCK:
        journal = load(path)
        entries = journal["entries"]
        if len(entries) >= MAX_ENTRIES:
            raise JournalError(f"Journal voll ({MAX_ENTRIES} Einträge).")
        entry = build_entry(form, context_snapshot(model, now), now, len(entries) + 1)
        entries.append(entry)
        journal["updated_at"] = _iso(now)
        save(journal, path)
    return entry


def add_review(path: Path, form: Mapping[str, str], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    entry_id = str(form.get("id", "")).strip()
    review: dict[str, Any] = {}
    for key, question in REVIEW:
        if key == "again":
            answer = _yes(form, key)
            if answer is None:
                raise JournalError(f"„{question}“ ist nicht beantwortet.")
            review[key] = answer
        else:
            review[key] = _text(form, key, question, required=True)
    review["at"] = _iso(now)
    with _LOCK:
        journal = load(path)
        entry = next((e for e in journal["entries"] if e.get("id") == entry_id), None)
        if entry is None:
            raise JournalError("Eintrag nicht gefunden.")
        if entry.get("status") in {OPEN, FILLED}:
            raise JournalError("Der Trade läuft noch: Rückblick erst nach dem Ende.")
        entry["review"] = review
        journal["updated_at"] = _iso(now)
        save(journal, path)
    return entry


def cancel_entry(path: Path, form: Mapping[str, str], now: datetime | None = None) -> dict[str, Any]:
    """Withdraw a resting idea before it fills (the trader changed their mind)."""
    now = now or datetime.now(timezone.utc)
    entry_id = str(form.get("id", "")).strip()
    with _LOCK:
        journal = load(path)
        entry = next((e for e in journal["entries"] if e.get("id") == entry_id), None)
        if entry is None:
            raise JournalError("Eintrag nicht gefunden.")
        if entry.get("status") != OPEN:
            raise JournalError("Nur ein noch nicht ausgelöster Einstieg kann zurückgezogen werden.")
        entry.update(status="CANCELLED", closed_at=_iso(now), note="vor dem Einstieg zurückgezogen")
        journal["updated_at"] = _iso(now)
        save(journal, path)
    return entry


def _r(entry: Mapping[str, Any], price: float) -> float:
    risk = abs(entry["entry"] - entry["stop"])
    move = price - entry["entry"] if entry["direction"] == "LONG" else entry["entry"] - price
    return move / risk if risk else 0.0


def _close(entry: dict[str, Any], at: datetime, price: float, reason: str) -> None:
    entry.update(status="CLOSED", closed_at=_iso(at), exit_reason=reason, exit_price=price, result_r=round(_r(entry, price), 3))


def evaluate(journal: dict[str, Any], minute_candles: Sequence[Mapping[str, Any]], now: datetime) -> None:
    """Follow OPEN and FILLED trades on 1m candles after their last evaluation."""
    minutes = clean_candles(minute_candles, "1m")
    for entry in journal.get("entries", []):
        if entry.get("status") not in {OPEN, FILLED}:
            continue
        through = _time(entry["evaluated_through"])
        fresh = [c for c in minutes if c["open_time"] >= through]
        if fresh and fresh[0]["open_time"] > through + timedelta(minutes=1) and not entry.get("data_gap"):
            entry["data_gap"] = f"1m-Kerzen fehlen zwischen {_iso(through)} und {_iso(fresh[0]['open_time'])}"
        long = entry["direction"] == "LONG"
        previous = None
        for candle in fresh:
            if previous and candle["open_time"] > previous + timedelta(minutes=1) and not entry.get("data_gap"):
                entry["data_gap"] = f"1m-Kerzen fehlen zwischen {_iso(previous)} und {_iso(candle['open_time'])}"
            previous = candle["open_time"]
            if entry["status"] == OPEN:
                if candle["open_time"] >= _time(entry["created_at"]) + timedelta(hours=PENDING_HOURS):
                    entry.update(status="EXPIRED", closed_at=_iso(candle["open_time"]), note=f"{PENDING_HOURS} h ohne Einstieg.")
                    break
                if candle["low"] <= entry["entry"] <= candle["high"] or (long and candle["high"] < entry["entry"]) or (not long and candle["low"] > entry["entry"]):
                    entry.update(status=FILLED, filled_at=_iso(candle["open_time"]), fill_price=entry["entry"], max_favorable_r=0.0, max_adverse_r=0.0)
                    # Fill candle: only the stop can trigger (the order inside the candle is unknown).
                    if (long and candle["low"] <= entry["stop"]) or (not long and candle["high"] >= entry["stop"]):
                        _close(entry, candle["close_time"], entry["stop"], "STOP")
                        break
                continue
            if candle["open_time"] >= _time(entry["filled_at"]) + timedelta(hours=MAX_HOLD_HOURS):
                _close(entry, candle["open_time"], candle["open"], "TIMEOUT")
                break
            entry["max_favorable_r"] = round(max(entry["max_favorable_r"], _r(entry, candle["high"] if long else candle["low"])), 3)
            entry["max_adverse_r"] = round(min(entry["max_adverse_r"], _r(entry, candle["low"] if long else candle["high"])), 3)
            if (long and candle["low"] <= entry["stop"]) or (not long and candle["high"] >= entry["stop"]):
                _close(entry, candle["close_time"], entry["stop"], "STOP")
                break
            if (long and candle["high"] >= entry["target"]) or (not long and candle["low"] <= entry["target"]):
                _close(entry, candle["close_time"], entry["target"], "TARGET")
                break
        if fresh and entry["status"] in {OPEN, FILLED}:
            entry["evaluated_through"] = _iso(fresh[-1]["close_time"])
        elif fresh:
            entry["evaluated_through"] = entry.get("closed_at", entry["evaluated_through"])


def update(path: Path, series: Mapping[str, Sequence[Mapping[str, Any]]], now: datetime | None = None) -> dict[str, Any] | None:
    """One evaluation step from the runtime loop; writes only when something is followed."""
    now = now or datetime.now(timezone.utc)
    with _LOCK:
        journal = load(path)
        if not any(e.get("status") in {OPEN, FILLED} for e in journal["entries"]):
            return None
        evaluate(journal, series.get("1m") or [], now)
        journal["updated_at"] = _iso(now)
        save(journal, path)
    return journal


def _week(entry: Mapping[str, Any]) -> str:
    year, week, _ = _time(entry["created_at"]).isocalendar()
    return f"{year}-W{week:02d}"


def summary(journal: Mapping[str, Any]) -> dict[str, Any]:
    entries = list(journal.get("entries") or [])
    closed = [e for e in entries if e.get("status") == "CLOSED" and e.get("result_r") is not None]
    wins = [e for e in closed if e["result_r"] > 0]
    closed_ids = {id(e) for e in closed}
    weeks: dict[str, dict[str, Any]] = {}
    for entry in entries:
        week = weeks.setdefault(_week(entry), {"week": _week(entry), "trades": 0, "no_trades": 0, "closed": 0, "wins": 0, "sum_r": 0.0, "reviewed": 0})
        week["trades" if entry.get("kind") == "TRADE" else "no_trades"] += 1
        week["reviewed"] += bool(entry.get("review"))
        if id(entry) in closed_ids:
            week["closed"] += 1
            week["wins"] += entry["result_r"] > 0
            week["sum_r"] = round(week["sum_r"] + entry["result_r"], 3)
    gate_failures = {key: sum(key in (e.get("gate_failed") or []) for e in entries) for key, _ in GATE}
    with_bias = [e for e in closed if (e.get("context") or {}).get("bias") == e["direction"]]
    against = [e for e in closed if (e.get("context") or {}).get("bias") in {"LONG", "SHORT"} and (e.get("context") or {}).get("bias") != e["direction"]]
    return {
        "entries": len(entries),
        "trades": sum(e.get("kind") == "TRADE" for e in entries),
        "no_trades": sum(e.get("kind") == "NO_TRADE" for e in entries),
        "open": sum(e.get("status") == OPEN for e in entries),
        "filled": sum(e.get("status") == FILLED for e in entries),
        "closed": len(closed),
        "wins": len(wins),
        "win_rate": round(len(wins) / len(closed), 3) if closed else None,
        "sum_r": round(sum(e["result_r"] for e in closed), 3),
        "with_bias_r": round(sum(e["result_r"] for e in with_bias), 3),
        "with_bias": len(with_bias),
        "against_bias_r": round(sum(e["result_r"] for e in against), 3),
        "against_bias": len(against),
        "review_open": sum(e.get("status") in DONE | {NO_TRADE} and not e.get("review") for e in entries),
        "gate_failures": gate_failures,
        "weeks": [weeks[key] for key in sorted(weeks, reverse=True)],
    }
