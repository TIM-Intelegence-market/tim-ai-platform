"""English pages and data for the public read-only view (src/dashboard/public_server.py).

The Control Center stays German. The public view has its own English pages:
the interactive chart (same chart code, ``data-lang='en'``) and a summary of
the paper plan journals. The chart data from ``build_live_chart`` carries a few
German labels and notes; ``english_chart_model`` translates the known ones and
replaces any note it does not know by a neutral English line, so no German text
reaches a visitor through the API either.
"""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from src.dashboard.chart_live import SYMBOL_NAMES, SYMBOLS, VIEW_TIMEFRAMES, tab_label
from src.dashboard.chart_model import _time
from src.dashboard.helpers import _safe
from src.dashboard.layout import CSS, EXTRA_CSS
from src.dashboard.pages.chart import APP_SRC, LIB_PATH
from src.dashboard.plan_journal import FILLED, OPEN, RULE_LEVEL, RULE_STRUCT, RULE_TIM, summary

LOCAL = ZoneInfo("Europe/Berlin")
DISCLAIMER = ("Research, not financial advice. Observation and paper tracking only: no orders, no recommendations. "
              "Data: public Binance candles and TIM's own analysis; the view can be delayed or incomplete.")
NAV = (("/chart", "Chart"), ("/journal", "Paper journal"))
REPO = "https://github.com/TIM-Intelegence-market/tim-ai-platform"

GROUPS_EN = {
    "day": "Day (1D)", "week": "Week (1W)", "month": "Month (1M)", "quarter": "Quarter (1Q)", "year": "Year (1Y)",
    "vwap": "VWAP (week, month, quarter, year)", "vwap_bands": "VWAP bands week (±1σ, ±2σ)", "naked": "naked POC",
    "running": "running POCs", "session": "Sessions", "ib": "Initial Balance",
    "structure": "BOS / MSS", "trend": "Trend lines", "fib": "Fibonacci (last swing)", "tpo": "TPO (day profile)",
    "vp": "Volume Profile (day, real trades)", "fp": "Footprint (bid × ask)", "bubbles": "Volume bubbles (large market orders)",
    "plans_short": "TIM plans SHORT 15m", "plans_mid": "TIM plans MID 1h", "plans_long": "TIM plans LONG 1D",
    "plans_old": "TIM plans, test versions 30m",
    "gamma": "Options gamma (Deribit)",
    "liq": "Liquidation heatmap (estimate)",
    "cvd": "CVD spot vs. perp", "oi": "Open interest + Z-score (7.5 d)",
}
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
    (r"^Vorquartal ", "Prior quarter "),
    (r"^Vorjahr ", "Prior year "),
    (r"aus Tageskerzen geschätzt", "estimated from daily candles"),
    (r"aus Wochenkerzen geschätzt, Ränder ungefähr", "estimated from weekly candles, edges approximate"),
    (r"^VWAP Woche ab ", "VWAP week from "),
    (r"^VWAP Monat ab ", "VWAP month from "),
    (r"^VWAP 12 Monate", "VWAP 12 months"),
    (r"^VWAP Quartal ab ", "VWAP quarter from "),
    (r"^VWAP Jahr ab ", "VWAP year from "),
    (r", Band ([+−]\dσ)$", r", band \1"),
    (r", echte Trades$", ", real trades"),
    (r"unberührter Volumen-POC \(vPOC\)", "untouched volume POC (vPOC)"),
    (r"unberührter TPO-POC \(Zeit, 30m-Perioden\)", "untouched TPO POC (time, 30m periods)"),
    (r" \(Schätzung aus Kerzen\)", " (estimated from candles)"),
    (r", aus (\w+)-Kerzen(?=,|$)", r", from \1 candles"),
    (r", Linie aus den gezeigten Kerzen(?=,|$)", ", line from the shown candles"),
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
    (r"^Long-Fib Swing-Tief → Hoch \(Docht\), Zone, kein Signal", "Long fib, swing low → high (wicks), zone, not a signal"),
    (r"^Short-Fib Swing-Hoch → Tief \(Docht\), Zone, kein Signal", "Short fib, swing high → low (wicks), zone, not a signal"),
    (r"durch die letzten zwei Swing-Tiefs \((\d+) Kerzen je Seite\)", r"through the last two swing lows (\1 candles per side)"),
    # Options gamma levels (gamma_data.py).
    (r"^(Opt )?EM hoch ", r"\1EM high "),
    (r"^(Opt )?EM tief ", r"\1EM low "),
    (r"^darüber dämpfen Händler eher, darunter verstärken sie Bewegungen$",
     "above it dealer hedging tends to dampen moves, below it to amplify them (estimate)"),
    (r"^größtes Call-Gamma über dem Preis$", "largest call gamma above the price (estimate)"),
    (r"^größtes Put-Gamma unter dem Preis$", "largest put gamma below the price (estimate)"),
    (r"^Hauptverfall (\S+) \((\d+) % des OI\)$", r"main expiry \1 (\2 % of open interest)"),
    (r"^erwartete Bewegung bis Verfall, ATM-IV ([\d.]+) %$", r"expected move until expiry, ATM IV \1 %"),
    # Estimated liquidation clusters (liquidation_data.py).
    (r"^Liq-Cluster oben$", "Liq cluster above"),
    (r"^Liq-Cluster unten$", "Liq cluster below"),
    (r"^stärkste geschätzte Short-Liquidationen über dem Preis$", "strongest estimated short liquidations above the price"),
    (r"^stärkste geschätzte Long-Liquidationen unter dem Preis$", "strongest estimated long liquidations below the price"),
)
NOTES_EN: tuple[tuple[str, str], ...] = (
    (r"^Kerzen aus der TIM-Runtime", "Candles from the TIM runtime (exchange not reachable)."),
    (r"^Keine Kerzen", "No candles for this selection."),
    (r"^Keine Tages-/Wochenlevel", "No day/week levels yet: too few closed 30m and 1h candles."),
    (r"^Volume Profile und Footprint aus echten Trades gibt es nur für (\w+)", r"Volume profile and footprint from real trades exist only for \1: TIM collects trades only there."),
    (r"^Gold über PAXG", "Gold via PAXG (tokenised gold, 1 PAXG = 1 troy ounce): trades around the clock, real gold does not; "
                         "weekend candles and thinner liquidity can shift levels against XAUUSD."),
    (r"^Gamma: Deribit-Stand ist (\d+) min alt", r"Gamma: Deribit data is \1 min old, levels hidden."),
    (r"^Liquidations-Heatmap: Binance-Stand ist (\d+) min alt", r"Liquidation heatmap: Binance data is \1 min old, hidden."),
    (r"^Keine großen Market Orders", "No large market orders in the shown window."),
    (r"^Noch keine Trades", "No trades from the TIM database yet (the runtime delivers them every 2 minutes)."),
    (r"^(Level \S+: )?Börse nicht erreichbar", r"\1Exchange not reachable, retrying shortly."),
    (r"^Perp-Trades noch nicht da", "Perp trades not there yet (the collector starts with the previous day): showing spot."),
    (r"^Open Interest: Binance-Stand älter", "Open interest: Binance data older than 3 h, hidden."),
    (r"^CVD nur Spot", "CVD spot only: no perp trades in the shown window yet."),
    (r"^CVD nur Perp", "CVD perp only: no spot trades in the shown window."),
    (r"^CVD ab (\d+)m", r"CVD from \1m."),
)
SOURCES_EN = {
    "TIM-Runtime (wie Plan-Journale)": "TIM runtime (same as the plan journals)",
    "Binance-Klines (nur Anzeige)": "Binance klines (display only)",
    "TIM agg_trades (Binance Spot aggTrades, eigene Datenbank)": "TIM agg_trades (Binance spot aggTrades, own database)",
    "Binance USD-M Perp aggTrades (BTCUSDT, öffentlich, TIM-Sammler)": "Binance USD-M perp aggTrades (BTCUSDT, public, TIM collector)",
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
    out["groups"] = {key: GROUPS_EN.get(key, value) for key, value in (model.get("groups") or {}).items()}
    out["drawings"] = [{**d, "name": english_text(d.get("name")), "label": english_text(d.get("label")), "note": english_text(d.get("note"))}
                       for d in model.get("drawings") or []]
    out["notes"] = [english_note(n) for n in model.get("notes") or []]
    plan_labels = {"Struktur 30m": "Structure 30m"}
    out["plans"] = [{**p, "label": plan_labels.get(p.get("label"), p.get("label"))} for p in model.get("plans") or []]
    if isinstance(model.get("footprint"), dict):
        out["footprint"] = {**model["footprint"], "note": english_note(model["footprint"].get("note"))}
    if isinstance(model.get("fib"), dict):
        out["fib"] = {**model["fib"], "note": english_text(model["fib"].get("note"))}
    if isinstance(model.get("bubbles"), dict):
        out["bubbles"] = {**model["bubbles"], "note": english_note(model["bubbles"].get("note"))}
    if isinstance(model.get("cvd"), dict):
        out["cvd"] = {**model["cvd"], "note": english_note(model["cvd"].get("note"))}
    if isinstance(model.get("oi"), dict):
        out["oi"] = {**model["oi"], "source": "Binance USD-M open interest (BTCUSDT, 1h, public)"}
    for key in ("level_source", "trade_source"):
        if key in model:
            out[key] = SOURCES_EN.get(model[key], model[key])
    out["name"] = {"BTCUSDT": "Bitcoin", "ETHUSDT": "Ethereum", "SOLUSDT": "Solana", "PAXGUSDT": "Gold (PAXG)"}.get(str(model.get("symbol")), model.get("name"))
    return out


# --- pages -------------------------------------------------------------------

def shell(title: str, active: str, body: str, extra_css: str = "") -> str:
    """English page frame: same styles as the Control Center (so its CSP hash fits), no live script.

    A page with ``extra_css`` must be served with a CSP that hashes the longer style (``journal_csp``)."""
    nav = "".join(f"<a href='{href}'" + (" aria-current='page'" if href == active else "") + f">{label}</a>" for href, label in NAV)
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='color-scheme' content='dark'><meta name='robots' content='noindex,nofollow'>"
        f"<title>{_safe(title)} · TIM</title><style>{CSS}{EXTRA_CSS}{extra_css}</style></head><body>"
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


def chart_page(symbol: str | None, timeframe: str | None, summary: str = "") -> str:
    from src.dashboard.chart_live import DEFAULT_SYMBOL, DEFAULT_VIEW

    symbol = symbol if symbol in SYMBOLS else DEFAULT_SYMBOL
    view = timeframe if timeframe in VIEW_TIMEFRAMES else DEFAULT_VIEW
    symbols = "".join(
        f"<a href='/chart?symbol={item}&amp;tf={view}' class='tc-tab{' tc-tab--active' if item == symbol else ''}'"
        + (" aria-current='page'" if item == symbol else "") + f">{tab_label(item)}</a>"
        for item in SYMBOLS)
    frames = "".join(
        f"<a href='/chart?symbol={symbol}&amp;tf={item}' data-tf='{item}' class='tc-tab{' tc-tab--active' if item == view else ''}'"
        + (" aria-current='page'" if item == view else "") + f">{item}</a>"
        for item in VIEW_TIMEFRAMES)
    body = _hero("TIM chart", "BTC, ETH, SOL and gold on every timeframe: zoom, pan, crosshair. "
                 "Levels are drawn as labelled segments from the moment they formed.")
    body += summary
    body += (
        f"<section class='cc-section tc-live' id='tc-live' data-lang='en' data-symbol='{_safe(symbol)}' data-tf='{_safe(view)}'>"
        f"<nav class='tc-tabs' aria-label='Coin'>{symbols}<span class='tc-tabs__sep'>Timeframe:</span>{frames}</nav>"
        "<div class='tc-live__bar'><div id='tc-live-layers' class='tc-live__layers' aria-label='Show or hide lines'></div>"
        "<div class='tc-live__actions'><button type='button' class='tc-tab' data-action='now'>Go to now</button>"
        "<button type='button' class='tc-tab' data-action='fit'>Show all</button><button type='button' class='tc-tab' data-action='footprint' title='Last candles large, footprint with numbers'>Footprint</button>"
        "<span class='tc-market' role='group' aria-label='Trades behind volume profile, footprint and delta'><button type='button' class='tc-tab' data-action='market' data-market='spot' title='Volume profile, footprint, delta from spot trades'>Spot</button>"
        "<button type='button' class='tc-tab' data-action='market' data-market='perp' title='Volume profile, footprint, delta from perp trades (Binance futures)'>Perp</button></span>"
        "<button type='button' class='tc-tab' data-action='plans'>Only TIM's trades</button><button type='button' class='tc-tab' data-action='none'>Untick all</button><button type='button' class='tc-tab' data-action='reset'>Reset lines</button></div></div>"
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
        "green/red tick = delta); the <b>footprint</b> (5m to 4h, “Footprint” button) follows the zoom: medium = one colour column per candle (green/red = delta, "
        "strong = high volume), close = bid × ask per price step next to a slim candle, finer steps the closer you zoom, POC framed yellow, "
        "4:1 imbalances bold (green = buyers, red = sellers), stacked imbalances (3+) as a bar at the side, unfinished auction at the high/low "
        "dotted orange, Δ and volume (V) below the candle. <b>Volume bubbles</b> (timeframes up to 4h) = large market orders from TIM's trades "
        "(all aggTrades of one taker order, same millisecond and side, from 100,000 USD): green = aggressive buyer, red = aggressive seller, "
        "circle area = order size against the largest in view, the largest carry their size in BTC; only the largest in view are shown, zooming in adds smaller ones. <b>Fibonacci</b> as in TradingView on the last big swing (wick to wick; a swing counts after a move of 3 average candle ranges against it, "
        "and while price only pulls back the fib stays on the impulse): 1 = start, 0 = end, zones 0.236 to 1 plus 0.886/0.941 and 1.618. Times in Central European time. Display only, no orders. "
        "Chart: <a href='https://www.tradingview.com/' rel='noopener noreferrer'>TradingView Lightweight Charts</a> (Apache 2.0).</p>"
        f"<script src='{LIB_PATH}'></script><script src='{APP_SRC}'></script></section>"
    )
    return shell("Chart", "/chart", body)


# --- paper journal ------------------------------------------------------------

# Journals on the public page. The three horizons come first (Uzi 27.10.2026: SHORT 15m, MID 1h,
# LONG 1D, same TIM rule); the earlier test versions stay visible below them.
HORIZONS_EN = (
    ("short", "SHORT · 15m", "Intraday: a plan at every 15-minute close, waits up to 12 h for its entry, holds up to 24 h"),
    ("mid", "MID · 1h", "Session: a plan at every hourly close, waits up to 24 h, holds up to 3 days"),
    ("long", "LONG · 1D", "Structure: a plan at every daily close, waits up to 7 days, holds up to 3 weeks"),
)
EARLIER_EN = (
    ("tim", "TIM rule 30m", "first version: fixed stop, targets at 1.5 / 2 / 3 R"),
    ("struct", "Structure rule 30m", "stop behind the 30m swing, targets at liquidity"),
)
JOURNAL_KEYS = tuple(key for key, _, _ in HORIZONS_EN + EARLIER_EN)
DEFAULT_JOURNAL = "mid"
CHART_TF = {"short": "15m", "mid": "1h", "long": "1d", "tim": "30m", "struct": "30m", "level": "30m"}
ALIASES = {RULE_TIM: "tim", RULE_STRUCT: "struct", RULE_LEVEL: "level"}  # older callers pass rule ids
RULES_EN = tuple((rule, name, text) for rule, (_, name, text) in zip((RULE_TIM, RULE_STRUCT), EARLIER_EN))
STATUS_EN = {"OPEN": "waiting for entry", "FILLED": "in trade", "CLOSED": "closed", "INVALIDATED": "invalidated before entry",
             "REPLACED": "replaced", "EXPIRED": "expired"}
EXIT_EN = {"STOP": "stop", "BREAK_EVEN": "break-even after TP1", "BREAK_EVEN_COSTS": "break-even + costs after TP1",
           "COST_STOP": "stop at break-even + costs", "TRAIL_STOP": "trailing stop", "TP3": "TP3", "TIMEOUT": "time limit",
           "INVALIDATION": "close beyond invalidation"}
SETUP_EN = {
    "LIQUIDITY_SWEEP_REVERSAL": "a reversal after a liquidity sweep",
    "BREAKOUT_ACCEPTANCE": "a breakout that held (acceptance)",
    "FAILED_RETEST": "a failed retest",
    "FAILED_CONTINUATION": "a failed continuation",
    "REJECTION_FAILED_BREAKOUT": "a failed breakout (rejection)",
    "BALANCE_ROTATION": "a rotation inside the range",
    "EXHAUSTION_REVERSAL": "an exhaustion reversal",
    "LEVEL_REACTION": "a reaction at a main level",
}
MARKET_EN = {"BALANCE": "range", "RANGE": "range", "TREND_UP": "uptrend", "TREND_DOWN": "downtrend", "IMBALANCE_UP": "push up",
             "IMBALANCE_DOWN": "push down"}
_ID = re.compile(r"^[0-9a-f]{6,32}$")


def _r(value: Any) -> str:
    return "–" if not isinstance(value, (int, float)) else f"{value:+.2f} R"


def _price(value: Any) -> str:
    return f"{value:,.2f}" if isinstance(value, (int, float)) else "–"


def _when(value: Any) -> str:
    moment = _time(value) if value else None
    return moment.astimezone(LOCAL).strftime("%Y-%m-%d %H:%M") if moment else "–"


JOURNAL_CSS = (
    ".pj-tabs{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:0 0 22px}"
    ".pj-tab{display:block;padding:14px 16px;border:1px solid var(--line);border-radius:10px;background:var(--surface);color:var(--text-soft);text-decoration:none}"
    ".pj-tab:hover{border-color:var(--line-strong)}"
    ".pj-tab--active{border-color:var(--blue);background:#101b2c;color:var(--text)}"
    ".pj-tab b{display:block;font-size:15px;color:var(--text)}.pj-tab small{display:block;color:var(--muted);margin-top:2px}"
    ".pj-tab .pj-tab__num{display:block;margin-top:10px;font:700 18px var(--font-mono)}"
    ".pj-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:0 0 14px}"
    ".pj-kpi{padding:14px 16px;border:1px solid var(--line);border-radius:10px;background:var(--surface)}"
    ".pj-kpi span{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}"
    ".pj-kpi strong{display:block;margin-top:6px;font:700 24px var(--font-mono);color:var(--text)}"
    ".pj-kpi small{display:block;margin-top:4px;color:var(--muted)}"
    ".pj-pos{color:var(--green)!important}.pj-neg{color:var(--red)!important}.pj-flat{color:var(--muted)!important}"
    ".pj-curve{border:1px solid var(--line);border-radius:10px;background:#0b1017;padding:12px 14px;margin:0 0 22px}"
    ".pj-curve p{margin:0 0 8px;color:var(--muted);font-size:12px}.pj-curve svg{display:block;width:100%;height:150px}"
    ".pj-now{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px}"
    ".pj-plan{padding:14px 16px;border:1px solid var(--line);border-left:3px solid var(--blue);border-radius:10px;background:var(--surface)}"
    ".pj-plan--short{border-left-color:var(--red)}.pj-plan--long{border-left-color:var(--green)}"
    ".pj-plan header{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:8px}"
    ".pj-plan dl{display:grid;grid-template-columns:auto 1fr;gap:3px 12px;margin:0;font-size:13px}.pj-plan dt{color:var(--muted)}"
    ".pj-plan dd{margin:0;font-family:var(--font-mono)}"
    ".pj-table table{min-width:640px}.pj-table td,.pj-table th{padding:10px 12px}"
    ".pj-day td{background:#0e141d;color:var(--muted);font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;padding:7px 12px}"
    ".pj-dir{font-weight:750}.pj-dir--long{color:var(--green)}.pj-dir--short{color:var(--red)}"
    ".pj-res{display:inline-block;min-width:52px;padding:2px 8px;border-radius:5px;font-size:12px;font-weight:700;text-align:center}"
    ".pj-res--win{background:var(--green-soft);color:var(--green)}.pj-res--loss{background:var(--red-soft);color:var(--red)}"
    ".pj-res--be{background:var(--surface-soft);color:var(--muted)}"
    ".pj-more{margin-top:12px;border:1px solid var(--line);border-radius:10px;background:var(--surface)}"
    ".pj-more summary{cursor:pointer;padding:12px 16px;color:var(--text-soft);font-weight:650}"
    ".pj-more summary small{color:var(--muted);font-weight:400}.pj-more[open] summary{border-bottom:1px solid var(--line)}"
    ".pj-more__body{padding:12px 16px}.pj-more__body>p{margin:0 0 10px;color:var(--muted);font-size:13px}"
    ".pj-empty{padding:16px;border:1px dashed var(--line);border-radius:10px;color:var(--muted)}"
    ".pj-table td{white-space:nowrap}"
    "@media(max-width:640px){.pj-kpi strong{font-size:20px}.pj-tabs{grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}"
    ".pj-tab{padding:10px}.pj-tab>small:first-of-type{display:none}.pj-tab b{font-size:13px}.pj-tab .pj-tab__num{font-size:15px;margin-top:6px}"
    ".pj-trades table{min-width:0}.pj-trades .pj-wide{display:none}.pj-trades td,.pj-trades th{padding:9px 8px}}"
)
JOURNAL_STYLE = CSS + EXTRA_CSS + JOURNAL_CSS
JOURNAL_CSS += (
    ".pj-tabs--small{grid-template-columns:repeat(auto-fit,minmax(170px,1fr));margin-top:-10px}"
    ".pj-tabs--small .pj-tab{padding:9px 12px}.pj-tabs--small .pj-tab b{font-size:13px}.pj-tabs--small .pj-tab .pj-tab__num{font-size:14px;margin-top:4px}"
    ".pj-label{margin:0 0 8px;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}"
    ".pj-why{white-space:normal!important;min-width:260px;color:var(--text-soft)}"
    ".pj-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}"
    ".pj-facts dl{margin:0;padding:14px 16px;border:1px solid var(--line);border-radius:10px;background:var(--surface);"
    "display:grid;grid-template-columns:auto 1fr;gap:5px 14px;font-size:13px}"
    ".pj-facts dt{color:var(--muted)}.pj-facts dd{margin:0;font-family:var(--font-mono);text-align:right}"
    ".pj-story{font-size:17px;line-height:1.55;max-width:820px;color:var(--text)}"
    ".pj-steps{margin:0;padding:0 0 0 18px;color:var(--text-soft)}.pj-steps li{margin:4px 0}"
    "@media(max-width:640px){.pj-trades table,.pj-trades tbody{display:block;min-width:0}.pj-trades thead{display:none}"
    ".pj-trades tr{display:grid;grid-template-columns:auto auto 1fr auto;gap:6px 10px;align-items:center;border-bottom:1px solid var(--line)}"
    ".pj-trades tr td{border:0;padding:10px 12px 0}.pj-trades .pj-why{order:4;grid-column:1/-1;min-width:0;padding-top:0}"
    ".pj-trades .pj-c-res{order:2}.pj-trades .pj-c-net{order:3;text-align:right}.pj-trades .pj-c-more{order:5;grid-column:1/-1;padding:0 12px 10px}"
    ".pj-trades .pj-day td{grid-column:1/-1;padding:7px 12px}}"
)
JOURNAL_STYLE = CSS + EXTRA_CSS + JOURNAL_CSS
NEVER_TRIGGERED = ("INVALIDATED", "REPLACED", "EXPIRED")


def journal_href(key: str) -> str:
    return "/journal" if key == DEFAULT_JOURNAL else f"/journal?rule={key}"


def journal_csp() -> str:
    """The journal pages have their own style block (no script at all), so they get their own hash."""
    style_hash = base64.b64encode(hashlib.sha256(JOURNAL_STYLE.encode()).digest()).decode()
    return (f"default-src 'none'; style-src 'sha256-{style_hash}'; script-src 'none'; connect-src 'none'; img-src 'self' data:; "
            "font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def _tone(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "pj-flat"
    return "pj-pos" if value > 0.005 else "pj-neg" if value < -0.005 else "pj-flat"


def _closed_at(entry: Mapping[str, Any]) -> Any:
    return entry.get("closed_at") or entry.get("filled_at") or entry.get("created_at")


def _sort_key(entry: Mapping[str, Any], field: str) -> float:
    moment = _time(entry.get(field)) if entry.get(field) else None
    return moment.timestamp() if moment else 0.0


def _pct(a: Any, b: Any) -> str:
    try:
        return f"{abs(float(a) - float(b)) / float(b) * 100:.2f} %"
    except (TypeError, ValueError, ZeroDivisionError):
        return "–"


def explain(entry: Mapping[str, Any]) -> str:
    """One or two plain sentences: what TIM planned and what happened."""
    side = "Long" if entry.get("direction") == "LONG" else "Short"
    setup = SETUP_EN.get(str(entry.get("scenario_type")), "a setup from TIM's chart analysis")
    market = MARKET_EN.get(str(entry.get("market_state")), "")
    plan = (f"{side} on {setup}" + (f" in a {market}" if market else "")
            + f": entry {_price(entry.get('fill_price') or entry.get('entry'))}, stop {_price(entry.get('stop'))} "
            f"({_pct(entry.get('stop'), entry.get('entry'))} away).")
    status, reason = entry.get("status"), str(entry.get("exit_reason") or "")
    hits = len(entry.get("tp_hits") or [])
    targets = entry.get("targets") or []
    if status == "OPEN":
        return plan + " Waiting for price to reach the entry."
    if status == "FILLED":
        return plan + (f" In the trade, {hits} of 3 targets reached." if hits else " In the trade.")
    if status == "INVALIDATED":
        return plan + " Cancelled before the entry: a close beyond the invalidation level."
    if status == "REPLACED":
        return plan + " Never filled: TIM drew new levels in the same direction."
    if status == "EXPIRED":
        return plan + " Never filled: price did not come back to the entry in time."
    if reason == "STOP" and not hits:
        what = "Price went against the plan and hit the stop."
    elif reason == "TP3":
        what = "All three targets were reached."
    elif reason in ("BREAK_EVEN", "BREAK_EVEN_COSTS") or (reason in ("COST_STOP", "STOP") and hits):
        first = f" at {_price(targets[0])}" if targets else ""
        what = f"A third was taken at TP1{first}; the rest closed at break-even" + (" + costs." if reason != "BREAK_EVEN" else ".")
    elif reason == "COST_STOP":
        what = "TIM moved the stop to break-even + costs to protect the trade; price came back and closed it there."
    elif reason == "TRAIL_STOP":
        what = f"TIM trailed the stop behind the latest swing to lock in profit; it closed the rest ({hits} of 3 targets hit)."
    elif reason == "TIMEOUT":
        what = "Closed at the time limit without reaching the targets."
    elif reason == "INVALIDATION":
        what = "A close beyond the invalidation level ended the trade."
    else:
        what = "Closed."
    return f"{plan} {what}"


def _curve(trades: list[Mapping[str, Any]]) -> str:
    """Cumulative net R over the counted closed trades, oldest first, as a small inline SVG."""
    if not trades:
        return ""
    points, total = [0.0], 0.0
    for entry in trades:
        total += float(entry.get("net_r") or 0.0)
        points.append(total)
    width, height, pad = 600.0, 150.0, 12.0
    low, high = min(points + [0.0]), max(points + [0.0])
    span = (high - low) or 1.0
    step = (width - 2 * pad) / max(len(points) - 1, 1)

    def y(value: float) -> float:
        return round(pad + (high - value) / span * (height - 2 * pad), 1)

    coords = [(round(pad + i * step, 1), y(v)) for i, v in enumerate(points)]
    line = " ".join(f"{x},{yy}" for x, yy in coords)
    colour = "#35d39a" if total > 0 else "#ff6577" if total < 0 else "#8491a3"
    zero = y(0.0)
    return ("<div class='pj-curve'><p>Net result after each closed trade (R, counted trades only, oldest left)</p>"
            f"<svg viewBox='0 0 {int(width)} {int(height)}' preserveAspectRatio='none' role='img' "
            f"aria-label='Cumulative net result: {_safe(_r(total))} after {len(trades)} trades'>"
            f"<line x1='{pad}' x2='{width - pad}' y1='{zero}' y2='{zero}' stroke='#344154' stroke-dasharray='4 4' stroke-width='1'/>"
            f"<polyline points='{line}' fill='none' stroke='{colour}' stroke-width='2.5' stroke-linejoin='round' vector-effect='non-scaling-stroke'/>"
            f"<circle cx='{coords[-1][0]}' cy='{coords[-1][1]}' r='4' fill='{colour}'/></svg></div>")


def _tab(key: str, name: str, text: str, journal: Mapping[str, Any] | None, active: bool, small: bool = False) -> str:
    stats = summary(journal or {})
    if stats["closed"]:
        number = (f"<span class='pj-tab__num {_tone(stats['sum_net_r'])}'>{_safe(_r(stats['sum_net_r']))}</span>"
                  f"<small>{stats['closed']} closed trade{'s' if stats['closed'] != 1 else ''}</small>")
    else:
        number = ("<span class='pj-tab__num pj-flat'>–</span><small>"
                  + ("no closed trade yet" if (journal or {}).get("entries") else "no plan yet") + "</small>")
    current = " aria-current='page'" if active else ""
    return (f"<a class='pj-tab{' pj-tab--active' if active else ''}' href='{journal_href(key)}'{current}>"
            f"<b>{_safe(name)}</b>" + ("" if small else f"<small>{_safe(text)}</small>") + f"{number}</a>")


def _kpis(stats: Mapping[str, Any], waiting: int, in_trade: int) -> str:
    closed = stats["closed"]
    net = stats["sum_net_r"] if closed else None
    per = stats["sum_net_r"] / closed if closed else None
    rate = f"{stats['net_wins'] / closed * 100:.0f} %" if closed else "–"
    tiles = (
        ("Net result", f"<strong class='{_tone(net)}'>{_safe(_r(net))}</strong>", "after fees and slippage"),
        ("Closed trades", f"<strong>{closed}</strong>", f"{stats['net_wins']} won · {closed - stats['net_wins']} lost or flat" if closed else "none yet"),
        ("Win rate", f"<strong>{_safe(rate)}</strong>", "share of trades with net R above 0"),
        ("Per trade", f"<strong class='{_tone(per)}'>{_safe(_r(per))}</strong>", "average net R"),
        ("Open now", f"<strong>{waiting + in_trade}</strong>", f"{in_trade} in trade · {waiting} waiting for entry"),
    )
    return "<div class='pj-kpis'>" + "".join(
        f"<div class='pj-kpi'><span>{label}</span>{value}<small>{_safe(note)}</small></div>" for label, value, note in tiles) + "</div>"


def _direction(entry: Mapping[str, Any]) -> str:
    direction = str(entry.get("direction") or "–")
    return f"<span class='pj-dir pj-dir--{_safe(direction.lower())}'>{_safe(direction)}</span>"


def _targets(entry: Mapping[str, Any]) -> str:
    return " · ".join(f"{_price(t)}" for t in entry.get("targets") or [] if t is not None) or "–"


def _detail_href(key: str, entry: Mapping[str, Any]) -> str:
    return f"/journal/trade?rule={key}&amp;id={_safe(str(entry.get('id') or ''))}"


def _now_card(key: str, entry: Mapping[str, Any]) -> str:
    direction = str(entry.get("direction") or "").lower()
    state = "in trade" if entry.get("status") == FILLED else "waiting for entry"
    since = entry.get("filled_at") if entry.get("status") == FILLED else entry.get("created_at")
    return (f"<article class='pj-plan pj-plan--{_safe(direction)}'><header>{_direction(entry)}<span class='cc-note'>{_safe(state)}</span></header>"
            f"<p class='cc-note'>{_safe(explain(entry))}</p>"
            f"<dl><dt>Since</dt><dd>{_safe(_when(since))}</dd><dt>Entry</dt><dd>{_safe(_price(entry.get('entry')))}</dd>"
            f"<dt>Stop</dt><dd>{_safe(_price(entry.get('stop')))}</dd><dt>Targets</dt><dd>{_safe(_targets(entry))}</dd></dl>"
            f"<p class='cc-note'><a href='{_detail_href(key, entry)}'>Details</a></p></article>")


def _result(net: Any) -> str:
    if not isinstance(net, (int, float)):
        return "<span class='pj-res pj-res--be'>–</span>"
    kind, word = ("win", "Win") if net > 0.005 else ("loss", "Loss") if net < -0.005 else ("be", "Flat")
    return f"<span class='pj-res pj-res--{kind}'>{word}</span>"


def _exit(entry: Mapping[str, Any]) -> str:
    reason = entry.get("exit_reason")
    return EXIT_EN.get(str(reason), str(reason).lower()) if reason else "–"


def _trade_rows(key: str, trades: list[Mapping[str, Any]]) -> str:
    rows, day = [], None
    for entry in trades:
        moment = _time(_closed_at(entry))
        label = moment.astimezone(LOCAL).strftime("%a %d %b %Y") if moment else "–"
        if label != day:
            day = label
            rows.append(f"<tr class='pj-day'><td colspan='6'>{_safe(label)}</td></tr>")
        rows.append(
            f"<tr><td>{_safe(moment.astimezone(LOCAL).strftime('%H:%M') if moment else '–')}</td><td>{_direction(entry)}</td>"
            f"<td class='pj-why'>{_safe(explain(entry))}</td><td class='pj-c-res'>{_result(entry.get('net_r'))}</td>"
            f"<td class='mono pj-c-net {_tone(entry.get('net_r'))}'>{_safe(_r(entry.get('net_r')))}</td>"
            f"<td class='pj-c-more'><a href='{_detail_href(key, entry)}'>Details</a></td></tr>")
    return "".join(rows)


def _table(head: tuple[str, ...], rows: str, kind: str = "", wide: tuple[str, ...] = ()) -> str:
    cells = "".join(f"<th class='pj-wide'>{h}</th>" if h in wide else f"<th>{h}</th>" for h in head)
    return (f"<div class='table-wrap pj-table {kind}'><table><thead><tr>" + cells
            + f"</tr></thead><tbody>{rows}</tbody></table></div>")


def _more(title: str, note: str, body: str, count: int) -> str:
    return (f"<details class='pj-more'><summary>{_safe(title)} <small>({count})</small></summary>"
            f"<div class='pj-more__body'><p>{_safe(note)}</p>{body}</div></details>")


def _normal(journals: Mapping[str, Mapping[str, Any]], shown: str) -> tuple[dict[str, Mapping[str, Any]], str]:
    keyed = {ALIASES.get(key, key): value for key, value in journals.items()}
    shown = ALIASES.get(shown, shown)
    if shown not in JOURNAL_KEYS:
        shown = DEFAULT_JOURNAL if DEFAULT_JOURNAL in keyed or not keyed else next(iter(keyed))
    return keyed, shown


def journal_page(journals: Mapping[str, Mapping[str, Any]], shown: str = DEFAULT_JOURNAL) -> str:
    """One journal at a time: headline numbers, result curve, open plans, closed trades explained in a sentence;
    the rest folded away. Every trade links to its detail page."""
    journals, shown = _normal(journals, shown)
    horizon_tabs = "".join(_tab(key, name, text, journals.get(key), key == shown) for key, name, text in HORIZONS_EN
                           if key in journals or key == shown)
    earlier_tabs = "".join(_tab(key, name, text, journals.get(key), key == shown, small=True) for key, name, text in EARLIER_EN
                           if key in journals)
    journal = journals.get(shown) or {}
    name, rule_text = next(((n, t) for k, n, t in HORIZONS_EN + EARLIER_EN if k == shown), ("", ""))
    body = _hero("Paper journal", "TIM writes down long and short plans by itself and follows each one on 1-minute candles, "
                 "in three timeframes. Paper only, no orders. 1 R = distance from entry to stop; net = after 0.05 % fees and "
                 "0.03 % slippage per side.")
    if horizon_tabs:
        body += f"<p class='pj-label'>Timeframes</p><nav class='pj-tabs' aria-label='Timeframe'>{horizon_tabs}</nav>"
    if earlier_tabs:
        body += f"<p class='pj-label'>Earlier test versions (30m)</p><nav class='pj-tabs pj-tabs--small' aria-label='Earlier versions'>{earlier_tabs}</nav>"

    if str(journal.get("integrity") or "").startswith("LOG_BROKEN"):
        body += "<section class='cc-section'><p class='pj-empty'>Journal locked: the event log needs a check.</p></section>"
        return shell("Paper journal", "/journal", body, extra_css=JOURNAL_CSS)

    every = list(journal.get("entries") or [])
    counted = [e for e in every if not e.get("excluded")]
    excluded = [e for e in every if e.get("excluded")]
    trades = sorted((e for e in counted if e.get("status") == "CLOSED" and e.get("gross_r") is not None),
                    key=lambda e: _sort_key(e, "closed_at") or _sort_key(e, "created_at"))
    now = sorted((e for e in counted if e.get("status") in (OPEN, FILLED)), key=lambda e: _sort_key(e, "created_at"), reverse=True)
    never = sorted((e for e in counted if e.get("status") in NEVER_TRIGGERED), key=lambda e: _sort_key(e, "created_at"), reverse=True)
    stats = summary(journal)
    in_trade = sum(e.get("status") == FILLED for e in now)

    body += (f"<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>{_safe(name)}</p>"
             f"<h2>Result so far</h2><p class='cc-section__note'>{_safe(rule_text)}. Few closed trades say little; "
             "the numbers only mean something after many. "
             f"<a href='/chart?tf={CHART_TF[shown]}'>See the plans on the chart</a>.</p></div></div>"
             f"{_kpis(stats, len(now) - in_trade, in_trade)}{_curve(trades)}</section>")

    cards = "".join(_now_card(shown, e) for e in now) or "<p class='pj-empty'>No open plan right now.</p>"
    body += ("<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Now</p>"
             f"<h2>Open plans</h2></div></div><div class='pj-now'>{cards}</div></section>")

    latest = list(reversed(trades))[:100]
    empty = "No plans yet." if not every else "No closed trade yet."
    trade_table = (_table(("Closed", "Side", "What happened", "Result", "Net R", ""), _trade_rows(shown, latest), "pj-trades")
                   if latest else f"<p class='pj-empty'>{empty}</p>")
    body += ("<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Trades</p>"
             f"<h2>Closed trades{' (latest 100)' if len(trades) > 100 else ''}</h2>"
             "<p class='cc-section__note'>Newest first, Central European time. Details shows every number of a trade.</p></div></div>"
             f"{trade_table}")
    if never:
        rows = "".join(_plan_row(e, shown) for e in never[:100])
        body += _more("Plans that never triggered", "Written down, but price never reached the entry, a newer plan replaced it, "
                      "or it ran out of time. They cost nothing and are not counted.", _plan_table(rows), len(never))
    if excluded:
        rows = "".join(_plan_row(e, shown) for e in sorted(excluded, key=lambda e: _sort_key(e, "created_at"), reverse=True)[:100])
        body += _more("Corrected entries, not counted", "Booking errors found in review (plans recorded after their stop had "
                      "already been hit, one double booking). They stay listed for transparency but are left out of every number.",
                      _plan_table(rows), len(excluded))
    body += "</section>"

    rows = []
    for key, rname, _ in HORIZONS_EN + EARLIER_EN:
        other = journals.get(key)
        if other is None:
            continue
        s = summary(other)
        rate = f"{s['win_rate'] * 100:.0f} %" if s["win_rate"] is not None else "–"
        per = s["sum_net_r"] / s["closed"] if s["closed"] else None
        rows.append(f"<tr><td><a href='{journal_href(key)}'>{_safe(rname)}</a></td><td>{s['plans']}</td><td>{s['closed']}</td>"
                    f"<td>{_safe(rate)}</td><td class='mono {_tone(s['sum_net_r'] if s['closed'] else None)}'>{_safe(_r(s['sum_net_r'] if s['closed'] else None))}</td>"
                    f"<td class='mono'>{_safe(_r(per))}</td><td class='mono'>{_safe(_r(s['sum_r'] if s['closed'] else None))}</td>"
                    f"<td>{s['excluded']['plans']}</td></tr>")
    body += ("<section class='cc-section'>" + _more(
        "Compare all journals", "Same market, same candles, different timeframes and rules. Win rate here counts gross R above 0.",
        _table(("Journal", "Plans", "Closed", "Win rate", "Net sum", "Net per trade", "Gross sum", "Not counted"), "".join(rows)), len(rows))
        + f"<p class='cc-note'>Raw data as JSON: <a href='/api/plan-journal?rule={shown}'>{_safe(name)}</a>.</p></section>")
    return shell("Paper journal", "/journal", body, extra_css=JOURNAL_CSS)


def _plan_table(rows: str) -> str:
    return _table(("Created", "Plan", "Entry", "Stop", "Targets", "Status", "Net R", ""), rows)


def _plan_row(entry: Mapping[str, Any], key: str = DEFAULT_JOURNAL) -> str:
    status = STATUS_EN.get(str(entry.get("status")), str(entry.get("status") or "–").lower())
    if entry.get("exit_reason"):
        status += f" ({EXIT_EN.get(str(entry['exit_reason']), str(entry['exit_reason']).lower())})"
    if entry.get("excluded"):
        status = "not counted (corrected) · " + status
    targets = " · ".join(f"TP{i} {_price(t)}" for i, t in enumerate(entry.get("targets") or [], start=1) if t is not None) or "–"
    return (f"<tr><td>{_safe(_when(entry.get('created_at')))}</td><td>{_direction(entry)}</td>"
            f"<td class='mono'>{_safe(_price(entry.get('entry')))}</td><td class='mono'>{_safe(_price(entry.get('stop')))}</td>"
            f"<td>{_safe(targets)}</td><td>{_safe(status)}</td>"
            f"<td class='mono'>{_safe(_r(entry.get('net_r')))}</td><td><a href='{_detail_href(key, entry)}'>Details</a></td></tr>")


# --- one trade -----------------------------------------------------------------

def _steps(entry: Mapping[str, Any]) -> list[tuple[Any, str]]:
    """What happened, in time order."""
    steps: list[tuple[Any, str]] = [(entry.get("created_at"), f"Plan written at the {entry.get('timeframe') or ''} close.")]
    if entry.get("armed_at"):
        steps.append((entry["armed_at"], "Price broke through the entry first; the limit waited for the retest."))
    if entry.get("filled_at"):
        steps.append((entry["filled_at"], f"Filled at {_price(entry.get('fill_price') or entry.get('entry'))}."))
    for index, moment in enumerate(entry.get("tp_hits") or [], start=1):
        target = (entry.get("targets") or [None] * 3)[index - 1] if index <= len(entry.get("targets") or []) else None
        steps.append((moment, f"TP{index} reached ({_price(target)}): a third taken."))
    if entry.get("tim_verdict_at") and entry.get("tim_verdict"):
        verdict = "protect the trade" if entry["tim_verdict"] == "SICHERN" else "hold"
        steps.append((entry["tim_verdict_at"], f"TIM judged the running trade: {verdict}."))
    moves = entry.get("stop_path") or ([[entry["cost_stop_at"], entry["cost_stop"], entry.get("cost_stop_kind")]]
                                       if entry.get("cost_stop_at") and entry.get("cost_stop") is not None else [])
    for at, price, kind in moves:
        where = "behind the latest swing" if str(kind).upper() == "SWING" else "to break-even + costs"
        steps.append((at, f"Stop moved {where}: {_price(price)}."))
    review = entry.get("stop_review") or {}
    if review.get("checked_through"):
        steps.append((review["checked_through"], "The stop was only a wick: price closed back beyond it right after." if review.get("wick")
                      else "Not a wick: price stayed beyond the stop after it was hit."))
    if entry.get("closed_at"):
        end = STATUS_EN.get(str(entry.get("status")), "closed")
        if entry.get("status") == "CLOSED":
            end = f"Closed ({_exit(entry)}) at {_price(entry.get('exit_price'))}: {_r(entry.get('net_r'))} net."
        steps.append((entry["closed_at"], end[:1].upper() + end[1:]))
    return sorted(steps, key=lambda item: _sort_key({"t": item[0]}, "t"))


def _facts(title: str, pairs: list[tuple[str, str]]) -> str:
    return f"<dl aria-label='{_safe(title)}'>" + "".join(f"<dt>{_safe(k)}</dt><dd>{_safe(v)}</dd>" for k, v in pairs) + "</dl>"


def trade_page(journals: Mapping[str, Mapping[str, Any]], key: str, trade_id: str) -> str | None:
    """Every number of one plan. None when the journal or the id is unknown."""
    journals, key = _normal(journals, key)
    if not _ID.match(trade_id or ""):
        return None
    entry = next((e for e in (journals.get(key) or {}).get("entries") or [] if e.get("id") == trade_id), None)
    if entry is None:
        return None
    name = next((n for k, n, _ in HORIZONS_EN + EARLIER_EN if k == key), key)
    side = "Long" if entry.get("direction") == "LONG" else "Short"
    status = STATUS_EN.get(str(entry.get("status")), str(entry.get("status") or "").lower())
    head = f"{side} · {name} · {status}" + (f" · {_r(entry.get('net_r'))}" if entry.get("net_r") is not None else "")
    targets = entry.get("targets") or []
    plan = [("Created", _when(entry.get("created_at"))), ("Entry", _price(entry.get("entry"))),
            ("Entry zone", f"{_price(entry.get('entry_low'))} – {_price(entry.get('entry_high'))}"),
            ("Stop", f"{_price(entry.get('stop'))} ({_pct(entry.get('stop'), entry.get('entry'))})"),
            *[(f"TP{i}", _price(t)) for i, t in enumerate(targets, start=1)],
            ("Invalidation", f"close {entry.get('invalidation_side') or ''} {_price(entry.get('invalidation_level'))}")]
    result = [("Filled", _when(entry.get("filled_at"))), ("Fill price", _price(entry.get("fill_price"))),
              ("Closed", _when(entry.get("closed_at"))), ("Exit", f"{_exit(entry)} at {_price(entry.get('exit_price'))}"),
              ("Gross", _r(entry.get("gross_r"))), ("Fees", _r(-(entry.get("fee_r") or 0)) if entry.get("fee_r") is not None else "–"),
              ("Slippage", _r(-(entry.get("slippage_r") or 0)) if entry.get("slippage_r") is not None else "–"),
              ("Net", _r(entry.get("net_r"))), ("Best during trade", _r(entry.get("max_favorable_r"))),
              ("Worst during trade", _r(entry.get("max_adverse_r")))]
    context = [("Timeframe", str(entry.get("timeframe") or "–")),
               ("Setup", SETUP_EN.get(str(entry.get("scenario_type")), str(entry.get("scenario_type") or "–")).removeprefix("a ").removeprefix("an ")),
               ("Market", MARKET_EN.get(str(entry.get("market_state")), str(entry.get("market_state") or "–")).lower()),
               ("Setup grade", f"{entry.get('setup_grade') or '–'} (heuristic)"), ("Data quality", str(entry.get("data_quality") or "–").lower()),
               ("Counted", "no, corrected" if entry.get("excluded") else "yes"), ("Id", str(entry.get("id")))]
    steps = "".join(f"<li><span class='mono'>{_safe(_when(moment))}</span> {_safe(text)}</li>" for moment, text in _steps(entry))
    body = _hero(head, "One plan from TIM's paper journal. Paper only, no orders.")
    body += (f"<section class='cc-section'><p class='pj-story'>{_safe(explain(entry))}</p>"
             f"<p class='cc-note'><a href='{journal_href(key)}'>← back to {_safe(name)}</a> · "
             f"<a href='/chart?tf={CHART_TF.get(key, '30m')}'>see it on the chart</a></p></section>")
    body += ("<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Numbers</p><h2>Key data</h2></div></div>"
             f"<div class='pj-facts'>{_facts('Plan', plan)}{_facts('Result', result)}{_facts('Context', context)}</div></section>")
    body += ("<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Timeline</p><h2>What happened</h2>"
             "<p class='cc-section__note'>Central European time.</p></div></div>"
             f"<ol class='pj-steps'>{steps}</ol></section>")
    return shell("Paper trade", "/journal", body, extra_css=JOURNAL_CSS)
