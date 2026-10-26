"""Graphify graph of the TIM code base inside the Control Center (`/graphify`).

The graph is built on the Mac by the hourly job `com.tim.obsidian-refresh`
(`src/obsidian_vault/auto_refresh.py`), which copies `graph.html` and
`GRAPH_REPORT.md` to `~/Documents/TIM/TIM Graph Ansicht/`. This page only
serves those files; it never runs graphify itself.

graph.html is a standalone graphify document: inline style and scripts,
one inline `onchange` handler and vis-network from unpkg (pinned version with
SRI hash). The CSP allows exactly those inline blocks by SHA-256 hash and only
that one script URL prefix.
"""
from __future__ import annotations

import base64
import hashlib
import html
import os
import re
from datetime import datetime, timezone
from pathlib import Path

VIEW_ENV = "TIM_GRAPHIFY_VIEW"
DEFAULT_VIEW = Path.home() / "Documents/TIM/TIM Graph Ansicht"
VIS_PREFIX = "https://unpkg.com/vis-network@"
MAX_BYTES = 2_000_000  # dashboard response limit; the aggregated view is ~0.7 MB

_SCRIPT = re.compile(r"<script(\s[^>]*)?>(.*?)</script>", re.S | re.I)
_SRC = re.compile(r"""\bsrc\s*=\s*["']([^"']+)["']""", re.I)
_SAFE_URL = re.compile(r"^https://unpkg\.com/vis-network@[0-9.]+/[A-Za-z0-9._/-]+\.js$")
_HANDLER = re.compile(r"""\son[a-z]+\s*=\s*"([^"]*)\"""", re.I)


def view_dir() -> Path:
    value = os.environ.get(VIEW_ENV)
    return Path(value).expanduser() if value else DEFAULT_VIEW


def _hash(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


def graph_csp(page: str) -> str | None:
    """CSP for one graphify document, or None when it holds anything unexpected."""
    scripts: list[str] = []
    external: list[str] = []
    for attrs, body in _SCRIPT.findall(page):
        src = _SRC.search(attrs or "")
        if src:
            url = src.group(1)
            if not url.startswith(VIS_PREFIX) or body.strip() or ".." in url or not _SAFE_URL.match(url):
                return None  # only the pinned vis-network script may load from outside
            external.append(url)
            continue
        scripts.append(_hash(body))
    handlers = [_hash(html.unescape(value)) for value in _HANDLER.findall(page)]
    script_src = " ".join(dict.fromkeys(scripts + handlers)) or "'none'"
    if handlers:
        script_src += " 'unsafe-hashes'"
    return (
        "default-src 'none'; "
        f"script-src {script_src} {' '.join(dict.fromkeys(external))}; "
        # vis-network and the page set inline styles at runtime (a hash would disable
        # 'unsafe-inline'); styles cannot run script, scripts stay hash-locked
        "style-src 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'none'; font-src 'none'; "
        "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )


def _missing_page(reason: str) -> str:
    return (
        "<!doctype html><html lang='de'><meta charset='utf-8'><title>Graphify-Graph</title>"
        "<body style='font-family:-apple-system,sans-serif;max-width:640px;margin:48px auto;padding:0 16px'>"
        f"<h1>Graphify-Graph</h1><p>{html.escape(reason)}</p>"
        "<p>Der Graph entsteht stündlich durch den Mac-Job <code>com.tim.obsidian-refresh</code> "
        f"in <code>{html.escape(str(view_dir()))}</code>.</p><p><a href='/mcp'>Zurück</a></p></body></html>"
    )


MISSING_CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; "
               "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def graph_page(directory: Path | None = None) -> tuple[int, str, str]:
    """(status, html, csp) for `/graphify`."""
    path = (directory or view_dir()) / "graph.html"
    try:
        if path.stat().st_size > MAX_BYTES:
            return 413, _missing_page("Die Graph-Datei ist zu groß für die Anzeige."), MISSING_CSP
        page = path.read_text(encoding="utf-8")
    except OSError:
        return 404, _missing_page("Noch kein Graph vorhanden."), MISSING_CSP
    csp = graph_csp(page)
    if csp is None:
        return 500, _missing_page("Die Graph-Datei enthält unerwartete Skripte und wird nicht angezeigt."), MISSING_CSP
    page = re.sub(r"<title>.*?</title>", "<title>TIM Graphify-Graph</title>", page, count=1, flags=re.S)
    return 200, page, csp


def report_text(directory: Path | None = None) -> tuple[int, str]:
    """(status, markdown) for `/graphify/report`."""
    path = (directory or view_dir()) / "GRAPH_REPORT.md"
    try:
        return 200, path.read_text(encoding="utf-8")[:MAX_BYTES]
    except OSError:
        return 404, "Noch kein Graphify-Bericht vorhanden.\n"


def graph_status(directory: Path | None = None) -> dict[str, str | None]:
    """Age of the graph for the /mcp page."""
    path = (directory or view_dir()) / "graph.html"
    try:
        stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return {"status": "UNAVAILABLE", "updated_at_utc": None}
    return {"status": "AVAILABLE", "updated_at_utc": stamp.isoformat(timespec="seconds")}
