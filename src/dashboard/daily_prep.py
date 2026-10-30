"""Daily prep ("Mein Tag"): the trader's own morning preparation, stored append-only.

The page /my-day asks what a trading prep page asks every morning (focus,
how body and head feel, what is carried over, the levels for today, the
plan, the day's limits in R, breathing and the pledge) but fills the level
list from TIM's preparation map, so only the plan and the rules are typed.

Paper and self-report only: nothing here places, blocks or sizes an order.
Every save appends a new entry; the newest entry of a day counts, older
ones stay in the file as history. Days are German local days.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

SCHEMA = "tim_daily_prep/1"
SOURCE = "Trader-Eingabe im Control Center (Mein Tag), Level aus TIMs Vorbereitung, nur Papier"
LOCAL = ZoneInfo("Europe/Berlin")
PREP, SKIP, NO_TRADE_DAY = "PREP", "SKIP", "NO_TRADE_DAY"
KINDS = {PREP: "Vorbereitung", SKIP: "heute übersprungen", NO_TRADE_DAY: "No-Trade-Tag"}
FOCUS = ("BTC", "ETH", "SOL")
MOODS = (("body", "Körper"), ("head", "Kopf"), ("carry", "Altlast (0 = frei, 5 = schwer)"))
PREFILL_LEVELS = 8  # levels nearest to the price that the form offers
MAX_LEVELS = 16
MAX_ENTRIES = 5000
MAX_TEXT = 1000
MAX_LABEL = 80
MAX_R = 20.0
MAX_TRADES = 50
_LOCK = threading.Lock()


class PrepError(ValueError):
    """Invalid trader input; the message is shown on the page."""


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def local_day(moment: datetime) -> date:
    return moment.astimezone(LOCAL).date()


def empty_log() -> dict[str, Any]:
    return {"schema": SCHEMA, "source": SOURCE, "entries": []}


def load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_log()
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("entries"), list):
        return empty_log()
    return data


def save(log: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(log, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def suggested_levels(model: Mapping[str, Any] | None, count: int = PREFILL_LEVELS) -> list[dict[str, Any]]:
    """The levels nearest to the price from TIM's preparation map (day/week and month/quarter/year/VWAP), top to bottom."""
    if not model:
        return []
    levels = [*(model.get("levels") or []), *((model.get("htf_levels") or {}).get("levels") or [])]
    last = model.get("last")
    usable = [level for level in levels if isinstance(level.get("price"), (int, float)) and math.isfinite(level["price"])]
    if isinstance(last, (int, float)) and last > 0:
        usable.sort(key=lambda level: abs(level["price"] - last))
    picked = usable[:count]
    return [{"label": str(level["label"])[:MAX_LABEL], "price": float(level["price"])}
            for level in sorted(picked, key=lambda level: -level["price"])]


def level_value(level: Mapping[str, Any]) -> str:
    """Form value of one level checkbox: label and price, so the saved list is what the trader saw."""
    return f"{level['label']}|{level['price']}"


def _text(form: Mapping[str, str], key: str, label: str, required: bool = False, keep_lines: bool = False) -> str:
    raw = str(form.get(key, ""))
    value = "\n".join(" ".join(line.split()) for line in raw.splitlines()).strip() if keep_lines else " ".join(raw.split())
    if len(value) > MAX_TEXT:
        raise PrepError(f"{label}: höchstens {MAX_TEXT} Zeichen.")
    if required and not value:
        raise PrepError(f"{label} fehlt.")
    return value


def _number(form: Mapping[str, str], key: str, label: str, low: float, high: float, integer: bool = False) -> float | int:
    raw = str(form.get(key, "")).strip().replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        raise PrepError(f"{label}: bitte eine Zahl eingeben.") from None
    if not math.isfinite(value) or not low <= value <= high or (integer and value != int(value)):
        kind = "ganze Zahl" if integer else "Zahl"
        raise PrepError(f"{label}: {kind} zwischen {low:g} und {high:g}.")
    return int(value) if integer else round(value, 2)


def _levels(form: Mapping[str, str]) -> list[dict[str, Any]]:
    result = []
    for key in sorted((k for k in form if re.fullmatch(r"lv_\d{1,2}", k)), key=lambda k: int(k[3:])):
        label, _, price = str(form[key]).rpartition("|")
        label = " ".join(label.split())
        try:
            value = float(price)
        except ValueError:
            raise PrepError("Level-Liste beschädigt: bitte die Seite neu laden.") from None
        if not label or len(label) > MAX_LABEL or not math.isfinite(value) or value <= 0:
            raise PrepError("Level-Liste beschädigt: bitte die Seite neu laden.")
        result.append({"label": label, "price": value})
    if len(result) > MAX_LEVELS:
        raise PrepError(f"Höchstens {MAX_LEVELS} Level.")
    return result


def build_entry(form: Mapping[str, str], now: datetime, number: int, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate the form and build one entry: PREP, SKIP or NO_TRADE_DAY."""
    kind = str(form.get("kind", "")).strip().upper()
    if kind not in KINDS:
        raise PrepError("Unbekannte Aktion: bitte die Seite neu laden.")
    entry: dict[str, Any] = {"id": f"DP-{number:04d}", "created_at": _iso(now), "day": local_day(now).isoformat(), "kind": kind,
                             "context": dict(context or {})}
    if kind != PREP:
        entry["note"] = _text(form, "note", "Notiz")
        return entry
    focus = [coin for coin in FOCUS if str(form.get(f"f_{coin}", "")) == "1"]
    if not focus:
        raise PrepError("Fokus fehlt: mindestens einen Coin wählen.")
    moods = {key: _number(form, key, label, 0, 5, integer=True) for key, label in MOODS}
    if str(form.get("oath", "")) != "1":
        raise PrepError("Eid fehlt: ohne „Ich halte mich heute an meine Regeln“ keine Vorbereitung.")
    cutoff = str(form.get("cutoff", "")).strip()
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", cutoff):
        raise PrepError("Schlusszeit: bitte als HH:MM (Ortszeit).")
    entry.update(
        focus=focus,
        mood=moods,
        carrying=_text(form, "carrying", "Was ich mitschleppe"),
        levels=_levels(form),
        extra_levels=_text(form, "extra_levels", "Eigene Level", keep_lines=True),
        plan=_text(form, "plan", "Plan", required=True, keep_lines=True),
        counter_trend=str(form.get("counter_trend", "")) == "1",
        limits={"max_risk_r": _number(form, "max_risk_r", "Max. Risiko am Tag (R)", 0.1, MAX_R),
                "max_trades": _number(form, "max_trades", "Max. Trades", 1, MAX_TRADES, integer=True),
                "cutoff": cutoff},
        breathing=str(form.get("breathing", "")) == "1",
        oath=True,
    )
    entry["hints"] = hints(entry)
    return entry


def hints(entry: Mapping[str, Any]) -> list[str]:
    """Plain reminders from the trader's own answers; never a block."""
    result = []
    mood = entry.get("mood") or {}
    if mood.get("body", 5) <= 1 or mood.get("head", 5) <= 1:
        result.append("Körper oder Kopf sehr schwach: heute kleiner oder gar nicht")
    if mood.get("carry", 0) >= 4:
        result.append("schwere Altlast: Tilt-Gefahr, Grenzen halbieren?")
    if entry.get("counter_trend"):
        result.append("Gegentrend geplant: nur mit klarer Bestätigung")
    if not entry.get("levels") and not entry.get("extra_levels"):
        result.append("keine Level gewählt")
    return result


def context_snapshot(model: Mapping[str, Any] | None) -> dict[str, Any]:
    """What TIM saw when the prep was saved: bias, location and price."""
    if not model:
        return {}
    return {"bias": (model.get("bias") or {}).get("bias"), "location": (model.get("location") or {}).get("state"),
            "last": model.get("last")}


def add_entry(path: Path, form: Mapping[str, str], model: Mapping[str, Any] | None = None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    with _LOCK:
        log = load(path)
        entries = log["entries"]
        if len(entries) >= MAX_ENTRIES:
            raise PrepError(f"Log voll ({MAX_ENTRIES} Einträge).")
        entry = build_entry(form, now, len(entries) + 1, context_snapshot(model))
        entries.append(entry)
        log["updated_at"] = _iso(now)
        save(log, path)
    return entry


def today(log: Mapping[str, Any], now: datetime | None = None) -> dict[str, Any] | None:
    """The newest entry of today's local day, or None."""
    day = local_day(now or datetime.now(timezone.utc)).isoformat()
    return next((entry for entry in reversed(log.get("entries") or []) if entry.get("day") == day), None)


def latest_per_day(entries: Sequence[Mapping[str, Any]], days: int = 14) -> list[Mapping[str, Any]]:
    """One entry per day (the newest), newest day first."""
    seen: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        seen[str(entry.get("day"))] = entry
    return [seen[day] for day in sorted(seen, reverse=True)[:days]]
