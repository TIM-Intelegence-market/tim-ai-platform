"""The four screens of the new Control Center (31.10.2026): Cockpit, Journal, Forschung, System.

Each screen is one page without sub-pages. Display only: every value comes from
what TIM already writes (state, candles, paper journals, notes, research
logbook, status files). Nothing here computes a new signal or writes a file.
The older detail pages stay linked from each screen.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.dashboard.cockpit.page import REFRESH_SECONDS, SCRIPT, STYLE, local_time
from src.dashboard.shell import frame

SCREEN_CSS = """
main:has(>#cockpit>.scr){max-width:none;padding:0}
.scr{max-width:1440px;margin:0 auto;padding:20px 24px 30px;display:grid;gap:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px;min-width:0}
.card>h2{display:flex;justify-content:space-between;gap:10px;margin:0 0 10px;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.card>h2 a{color:var(--muted);text-transform:none;letter-spacing:0;font-weight:600}
.lead{display:flex;gap:16px;align-items:flex-start}
.lead__dot{width:14px;height:14px;border-radius:50%;flex:none;margin-top:9px;background:var(--unknown)}
.lead__dot[data-s=ok]{background:var(--ok)}.lead__dot[data-s=warn]{background:var(--warn)}.lead__dot[data-s=fail]{background:var(--fail)}
.lead h1{margin:0;font-size:clamp(21px,2.4vw,27px);line-height:1.25;font-weight:700;letter-spacing:-.01em}
.lead p{margin:4px 0 0;color:var(--muted)}
.lead ul{margin:10px 0 0;padding:0;list-style:none}.lead li{padding:3px 0}
.lead li b{color:var(--fail);margin-right:8px}.lead li.w b{color:var(--warn)}
.two{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(0,1fr);gap:16px;align-items:start}
.stack{display:grid;gap:16px;min-width:0}
.row{display:flex;justify-content:space-between;align-items:baseline;gap:12px;padding:9px 0;border-top:1px solid var(--line)}
.row:first-of-type{border-top:0}.row>span:last-child{text-align:right}
.mut{color:var(--muted)}.sm{font-size:12.5px}
.tag{display:inline-block;font-size:11.5px;font-weight:600;padding:2px 8px;border-radius:6px;background:var(--unknownbg);color:var(--muted);margin-right:6px;white-space:nowrap}
.tag.l{color:var(--ok);background:var(--okbg)}.tag.s{color:var(--fail);background:var(--failbg)}.tag.w{color:var(--warn);background:var(--warnbg)}
.up{color:var(--ok)}.dn{color:var(--fail)}.warnc{color:var(--warn)}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.kpi b{display:block;font-size:26px;font-weight:700;line-height:1.2;margin:2px 0}
.kpi3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.kpi3 b{display:block;font-size:20px;font-weight:700}
.chart-card .chartbox{border:0;padding:0;background:#0a0f15}
.chart-card .tc-svg{min-width:0}
.chart-empty{padding:60px 16px;text-align:center;color:var(--muted)}
.tbl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
.trades{width:100%;border-collapse:collapse;font-size:14px;font-variant-numeric:tabular-nums}
.trades th{font-size:12px;font-weight:500;color:var(--muted);text-align:left;padding:6px 8px}
.trades td{padding:9px 8px;border-top:1px solid var(--line);vertical-align:top}
.lights{list-style:none;margin:0;padding:0}
.lights>li{border-top:1px solid var(--line)}.lights>li:first-child{border-top:0}
.lights details>summary,.lights .ok-row{display:grid;grid-template-columns:18px minmax(0,1fr) auto;gap:10px;align-items:baseline;padding:10px 0;list-style:none;cursor:pointer}
.lights .ok-row{cursor:default}
.lights summary::-webkit-details-marker{display:none}
.lights .dot{width:9px;height:9px;border-radius:50%;background:var(--unknown);display:inline-block}
.lights .dot[data-s=ok]{background:var(--ok)}.lights .dot[data-s=warn]{background:var(--warn)}.lights .dot[data-s=fail]{background:var(--fail)}
.lights .why{margin:0 0 12px 28px;padding:10px 12px;border-radius:10px;background:var(--unknownbg);font-size:14px}
.lights .why p{margin:0 0 4px}
.nw{white-space:nowrap}
.links{display:flex;flex-wrap:wrap;gap:6px 18px}.links a{font-weight:600}
.study{display:grid;grid-template-columns:4.2rem minmax(0,1fr) auto;gap:4px 12px;padding:10px 0;border-top:1px solid var(--line);align-items:baseline}
.study:first-of-type{border-top:0}.study b{font-weight:700}.study p{margin:2px 0 0;color:var(--muted);font-size:13.5px}
@media (max-width:980px){.two{grid-template-columns:1fr}}
@media (max-width:700px){.scr{padding:14px}.kpis{grid-template-columns:1fr 1fr}.study{grid-template-columns:3.4rem minmax(0,1fr)}.study>span:last-child{grid-column:2}}
"""

CSS = STYLE + SCREEN_CSS


def _hash(block: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(block.encode()).digest()).decode() + "'"


SCREEN_CSP = (
    "default-src 'none'; "
    f"style-src {_hash(CSS)}; "
    f"script-src {_hash(SCRIPT)}; "
    "connect-src 'self'; img-src 'self' data:; font-src 'none'; "
    "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

RULES = (("tim", "TIM-Regel", "tim/1"), ("struct", "Struktur", "struct/1"))
STATE_WORDS = {"ok": "OK", "warn": "prüfen", "fail": "Fehler", "unknown": "keine Daten"}


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value == value else None


def _r(value: Any, sign: bool = True) -> str:
    number = _num(value)
    if number is None:
        return "—"
    return (f"{number:+.2f} R" if sign else f"{number:.2f} R").replace(".", ",").replace("-", "−")


def _rcls(value: Any) -> str:
    number = _num(value)
    return "" if number is None or number == 0 else ("up" if number > 0 else "dn")


def _price(value: Any) -> str:
    number = _num(value)
    return "—" if number is None else f"{number:,.0f}".replace(",", ".")


def _dir(direction: Any) -> str:
    word = str(direction or "").upper()
    return {"LONG": "<span class='tag l'>Long</span>", "SHORT": "<span class='tag s'>Short</span>"}.get(word, f"<span class='tag'>{_e(word or '—')}</span>")


def _page(title: str, path: str, body: str) -> str:
    live = f"<span id='live' class='live' aria-live='polite'>● Live, alle {REFRESH_SECONDS} s</span>"
    inner = frame(path, f"<div id='cockpit' data-fragment='{_e(path)}?fragment=1'>{body}</div>", live=live)
    return ("<!doctype html><html lang='de'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'><meta name='color-scheme' content='dark'>"
            f"<title>{_e(title)} · TIM</title><style>{CSS}</style></head><body class='ncc'>{inner}"
            f"<script>{SCRIPT}</script></body></html>")


def _safe(build: Callable[[], str], what: str) -> str:
    try:
        return build()
    except Exception as exc:  # noqa: BLE001 - one broken block must not take the screen down
        return f"<div class='card'><h2>{_e(what)}</h2><p class='mut'>Nicht lesbar: {_e(type(exc).__name__)}: {_e(str(exc)[:160])}</p></div>"


# --- shared data -------------------------------------------------------------------

def journals(state: Any) -> dict[str, Any]:
    """TIM's active paper rules (TIM, Struktur) with entries, summary and the newest notes."""
    from src.dashboard import plan_notes
    from src.dashboard.plan_journal import load_view, summary

    notes = plan_notes.latest(plan_notes.load(state.plan_notes_path))
    paths = {"tim": state.plan_journal_path, "struct": state.plan_journal_struct_path}
    out: dict[str, Any] = {"notes": notes, "rules": []}
    for key, label, rule in RULES:
        view = load_view(paths[key])
        entries = [e for e in view.get("entries") or [] if isinstance(e, dict) and not e.get("excluded")]
        missing = {str(e.get("id")) for e in plan_notes.missing(entries, rule, notes)}
        out["rules"].append({"key": key, "label": label, "rule": rule, "entries": entries, "summary": summary(view),
                             "missing": missing, "integrity": str(view.get("integrity") or "")})
    return out


def _totals(data: dict[str, Any]) -> dict[str, Any]:
    closed = [e for r in data["rules"] for e in r["entries"] if e.get("status") == "CLOSED" and _num(e.get("net_r")) is not None]
    costs = sum((_num(e.get("fee_r")) or 0.0) + (_num(e.get("slippage_r")) or 0.0) for e in closed)
    wins = sum((_num(e.get("net_r")) or 0.0) > 0 for e in closed)
    return {"closed": len(closed), "wins": wins, "losses": len(closed) - wins, "net": round(sum(_num(e["net_r"]) or 0.0 for e in closed), 3),
            "costs": round(costs, 3), "win_rate": (wins / len(closed)) if closed else None,
            "missing": sum(len(r["missing"]) for r in data["rules"])}


# --- Cockpit -----------------------------------------------------------------------

def _chart_html(state: Any) -> str:
    from src.dashboard.chart_model import build_chart_model
    from src.dashboard.pages.chart import _chart_svg

    model = build_chart_model(state.chart_series(), "30m", visible=80)
    if not model.get("candles"):
        return "<div class='chart-empty'>Noch keine Kerzen. Der Chart erscheint, sobald TIM Marktdaten liefert.</div>"
    return f"<div class='chartbox'>{_chart_svg(model)}</div>"


def _tile(tiles: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return next((t for t in tiles if t.get("id") == key), {})


def _lead(model: dict[str, Any]) -> str:
    needs = model.get("attention") or []
    today = model.get("today") or []
    open_items = [t for t in today if t.get("done") is False]
    if needs:
        fails = sum(t.get("state") == "fail" for t in needs)
        state = "fail" if fails else "warn"
        line = (f"{fails} {'Fehler' if fails else ''}, bitte ansehen" if fails else
                f"{len(needs)} {'Punkt braucht' if len(needs) == 1 else 'Punkte brauchen'} einen Blick")
    elif open_items:
        state = "ok" if model.get("overall") == "ok" else "unknown"
        line = ("Alles ruhig. " if state == "ok" else "") + f"{len(open_items)} {'Punkt wartet' if len(open_items) == 1 else 'Punkte warten'} auf dich."
    else:
        state = model.get("overall") or "unknown"
        line = "Alles ruhig, nichts offen." if state == "ok" else str(model.get("headline") or "Nicht alle Quellen liefern Daten")
    market = model.get("market") or []
    bits = []
    for key, prefix in (("market_state", "Markt"), ("bias", "Bias"), ("setup", "Setup")):
        tile = _tile(market, key)
        if tile.get("value") and tile.get("value") != "—":
            bits.append(f"{prefix} {tile['value']}")
    sub = " · ".join(bits) or "TIMs Marktanalyse hat noch keine Daten"
    items = "".join(
        f"<li class='{'w' if t.get('state') == 'warn' else ''}'><b>{_e(STATE_WORDS.get(str(t.get('state')), ''))}</b>"
        f"<a href='{_e(t.get('href') or '/system')}'>{_e(t.get('label'))}</a>: {_e(t.get('reason') or t.get('value'))}</li>"
        for t in needs[:5])
    return (f"<div class='card lead'><span class='lead__dot' data-s='{_e(state)}'></span><div><h1>{_e(line)}</h1>"
            f"<p>{_e(sub)}</p>{f'<ul>{items}</ul>' if items else ''}</div></div>")


def _plans_card(data: dict[str, Any], model: dict[str, Any]) -> str:
    rows = []
    for rule in data["rules"]:
        for entry in rule["entries"]:
            status = entry.get("status")
            if status not in {"OPEN", "FILLED"}:
                continue
            word = "<span class='mut sm'>wartet</span>" if status == "OPEN" else "<span class='up sm'>im Trade</span>"
            rows.append((str(entry.get("created_at") or ""),
                         f"<div class='row'><span>{_dir(entry.get('direction'))}{_e(rule['label'])} {_e(_price(entry.get('entry')))}</span>{word}</div>"))
    rows.sort(reverse=True)
    body = "".join(html_row for _, html_row in rows[:6])
    if not body:
        hint = next((p.get("title") for p in model.get("plans") or [] if p.get("title")), "")
        body = f"<p class='mut'>Kein Papier-Plan offen.{(' TIM sieht: ' + _e(hint)) if hint else ''}</p>"
    return f"<div class='card'><h2>TIMs Pläne jetzt <a href='/journal'>Plan-Journal</a></h2>{body}</div>"


def _result_card(data: dict[str, Any]) -> str:
    cells = "".join(
        f"<div><b class='{_rcls(r['summary'].get('sum_net_r'))}'>{_e(_r(r['summary'].get('sum_net_r')))}</b><span class='mut sm'>{_e(r['label'])} · {r['summary'].get('closed', 0)} Trades</span></div>"
        for r in data["rules"])
    totals = _totals(data)
    rate = "—" if totals["win_rate"] is None else f"{totals['win_rate'] * 100:.0f} %"
    cells += f"<div><b>{_e(rate)}</b><span class='mut sm'>Treffer netto</span></div>"
    return f"<div class='card'><h2>Papier-Ergebnis <a href='/trades'>Journal</a></h2><div class='kpi3'>{cells}</div><p class='mut sm'>Alle geschlossenen Papier-Trades, nach Kosten.</p></div>"


def _today_card(model: dict[str, Any]) -> str:
    rows = "".join(
        f"<div class='row'><span>{'✓' if t.get('done') else '○'} <a href='{_e(t.get('href'))}'>{_e(t.get('label'))}</a></span><span class='mut sm'>{_e(t.get('text'))}</span></div>"
        for t in model.get("today") or [])
    return f"<div class='card'><h2>Heute zu tun</h2>{rows or '<p class=mut>Nichts offen.</p>'}</div>"


def cockpit_body(state: Any) -> str:
    from src.dashboard.cockpit.lage import build_lage

    model = build_lage(state)
    try:
        data = journals(state)
    except Exception:  # noqa: BLE001
        data = {"rules": [], "notes": {}}
    chart = _safe(lambda: _chart_html(state), "Chart")
    right = (_safe(lambda: _plans_card(data, model), "TIMs Pläne") + _safe(lambda: _result_card(data), "Papier-Ergebnis")
             + _safe(lambda: _today_card(model), "Heute zu tun"))
    return (f"<div class='scr'>{_lead(model)}<div class='two'>"
            f"<div class='card chart-card'><h2>BTCUSDT · 30m <a href='/chart'>Großer Chart öffnen</a></h2>{chart}</div>"
            f"<div class='stack'>{right}</div></div></div>")


# --- Journal -----------------------------------------------------------------------

def _note_cell(rule: dict[str, Any], entry: dict[str, Any], notes: dict[str, Any]) -> str:
    from src.dashboard import plan_notes

    note = notes.get(plan_notes.key(rule["rule"], entry.get("id")))
    if note:
        return _e(note.get("reason"))
    if str(entry.get("id")) in rule["missing"]:
        return "<a class='tag w' href='/journal'>Notiz fehlt</a>"
    return "<span class='mut'>—</span>"


def journal_body(state: Any) -> str:
    data = journals(state)
    totals = _totals(data)
    kpis = (
        f"<div class='card kpi'><h2>Netto</h2><b class='{_rcls(totals['net'])}'>{_e(_r(totals['net']))}</b><span class='mut sm'>TIM-Regel und Struktur, nach Kosten</span></div>"
        f"<div class='card kpi'><h2>Trades</h2><b>{totals['closed']}</b><span class='mut sm'>{totals['wins']} Gewinner · {totals['losses']} Verlierer</span></div>"
        f"<div class='card kpi'><h2>Kosten</h2><b>{_e(_r(totals['costs'], sign=False))}</b><span class='mut sm'>Gebühren und Slippage</span></div>"
        f"<div class='card kpi'><h2>Notizen offen</h2><b class='{'warnc' if totals['missing'] else ''}'>{totals['missing']}</b><span class='mut sm'>eine Zeile pro Plan, letzte 7 Tage</span></div>"
    )
    rules = "".join(
        f"<div class='row'><span><b>{_e(r['label'])}</b> <span class='mut sm'>{r['summary'].get('closed', 0)} geschlossen · {r['summary'].get('open', 0)} warten · {r['summary'].get('filled', 0)} im Trade</span></span>"
        f"<span class='{_rcls(r['summary'].get('sum_net_r'))}'>{_e(_r(r['summary'].get('sum_net_r')))}</span></div>"
        + (f"<p class='dn sm'>Journal gesperrt: Ereignislog beschädigt.</p>" if r["integrity"].startswith("LOG_BROKEN") else "")
        for r in data["rules"])
    rows = []
    for rule in data["rules"]:
        for entry in rule["entries"]:
            if entry.get("status") not in {"OPEN", "FILLED", "CLOSED"}:
                continue
            if entry.get("status") == "CLOSED":
                result = f"<span class='{_rcls(entry.get('net_r'))}'>{_e(_r(entry.get('net_r')))}</span>"
            else:
                result = "<span class='mut'>wartet</span>" if entry.get("status") == "OPEN" else "<span class='up'>im Trade</span>"
            rows.append((str(entry.get("created_at") or ""),
                         f"<tr><td>{_e(local_time(entry.get('created_at'), with_date=True))}</td><td>{_e(rule['label'])}</td><td>{_dir(entry.get('direction'))}</td>"
                         f"<td>{_e(_price(entry.get('entry')))}</td><td>{result}</td><td>{_note_cell(rule, entry, data['notes'])}</td></tr>"))
    rows.sort(reverse=True)
    table = ("<div class='tbl-wrap'><table class='trades'><thead><tr><th>Zeit</th><th>Regel</th><th>Richtung</th><th>Einstieg</th><th>Ergebnis</th><th>Deine Notiz</th></tr></thead>"
             f"<tbody>{''.join(r for _, r in rows[:20])}</tbody></table></div>") if rows else "<p class='mut'>Noch keine Papier-Trades im Journal.</p>"
    trader = _safe(lambda: _trader_line(state), "Trader-Journal")
    return (f"<div class='scr'><div class='kpis'>{kpis}</div>"
            f"<div class='card'><h2>Regeln <a href='/journal'>Plan-Journal mit allen Details</a></h2>{rules}</div>"
            f"<div class='card'><h2>Letzte Trades <span>Papier</span></h2>{table}</div>{trader}</div>")


def _trader_line(state: Any) -> str:
    from src.dashboard import trader_journal as tj

    stats = tj.summary(tj.load(state.trader_journal_path))
    if not stats.get("entries"):
        text = "Noch kein eigener Trade eingetragen."
    else:
        text = f"{stats['open'] + stats['filled']} offen · {stats['closed']} geschlossen · Summe {_r(stats.get('sum_r'))} · {stats['review_open']} Rückblick(e) offen"
    return f"<div class='card'><h2>Deine eigenen Trades <a href='/trader-journal'>Trader-Journal</a></h2><p>{_e(text)}</p></div>"


# --- Forschung ---------------------------------------------------------------------

LOGBOOK = Path("docs/research_lab/LOGBUCH.json")
STUDY_TAGS = {"running": ("läuft", "w"), "waiting": ("wartet auf Daten", ""), "confirmed": ("bestätigt", "l"),
              "candidate": ("Kandidat", ""), "failed": ("nicht bestanden", "s"), "not_testable": ("nicht testbar", "s"),
              "aborted": ("abgebrochen", "")}


TASK_WORDS = {"trades": "Trade-Reflexion (stündlich)", "weekly": "Forschungsrunde (sonntags)", "monthly": "Monats-Reflexion (am 1.)"}
IDEA_TAGS = {"ready": "l", "new": "", "waiting_data": "w", "waiting_budget": "w"}


RULE_WORDS = {"candidate": "Kandidat", "failed": "nicht bestanden", "not_testable": "zu wenige Trades"}


def _workshop_card(root: Path) -> str:
    """F9: what the research workshop on the Mac is doing (read only, data/research/)."""
    from src.research_lab.workshop.overview import overview

    data = overview(root)
    counts = data["idea_counts"]
    open_count = sum(counts.get(k, 0) for k in IDEA_TAGS)
    trades = data["trades"] or {"count": 0, "top": []}
    head = (f"<div class='kpi3'><div><span class='mut sm'>Offene Ideen</span><b>{open_count}</b><span class='mut sm'>"
            f"{counts.get('ready', 0)} bereit</span></div>"
            f"<div><span class='mut sm'>Studien-Budget {_e(data['month'])}</span><b>{data['drafts_this_month']} / {data['budget']}</b>"
            f"<span class='mut sm'>Stufe {data['stage']}: du gibst jede Studie frei</span></div>"
            f"<div><span class='mut sm'>Reflektierte Trades</span><b>{trades['count']}</b><span class='mut sm'>Papier, alle Journale</span></div></div>")
    ideas = "".join(
        f"<div class='row'><span><b>{_e(i['id'])}</b> {_e(i['title'])}<br><span class='mut sm'>{_e(i['source'])}"
        + (f" · {_e(i['reason'])}" if i["reason"] else "") + "</span></span>"
        f"<span><span class='tag {IDEA_TAGS.get(i['status'], '')}'>{_e(i['status_text'])}</span></span></div>"
        for i in data["ideas"]) or "<p class='mut'>Keine offenen Ideen.</p>"
    lessons = "".join(f"<div class='row'><span>{_e(t['text'])}</span><span class='mut nw'>{t['count']} ({round(t['share'] * 100)} %)</span></div>"
                      for t in trades["top"]) or "<p class='mut'>Noch keine Muster.</p>"
    shadows = "".join(
        f"<div class='row'><span><b>{_e(r['study'])}</b> {_e(r['model_id'])}<br><span class='mut sm'>Fenster bis {_e(local_time(r['window_end'], with_date=True))} · "
        f"{r['closed']} von {r['plans']} Plänen abgeschlossen</span></span>"
        f"<span><span class='tag'>{_e(r['verdict'] or 'läuft')}</span></span></div>"
        for r in data["shadows"]) or "<p class='mut'>Kein Kandidat im Schattenbetrieb. Ein Kandidat läuft 30 Tage mit und zählt nie im Netto-R.</p>"
    plan = "".join(
        f"<div class='row'><span>{_e(TASK_WORDS[task])}</span><span class='{'' if info.get('ok') is not False else 'dn'}'>"
        + (_e(local_time(info["last_run"], with_date=True)) if info.get("last_run") else "noch nie")
        + (" · wartet auf CI-Job" if info.get("held") else "") + (" · Fehler" if info.get("ok") is False else "") + "</span></div>"
        for task, info in data["schedule"].items())
    if data.get("schedule_paused"):
        plan += "<p class='warnc sm'>Zeitplan pausiert (PAUSE-Datei).</p>"
    tests = data.get("rule_tests") or {"count": 0, "candidates": 0, "recent": []}
    rule_tests = "".join(
        f"<div class='row'><span><b>{_e(r['run'])}</b> {_e(r['title'])}<br><span class='mut sm'>{_e(local_time(r['at'], with_date=True))}</span></span>"
        f"<span><span class='tag'>{_e(RULE_WORDS.get(r['status'], r['status']))}</span></span></div>" for r in tests["recent"])
    rule_tests = ((f"<p class='mut sm'>{tests['count']} Regeln erkundet, {tests['candidates']} Kandidaten. Bei vielen Versuchen "
                   "ist ein zufällig guter dabei; ein Kandidat braucht eine echte Studie.</p>" + rule_tests) if tests["count"] else
                  "<p class='mut'>Noch keine Regel getestet. Schreib eine Regel in den Chat, TIM prüft sie auf 2020 bis 2024.</p>")
    notes = "".join(f"<p class='mut sm'>{_e(n)}</p>" for n in data["notes"])
    reflection = (f"<p class='mut sm'>Letzte Monats-Reflexion: {_e(data['last_reflection'])}</p>" if data["last_reflection"] else "")
    return (f"<div class='card'><h2>Forschungswerkstatt <span>läuft auf dem Mac</span></h2>{head}</div>"
            f"<div class='two'><div class='card'><h2>Ideen-Liste <span>nächste zuerst</span></h2>{ideas}</div>"
            f"<div class='stack'><div class='card'><h2>Zeitplan</h2>{plan or '<p class=mut>Noch kein Lauf.</p>'}{reflection}{notes}</div>"
            f"<div class='card'><h2>Lehren aus den Trades</h2>{lessons}</div>"
            f"<div class='card'><h2>Schattenbetrieb</h2>{shadows}</div>"
            f"<div class='card'><h2>Regel-Tests <span>Erkundung, kein Beleg</span></h2>{rule_tests}</div></div></div>")


def forschung_body(state: Any, path: Path = LOGBOOK, research_root: Path = Path(".")) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = [e for e in data.get("entries") or [] if isinstance(e, dict)]
    except (OSError, ValueError, AttributeError) as exc:
        return f"<div class='scr'><div class='card'><h2>Logbuch</h2><p class='mut'>Logbuch nicht lesbar: {_e(type(exc).__name__)}</p></div></div>"
    entries.sort(key=lambda e: str(e.get("started") or ""), reverse=True)
    count = {key: sum(e.get("status") == key for e in entries) for key in STUDY_TAGS}
    ended = count["failed"] + count["not_testable"] + count["aborted"]
    kpis = (
        f"<div class='card kpi'><h2>Studien</h2><b>{len(entries)}</b><span class='mut sm'>im Logbuch, Stand {_e(data.get('updated') or '—')}</span></div>"
        f"<div class='card kpi'><h2>Laufen</h2><b>{count['running']}</b><span class='mut sm'>{count['waiting']} warten auf Daten</span></div>"
        f"<div class='card kpi'><h2>Ohne Vorteil beendet</h2><b>{ended}</b><span class='mut sm'>nicht bestanden, nicht testbar, abgebrochen</span></div>"
        f"<div class='card kpi'><h2>Bestätigt</h2><b>{count['confirmed']}</b><span class='mut sm'>beschreibende Befunde, keine Handelsregel</span></div>"
    )
    rows = "".join(
        f"<div class='study'><b>{_e(e.get('id'))}</b><div>{_e(e.get('title'))}<p>{_e(e.get('result'))}</p>"
        + (f"<p>Gelernt: {_e(e.get('lesson'))}</p>" if e.get("lesson") else "")
        + f"</div><span><span class='tag {STUDY_TAGS.get(str(e.get('status')), ('', ''))[1]}'>{_e(STUDY_TAGS.get(str(e.get('status')), (e.get('status') or '—', ''))[0])}</span></span></div>"
        for e in entries)
    more = ("<div class='links'><a href='/neu/forschung'>Forschung im Detail</a><a href='/cases'>Research-Fälle</a><a href='/observations'>Beobachtungen</a>"
            "<a href='/orderflow'>Orderflow</a><a href='/signals'>Signal-Research</a><a href='/analytics'>Analysen</a><a href='/insights'>Erkenntnisse</a>"
            "<a href='/research'>Recherche-Werkzeug</a></div>")
    workshop = _safe(lambda: _workshop_card(research_root), "Forschungswerkstatt")
    return (f"<div class='scr'><div class='kpis'>{kpis}</div>{workshop}"
            f"<div class='card'><h2>Logbuch der Studien <span>neueste zuerst</span></h2>{rows or '<p class=mut>Noch keine Studie eingetragen.</p>'}</div>"
            f"<div class='card'><h2>Mehr Forschung</h2>{more}</div></div>")


# --- System ------------------------------------------------------------------------

def _light(tile: dict[str, Any]) -> str:
    state = str(tile.get("state") or "unknown")
    value = tile.get("value")
    if str(value or "").strip().upper() in {"", "—", "UNAVAILABLE", "UNKNOWN", "NONE"}:
        value = STATE_WORDS.get(state, "keine Daten")
    head = (f"<span class='dot' data-s='{_e(state)}'></span><span><b>{_e(tile.get('label'))}</b></span>"
            f"<span class='mut sm'>{_e(value)}</span>")
    if state == "ok":
        return f"<li><div class='ok-row'>{head}</div></li>"
    why = (f"<p>{_e(tile.get('reason') or 'Keine Daten')}</p>"
           + (f"<p class='mut sm'>{_e(tile.get('detail'))}</p>" if tile.get("detail") else "")
           + (f"<p><a href='{_e(tile.get('href'))}'>Details ansehen</a></p>" if tile.get("href") else ""))
    return f"<li><details{' open' if state in {'fail', 'warn'} else ''}><summary>{head}</summary><div class='why'>{why}</div></details></li>"


SYSTEM_PAGES = (("Betrieb", "/neu/betrieb"), ("Mac jetzt", "/neu/mac"), ("Freigabe & Sicherheit", "/neu/system"), ("Laufzeit", "/runtime"),
                ("Datenqualität", "/data-quality"), ("Vorfälle & Lücken", "/gaps"), ("Systemzustand", "/health"), ("Ausnahmen", "/exceptions"),
                ("Zeitleiste", "/timeline"), ("Sicherheit", "/security"), ("Audit & Evidenz", "/audit-evidence"), ("Graphify & MCP", "/mcp"),
                ("Graphify-Graph", "/graphify"))


def system_body(state: Any) -> str:
    from src.dashboard.cockpit.lage import build_lage

    model = build_lage(state)
    tiles = list(model.get("system") or []) + list(model.get("mac") or [])
    green = sum(t.get("state") == "ok" for t in tiles)
    worst = "fail" if any(t.get("state") == "fail" for t in tiles) else "warn" if any(t.get("state") == "warn" for t in tiles) else (
        "ok" if green == len(tiles) and tiles else "unknown")
    line = f"{green} von {len(tiles)} grün" + ("" if worst == "ok" else ", bitte ansehen" if worst in {"fail", "warn"} else "")
    order = {"fail": 0, "warn": 1, "unknown": 2, "ok": 3}
    tiles.sort(key=lambda t: order.get(str(t.get("state")), 2))
    lights = "".join(_light(t) for t in tiles)
    pages = "".join(f"<a href='{_e(href)}'>{_e(label)}</a>" for label, href in SYSTEM_PAGES)
    stamp = local_time(datetime.now(timezone.utc))
    return (f"<div class='scr'><div class='card lead'><span class='lead__dot' data-s='{_e(worst)}'></span><div><h1>{_e(line)}</h1>"
            f"<p>Was nicht grün ist, steht oben und ist aufgeklappt. Stand {_e(stamp)}.</p></div></div>"
            f"<div class='card'><h2>Ampel</h2><ul class='lights'>{lights}</ul></div>"
            f"<div class='card'><h2>Detailseiten</h2><div class='links'>{pages}</div></div>"
            "<div class='card'><h2>Archiv</h2><p class='mut'>V2-Kampagne, alte Übersicht und Pilotansicht: erreichbar, aber nicht mehr im Weg. "
            "<a href='/archiv'>Zum Archiv</a></p></div></div>")


# --- routing -----------------------------------------------------------------------

SCREENS: dict[str, tuple[str, Callable[[Any], str]]] = {
    "/": ("Cockpit", cockpit_body),
    "/trades": ("Journal", journal_body),
    "/forschung": ("Forschung", forschung_body),
    "/system": ("System", system_body),
}


def render(path: str, state: Any, fragment: bool = False) -> tuple[str, str]:
    """(content type, payload) for one screen; ``fragment`` returns only the refreshable body as JSON."""
    title, build = SCREENS[path]
    body = build(state)
    if fragment:
        return "application/json", json.dumps({"html": body})
    return "text/html; charset=utf-8", _page(title, path, body)
