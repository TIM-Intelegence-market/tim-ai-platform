"""Täglicher Kritiker: einmal am Tag kritisiert DeepSeek (über Hermes) das Projekt und den Chart aus Nutzersicht.

Uzi, 11.11.2026 ("ich moechte das der Hermes agent alle 24H als Kritiker das Projekt zur weiterentwicklung
kritisiert", "er soll die perspektive des chart nuzters ebenfalls einbauen", "go"). TIM sammelt die Fakten selbst:
Papier-Ergebnisse der Journale (7 und 30 Tage), die Schatten-Auswertungen, den Zustand des Control Centers, was
der Chart gerade liefert (Ebenen, Mengen, Hinweise, Größe und Bauzeit der Live-Daten), die Merges der letzten Tage
und was auf Uzi wartet. Hermes bekommt nur diese Zeilen und die Kritik von gestern, und schreibt zwei Teile:
"Projekt" und "Chart aus Nutzersicht".

Nur lesend: nichts hier handelt, ändert eine Datei außer der eigenen oder legt etwas an. Hinaus gehen Zahlen und
Überschriften, kein Code, keine Schlüssel, keine Kontodaten. DeepSeek sieht kein Bild: die Chart-Kritik betrifft
Inhalt, Vollständigkeit, Frische und Tempo, nicht Farben oder Anordnung. Antwortet Hermes nicht, bleiben die Fakten.
"""
from __future__ import annotations

import json
import subprocess
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.dashboard.daily_report import LOCAL
from src.dashboard.orderflow_shadow import _iso, _save, _time, load

SCHEMA = "tim_daily_critic/1"
DEFAULT_PATH = Path("data/hermes/daily_critic.json")
SLOT_HOUR = 7  # local
WINDOW_HOURS = 3  # a slot missed by more than this is skipped, not written late
KEEP = 14
MAX_PROMPT = 5000
MAX_PREVIOUS = 900
MAX_LINES = 45
MERGE_DAYS = 7
MIN_SAMPLE = 30  # closed plans below this are named a small sample

Ask = Callable[[str], Mapping[str, Any]]
Source = Callable[[], Sequence[str]]


def due_slot(now: datetime, reports: Sequence[Mapping[str, Any]]) -> str | None:
    """The day to write now, or None: before 7, already written, or missed by too long."""
    local = now.astimezone(LOCAL)
    slot = local.replace(hour=SLOT_HOUR, minute=0, second=0, microsecond=0)
    key = slot.strftime("%Y-%m-%d")
    if local < slot or local - slot > timedelta(hours=WINDOW_HOURS) or any(r.get("slot") == key for r in reports):
        return None
    return key


def journal_facts(journals: Mapping[str, Path], now: datetime) -> list[str]:
    """Closed paper plans of the last 7 and 30 days per journal: count, wins, net R."""
    from src.dashboard.plan_journal import load_view

    lines = []
    for name, path in journals.items():
        journal = load_view(Path(path))
        if journal.get("blocked"):
            lines.append(f"Papier-Journal {name}: gesperrt, nicht lesbar.")
            continue
        closed = [e for e in journal.get("entries") or [] if not e.get("excluded") and e.get("status") == "CLOSED"
                  and e.get("net_r") is not None and e.get("closed_at")]
        parts = []
        for days in (7, 30):
            mine = [e for e in closed if now - timedelta(days=days) <= _time(e["closed_at"]) <= now]
            wins = sum(float(e["net_r"]) > 0 for e in mine)
            parts.append(f"{days} Tage: {len(mine)} geschlossen, {wins} im Plus, {sum(float(e['net_r']) for e in mine):+.2f} R netto"
                         + (f" (kleine Stichprobe, unter {MIN_SAMPLE})" if len(mine) < MIN_SAMPLE else "")
                         if mine else f"{days} Tage: kein Plan geschlossen, keine Evidenz")
        lines.append(f"Papier-Journal {name}: " + "; ".join(parts) + ".")
    return lines


def shadow_facts(shadows: Mapping[str, Path]) -> list[str]:
    """The summaries the shadow studies keep in their own files (orderflow shadow, second opinion)."""
    lines = []
    for name, path in shadows.items():
        summary = (load(Path(path)) or {}).get("summary")
        if not summary:
            lines.append(f"{name}: noch keine Auswertung.")
            continue
        table = summary.get("by_gate") or summary.get("by_verdict") or {}
        rows = ", ".join(f"{key} {row.get('n')} Pläne {float(row.get('sum_net_r') or 0):+.2f} R" for key, row in table.items())
        covered = summary.get("with_lage", summary.get("with_opinion"))
        coverage = f"Abdeckung {covered} von {summary.get('plans', 0)} Plänen mit Daten; " if covered is not None else ""
        lines.append(f"{name}: {coverage}Urteil braucht {summary.get('target', '?')} geschlossene Pläne, bisher {summary.get('closed', 0)}, "
                     "noch nicht belastbar" + (f" ({rows})" if rows else "") + ".")
    return lines


def chart_facts(model: Mapping[str, Any], seconds: float | None = None) -> list[str]:
    """What the live chart delivers to a user, read from its own JSON: amounts, gaps, notes, size, build time."""
    size = len(json.dumps(model, default=str).encode())
    candles = model.get("candles") or []
    groups = Counter(str(d.get("group")) for d in model.get("drawings") or [])
    lines = [f"Chart {model.get('symbol')} {model.get('timeframe')}: {len(candles)} Kerzen, letzte geschlossene {model.get('last_closed') or 'unbekannt'}, "
             f"Live-Daten {size // 1024} KB" + (f", gebaut in {seconds:.1f} s" if seconds is not None else "") + "."]
    lines.append(f"Chart-Ebenen: {len(model.get('groups') or [])} wählbar, {len(model.get('default_groups') or [])} beim Start an. Linien und "
                 "Marken je Ebene: " + (", ".join(f"{name} {count}" for name, count in groups.most_common(14)) or "keine") + ".")
    bubbles = (model.get("bubbles") or {}).get("items") or []
    footprint = (model.get("footprint") or {}).get("bars") or []
    lines.append(f"Chart-Inhalt: {len(model.get('plans') or [])} Pläne, {len(bubbles)} Volumen-Blasen, {len(footprint)} Footprint-Kerzen, "
                 f"{len(model.get('volume_profile') or [])} Volumenprofile, {len(model.get('tpo') or [])} TPO-Profile, "
                 f"Liquidations-Karte {'da' if model.get('liquidation') else 'fehlt'}.")
    for note in list(model.get("notes") or [])[:6]:
        lines.append(f"Hinweis im Chart: {str(note)[:160]}")
    return lines


def cockpit_facts(lage: Mapping[str, Any]) -> list[str]:
    """Control Center as a user sees it: how many rows are red, yellow or without data, and which."""
    tiles = [t for key in ("market", "journals", "system", "mac", "own_data") for t in lage.get(key) or [] if isinstance(t, Mapping)]
    states = Counter(str(t.get("state")) for t in tiles)
    lines = [(f"Control Center: {lage.get('headline') or 'ohne Überschrift'}; {len(tiles)} Kacheln, {states.get('fail', 0)} rot, "
              f"{states.get('warn', 0)} gelb, {states.get('unknown', 0)} ohne Daten.")]
    for tile in [t for t in tiles if t.get("state") == "unknown"][:6]:
        lines.append(f"Kachel ohne Daten: {tile.get('label')}: {tile.get('reason') or 'kein Grund angegeben'}.")
    for tile in list(lage.get("attention") or [])[:6]:
        lines.append(f"Braucht einen Blick: {tile.get('label')}: {tile.get('value')}"
                     + (f" ({tile.get('reason')})" if tile.get("reason") else "") + ".")
    return lines


def merge_facts(root: Path | str = ".", days: int = MERGE_DAYS, limit: int = 12) -> list[str]:
    """Titles of the pull requests merged in the last days, from the local git history (no network)."""
    run = subprocess.run(["git", "log", "--merges", f"--since={days}.days", f"-n{limit}", "--pretty=%b"],
                         cwd=str(root), capture_output=True, text=True, timeout=10, check=False)
    titles = [line.strip()[:120] for line in run.stdout.splitlines() if line.strip() and not line.lower().startswith(("signed-off", "co-authored"))]
    if run.returncode != 0:
        return ["Merges: Git-Verlauf nicht lesbar."]
    return [f"Gemergt in {days} Tagen ({len(titles)}): " + "; ".join(titles) + "."] if titles else [f"Gemergt in {days} Tagen: nichts."]


def gather(sources: Mapping[str, Source]) -> list[str]:
    """All fact lines. A source that fails is named as unreadable, never left out quietly."""
    lines: list[str] = []
    for name, source in sources.items():
        try:
            lines.extend(str(line) for line in source())
        except Exception as error:  # noqa: BLE001 - one broken source must not cost the critique
            lines.append(f"{name}: nicht lesbar ({type(error).__name__}).")
    return lines[:MAX_LINES]


def prompt(lines: Sequence[str], previous: str | None) -> str:
    text = ("Du bist der tägliche Kritiker von TIM (Papier-Handel und Live-Chart für BTC). Nutze keine Werkzeuge und nur diese "
            "Fakten, erfinde nichts dazu, keine Handelsempfehlung. Schreibe auf Deutsch zwei Teile.\n"
            "PROJEKT: die drei größten Schwächen, je mit einem konkreten Verbesserungsvorschlag und kurzer Begründung; dazu ein "
            "Punkt, der gut läuft.\n"
            "CHART AUS NUTZERSICHT: du bist jemand, der den Chart täglich öffnet. Was fehlt, ist leer, veraltet, langsam oder "
            "unverständlich? Drei Punkte, je mit Vorschlag.\n"
            "Wenn eine Kritik von gestern noch gilt, schreibe 'noch offen' davor statt sie neu zu erfinden.\nFakten:\n" + "\n".join(lines))
    if previous:
        text += "\nKritik von gestern:\n" + previous[:MAX_PREVIOUS]
    else:
        text += "\nEs gibt noch keine Kritik von gestern; erwähne das nicht."
    return text[:MAX_PROMPT]


def _hermes(text: str) -> Mapping[str, Any]:
    from src.dashboard import hermes_bridge

    return hermes_bridge.ask(text, limit=MAX_PROMPT, record=False)


def latest(path: Path | None, count: int = 1) -> list[dict[str, Any]]:
    reports = (load(Path(path or DEFAULT_PATH)) or {}).get("reports") or []
    return list(reversed(reports[-count:]))


def update(path: Path, sources: Mapping[str, Source], now: datetime | None = None, ask: Ask | None = None) -> dict[str, Any] | None:
    """Write today's critique, once. Returns it, or None when nothing is due."""
    now = now or datetime.now(timezone.utc)
    path = Path(path)
    state = load(path) or {"schema": SCHEMA, "reports": []}
    reports = state.setdefault("reports", [])
    key = due_slot(now, reports)
    if key is None:
        return None
    lines = gather(sources)
    previous = next((r.get("text") for r in reversed(reports) if r.get("text")), None)
    try:
        reply = (ask or _hermes)(prompt(lines, previous))
    except Exception as error:  # noqa: BLE001 - the facts stay as the record then
        reply = {"ok": False, "error": type(error).__name__}
    report = {"slot": key, "at": _iso(now), "facts": lines,
              "text": str(reply.get("answer") or "")[:4000] if reply.get("ok") else None,
              "error": None if reply.get("ok") else str(reply.get("error") or "keine Antwort")[:200]}
    reports.append(report)
    state["reports"] = reports[-KEEP:]
    _save(state, path)
    return report


def state_sources(state: Any, root: Path | str = ".", symbol: str = "BTCUSDT") -> dict[str, Source]:
    """The sources of the running TIM: journals, shadows, Control Center, live chart, merges, what waits for Uzi."""
    from src.dashboard import orderflow_shadow, waiting_on_uzi
    from src.dashboard.state import plan_journal_paths

    def chart() -> list[str]:
        from src.dashboard.chart_live import build_live_chart, load_plan_journals
        from src.dashboard.perp_flow import chart_inputs

        with state.lock:
            footprint, gamma, liquidation = dict(state.footprint), dict(state.gamma), dict(state.liquidation)
            perp, open_interest = chart_inputs(state, symbol)
        started = time.monotonic()
        model = build_live_chart(symbol, "30m", state.chart_series(), footprint=footprint, gamma=gamma, liquidation=liquidation,
                                 plan_journals=load_plan_journals(plan_journal_paths(state)), perp=perp, open_interest=open_interest)
        return chart_facts(model, time.monotonic() - started)

    def cockpit() -> list[str]:
        from src.dashboard.cockpit.lage import build_lage

        return cockpit_facts(build_lage(state))

    journals = {"15m": state.plan_journal_short_path, "1h": state.plan_journal_mid_path, "1d": state.plan_journal_long_path}
    return {
        "Papier-Journale": lambda: journal_facts(journals, datetime.now(timezone.utc)),
        "Schatten": lambda: shadow_facts({"Orderflow-Schatten": orderflow_shadow.DEFAULT_PATH, "Zweitmeinung": state.plan_opinion_path}),
        "Control Center": cockpit,
        "Chart": chart,
        "Merges": lambda: merge_facts(root),
        "Wartet auf Uzi": lambda: [f"Wartet auf Uzi: {item}" for item in list(waiting_on_uzi.items(root))[:6]],
    }
