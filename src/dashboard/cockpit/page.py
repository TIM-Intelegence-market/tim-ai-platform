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

# The areas of the new dashboard. Areas not built yet list the old pages
# that hold their content, so no area is an empty page.
AREAS: list[dict[str, Any]] = [
    {"key": "lage", "label": "Lage", "href": "/neu", "built": True,
     "text": "Läuft TIM, sind die Daten frisch, was sagt TIM zum Markt, was braucht dich."},
    {"key": "markt", "label": "Markt & Pläne", "href": "/neu/markt", "built": True,
     "text": "Chart mit TIMs Plänen, Vorbereitung, Plan-Journal und Trader-Journal an einem Ort.",
     "pages": [("TIM-Chart", "/chart", "Großer Chart mit Szenario-Tabelle und Levels"),
               ("Vorbereitung", "/prep", "Volle Level-Karte, HTF-Struktur, Value und Sessions"),
               ("Setup-Pfad", "/setup-path", "Analyse-Gate und Pipeline-Stufen"),
               ("Plan-Journal", "/journal", "Alle Pläne mit Grade, Evidenz und Kosten"),
               ("Trader-Journal", "/trader-journal", "Eigene Papier-Trades eintragen und reviewen")]},
    {"key": "mac", "label": "Mac jetzt", "href": "/neu/mac", "built": True,
     "text": "Woran der Mac gerade arbeitet: CI-Lauf, Issue-Worker und die TIM-Dienste im Hintergrund.",
     "pages": [("Worker-Dashboard", "http://127.0.0.1:8767/", "Volles Dashboard des Issue-Workers"),
               ("Health Center", "/health", "Watchdog und Gesundheitsprüfungen"),
               ("Zeitleiste", "/timeline", "Ereignisse von Watchdog, Backup und Kampagne")]},
    {"key": "forschung", "label": "Forschung", "href": "/neu/forschung", "built": True,
     "text": "Research Cases, Signale, Orderflow, Analytics, Insights und Qualifikation.",
     "pages": [("Research Cases", "/cases", "Alle Fälle mit Status und Beweislage"),
               ("Beobachtungen", "/observations", "Jüngste Beobachtungen der Detektoren"),
               ("Orderflow", "/orderflow", "Orderflow-Beobachtungen und Validierungen"),
               ("Signalforschung", "/signals", "Signale mit Kontext und Rückblick"),
               ("Analytics", "/analytics", "Auswertung über Fälle und Beobachtungen"),
               ("Insights", "/insights", "Rückblickende Auswertung"),
               ("Unabhängige Fälle", "/independent-cases", "Fälle für die Qualifizierung"),
               ("Qualifikation", "/qualification", "Stand der Qualifizierungskampagne")]},
    {"key": "betrieb", "label": "Betrieb", "href": "/neu/betrieb", "built": True,
     "text": "Runtime, Datenqualität, Lücken, Health, Zeitleiste und Ausnahmen.",
     "pages": [("Runtime", "/runtime", "Prozess, Queue, Cursor, Logs"),
               ("Datenqualität", "/data-quality", "Abdeckung der Datenräume"),
               ("Vorfälle & Lücken", "/gaps", "Offene Datenlücken und Vorfälle"),
               ("Health Center", "/health", "Watchdog und Gesundheitsprüfungen"),
               ("Zeitleiste", "/timeline", "Ereignisse von Watchdog, Backup und Kampagne"),
               ("Ausnahmen", "/exceptions", "Datenqualitäts-Ausnahmen")]},
    {"key": "system", "label": "System & Freigabe", "href": "/neu/system", "built": True,
     "text": "V2-Freigabe, Sicherheit, Audit, MCP und Deploy-Verlauf.",
     "pages": [("V2 Readiness", "/v2-readiness", "Gates, Blocker und Verantwortliche"),
               ("Security", "/security", "PostgreSQL-Sicherheitsprüfung"),
               ("Audit & Evidence", "/audit-evidence", "Tests, Deploy-Stand, Vorfälle"),
               ("Graphify & MCP", "/mcp", "MCP-Anbindung")]},
]
AREA_BY_KEY = {area["key"]: area for area in AREAS}

STYLE = """
:root{--bg:#edf1f3;--panel:#fff;--ink:#16222e;--muted:#52616e;--line:#d3dce2;--accent:#0e5a73;--ok:#23744a;--warn:#8a5600;--fail:#b02a22;--unknown:#5f6b77;--okbg:#e7f2ec;--warnbg:#fbf1dd;--failbg:#fbe6e4;--unknownbg:#eef1f3;--rowwarn:#fdf6e8;--rowfail:#fdf0ef}
@media (prefers-color-scheme:dark){:root{--bg:#0f1a22;--panel:#15232e;--ink:#e2e9ee;--muted:#9aaab6;--line:#263744;--accent:#7cc4dd;--ok:#5cc48d;--warn:#e5a84b;--fail:#f37f75;--unknown:#93a0ab;--okbg:#143026;--warnbg:#33280f;--failbg:#3a1a19;--unknownbg:#1c2b36;--rowwarn:#221f14;--rowfail:#271a1c}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "Avenir Next",Avenir,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;font-variant-numeric:tabular-nums}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
a:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
.top{background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
.top__in{max-width:1280px;margin:0 auto;padding:0 16px;display:flex;flex-wrap:wrap;align-items:center;gap:0 24px}
.brand{font-weight:700;font-size:19px;color:var(--ink);padding:12px 0}.brand small{font-weight:500;color:var(--muted);font-size:13px;margin-left:8px}
.nav{display:flex;flex-wrap:wrap;gap:2px;flex:1;align-self:stretch}
.nav a{display:flex;align-items:center;padding:12px 10px;color:var(--muted);font-weight:600;font-size:14px;border-bottom:3px solid transparent;margin-bottom:-1px}
.nav a:hover{color:var(--ink);text-decoration:none}
.nav a[aria-current=page]{color:var(--ink);border-bottom-color:var(--accent)}
.nav a.old{margin-left:auto;font-weight:500}
.live{font-size:13px;color:var(--muted);white-space:nowrap}
.live[data-state=fail]{color:var(--fail)}
main{max-width:1280px;margin:0 auto;padding:22px 16px 40px}
.head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 16px;margin-bottom:18px}
.head h1{margin:0;font-size:26px;font-weight:600;letter-spacing:-.01em}
.pill{display:inline-flex;align-items:center;gap:7px;padding:3px 10px;border-radius:6px;font-weight:600;font-size:14px}
.s-ok{color:var(--ok)}.s-warn{color:var(--warn)}.s-fail{color:var(--fail)}.s-unknown{color:var(--unknown)}
.pill.s-ok{background:var(--okbg)}.pill.s-warn{background:var(--warnbg)}.pill.s-fail{background:var(--failbg)}.pill.s-unknown{background:var(--unknownbg)}
.pill::before,.tile__state::before,.hero__line::before{content:"\\25CB"/"";font-size:.8em}
.s-ok.pill::before,.s-ok>.tile__state::before,.hero.s-ok .hero__line::before{content:"\\25CF"/""}
.s-warn.pill::before,.s-warn>.tile__state::before,.hero.s-warn .hero__line::before{content:"\\25B2"/""}
.s-fail.pill::before,.s-fail>.tile__state::before,.hero.s-fail .hero__line::before{content:"\\25A0"/""}
.k-info.s-ok>.tile__state::before{content:none}
.meta{color:var(--muted);font-size:14px}
section{margin:0 0 26px}
section>h2{font-size:17px;font-weight:600;color:var(--ink);margin:0 0 8px}
section>h2 a{color:inherit}
.hero[class]{color:var(--ink)}
.hero{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px 40px;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px 24px;margin:0 0 26px}
.hero__line{margin:0 0 12px;font-size:clamp(25px,3.4vw,38px);line-height:1.15;font-weight:600;letter-spacing:-.015em;color:var(--ink);display:flex;gap:14px;align-items:baseline}
.hero__line::before{font-size:.6em;position:relative;top:-.12em}
.hero.s-ok .hero__line::before{color:var(--ok)}.hero.s-warn .hero__line::before{color:var(--warn)}.hero.s-fail .hero__line::before{color:var(--fail)}.hero.s-unknown .hero__line::before{color:var(--unknown)}
.hero h2{font-size:15px;font-weight:600;color:var(--muted);margin:0 0 4px}
.hero .need li{padding:6px 0}
.hero__market{border-left:1px solid var(--line);padding-left:28px;min-width:220px}
.hero__market p{margin:0}
.hero__price{font-size:34px;font-weight:600;letter-spacing:-.01em;line-height:1.1;margin:2px 0 8px!important}
.hero__price small{font-size:15px;font-weight:600;color:var(--muted);margin-right:8px;letter-spacing:0}
.hero__market .meta{font-size:13px}
@media (max-width:760px){.hero{grid-template-columns:1fr;padding:18px 16px}.hero__market{border-left:0;border-top:1px solid var(--line);padding:14px 0 0}}
.grid{container-type:inline-size;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.tile{display:grid;grid-template-columns:7rem 9.5rem minmax(0,1fr) 14rem;grid-template-areas:"state label body foot";gap:2px 16px;padding:11px 16px;border-top:1px solid var(--line);align-items:baseline;min-width:0}
.tile:first-child{border-top:0}
.tile.s-warn{background:var(--rowwarn)}.tile.s-fail{background:var(--rowfail)}
.tile__state{grid-area:state;font-size:13px;font-weight:600;display:flex;gap:7px;align-items:baseline;white-space:nowrap}
.tile__label{grid-area:label;font-size:14px;font-weight:600;color:var(--ink)}
.tile__body{grid-area:body;min-width:0}
.tile__value{font-size:17px;font-weight:600;color:var(--ink);overflow-wrap:anywhere;line-height:1.3}
.tile__value a{color:inherit;text-underline-offset:3px}
.tile__reason{font-size:14px;color:var(--ink);overflow-wrap:anywhere;margin-top:2px}
.tile.s-warn .tile__reason{color:var(--warn)}.tile.s-fail .tile__reason{color:var(--fail)}
.tile__detail{font-size:13px;color:var(--muted);overflow-wrap:anywhere;margin-top:2px}
.tile__foot{grid-area:foot;font-size:12.5px;color:var(--muted);overflow-wrap:anywhere;display:flex;flex-direction:column;gap:1px}
@container (max-width:640px){.tile{grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"label state" "body body" "foot foot";padding:11px 14px}.tile__foot{margin-top:4px}}
.cols{display:grid;grid-template-columns:minmax(0,1.75fr) minmax(0,1fr);gap:26px}
@media (max-width:900px){.cols{display:flex;flex-direction:column;gap:0}.cols>div{display:contents}.cols .first-on-phone{order:-1}}
.need{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:4px 16px}
.hero .need{background:none;border:0;padding:0;border-radius:0}
.need li{list-style:none;padding:9px 0;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:baseline}
.need li:last-child{border-bottom:0}.need ul{margin:0;padding:0}
.need b{white-space:nowrap;font-weight:600}.need li span,.note{overflow-wrap:anywhere;min-width:0}
.empty{color:var(--muted);padding:10px 0;margin:0}
.plans{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.plan{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 16px}
.plan h3{margin:0 0 6px;font-size:16px;font-weight:600}.plan ul{margin:0;padding-left:18px;font-size:14px}
.plan--long{border-top:4px solid var(--ok)}.plan--short{border-top:4px solid var(--fail)}
.plan--long h3{color:var(--ok)}.plan--short h3{color:var(--fail)}
.pages{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:0;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.page{padding:12px 16px;border-top:1px solid var(--line);margin-top:-1px;color:var(--ink)}
.page:hover{background:var(--bg);text-decoration:none}
.page b{display:block;margin-bottom:2px;color:var(--accent);font-weight:600}
.note{font-size:14px;color:var(--muted)}
.chartbox{--green:#35d39a;--red:#ff6577;--blue:#70a7ff;--yellow:#f2bd55;--cyan:#51c7d9;--text:#f1f5f9;--text-soft:#c5ced9;--muted:#8491a3;--line:#242e3c;background:#0a0f15;border:1px solid #242e3c;border-radius:10px;padding:6px;overflow:hidden}
.tc-svg{display:block;width:100%;height:auto}.tc-svg text{font:10.5px ui-monospace,SFMono-Regular,Menlo,monospace}
.tc-frame{fill:#0a0f15;stroke:var(--line)}.tc-grid{stroke:#18212d;stroke-width:1}.tc-axis{fill:#5d6a7c}
.tc-wick{stroke-width:1}.tc-up{stroke:var(--green);fill:var(--green)}.tc-down{stroke:var(--red);fill:var(--red)}.tc-body.tc-down{fill:var(--red)}.tc-body.tc-up{fill:#0a0f15;stroke-width:1.2}
.tc-value-area{fill:rgba(112,167,255,.06)}.tc-profile{fill:rgba(132,145,163,.22)}.tc-profile--va{fill:rgba(112,167,255,.32)}
.tc-va{stroke:var(--blue);stroke-width:1;stroke-dasharray:2 3}.tc-poc{stroke:var(--yellow);stroke-width:1.4}.tc-range{stroke:#6b7686;stroke-width:1;stroke-dasharray:1 4}
.tc-bos{stroke-width:1.2;stroke-dasharray:6 4}.tc-bos--up{stroke:var(--cyan)}.tc-bos--down{stroke:#c58cff}
.tc-last{stroke:#e2e8f0;stroke-width:1;stroke-dasharray:3 3}
.tc-zone{stroke-width:1.2}.tc-zone--long{fill:rgba(53,211,154,.16);stroke:var(--green)}.tc-zone--short{fill:rgba(255,101,119,.16);stroke:var(--red)}.tc-zone--neutral{fill:rgba(132,145,163,.12);stroke:var(--muted)}
.tc-zone-text{font-weight:700}.tc-zone-text--long{fill:var(--green)}.tc-zone-text--short{fill:var(--red)}.tc-zone-text--neutral{fill:var(--muted)}
.tc-trigger{stroke-width:1;stroke-dasharray:4 2}.tc-trigger--long{stroke:var(--green)}.tc-trigger--short{stroke:var(--red)}.tc-trigger--neutral{stroke:var(--muted)}
.tc-stop{stroke:var(--red);stroke-width:1.3;stroke-dasharray:7 4}.tc-target{stroke:var(--green);stroke-width:1.1;stroke-dasharray:7 4}
.tc-label{fill:var(--text-soft)}.tc-va-text{fill:var(--blue)}.tc-poc-text{fill:var(--yellow)}.tc-range-text{fill:#8491a3}.tc-bos-text{fill:var(--cyan)}.tc-last-text{fill:#fff;font-weight:700}.tc-stop-text{fill:var(--red)}.tc-target-text{fill:var(--green)}.tc-trigger-text{fill:var(--text-soft)}
.tc-edge{fill:var(--yellow);font-weight:700}
.tc-dir{font:700 11px ui-monospace,SFMono-Regular,Menlo,monospace}.tc-dir--long{color:var(--green)}.tc-dir--short{color:var(--red)}.tc-dir--neutral{color:var(--muted)}
.tc-svg .tc-plan-text,.tc-svg .tc-zone-text{font-weight:700;font-size:11px}.tc-invalid{stroke:var(--red);stroke-width:1.6}.tc-invalid-text{fill:var(--red)}
.tc-block{fill:rgba(242,189,85,.08);stroke:rgba(242,189,85,.35);stroke-dasharray:2 3}.tc-block-text{fill:var(--yellow)}
.tc-banner{fill:rgba(242,189,85,.12);stroke:var(--yellow)}.tc-banner-text{fill:var(--yellow);font-weight:700}
.tc-footer{fill:rgba(7,10,15,.85);stroke:var(--line)}.tc-footer-text{fill:var(--text-soft)}
.tc-svg .tc-plan-text,.tc-svg .tc-zone-text,.tc-svg .tc-block-text,.tc-svg .tc-edge{paint-order:stroke;stroke:#0a0f15;stroke-width:4px;stroke-linejoin:round}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 10px}.tabs a{padding:6px 14px;border:1px solid var(--line);border-radius:8px;color:var(--muted);font-weight:600;font-size:14px;background:var(--panel)}
.tabs a[aria-current=page]{color:var(--panel);background:var(--ink);border-color:var(--ink)}
.tbl{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:14px}
.tbl th,.tbl td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
.tbl th{white-space:nowrap;font-size:13px;color:var(--muted);font-weight:600;background:var(--bg)}
.tbl tr:last-child td{border-bottom:0}.tbl .num{white-space:nowrap}
.tbl .cur td{background:var(--unknownbg);font-weight:600}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}.scroll>.tbl{min-width:600px}.scroll .tbl td{overflow-wrap:normal}
@media (max-width:700px){.chartbox{overflow-x:auto;-webkit-overflow-scrolling:touch}.chartbox .tc-svg{min-width:820px}}
.dir-long{color:var(--ok);font-weight:600}.dir-short{color:var(--fail);font-weight:600}
.box{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 16px;overflow-wrap:anywhere}
.grid+.box,.box+.note,.grid+.scroll{margin-top:12px}main>.need{margin-bottom:20px}
.events{overflow-wrap:anywhere}.box p{margin:0 0 6px}.box p:last-child{margin:0}
.now li{display:grid;grid-template-columns:160px 1fr;gap:4px 16px}
@media (max-width:560px){.now li{grid-template-columns:1fr}}
.sub{font-size:15px;font-weight:600;margin:16px 0 6px;color:var(--ink)}
.events{margin:6px 0 0;padding-left:18px;font-size:14px}.events li{margin:0 0 3px}
footer{max-width:1280px;margin:0 auto;padding:0 16px 30px;color:var(--muted);font-size:13px}
@media (max-width:700px){.nav{order:3;flex-basis:100%;flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch}.nav a{white-space:nowrap}.nav a.old{margin-left:0}.live{margin-left:auto}}
@media (max-width:560px){.head h1{font-size:22px}}
@media (max-width:700px){.tabs a{padding:11px 16px}}
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
    try:
        local = moment.astimezone(LOCAL)
    except (OverflowError, OSError, ValueError):
        return "—"
    return local.strftime("%d.%m. %H:%M") if with_date else local.strftime("%H:%M")


def _tile(tile: dict[str, Any]) -> str:
    """One status row: state, label, value with reason, then as-of time and source."""
    state = tile.get("state") or "unknown"
    info = (tile.get("extra") or {}).get("kind") == "info"
    label = "" if info and state == "ok" else ((tile.get("extra") or {}).get("state_label") or STATE_LABELS.get(state, state))
    value = _e(tile.get("value"))
    if tile.get("href"):
        value = f"<a href='{_e(tile['href'])}'>{value}</a>"
    extra = tile.get("extra") or {}
    detail = tile.get("detail") or ""
    if extra.get("start"):
        detail = f"{local_time(extra['start'], True)}–{local_time(extra.get('end'))} Uhr" + (f", {detail}" if detail else "")
    as_of = tile.get("as_of")
    stamp = ""
    if as_of:
        stamp = (f"<span>Stand {local_time(as_of, True)}, <time data-asof='{_e(as_of)}'>{_e(human_age(tile.get('age_seconds')))}</time></span>")
    return (
        f"<article class='tile s-{_e(state)}{' k-info' if info else ''}{' k-parked' if (tile.get('extra') or {}).get('kind') == 'parked' else ''}' id='t-{_e(tile.get('id'))}'>"
        f"<span class='tile__state'>{_e(label)}</span>"
        f"<span class='tile__label'>{_e(tile.get('label'))}</span>"
        f"<div class='tile__body'><div class='tile__value'>{value}</div>"
        + (f"<div class='tile__reason'>{_e(tile.get('reason'))}</div>" if tile.get("reason") and state != "ok" else "")
        + (f"<div class='tile__detail'>{_e(detail)}</div>" if detail else "")
        + f"</div><div class='tile__foot'>{stamp}<span title='Quelle'>{_e(tile.get('source'))}</span></div></article>"
    )


def _headline(model: dict[str, Any]) -> str:
    """The headline as a plain sentence (singular and plural spelled out)."""
    text = str(model.get("headline") or "")
    needs = model.get("attention") or []
    if text.endswith("Punkt(e) brauchen einen Blick"):
        return "Ein Punkt braucht einen Blick" if len(needs) == 1 else f"{len(needs)} Punkte brauchen einen Blick"
    return text


def _by_id(tiles: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return next((t for t in tiles if t.get("id") == key), {})


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
    market = model.get("market") or []
    price, market_state, setup = _by_id(market, "price"), _by_id(market, "market_state"), _by_id(market, "setup")
    hero_market = (
        "<div class='hero__market'><p class='meta'>BTCUSDT</p>"
        f"<p class='hero__price'>{_e(price.get('value') or '—')}</p>"
        f"<p>Markt {_e(market_state.get('value') or '—')}</p><p>Setup {_e(setup.get('value') or '—')}</p>"
        + (f"<p class='meta'>Stand <time data-asof='{_e(price['as_of'])}'>{_e(human_age(price.get('age_seconds')))}</time></p>" if price.get("as_of") else "")
        + "</div>"
    )
    return (
        f"<div class='head'><h1>Lage</h1>"
        f"<span class='meta'>Stand {local_time(model.get('generated_at'), True)} Uhr. {_e(model.get('safety'))}</span></div>"
        f"<div class='hero s-{_e(overall)}'><div><p class='hero__line'>{_e(_headline(model))}</p>"
        f"<section aria-labelledby='h-need'><h2 id='h-need'>Braucht dich</h2><div class='need'>{need_html}</div></section></div>"
        f"{hero_market}</div>"
        f"<div class='cols'><div>"
        f"<section aria-labelledby='h-system'><h2 id='h-system'>System</h2>{_grid(model.get('system') or [])}</section>"
        f"<section aria-labelledby='h-market'><h2 id='h-market'>Markt jetzt</h2>{_grid(market)}</section>"
        f"<section aria-labelledby='h-plans'><h2 id='h-plans'>TIMs Pläne jetzt</h2>{plan_html}"
        "<p class='note'>Stop und Ziele sind eine Vorschau nach TIMs Regeln, keine Order und keine Anlageberatung.</p></section>"
        f"</div><div>"
        f"<section aria-labelledby='h-mac'><h2 id='h-mac'><a href='/neu/mac'>Mac jetzt</a></h2>{_grid(model.get('mac') or [])}</section>"
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


def _price(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{value:+.2f} %".replace(".", ",")


def _rtext(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{value:+.2f} R".replace(".", ",")


def _dir(direction: Any) -> str:
    text = str(direction or "")
    css = {"LONG": "dir-long", "SHORT": "dir-short"}.get(text.upper(), "")
    return f"<span class='{css}'>{_e(text or '—')}</span>"


def _more_pages(key: str) -> str:
    pages = "".join(
        f"<a class='page' href='{_e(href)}'><b>{_e(label)}</b><span class='note'>{_e(text)}</span></a>"
        for label, href, text in AREA_BY_KEY[key].get("pages") or []
    )
    return f"<section aria-labelledby='h-more'><h2 id='h-more'>Weitere Seiten</h2><div class='pages'>{pages}</div></section>" if pages else ""


def _head(title: str, model: dict[str, Any], pill_state: str | None = None, pill_text: str | None = None) -> str:
    pill = f"<span class='pill s-{_e(pill_state)}'>{_e(pill_text)}</span>" if pill_state and pill_text else ""
    return (f"<div class='head'><h1>{_e(title)}</h1>{pill}"
            f"<span class='meta'>Stand {local_time(model.get('generated_at'), True)} Uhr. {_e(model.get('safety'))}</span></div>")


EXIT_WORDS = {"STOP": "Stop", "BREAK_EVEN": "Break-even", "TP3": "TP3", "TIMEOUT": "Zeitablauf", "INVALIDATION": "ungültig"}
STATUS_WORDS = {"OPEN": "wartet", "FILLED": "im Trade", "CLOSED": "geschlossen", "INVALIDATED": "ungültig", "EXPIRED": "abgelaufen",
                "REPLACED": "ersetzt", "NO_TRADE": "kein Trade"}


def markt_body(model: dict[str, Any]) -> str:
    """The refreshable part of "Markt & Pläne"."""
    chart = model.get("chart") or {}
    tf = chart.get("timeframe") or model.get("timeframe") or "15m"
    tabs = "".join(
        f"<a href='/neu/markt?tf={_e(item)}'{' aria-current=page' if item == tf else ''}>{_e(item)}</a>" for item in model.get("timeframes") or []
    )
    decision = chart.get("decision")
    if chart.get("svg"):
        chart_html = (f"<div class='chartbox'>{chart['svg']}</div>"
                      f"<p class='note'>BTCUSDT {_e(tf)} · {_e(chart.get('candles'))} Kerzen · Entscheidung der Pipeline: {_e(decision)}"
                      + (f" ({_e(', '.join(chart.get('decision_reasons') or []))})" if chart.get("decision_reasons") else "")
                      + ". Grün/Rot: Einstiegszonen, gelb: Sperrzeit um die NY-Eröffnung. Zeiten im Chart in UTC. "
                      f"<a href='/chart?tf={_e(tf)}'>Großer Chart</a></p>"
                      + "".join(f"<p class='note'>{_e(n)}</p>" for n in chart.get("notes") or []))
    else:
        chart_html = f"<p class='empty'>{_e(chart.get('note') or 'Kein Chart verfügbar.')}</p>"
    plans = model.get("plans") or []
    plan_html = (
        "<div class='plans'>" + "".join(
            f"<article class='plan plan--{_e(p.get('direction', '').lower())}'><h3>{_e(p.get('title'))}</h3><ul>"
            + "".join(f"<li>{_e(line)}</li>" for line in p.get("lines") or []) + "</ul></article>"
            for p in plans) + "</div>"
        if plans else "<p class='empty'>Kein Plan mit Einstiegszone: Der Kurs steht nicht an einer Range-Kante.</p>"
    )

    prep = model.get("prep") or {}
    if prep.get("ok"):
        level_rows = "".join(f"<tr><td>{_e(l['label'])}</td><td class='num'>{_price(l['price'])}</td><td class='num'>{_pct(l.get('distance_pct'))}</td></tr>"
                             for l in prep.get("above") or [])
        level_rows += f"<tr class='cur'><td>Kurs</td><td class='num'>{_price(prep.get('last'))}</td><td class='num'>{_e(local_time(prep.get('last_time')))} Uhr</td></tr>"
        level_rows += "".join(f"<tr><td>{_e(l['label'])}</td><td class='num'>{_price(l['price'])}</td><td class='num'>{_pct(l.get('distance_pct'))}</td></tr>"
                              for l in prep.get("below") or [])
        htf = " · ".join(f"{h['label']} {h['state']}" for h in prep.get("htf") or [])
        sessions = "".join(
            f"<tr><td>{_e(x['name'])}</td><td class='num'>{local_time(x.get('start'))}–{local_time(x.get('end'))}</td>"
            f"<td class='num'>{_price(x.get('high'))}</td><td class='num'>{_price(x.get('low'))}</td><td>{'läuft' if x.get('running') else 'vorbei'}</td></tr>"
            for x in prep.get("sessions") or []
        ) or "<tr><td colspan='5' class='empty'>Noch keine Session mit Kerzen.</td></tr>"
        prep_html = (
            f"<div class='box'><p><b>Bias {_e(prep.get('bias'))}</b>: {_e(prep.get('bias_text'))}</p>"
            f"<p>{_e(prep.get('location'))}" + (f": {_e(prep.get('location_hint'))}" if prep.get("location_hint") else "") + "</p>"
            + (f"<p class='note'>Struktur {_e(htf)}</p>" if htf else "") + "</div>"
            f"<h3 class='sub'>Nächste Level ({len(prep.get('above') or []) + len(prep.get('below') or [])} von {_e(prep.get('levels_total'))})</h3>"
            f"<div class='scroll'><table class='tbl'><thead><tr><th>Level</th><th>Preis</th><th>Abstand</th></tr></thead><tbody>{level_rows}</tbody></table></div>"
            f"<h3 class='sub'>Sessions</h3><div class='scroll'><table class='tbl'><thead><tr><th>Session</th><th>Zeit</th><th>Hoch</th><th>Tief</th><th></th></tr></thead>"
            f"<tbody>{sessions}</tbody></table></div>"
            + "".join(f"<p class='note'>{_e(n)}</p>" for n in prep.get("notes") or [])
            + "<p class='note'><a href='/prep'>Volle Vorbereitung</a></p>"
        )
    else:
        prep_html = f"<p class='empty'>{_e(prep.get('note') or 'Keine Vorbereitung verfügbar.')}</p>"

    pj = model.get("plan_journal") or {}

    def plan_row(e: dict[str, Any], finished: bool) -> str:
        targets = " · ".join(_price(t) for t in e.get("targets") or []) or "—"
        when = local_time(e.get("closed_at") if finished else e.get("created_at"), True)
        result = (f"{_rtext(e.get('net_r'))} netto" + (f" · {EXIT_WORDS.get(e.get('exit_reason'), e.get('exit_reason'))}" if e.get("exit_reason") else "")
                  if finished else (f"seit {local_time(e.get('filled_at'), True)}" if e.get("filled_at") else "wartet auf Einstieg"))
        return (f"<tr><td class='num'>{_e(when)}</td><td>{_dir(e.get('direction'))} {_e(e.get('scenario'))}</td>"
                f"<td>{_e(STATUS_WORDS.get(e.get('status'), e.get('status')))}</td><td class='num'>{_price(e.get('entry'))}</td>"
                f"<td class='num'>{_price(e.get('stop'))}</td><td class='num'>{_e(targets)}</td><td>{_e(result)}</td></tr>")

    head = "<thead><tr><th>Zeit</th><th>Plan</th><th>Status</th><th>Einstieg</th><th>Stop</th><th>Ziele</th><th>Ergebnis</th></tr></thead>"
    if pj.get("integrity", "").startswith("LOG_BROKEN"):
        pj_html = f"<p class='empty s-fail'>Plan-Journal gesperrt: Ereignislog beschädigt ({_e(pj['integrity'][:160])}).</p>"
    elif pj.get("note"):
        pj_html = f"<p class='empty'>{_e(pj['note'])}</p>"
    else:
        active = "".join(plan_row(e, False) for e in pj.get("active") or []) or "<tr><td colspan='7' class='empty'>Kein Plan offen.</td></tr>"
        closed = "".join(plan_row(e, True) for e in pj.get("closed") or []) or "<tr><td colspan='7' class='empty'>Noch nichts geschlossen.</td></tr>"
        stats = pj.get("summary") or {}
        rate = stats.get("win_rate")
        pj_html = (
            f"<p class='note'>{_e(stats.get('plans', 0))} Pläne · {_e(stats.get('closed', 0))} geschlossen · Trefferquote "
            f"{_e(f'{rate * 100:.0f} %' if isinstance(rate, (int, float)) else '—')} · netto {_e(_rtext(stats.get('sum_net_r')))} · nur Papier</p>"
            f"<h3 class='sub'>Offen</h3><div class='scroll'><table class='tbl'>{head}<tbody>{active}</tbody></table></div>"
            f"<h3 class='sub'>Zuletzt geschlossen</h3><div class='scroll'><table class='tbl'>{head}<tbody>{closed}</tbody></table></div>"
            "<p class='note'><a href='/journal'>Ganzes Plan-Journal</a> · <a href='/journal/struct'>Struktur-Regel</a></p>"
        )

    tj = model.get("trader_journal") or {}
    if tj.get("note"):
        tj_html = f"<p class='empty'>{_e(tj['note'])}</p>"
    elif not tj.get("rows"):
        tj_html = "<p class='empty'>Noch kein eigener Papier-Trade. <a href='/trader-journal'>Ersten Trade eintragen</a></p>"
    else:
        rows = "".join(
            f"<tr><td class='num'>{local_time(r.get('created_at'), True)}</td><td>{_dir(r.get('direction'))} {_e(r.get('id'))}</td>"
            f"<td>{_e(STATUS_WORDS.get(r.get('status'), r.get('status')))}</td><td class='num'>{_price(r.get('entry'))}</td>"
            f"<td class='num'>{_price(r.get('stop'))}</td><td class='num'>{_price(r.get('target'))}</td><td class='num'>{_e(_rtext(r.get('result_r')))}</td>"
            f"<td>{'ja' if r.get('review') else 'offen'}</td></tr>"
            for r in tj["rows"]
        )
        stats = tj.get("summary") or {}
        tj_html = (
            f"<p class='note'>{_e(stats.get('trades', 0))} Trades · {_e(stats.get('no_trades', 0))} bewusst nicht gehandelt · Summe {_e(_rtext(stats.get('sum_r')))} · "
            f"{_e(stats.get('review_open', 0))} Review(s) offen · nur Papier</p>"
            "<div class='scroll'><table class='tbl'><thead><tr><th>Zeit</th><th>Trade</th><th>Status</th><th>Einstieg</th><th>Stop</th><th>Ziel</th><th>Ergebnis</th><th>Review</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div><p class='note'><a href='/trader-journal'>Trade eintragen oder reviewen</a></p>"
        )
    slow = [f"{name} ({info.get('error')})" for name, info in (model.get("sources") or {}).items() if not info.get("ok") or info.get("stale_seconds") is not None]
    return (
        _head("Markt & Pläne", model, "warn" if chart.get("svg") and decision not in {None, "UNAVAILABLE", "NO_TRADE"} else "unknown",
              f"Pipeline: {decision or 'keine Analyse'}")
        + f"<section aria-labelledby='h-mkt'><h2 id='h-mkt'>Markt jetzt</h2>{_grid(model.get('market') or [])}</section>"
        + f"<section aria-labelledby='h-chart'><h2 id='h-chart'>TIM-Chart</h2><nav class='tabs' aria-label='Zeitrahmen'>{tabs}</nav>{chart_html}</section>"
        + "<div class='cols'><div>"
        + f"<section aria-labelledby='h-plans'><h2 id='h-plans'>TIMs Pläne jetzt (15m)</h2>{plan_html}"
        + "<p class='note'>Stop und Ziele sind eine Vorschau nach TIMs Regeln für unbestätigte Szenarien, keine Order und keine Anlageberatung. "
        + "Rund um die NY-Eröffnung (15 min davor bis 30 min danach) keine neuen Einstiege.</p></section>"
        + f"<section aria-labelledby='h-pj'><h2 id='h-pj'>Plan-Journal</h2>{pj_html}</section>"
        + f"<section aria-labelledby='h-tj'><h2 id='h-tj'>Trader-Journal</h2>{tj_html}</section>"
        + "</div><div>"
        + f"<section aria-labelledby='h-prep'><h2 id='h-prep'>Vorbereitung</h2>{prep_html}</section>"
        + f"<section aria-labelledby='h-journal'><h2 id='h-journal'>Journale</h2>{_grid(model.get('journals') or [])}</section>"
        + (f"<p class='note'>Langsame oder fehlende Quellen: {_e('; '.join(slow))}</p>" if slow else "")
        + "</div></div>" + _more_pages("markt")
    )


def mac_body(model: dict[str, Any]) -> str:
    """The refreshable part of "Mac jetzt"."""
    now_rows = "".join(
        f"<li><b>{_e(line.get('label'))}</b><span><span class='s-{_e(line.get('state'))}'>{_e(line.get('value'))}</span>"
        + (f" · {_e(line.get('detail'))}" if line.get("detail") else "")
        + (f" · <time data-asof='{_e(line['as_of'])}'>{_e(human_age(line.get('age_seconds')))}</time>" if line.get("as_of") else "")
        + "</span></li>"
        for line in model.get("now") or []
    ) or "<li><span>Keine Angaben.</span></li>"
    details = model.get("worker_details") or {}
    worker_extra = []
    current = details.get("current")
    if current:
        title = _e(current.get("title"))
        link = f"<a href='{_e(current['url'])}'>#{_e(current.get('issue'))}</a>" if current.get("url") else f"#{_e(current.get('issue'))}"
        events = "".join(
            f"<li>{_e(local_time(ev.get('at')))} · {_e(ev.get('phase'))}" + (f" ({_e(ev.get('place'))})" if ev.get("place") else "")
            + (f": {_e(ev.get('detail'))}" if ev.get("detail") else "") + "</li>"
            for ev in current.get("events") or []
        )
        worker_extra.append(f"<div class='box'><p><b>Arbeitet an {link}</b> {title}</p>" + (f"<ul class='events'>{events}</ul>" if events else "") + "</div>")
    if details.get("last_intake"):
        worker_extra.append(f"<p class='note'>Letzte Prüfung: {_e(details['last_intake'])}</p>")
    if details.get("last_triage"):
        worker_extra.append(f"<p class='note'>Letzte Triage: {_e(details['last_triage'])}</p>")
    stalled = [n for n in details.get("stalled") or [] if n is not None]
    if stalled:
        worker_extra.append(f"<p class='note'>Frühere Läufe ohne PR: {_e(', '.join('#' + str(n) for n in stalled))} (Verlauf, kein laufender Auftrag)</p>")
    error = details.get("last_error")
    if error and not error.get("recent"):
        worker_extra.append(f"<p class='note'>Letzter Fehler ({_e(error.get('age'))}, erledigt): {_e(error.get('text'))}</p>")
    open_rows = "".join(
        f"<tr><td class='num'>" + (f"<a href='{_e(o['url'])}'>#{_e(o.get('number'))}</a>" if o.get("url") else f"#{_e(o.get('number'))}") + "</td>"
        f"<td>{_e(o.get('title'))}</td><td>{'bereit' if o.get('eligible') else _e(o.get('stage') or 'wartet')}</td><td>{_e(o.get('waiting'))}</td></tr>"
        for o in details.get("open") or []
    )
    done_rows = "".join(
        f"<tr><td class='num'>#{_e(d.get('issue'))}</td><td>{_e(d.get('title'))}</td>"
        f"<td class='num'>" + (f"<a href='{_e(d['url'])}'>PR #{_e(d.get('pr'))}</a>" if d.get("url") else (f"PR #{_e(d.get('pr'))}" if d.get("pr") else "—")) + "</td>"
        f"<td>{_e(d.get('state'))}</td><td class='num'>{local_time(d.get('at'), True)}</td><td>{_e(', '.join(d.get('helpers') or []))}</td></tr>"
        for d in details.get("done") or []
    )
    lists = ""
    if details.get("reachable"):
        lists = (
            f"<h3 class='sub'>Offene Issues ({_e(details.get('open_total', 0))}, bereite zuerst)</h3>"
            + (f"<div class='scroll'><table class='tbl'><thead><tr><th>Issue</th><th>Titel</th><th>Stand</th><th>Warum nicht jetzt</th></tr></thead><tbody>{open_rows}</tbody></table></div>"
               if open_rows else "<p class='empty'>Keine offenen Issues für den Worker.</p>")
            + "<h3 class='sub'>Zuletzt erledigt</h3>"
            + (f"<div class='scroll'><table class='tbl'><thead><tr><th>Issue</th><th>Titel</th><th>PR</th><th>Stand</th><th>Zeit</th><th>Helfer</th></tr></thead><tbody>{done_rows}</tbody></table></div>"
               if done_rows else "<p class='empty'>Noch nichts erledigt.</p>")
        )
    return (
        _head("Mac jetzt", model, model.get("overall") or "unknown", _headline(model))
        + f"<section aria-labelledby='h-now'><h2 id='h-now'>Gerade jetzt</h2><div class='need now'><ul>{now_rows}</ul></div></section>"
        + f"<section id='worker' aria-labelledby='h-worker'><h2 id='h-worker'>Issue-Worker</h2>{_grid(model.get('worker') or [])}"
        + "".join(worker_extra) + lists
        + "<p class='note'><a href='http://127.0.0.1:8767/'>Volles Worker-Dashboard</a> (Link funktioniert nur direkt am Mac)</p></section>"
        + f"<section id='dienste' aria-labelledby='h-svc'><h2 id='h-svc'>Dienste im Hintergrund</h2>{_grid(model.get('services') or [])}"
        + "<p class='note'>Jede Kachel zeigt das letzte Lebenszeichen des Dienstes aus seiner Statusdatei. Ist es älter als sein Takt erlaubt, wird die Kachel gelb.</p></section>"
        + _more_pages("mac")
    )


def _table(table: Any) -> str:
    """A small table of cells ({text, href}); links stay inside this dashboard."""
    if not isinstance(table, dict) or not table.get("rows"):
        return ""
    head = "".join(f"<th>{_e(h)}</th>" for h in table.get("head") or [])

    def cell(c: Any) -> str:
        if not isinstance(c, dict):
            return f"<td>{_e(c)}</td>"
        href = str(c.get("href") or "")
        text = _e(c.get("text"))
        if href.startswith("/") and not href.startswith("//") and "\\" not in href:
            text = f"<a href='{_e(href)}'>{text}</a>"
        return f"<td>{text}</td>"

    rows = "".join("<tr>" + "".join(cell(c) for c in row) + "</tr>" for row in table["rows"] if isinstance(row, list))
    return f"<div class='scroll'><table class='tbl'><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>"


def sections_body(model: dict[str, Any]) -> str:
    """The refreshable part of Forschung, Betrieb and System & Freigabe."""
    key = str(model.get("area") or "")
    parked = model.get("parked") or 0
    out = [_head(AREA_BY_KEY[key]["label"] if key in AREA_BY_KEY else str(model.get("title") or ""), model,
                 model.get("overall") or "unknown", _headline(model))]
    needs = model.get("attention") or []
    if needs:
        out.append("<div class='need'><ul>" + "".join(
            f"<li><b class='s-{_e(t.get('state'))}'>{_e(STATE_LABELS.get(t.get('state'), t.get('state')))}</b>"
            f"<span><a href='#t-{_e(t.get('id'))}'>{_e(t.get('label'))}</a>: {_e(t.get('reason'))}</span></li>"
            for t in needs) + "</ul></div>")
    if parked:
        out.append(f"<p class='note'>{_e(parked)} {'Punkt wartet' if parked == 1 else 'Punkte warten'} bewusst auf einen Menschen "
                   "oder gelten gerade nicht (grau mit eigenem Wort). Das ist kein Fehler.</p>")
    for section in model.get("sections") or []:
        if not isinstance(section, dict):
            continue
        sid = _e(section.get("id"))
        tiles = [t for t in section.get("tiles") or [] if isinstance(t, dict)]
        table = _table(section.get("table"))
        body = (_grid(tiles) if tiles else "") + table
        if not table and section.get("empty"):
            body += f"<p class='empty'>{_e(section['empty'])}</p>"
        if section.get("note"):
            body += f"<p class='note'>{_e(section['note'])}</p>"
        out.append(f"<section id='{sid}' aria-labelledby='h-{sid}'><h2 id='h-{sid}'>{_e(section.get('title'))}</h2>{body}</section>")
    slow = [f"{name} ({info.get('error') or ('letzter Stand von vor ' + str(info.get('stale_seconds')) + ' s' if info.get('stale_seconds') is not None else 'keine Antwort')})"
            for name, info in (model.get("sources") or {}).items()
            if isinstance(info, dict) and (not info.get("ok") or info.get("stale_seconds") is not None)]
    if slow:
        out.append(f"<p class='note'>Langsame oder fehlende Quellen: {_e('; '.join(slow))}</p>")
    if key in AREA_BY_KEY:
        out.append(_more_pages(key))
    return "".join(out)


def render_sections(model: dict[str, Any]) -> str:
    key = str(model.get("area") or "")
    return page(AREA_BY_KEY[key]["label"], key, sections_body(model), refresh=True)


def page(title: str, active: str, body: str, refresh: bool, fragment: str | None = None) -> str:
    nav = "".join(
        f"<a href='{_e(a['href'])}'{' aria-current=page' if a['key'] == active else ''}>{_e(a['label'])}</a>" for a in AREAS
    ) + "<a class='old' href='/'>Bisheriges Dashboard</a>"
    fragment = fragment or AREA_BY_KEY[active]["href"] + "?fragment=1"
    return (
        "<!doctype html><html lang='de'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'><meta name='color-scheme' content='light dark'>"
        f"<title>{_e(title)} · TIM</title><style>{STYLE}</style></head><body>"
        f"<header class='top'><div class='top__in'><a class='brand' href='/neu'>TIM<small>Control Center</small></a>"
        f"<nav class='nav' aria-label='Bereiche'>{nav}</nav>"
        f"<span id='live' class='live' aria-live='polite'>{'● Live, alle ' + str(REFRESH_SECONDS) + ' s' if refresh else ''}</span></div></header>"
        f"<main id='cockpit' data-fragment='{_e(fragment)}'>{body}</main>"
        "<footer>TIM beobachtet nur und handelt auf Papier: keine Orders, keine Shell- oder Git-Aktionen. Alle Zeiten in deutscher Ortszeit.</footer>"
        + (f"<script>{SCRIPT}</script>" if refresh else "")
        + "</body></html>"
    )


def render_lage(model: dict[str, Any]) -> str:
    return page("Lage", "lage", lage_body(model), refresh=True)


def render_area(key: str) -> str:
    return page(AREA_BY_KEY[key]["label"], key, area_body(key), refresh=False)


def render_markt(model: dict[str, Any]) -> str:
    tf = model.get("timeframe") or "15m"
    return page("Markt & Pläne", "markt", markt_body(model), refresh=True, fragment=f"/neu/markt?tf={tf}&fragment=1")


def render_mac(model: dict[str, Any]) -> str:
    return page("Mac jetzt", "mac", mac_body(model), refresh=True)
