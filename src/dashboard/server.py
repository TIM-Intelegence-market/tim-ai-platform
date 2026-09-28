from __future__ import annotations

import json
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

from src.dashboard.api import _research_cases_collection
from src.dashboard.constants import MAX_RESPONSE_BYTES
from src.dashboard.layout import _content_security_policy, _content_security_policy_for, _error_page
from src.dashboard.security import _is_loopback_request_host, _require_loopback_host
from src.dashboard.pages.pilot import render_pilot
from src.dashboard.state import DashboardState
from src.dashboard.views import render

class DashboardServer:
    def __init__(self, state: DashboardState, host: str = "127.0.0.1", port: int = 8765, research_router: ResearchRouter | None = None) -> None:
        host = _require_loopback_host(host)
        self.state, self.host, self.port = state, host, port
        self.research_router = research_router or ResearchRouter()
        self.research_lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def respond(self, status: int, payload: bytes, content_type: str) -> None:
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
                html_page = content_type.startswith("text/html")
                self.send_header("Content-Security-Policy", _content_security_policy_for(payload.decode("utf-8", "replace")) if html_page else _content_security_policy())
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
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
                if path == "/pilot":
                    return self.respond(200, render_pilot(outer.state).encode(), "text/html; charset=utf-8")
                if path == "/api/orderflow/history":
                    with outer.state.lock:
                        history = {"observations": [dict(item) for item in outer.state.orderflow_observations], "validations": [dict(item) for item in outer.state.orderflow_validations]}
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
                    return self.respond(200, case_export_html(export).encode(), "text/html; charset=utf-8")
                pages = {
                    "/": "Overview", "/security": "Security", "/runtime": "Runtime",
                    "/data-quality": "Data Quality", "/gaps": "Incidents & Gaps",
                    "/qualification": "Qualification",
                    "/independent-cases": "Independent Cases",
                    "/v2-readiness": "V2 Readiness", "/mcp": "Graphify & MCP",
                    "/setup-path": "Setup Path",
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
                    return self.respond(200, json.dumps(_research_cases_collection(full, query, stats_only=(path == "/api/research-cases/stats"))).encode(), "application/json")
                if path.startswith("/api/research-cases/"):
                    cid = unquote(path.removeprefix("/api/research-cases/"))
                    with outer.state.lock:
                        full_cases = [dict(entry) for entry in outer.state.research_cases]
                    item = next((entry for entry in full_cases if str(entry.get("case_id")) == cid), None)
                    return self.respond(200 if item else 404, json.dumps(item or {"error": "case not found"}).encode(), "application/json")
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

            def do_POST(self):
                if not _is_loopback_request_host(self.headers.get("Host")):
                    return self.respond(421, b'{"error":"loopback Host header required"}', "application/json")
                path = urlparse(self.path).path
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
