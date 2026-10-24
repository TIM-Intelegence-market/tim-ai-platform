"""HTML of the new Control Center (Cockpit), served under /neu.

One style block and one script block, both fixed constants, so the CSP can pin
them by hash. All stored values go through ``html.escape``. Times are shown in
German local time (Europe/Berlin).
"""

from __future__ import annotations

import base64
import hashlib
import html
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.dashboard.cockpit.tiles import STATE_LABELS, human_age
from src.dashboard.helpers import _parse_time

LOCAL = ZoneInfo("Europe/Berlin")
REFRESH_SECONDS = 30

# The five areas of the new dashboard. Areas not built yet list the old pages
# that hold their content, so no area is an empty page.
AREAS: list[dict[str, Any]] = [
    {"key": "lage", "label": "Lage", "href": "/neu", "built": True,
     "text": "Läuft TIM, sind die Daten frisch, was sagt TIM zum Markt, was braucht dich."},
    {"key": "markt", "label": "Markt & Pläne", "href": "/neu/markt", "built": False,
     "text": "Chart, Vorbereitung, Setup-Pfad, Plan-Journal und Trader-Journal an einem Ort.",
     "pages": [("TIM-Chart", "/chart", "Kerzen, Levels, Szenarien mit Zonen, Stop und Zielen"),
               ("Vorbereitung", "/prep", "HTF-Bias, Vortages- und Wochen-Value, Sessions"),
               ("Setup-Pfad", "/setup-path", "Analyse-Gate und TIMs Pläne im Chart"),
               ("Plan-Journal", "/journal", "TIMs Long- und Short-Pläne auf Papier verfolgt"),
               ("Trader-Journal", "/trader-journal", "Eigene Papier-Trades mit Flussdiagramm als Gate")]},
    {"key": "forschung", "label": "Forschung", "href": "/neu/forschung", "built": False,
     "text": "Research Cases, Signale, Orderflow, Analytics, Insights und Qualifikation.",
     "pages": [("Research Cases", "/cases", "Alle Fälle mit Status und Beweislage"),
               ("Beobachtungen", "/observations", "Jüngste Beobachtungen der Detektoren"),
               ("Orderflow", "/orderflow", "Orderflow-Beobachtungen und Validierungen"),
               ("Signalforschung", "/signals", "Signale mit Kontext und Rückblick"),
               ("Analytics", "/analytics", "Auswertung über Fälle und Beobachtungen"),
               ("Insights", "/insights", "Rückblickende Auswertung"),
               ("Unabhängige Fälle", "/independent-cases", "Fälle für die Qualifizierung"),
               ("Qualifikation", "/qualification", "Stand der Qualifizierungskampagne")]},
    {"key": "betrieb", "label": "Betrieb", "href": "/neu/betrieb", "built": False,
     "text": "Runtime, Datenqualität, Lücken, Health, Zeitleiste und Ausnahmen.",
     "pages": [("Runtime", "/runtime", "Prozess, Queue, Cursor, Logs"),
               ("Datenqualität", "/data-quality", "Abdeckung der Datenräume"),
               ("Vorfälle & Lücken", "/gaps", "Offene Datenlücken und Vorfälle"),
               ("Health Center", "/health", "Watchdog und Gesundheitsprüfungen"),
               ("Zeitleiste", "/timeline", "Ereignisse von Watchdog, Backup und Kampagne"),
               ("Ausnahmen", "/exceptions", "Datenqualitäts-Ausnahmen")]},
    {"key": "system", "label": "System & Freigabe", "href": "/neu/system", "built": False,
     "text": "V2-Freigabe, Sicherheit, Audit, MCP und Deploy-Verlauf.",
     "pages": [("V2 Readiness", "/v2-readiness", "Gates, Blocker und Verantwortliche"),
               ("Security", "/security", "PostgreSQL-Sicherheitsprüfung"),
               ("Audit & Evidence", "/audit-evidence", "Tests, Deploy-Stand, Vorfälle"),
               ("Graphify & MCP", "/mcp", "MCP-Anbindung")]},
]
AREA_BY_KEY = {area["key"]: area for area in AREAS}

STYLE = """
:root{--bg:#f4f5f7;--panel:#fff;--ink:#14171c;--muted:#5b6472;--line:#dfe3e8;--ok:#1a8f5a;--warn:#b7791f;--fail:#c53030;--unknown:#8a94a3;--accent:#2457c5;--okbg:#e6f5ee;--warnbg:#fdf3e1;--failbg:#fdeaea;--unknownbg:#eef0f3}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--muted:#9aa5b1;--line:#2a313b;--ok:#3fb27f;--warn:#e3a43a;--fail:#f06262;--unknown:#7d8794;--accent:#6c9cff;--okbg:#12291f;--warnbg:#2e2412;--failbg:#331718;--unknownbg:#1e242c}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.top{background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
.top__in{max-width:1280px;margin:0 auto;padding:10px 16px;display:flex;flex-wrap:wrap;align-items:center;gap:8px 20px}
.brand{font-weight:800;font-size:18px;letter-spacing:.04em;color:var(--ink)}.brand small{font-weight:500;color:var(--muted);font-size:12px;margin-left:8px;letter-spacing:0}
.nav{display:flex;flex-wrap:wrap;gap:4px;flex:1}
.nav a{padding:6px 10px;border-radius:8px;color:var(--muted);font-weight:600;font-size:14px}
.nav a[aria-current=page]{background:var(--bg);color:var(--ink)}
.nav a.old{margin-left:auto;font-weight:500}
.live{font-size:12px;color:var(--muted);white-space:nowrap}
.live[data-state=fail]{color:var(--fail)}
main{max-width:1280px;margin:0 auto;padding:18px 16px 40px}
.head{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;margin-bottom:18px}
.head h1{margin:0;font-size:24px}
.pill{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;font-weight:700;font-size:13px}
.pill::before{content:"";width:8px;height:8px;border-radius:50%;background:currentColor}
.s-ok{color:var(--ok)}.s-warn{color:var(--warn)}.s-fail{color:var(--fail)}.s-unknown{color:var(--unknown)}
.pill.s-ok{background:var(--okbg)}.pill.s-warn{background:var(--warnbg)}.pill.s-fail{background:var(--failbg)}.pill.s-unknown{background:var(--unknownbg)}
.meta{color:var(--muted);font-size:13px}
section{margin:0 0 22px}
section>h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:0 0 8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.tile{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--unknown);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:3px;min-width:0}
.tile.s-ok{border-left-color:var(--ok)}.tile.s-warn{border-left-color:var(--warn)}.tile.s-fail{border-left-color:var(--fail)}
.tile.k-info.s-ok{border-left-color:var(--line)}
.tile__top{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.tile__label{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.tile__state{font-size:11px;font-weight:700}
.tile__value{font-size:20px;font-weight:700;color:var(--ink);overflow-wrap:anywhere}
.tile__reason{font-size:13px;color:var(--ink);overflow-wrap:anywhere}
.tile.s-warn .tile__reason{color:var(--warn)}.tile.s-fail .tile__reason{color:var(--fail)}
.tile__detail,.tile__foot{font-size:12px;color:var(--muted);overflow-wrap:anywhere}
.tile__foot{margin-top:auto;padding-top:4px;display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}
.cols{display:grid;grid-template-columns:2fr 1fr;gap:18px}
@media (max-width:900px){.cols{display:flex;flex-direction:column;gap:0}.cols>div{display:contents}.cols .first-on-phone{order:-1}}
.need{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:4px 12px}
.need li{list-style:none;padding:8px 0;border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:baseline}
.need li:last-child{border-bottom:0}.need ul{margin:0;padding:0}
.need b{white-space:nowrap}.need li span,.note{overflow-wrap:anywhere;min-width:0}
.empty{color:var(--muted);padding:10px 0;margin:0}
.plans{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}
.plan{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.plan h3{margin:0 0 6px;font-size:15px}.plan ul{margin:0;padding-left:18px;font-size:13px}
.plan--long h3{color:var(--ok)}.plan--short h3{color:var(--fail)}
.pages{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}
.page{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
.page b{display:block;margin-bottom:2px}
.note{font-size:13px;color:var(--muted)}
footer{max-width:1280px;margin:0 auto;padding:0 16px 30px;color:var(--muted);font-size:12px}
.tile__value a{color:inherit}
@media (max-width:700px){.nav{order:3;flex-basis:100%;flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch}.nav a{white-space:nowrap}.nav a.old{margin-left:0}.live{margin-left:auto}}
@media (max-width:560px){.tile__value{font-size:18px}.head h1{font-size:20px}}
"""

SCRIPT = """
(() => {
  'use strict';
  const REFRESH_MS = %d * 1000;
  const root = document.getElementById('cockpit');
  const live = document.getElementById('live');
  if (!root || !live) return;
  let lastOk = Date.now(), busy = false;
  function age(seconds) {
    if (seconds < -60) return 'Zeitstempel in der Zukunft';
    if (seconds < 0) seconds = 0;
    if (seconds < 90) return 'vor ' + seconds + ' s';
    if (seconds < 5400) return 'vor ' + Math.round(seconds / 60) + ' min';
    if (seconds < 129600) return 'vor ' + Math.round(seconds / 3600) + ' h';
    return 'vor ' + Math.round(seconds / 86400) + ' Tagen';
  }
  function tick() {
    document.querySelectorAll('time[data-asof]').forEach(el => {
      const t = Date.parse(el.dataset.asof);
      if (!isNaN(t)) el.textContent = age(Math.floor((Date.now() - t) / 1000));
    });
    const behind = Math.floor((Date.now() - lastOk) / 1000);
    if (behind > 2 * REFRESH_MS / 1000) { live.dataset.state = 'fail'; live.textContent = '● Keine Verbindung, Anzeige ' + age(behind).replace('vor ', '') + ' alt'; }
  }
  async function refresh() {
    if (busy || document.hidden) return;
    busy = true;
    try {
      const res = await fetch(root.dataset.fragment, {cache: 'no-store', headers: {'Accept': 'application/json'}});
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      if (typeof data.html === 'string') root.innerHTML = data.html;
      lastOk = Date.now();
      live.dataset.state = 'ok';
      live.textContent = '● Live, aktualisiert ' + new Date().toLocaleTimeString('de-DE', {timeZone: 'Europe/Berlin', hour: '2-digit', minute: '2-digit', second: '2-digit'});
    } catch (err) {
      live.dataset.state = 'fail';
      live.textContent = '● Aktualisierung fehlgeschlagen (' + err.message + ')';
    } finally { busy = false; tick(); }
  }
  setInterval(refresh, REFRESH_MS);
  setInterval(tick, 5000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  tick();
})();
""" % REFRESH_SECONDS


def _hash(block: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(block.encode()).digest()).decode() + "'"


COCKPIT_CSP = (
    "default-src 'none'; "
    f"style-src {_hash(STYLE)}; "
    f"script-src {_hash(SCRIPT)}; "
    "connect-src 'self'; img-src 'self' data:; font-src 'none'; "
    "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def local_time(value: Any, with_date: bool = False) -> str:
    moment = value if isinstance(value, datetime) else _parse_time(value)
    if moment is None:
        return "—"
    local = moment.astimezone(LOCAL)
    return local.strftime("%d.%m. %H:%M") if with_date else local.strftime("%H:%M")


def _tile(tile: dict[str, Any]) -> str:
    state = tile.get("state") or "unknown"
    info = (tile.get("extra") or {}).get("kind") == "info"
    label = "" if info and state == "ok" else STATE_LABELS.get(state, state)
    value = _e(tile.get("value"))
    if tile.get("href"):
        value = f"<a href='{_e(tile['href'])}'>{value}</a>"
    extra = tile.get("extra") or {}
    detail = tile.get("detail") or ""
    if extra.get("start"):
        detail = f"{local_time(extra['start'], True)}–{local_time(extra.get('end'))} Uhr" + (f" · {detail}" if detail else "")
    as_of = tile.get("as_of")
    stamp = ""
    if as_of:
        stamp = (f"<span>Stand {local_time(as_of, True)} · <time data-asof='{_e(as_of)}'>{_e(human_age(tile.get('age_seconds')))}</time></span>")
    return (
        f"<article class='tile s-{_e(state)}{' k-info' if info else ''}' id='t-{_e(tile.get('id'))}'>"
        f"<div class='tile__top'><span class='tile__label'>{_e(tile.get('label'))}</span>"
        f"<span class='tile__state s-{_e(state)}'>{_e(label)}</span></div>"
        f"<div class='tile__value'>{value}</div>"
        + (f"<div class='tile__reason'>{_e(tile.get('reason'))}</div>" if tile.get("reason") and state != "ok" else "")
        + (f"<div class='tile__detail'>{_e(detail)}</div>" if detail else "")
        + f"<div class='tile__foot'>{stamp}<span title='Quelle'>{_e(tile.get('source'))}</span></div></article>"
    )


def _grid(tiles: list[dict[str, Any]]) -> str:
    return "<div class='grid'>" + "".join(_tile(t) for t in tiles) + "</div>"


def lage_body(model: dict[str, Any]) -> str:
    """The refreshable part of the start page (also sent as fragment)."""
    overall = model.get("overall") or "unknown"
    needs = model.get("attention") or []
    need_html = (
        "<ul>" + "".join(
            f"<li><b class='s-{_e(t['state'])}'>{_e(STATE_LABELS.get(t['state'], t['state']))}</b>"
            f"<span><a href='{_e(t.get('href') or '#t-' + str(t.get('id')))}'>{_e(t.get('label'))}</a>: {_e(t.get('reason'))}</span></li>"
            for t in needs) + "</ul>"
        if needs else "<p class='empty'>Nichts offen. Alle Quellen mit Status sind grün oder liefern bewusst keine Daten (grau, Grund auf der Kachel).</p>"
    )
    plans = model.get("plans") or []
    plan_html = (
        "<div class='plans'>" + "".join(
            f"<article class='plan plan--{_e(p.get('direction', '').lower())}'><h3>{_e(p.get('title'))}</h3><ul>"
            + "".join(f"<li>{_e(line)}</li>" for line in p.get("lines") or []) + "</ul></article>"
            for p in plans) + "</div>"
        if plans else "<p class='empty'>Kein Plan mit Einstiegszone: Der Kurs steht nicht an einer Range-Kante. <a href='/setup-path'>Setup-Pfad</a></p>"
    )
    slow = [f"{name} ({info.get('error')})" for name, info in (model.get("sources") or {}).items() if not info.get("ok") or info.get("stale_seconds") is not None]
    return (
        f"<div class='head'><h1>Lage</h1><span class='pill s-{_e(overall)}'>{_e(model.get('headline'))}</span>"
        f"<span class='meta'>Stand {local_time(model.get('generated_at'), True)} Uhr · {_e(model.get('safety'))}</span></div>"
        f"<div class='cols'><div>"
        f"<section aria-labelledby='h-system'><h2 id='h-system'>System</h2>{_grid(model.get('system') or [])}</section>"
        f"<section aria-labelledby='h-market'><h2 id='h-market'>Markt jetzt</h2>{_grid(model.get('market') or [])}</section>"
        f"<section aria-labelledby='h-plans'><h2 id='h-plans'>TIMs Pläne jetzt</h2>{plan_html}"
        "<p class='note'>Stop und Ziele sind eine Vorschau nach TIMs Regeln, keine Order und keine Anlageberatung.</p></section>"
        f"</div><div>"
        f"<section class='first-on-phone' aria-labelledby='h-need'><h2 id='h-need'>Braucht dich</h2><div class='need'>{need_html}</div></section>"
        f"<section aria-labelledby='h-journal'><h2 id='h-journal'>Journale</h2>{_grid(model.get('journals') or [])}</section>"
        + (f"<p class='note'>Langsame oder fehlende Quellen: {_e('; '.join(slow))}</p>" if slow else "")
        + "</div></div>"
    )


def area_body(key: str) -> str:
    area = AREA_BY_KEY[key]
    pages = "".join(
        f"<a class='page' href='{_e(href)}'><b>{_e(label)}</b><span class='note'>{_e(text)}</span></a>"
        for label, href, text in area.get("pages") or []
    )
    return (
        f"<div class='head'><h1>{_e(area['label'])}</h1><span class='pill s-unknown'>Im Aufbau</span></div>"
        f"<p>{_e(area['text'])}</p>"
        "<p class='note'>Dieser Bereich wird im nächsten Paket neu gebaut. Bis dahin stehen seine Inhalte auf diesen Seiten des bisherigen Dashboards:</p>"
        f"<div class='pages'>{pages}</div>"
    )


def page(title: str, active: str, body: str, refresh: bool) -> str:
    nav = "".join(
        f"<a href='{_e(a['href'])}'{' aria-current=page' if a['key'] == active else ''}>{_e(a['label'])}</a>" for a in AREAS
    ) + "<a class='old' href='/'>Bisheriges Dashboard</a>"
    fragment = AREA_BY_KEY[active]["href"] + "?fragment=1"
    return (
        "<!doctype html><html lang='de'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'><meta name='color-scheme' content='light dark'>"
        f"<title>{_e(title)} · TIM</title><style>{STYLE}</style></head><body>"
        f"<header class='top'><div class='top__in'><a class='brand' href='/neu'>TIM<small>Control Center</small></a>"
        f"<nav class='nav' aria-label='Bereiche'>{nav}</nav>"
        f"<span id='live' class='live' aria-live='polite'>{'● Live, alle ' + str(REFRESH_SECONDS) + ' s' if refresh else ''}</span></div></header>"
        f"<main id='cockpit' data-fragment='{_e(fragment)}'>{body}</main>"
        "<footer>TIM · nur Beobachtung und Papier · keine Orders, keine Shell- oder Git-Aktionen · Zeiten in deutscher Ortszeit</footer>"
        + (f"<script>{SCRIPT}</script>" if refresh else "")
        + "</body></html>"
    )


def render_lage(model: dict[str, Any]) -> str:
    return page("Lage", "lage", lage_body(model), refresh=True)


def render_area(key: str) -> str:
    return page(AREA_BY_KEY[key]["label"], key, area_body(key), refresh=False)
