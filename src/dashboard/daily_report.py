"""Tagesbericht: morgens um 8 und abends um 22 Uhr (deutsche Zeit) ein kurzer Bericht im Control Center.

Uzi, 09.11.2026 ("dann 2"). TIM sammelt die Fakten selbst (Papier-Ergebnis der 15m/1h-Journale seit dem letzten
Bericht, offene Pläne und Positionen, die Orderflow-Lage, was im Control Center gerade einen Blick braucht) und
lässt DeepSeek (über Hermes) daraus ein paar deutsche Sätze schreiben. Die Fakten stehen immer mit im Bericht;
antwortet Hermes nicht, bleibt der Bericht bei den Fakten. Nur Papier-Journale und öffentliche Marktdaten gehen
hinaus, keine Kontodaten, keine Schlüssel. Nichts hier handelt.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.dashboard.orderflow_shadow import _iso, _save, _time, lage_view, load

SCHEMA = "tim_daily_report/1"
DEFAULT_PATH = Path("data/hermes/daily_reports.json")
LOCAL = ZoneInfo("Europe/Berlin")
SLOTS = (8, 22)  # local hours
WINDOW_HOURS = 3  # a slot missed by more than this is skipped, not written late
KEEP = 14
MAX_PROMPT = 2500
LIVE = {"OPEN": "wartet auf Einstieg", "FILLED": "im Trade"}

Ask = Callable[[str], Mapping[str, Any]]


def due_slot(now: datetime, reports: Sequence[Mapping[str, Any]]) -> tuple[str, datetime] | None:
    """The slot to write now (key, slot time), or None: before the first slot, already written, or missed by too long."""
    local = now.astimezone(LOCAL)
    for hour in sorted(SLOTS, reverse=True):
        slot = local.replace(hour=hour, minute=0, second=0, microsecond=0)
        if slot <= local:
            key = slot.strftime("%Y-%m-%d-%H")
            late = local - slot > timedelta(hours=WINDOW_HOURS)
            return None if late or any(r.get("slot") == key for r in reports) else (key, slot)
    return None


def _money(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "unbekannt"


def facts(journals: Mapping[str, Path], lage: Mapping[str, Any] | None, attention: Sequence[Mapping[str, Any]] | None,
          since: datetime, now: datetime, waiting: Sequence[str] | None = ()) -> list[str]:
    """Plain German lines. Everything the report may say comes from here."""
    from src.dashboard.plan_journal import load_view

    lines = [f"Zeitraum: {since.astimezone(LOCAL).strftime('%d.%m. %H:%M')} bis {now.astimezone(LOCAL).strftime('%d.%m. %H:%M')} Uhr."]
    for name, path in journals.items():
        journal = load_view(Path(path))
        if journal.get("blocked"):
            lines.append(f"Papier-Journal {name}: gesperrt, nicht lesbar.")
            continue
        entries = [e for e in journal.get("entries") or [] if not e.get("excluded")]
        new = [e for e in entries if e.get("created_at") and since <= _time(e["created_at"]) <= now]
        closed = [e for e in entries if e.get("status") == "CLOSED" and e.get("net_r") is not None and e.get("closed_at")
                  and since <= _time(e["closed_at"]) <= now]
        total = round(sum(float(e["net_r"]) for e in closed), 2)
        wins = sum(float(e["net_r"]) > 0 for e in closed)
        lines.append(f"Papier-Journal {name}: {len(new)} neue Pläne, {len(closed)} geschlossen ({wins} im Plus), Summe {total:+.2f} R netto.")
        for entry in entries:
            if entry.get("status") in LIVE:
                lines.append(f"Offen {name}: {entry.get('direction')} {LIVE[entry['status']]}, Einstieg {_money(entry.get('entry'))}, "
                             f"Stop {_money(entry.get('stop'))}.")
    view = lage_view(lage)
    if view:
        lines.append(f"Orderflow jetzt: Preis {_money(view.get('price'))}, Welle {view.get('direction') or 'keine'} "
                     f"(Stärke {view.get('strength')}, Phase {view.get('phase')}, Erschöpfung {'ja' if view.get('exhaustion') else 'nein'}), "
                     f"Tempo {view.get('tempo')}, Delta 5 Minuten {view.get('delta_5m')}, Perp-Delta 5 Minuten {view.get('perp_delta_5m')}.")
    else:
        lines.append("Orderflow: gerade keine frischen Daten.")
    if attention is None:
        lines.append("Control Center: Zustand nicht lesbar.")
    elif attention:
        for tile in list(attention)[:6]:
            lines.append(f"Braucht einen Blick: {tile.get('label')}: {tile.get('value')}"
                         + (f" ({tile.get('reason')})" if tile.get("reason") else "") + ".")
    else:
        lines.append("Control Center: nichts hängt.")
    # P6 (docs/MULTI_AGENTEN_SYSTEM.md): one place for everything that waits for Uzi.
    if waiting is None:
        lines.append("Wartet auf Uzi: nicht lesbar.")
    elif waiting:
        lines.extend(f"Wartet auf Uzi: {item}" for item in list(waiting)[:6])
    else:
        lines.append("Wartet auf Uzi: nichts.")
    return lines


def prompt(lines: Sequence[str], slot: datetime) -> str:
    kind = "Morgenbericht" if slot.hour < 12 else "Abendbericht"
    return (f"Schreibe den {kind} für TIM (Papier-Handel auf BTC) auf Deutsch in höchstens sechs kurzen Sätzen. Nutze keine "
            "Werkzeuge und nur diese Fakten, erfinde nichts dazu, keine Handelsempfehlung:\n" + "\n".join(lines))[:MAX_PROMPT]


def _hermes(text: str) -> Mapping[str, Any]:
    from src.dashboard import hermes_bridge

    return hermes_bridge.ask(text, limit=MAX_PROMPT, record=False)


def latest(path: Path | None) -> dict[str, Any] | None:
    reports = (load(Path(path or DEFAULT_PATH)) or {}).get("reports") or []
    return reports[-1] if reports else None


def update(path: Path, journals: Mapping[str, Path], lage: Mapping[str, Any] | None,
           attention: Callable[[], Sequence[Mapping[str, Any]]] | None = None, now: datetime | None = None,
           ask: Ask | None = None, waiting: Callable[[], Sequence[str]] | None = None) -> dict[str, Any] | None:
    """Write the report of the due slot, once. Returns it, or None when nothing is due."""
    now = now or datetime.now(timezone.utc)
    path = Path(path)
    state = load(path) or {"schema": SCHEMA, "reports": []}
    reports = state.setdefault("reports", [])
    due = due_slot(now, reports)
    if due is None:
        return None
    key, slot = due
    previous = _time(reports[-1]["until"]) if reports else slot - timedelta(hours=24)
    since = max(previous, now - timedelta(hours=24))
    try:
        needs: Sequence[Mapping[str, Any]] | None = attention() if attention else []
    except Exception:  # noqa: BLE001 - the report is written without the Control Center state
        needs = None
    try:
        open_items: Sequence[str] | None = waiting() if waiting else []
    except Exception:  # noqa: BLE001 - the report is written without the waiting list
        open_items = None
    lines = facts(journals, lage, needs, since, now, open_items)
    try:
        reply = (ask or _hermes)(prompt(lines, slot))
    except Exception as error:  # noqa: BLE001 - the facts are the report then
        reply = {"ok": False, "error": type(error).__name__}
    report = {"slot": key, "at": _iso(now), "since": _iso(since), "until": _iso(now), "facts": lines,
              "text": str(reply.get("answer") or "")[:1500] if reply.get("ok") else None,
              "error": None if reply.get("ok") else str(reply.get("error") or "keine Antwort")[:200]}
    reports.append(report)
    state["reports"] = reports[-KEEP:]
    _save(state, path)
    return report
