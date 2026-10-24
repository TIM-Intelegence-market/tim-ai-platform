"""Data models of the cockpit areas "Forschung", "Betrieb" and "System & Freigabe" (P3).

Each area is a list of sections; a section holds status tiles and, where it
helps, one small table. Everything comes from what TIM already writes: the
dashboard snapshot (``/api/state``), its ``operations`` block and the status
files in ``data/operational``. Nothing is calculated anew and nothing is
written. The full detail pages of the old dashboard stay linked.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

from src.dashboard.cockpit.lage import _broken, _info, _system_tiles, UNAVAILABLE_WORDS
from src.dashboard.cockpit.sources import BudgetedSources, SourceResult
from src.dashboard.cockpit.tiles import Tile, attention, make_tile, unavailable, worst
from src.dashboard.state import DashboardState

SCHEMA = "tim_cockpit_area/1"
SAFETY = "Nur Beobachtung und Papier, keine Order, keine Anlageberatung"
ROWS_SHOWN = 8
VALIDATOR_MAX_AGE = 300
CASE_MAX_AGE = 3 * 3600  # a new case or observation at least every few hours while the market runs
HUMAN_WORDS = ("PENDING HUMAN", "HUMAN ACTION", "TIME GATE", "NOT APPLICABLE")
CASE_WORDS = {"OPEN": "offen", "COLLECTING_EVIDENCE": "sammelt Belege", "READY_FOR_REVIEW": "bereit zur Prüfung",
              "MONITORING": "beobachtet", "CONFIRMED": "bestätigt", "REJECTED": "verworfen", "QUARANTINED": "isoliert",
              "CLOSED": "geschlossen", "INVALIDATED": "ungültig"}

_SOURCES: dict[str, BudgetedSources] = {"forschung": BudgetedSources(), "betrieb": BudgetedSources(), "system": BudgetedSources()}


# --- small helpers ----------------------------------------------------------

def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip().upper() in UNAVAILABLE_WORDS) or value == ""


def _text(value: Any, limit: int = 160) -> str:
    text = "—" if _missing(value) else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _num(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _text(value)
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{int(value):,}".replace(",", ".")


STATUS_WORDS = {"PASS": "bestanden", "FAIL": "fehlgeschlagen", "RUNNING": "läuft", "GREEN": "grün", "YELLOW": "gelb",
                "RED": "rot", "AMBER": "gelb", "STALE": "veraltet", "BLOCKED": "blockiert", "ABORTED": "abgebrochen",
                "PENDING HUMAN APPROVAL": "wartet auf Freigabe", "NOT APPLICABLE": "entfällt", "PARTIAL": "teilweise"}


def _word(value: Any, limit: int = 60) -> str:
    """A status word in plain German; unknown words stay as they are (lower case)."""
    if _missing(value):
        return "—"
    text = str(value).strip()
    return STATUS_WORDS.get(text.upper().replace("_", " "), _text(text, limit).lower())


def _local(value: Any) -> str:
    from src.dashboard.cockpit.page import local_time

    return local_time(value, True)


def _cell(text: Any, href: str = "") -> dict[str, str]:
    """A table cell; links only to pages of this dashboard (no scheme, no host)."""
    link = href if href.startswith("/") and not href.startswith("//") and "\\" not in href else ""
    return {"text": _text(text), "href": link}


# Whole words only: "RED" must not match "REQUIRED".
FAULT_PATTERN = re.compile(r"\b(FAIL\w*|RED|ERROR\w*|BLOCK\w*|MISMATCH\w*|CONFLICT\w*|BROKEN)\b")


def _faulty(status: Any) -> bool:
    return bool(FAULT_PATTERN.search(str(status or "").upper().replace("_", " ")))


def _human_gate(status: Any) -> bool:
    """A step that waits for a person. A status that also names a fault is a fault, not a human step."""
    text = str(status or "").upper().replace("_", " ")
    return any(word in text for word in HUMAN_WORDS) and not _faulty(text)


def _count(value: Any) -> int | None:
    """A non-negative count from int, whole float or digit string; anything else is None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parked(tile: Tile, word: str) -> Tile:
    """A tile that is grey on purpose (human step, aborted campaign, external path).

    It stays visible with its reason but does not turn the area headline grey:
    nothing is broken, it simply waits for a person or does not apply.
    """
    tile.extra["kind"] = "parked"
    tile.extra["state_label"] = word
    return tile


def _split_missing(tiles: list[Tile]) -> tuple[list[Tile], list[str]]:
    """Measurements without any value become one line instead of many grey rows."""
    missing = [tile.label for tile in tiles if tile.value == "—" and tile.state == "unknown"]
    return [tile for tile in tiles if not (tile.value == "—" and tile.state == "unknown")], missing


def _section(key: str, title: str, tiles: list[Tile], *, note: str = "", table: dict[str, Any] | None = None,
             empty: str = "") -> dict[str, Any]:
    return {"id": key, "title": title, "tiles": tiles, "note": note, "table": table, "empty": empty}


def _snapshot_failed(result: SourceResult, area: str) -> list[dict[str, Any]]:
    reason = result.reason() if not result.ok else f"Unerwartetes Format ({type(result.value).__name__} statt Objekt)"
    tile = unavailable("snapshot", "TIM-Zustand", reason, "DashboardState.snapshot()")
    return [_section("snapshot", "Datenquelle", [tile], note=f"Ohne den TIM-Zustand lässt sich der Bereich {area} nicht aufbauen.")]


def _metric_tile(key: str, label: str, metric: Any, href: str, *, unit: str = "", judge: bool = False,
                 now: datetime) -> Tile:
    """A tile from an operations metric ({value, status, unit, source}).

    ``judge`` is False for plain measurements (MEASURED): they are shown as
    information, not as a green verdict.
    """
    if not isinstance(metric, dict) or _missing(metric.get("value")):
        source = metric.get("source", "") if isinstance(metric, dict) else ""
        return unavailable(key, label, "Kein Messwert in der Quelle", str(source), href)
    value = metric.get("value")
    if isinstance(value, str) and value.strip().upper().replace("_", " ") in STATUS_WORDS:
        value = _word(value)
    shown = f"{_num(value)} {unit}".strip() if unit else _num(value)
    status = str(metric.get("status") or "")
    if not judge:
        return _info(make_tile(key, label, shown, state="ok", source=str(metric.get("source") or ""), href=href, now=now))
    if status.upper() == "MEASURED":
        return make_tile(key, label, shown, state="unknown", reason="Gemessen, aber die Quelle bewertet den Wert nicht",
                         source=str(metric.get("source") or ""), href=href, now=now)
    return make_tile(key, label, shown, status, reason="" if status.upper() in {"PASS", "GREEN"} else f"Status {_word(status)}",
                     source=str(metric.get("source") or ""), href=href, now=now)


def _model(key: str, title: str, sections: list[dict[str, Any]], results: dict[str, SourceResult], now: datetime) -> dict[str, Any]:
    tiles = [tile for section in sections for tile in section["tiles"] if isinstance(tile, Tile)]
    judged = [tile for tile in tiles if (tile.extra or {}).get("kind") not in {"info", "parked"}]
    parked = [tile for tile in tiles if (tile.extra or {}).get("kind") == "parked"]
    needs = attention(judged)
    overall = worst([tile.state for tile in judged]) if judged else "unknown"
    if needs:
        fails = sum(tile.state == "fail" for tile in needs)
        headline = (f"{fails} Fehler, bitte ansehen" if fails else
                    ("Ein Punkt braucht einen Blick" if len(needs) == 1 else f"{len(needs)} Punkte brauchen einen Blick"))
        overall = "fail" if fails else "warn"
    elif overall == "ok":
        headline = "Alles in Ordnung"
    else:
        headline = "Nicht alle Quellen liefern Daten"
    return {
        "schema": SCHEMA,
        "area": key,
        "title": title,
        "generated_at": now.isoformat(),
        "mode": "OBSERVE",
        "safety": SAFETY,
        "headline": headline,
        "overall": overall,
        "parked": len(parked),
        "attention": [tile.to_dict() for tile in needs],
        "sections": [{**section, "tiles": [tile.to_dict() for tile in section["tiles"]]} for section in sections],
        "sources": {name: {"ok": r.ok, "seconds": r.seconds, "error": r.error, "stale_seconds": r.stale_seconds} for name, r in results.items()},
    }


def _safe_sections(builders: list[tuple[str, str, Callable[[], dict[str, Any]]]]) -> list[dict[str, Any]]:
    """Build each section on its own: an odd data shape greys one section, never the page."""
    out = []
    for key, title, build in builders:
        try:
            out.append(build())
        except Exception as exc:  # noqa: BLE001 - unexpected data shape
            out.append(_section(key, title, [unavailable(key, title, _broken(exc), "Kachelbau")]))
    return out


# --- Forschung --------------------------------------------------------------

def _validator_section(data: dict[str, Any], now: datetime) -> dict[str, Any]:
    validator = data.get("validator") or {}
    status = str(validator.get("status") or "UNAVAILABLE")
    cycles = validator.get("cycles")
    tile = make_tile("validator", "Forschungs-Validator", f"{_word(status)}, {_num(cycles)} Zyklen" if not _missing(status) else "—",
                     "PASS" if status.upper() == "RUNNING" else status,
                     reason="" if status.upper() == "RUNNING" else f"Validator meldet {status}",
                     source="data/runtime/validator_state.json", as_of=validator.get("last_cycle_at"),
                     max_age_seconds=VALIDATOR_MAX_AGE, href="/research", now=now)
    acceptance = validator.get("acceptance") if isinstance(validator.get("acceptance"), dict) else {}
    coverage = acceptance.get("coverage_percent")
    cover = _info(make_tile("coverage", "Abdeckung im Lauf", f"{_num(coverage)} %" if isinstance(coverage, (int, float)) else _text(acceptance.get("status")),
                            state="ok", source="validator acceptance", href="/data-quality", now=now))
    return _section("validator", "Forschungslauf", [tile, cover],
                    note="Der Validator prüft TIMs Beobachtungen in festen Zyklen. Er schreibt nichts in den Markt und erzeugt keine Signale.")


def _cases_section(data: dict[str, Any], now: datetime) -> dict[str, Any]:
    counts = _dict(data.get("case_counts"))
    cases = [c for c in data.get("research_cases") or [] if isinstance(c, dict)]
    latest = max((str(c.get("updated_at") or c.get("opened_at") or "") for c in cases), default="")
    total = make_tile("cases_total", "Research Cases", f"{_num(counts.get('total', 0))} gesamt",
                      "PASS" if counts else "UNAVAILABLE", reason="" if counts else "Keine Fallzählung im TIM-Zustand",
                      source="/api/state case_counts", as_of=latest or None, max_age_seconds=CASE_MAX_AGE if counts else None,
                      href="/cases", now=now, detail=f"{_num(counts.get('active', 0))} aktiv, {_num(counts.get('closed', 0))} geschlossen")
    review = _count(counts.get("ready_for_review", 0))
    ready = make_tile("cases_review", "Bereit zur Prüfung", _num(review) if review is not None else "—",
                      state="unknown" if review is None else ("warn" if review else "ok"),
                      reason=("Keine lesbare Zahl in der Quelle" if review is None else
                              "Ein Fall wartet auf deine Prüfung" if review == 1 else f"{_num(review)} Fälle warten auf deine Prüfung") if review != 0 else "",
                      source="/api/state case_counts.ready_for_review", href="/cases", now=now)
    collecting = _info(make_tile("cases_collecting", "Sammeln Belege", _num(counts.get("collecting_evidence", 0)), state="ok",
                                 source="/api/state case_counts", href="/cases", now=now,
                                 detail=f"davon offen {_num(counts.get('open', 0))}"))
    confirmed = _info(make_tile("cases_confirmed", "Bestätigt / verworfen",
                                f"{_num(counts.get('confirmed', 0))} / {_num(counts.get('rejected', 0))}", state="ok",
                                source="/api/state case_counts", href="/cases", now=now,
                                detail=f"isoliert {_num(counts.get('quarantined', 0))}"))
    rows = []
    for case in sorted(cases, key=lambda c: str(c.get("updated_at") or c.get("opened_at") or ""), reverse=True)[:ROWS_SHOWN]:
        cid = str(case.get("case_id") or "")
        kinds = sorted({str(ev.get("kind")) for ev in case.get("evidence") or [] if isinstance(ev, dict) and ev.get("kind")})
        status = str(case.get("status") or "OPEN").upper()
        rows.append([_cell(_local(case.get("updated_at") or case.get("opened_at"))),
                     _cell(cid[:22], f"/cases?id={cid}" if cid else ""),
                     _cell(CASE_WORDS.get(status, status)),
                     _cell(", ".join(kinds) or "—"),
                     _cell(len(case.get("observation_ids") or [])),
                     _cell(", ".join(str(m) for m in case.get("missing_evidence") or []) or "—")])
    table = {"head": ["Zeit", "Fall", "Status", "Art", "Beob.", "Fehlende Belege"], "rows": rows} if rows else None
    return _section("cases", "Research Cases", [total, ready, collecting, confirmed], table=table,
                    empty="Noch kein Fall im sichtbaren Fenster.",
                    note="Ein Fall bündelt Beobachtungen und sammelt Belege. Bestätigt wird nur nach Prüfung, nie automatisch.")


def _observations_section(data: dict[str, Any], now: datetime) -> dict[str, Any]:
    observations = [o for o in data.get("observations") or [] if isinstance(o, dict)]
    latest = max((str(o.get("observed_at") or "") for o in observations), default="")
    kinds: dict[str, int] = {}
    for item in observations:
        kinds[str(item.get("kind") or "?")] = kinds.get(str(item.get("kind") or "?"), 0) + 1
    top = ", ".join(f"{k} {v}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])[:3])
    tile = make_tile("observations", "Beobachtungen", f"{_num(len(observations))} im Fenster",
                     "PASS" if observations else "UNAVAILABLE",
                     reason="" if observations else "Noch keine Beobachtung seit dem Start dieses Prozesses",
                     source="/api/state observations (sichtbares Fenster)", as_of=latest or None,
                     max_age_seconds=CASE_MAX_AGE if observations else None, href="/observations", now=now, detail=top)
    rows = []
    for item in sorted(observations, key=lambda o: str(o.get("observed_at") or ""), reverse=True)[:ROWS_SHOWN]:
        oid = str(item.get("observation_id") or "")
        rows.append([_cell(_local(item.get("observed_at"))), _cell(item.get("kind"), f"/observations?id={oid}" if oid else ""),
                     _cell(item.get("timeframe")), _cell(item.get("confidence")), _cell(item.get("summary"), "")])
    table = {"head": ["Zeit", "Art", "Rahmen", "Konfidenz", "Beschreibung"], "rows": rows} if rows else None
    return _section("observations", "Jüngste Beobachtungen", [tile], table=table, empty="Keine Beobachtung im Fenster.")


def _qualification_section(ops: dict[str, Any], now: datetime) -> dict[str, Any]:
    qual = ops.get("qualification") or {}
    ind = ops.get("independent_cases") or {}
    readiness = ops.get("readiness") or {}
    status = str(qual.get("status") or "UNAVAILABLE")
    aborted = "ABORTED" in status.upper()
    campaign = make_tile("campaign", "Kampagne", "abgebrochen" if aborted else _word(qual.get("status")),
                         state="unknown" if aborted else None, raw_status=None if aborted else status,
                         reason=(readiness.get("current_reason") or "Kampagne abgebrochen, zählt nicht") if aborted else
                         ("" if status.upper() in {"RUNNING", "ACTIVE", "PASS"} else f"Kampagne {status}"),
                         source=str(qual.get("source") or ""), href="/qualification", now=now,
                         detail=f"{_text(qual.get('campaign_id'))}, {_num(qual.get('manifests_written'))} von mindestens {_num(qual.get('minimum_days'))} Tagesmanifesten")
    if aborted:
        campaign = _parked(campaign, "Abgebrochen")
    current, required = ind.get("current"), ind.get("required")
    cases = _info(make_tile("independent", "Unabhängige Fälle", f"{_num(ind.get('qualification'))} von {_num(required)} für die Kampagne",
                            state="ok", source=str(ind.get("source") or ""), href="/independent-cases", now=now,
                            detail=f"Gesamtbestand {_num(current)}, Kontrollen {_text(ind.get('negative_controls'))}"))
    approval = ind.get("human_approval")
    waiting = _human_gate(approval) or _human_gate(ind.get("manual_review"))
    human = make_tile("human_review", "Menschliche Prüfung", _word(ind.get("manual_review") or approval), state="unknown",
                      reason=("Wartet auf eure Freigabe (Uzi, Integrity Lead); Agenten geben nichts frei" if waiting else
                              f"Status {_word(approval)}" if not _missing(approval) else "Kein Status in der Quelle"),
                      source=str(ind.get("source") or ""), href="/independent-cases", now=now)
    if waiting:
        human = _parked(human, "Wartet auf euch")
    return _section("qualification", "Qualifizierung", [campaign, cases, human],
                    note="Eine neue Kampagne beginnt bei Tag 0. Was abgebrochen ist, zählt nicht als bestanden.")


def build_forschung(state: DashboardState, now: datetime | None = None, budget: float = 1.5,
                    sources: BudgetedSources | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    results = (sources or _SOURCES["forschung"]).run({"snapshot": state.snapshot}, budget=budget)
    snap = results["snapshot"]
    if not snap.ok or not isinstance(snap.value, dict):
        sections = _snapshot_failed(snap, "Forschung")
    else:
        data = snap.value if isinstance(snap.value, dict) else None
        ops = _dict((data or {}).get("operations"))
        sections = _safe_sections([
            ("validator", "Forschungslauf", lambda: _validator_section(data, now)),
            ("cases", "Research Cases", lambda: _cases_section(data, now)),
            ("observations", "Jüngste Beobachtungen", lambda: _observations_section(data, now)),
            ("qualification", "Qualifizierung", lambda: _qualification_section(ops, now)),
        ])
    return _model("forschung", "Forschung", sections, results, now)


# --- Betrieb ----------------------------------------------------------------

RUNTIME_METRICS = (
    ("receive_rate", "Empfang", "/s", False), ("persist_rate", "Gespeichert", "/s", False),
    ("queue_depth", "Warteschlange", "", False), ("queue_age", "Älteste Nachricht", "s", True),
    ("cursor_age", "Cursor-Alter", "s", True), ("source_to_store_latency", "Latenz Quelle bis DB", "s", False),
    ("event_loop_lag", "Event-Loop-Verzug", "s", False), ("restarts", "Neustarts gesamt", "", False),
    ("drop_count", "Verworfen gesamt", "", False), ("duplicate_count", "Doppelte gesamt", "", False),
    ("late_count", "Verspätet gesamt", "", False), ("disk", "Datenträger belegt", "%", True),
    ("logs", "Logdateien", "", True),
)


def _health_section(results: dict[str, SourceResult], now: datetime) -> dict[str, Any]:
    tiles = _system_tiles(results["snapshot"], results["backup"], results["server_health"], now)
    wanted = {"runtime", "market_data", "database", "watchdog", "backup"}
    return _section("health", "Gesundheit", [tile for tile in tiles if tile.id in wanted],
                    note="Dieselben Prüfungen wie auf der Startseite: Prozess, Datenstrom, Datenbank, Watchdog und Backup.")


def _runtime_section(ops: dict[str, Any], now: datetime) -> dict[str, Any]:
    runtime = ops.get("runtime") or {}
    tiles = [_metric_tile(key, label, runtime.get(key), "/runtime", unit=unit, judge=judge, now=now)
             for key, label, unit, judge in RUNTIME_METRICS]
    shown, missing = _split_missing(tiles)
    note = "Zähler „gesamt“ laufen seit dem ersten Start und wachsen nur. Bewertet werden nur Werte mit eigener Grenze (Alter, Datenträger, Logs)."
    if missing:
        note += f" Ohne Messwert in der Quelle: {', '.join(missing)}."
    return _section("runtime", "Datenpipeline", shown or [unavailable("runtime_none", "Datenpipeline", "Keine Laufzeitmesswerte im TIM-Zustand", "operations.runtime", "/runtime")],
                    note=note)


def _quality_section(ops: dict[str, Any], now: datetime) -> dict[str, Any]:
    from src.dashboard.operations import _archive_reason

    gaps = ops.get("gaps") or {}
    p0, p1 = _count(gaps.get("p0")), _count(gaps.get("p1"))
    gap_tile = make_tile("gaps", "Offene Datenlücken", f"P0 {_num(p0)}, P1 {_num(p1)}",
                         state="fail" if isinstance(p0, int) and p0 else ("warn" if isinstance(p1, int) and p1 else
                                                                          ("ok" if isinstance(p0, int) else "unknown")),
                         reason=(("Eine P0-Lücke" if p0 == 1 else f"{_num(p0)} P0-Lücken") if isinstance(p0, int) and p0 else
                                 ("Eine P1-Lücke im Register" if p1 == 1 else f"{_num(p1)} P1-Lücken im Register") if isinstance(p1, int) and p1 else
                                 "" if isinstance(p0, int) else "Kein Lückenregister geladen"),
                         source=str(gaps.get("source") or ""), href="/gaps", now=now)
    history = ops.get("history_recovery") or {}
    recover = make_tile("history_recovery", "Lückenreparatur", _word(history.get("reported_status") or history.get("status")),
                        history.get("status") or "UNAVAILABLE", source=str(history.get("source") or ""),
                        as_of=history.get("checked_at"),  # no fixed cadence known, so the age is shown but not judged
                        reason="" if str(history.get("status", "")).upper() == "PASS" else
                        ("Kein Bericht der Lückenreparatur" if _missing(history.get("status")) else f"Lückenreparatur meldet {history.get('status')}"),
                        href="/gaps", now=now)
    current_rooms = [room for room in ops.get("datasets") or [] if isinstance(room, dict) and _archive_reason(room) is None]
    archived = len([room for room in ops.get("datasets") or [] if isinstance(room, dict)]) - len(current_rooms)
    failing = [room for room in current_rooms if not str(room.get("status", "")).upper().startswith("PASS")]
    passing = [room for room in current_rooms if room not in failing]
    chosen = failing + passing[: max(0, 4 - len(failing))]
    left_out = len(current_rooms) - len(chosen)
    room_tiles = [make_tile(f"room_{i}", _text(room.get("label"), 40), _text(room.get("coverage")), room.get("status"),
                            reason="" if str(room.get("status", "")).upper().startswith("PASS") else f"Status {room.get('status')}",
                            source=str(room.get("source") or ""), href="/data-quality", now=now,
                            detail=f"{_num(room.get('observed'))} von {_num(room.get('expected'))} Minuten")
                  for i, room in enumerate(chosen)]
    rows = [[_cell(_local(g.get("start"))), _cell(_local(g.get("end"))), _cell(g.get("priority")), _cell(g.get("root_cause")),
             _cell(g.get("repairability")), _cell(g.get("status"))]
            for g in (gaps.get("rows") or [])[:ROWS_SHOWN] if isinstance(g, dict)]
    table = {"head": ["Von", "Bis", "Priorität", "Ursache", "Reparierbar", "Status"], "rows": rows} if rows else None
    return _section("quality", "Datenqualität", [gap_tile, recover] + room_tiles, table=table, empty="Keine Lücke im Register.",
                    note=("Aktuelle Evidenzräume" + (f" (weitere {left_out} grüne auf der Seite Datenqualität)" if left_out else "") + "; "
                          + ("ein abgeschlossener oder eingefrorener Raum steht" if archived == 1 else
                             f"{archived} abgeschlossene oder eingefrorene Räume stehen")
                          + " auf der alten Seite unter „Altbestand“."))


def _timeline_section(data: dict[str, Any], now: datetime) -> dict[str, Any]:
    events = [e for e in data.get("timeline") or [] if isinstance(e, dict)]
    shown = [e for e in reversed(events) if str(e.get("event")) not in {"VALIDATION_CYCLE", "RESEARCH_CYCLE_CHECK"}][:ROWS_SHOWN]
    routine = len(events) - len([e for e in events if str(e.get("event")) not in {"VALIDATION_CYCLE", "RESEARCH_CYCLE_CHECK"}])
    rows = [[_cell(_local(e.get("timestamp"))), _cell(e.get("event")), _cell(e.get("severity")), _cell(e.get("summary"))] for e in shown]
    table = {"head": ["Zeit", "Ereignis", "Stufe", "Inhalt"], "rows": rows} if rows else None
    return _section("timeline", "Zeitleiste", [], table=table,
                    empty="Keine besonderen Ereignisse in den letzten 50 Einträgen, nur Routine-Zyklen.",
                    note=f"Ohne Routine-Zyklen ({routine} von {len(events)} Einträgen ausgeblendet). Alles auf der Seite Zeitleiste.")


def build_betrieb(state: DashboardState, now: datetime | None = None, budget: float = 1.5,
                  sources: BudgetedSources | None = None) -> dict[str, Any]:
    from src.dashboard.cockpit.lage import _read_json

    now = now or datetime.now(timezone.utc)
    operational = state.operational_watchdog_path.parent
    results = (sources or _SOURCES["betrieb"]).run({
        "snapshot": state.snapshot,
        "backup": lambda: _read_json(operational / "backup_last_run.json"),
        "server_health": lambda: _read_json(operational / "server_health.json"),
    }, budget=budget)
    snap = results["snapshot"]
    if not snap.ok or not isinstance(snap.value, dict):
        sections = _safe_sections([("health", "Gesundheit", lambda: _health_section(results, now))]) + _snapshot_failed(snap, "Betrieb")
    else:
        data = snap.value if isinstance(snap.value, dict) else None
        ops = _dict((data or {}).get("operations"))
        sections = _safe_sections([
            ("health", "Gesundheit", lambda: _health_section(results, now)),
            ("runtime", "Datenpipeline", lambda: _runtime_section(ops, now)),
            ("quality", "Datenqualität", lambda: _quality_section(ops, now)),
            ("timeline", "Zeitleiste", lambda: _timeline_section(data, now)),
        ])
    return _model("betrieb", "Betrieb", sections, results, now)


# --- System & Freigabe ----------------------------------------------------------

SECURITY_METRICS = (
    ("listener_after", "Datenbank lauscht auf"), ("lan_exposure", "Erreichbar im Netz"),
    ("dashboard_binding", "Dashboard gebunden an"), ("observe_only", "Modus"),
    ("trading_actions", "Ausgeführte Handelsaktionen"), ("hba", "Zugangsregeln (pg_hba)"),
    ("credential_rotation", "Passwort-Rotation"), ("secret_provider", "Geheimnis-Speicher"), ("safe_stop", "Sicherer Stopp"),
)


def _mode_section(data: dict[str, Any], ops: dict[str, Any], now: datetime) -> dict[str, Any]:
    modes = {str(m) for m in (data.get("mode"), ops.get("mode")) if not _missing(m)}
    mode = " / ".join(sorted(modes))
    mode_tile = make_tile("mode", "Betriebsart", mode or "—", state="ok" if modes == {"OBSERVE"} else "fail",
                          reason="" if modes == {"OBSERVE"} else
                          (f"Quellen widersprechen sich: {mode}" if len(modes) > 1 else f"Betriebsart {mode or 'unbekannt'} statt OBSERVE"),
                          source="/api/state mode", now=now)
    locked = ops.get("trading_locked") is True and ops.get("execution_disabled") is True
    trade = make_tile("trading", "Handel", "gesperrt" if locked else "nicht bestätigt gesperrt", state="ok" if locked else "fail",
                      reason="" if locked else "operations.trading_locked/execution_disabled nicht beide wahr",
                      source="/api/state operations.trading_locked", now=now)
    readiness = ops.get("readiness") or {}
    status = str(readiness.get("status") or "UNAVAILABLE")
    v2 = make_tile("v2", "V2-Freigabe", "nicht qualifiziert" if "NOT QUALIFIED" in status.upper() else _word(readiness.get("status")),
                   state="unknown" if ("NOT QUALIFIED" in status.upper() or "STALE" in status.upper()) and not _faulty(status) else None,
                   raw_status=status, reason=_text(readiness.get("current_reason") or status, 200),
                   source=str(readiness.get("source") or ""), href="/v2-readiness", now=now)
    if "NOT QUALIFIED" in status.upper() and not _faulty(status):
        v2 = _parked(v2, "Nicht qualifiziert")
    return _section("mode", "Betriebsart und Freigabe", [mode_tile, trade, v2],
                    note="Den Handel kann keine Seite freischalten. Nur eine menschliche Freigabe-Instanz könnte das ändern, und V2 enthält kein Echtgeld.")


def _gates_section(ops: dict[str, Any], now: datetime) -> dict[str, Any]:
    readiness = ops.get("readiness") or {}
    gates = [g for g in readiness.get("gates") or [] if isinstance(g, dict)]
    source = str(readiness.get("source") or "")
    tiles, rows, passed = [], [], 0
    for index, gate in enumerate(gates):
        gid = gate.get("id") if not _missing(gate.get("id")) else f"nr{index + 1}"
        current = gate.get("current_status")
        recorded = gate.get("status")
        shown = current if not _missing(current) else recorded
        human = _human_gate(shown)
        archive_only = _missing(current) and not human
        label = f"{_text(gate.get('id'), 12)} {_text(gate.get('name'), 50)}"
        if human and "NOT APPLICABLE" in str(shown).upper().replace("_", " "):
            tile = _parked(make_tile(f"gate_{gid}", label, _word(shown), state="unknown",
                                     reason=_text(gate.get("current_note"), 200) if not _missing(gate.get("current_note"))
                                     else "Gilt für diesen Stand nicht", source=source, href="/v2-readiness", now=now),
                           "Entfällt")
        elif human:
            tile = _parked(make_tile(f"gate_{gid}", label, _word(shown), state="unknown",
                                     reason="Menschlicher Schritt, kein technischer Fehler", source=source, href="/v2-readiness", now=now),
                           "Wartet auf euch")
        elif archive_only and _faulty(recorded):
            tile = make_tile(f"gate_{gid}", label, _word(recorded), state="warn",
                             reason="Archivwert ist ein Fehler, heute nicht neu gemessen", source=source, href="/v2-readiness", now=now)
        elif archive_only:
            tile = _parked(make_tile(f"gate_{gid}", label, _word(recorded), state="unknown",
                                     reason="Nur Archivwert, heute nicht neu gemessen", source=source, href="/v2-readiness", now=now),
                           "Nur Archiv")
        else:
            tile = make_tile(f"gate_{gid}", label, _word(shown), shown, reason=_text(gate.get("current_note"), 200),
                             source=source, href="/v2-readiness", now=now)
            if tile.state == "ok":
                tile.reason = ""
        if tile.state == "ok":
            passed += 1
        else:
            tiles.append(tile)
        rows.append([_cell(gate.get("id")), _cell(gate.get("name")), _cell(_word(recorded)), _cell(_word(current)),
                     _cell(gate.get("owner"))])
    if gates:
        tiles.insert(0, _info(make_tile("gates_summary", "Heute bestanden", f"{passed} von {len(gates)} Gates", state="ok",
                                        source=source, href="/v2-readiness", now=now,
                                        detail="Grüne Gates stehen nur in der Tabelle, Kacheln zeigen den Rest.")))
    table = {"head": ["Gate", "Name", "Archiv", "Heute", "Verantwortlich"], "rows": rows} if rows else None
    return _section("gates", "V2-Gates", tiles, table=table, empty="Kein Gate-Modell geladen.",
                    note="„Heute“ ist neu gemessen; „Archiv“ ist der eingefrorene Stand vom 01.08.2026. Grau heißt: nur Archivwert oder menschlicher Schritt.")


def _security_section(ops: dict[str, Any], now: datetime) -> dict[str, Any]:
    security = ops.get("security") or {}
    tiles = []
    for key, label in SECURITY_METRICS:
        metric = security.get(key)
        if key == "trading_actions" and isinstance(metric, dict):
            # Judged by the number alone: zero is green, any other count red, no readable number grey.
            count = _count(metric.get("value"))
            metric = {**metric, "status": "UNAVAILABLE" if count is None else ("PASS" if count == 0 else "FAIL")}
        if key == "observe_only" and isinstance(metric, dict):
            value = metric.get("value")
            ok = value is True or str(value).strip().upper() == "OBSERVE"
            metric = {**metric, "status": "PASS" if ok else "FAIL"}
        tiles.append(_metric_tile(f"sec_{key}", label, metric, "/security", judge=True, now=now))
    shown, missing = _split_missing(tiles)
    note = f"Zuletzt live geprüft {_local(security.get('last_test'))} Uhr."
    if missing:
        note += f" Ohne maschinenlesbare Prüfung (Details auf der Seite Security): {', '.join(missing)}."
    return _section("security", "Sicherheit", shown or [unavailable("sec_none", "Sicherheit", "Keine Sicherheitsprüfung im TIM-Zustand", "operations.security", "/security")],
                    note=note)


def _audit_section(ops: dict[str, Any], now: datetime) -> dict[str, Any]:
    audit = ops.get("audit") or {}
    commit = str(audit.get("deployed_commit") or "")
    deploy = (unavailable("deploy", "Laufender Stand", "Kein Deployment-Eintrag", "data/operational/deployment.json", "/audit-evidence")
              if _missing(commit) else
              _info(make_tile("deploy", "Laufender Stand", commit[:7], state="ok", source="data/operational/deployment.json",
                              as_of=audit.get("deployed_at"), href="/audit-evidence", now=now,
                              detail=f"eingespielt {_local(audit.get('deployed_at'))} Uhr")))
    tests = make_tile("tests", "CI-Test", f"{_num(audit.get('passed'))} grün, {_num(audit.get('failed'))} rot",
                      audit.get("test_status"), reason="" if str(audit.get("test_status")).upper() == "PASS" else
                      (f"Letzter Lauf {_word(audit.get('test_status'))}" if not _missing(audit.get("test_status")) else "Kein Testergebnis in der Quelle"),
                      source=_text(audit.get("test_source"), 120), as_of=audit.get("last_test"), href="/audit-evidence", now=now)
    doctor = make_tile("doctor", "Doctor", _word(audit.get("doctor")), audit.get("doctor"),
                       reason="" if str(audit.get("doctor")).upper() == "PASS" else "Doctor ohne PASS", source="final_test_summary.json",
                       href="/audit-evidence", now=now)
    validate = make_tile("validate", "Validate", _word(audit.get("validate")), audit.get("validate"),
                         reason="" if str(audit.get("validate")).upper() == "PASS" else "Validate ohne PASS", source="final_test_summary.json",
                         href="/audit-evidence", now=now)
    protected = make_tile("protected", "Geschützte Dateien", _word(audit.get("protected_state")), audit.get("protected_state"),
                          reason="" if str(audit.get("protected_state")).upper().startswith("PASS") else "Prüfsummen weichen ab oder fehlen",
                          source="protected_state", href="/audit-evidence", now=now)
    mcp = ops.get("mcp") or {}
    mcp_status = str(mcp.get("status") or "")
    mcp_external = "EXTERNAL" in mcp_status.upper() and not _faulty(mcp_status.upper().replace("BLOCKED", ""))
    mcp_tile = make_tile("mcp", "Secure MCP (extern)", _word(mcp.get("status")), mcp_status or None,
                         state="unknown" if mcp_external or _missing(mcp.get("status")) else None,
                         reason="Externer Weg, gehört nicht zum V2-Kern; wartet auf Schritt bei OpenAI" if mcp_external
                         else ("" if not _faulty(mcp_status) and mcp_status.upper() in {"PASS", "OK", "GREEN"} else _text(mcp.get("status"))), source=str(mcp.get("source") or ""), href="/mcp", now=now)
    if mcp_external:
        mcp_tile = _parked(mcp_tile, "Extern")
    incidents = [i for i in audit.get("incidents") or [] if isinstance(i, dict)][:ROWS_SHOWN]
    rows = [[_cell(_local(i.get("timestamp_utc") or i.get("timestamp"))), _cell(i.get("severity")), _cell(i.get("event")),
             _cell(i.get("component_id")), _cell(i.get("reason_code") or i.get("summary"))] for i in incidents]
    table = {"head": ["Zeit", "Stufe", "Ereignis", "Komponente", "Grund"], "rows": rows} if rows else None
    return _section("audit", "Prüfung und Nachweise", [deploy, tests, doctor, validate, protected, mcp_tile], table=table,
                    empty="Kein Vorfall im begrenzten Zeitfenster.")


def build_system(state: DashboardState, now: datetime | None = None, budget: float = 1.5,
                 sources: BudgetedSources | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    results = (sources or _SOURCES["system"]).run({"snapshot": state.snapshot}, budget=budget)
    snap = results["snapshot"]
    if not snap.ok or not isinstance(snap.value, dict):
        sections = _snapshot_failed(snap, "System & Freigabe")
    else:
        data = snap.value if isinstance(snap.value, dict) else None
        ops = _dict((data or {}).get("operations"))
        sections = _safe_sections([
            ("mode", "Betriebsart und Freigabe", lambda: _mode_section(data, ops, now)),
            ("gates", "V2-Gates", lambda: _gates_section(ops, now)),
            ("security", "Sicherheit", lambda: _security_section(ops, now)),
            ("audit", "Prüfung und Nachweise", lambda: _audit_section(ops, now)),
        ])
    return _model("system", "System & Freigabe", sections, results, now)


BUILDERS = {"forschung": build_forschung, "betrieb": build_betrieb, "system": build_system}
