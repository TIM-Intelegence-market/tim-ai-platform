from __future__ import annotations

import hmac
import json
import re
import secrets
import threading
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from src.analytics.research import ResearchAnalyticsEngine
from src.insights import ResearchInsightsEngine
from src.research.case_export import build_case_export, to_html as case_export_html, to_json as case_export_json
from src.research.retrospective import case_retrospective
from src.research.router import ResearchRouter
from src.llm.ollama_client import OllamaClient
from src.llm.prompts import observation_prompt
from config.settings import settings

from src.dashboard.api import _research_case_detail, _research_cases_collection
from src.dashboard.chart_model import build_chart_model
from src.dashboard.constants import HISTORY_LIMIT, MAX_RESPONSE_BYTES
from src.dashboard.layout import _content_security_policy, _content_security_policy_for, _error_page
from src.dashboard.security import _is_loopback_request_host, _require_loopback_host
from src.dashboard.pages.chart import CHART_SCRIPTS, render_chart_page
from src.dashboard.pages.pilot import PILOT_CSP, render_pilot
from src.dashboard.state import DashboardState, plan_journal_paths
from src.dashboard.views import render

class DashboardServer:
    def __init__(self, state: DashboardState, host: str = "127.0.0.1", port: int = 8765, research_router: ResearchRouter | None = None) -> None:
        host = _require_loopback_host(host)
        self.state, self.host, self.port = state, host, port
        self.research_router = research_router or ResearchRouter()
        self.research_lock = threading.Lock()
        # Form token for the trader journal: a page from another site cannot read it, so it cannot post.
        self.form_token = secrets.token_urlsafe(32)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def respond(self, status: int, payload: bytes, content_type: str, csp: str | None = None,
                        referrer: str = "no-referrer", location: str | None = None) -> None:
                if len(payload) > MAX_RESPONSE_BYTES:
                    status = 413
                    payload = b'{"error":"response exceeds dashboard limit"}'
                    content_type = "application/json"
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Security-Policy", csp or _content_security_policy())
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", referrer)
                if location:
                    self.send_header("Location", location)
                self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
                self.send_header("Cross-Origin-Opener-Policy", "same-origin")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                if not _is_loopback_request_host(self.headers.get("Host")):
                    return self.respond(421, b'{"error":"loopback Host header required"}', "application/json")
                parsed = urlparse(self.path)
                path, query = parsed.path, parse_qs(parsed.query)
                if path == "/api/state":
                    return self.respond(200, json.dumps(outer.state.snapshot()).encode(), "application/json")
                if path == "/api/operations":
                    return self.respond(200, json.dumps(outer.state.snapshot()["operations"], sort_keys=True).encode(), "application/json")
                if path == "/api/health":
                    snapshot = outer.state.snapshot()
                    payload = {
                        "timestamp": snapshot["timestamp"],
                        "mode": snapshot["mode"],
                        "operational": snapshot["operational_health"],
                        "historical_scientific": {
                            "validator_status": snapshot["validator"].get("status", "UNKNOWN"),
                            "last_checked_at": snapshot["validator"].get("last_cycle_at"),
                            "quality_status": snapshot["research_quality"].get("validation_status", "UNKNOWN"),
                            "audit_status": snapshot["research_audit"].get("status", "UNKNOWN"),
                        },
                        "governance": {
                            "readiness_status": snapshot["readiness"].get("readiness_status", "UNKNOWN"),
                            "core_status": snapshot["core_manifest"].get("status", "UNKNOWN"),
                            "observe_only": snapshot["mode"] == "OBSERVE",
                        },
                    }
                    return self.respond(200, json.dumps(payload, sort_keys=True).encode(), "application/json")
                if path == "/api/analytics":
                    return self.respond(200, ResearchAnalyticsEngine.to_json(outer.state.analytics()).encode(), "application/json")
                if path == "/api/insights":
                    return self.respond(200, ResearchInsightsEngine.to_json(outer.state.insights()).encode(), "application/json")
                if path == "/api/readiness":
                    return self.respond(200, json.dumps(outer.state.readiness(),sort_keys=True).encode(), "application/json")
                if path.startswith("/exports/analytics."):
                    analytics = outer.state.analytics()
                    extension = path.rsplit(".", 1)[-1]
                    exports = {"json": (ResearchAnalyticsEngine.to_json, "application/json"), "csv": (ResearchAnalyticsEngine.to_csv, "text/csv; charset=utf-8"), "md": (ResearchAnalyticsEngine.to_markdown, "text/markdown; charset=utf-8")}
                    if extension not in exports:
                        return self.respond(404, b'{"error":"not found"}', "application/json")
                    formatter, content_type = exports[extension]
                    return self.respond(200, formatter(analytics).encode(), content_type)
                if path.startswith("/exports/insights."):
                    insights = outer.state.insights()
                    extension = path.rsplit(".", 1)[-1]
                    exports = {"json": (ResearchInsightsEngine.to_json, "application/json"), "csv": (ResearchInsightsEngine.to_csv, "text/csv; charset=utf-8"), "md": (ResearchInsightsEngine.to_markdown, "text/markdown; charset=utf-8")}
                    if extension not in exports:
                        return self.respond(404, b'{"error":"not found"}', "application/json")
                    formatter, content_type = exports[extension]
                    return self.respond(200, formatter(insights).encode(), content_type)
                if path == "/chart":
                    from src.dashboard.pages.chart import CHART_CSP

                    try:
                        page = render_chart_page(outer.state, query.get("tf", [None])[0], query.get("levels", [None])[0], query.get("symbol", [None])[0])
                    except Exception as exc:  # noqa: BLE001 - bounded degradation instead of a dropped connection
                        return self.respond(500, _error_page("Chart", exc).encode(), "text/html; charset=utf-8")
                    return self.respond(200, page.encode(), "text/html; charset=utf-8", csp=CHART_CSP)
                if path in CHART_SCRIPTS:
                    return self.respond(200, CHART_SCRIPTS[path], "text/javascript; charset=utf-8")
                if path == "/api/chart/live":
                    from src.dashboard.chart_live import build_live_chart

                    try:
                        with outer.state.lock:
                            footprint = dict(outer.state.footprint)
                            gamma = dict(outer.state.gamma)
                            liquidation = dict(outer.state.liquidation)
                        from src.dashboard.chart_live import load_plan_journals

                        model = build_live_chart(query.get("symbol", [None])[0], query.get("tf", [None])[0], outer.state.chart_series(), footprint=footprint,
                                                 plan_journals=load_plan_journals(plan_journal_paths(outer.state)), gamma=gamma,
                                                 liquidation=liquidation)
                    except Exception as exc:  # noqa: BLE001 - malformed data must not drop the connection
                        return self.respond(500, json.dumps({"error": type(exc).__name__}).encode(), "application/json")
                    return self.respond(200, json.dumps(model, default=str).encode(), "application/json")
                if path == "/api/chart":
                    try:
                        from src.dashboard.analysis_card import with_journal_check

                        series, now = outer.state.chart_series(), datetime.now(timezone.utc)
                        model = with_journal_check(build_chart_model(series, query.get("tf", ["30m"])[0], now=now, card=True),
                                                   series, outer.state.plan_journal_level_path, now)
                    except Exception as exc:  # noqa: BLE001 - malformed stored data must not drop the connection
                        return self.respond(500, json.dumps({"error": type(exc).__name__}).encode(), "application/json")
                    return self.respond(200, json.dumps(model, default=str).encode(), "application/json")
                if path == "/api/macro":
                    from src.dashboard.macro_bar import CACHE as MACRO_CACHE

                    macro = MACRO_CACHE.snapshot()
                    return self.respond(200, json.dumps(macro or {"status": "LOADING"}, default=str).encode(), "application/json")
                if path == "/api/prep":
                    from src.dashboard.session_map import build_session_map

                    from src.dashboard.gamma_data import prep_block

                    try:
                        prep = build_session_map(outer.state.chart_series())
                        with outer.state.lock:
                            gamma = outer.state.gamma.get(str(outer.state.market_status.get("symbol") or "BTCUSDT"))
                        prep["gamma"] = prep_block(gamma)
                    except Exception as exc:  # noqa: BLE001 - malformed stored data must not drop the connection
                        return self.respond(500, json.dumps({"error": type(exc).__name__}).encode(), "application/json")
                    return self.respond(200, json.dumps(prep, default=str).encode(), "application/json")
                if path == "/api/gamma":
                    from src.dashboard.gamma_data import with_age

                    symbol = query.get("symbol", ["BTCUSDT"])[0]
                    with outer.state.lock:
                        snapshot = outer.state.gamma.get(symbol)
                    current = with_age(snapshot)
                    if current is None:
                        return self.respond(404, json.dumps({"error": "no gamma snapshot", "symbol": symbol}).encode(), "application/json")
                    return self.respond(200, json.dumps(current, default=str).encode(), "application/json")
                if path == "/api/liquidation":
                    from src.dashboard.liquidation_data import with_age as liquidation_with_age

                    symbol = query.get("symbol", ["BTCUSDT"])[0]
                    with outer.state.lock:
                        heatmap = outer.state.liquidation.get(symbol)
                    current = liquidation_with_age(heatmap)
                    if current is None:
                        return self.respond(404, json.dumps({"error": "no liquidation estimate", "symbol": symbol}).encode(), "application/json")
                    return self.respond(200, json.dumps(current, default=str).encode(), "application/json")
                if path == "/trader-journal":
                    saved = query.get("saved", [""])[0]
                    return self.trader_journal_page(200, saved=saved if re.fullmatch(r"TJ-\d{4,5}", saved or "") else None)
                if path == "/my-day":
                    saved = query.get("saved", [""])[0]
                    return self.my_day_page(200, saved=saved if re.fullmatch(r"DP-\d{4,5}", saved or "") else None)
                if path == "/api/my-day":
                    from src.dashboard import daily_prep

                    log = daily_prep.load(outer.state.daily_prep_path)
                    return self.respond(200, json.dumps({**log, "entries": log["entries"][-200:], "today": daily_prep.today(log)}, default=str).encode(), "application/json")
                if path == "/api/trader-journal":
                    from src.dashboard import trader_journal

                    journal = trader_journal.load(outer.state.trader_journal_path)
                    return self.respond(200, json.dumps({**journal, "entries": journal["entries"][-500:], "summary": trader_journal.summary(journal)}, default=str).encode(), "application/json")
                if path == "/api/candles-derived":
                    timeframe = query.get("tf", ["4h"])[0]
                    with outer.state.lock:
                        rows = [dict(item) for item in outer.state.derived_candles.get(timeframe, [])]
                    if timeframe not in ("4h", "1d"):
                        return self.respond(400, json.dumps({"error": "tf must be 4h or 1d"}).encode(), "application/json")
                    return self.respond(200, json.dumps({"symbol": outer.state.market_status.get("symbol"), "timeframe": timeframe, "source": "derived from persisted 1h candles, complete buckets only", "count": len(rows), "candles": rows}, default=str).encode(), "application/json")
                if path == "/api/validations-long":
                    with outer.state.lock:
                        rows = [dict(item) for item in outer.state.orderflow_validations_long[-500:]]
                    return self.respond(200, json.dumps({"validation_version": "long-1.0.0", "horizons_minutes": [60, 240, 1440], "mode": "OBSERVE", "note": "Nachprüfung nach 1h, 4h und 24h aus 1-Minuten-Kerzen; nur Messwerte, keine Einstufung.", "count": len(rows), "validations": rows}, default=str).encode(), "application/json")
                if path == "/api/plan-journal":
                    from src.dashboard.plan_journal import load_view as load_plan_journal

                    rule = query.get("rule", [""])[0]
                    journal_path = {"struct": outer.state.plan_journal_struct_path, "level": outer.state.plan_journal_level_path}.get(rule, outer.state.plan_journal_path)
                    from src.dashboard.plan_cost_check import with_cost_check
                    return self.respond(200, json.dumps(with_cost_check(load_plan_journal(journal_path)), default=str).encode(), "application/json")
                if path == "/neu" or path.startswith("/neu/") or path == "/api/cockpit":
                    return self.cockpit(path, query)
                if path in ("/graphify", "/graphify/"):
                    from src.dashboard.pages.graphify import graph_page

                    status, page, csp = graph_page()
                    return self.respond(status, page.encode(), "text/html; charset=utf-8", csp=csp)
                if path == "/graphify/communities":
                    from src.dashboard.pages.graphify import graph_page

                    status, page, csp = graph_page(name="graph.html")
                    return self.respond(status, page.encode(), "text/html; charset=utf-8", csp=csp)
                if path in ("/graphify/report", "/graphify/luecken"):
                    from src.dashboard.pages.graphify import GAP_REPORT, report_text

                    status, text = report_text(name=GAP_REPORT) if path.endswith("luecken") else report_text()
                    return self.respond(status, text.encode(), "text/plain; charset=utf-8")
                if path == "/pilot":
                    return self.respond(200, render_pilot(outer.state).encode(), "text/html; charset=utf-8", csp=PILOT_CSP)
                if path == "/api/orderflow/history":
                    with outer.state.lock:
                        # Bounded like the visible observation window: the runtime keeps appending validations.
                        history = {"observations": [dict(item) for item in outer.state.orderflow_observations[-HISTORY_LIMIT:]], "validations": [dict(item) for item in outer.state.orderflow_validations[-HISTORY_LIMIT:]]}
                    return self.respond(200, json.dumps(history, default=str).encode(), "application/json")
                if path.startswith("/exports/case/"):
                    cid, _, extension = unquote(path.removeprefix("/exports/case/")).rpartition(".")
                    with outer.state.lock:
                        item = next((dict(entry) for entry in outer.state.research_cases if str(entry.get("case_id")) == cid), None)
                        orderflow_observations = [dict(entry) for entry in outer.state.orderflow_observations]
                        orderflow_validations = [dict(entry) for entry in outer.state.orderflow_validations]
                    if item is None or extension not in {"json", "html"}:
                        return self.respond(404, b'{"error":"case not found"}', "application/json")
                    try:
                        retrospective = case_retrospective(item, orderflow_observations, orderflow_validations) or None
                    except Exception:  # malformed stored data must not break the page
                        retrospective = None
                    export = build_case_export(item, exported_at=datetime.now(timezone.utc), retrospective=retrospective)
                    if extension == "json":
                        return self.respond(200, case_export_json(export).encode(), "application/json")
                    proof_page = case_export_html(export)
                    return self.respond(200, proof_page.encode(), "text/html; charset=utf-8", csp=_content_security_policy_for(proof_page))
                pages = {
                    "/": "Overview", "/security": "Security", "/runtime": "Runtime",
                    "/data-quality": "Data Quality", "/gaps": "Incidents & Gaps",
                    "/qualification": "Qualification",
                    "/independent-cases": "Independent Cases",
                    "/v2-readiness": "V2 Readiness", "/mcp": "Graphify & MCP",
                    "/prep": "Prep",
                    "/setup-path": "Setup Path",
                    "/journal": "Plan Journal", "/journal/struct": "Plan Journal Struct", "/journal/level": "Plan Journal Level",
                    "/audit-evidence": "Audit & Evidence",
                    "/observations": "Observations", "/cases": "Research Cases", "/orderflow": "Orderflow",
                    "/signals": "Signal Research", "/analytics": "Analytics", "/insights": "Insights",
                    "/health": "Health Center", "/exceptions": "Data Quality Exceptions",
                    "/timeline": "Timeline", "/research": "Research",
                }
                if path in pages:
                    try:
                        page = render(outer.state, pages[path], query.get("id", [None])[0])
                    except Exception as exc:  # noqa: BLE001 - bounded degradation instead of a dropped connection
                        return self.respond(500, _error_page(pages[path], exc).encode(), "text/html; charset=utf-8")
                    return self.respond(200, page.encode(), "text/html; charset=utf-8")
                if path.startswith("/api/observations/"):
                    oid = unquote(path.removeprefix("/api/observations/"))
                    item = next((entry for entry in outer.state.snapshot()["observations"] if str(entry.get("observation_id")) == oid), None)
                    return self.respond(200 if item else 404, json.dumps(item or {"error": "observation not found"}).encode(), "application/json")
                if path.startswith("/api/cases/"):
                    cid = unquote(path.removeprefix("/api/cases/"))
                    with outer.state.lock:
                        full_cases = [dict(entry) for entry in outer.state.research_cases]
                    item = next((entry for entry in full_cases if str(entry.get("case_id")) == cid), None)
                    return self.respond(200 if item else 404, json.dumps(item or {"error": "case not found"}).encode(), "application/json")
                if path == "/api/research-cases" or path == "/api/research-cases/stats":
                    with outer.state.lock:
                        full = {"research_cases": [dict(entry) for entry in outer.state.research_cases]}
                    return self.respond(200, json.dumps(_research_cases_collection(full, query, stats_only=(path == "/api/research-cases/stats")), default=str).encode(), "application/json")
                if path.startswith("/api/research-cases/"):
                    cid = unquote(path.removeprefix("/api/research-cases/"))
                    with outer.state.lock:
                        full_cases = [dict(entry) for entry in outer.state.research_cases]
                    item = next((entry for entry in full_cases if str(entry.get("case_id")) == cid), None)
                    payload = _research_case_detail(item) if item else {"error": "case not found"}
                    return self.respond(200 if item else 404, json.dumps(payload, default=str).encode(), "application/json")
                if path == "/api/rag":
                    q = (query.get("q", [""])[0] or "").strip().lower()
                    if not q:
                        return self.respond(400, b'{"error":"q query param required"}', "application/json")
                    snap = outer.state.snapshot()
                    # RAG über Research Cases + Market Memory (active_observations)
                    scored = []
                    for obs in snap["active_observations"][-100:]:
                        text = f"{obs.get('kind','')} {obs.get('summary','')} {obs.get('rule_id','')}".lower()
                        score = sum(1 for tok in q.split() if tok in text) / max(1, len(q.split()))
                        if score > 0:
                            scored.append((score, obs))
                    scored.sort(key=lambda x: x[0], reverse=True)
                    top_obs = [o for _, o in scored[:5]]
                    # auch Cases durchsuchen
                    case_hits = []
                    for case in snap["research_cases"][-50:]:
                        text = f"{case.get('case_id','')} {' '.join(case.get('observation_ids',[]))} {' '.join(case.get('missing_evidence',[]))}".lower()
                        if any(tok in text for tok in q.split()):
                            case_hits.append(case)
                            if len(case_hits) >= 5:
                                break
                    payload = {"query": q, "observations": top_obs, "cases": case_hits[:5], "provenance": "PUBLIC_MARKET_DATA_DETERMINISTIC", "graphify": "enabled" if Path("graphify-out/graph.json").exists() else "disabled", "omniroute": "http://localhost:20128/v1"}
                    return self.respond(200, json.dumps(payload).encode(), "application/json")
                if path == "/api/llm/explain":
                    q = (query.get("q", [""])[0] or "").strip()
                    obs_id = (query.get("observation_id", [""])[0] or "").strip()
                    snap = outer.state.snapshot()
                    # finde Observation
                    obs = None
                    if obs_id:
                        obs = next((o for o in snap["active_observations"] if str(o.get("observation_id")) == obs_id), None)
                    if not obs and snap["active_observations"]:
                        obs = snap["active_observations"][-1]
                    if not obs:
                        return self.respond(404, b'{"error":"no observation for LLM"}', "application/json")
                    # LLM via Ollama/OmniRoute wenn enabled, sonst Fallback
                    import asyncio as _asyncio
                    try:
                        if not settings.enable_ollama:
                            raise RuntimeError("Ollama disabled by policy")
                        client = OllamaClient(settings.ollama_url, settings.ollama_model)
                        # auch OmniRoute als fallback testen (20128)
                        prompt = observation_prompt(type("O",(),obs)()) if False else f"Erkläre TIM Observation {obs.get('kind')} {obs.get('summary')} OBSERVE-only, keine Handlungsempfehlung. Query: {q}"
                        # sync call via asyncio
                        result = _asyncio.run(client.generate_json(prompt)) if hasattr(client, 'generate_json') else {"explanation": "LLM disabled"}
                        payload = {"observation": obs, "llm": result, "model": settings.ollama_model, "via": settings.ollama_url, "omniroute": "http://localhost:20128/v1"}
                    except Exception as exc:
                        payload = {"observation": obs, "llm": {"explanation": f"LLM unavailable: {type(exc).__name__}: {exc}", "fallback": f"Observation {obs.get('kind')} {obs.get('summary')} — Provenance {obs.get('provenance')}"}, "model": settings.ollama_model, "via": "fallback", "omniroute": "http://localhost:20128/v1"}
                    return self.respond(200, json.dumps(payload).encode(), "application/json")
                if path.startswith("/reports/"):
                    name = Path(unquote(path.removeprefix("/reports/"))).name
                    root = outer.research_router.config.report_root.resolve()
                    candidate = (root / name).resolve()
                    if candidate.parent != root or not candidate.is_file() or candidate.suffix not in {".md", ".json"}:
                        return self.respond(404, b'{"error":"report not found"}', "application/json")
                    return self.respond(200, candidate.read_bytes(), "text/markdown; charset=utf-8" if candidate.suffix == ".md" else "application/json")
                return self.respond(404, b'{"error":"not found"}', "application/json")

            def cockpit(self, path: str, query: dict[str, list[str]]) -> None:
                """New Control Center under /neu (display only, runs next to the old pages)."""
                from src.dashboard import cockpit

                try:
                    if path == "/api/cockpit":
                        area = query.get("area", ["lage"])[0]
                        builders = {"lage": lambda: cockpit.build_lage(outer.state), "mac": lambda: cockpit.build_mac(outer.state),
                                    "markt": lambda: cockpit.build_markt(outer.state, query.get("tf", [None])[0]),
                                    "forschung": lambda: cockpit.build_forschung(outer.state),
                                    "betrieb": lambda: cockpit.build_betrieb(outer.state),
                                    "system": lambda: cockpit.build_system(outer.state)}
                        if area not in builders:
                            return self.respond(404, b'{"error":"not found"}', "application/json")
                        model = builders[area]()
                        if isinstance(model.get("chart"), dict):
                            model["chart"].pop("svg", None)  # the JSON carries data, the SVG stays on the page
                        return self.respond(200, json.dumps(model, default=str).encode(), "application/json")
                    key = path.removeprefix("/neu").strip("/") or "lage"
                    if key not in cockpit.AREA_BY_KEY:
                        return self.respond(404, b'{"error":"not found"}', "application/json")
                    fragment = query.get("fragment", [""])[0] == "1"
                    if key in cockpit.BUILT:
                        build, body, render = cockpit.BUILT[key]
                        model = build(outer.state, query.get("tf", [None])[0]) if key == "markt" else build(outer.state)
                        if fragment:
                            return self.respond(200, json.dumps({"html": body(model)}).encode(), "application/json")
                        return self.respond(200, render(model).encode(), "text/html; charset=utf-8", csp=cockpit.COCKPIT_CSP)
                    return self.respond(200, cockpit.render_area(key).encode(), "text/html; charset=utf-8", csp=cockpit.COCKPIT_CSP)
                except Exception as exc:  # noqa: BLE001 - bounded degradation instead of a dropped connection
                    return self.respond(500, _error_page("Cockpit", exc).encode(), "text/html; charset=utf-8")

            def trader_journal_page(self, status: int, form: dict[str, str] | None = None, error: str | None = None, saved: str | None = None) -> None:
                from src.dashboard import trader_journal
                from src.dashboard.pages.trader_journal import journal_csp, render_trader_journal
                from src.dashboard.session_map import build_session_map, summary_line

                try:
                    context_line = summary_line(build_session_map(outer.state.chart_series()))
                except Exception:  # noqa: BLE001 - the journal works without TIM's context line
                    context_line = "kein Kontext verfügbar"
                try:
                    page = render_trader_journal(outer.state.snapshot(), trader_journal.load(outer.state.trader_journal_path), outer.form_token,
                                                 context_line, form=form, error=error, saved=saved)
                except Exception as exc:  # noqa: BLE001 - bounded degradation instead of a dropped connection
                    return self.respond(500, _error_page("Trader-Journal", exc).encode(), "text/html; charset=utf-8")
                # same-origin keeps the Origin header on the form post (no-referrer would send "null").
                return self.respond(status, page.encode(), "text/html; charset=utf-8", csp=journal_csp(page), referrer="same-origin")

            def checked_form(self, reload_path: str, max_fields: int = 40) -> dict[str, str] | None:
                """Same-origin, form-encoded, size-limited body with the page's token; None after an error response."""
                origin = self.headers.get("Origin")
                if origin is not None and origin != f"http://{self.headers.get('Host')}":
                    self.respond(403, b'{"error":"cross-origin form post refused"}', "application/json")
                    return None
                if self.headers.get_content_type() != "application/x-www-form-urlencoded":
                    self.respond(415, b'{"error":"form encoding required"}', "application/json")
                    return None
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    size = -1
                if size < 1 or size > 8192:
                    self.respond(413, b'{"error":"form body must be between 1 and 8192 bytes"}', "application/json")
                    return None
                try:
                    fields = parse_qs(self.rfile.read(size).decode("utf-8"), keep_blank_values=True, strict_parsing=False, max_num_fields=max_fields)
                except (UnicodeDecodeError, ValueError):
                    self.respond(400, b'{"error":"malformed form body"}', "application/json")
                    return None
                form = {key: values[0] for key, values in fields.items() if values}
                if not hmac.compare_digest(str(form.get("token", "")).encode(), outer.form_token.encode()):
                    self.respond(403, json.dumps({"error": f"form token invalid, reload {reload_path}"}).encode(), "application/json")
                    return None
                form.pop("token", None)
                return form

            def my_day_page(self, status: int, form: dict[str, str] | None = None, error: str | None = None, saved: str | None = None) -> None:
                from src.dashboard import daily_prep
                from src.dashboard.pages.my_day import my_day_csp, render_my_day
                from src.dashboard.session_map import build_session_map

                try:
                    model = build_session_map(outer.state.chart_series())
                except Exception:  # noqa: BLE001 - the prep form works without TIM's levels
                    model = None
                try:
                    log = daily_prep.load(outer.state.daily_prep_path)
                    page = render_my_day(outer.state.snapshot(), log, outer.form_token, daily_prep.suggested_levels(model),
                                         (model or {}).get("last"), daily_prep.today(log), form=form, error=error, saved=saved)
                except Exception as exc:  # noqa: BLE001 - bounded degradation instead of a dropped connection
                    return self.respond(500, _error_page("Mein Tag", exc).encode(), "text/html; charset=utf-8")
                return self.respond(status, page.encode(), "text/html; charset=utf-8", csp=my_day_csp(page), referrer="same-origin")

            def my_day_post(self) -> None:
                from src.dashboard import daily_prep
                from src.dashboard.session_map import build_session_map

                form = self.checked_form("/my-day", max_fields=60)
                if form is None:
                    return None
                try:
                    model = build_session_map(outer.state.chart_series())
                except Exception:  # noqa: BLE001 - a prep is kept even without TIM's context
                    model = None
                try:
                    entry = daily_prep.add_entry(outer.state.daily_prep_path, form, model)
                except daily_prep.PrepError as exc:
                    return self.my_day_page(400, form=form, error=str(exc))
                return self.respond(303, b"", "text/plain; charset=utf-8", location=f"/my-day?saved={entry['id']}")

            def trader_journal_post(self, path: str) -> None:
                from src.dashboard import trader_journal
                from src.dashboard.session_map import build_session_map

                form = self.checked_form("/trader-journal")
                if form is None:
                    return None
                journal_path = outer.state.trader_journal_path
                try:
                    if path == "/trader-journal/entry":
                        try:
                            model = build_session_map(outer.state.chart_series())
                        except Exception:  # noqa: BLE001 - an entry is kept even without TIM's context
                            model = None
                        entry = trader_journal.add_entry(journal_path, form, model)
                    elif path == "/trader-journal/review":
                        entry = trader_journal.add_review(journal_path, form)
                    else:
                        entry = trader_journal.cancel_entry(journal_path, form)
                except trader_journal.JournalError as exc:
                    return self.trader_journal_page(400, form=form if path == "/trader-journal/entry" else None, error=str(exc))
                return self.respond(303, b"", "text/plain; charset=utf-8", location=f"/trader-journal?saved={entry['id']}")

            def do_POST(self):
                if not _is_loopback_request_host(self.headers.get("Host")):
                    return self.respond(421, b'{"error":"loopback Host header required"}', "application/json")
                path = urlparse(self.path).path
                if path in {"/trader-journal/entry", "/trader-journal/review", "/trader-journal/cancel"}:
                    return self.trader_journal_post(path)
                if path == "/my-day/save":
                    return self.my_day_post()
                if path not in {"/api/research/quick", "/api/research/deep"}:
                    return self.respond(404, b'{"error":"not found"}', "application/json")
                try:
                    if self.headers.get_content_type() != "application/json":
                        raise ValueError("Content-Type must be application/json")
                    size = int(self.headers.get("Content-Length", "0"))
                    if size < 2 or size > 8192:
                        raise ValueError("request body must be between 2 and 8192 bytes")
                    value = json.loads(self.rfile.read(size))
                    query = str(value.get("query", "")).strip()
                    limit = 500 if path.endswith("/quick") else 2000
                    if not query or len(query) > limit:
                        raise ValueError(f"query must contain 1-{limit} characters")
                    report_type = str(value.get("type", "research_report"))
                    if report_type not in {"research_report", "deep"}:
                        raise ValueError("unsupported report type")
                    snapshot = outer.state.snapshot()
                    evidence = [{"source": item.get("source", "TIM_DASHBOARD"), "provenance": item.get("provenance", snapshot["provenance"]), "observed_at": item.get("observed_at"), "summary": item.get("summary", "")} for item in snapshot["observations"][-20:]]
                    requested = "quick" if path.endswith("/quick") else ("deep" if report_type == "deep" else "report")
                    with outer.research_lock:
                        routed = outer.research_router.route(query, evidence, requested_type=requested, context={"symbol": snapshot["market_status"].get("symbol", "BTCUSDT"), "timeframe": "mixed"})
                    result = asdict(routed["result"]) if is_dataclass(routed["result"]) else dict(routed["result"])
                    if routed["module"] == "B":
                        result["download_url"] = "/reports/" + Path(result["file"]).name
                    return self.respond(200, json.dumps({"selected_type": routed["selected_type"], "module": routed["module"], "result": result}).encode(), "application/json")
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    return self.respond(400, json.dumps({"error": str(exc)}).encode(), "application/json")
                except Exception:
                    return self.respond(500, b'{"error":"research processing failed"}', "application/json")

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="tim-dashboard", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
