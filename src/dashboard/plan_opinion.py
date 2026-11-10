"""Zweitmeinung zu jedem Plan: DeepSeek (über Hermes) schreibt "dafür / dagegen" zu jedem neuen 15m/1h-Plan.

Uzi, 09.11.2026 ("go 1"). Nur ein Kommentar: nichts hier handelt, filtert oder ändert ein Journal. Sobald ein Plan
im 15m- oder 1h-Journal steht, bekommt Hermes den Plan (Richtung, Zeitrahmen, Einstieg, Stop, Ziele) und die
Live-Orderflow-Lage dieses Moments (Welle, Tempo, Delta, Perp-Delta, nahe Level) und antwortet in drei Zeilen:
DAFÜR, DAGEGEN, URTEIL. Es gehen keine Schlüssel, kein Code und keine Kontodaten hinaus.

Prospektiv: nur Pläne ab ``started_at``. Kein Blick nach vorn: die Lage wird beim ersten Sehen des Plans
festgehalten, und ein Plan, der älter als ``MAX_AGE_MINUTES`` ist, bekommt keine Meinung mehr. Fortsetzbar: jeder
Schritt liest die Journale und speichert eine JSON-Datei. Urteil nach ``TARGET_TRADES`` geschlossenen Plänen, durch Uzi.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.dashboard.orderflow_shadow import _iso, _save, _time, lage_view, load

SCHEMA = "tim_plan_opinion/1"
DEFAULT_PATH = Path("data/journal/tim_plan_opinion.json")
TARGET_TRADES = 30
MAX_AGE_MINUTES = 30
MAX_ATTEMPTS = 2
MAX_PROMPT = 1500
MAX_SENTENCE = 400
VERDICTS = ("DAFÜR", "DAGEGEN", "NEUTRAL")
UNCLEAR = "UNKLAR"
_LINE = re.compile(r"^\W*(DAF(?:Ü|UE)R|DAGEGEN|URTEIL)\W*:\s*(.+)$", re.IGNORECASE)

Ask = Callable[[str], Mapping[str, Any]]


def _num(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "unbekannt"


def prompt(record: Mapping[str, Any], symbol: str = "BTCUSDT") -> str:
    """What Hermes gets: the plan's public numbers and the Lage of the plan's moment. Nothing else."""
    targets = " / ".join(_num(t) for t in record.get("targets") or []) or "unbekannt"
    lines = [
        "Du gibst eine Zweitmeinung zu einem Papier-Handelsplan. Nutze keine Werkzeuge, urteile nur aus diesen Angaben.",
        (f"Plan: {symbol} {record.get('direction')} im {record.get('timeframe')}-Zeitrahmen, Einstieg {_num(record.get('entry'))}, "
         f"Stop {_num(record.get('stop'))}, Ziele {targets}."),
    ]
    view = record.get("lage_at_plan")
    if view:
        lines.append(
            f"Orderflow jetzt: Preis {_num(view.get('price'))}, Welle {view.get('direction') or 'keine'} (Stärke {view.get('strength')}, "
            f"Phase {view.get('phase')}, Erschöpfung {'ja' if view.get('exhaustion') else 'nein'}), Tempo {view.get('tempo')}, "
            f"Delta 5 Minuten {view.get('delta_5m')}, Perp-Delta 5 Minuten {view.get('perp_delta_5m')}.")
        near = [f"{l.get('name')} {l.get('distance_pct')} % entfernt (Absorption {l.get('absorption')}, Imbalance {l.get('imbalance')})"
                for l in view.get("levels") or []]
        if near:
            lines.append("Nahe Level: " + "; ".join(near) + ".")
    else:
        lines.append("Orderflow: gerade keine frischen Daten.")
    lines.append("Antworte auf Deutsch in genau drei Zeilen und sonst nichts:\nDAFÜR: <ein Satz>\nDAGEGEN: <ein Satz>\n"
                 "URTEIL: DAFÜR oder DAGEGEN oder NEUTRAL")
    return "\n".join(lines)[:MAX_PROMPT]


def parse(answer: str) -> dict[str, Any]:
    """The three lines of the answer. A reply without a readable verdict is kept as UNKLAR, never guessed."""
    found: dict[str, str] = {}
    for line in str(answer or "").splitlines():
        match = _LINE.match(line.strip().replace("*", ""))
        if match:
            found.setdefault(match.group(1).upper().replace("UE", "Ü"), match.group(2).strip()[:MAX_SENTENCE])
    word = re.sub(r"[^A-ZÄÖÜ]", "", found.get("URTEIL", "").upper().replace("DAFUER", "DAFÜR"))
    return {"pro": found.get("DAFÜR"), "contra": found.get("DAGEGEN"), "verdict": word if word in VERDICTS else UNCLEAR}


def _hermes(text: str) -> Mapping[str, Any]:
    from src.dashboard import hermes_bridge

    return hermes_bridge.ask(text, limit=MAX_PROMPT, record=False)


def summary(state: Mapping[str, Any]) -> dict[str, Any]:
    plans = list((state.get("plans") or {}).values())
    judged = [p for p in plans if (p.get("opinion") or {}).get("verdict")]
    closed = [p for p in judged if p.get("journal", {}).get("status") == "CLOSED" and p["journal"].get("net_r") is not None]
    by_verdict: dict[str, dict[str, Any]] = {}
    for plan in closed:
        row = by_verdict.setdefault(plan["opinion"]["verdict"], {"n": 0, "wins": 0, "sum_net_r": 0.0})
        row["n"] += 1
        row["wins"] += float(plan["journal"]["net_r"]) > 0
        row["sum_net_r"] = round(row["sum_net_r"] + float(plan["journal"]["net_r"]), 4)
    return {"plans": len(plans), "with_opinion": len(judged), "closed": len(closed), "target": TARGET_TRADES,
            "judgeable": len(closed) >= TARGET_TRADES, "by_verdict": by_verdict}


def update(path: Path, journal_paths: Sequence[Path], lage: Mapping[str, Any] | None, now: datetime | None = None,
           ask: Ask | None = None, symbol: str = "BTCUSDT", max_calls: int = 1) -> dict[str, Any]:
    """One step: note new plans with the Lage of this moment, ask for at most ``max_calls`` opinions, follow the results."""
    from src.dashboard.plan_journal import load_view

    now = now or datetime.now(timezone.utc)
    path = Path(path)
    state = load(path) or {"schema": SCHEMA, "started_at": _iso(now), "sources": [Path(p).name for p in journal_paths],
                           "note": "Nur Kommentar, kein Eingriff in Pläne oder Handel", "plans": {}}
    started = _time(state["started_at"])
    view = lage_view(lage)
    plans = state["plans"]
    for journal_path in journal_paths:
        journal = load_view(Path(journal_path))
        if journal.get("blocked"):
            continue
        for entry in journal.get("entries") or []:
            if entry.get("excluded") or not entry.get("created_at") or _time(entry["created_at"]) < started:
                continue
            record = plans.setdefault(str(entry["id"]), {
                "id": entry["id"], "journal_file": Path(journal_path).name, "timeframe": entry.get("timeframe"),
                "direction": entry.get("direction"), "created_at": entry["created_at"], "entry": entry.get("entry"),
                "stop": entry.get("stop"), "targets": list(entry.get("targets") or [])[:3], "lage_at_plan": view, "attempts": 0})
            record["journal"] = {"status": entry.get("status"), "filled_at": entry.get("filled_at"), "closed_at": entry.get("closed_at"),
                                 "exit_reason": entry.get("exit_reason"), "net_r": entry.get("net_r")}
    calls = 0
    for record in sorted(plans.values(), key=lambda p: str(p.get("created_at"))):
        if record.get("opinion") or record.get("skipped"):
            continue
        if now - _time(record["created_at"]) > timedelta(minutes=MAX_AGE_MINUTES):
            record["skipped"] = "zu spät gesehen oder keine Antwort"
            continue
        if record.get("attempts", 0) >= MAX_ATTEMPTS:
            record["skipped"] = record.get("last_error") or "keine Antwort"
            continue
        if calls >= max_calls:
            continue
        calls += 1
        record["attempts"] = record.get("attempts", 0) + 1
        try:
            reply = (ask or _hermes)(prompt(record, symbol))
        except Exception as error:  # noqa: BLE001 - a comment must never stop the step
            reply = {"ok": False, "error": type(error).__name__}
        if reply.get("ok"):
            record["opinion"] = {**parse(str(reply.get("answer") or "")), "at": _iso(now), "seconds": reply.get("seconds")}
            record.pop("last_error", None)
        else:
            record["last_error"] = str(reply.get("error") or "keine Antwort")[:200]
    state["checked_at"] = _iso(now)
    state["summary"] = summary(state)
    _save(state, path)
    return state
