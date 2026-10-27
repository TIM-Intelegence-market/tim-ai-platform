"""English pages and data for the public read-only view (src/dashboard/public_server.py).

The Control Center stays German. The public view has its own English pages:
the interactive chart (same chart code, ``data-lang='en'``) and a summary of
the paper plan journals. The chart data from ``build_live_chart`` carries a few
German labels and notes; ``english_chart_model`` translates the known ones and
replaces any note it does not know by a neutral English line, so no German text
reaches a visitor through the API either.
"""

from __future__ import annotations

import re
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from src.dashboard.chart_live import SYMBOL_NAMES, SYMBOLS, VIEW_TIMEFRAMES
from src.dashboard.chart_model import _time
from src.dashboard.helpers import _safe
from src.dashboard.layout import CSS, EXTRA_CSS
from src.dashboard.pages.chart import APP_PATH, LIB_PATH
from src.dashboard.plan_journal import RULE_LEVEL, RULE_STRUCT, RULE_TIM, summary

LOCAL = ZoneInfo("Europe/Berlin")
DISCLAIMER = ("Research, not financial advice. Observation and paper tracking only: no orders, no recommendations. "
              "Data: public Binance candles and TIM's own analysis; the view can be delayed or incomplete.")
NAV = (("/chart", "Chart"), ("/journal", "Paper journal"))
REPO = "https://github.com/TIM-Intelegence-market/tim-ai-platform"

GROUPS_EN = {
    "day": "Day (1D)", "week": "Week (1W)", "month": "Month (1M)", "naked": "naked POC",
    "running": "running POCs", "session": "Sessions", "ib": "Initial Balance",
    "structure": "BOS / MSS", "trend": "Trend lines", "tpo": "TPO (day profile)",
    "vp": "Volume Profile (day, real trades)", "fp": "Footprint (bid × ask)",
}
PRIVATE_GROUPS = frozenset({"gamma"})
# Ordered (pattern, replacement) pairs for labels, names and notes of the drawings.
TEXT_EN: tuple[tuple[str, str], ...] = (
    (r"POC lfd\.", "POC (running)"),
    (r"\blfd\.", "running"),
    (r"Trend Hochs", "Trend highs"),
    (r"Trend Tiefs", "Trend lows"),
    (r" gebrochen\b", " broken"),
    (r"^Vortag ", "Prior day "),
    (r"^Vorwoche ab ", "Prior week from "),
    (r"^Vormonat ", "Prior month "),
    (r"unberührter Tages-POC", "untouched daily POC"),
    (r"laufendes Tagesprofil", "running day profile"),
    (r"laufendes Wochenprofil", "running week profile"),
    (r" \(läuft\)", " (running)"),
    (r"Initial Balance \(90 min ab 00:00 UTC\)", "Initial Balance (first 90 min from 00:00 UTC)"),
    (r"Schlusskurs jenseits des bestätigten Swings", "Close beyond the confirmed swing"),
    (r"BOS-Ziel", "BOS target"),
    (r"^Bruch des Swings, per Schlusskurs \(Docht zählt nicht\)", "Break of the swing, by the close (a wick does not count)"),
    (r"^Bruch des (Strong Low|Strong High), per Schlusskurs \(Docht zählt nicht\)", r"Break of the \1, by the close (a wick does not count)"),
    (r"^Trend aufwärts; Schlusskurs darunter = MSS", "Uptrend; a close below = MSS"),
    (r"^Trend abwärts; Schlusskurs darüber = MSS", "Downtrend; a close above = MSS"),
    (r"^Schlusskurs darüber = BOS", "A close above = BOS"),
    (r"^Schlusskurs darunter = BOS", "A close below = BOS"),
    (r"durch die letzten zwei Swing-Hochs \((\d+) Kerzen je Seite\)", r"through the last two swing highs (\1 candles per side)"),
    (r"durch die letzten zwei Swing-Tiefs \((\d+) Kerzen je Seite\)", r"through the last two swing lows (\1 candles per side)"),
)
NOTES_EN: tuple[tuple[str, str], ...] = (
    (r"^Kerzen aus der TIM-Runtime", "Candles from the TIM runtime (exchange not reachable)."),
    (r"^Keine Kerzen", "No candles for this selection."),
    (r"^Keine Tages-/Wochenlevel", "No day/week levels yet: too few closed 30m and 1h candles."),
    (r"^Volume Profile und Footprint aus echten Trades gibt es nur für (\w+)", r"Volume profile and footprint from real trades exist only for \1: TIM collects trades only there."),
    (r"^Noch keine Trades", "No trades from the TIM database yet (the runtime delivers them every 2 minutes)."),
    (r"^(Level \S+: )?Börse nicht erreichbar", r"\1Exchange not reachable, retrying shortly."),
)
SOURCES_EN = {
    "TIM-Runtime (wie Plan-Journale)": "TIM runtime (same as the plan journals)",
    "Binance-Klines (nur Anzeige)": "Binance klines (display only)",
    "TIM agg_trades (Binance Spot aggTrades, eigene Datenbank)": "TIM agg_trades (Binance spot aggTrades, own database)",
}
_GERMAN = re.compile(r"[äöüÄÖÜß]|\b(?:und|nicht|Kerzen|keine|noch|für|aus|der|die|das)\b")


def english_text(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    for pattern, replacement in TEXT_EN:
        text = re.sub(pattern, replacement, text)
    return text


def english_note(note: Any) -> Any:
    if not isinstance(note, str) or not note:
        return note
    for pattern, replacement in NOTES_EN:
        match = re.search(pattern, note)
        if match:
            return match.expand(replacement)
    return "Data note available in TIM's German view." if _GERMAN.search(note) else note


def english_chart_model(model: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(model)
    # The public view gets no options gamma (German-only levels, not part of the public scope).
    out["groups"] = {key: GROUPS_EN.get(key, value) for key, value in (model.get("groups") or {}).items() if key not in PRIVATE_GROUPS}
    if "default_groups" in model:
        out["default_groups"] = [key for key in model["default_groups"] if key not in PRIVATE_GROUPS]
    out["drawings"] = [{**d, "name": english_text(d.get("name")), "label": english_text(d.get("label")), "note": english_text(d.get("note"))}
                       for d in model.get("drawings") or []]
    out["notes"] = [english_note(n) for n in model.get("notes") or []]
    if isinstance(model.get("footprint"), dict):
        out["footprint"] = {**model["footprint"], "note": english_note(model["footprint"].get("note"))}
    for key in ("level_source", "trade_source"):
        if key in model:
            out[key] = SOURCES_EN.get(model[key], model[key])
    out["name"] = {"BTCUSDT": "Bitcoin", "ETHUSDT": "Ethereum", "SOLUSDT": "Solana"}.get(str(model.get("symbol")), model.get("name"))
    return out


# --- pages -------------------------------------------------------------------

def shell(title: str, active: str, body: str) -> str:
    """English page frame: same styles as the Control Center (so its CSP hash fits), no live script."""
    nav = "".join(f"<a href='{href}'" + (" aria-current='page'" if href == active else "") + f">{label}</a>" for href, label in NAV)
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='color-scheme' content='dark'><meta name='robots' content='noindex,nofollow'>"
        f"<title>{_safe(title)} · TIM</title><style>{CSS}{EXTRA_CSS}</style></head><body>"
        "<a class='skip-link' href='#main-content'>Skip to content</a>"
        "<header class='topbar'><div class='topbar__inner'><a class='brand' href='/chart' aria-label='TIM home'>TIM"
        "<small>TRADING INTELLIGENCE MACHINE · PUBLIC READ-ONLY VIEW</small></a>"
        f"<nav class='nav' aria-label='Main navigation'><div class='nav__group'>{nav}</div></nav></div></header>"
        f"<main id='main-content' class='shell' tabindex='-1'><section class='cc-section'><p class='cc-note'><b>{_safe(DISCLAIMER)}</b></p></section>{body}</main>"
        f"<footer class='footer'>TIM · public read-only view · research, not financial advice · <a href='{REPO}' rel='noopener noreferrer'>source code</a></footer>"
        "</body></html>"
    )


def _hero(title: str, text: str) -> str:
    return f"<div class='hero'><div><h1>{_safe(title)}</h1><p>{_safe(text)}</p></div><div class='observe'>OBSERVE • READ-ONLY</div></div>"


def chart_page(symbol: str | None, timeframe: str | None) -> str:
    from src.dashboard.chart_live import DEFAULT_SYMBOL, DEFAULT_VIEW

    symbol = symbol if symbol in SYMBOLS else DEFAULT_SYMBOL
    view = timeframe if timeframe in VIEW_TIMEFRAMES else DEFAULT_VIEW
    symbols = "".join(
        f"<a href='/chart?symbol={item}&amp;tf={view}' class='tc-tab{' tc-tab--active' if item == symbol else ''}'"
        + (" aria-current='page'" if item == symbol else "") + f">{item.removesuffix('USDT')}</a>"
        for item in SYMBOLS)
    frames = "".join(
        f"<a href='/chart?symbol={symbol}&amp;tf={item}' data-tf='{item}' class='tc-tab{' tc-tab--active' if item == view else ''}'"
        + (" aria-current='page'" if item == view else "") + f">{item}</a>"
        for item in VIEW_TIMEFRAMES)
    body = _hero("TIM chart", "BTC, ETH and SOL on every timeframe: zoom, pan, crosshair. "
                 "Levels are drawn as labelled segments from the moment they formed.")
    body += (
        f"<section class='cc-section tc-live' id='tc-live' data-lang='en' data-symbol='{_safe(symbol)}' data-tf='{_safe(view)}'>"
        f"<nav class='tc-tabs' aria-label='Coin'>{symbols}<span class='tc-tabs__sep'>Timeframe:</span>{frames}</nav>"
        "<div class='tc-live__bar'><div id='tc-live-layers' class='tc-live__layers' aria-label='Show or hide lines'></div>"
        "<div class='tc-live__actions'><button type='button' class='tc-tab' data-action='now'>Go to now</button>"
        "<button type='button' class='tc-tab' data-action='fit'>Show all</button>"
        "<button type='button' class='tc-tab' data-action='reset'>Reset lines</button></div></div>"
        "<div class='tc-live__frame'><p id='tc-live-legend' class='tc-live__legend'></p>"
        "<div id='tc-live-chart' class='tc-live__chart' role='img' aria-label='Interactive candlestick chart'></div></div>"
        "<p id='tc-live-status' class='cc-note tc-live__status'>Chart loading… (needs JavaScript)</p>"
        "<p class='cc-note'>Mouse wheel = zoom, drag = pan, drag the price axis = change height, double-click the axis = reset. "
        "<b>BOS / MSS</b> count only on a close (a wick through the level is a sweep): BOS = break of the last swing in trend direction, "
        "MSS = close beyond the <b>Strong Low</b> (uptrend) or <b>Strong High</b> (downtrend), the low/high the last push came from. "
        "Dashed and running to now: the open Strong Low/High and the <b>BOS target</b>. Swings: 3 candles per side. "
        "Every line starts where its level formed (highs/lows at their candle, profiles at the start of their day/week) and carries "
        "timeframe and name, e.g. <b>1D VAH</b> or <b>1W POC</b>. A ← means the start lies left of the loaded candles. "
        "<b>TPO</b>: day profile from 30-minute periods (letters A, B, C … from 00:00 UTC) behind the candles, value area lighter, "
        "POC yellow, single prints orange; on timeframes up to 4h. <b>Volume profile</b> and <b>footprint</b> come from TIM's own "
        "recorded trades (BTC only): the profile per day at the day's right edge (volume per price step, value area, POC yellow, "
        "green/red tick = delta); the footprint shows bid × ask per price step for each candle once candles are wide enough (zoom in), "
        "4:1 imbalances filled, Δ below the candle. Times in Central European time. Display only, no orders. "
        "Chart: <a href='https://www.tradingview.com/' rel='noopener noreferrer'>TradingView Lightweight Charts</a> (Apache 2.0).</p>"
        f"<script src='{LIB_PATH}'></script><script src='{APP_PATH}'></script></section>"
    )
    return shell("Chart", "/chart", body)


RULES_EN = (
    (RULE_TIM, "TIM rule", "fixed stop, targets at 1.5 / 2 / 3 R"),
    (RULE_STRUCT, "Structure rule", "stop behind the 30m swing, targets at liquidity"),
    (RULE_LEVEL, "Level rule", "main levels from the chart, stop behind the swing"),
)
STATUS_EN = {"OPEN": "waiting for entry", "FILLED": "in trade", "CLOSED": "closed", "INVALIDATED": "invalidated before entry",
             "REPLACED": "replaced", "EXPIRED": "expired"}
EXIT_EN = {"STOP": "stop", "BREAK_EVEN": "break-even after TP1", "BREAK_EVEN_COSTS": "break-even + costs after TP1",
           "COST_STOP": "stop at break-even + costs", "TRAIL_STOP": "trailing stop", "TP3": "TP3", "TIMEOUT": "time limit",
           "INVALIDATION": "close beyond invalidation"}


def _r(value: Any) -> str:
    return "–" if not isinstance(value, (int, float)) else f"{value:+.2f} R"


def _price(value: Any) -> str:
    return f"{value:,.2f}" if isinstance(value, (int, float)) else "–"


def _when(value: Any) -> str:
    moment = _time(value)
    return moment.astimezone(LOCAL).strftime("%Y-%m-%d %H:%M") if moment else "–"


def journal_page(journals: Mapping[str, Mapping[str, Any]], shown: str = RULE_TIM) -> str:
    """Comparison of the paper rule versions plus the latest plans of one rule."""
    rows = []
    for rule, name, text in RULES_EN:
        journal = journals.get(rule)
        if journal is None:
            continue
        stats = summary(journal)
        rate = f"{stats['win_rate'] * 100:.0f} %" if stats["win_rate"] is not None else "–"
        per = stats["sum_net_r"] / stats["closed"] if stats["closed"] else None
        href = {RULE_TIM: "/journal", RULE_STRUCT: "/journal?rule=struct", RULE_LEVEL: "/journal?rule=level"}[rule]
        rows.append(f"<tr><td><a href='{href}'>{_safe(name)}</a><small> {_safe(text)}</small></td><td>{stats['plans']}</td>"
                    f"<td>{stats['closed']}</td><td>{_safe(rate)}</td><td class='mono'>{_safe(_r(stats['sum_net_r']))}</td>"
                    f"<td class='mono'>{_safe(_r(per))}</td><td class='mono'>{_safe(_r(stats['sum_r']))}</td><td>{stats['excluded']['plans']}</td></tr>")
    body = _hero("Paper journal", "TIM writes down its long and short plans automatically and tracks them by fixed rules on 1-minute candles. "
                 "Paper only: no orders. Results in R (1 R = distance entry to stop), net after fees 0.05 % and slippage 0.03 % per side.")
    body += ("<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Comparison</p>"
             "<h2>Rule versions side by side</h2><p class='cc-section__note'>Same market, same candles. Corrected entries (phantoms, a double booking) "
             "stay visible but are not counted. Meaningful only after many closed plans.</p></div></div>"
             "<div class='table-wrap'><table><thead><tr><th>Rule</th><th>Plans</th><th>Closed</th><th>Win rate</th><th>Net sum</th>"
             f"<th>Net per plan</th><th>Gross sum</th><th>Not counted</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>")
    journal = journals.get(shown) or {}
    name = next((n for r, n, _ in RULES_EN if r == shown), "TIM rule")
    entries = list(journal.get("entries") or [])[-100:]
    plan_rows = "".join(_plan_row(e) for e in reversed(entries)) or "<tr><td colspan='8' class='cc-note'>No plans yet.</td></tr>"
    if str(journal.get("integrity") or "").startswith("LOG_BROKEN"):
        plan_rows = "<tr><td colspan='8' class='cc-note'>Journal locked: the event log needs a check.</td></tr>"
    body += ("<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Plans</p>"
             f"<h2>{_safe(name)}: latest 100 plans (newest first)</h2><p class='cc-section__note'>Times in Central European time. "
             "Data as JSON: <a href='/api/plan-journal'>TIM rule</a> · <a href='/api/plan-journal?rule=struct'>structure rule</a> · "
             "<a href='/api/plan-journal?rule=level'>level rule</a>.</p></div></div>"
             "<div class='table-wrap'><table><thead><tr><th>Created</th><th>Plan</th><th>Entry</th><th>Stop</th><th>Targets</th>"
             f"<th>Status</th><th>Gross R</th><th>Net R</th></tr></thead><tbody>{plan_rows}</tbody></table></div></section>")
    return shell("Paper journal", "/journal", body)


def _plan_row(entry: Mapping[str, Any]) -> str:
    status = STATUS_EN.get(str(entry.get("status")), str(entry.get("status") or "–").lower())
    if entry.get("exit_reason"):
        status += f" ({EXIT_EN.get(str(entry['exit_reason']), str(entry['exit_reason']).lower())})"
    if entry.get("excluded"):
        status = "not counted (corrected) · " + status
    targets = " · ".join(f"TP{i} {_price(t)}" for i, t in enumerate(entry.get("targets") or [], start=1) if t is not None) or "–"
    direction = str(entry.get("direction") or "–")
    return (f"<tr><td>{_safe(_when(entry.get('created_at')))}</td><td><span class='tag tag--{_safe(direction.lower())}'>{_safe(direction)}</span></td>"
            f"<td class='mono'>{_safe(_price(entry.get('entry')))}</td><td class='mono'>{_safe(_price(entry.get('stop')))}</td>"
            f"<td>{_safe(targets)}</td><td>{_safe(status)}</td><td class='mono'>{_safe(_r(entry.get('gross_r')))}</td>"
            f"<td class='mono'>{_safe(_r(entry.get('net_r')))}</td></tr>")
