"""Read-only public view of the TIM dashboard, in English (for a Cloudflare Tunnel).

Runs next to the Control Center on its own loopback port and serves a fixed
allowlist: the interactive chart, the paper plan journals and the two data
APIs they need, plus the live test account (``/live``, from a status file
the local live trader writes). Nothing else: no Mac, system, worker or approval pages, no
``/api/state``, no LLM call, no form and no POST. The pages are English
renders from ``src/dashboard/public_en.py``; the German Control Center on 8765
is unchanged. Every page carries the note "research, not financial advice".

Off by default. ``TIM_PUBLIC_DASHBOARD=true`` or the flag file
``~/Library/Application Support/TIM/public-dashboard.enabled`` starts it; the tunnel itself is
started by the owner outside TIM (see ``ops/macos/PUBLIC_DASHBOARD.md``).
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse

from src.dashboard.constants import MAX_RESPONSE_BYTES
from src.dashboard import public_auth
from src.dashboard.layout import _content_security_policy
from src.dashboard.security import _require_loopback_host

DEFAULT_PORT = 8780
PLAN_PATHS = frozenset({"/chart", "/api/chart/live"})  # open, but TIM's plans on them need the login
PAGES = ("/chart", "/guide", "/journal", "/journal/trade", "/live", "/reading")
# Query keys a public page or API may pass on; everything else is dropped before rendering.
QUERY_KEYS = {"/chart": ("symbol", "tf"), "/guide": ("lang",), "/journal": ("rule",), "/journal/trade": ("rule", "id"), "/live": (), "/reading": ("tf", "lang"), "/api/chart/live": ("symbol", "tf", "market"), "/api/plan-journal": ("rule",)}
PAGE_TTL = 10.0        # seconds a rendered public page is reused
API_TTL = 5.0          # seconds a data answer is reused
RATE_PER_MINUTE = 120  # requests per client and minute
MAX_BUSY = 8           # renders running at the same time
MAX_URL = 512
# Written every few minutes by the local live trader (outside the repo, read-only key, no secrets inside).
LIVE_STATUS_FILE = Path(os.environ.get("TIM_LIVE_STATUS_FILE", Path.home() / "Library/Application Support/TIM/live_status.json"))
MAX_LIVE_STATUS_BYTES = 16_384


def path_is_private(raw_path: str) -> bool:
    return (urlparse(raw_path).path.rstrip("/") or "/") in public_auth.PROTECTED


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
        self.live_status_file = LIVE_STATUS_FILE
        self.limiter, self.cache = limiter or RateLimiter(), cache or TTLCache()
        self.login_failures = public_auth.FailureLimiter()
        self.known_logins = public_auth.KnownLogins()
        self.check_slot = threading.Lock()  # one slow password check at a time
        self.busy = threading.BoundedSemaphore(MAX_BUSY)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "TIM-public"
            sys_version = ""

            def respond(self, status: int, payload: bytes, content_type: str, csp: str | None = None,
                        location: str | None = None, head: bool = False, challenge: bool = False,
                        private: bool = False) -> None:
                if len(payload) > MAX_RESPONSE_BYTES:
                    status, payload, content_type = 413, b'{"error":"too large"}', "application/json"
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store" if private or path_is_private(self.path) else "public, max-age=5" if status == 200 else "no-store")
                if challenge:
                    self.send_header("WWW-Authenticate", f'Basic realm="{public_auth.REALM}", charset="UTF-8"')
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
                from src.dashboard.pwa import assets as pwa_assets

                if path in pwa_assets():
                    body, kind = pwa_assets()[path]
                    return self.respond(200, body, kind, head=head)

                if path in CHART_SCRIPTS:
                    return self.respond(200, CHART_SCRIPTS[path], "text/javascript; charset=utf-8", head=head)
                if path not in QUERY_KEYS:
                    return self.respond(404, b'{"error":"not found"}', "application/json", head=head)
                if path in public_auth.PROTECTED:
                    denied = outer.login_gate(self.client(), self.headers.get("Authorization"))
                    if denied:
                        return self.respond(denied, b'{"error":"login required"}', "application/json", head=head,
                                            challenge=denied == 401)
                # The open chart shows TIM's plans only to a logged-in visitor (Uzi 21.11.2026); a wrong or missing
                # login simply gets the chart without them, and still counts as a failed attempt.
                member = path in PLAN_PATHS and bool(self.headers.get("Authorization")) and \
                    outer.login_gate(self.client(), self.headers.get("Authorization")) is None
                query = clean_query(path, parse_qs(parsed.query))
                if not outer.busy.acquire(blocking=False):
                    return self.respond(503, b'{"error":"busy"}', "application/json", head=head)
                try:
                    key = path + ("!member" if member else "") + "?" + urlencode(sorted(query.items()))
                    if path in PAGES:
                        page = outer.cache.get(key, PAGE_TTL, lambda: outer.render_page(path, query, member))
                        if page is None:
                            return self.respond(404, b'{"error":"not found"}', "application/json", head=head)
                        from src.dashboard.public_en import journal_csp, reading_csp

                        return self.respond(200, page.encode(), "text/html; charset=utf-8",
                                            csp=CHART_CSP if path == "/chart" else reading_csp() if path == "/reading" else journal_csp(), head=head, private=member)
                    payload = outer.cache.get(key, API_TTL, lambda: outer.render_api(path, query, member))
                    return self.respond(200, payload, "application/json", head=head, private=member)
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

    def login_gate(self, client: str, authorization: str | None) -> int | None:
        """None when the visitor may pass; 401 asks for the login, 429 pauses a guesser, 503 means no login is set up."""
        credentials = public_auth.load_credentials()
        if credentials is None:
            return 503  # fail closed: without a login file the private pages stay shut
        if not authorization:
            return 401  # no password sent: nothing to check, nothing to count
        if self.known_logins.has(authorization, credentials):
            return None  # checked a moment ago: an open chart asks every few seconds, the slow check runs once
        if not self.login_failures.reserve(client):
            return 429
        if not self.check_slot.acquire(timeout=public_auth.CHECK_WAIT):
            self.login_failures.release(client)  # the check never ran
            return 429
        try:
            passed = public_auth.check_login(authorization, credentials)
        finally:
            self.check_slot.release()
        if passed:
            self.login_failures.release(client)
            self.known_logins.add(authorization, credentials)
            return None
        return 401

    def journal_paths(self) -> dict[str, Any]:
        """Public journal key -> journal file (the three horizons first, then the earlier 30m versions)."""
        from src.dashboard.state import plan_journal_paths

        return plan_journal_paths(self.state)

    def journals(self) -> dict[str, Any]:
        from src.dashboard.plan_journal import load_view

        # A horizon journal that has not started yet (no file) still gets its tab.
        return {key: load_view(path) for key, path in self.journal_paths().items()}

    def summary_html(self, member: bool = False) -> str:
        """English text of what TIM's analysis says now (BTC); a failure only hides it."""
        from src.dashboard.analysis_summary import build_summary, render_en
        from src.dashboard.chart_live import load_plan_journals

        try:
            with self.state.lock:
                trades = dict(getattr(self.state, "footprint", None) or {})
            text = render_en(build_summary(self.state.chart_series(), load_plan_journals(self.journal_paths()) if member else {}, trades=trades or None))
            if not member:  # nothing about plans for a visitor without login, not even "none open"
                text = text.replace("<p>No open paper plans: TIM is waiting.</p>", "")
        except Exception:  # noqa: BLE001 - the public chart must still render
            return ""
        try:
            from src.dashboard import move_context

            text += move_context.render_en(move_context.shown(self.state.chart_series(), move_context.sources_from_state(self.state)))
        except Exception:  # noqa: BLE001 - the move explanation only hides itself
            pass
        return text

    def live_status(self) -> dict[str, Any] | None:
        """The live trader's status file; missing, too big or broken means "no live data"."""
        try:
            path = self.live_status_file
            if path.stat().st_size > MAX_LIVE_STATUS_BYTES:
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def render_page(self, path: str, query: dict[str, str], member: bool = False) -> str | None:
        from src.dashboard import public_en

        if path == "/chart":
            return public_en.chart_page(query.get("symbol"), query.get("tf"), self.summary_html(member))
        if path == "/guide":
            return public_en.guide_page(query.get("lang"))
        if path == "/live":
            return public_en.live_page(self.live_status())
        if path == "/reading":
            return self.reading_page(query)
        if path == "/journal/trade":
            return public_en.trade_page(self.journals(), query.get("rule", ""), query.get("id", ""))
        return public_en.journal_page(self.journals(), query.get("rule", public_en.DEFAULT_JOURNAL))

    def chart_model(self, query: dict[str, str], member: bool = False) -> dict[str, Any]:
        """The interactive chart's data (German labels; ``english_chart_model`` translates them)."""
        from src.dashboard.chart_live import build_live_chart
        from src.dashboard.market_context import chart_context
        from src.dashboard.perp_flow import chart_inputs as perp_chart_inputs

        with self.state.lock:
            footprint = dict(self.state.footprint)
            gamma = dict(self.state.gamma)
            gamma_zones = dict(getattr(self.state, "gamma_zones", None) or {})
            liquidation = dict(self.state.liquidation)
            perp, open_interest = perp_chart_inputs(self.state, query.get("symbol"))
            bybit = dict(getattr(self.state, "bybit_flow", None) or {})
        from src.dashboard.chart_live import load_plan_journals
        from src.dashboard.gamma_zones import load as load_zone_watch

        # Uzi 22.11.2026 "öffentlich": the yellow gamma zones (order book wall at a gamma level) on the public chart too.
        zone_watch_path = getattr(self.state, "gamma_zone_watch_path", None)
        model = build_live_chart(query.get("symbol"), query.get("tf"), self.state.chart_series(), footprint=footprint,
                                 plan_journals=load_plan_journals(self.journal_paths()) if member else None, gamma=gamma,
                                 gamma_zones=gamma_zones, gamma_zone_watch=load_zone_watch(zone_watch_path) if zone_watch_path else None,
                                 liquidation=liquidation, perp=perp, open_interest=open_interest, bybit=bybit,
                                 market=query.get("market"),
                                 context=chart_context(query.get("symbol")))
        return model

    def english_model(self, symbol: str | None, tf: str, market: str | None, member: bool) -> dict[str, Any]:
        """One timeframe of the chart as the visitor sees it, cached briefly (the reading needs 30m and 4h on every view)."""
        from src.dashboard.public_en import english_chart_model

        key = f"reading-model|{symbol}|{tf}|{market}|{member}"
        return self.cache.get(key, API_TTL, lambda: english_chart_model(
            self.chart_model({"symbol": symbol, "tf": tf, "market": market}, member)))

    def reading_overlay(self, query: dict[str, str], shown: dict[str, Any], member: bool) -> dict[str, Any] | None:
        """Uzi 24.11.2026: one reading for every timeframe (details 30m, big picture 4h), drawn on the shown candles."""
        from src.dashboard.chart_reading import unified_overlay

        return unified_overlay(shown, lambda tf: self.english_model(query.get("symbol"), tf, query.get("market"), member))

    def reading_page(self, query: dict[str, str]) -> str:
        """TIM chart reading for logged-in traders (Uzi 23.11.2026): BTC, plain sentences in English or German."""
        from src.dashboard import chart_reading, public_en

        # One reading, one chart (Uzi 24.11.2026): details from 30m, the big picture from 4h, whatever "tf" says.
        lang = query.get("lang") if query.get("lang") in chart_reading.LANGS else "en"
        model = self.english_model("BTCUSDT", chart_reading.BASE_TF, None, True)
        big = self.english_model("BTCUSDT", chart_reading.BIG_TF, None, True)
        reading = chart_reading.build_unified(model, big, lang=lang)
        return public_en.reading_page(chart_reading.render(reading, drawing=False), chart_reading.BASE_TF, lang)

    def render_api(self, path: str, query: dict[str, str], member: bool = False) -> bytes:
        if path == "/api/chart/live":
            model = self.chart_model(query, member)
            from src.dashboard.pages.chart import APP_VERSION
            from src.dashboard.public_en import english_chart_model

            out = english_chart_model(model)
            if member:  # TIM's reading as boxes on the chart, for logged-in traders only (Uzi 23.11.2026)
                out["reading"] = self.reading_overlay(query, out, member)
            return json.dumps({**out, "app_version": APP_VERSION}, default=str).encode()
        from src.dashboard.plan_cost_check import with_cost_check
        from src.dashboard.plan_journal import load_view

        journal_path = self.journal_paths().get(query.get("rule", ""), self.state.plan_journal_path)
        return json.dumps(with_cost_check(load_view(journal_path)), default=str).encode()

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
