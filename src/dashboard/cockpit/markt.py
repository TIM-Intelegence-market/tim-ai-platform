"""Data model of the cockpit area "Markt & Pläne".

Chart with TIM's plans, preparation (bias, value, levels, sessions), the plan
journal and the trader journal on one page. Read only: the same builders as the
old pages (/chart, /prep, /journal, /trader-journal), no new calculation.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from src.dashboard.cockpit.lage import SETUP_CANDLES, _broken, _info, _journal_tiles, _market_tiles, _r, MARKET_TILES, JOURNAL_TILES
from src.dashboard.cockpit.sources import BudgetedSources, SourceResult
from src.dashboard.cockpit.tiles import unavailable
from src.dashboard.state import DashboardState

SCHEMA = "tim_cockpit_markt/1"
from src.dashboard.chart_history import TIMEFRAMES
DEFAULT_TIMEFRAME = "30m"
LEVELS_EACH_SIDE = 4
CLOSED_SHOWN = 5
ACTIVE = {"OPEN", "FILLED"}
FINISHED = {"CLOSED", "INVALIDATED", "EXPIRED", "REPLACED"}

_SOURCES = BudgetedSources()


def timeframe_of(value: Any) -> str:
    text = str(value or "")
    return text if text in TIMEFRAMES else DEFAULT_TIMEFRAME


def _jobs(state: DashboardState, timeframe: str) -> dict[str, Any]:
    series_lock, series_box = threading.Lock(), {}

    def series() -> dict[str, Any]:
        with series_lock:
            if "value" not in series_box:
                series_box["value"] = state.chart_series()
            return series_box["value"]

    def chart() -> dict[str, Any]:
        from src.dashboard.chart_model import build_chart_model

        return build_chart_model(series(), "30m", visible=SETUP_CANDLES)

    def chart_other() -> dict[str, Any]:
        from src.dashboard.chart_model import build_chart_model

        return build_chart_model(series(), timeframe)

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
        return {"exists": state.trader_journal_path.exists(), "summary": tj.summary(journal), "journal": journal}

    jobs = {"series": series, "chart": chart, "prep": prep, "plan_journal": plan_journal, "trader_journal": trader_journal}
    if timeframe != "30m":
        jobs[f"chart_{timeframe}"] = chart_other
    return jobs


def _chart(result: SourceResult, timeframe: str) -> dict[str, Any]:
    if not result.ok:
        return {"timeframe": timeframe, "svg": None, "note": result.reason()}
    model = result.value or {}
    if not model.get("candles"):
        return {"timeframe": timeframe, "svg": None, "note": "Noch keine Kerzen für diesen Zeitrahmen. Der Chart erscheint, sobald die Runtime Daten liefert.",
                "available": list(model.get("available_timeframes") or [])}
    from src.dashboard.pages.chart import _chart_svg

    analysis = model.get("analysis") or {}
    decision = analysis.get("decision") or {}
    return {
        "timeframe": model.get("timeframe") or timeframe,
        "svg": _chart_svg(model),
        "candles": len(model.get("candles") or []),
        "available": list(model.get("available_timeframes") or []),
        "decision": str(decision.get("status") or "UNAVAILABLE"),
        "decision_reasons": [str(item) for item in decision.get("reasons") or []][:4],
        "notes": [str(item) for item in model.get("notes") or []][:4],
        "last_time": (model.get("levels") or {}).get("last_time"),
    }


def _prep(result: SourceResult) -> dict[str, Any]:
    if not result.ok:
        return {"ok": False, "note": result.reason()}
    model = result.value or {}
    if not model.get("levels") and not model.get("htf"):
        return {"ok": False, "note": " ".join(str(n) for n in model.get("notes") or []) or "Zu wenige Kerzen für die Vorbereitung."}
    levels = [lvl for lvl in model.get("levels") or [] if isinstance(lvl, dict) and isinstance(lvl.get("price"), (int, float))]
    last = model.get("last")
    above = [lvl for lvl in levels if isinstance(last, (int, float)) and lvl["price"] >= last][-LEVELS_EACH_SIDE:]
    below = [lvl for lvl in levels if isinstance(last, (int, float)) and lvl["price"] < last][:LEVELS_EACH_SIDE]
    htf = model.get("htf") or {}
    return {
        "ok": True,
        "bias": (model.get("bias") or {}).get("bias") or "UNKNOWN",
        "bias_text": (model.get("bias") or {}).get("text") or "",
        "location": (model.get("location") or {}).get("label") or "",
        "location_hint": (model.get("location") or {}).get("hint") or "",
        "last": last,
        "last_time": model.get("last_time"),
        "htf": [{"label": label, "state": str(info.get("state") or "UNKNOWN"), "text": str(info.get("text") or "")}
                for label, info in htf.items() if isinstance(info, dict)],
        "above": [{"label": str(lvl.get("label")), "price": lvl["price"], "distance_pct": lvl.get("distance_pct")} for lvl in above],
        "below": [{"label": str(lvl.get("label")), "price": lvl["price"], "distance_pct": lvl.get("distance_pct")} for lvl in below],
        "levels_total": len(levels),
        "sessions": [{"name": str(s.get("name")), "start": s.get("start"), "end": s.get("end"), "high": s.get("high"), "low": s.get("low"),
                      "running": bool(s.get("running"))} for s in model.get("sessions") or [] if isinstance(s, dict)],
        "notes": [str(n) for n in model.get("notes") or []][:3],
    }


def _plan_rows(result: SourceResult) -> dict[str, Any]:
    if not result.ok:
        return {"active": [], "closed": [], "note": result.reason()}
    journal = result.value.get("journal") or {}
    entries = [e for e in journal.get("entries") or [] if isinstance(e, dict)]
    active = sorted((e for e in entries if e.get("status") in ACTIVE), key=lambda e: str(e.get("created_at") or ""), reverse=True)
    closed = sorted((e for e in entries if e.get("status") in FINISHED), key=lambda e: str(e.get("closed_at") or e.get("created_at") or ""), reverse=True)

    def row(entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(entry.get("id") or entry.get("scenario_id") or ""),
            "created_at": entry.get("created_at"), "closed_at": entry.get("closed_at"), "filled_at": entry.get("filled_at"),
            "direction": str(entry.get("direction") or ""), "status": str(entry.get("status") or ""),
            "scenario": str(entry.get("scenario_id") or ""), "entry": entry.get("entry"), "stop": entry.get("stop"),
            "targets": [t for t in entry.get("targets") or [] if isinstance(t, (int, float))][:3],
            "tp_hits": len(entry.get("tp_hits") or []), "exit_reason": str(entry.get("exit_reason") or ""),
            "net_r": entry.get("net_r"), "gross_r": entry.get("gross_r"), "market_state": str(entry.get("market_state") or ""),
            "decision": str(entry.get("journal_decision") or ""),
        }

    return {"active": [row(e) for e in active[:10]], "closed": [row(e) for e in closed[:CLOSED_SHOWN]],
            "integrity": str(journal.get("integrity") or ""), "summary": result.value.get("summary") or {}}


def _trader_rows(result: SourceResult) -> dict[str, Any]:
    if not result.ok:
        return {"rows": [], "note": result.reason()}
    journal = result.value.get("journal") or {}
    entries = sorted((e for e in journal.get("entries") or [] if isinstance(e, dict)), key=lambda e: str(e.get("created_at") or ""), reverse=True)
    rows = [{"id": str(e.get("id") or ""), "created_at": e.get("created_at"), "kind": str(e.get("kind") or ""), "status": str(e.get("status") or ""),
             "direction": str(e.get("direction") or ""), "entry": e.get("entry"), "stop": e.get("stop"), "target": e.get("target"),
             "result_r": e.get("result_r"), "review": bool(e.get("review")), "thesis": str(e.get("thesis") or "")[:160]}
            for e in entries[:6]]
    return {"rows": rows, "summary": result.value.get("summary") or {}}


def build_markt(state: DashboardState, timeframe: str | None = None, now: datetime | None = None, budget: float = 1.5,
                sources: BudgetedSources | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    timeframe = timeframe_of(timeframe)
    results = (sources or _SOURCES).run(_jobs(state, timeframe), budget=budget)
    try:
        market, plans = _market_tiles(results["series"], results["chart"], results["prep"], now)
    except Exception as exc:  # noqa: BLE001 - unexpected data shape: grey tiles with the reason, not a broken page
        market, plans = [_info(unavailable(key, label, _broken(exc), "Kachelbau Markt", href)) for key, label, href in MARKET_TILES], []
    try:
        journals = _journal_tiles(results["plan_journal"], results["trader_journal"], now)
    except Exception as exc:  # noqa: BLE001
        journals = [unavailable(key, label, _broken(exc), "Kachelbau Journale", href) for key, label, href in JOURNAL_TILES]
    sections: dict[str, Any] = {}
    for name, build in (("chart", lambda: _chart(results["chart" if timeframe == "30m" else f"chart_{timeframe}"], timeframe)),
                        ("prep", lambda: _prep(results["prep"])),
                        ("plan_journal", lambda: _plan_rows(results["plan_journal"])),
                        ("trader_journal", lambda: _trader_rows(results["trader_journal"]))):
        try:
            sections[name] = build()
        except Exception as exc:  # noqa: BLE001
            sections[name] = {"ok": False, "note": _broken(exc), "svg": None, "active": [], "closed": [], "rows": []}
    stats = (sections["plan_journal"].get("summary") or {})
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "mode": "OBSERVE",
        "safety": "Nur Beobachtung und Papier, keine Order, keine Anlageberatung",
        "timeframe": timeframe,
        "timeframes": list(TIMEFRAMES),
        "market": [t.to_dict() for t in market],
        "plans": plans,
        "journals": [t.to_dict() for t in journals],
        "plan_journal_line": (f"Plan-Journal: {stats.get('open', 0)} warten, {stats.get('filled', 0)} im Trade, {stats.get('closed', 0)} geschlossen, "
                              f"netto {_r(stats.get('sum_net_r'))}") if stats else "",
        **sections,
        "sources": {name: {"ok": r.ok, "seconds": r.seconds, "error": r.error, "stale_seconds": r.stale_seconds} for name, r in results.items()},
    }
