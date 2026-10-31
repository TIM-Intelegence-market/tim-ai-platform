"""Read-only public view of the TIM dashboard, in English (for a Cloudflare Tunnel).

Runs next to the Control Center on its own loopback port and serves a fixed
allowlist: the interactive chart, the paper plan journals and the two data
APIs they need. Nothing else: no Mac, system, worker or approval pages, no
``/api/state``, no LLM call, no form and no POST. The pages are English
renders from ``src/dashboard/public_en.py``; the German Control Center on 8765
is unchanged. Every page carries the note "research, not financial advice".

Off by default. ``TIM_PUBLIC_DASHBOARD=true`` or the flag file
``~/Library/Application Support/TIM/public-dashboard.enabled`` starts it; the tunnel itself is
started by the owner outside TIM (see ``ops/macos/PUBLIC_DASHBOARD.md``).
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse

from src.dashboard.constants import MAX_RESPONSE_BYTES
from src.dashboard.layout import _content_security_policy
from src.dashboard.security import _require_loopback_host

DEFAULT_PORT = 8780
PAGES = ("/chart", "/journal", "/journal/trade")
# Query keys a public page or API may pass on; everything else is dropped before rendering.
QUERY_KEYS = {"/chart": ("symbol", "tf"), "/journal": ("rule",), "/journal/trade": ("rule", "id"), "/api/chart/live": ("symbol", "tf", "market"), "/api/plan-journal": ("rule",)}
PAGE_TTL = 10.0        # seconds a rendered public page is reused
API_TTL = 5.0          # seconds a data answer is reused
RATE_PER_MINUTE = 120  # requests per client and minute
MAX_BUSY = 8           # renders running at the same time
MAX_URL = 512


def clean_query(path: str, query: dict[str, list[str]]) -> dict[str, str]:
    """Only the allowed keys, one short value each."""
    return {key: query[key][0][:32 if key == "id" else 16] for key in QUERY_KEYS.get(path, ()) if query.get(key) and query[key][0]}


class RateLimiter:
    """Fixed one-minute window per client key."""

    def __init__(self, per_minute: int = RATE_PER_MINUTE, clock: Callable[[], float] = time.monotonic) -> None:
        self.per_minute, self.clock = per_minute, clock
        self.lock = threading.Lock()
        self.windows: dict[str, tuple[float, int]] = {}

    def allow(self, key: str) -> bool:
        now = self.clock()
        with self.lock:
            start, count = self.windows.get(key, (now, 0))
            if now - start >= 60:
                start, count = now, 0
            if count >= self.per_minute:
                self.windows[key] = (start, count)
                return False
            self.windows[key] = (start, count + 1)
            if len(self.windows) > 10_000:  # forget old clients so the table stays small
                self.windows = {k: v for k, v in self.windows.items() if now - v[0] < 60}
            return True


class TTLCache:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.lock = threading.Lock()
        self.items: dict[str, tuple[float, Any]] = {}

    def get(self, key: str, ttl: float, build: Callable[[], Any]) -> Any:
        with self.lock:
            hit = self.items.get(key)
        if hit and self.clock() - hit[0] < ttl:
            return hit[1]
        value = build()
        with self.lock:
            if len(self.items) > 256:
                self.items.clear()
            self.items[key] = (self.clock(), value)
        return value


class PublicDashboardServer:
    """Allowlisted, GET-only view; binds loopback only, the tunnel reaches it from the same machine."""

    def __init__(self, state: Any, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 limiter: RateLimiter | None = None, cache: TTLCache | None = None) -> None:
        host = _require_loopback_host(host)
        self.state, self.host, self.port = state, host, port
        self.limiter, self.cache = limiter or RateLimiter(), cache or TTLCache()
        self.busy = threading.BoundedSemaphore(MAX_BUSY)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "TIM-public"
            sys_version = ""

            def respond(self, status: int, payload: bytes, content_type: str, csp: str | None = None,
                        location: str | None = None, head: bool = False) -> None:
                if len(payload) > MAX_RESPONSE_BYTES:
                    status, payload, content_type = 413, b'{"error":"too large"}', "application/json"
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "public, max-age=5" if status == 200 else "no-store")
                self.send_header("Content-Security-Policy", csp or _content_security_policy())
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Robots-Tag", "noindex, nofollow")
                self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
                self.send_header("Cross-Origin-Opener-Policy", "same-origin")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                if location:
                    self.send_header("Location", location)
                self.end_headers()
                if not head:
                    self.wfile.write(payload)

            def client(self) -> str:
                # The tunnel names the visitor: Cloudflare in CF-Connecting-IP, ngrok as the last
                # X-Forwarded-For entry (the one the tunnel appended). Without a tunnel the peer is local.
                forwarded = [part.strip() for part in (self.headers.get("X-Forwarded-For") or "").split(",") if part.strip()]
                return (self.headers.get("CF-Connecting-IP") or (forwarded[-1] if forwarded else "") or self.client_address[0] or "?")[:64]

            def do_HEAD(self):
                self.do_GET(head=True)

            def do_GET(self, head: bool = False):
                if len(self.path) > MAX_URL:
                    return self.respond(414, b'{"error":"url too long"}', "application/json", head=head)
                if not outer.limiter.allow(self.client()):
                    return self.respond(429, b'{"error":"too many requests"}', "application/json", head=head)
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"
                if path == "/":
                    return self.respond(302, b"", "text/plain", location="/chart", head=head)
                if path == "/robots.txt":
                    return self.respond(200, b"User-agent: *\nDisallow: /\n", "text/plain; charset=utf-8", head=head)
                from src.dashboard.pages.chart import CHART_CSP, CHART_SCRIPTS

                if path in CHART_SCRIPTS:
                    return self.respond(200, CHART_SCRIPTS[path], "text/javascript; charset=utf-8", head=head)
                if path not in QUERY_KEYS:
                    return self.respond(404, b'{"error":"not found"}', "application/json", head=head)
                query = clean_query(path, parse_qs(parsed.query))
                if not outer.busy.acquire(blocking=False):
                    return self.respond(503, b'{"error":"busy"}', "application/json", head=head)
                try:
                    key = path + "?" + urlencode(sorted(query.items()))
                    if path in PAGES:
                        page = outer.cache.get(key, PAGE_TTL, lambda: outer.render_page(path, query))
                        if page is None:
                            return self.respond(404, b'{"error":"not found"}', "application/json", head=head)
                        from src.dashboard.public_en import journal_csp

                        return self.respond(200, page.encode(), "text/html; charset=utf-8",
                                            csp=CHART_CSP if path == "/chart" else journal_csp(), head=head)
                    payload = outer.cache.get(key, API_TTL, lambda: outer.render_api(path, query))
                    return self.respond(200, payload, "application/json", head=head)
                except Exception as exc:  # noqa: BLE001 - a visitor gets a short error, never a trace
                    return self.respond(500, json.dumps({"error": type(exc).__name__}).encode(), "application/json", head=head)
                finally:
                    outer.busy.release()

            def deny(self):
                self.respond(405, b'{"error":"read-only"}', "application/json")

            do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = deny

            def log_message(self, *_):
                pass

        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="tim-public-dashboard", daemon=True)

    def journal_paths(self) -> dict[str, Any]:
        """Public journal key -> journal file (the three horizons first, then the earlier 30m versions)."""
        from src.dashboard.state import plan_journal_paths

        return plan_journal_paths(self.state)

    def journals(self) -> dict[str, Any]:
        from src.dashboard.plan_journal import load_view

        # A horizon journal that has not started yet (no file) still gets its tab.
        return {key: load_view(path) for key, path in self.journal_paths().items()}

    def summary_html(self) -> str:
        """English text of what TIM's analysis says now (BTC); a failure only hides it."""
        from src.dashboard.analysis_summary import build_summary, render_en
        from src.dashboard.chart_live import load_plan_journals

        try:
            return render_en(build_summary(self.state.chart_series(), load_plan_journals(self.journal_paths())))
        except Exception:  # noqa: BLE001 - the public chart must still render
            return ""

    def render_page(self, path: str, query: dict[str, str]) -> str | None:
        from src.dashboard import public_en

        if path == "/chart":
            return public_en.chart_page(query.get("symbol"), query.get("tf"), self.summary_html())
        if path == "/journal/trade":
            return public_en.trade_page(self.journals(), query.get("rule", ""), query.get("id", ""))
        return public_en.journal_page(self.journals(), query.get("rule", public_en.DEFAULT_JOURNAL))

    def render_api(self, path: str, query: dict[str, str]) -> bytes:
        if path == "/api/chart/live":
            from src.dashboard.chart_live import build_live_chart

            with self.state.lock:
                footprint = dict(self.state.footprint)
                gamma = dict(self.state.gamma)
                liquidation = dict(self.state.liquidation)
                perp = dict(getattr(self.state, "perp_flow", None) or {})
                open_interest = dict(getattr(self.state, "open_interest", None) or {})
            from src.dashboard.chart_live import load_plan_journals

            model = build_live_chart(query.get("symbol"), query.get("tf"), self.state.chart_series(), footprint=footprint,
                                     plan_journals=load_plan_journals(self.journal_paths()), gamma=gamma,
                                     liquidation=liquidation, perp=perp, open_interest=open_interest,
                                     market=query.get("market"))
            from src.dashboard.pages.chart import APP_VERSION
            from src.dashboard.public_en import english_chart_model

            return json.dumps({**english_chart_model(model), "app_version": APP_VERSION}, default=str).encode()
        from src.dashboard.plan_cost_check import with_cost_check
        from src.dashboard.plan_journal import load_view

        journal_path = self.journal_paths().get(query.get("rule", ""), self.state.plan_journal_path)
        return json.dumps(with_cost_check(load_view(journal_path)), default=str).encode()

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
