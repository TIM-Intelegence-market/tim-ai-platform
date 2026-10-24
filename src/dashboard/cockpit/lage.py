"""Data model of the cockpit start page "Lage".

Read only: every value comes from what TIM already writes (state snapshot,
chart candles, plan and trader journal, backup report). Nothing here computes
a new signal or writes a file.
"""

from __future__ import annotations

import json
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.dashboard.cockpit.sources import BudgetedSources, SourceResult
from src.dashboard.cockpit.tiles import Tile, attention, human_age, make_tile, unavailable, worst
from src.dashboard.state import DashboardState

SCHEMA = "tim_cockpit_lage/1"
SETUP_CANDLES = 80  # same window as the Setup-Pfad page (views.SETUP_CHART_CANDLES)
MARKET_DATA_MAX_AGE = 120
REPORT_MAX_AGE = 300
BACKUP_MAX_AGE = 26 * 3600  # daily backup at 03:15 plus slack
PLAN_JOURNAL_MAX_AGE = 45 * 60  # two 15m closes plus slack
PRICE_MAX_AGE = {"1m": 180, "5m": 600, "15m": 1800, "1h": 5400}
WORDS = {"GREEN": "grün", "PASS": "grün", "YELLOW": "gelb", "WARN": "gelb", "RED": "rot", "FAIL": "rot"}
UNAVAILABLE_WORDS = {None, "", "NONE", "UNAVAILABLE", "UNKNOWN", "MISSING", "—"}
SERVER_HEALTH_MAX_AGE = 600

_SOURCES = BudgetedSources()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _price(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _r(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:+.2f} R".replace(".", ",")


def _duration(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} T {hours} h"
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _missing(value: Any) -> bool:
    return str(value).strip().upper() in UNAVAILABLE_WORDS if value is not None else True


def _count(value: Any) -> str:
    return "—" if _missing(value) else str(value)


def _jobs(state: DashboardState) -> dict[str, Any]:
    # One copy of the candles per request, shared by price, chart and preparation.
    series_lock, series_box = threading.Lock(), {}

    def series() -> dict[str, Any]:
        with series_lock:
            if "value" not in series_box:
                series_box["value"] = state.chart_series()
            return series_box["value"]

    def chart() -> dict[str, Any]:
        from src.dashboard.chart_model import build_chart_model

        return build_chart_model(series(), "15m", visible=SETUP_CANDLES)

    def prep() -> dict[str, Any]:
        from src.dashboard.session_map import build_session_map

        return build_session_map(series())

    def plan_journal() -> dict[str, Any]:
        from src.dashboard.plan_journal import load_view, summary

        journal = load_view(state.plan_journal_path)
        return {"journal": journal, "summary": summary(journal)}

    def trader_journal() -> dict[str, Any]:
        from src.dashboard import trader_journal as tj

        journal = tj.load(state.trader_journal_path)
        return {"exists": state.trader_journal_path.exists(), "summary": tj.summary(journal)}

    def worker() -> dict[str, Any]:
        from src.dashboard.cockpit.mac import fetch_worker

        return fetch_worker()

    operational = state.operational_watchdog_path.parent
    return {
        "snapshot": state.snapshot,
        "worker": worker,
        "series": series,
        "chart": chart,
        "prep": prep,
        "plan_journal": plan_journal,
        "trader_journal": trader_journal,
        "backup": lambda: _read_json(operational / "backup_last_run.json"),
        "server_health": lambda: _read_json(operational / "server_health.json"),
    }


# --- system ---------------------------------------------------------------

def _system_tiles(snap: SourceResult, backup: SourceResult, server: SourceResult, now: datetime) -> list[Tile]:
    if not snap.ok:
        reason = snap.reason()
        return [unavailable(key, label, reason, "DashboardState.snapshot()", href) for key, label, href in (
            ("runtime", "TIM-Laufzeit", "/runtime"), ("market_data", "Marktdaten", "/data-quality"),
            ("database", "Datenbank", "/runtime"), ("watchdog", "Watchdog", "/health"),
            ("deploy", "Deploy-Stand", "/audit-evidence"), ("ci", "CI-Test", "/audit-evidence"))] + [_backup_tile(backup, now)]
    data = snap.value
    health = data.get("operational_health") or {}
    ops = data.get("operations") or {}
    audit = ops.get("audit") or {}
    current = ops.get("current_status") or {}

    # Runtime: this process answers, so it runs. Its colour is the live health of stream and database.
    problems = []
    if health.get("database") != "GREEN":
        problems.append("Datenbank nicht verbunden")
    age = _number(health.get("data_age_seconds"))
    fresh = age is not None and 0 <= age <= MARKET_DATA_MAX_AGE
    if health.get("stream") != "GREEN":
        stream_raw = (data.get("system_health") or {}).get("stream")
        problems.append(f"Datenstrom {stream_raw or 'unbekannt'}" + ("" if fresh else ", keine frischen Daten"))
    failing, server_red, server_note = [], False, ""
    report = server.value if server.ok and isinstance(server.value, dict) else {}
    checks = report.get("checks")
    if isinstance(checks, dict):
        from src.dashboard.cockpit.tiles import age_seconds as _age

        server_age = _age(report.get("checked_at") or report.get("timestamp"), now)
        if server_age is None or server_age > SERVER_HEALTH_MAX_AGE:
            server_note = f"Server-Check veraltet ({human_age(server_age)}), nicht gewertet"
        else:
            for name, check in checks.items():
                status = str(check.get("status", "")).upper() if isinstance(check, dict) else ""
                if status in {"RED", "FAIL", "YELLOW", "WARN"}:
                    failing.append(f"Server-Check {name}: {check.get('reason') or status}")
                    server_red = server_red or status in {"RED", "FAIL"}
    uptime = None
    started = health.get("runtime_started_at")
    if started:
        from src.dashboard.cockpit.tiles import age_seconds

        uptime = age_seconds(started, now)
    runtime_raw = health.get("status")
    if failing and runtime_raw == "GREEN":
        runtime_raw = "RED" if server_red else "YELLOW"
    runtime = make_tile(
        "runtime", "TIM-Laufzeit", f"läuft seit {_duration(uptime)}", runtime_raw,
        reason=" · ".join(problems + failing[:3]), source="/api/state operational_health, data/operational/server_health.json",
        as_of=health.get("checked_at"), href="/runtime", now=now, detail=server_note,
    )

    stream = health.get("stream")
    if stream == "GREEN" and fresh:
        market = make_tile("market_data", "Marktdaten", human_age(int(age)), "PASS", source="Binance Spot über TIM-Runtime",
                           as_of=health.get("last_data_at"), max_age_seconds=MARKET_DATA_MAX_AGE, href="/data-quality", now=now)
    elif health.get("last_data_at"):
        stream_raw = (data.get("system_health") or {}).get("stream") or "unbekannt"
        market = make_tile("market_data", "Marktdaten", human_age(int(age)) if age is not None else "—",
                           "FAIL" if stream != "GREEN" else "WARN",
                           reason=f"Datenstrom {stream_raw}" if stream != "GREEN" else "",
                           source="Binance Spot über TIM-Runtime", as_of=health.get("last_data_at"),
                           max_age_seconds=MARKET_DATA_MAX_AGE, href="/data-quality", now=now)
    else:
        market = unavailable("market_data", "Marktdaten", "Noch keine Marktdaten seit dem Start dieses Prozesses", "/api/state", "/data-quality")

    database = make_tile("database", "Datenbank", "verbunden" if health.get("database") == "GREEN" else "nicht verbunden",
                         health.get("database"), reason="" if health.get("database") == "GREEN" else "PostgreSQL meldet keine Verbindung",
                         source="/api/state system_health.database", href="/runtime", now=now)

    watch = current.get("watchdog") if isinstance(current.get("watchdog"), dict) else {}
    findings = [f for f in watch.get("findings") or [] if isinstance(f, dict)] if isinstance(watch.get("findings"), list) else []
    reported = str(watch.get("reported_status") or "").upper()
    reported = {"ATTENTION_REQUIRED": "FAIL", "ERROR": "FAIL"}.get(reported, reported)
    watchdog = make_tile(
        "watchdog", "Watchdog", WORDS.get(reported, reported or "—"),
        reported if watch.get("checked_at") else "UNAVAILABLE",
        reason="; ".join(f"{f.get('check')}: {f.get('reason') or f.get('status')}" for f in findings[:3])
        or ("Watchdog hat noch keinen Bericht geschrieben" if not watch.get("checked_at") else ""),
        source=str(watch.get("source") or "data/operational/watchdog_status.json"),
        as_of=watch.get("checked_at"), max_age_seconds=REPORT_MAX_AGE if watch.get("checked_at") else None,
        href="/health", now=now,
    )

    refresh = audit.get("dashboard_refresh") or {}
    commit = str(audit.get("deployed_commit") or "")
    agent_state = str(refresh.get("status") or "UNAVAILABLE")
    deploy_state = {"PASS": "ok", "WAITING": "ok", "FAIL": "fail"}.get(agent_state, "warn")
    if commit in UNAVAILABLE_WORDS:
        deploy = unavailable("deploy", "Deploy-Stand", "Kein Deployment-Eintrag (data/operational/deployment.json)", "data/operational/deployment.json", "/audit-evidence")
    else:
        deploy = make_tile(
            "deploy", "Deploy-Stand", commit[:7], state=deploy_state,
            reason="" if deploy_state == "ok" else f"Dashboard-Agent {agent_state}: {refresh.get('note') or refresh.get('reason') or ''}".strip(" :"),
            source="data/operational/deployment.json", as_of=audit.get("deployed_at"), href="/audit-evidence", now=now,
            detail=f"Dashboard-Agent: {refresh.get('note') or agent_state}",
        )

    test_status = audit.get("test_status")
    passed, failed = audit.get("passed"), audit.get("failed")
    if _missing(test_status):
        ci = unavailable("ci", "CI-Test", "Kein CI-Ergebnis für den laufenden Stand gefunden", str(audit.get("test_source") or ""), "/audit-evidence")
    else:
        ci = make_tile(
            "ci", "CI-Test", f"{_count(passed)} grün · {_count(failed)} rot", test_status,
            reason="" if str(test_status).upper() == "PASS" else f"Letzter Volllauf: {test_status}",
            source=str(audit.get("test_source") or ""), as_of=audit.get("last_test"), href="/audit-evidence", now=now,
        )
    return [runtime, market, database, watchdog, _backup_tile(backup, now), deploy, ci]


def _backup_tile(backup: SourceResult, now: datetime) -> Tile:
    source = "data/operational/backup_last_run.json"
    if not backup.ok:
        return unavailable("backup", "Backup", backup.reason(), source, "/timeline")
    report = backup.value or {}
    if not report.get("completed_at"):
        return unavailable("backup", "Backup", "Noch kein Backup-Bericht vorhanden", source, "/timeline")
    size = report.get("bytes")
    text = f"{size / 1e9:.1f} GB".replace(".", ",") if isinstance(size, (int, float)) and not isinstance(size, bool) else "Größe unbekannt"
    status = str(report.get("status") or "UNKNOWN").upper()
    return make_tile("backup", "Backup", text, status, reason="" if status == "PASS" else f"Backup meldet {status}",
                     source=source, as_of=report["completed_at"], max_age_seconds=BACKUP_MAX_AGE, href="/timeline", now=now)


# --- market ---------------------------------------------------------------

def _info(tile: Tile) -> Tile:
    tile.extra["kind"] = "info"
    return tile


def _market_tiles(series: SourceResult, chart: SourceResult, prep: SourceResult, now: datetime) -> tuple[list[Tile], list[dict[str, Any]]]:
    tiles: list[Tile] = []
    plans: list[dict[str, Any]] = []
    price = unavailable("price", "BTC-Preis", series.reason() or "Noch keine Kerzen im Speicher dieses Prozesses", "TIM-Runtime Kerzen", "/chart")
    if series.ok:
        for timeframe in ("1m", "5m", "15m", "1h"):
            candles = [c for c in (series.value or {}).get(timeframe) or [] if isinstance(c, dict) and c.get("close") is not None]
            if candles:
                last = max(candles, key=lambda c: str(c.get("close_time") or c.get("open_time") or ""))
                price = make_tile("price", "BTC-Preis", f"{_price(last.get('close'))} $", "PASS",
                                  source=f"BTCUSDT {timeframe}-Kerze, Binance Spot", as_of=last.get("close_time") or last.get("open_time"),
                                  max_age_seconds=PRICE_MAX_AGE[timeframe], href="/chart", now=now)
                break
    tiles.append(_info(price))

    if not chart.ok:
        for key, label in (("market_state", "Marktzustand"), ("setup", "Setup-Pfad"), ("block", "Nächste Sperrzeit")):
            tiles.append(_info(unavailable(key, label, chart.reason(), "15m-Chartanalyse", "/setup-path")))
    else:
        model = chart.value or {}
        analysis = model.get("analysis") or {}
        candle_time = (model.get("levels") or {}).get("last_time")
        if analysis.get("market_state"):
            tiles.append(_info(make_tile("market_state", "Marktzustand", str(analysis["market_state"]), "PASS",
                                         source="TIMs Pipeline auf 15m (80 Kerzen)", as_of=candle_time, max_age_seconds=PRICE_MAX_AGE["15m"],
                                         detail=f"Auktion {analysis.get('auction_state') or 'unbekannt'}", href="/setup-path", now=now)))
            scenarios = [s for s in analysis.get("scenarios") or [] if isinstance(s, dict) and s.get("plan_text")]
            decision = str((analysis.get("decision") or {}).get("status") or "UNAVAILABLE")
            missing = sorted({str(m) for s in scenarios for m in (s.get("missing_confirmations") or [])})
            where = "an einer Range-Kante" if scenarios else "in der Range-Mitte, kein Plan"
            tiles.append(_info(make_tile("setup", "Setup-Pfad", decision, "PASS", source="TIMs Pipeline auf 15m",
                                         as_of=candle_time, max_age_seconds=PRICE_MAX_AGE["15m"], href="/setup-path", now=now,
                                         detail=f"Kurs {where}" + (f" · fehlt: {', '.join(missing[:3])}" if missing else ""))))
            from src.dashboard.pages.setup_path import _plan_lines

            for scenario in scenarios[:2]:
                lines = _plan_lines(scenario, analysis.get("market_state"))
                plans.append({"direction": str(scenario.get("direction") or ""), "title": lines[0], "lines": lines[1:]})
        else:
            note = "; ".join(str(n) for n in model.get("notes") or []) or "TIMs Chartanalyse hat noch keinen Marktzustand"
            tiles.append(_info(unavailable("market_state", "Marktzustand", note, "15m-Chartanalyse", "/setup-path")))
            tiles.append(_info(unavailable("setup", "Setup-Pfad", note, "15m-Chartanalyse", "/setup-path")))
        block = model.get("next_block")
        if isinstance(block, dict) and block.get("start"):
            tiles.append(_info(make_tile("block", "Nächste Sperrzeit", block.get("label") or "NY-Eröffnung", "PASS",
                                         source="NY-Eröffnung, 15 min davor bis 30 min danach", href="/chart", now=now,
                                         extra={"start": block.get("start"), "end": block.get("end")})))
        else:
            tiles.append(_info(make_tile("block", "Nächste Sperrzeit", "keine in 24 h", "PASS",
                                         source="NY-Eröffnung, 15 min davor bis 30 min danach", href="/chart", now=now,
                                         detail="Keine NY-Eröffnung in den nächsten 24 Stunden")))

    bias_word = str(((prep.value or {}).get("bias") or {}).get("bias") or "UNKNOWN") if prep.ok else "UNKNOWN"
    if bias_word != "UNKNOWN":
        from src.dashboard.session_map import summary_line

        bias = prep.value["bias"]
        tiles.append(_info(make_tile("bias", "Übergeordneter Bias", str(bias.get("bias") or "—"), "PASS",
                                     source="Vorbereitung: 1h-Struktur, Tages- und Wochen-Value", href="/prep", now=now,
                                     detail=summary_line(prep.value))))
    else:
        bias_text = ((prep.value or {}).get("bias") or {}).get("text") if prep.ok else None
        reason = prep.reason() if not prep.ok else bias_text or "; ".join(str(n) for n in (prep.value or {}).get("notes") or []) or "Zu wenige Kerzen für den Bias"
        tiles.append(_info(unavailable("bias", "Übergeordneter Bias", reason, "Vorbereitung", "/prep")))
    return tiles, plans


# --- journals -------------------------------------------------------------

def _journal_tiles(plan: SourceResult, trader: SourceResult, now: datetime) -> list[Tile]:
    tiles = []
    if not plan.ok:
        tiles.append(unavailable("plan_journal", "Plan-Journal", plan.reason(), "data/journal/tim_plan_journal.json", "/journal"))
    else:
        journal, stats = plan.value["journal"], plan.value["summary"]
        integrity = str(journal.get("integrity") or "")
        if integrity.startswith("LOG_BROKEN"):
            tiles.append(make_tile("plan_journal", "Plan-Journal", "gesperrt", "FAIL", reason="Ereignislog beschädigt: " + integrity[11:120],
                                   source="data/journal/tim_plan_journal.events.jsonl", href="/journal", now=now))
        elif not stats["plans"] and not journal.get("last_plan_candle"):
            tiles.append(unavailable("plan_journal", "Plan-Journal", "Noch kein Plan festgehalten", "data/journal/tim_plan_journal.json", "/journal"))
        else:
            tiles.append(make_tile(
                "plan_journal", "Plan-Journal", f"{stats['open']} warten · {stats['filled']} im Trade", "PASS",
                source="data/journal/tim_plan_journal.json", as_of=journal.get("last_plan_candle"),
                max_age_seconds=PLAN_JOURNAL_MAX_AGE, href="/journal", now=now,
                detail=f"{stats['closed']} geschlossen · netto {_r(stats['sum_net_r'])} · nur Papier",
            ))
    if not trader.ok:
        tiles.append(unavailable("trader_journal", "Trader-Journal", trader.reason(), "data/journal/trader_journal.json", "/trader-journal"))
    else:
        stats = trader.value["summary"]
        if not stats["entries"]:
            tiles.append(unavailable("trader_journal", "Trader-Journal", "Noch kein Eintrag", "data/journal/trader_journal.json", "/trader-journal"))
        else:
            review = stats["review_open"]
            tiles.append(make_tile(
                "trader_journal", "Trader-Journal", f"{stats['open'] + stats['filled']} offen · {stats['closed']} geschlossen",
                "WARN" if review else "PASS", reason=f"{review} Review(s) offen" if review else "",
                source="data/journal/trader_journal.json", href="/trader-journal", now=now,
                detail=f"Summe {_r(stats['sum_r'])} · nur Papier",
            ))
    return tiles


# --- whole page -----------------------------------------------------------

SYSTEM_TILES = (("runtime", "TIM-Laufzeit", "/runtime"), ("market_data", "Marktdaten", "/data-quality"),
                ("database", "Datenbank", "/runtime"), ("watchdog", "Watchdog", "/health"), ("backup", "Backup", "/timeline"),
                ("deploy", "Deploy-Stand", "/audit-evidence"), ("ci", "CI-Test", "/audit-evidence"))
MARKET_TILES = (("price", "BTC-Preis", "/chart"), ("market_state", "Marktzustand", "/setup-path"), ("setup", "Setup-Pfad", "/setup-path"),
                ("block", "Nächste Sperrzeit", "/chart"), ("bias", "Übergeordneter Bias", "/prep"))
MAC_TILES = (("worker", "Issue-Worker", "/neu/mac"), ("ci_runner", "CI-Runner", "/neu/mac"))
JOURNAL_TILES = (("plan_journal", "Plan-Journal", "/journal"), ("trader_journal", "Trader-Journal", "/trader-journal"))


def _broken(exc: Exception) -> str:
    return f"Unerwartetes Datenformat: {type(exc).__name__}: {str(exc)[:120]}"


def build_lage(state: DashboardState, now: datetime | None = None, budget: float = 1.5, sources: BudgetedSources | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    results = (sources or _SOURCES).run(_jobs(state), budget=budget)
    try:
        system = _system_tiles(results["snapshot"], results["backup"], results["server_health"], now)
    except Exception as exc:  # noqa: BLE001 - unexpected data shape: grey tiles with the reason, not a broken page
        system = [unavailable(key, label, _broken(exc), "Kachelbau System", href) for key, label, href in SYSTEM_TILES]
    try:
        market, plans = _market_tiles(results["series"], results["chart"], results["prep"], now)
    except Exception as exc:  # noqa: BLE001
        market, plans = [_info(unavailable(key, label, _broken(exc), "Kachelbau Markt", href)) for key, label, href in MARKET_TILES], []
    try:
        journals = _journal_tiles(results["plan_journal"], results["trader_journal"], now)
    except Exception as exc:  # noqa: BLE001
        journals = [unavailable(key, label, _broken(exc), "Kachelbau Journale", href) for key, label, href in JOURNAL_TILES]
    try:
        from src.dashboard.cockpit.mac import worker_tiles

        mac = [t for t in worker_tiles(results["worker"], now)[0] if t.id in {"worker", "ci_runner"}]
    except Exception as exc:  # noqa: BLE001
        mac = [unavailable(key, label, _broken(exc), "Kachelbau Mac", "/neu/mac") for key, label, _ in MAC_TILES]
    needs = attention(system + journals + mac + [t for t in market if t.state in {"fail", "warn"}])
    overall = worst([t.state for t in system])
    if any(t.state == "fail" for t in needs):
        headline = f"{sum(t.state == 'fail' for t in needs)} Fehler, bitte ansehen"
    elif needs:
        headline = f"{len(needs)} Punkt(e) brauchen einen Blick"
    elif overall == "ok":
        headline = "Alles in Ordnung"
    else:
        headline = "Nicht alle Quellen liefern Daten"
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "mode": "OBSERVE",
        "safety": "Nur Beobachtung und Papier, kein Handel",
        "headline": headline,
        "overall": overall if not needs else ("fail" if any(t.state == "fail" for t in needs) else "warn"),
        "system": [t.to_dict() for t in system],
        "market": [t.to_dict() for t in market],
        "plans": plans,
        "journals": [t.to_dict() for t in journals],
        "mac": [t.to_dict() for t in mac],
        "attention": [t.to_dict() for t in needs],
        "sources": {name: {"ok": r.ok, "seconds": r.seconds, "error": r.error, "stale_seconds": r.stale_seconds} for name, r in results.items()},
    }
