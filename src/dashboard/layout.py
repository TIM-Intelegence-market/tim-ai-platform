from __future__ import annotations

import base64
import hashlib
from typing import Any
from src.dashboard import design_system
from src.dashboard.design_system import severity as _severity_of
from pathlib import Path

from src.dashboard.helpers import _safe

_ASSETS = Path(__file__).resolve().parent / "assets"

CSS = (_ASSETS / "style.css").read_text(encoding="utf-8")


EXTRA_CSS = (_ASSETS / "extra.css").read_text(encoding="utf-8")
EXTRA_CSS = EXTRA_CSS + design_system.COMPONENT_CSS


AUTO_REFRESH_SCRIPT = (_ASSETS / "auto_refresh.html").read_text(encoding="utf-8")


def _content_security_policy() -> str:
    style = CSS + EXTRA_CSS
    script = AUTO_REFRESH_SCRIPT.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    style_hash = base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()
    script_hash = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    return (
        "default-src 'none'; "
        f"style-src 'sha256-{style_hash}'; "
        f"script-src 'sha256-{script_hash}'; "
        "connect-src 'self'; img-src 'self' data:; font-src 'none'; "
        "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )


NAV_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("OPERATIONS", [
        ("Overview", "/"),
        ("Runtime", "/runtime"),
        ("Data Quality", "/data-quality"),
        ("Incidents & Gaps", "/gaps"),
    ]),
    ("RESEARCH", [
        ("Independent Cases", "/independent-cases"),
        ("Qualification", "/qualification"),
    ]),
    ("READINESS", [
        ("V2 Readiness", "/v2-readiness"),
    ]),
    ("INTELLIGENCE", [
        ("Setup Path", "/setup-path"),
        ("Graphify & MCP", "/mcp"),
    ]),
    ("SYSTEM", [
        ("Security", "/security"),
        ("Audit & Evidence", "/audit-evidence"),
    ]),
]


def _strip_states(data: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """Derive global header states strictly from the live snapshot.

    Values mirror the AUTO_REFRESH_SCRIPT derivation; a state without
    evidence renders as UNKNOWN, never as a healthy substitute.
    """
    live = data.get("operational_health", {})
    status = str(live.get("status", "UNKNOWN")).upper()
    if status == "GREEN":
        system = ("ok", "RUNNING")
    elif status == "RED":
        system = ("fail", "IMPAIRED")
    elif status == "YELLOW":
        system = ("warn", "DEGRADED")
    else:
        system = ("unknown", "UNKNOWN")

    stream = str(live.get("stream", "UNKNOWN")).upper()
    age = live.get("data_age_seconds")
    fresh = isinstance(age, (int, float)) and 0 <= age <= 120
    if stream == "GREEN" and fresh:
        data_state = ("ok", "LIVE")
    elif stream == "GREEN":
        data_state = ("warn", "STALE")
    elif stream in ("RED", "FAIL"):
        data_state = ("fail", "DOWN")
    else:
        data_state = ("unknown", "UNKNOWN")

    queue_depth = live.get("queue_depth")
    if isinstance(queue_depth, int):
        queue_state = ("ok", f"{queue_depth} EV") if queue_depth == 0 else ("warn", f"{queue_depth} EV")
    else:
        queue_state = ("unknown", "UNKNOWN")

    datasets = data.get("operations", {}).get("datasets") or []
    rolling = datasets[-1] if datasets else {}
    quality_status = rolling.get("status")
    quality_text = str(rolling.get("coverage") or "UNKNOWN")
    quality_state = (_severity_of(quality_status), quality_text)

    bands = (data.get("gate_model") or {}).get("bands") or {}
    research_gates = [str(g.get("status", "")).upper() for g in (bands.get("research_readiness") or []) if isinstance(g, dict)]
    research_gates = [s for s in research_gates if s]
    if research_gates and "FAIL" not in research_gates and all(s == "PASS" for s in research_gates):
        research_state = ("ok", "READY")
    elif research_gates and all(s == "NO_EVIDENCE" for s in research_gates):
        research_state = ("unknown", "UNKNOWN")
    elif research_gates and ("PASS" in research_gates or "IN_PROGRESS" in research_gates or "LIMITED" in research_gates):
        research_state = ("warn", "PARTIAL")
    else:
        readiness_status = str(data.get("readiness", {}).get("readiness_status", "UNKNOWN")).upper()
        if "NOT_READY" in readiness_status:
            research_state = ("warn", "NOT READY")
        elif readiness_status in ("READY_FOR_V2", "READY"):
            research_state = ("ok", "READY")
        elif readiness_status == "UNKNOWN":
            research_state = ("unknown", "UNKNOWN")
        else:
            research_state = ("warn", readiness_status)
    return [
        ("SYSTEM",) + system,
        ("LIVE DATA",) + data_state,
        ("QUEUE",) + queue_state,
        ("DATA QUALITY",) + quality_state,
        ("RESEARCH",) + research_state,
    ]


def _error_page(page: str, exc: Exception) -> str:
    """Bounded degradation page: a page that cannot render stays explorable.

    The message is operator-facing (loopback-only surface) and names the page,
    the exception type and its message so a malformed persisted record can be
    traced without exposing stack traces.
    """
    return (
        "<!doctype html><html lang='de'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='color-scheme' content='dark'>"
        f"<title>{_safe(page)} · Render-Fehler · TIM</title>"
        f"<style>{CSS}{EXTRA_CSS}</style></head><body><div class='errwrap'><div class='errbox'>"
        "<span class='badge badge--red'>RENDER FEHLER</span>"
        f"<h1>{_safe(page)} konnte nicht gerendert werden</h1>"
        f"<p>Die Seite <code>{_safe(page)}</code> ist auf einen ungültigen persistierten Datensatz gestoßen. "
        "Andere Seiten bleiben verfügbar; es wurden keine Daten verändert.</p>"
        f"<p><code>{type(exc).__name__}: {_safe(str(exc))}</code></p>"
        "<p><a href='/'>Zur Übersicht zurückkehren</a></p>"
        "</div></div></body></html>"
    )


def _layout(title: str, page: str, body: str, strip: list[tuple[str, str, str, str]] | None = None) -> str:
    nav_parts = []
    for group_label, links in NAV_GROUPS:
        items = "".join(
            f"<a href='{href}' class='{'active' if page == key else ''}'"
            f"{' aria-current=\'page\'' if page == key else ''}>{_safe(key)}</a>"
            for key, href in links
        )
        nav_parts.append(f"<div class='nav__group'><p class='nav__label'>{_safe(group_label)}</p>{items}</div>")
    nav = "".join(nav_parts)

    strip_rows = "".join(
        f"<div class='status-matrix__row{' status-matrix__row--locked' if label == 'TRADING' else ''}'>"
        f"<span>{_safe(label)}</span><b id='st-{_safe(label.lower().replace(' ', '-'))}' data-sev='{sev}'>{_safe(value)}</b></div>"
        for label, sev, value in (strip or [])
    )
    trading_row = (
        "<div class='status-matrix__row status-matrix__row--locked'>"
        "<span>TRADING</span><b data-sev='fail'>LOCKED</b></div>"
    )
    matrix = f"<dl class='status-matrix' aria-label='Globaler Systemstatus'>{strip_rows}{trading_row}</dl>" if strip else ""

    legacy_links = [
        ("Observations", "/observations"), ("Research Cases", "/cases"), ("Orderflow", "/orderflow"),
        ("Signal Research", "/signals"), ("Analytics", "/analytics"), ("Insights", "/insights"),
        ("Health Center", "/health"), ("Data Quality Exceptions", "/exceptions"),
        ("Timeline", "/timeline"), ("Research", "/research"),
    ]
    legacy_nav = "".join(
        f"<a href='{href}' class='{'active' if page == key else ''}'"
        f"{' aria-current=\'page\'' if page == key else ''}>{_safe(key)}</a>"
        for key, href in legacy_links
    )
    return f"""<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='color-scheme' content='dark'><link rel='icon' href='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 16 16%22><rect width=%2216%22 height=%2216%22 rx=%223%22 fill=%22%23070a0f%22/><rect x=%224%22 y=%224%22 width=%228%22 height=%228%22 rx=%221.5%22 fill=%22%2335d39a%22/></svg>'><title>{_safe(title)} · TIM</title><style>{CSS}{EXTRA_CSS}</style></head><body><a class='skip-link' href='#main-content'>Zum Hauptinhalt springen</a><header class='topbar'><div class='topbar__inner'><a class='brand' href='/' aria-label='TIM Control Center Startseite'>TIM<small>OPERATIONS &amp; RESEARCH CONTROL CENTER</small></a><nav class='nav' aria-label='Hauptnavigation'>{nav}</nav>{matrix}<details class='legacy-nav'><summary>Vertiefende Research-Ansichten</summary><nav aria-label='Vertiefende Research-Ansichten'>{legacy_nav}</nav></details><button type='button' id='tim-status' class='live badge--yellow' aria-live='polite' aria-label='Status jetzt aktualisieren'>● Startet…</button></div></header><main id='main-content' class='shell' tabindex='-1'>{body}</main><footer class='footer'>TIM · OBSERVE-only · read-only control surface · keine Trading-, Shell- oder Git-Aktionen</footer>{AUTO_REFRESH_SCRIPT}</body></html>"""


def _hero(title: str, text: str) -> str:
    return f"<div class='hero'><div><h1>{_safe(title)}</h1><p>{_safe(text)}</p></div><div class='observe'>OBSERVE • READ-ONLY</div></div>"
