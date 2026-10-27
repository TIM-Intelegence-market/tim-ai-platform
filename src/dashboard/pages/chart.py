"""TIM chart page: interactive chart (BTC/ETH/SOL, every timeframe) plus TIM's analysis for BTC.

The top chart is TradingView Lightweight Charts (Apache 2.0, served locally) fed by
/api/chart/live; every level is a labelled segment from the moment it formed. Below,
for BTC only: analysis card, plan view (SVG with zones, stop, targets) and tables.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from pathlib import Path

from src.dashboard.chart_live import DEFAULT_SYMBOL, GROUP_STYLE, SYMBOL_NAMES, SYMBOLS, VIEW_TIMEFRAMES
from src.dashboard.chart_model import CHART_TIMEFRAMES, DEFAULT_TIMEFRAME, build_chart_model
from src.dashboard.helpers import _safe
from src.dashboard.layout import _content_security_policy, _hero, _layout, _strip_states

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
LIB_PATH = "/assets/chart/lightweight-charts-4.2.3.js"
APP_PATH = "/assets/chart/tim_chart.js"
CHART_SCRIPTS = {
    LIB_PATH: (_ASSETS / "vendor" / "lightweight-charts-4.2.3.standalone.production.js").read_bytes(),
    APP_PATH: (_ASSETS / "tim_chart.js").read_bytes(),
}
# Same policy as every page, plus the two local script files above ('self'; nothing from outside).
CHART_CSP = _content_security_policy().replace("script-src ", "script-src 'self' ", 1)

WIDTH, HEIGHT = 1200, 600
PLOT_LEFT, PLOT_RIGHT = 12, 760
PROFILE_LEFT, PROFILE_RIGHT = 764, 850
LABEL_X = 856
TOP, BOTTOM = 18, 558
LABEL_GAP = 13
ZONE_SPACE = 260  # px right of the last candle reserved for written-out scenario plans
ZONE_SPACE_EMPTY = 24  # without any plan the candles use the width
MAX_MAIN_LEVELS = 8  # main levels (day, week, naked POC) drawn by default, nearest to price first
MAX_MINOR_LEVELS = 4  # session / IB / running POCs, drawn as short stubs at the right edge
MAX_STRUCTURE = 3  # newest BOS/MSS marks drawn
MINOR_STUB = 150  # px a minor level reaches left of the profile
LEVEL_MERGE = 0.0004  # main levels closer than 0.04 % share one line
PLAN_TEXT_CHARS = 44  # plan texts are cut to the zone width; the full text is the tooltip
LEVEL_KINDS = (  # first matching source part wins; order = rank
    ("naked", ("unberührter Tages-POC",)),
    ("week", ("Vorwoche", "Profil Vorwoche")),
    ("day", ("Vortag", "Profil Vortag")),
)
SCENARIO_NAMES = {
    "BREAKOUT_ACCEPTANCE": "Ausbruch + Annahme",
    "LEVEL_REACTION": "Level-Reaktion",
    "LIQUIDITY_SWEEP_REVERSAL": "Sweep + Rückeroberung",
    "REJECTION_FAILED_BREAKOUT": "Ablehnung / Fehlausbruch",
    "BALANCE_ROTATION": "Rotation in der Range",
    "VALUE_REVERSION": "Rückkehr zum Value",
}


def _price(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if value < 1000 else f"{value:,.0f}".replace(",", ".")


def _nice_ticks(low: float, high: float, count: int = 7) -> list[float]:
    span = max(high - low, 1e-9)
    raw = span / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next((f * magnitude for f in (1, 2, 2.5, 5, 10) if raw <= f * magnitude), 10 * magnitude)
    first = math.ceil(low / step) * step
    ticks, value = [], first
    while value <= high + 1e-9:
        ticks.append(round(value, 8))
        value += step
    return ticks


def level_kind(source: str | None) -> str:
    """day / week / naked for main levels, minor for sessions, IB and running POCs."""
    parts = str(source or "").split(" · ")
    for kind, sources in LEVEL_KINDS:
        if any(part in sources for part in parts):
            return kind
    return "minor"


def short_label(label: str) -> str:
    """Shorter chart label: "PDH · Vortag Hoch · Poor High" -> "PDH · Poor"."""
    for long, short in ((" · Vortag Hoch", ""), (" · Vortag Tief", ""), (" · Vorwoche Hoch", ""), (" · Vorwoche Tief", ""),
                        ("Poor High", "Poor"), ("Poor Low", "Poor"), (" (laufend)", " lfd."), ("Vorwoche ", "Vorw. ")):
        label = label.replace(long, short)
    return label


def chart_levels(references: list[dict[str, Any]], last: float | None, low: float, high: float, show_all: bool = False) -> dict[str, Any]:
    """Which reference levels the chart draws.

    By default the MAX_MAIN_LEVELS main levels and MAX_MINOR_LEVELS minor levels
    nearest to price inside the price window; ``show_all`` draws every level in
    the window. Main levels outside the window are named at the edge (nearest
    two per side). Returns {"main", "minor", "above", "below", "hidden"}."""
    anchor = last if last is not None else (low + high) / 2
    inside = [dict(r, kind=level_kind(r.get("source"))) for r in references if r.get("price") is not None and low <= r["price"] <= high]
    main = sorted((r for r in inside if r["kind"] != "minor"), key=lambda r: abs(r["price"] - anchor))
    minor = sorted((r for r in inside if r["kind"] == "minor"), key=lambda r: abs(r["price"] - anchor))
    if not show_all:
        main, minor = main[:MAX_MAIN_LEVELS], minor[:MAX_MINOR_LEVELS]
    hidden = len(inside) - len(main) - len(minor)
    rank = [kind for kind, _ in LEVEL_KINDS]
    merged: list[dict[str, Any]] = []
    for level in sorted(main, key=lambda r: r["price"]):
        if merged and level["price"] - merged[-1]["low"] <= merged[-1]["low"] * LEVEL_MERGE:
            place = merged[-1]
            place["label"] = f"{place['label']} + {level['label']}"
            if rank.index(level["kind"]) < rank.index(place["kind"]):
                place["kind"] = level["kind"]
        else:
            merged.append({**level, "low": level["price"]})
    main = merged
    outside = [r for r in references if r.get("price") is not None and level_kind(r.get("source")) != "minor" and not low <= r["price"] <= high]
    above = sorted((r for r in outside if r["price"] > high), key=lambda r: r["price"])[:2]
    below = sorted((r for r in outside if r["price"] < low), key=lambda r: -r["price"])[:2]
    return {"main": main, "minor": minor, "above": above, "below": below, "hidden": hidden}


def _time_label(value: str, timeframe: str) -> str:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return ""
    return moment.strftime("%d.%m.%y") if timeframe in ("1d", "1w", "1M") else moment.strftime("%d.%m. %H:%M")


def _spread_labels(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Push right-side labels apart so they stay readable; keeps price order."""
    labels = sorted(labels, key=lambda item: item["y"])
    for index in range(1, len(labels)):
        if labels[index]["ly"] - labels[index - 1]["ly"] < LABEL_GAP:
            labels[index]["ly"] = labels[index - 1]["ly"] + LABEL_GAP
    overflow = labels[-1]["ly"] - (BOTTOM + 4) if labels else 0
    if overflow > 0:
        for item in labels:
            item["ly"] -= overflow
        for index in range(len(labels) - 2, -1, -1):
            if labels[index + 1]["ly"] - labels[index]["ly"] < LABEL_GAP:
                labels[index]["ly"] = labels[index + 1]["ly"] - LABEL_GAP
    return labels


def _chart_svg(model: dict[str, Any], show_all: bool = False) -> str:
    candles = model["candles"]
    levels = model["levels"]
    profile = model.get("profile") or {}
    analysis = model.get("analysis") or {}
    timeframe = model["timeframe"]
    low = min(c["low"] for c in candles)
    high = max(c["high"] for c in candles)
    span = max(high - low, high * 0.001)

    # Levels widen the price axis when they are close; far ones are named at the edge instead.
    candidates = [profile.get("vah"), profile.get("val"), profile.get("poc")] + [b["level"] for b in model.get("bos", [])]
    level_plans = (model.get("level_plans") or {}).get("plans") or []
    for scenario in [*(analysis.get("scenarios") or []), *level_plans]:
        candidates += [scenario.get("entry_low"), scenario.get("entry_high"), scenario.get("trigger")]
        preview = scenario.get("preview") or {}
        candidates += [preview.get("stop")] + list((preview.get("targets") or [])[:1])
    near = [v for v in candidates if v is not None and low - span * 0.6 <= v <= high + span * 0.6]
    y_low = min([low] + near) - span * 0.03
    y_high = max([high] + near) + span * 0.03

    def y(price: float) -> float:
        return TOP + (y_high - price) * (BOTTOM - TOP) / (y_high - y_low)

    def visible(price: float | None) -> bool:
        return price is not None and y_low <= price <= y_high

    count = len(candles)
    has_plans = bool(level_plans) or any(
        s.get("entry_low") is not None or s.get("trigger") is not None or (s.get("preview") or {}).get("stop") is not None
        for s in analysis.get("scenarios") or [])
    space = ZONE_SPACE if has_plans else ZONE_SPACE_EMPTY
    slot = (PLOT_RIGHT - PLOT_LEFT - space) / count  # free space right of the last candle for zones
    body_w = max(1.0, slot * 0.64)

    def x(index: int) -> float:
        return PLOT_LEFT + slot * (index + 0.5)

    parts: list[str] = [f"<rect x='{PLOT_LEFT}' y='{TOP}' width='{PROFILE_RIGHT - PLOT_LEFT}' height='{BOTTOM - TOP}' class='tc-frame'/>"]
    labels: list[dict[str, Any]] = []
    above: list[str] = []
    below: list[str] = []

    def label(price: float, text: str, cls: str) -> None:
        labels.append({"y": y(price), "ly": y(price) + 4, "text": text, "cls": cls})

    def hline(price: float | None, cls: str, text: str, start: float = PLOT_LEFT) -> None:
        if price is None:
            return
        if not visible(price):
            (above if price > y_high else below).append(f"{text} {_price(price)}")
            return
        parts.append(f"<line x1='{start:.1f}' x2='{PROFILE_RIGHT}' y1='{y(price):.1f}' y2='{y(price):.1f}' class='{cls}'/>")
        label(price, f"{text} {_price(price)}", cls)

    for tick in _nice_ticks(y_low, y_high):
        parts.append(f"<line x1='{PLOT_LEFT}' x2='{PROFILE_RIGHT}' y1='{y(tick):.1f}' y2='{y(tick):.1f}' class='tc-grid'/>")
        parts.append(f"<text x='{PLOT_LEFT + 4}' y='{y(tick) - 3:.1f}' class='tc-axis'>{_safe(_price(tick))}</text>")

    step = max(1, count // 6)
    for index in range(step // 2, count, step):  # first label away from the left edge, so none overlap
        parts.append(f"<line x1='{x(index):.1f}' x2='{x(index):.1f}' y1='{TOP}' y2='{BOTTOM}' class='tc-grid'/>")
        parts.append(f"<text x='{x(index):.1f}' y='{BOTTOM + 16}' text-anchor='middle' class='tc-axis'>{_safe(_time_label(candles[index]['open_time'], timeframe))}</text>")

    # Value area band and volume profile bars.
    if profile.get("vah") is not None and profile.get("val") is not None:
        top_price, bottom_price = min(profile["vah"], y_high), max(profile["val"], y_low)
        if top_price > bottom_price:
            parts.append(f"<rect x='{PLOT_LEFT}' y='{y(top_price):.1f}' width='{PROFILE_RIGHT - PLOT_LEFT}' height='{y(bottom_price) - y(top_price):.1f}' class='tc-value-area'/>")
    bins = profile.get("bins") or []
    if bins:
        peak = max(b["volume"] for b in bins) or 1
        for item in bins:
            lo, hi = max(item["low"], y_low), min(item["high"], y_high)
            if hi <= lo:
                continue
            width = (PROFILE_RIGHT - PROFILE_LEFT) * item["volume"] / peak
            inside = profile.get("val") is not None and profile["val"] <= item["low"] and item["high"] <= profile["vah"]
            parts.append(f"<rect x='{PROFILE_RIGHT - width:.1f}' y='{y(hi):.1f}' width='{width:.1f}' height='{max(0.6, y(lo) - y(hi) - 0.4):.1f}' class='tc-profile{' tc-profile--va' if inside else ''}'/>")

    # Past NY-open block windows inside the visible time range.
    first_time, last_time = candles[0]["open_time"], candles[-1]["open_time"]
    for window in model.get("events", []):
        if window["end"] < first_time or window["start"] > last_time:
            continue
        x1 = next((x(i) - slot / 2 for i, c in enumerate(candles) if c["open_time"] >= window["start"]), x(count - 1))
        x2 = next((x(i) - slot / 2 for i, c in enumerate(candles) if c["open_time"] >= window["end"]), x(count - 1) + slot / 2)
        parts.append(f"<rect x='{x1:.1f}' y='{TOP}' width='{max(2.0, x2 - x1):.1f}' height='{BOTTOM - TOP}' class='tc-block'/>")
        event_date = datetime.fromisoformat(window["open"]).strftime("%d.%m.")
        parts.append(f"<text x='{x1 + 2:.1f}' y='{TOP + 50}' class='tc-block-text'><title>NYSE 09:30 America/New_York · {_safe(window['open'])}</title>NY {event_date}</text>")

    # Scenarios written out like a hand-drawn plan: zone with text, stop, invalidation, targets.
    zone_x = x(count - 1) + slot + 8
    zone_w = PROFILE_RIGHT - zone_x
    targets_above: list[str] = []
    targets_below: list[str] = []

    plan_lines: dict[tuple[str, float], list[str]] = {}
    plan_texts: list[str] = []

    def plan_line(price: float | None, cls: str, text: str) -> None:
        if price is None:
            return
        if not visible(price):
            (above if price > y_high else below).append(text)
            return
        plan_lines.setdefault((cls, round(price, 6)), []).append(text)  # same level: one line, joined text

    def cut(text: str) -> str:
        return text if len(text) <= PLAN_TEXT_CHARS else text[:PLAN_TEXT_CHARS - 1] + "…"

    for scenario in [*(analysis.get("scenarios") or []), *level_plans]:
        sid, direction = scenario["id"], scenario["direction"]
        kind = "long" if direction == "LONG" else "short" if direction == "SHORT" else "neutral"
        lo, hi = scenario.get("entry_low"), scenario.get("entry_high")
        plan_text = scenario.get("plan_text") or f"Plan {sid} {direction}"
        if lo is not None and hi is not None:
            lo, hi = min(lo, hi), max(lo, hi)
            if visible(lo) or visible(hi):
                top_price, bottom_price = min(hi, y_high), max(lo, y_low)
                parts.append(f"<rect x='{zone_x:.1f}' y='{y(top_price):.1f}' width='{zone_w:.1f}' height='{max(2.0, y(bottom_price) - y(top_price)):.1f}' class='tc-zone tc-zone--{kind}'/>")
                plan_texts.append(f"<text x='{zone_x + 4:.1f}' y='{y(top_price) + 12:.1f}' class='tc-zone-text tc-zone-text--{kind}'><title>{_safe(plan_text)}</title>{_safe(cut(plan_text))}</text>")
            else:
                (above if lo > y_high else below).append(plan_text)
        elif scenario.get("trigger") is not None:
            plan_line(scenario["trigger"], f"tc-trigger tc-trigger--{kind}", f"Trigger {sid} {_price(scenario['trigger'])}")
        invalid = scenario.get("invalidation_level")
        if invalid:
            plan_line(invalid["level"], "tc-invalid", invalid["text"])
        preview = scenario.get("preview") or {}
        if preview.get("stop") is not None:
            plan_line(preview["stop"], "tc-stop", preview.get("stop_text") or f"Stop {sid} {_price(preview['stop'])}")
            for number, target in enumerate((preview.get("targets") or [])[:2], start=1):
                text = f"TP{number} {sid} {_price(target)}"
                if visible(target):
                    plan_line(target, "tc-target", text)
                else:
                    (targets_above if target > y_high else targets_below).append(text)

    for (cls, price), texts in plan_lines.items():
        parts.append(f"<line x1='{zone_x:.1f}' x2='{PROFILE_RIGHT}' y1='{y(price):.1f}' y2='{y(price):.1f}' class='{cls}'/>")
        joined = " · ".join(texts)
        plan_texts.append(f"<text x='{zone_x + 4:.1f}' y='{y(price) - 5:.1f}' class='tc-plan-text {cls.split()[0]}-text'><title>{_safe(joined)}</title>{_safe(cut(joined))}</text>")

    for bos in model.get("bos", [])[-MAX_STRUCTURE:]:
        arrow = "↑" if bos["direction"] == "UP" else "↓"
        start = next((x(i) for i, c in enumerate(candles) if c["open_time"] >= bos["swing_time"]), PLOT_LEFT)
        end = next((x(i) for i, c in enumerate(candles) if c["open_time"] >= bos["break_time"]), x(count - 1))
        if visible(bos["level"]):
            cls = f"tc-bos tc-bos--{bos['direction'].lower()}"
            parts.append(f"<line x1='{start:.1f}' x2='{end:.1f}' y1='{y(bos['level']):.1f}' y2='{y(bos['level']):.1f}' class='{cls}'/>")
            parts.append(f"<text x='{end:.1f}' y='{y(bos['level']) - 5:.1f}' class='tc-bos-text'>{_safe(bos.get('kind', 'BOS'))} {arrow}</text>")

    # Reference levels by rank: main levels as thin lines in their colour, minor ones as stubs at the right edge.
    shown = chart_levels(model.get("reference_levels", []), levels.get("last"), y_low, y_high, show_all)
    for reference in shown["main"]:
        name = short_label(reference["label"])
        hline(reference["price"], f"tc-lvl tc-lvl--{reference['kind']}", name if len(name) <= 40 else name[:39] + "…")
    for reference in shown["minor"]:
        hline(reference["price"], "tc-lvl tc-lvl--minor", short_label(reference["label"]), start=PROFILE_LEFT - MINOR_STUB)
    for side, items in (("above", shown["above"]), ("below", shown["below"])):
        (above if side == "above" else below).extend(f"{short_label(r['label'])} {_price(r['price'])}" for r in items)
    # The chart window's POC only when no main level sits on it; its value area is the shaded band.
    poc = profile.get("poc")
    if poc is not None and not any(abs(r["price"] - poc) <= poc * 0.0005 for r in shown["main"]):
        hline(poc, "tc-poc", "POC Fenster")

    for index, candle in enumerate(candles):
        cls = "tc-up" if candle["close"] >= candle["open"] else "tc-down"
        cx = x(index)
        top_body, bottom_body = max(candle["open"], candle["close"]), min(candle["open"], candle["close"])
        parts.append(f"<line x1='{cx:.1f}' x2='{cx:.1f}' y1='{y(candle['high']):.1f}' y2='{y(candle['low']):.1f}' class='tc-wick {cls}'/>")
        parts.append(f"<rect x='{cx - body_w / 2:.1f}' y='{y(top_body):.1f}' width='{body_w:.1f}' height='{max(1.0, y(bottom_body) - y(top_body)):.1f}' class='tc-body {cls}'/>")

    last = levels.get("last")
    if last is not None:
        parts.append(f"<line x1='{PLOT_LEFT}' x2='{PROFILE_RIGHT}' y1='{y(last):.1f}' y2='{y(last):.1f}' class='tc-last'/>")
        label(last, f"Kurs {_price(last)}", "tc-last")

    parts.extend(plan_texts)  # on top of lines and candles, readable through the halo
    for item in _spread_labels(labels):
        parts.append(f"<text x='{LABEL_X}' y='{item['ly']:.1f}' class='tc-label {item['cls'].split()[-1]}-text'>{_safe(item['text'])}</text>")
    banners = [("↑ Ziele über dem Bild: ", targets_above, TOP + 2), ("↓ Ziele unter dem Bild: ", targets_below, BOTTOM - 44)]
    for prefix, items, top in banners:
        if items:
            parts.append(f"<rect x='{PLOT_LEFT + 70}' y='{top}' width='{PLOT_RIGHT - PLOT_LEFT - 140}' height='18' class='tc-banner'/>")
            parts.append(f"<text x='{PLOT_LEFT + 78}' y='{top + 13}' class='tc-banner-text'>{_safe(prefix + ' · '.join(items[:4]))}</text>")
    if above:
        parts.append(f"<text x='{PLOT_LEFT + 70}' y='{TOP + 34}' class='tc-edge'>{_safe('↑ über dem Bild: ' + ' · '.join(above[:4]))}</text>")
    if below:
        parts.append(f"<text x='{PLOT_LEFT + 70}' y='{BOTTOM - 52}' class='tc-edge'>{_safe('↓ unter dem Bild: ' + ' · '.join(below[:4]))}</text>")
    if shown["hidden"]:
        parts.append(f"<text x='{PROFILE_RIGHT}' y='{BOTTOM + 16}' text-anchor='end' class='tc-axis'>{shown['hidden']} weitere Level ausgeblendet</text>")
    risk = (model.get("risk") or {}).get("text")
    if risk:
        parts.append(f"<rect x='{PLOT_LEFT + 4}' y='{BOTTOM - 20}' width='{min(PLOT_RIGHT - PLOT_LEFT - 8, 8 + 6.4 * len(risk)):.1f}' height='16' class='tc-footer'/>")
        parts.append(f"<text x='{PLOT_LEFT + 10}' y='{BOTTOM - 8}' class='tc-footer-text'>{_safe(risk)}</text>")

    title = f"BTCUSDT {timeframe} · {count} Kerzen · TIM-Chart"
    return f"<svg viewBox='0 0 {WIDTH} {HEIGHT}' role='img' aria-label='{_safe(title)}' class='tc-svg'>{''.join(parts)}</svg>"


def _scenario_rows(analysis: dict[str, Any]) -> str:
    rows = []
    for s in (analysis.get("scenarios") or []):
        preview = s.get("preview") or {}
        zone = f"{_price(s['entry_low'])} – {_price(s['entry_high'])}" if s.get("entry_low") is not None else "keine Zone"
        targets = " / ".join(_price(t) for t in (preview.get("targets") or [])) or "–"
        rows.append(
            f"<tr><td><b>{_safe(s['id'])}</b></td><td><span class='tc-dir tc-dir--{_safe(s['direction'].lower())}'>{_safe(s['direction'])}</span></td>"
            f"<td>{_safe(SCENARIO_NAMES.get(s['type'], s['type']))}</td><td class='mono'>{_safe(zone)}</td><td class='mono'>{_safe(_price(s.get('trigger')))}</td>"
            f"<td class='mono'>{_safe(_price(preview.get('stop')))}</td><td class='mono'>{_safe(targets)}</td>"
            f"<td>{_safe(s['state'])}</td><td class='mono'>{_safe(f'{s['score']:.2f}' if s.get('score') is not None else '–')}</td>"
            f"<td>{_safe(', '.join(s.get('missing_confirmations', [])[:3]))}</td></tr>"
        )
    return "".join(rows) or "<tr><td colspan='10' class='empty'>Keine Szenarien.</td></tr>"


def _level_plan_rows(level_plans: dict[str, Any]) -> str:
    rows = []
    for p in level_plans.get("plans") or []:
        preview = p.get("preview") or {}
        targets = " / ".join(f"{_price(t)} ({label})" for t, label in zip(preview.get("targets") or [], preview.get("target_labels") or []))
        invalid = (p.get("invalidation_level") or {}).get("text", "–")
        rows.append(
            f"<tr><td><b>{_safe(p['id'])}</b></td><td><span class='tc-dir tc-dir--{_safe(p['direction'].lower())}'>{_safe(p['direction'])}</span></td>"
            f"<td>{_safe(p.get('anchor'))}</td><td>{_safe(p.get('trend'))}</td>"
            f"<td class='mono'>{_safe(_price(p.get('entry_low')))} – {_safe(_price(p.get('entry_high')))}</td>"
            f"<td class='mono'>{_safe(_price(preview.get('entry')))}</td><td class='mono'>{_safe(_price(preview.get('stop')))}</td>"
            f"<td class='mono'>{_safe(targets or '–')}</td><td class='mono'>{_safe(preview.get('reward_risk'))}</td>"
            f"<td>{_safe(invalid)}</td><td>{_safe(' · '.join(p.get('missing_confirmations') or []))}</td></tr>"
        )
    return "".join(rows) or "<tr><td colspan='11' class='empty'>Kein Level-Plan erfüllt die Regeln.</td></tr>"


def _rate(eco: dict[str, Any]) -> str:
    rate = eco.get("breakeven_hit_rate")
    return "–" if rate is None else f"{rate * 100:.0f} %"


def _r(value: Any) -> str:
    return "–" if value is None else f"{value:+.2f} R".replace(".", ",")


def _card_plan_rows(card: dict[str, Any]) -> str:
    rows = []
    for p in card.get("plans") or []:
        eco = p.get("economics") or {}
        targets = " / ".join(_price(t) for t in p.get("targets") or [])
        invalid = p.get("invalidation") or {}
        primary = " tc-card-plan--primary" if p.get("id") == card.get("primary") else ""
        rows.append(
            f"<tr class='tc-card-plan{primary}' data-plan='{_safe(p.get('id'))}'><td><b>{_safe(p.get('id'))}</b><small> {_safe(p['source'])}</small></td>"
            f"<td><span class='tc-dir tc-dir--{_safe(p['direction'].lower())}'>{_safe(p['direction'])}</span></td>"
            f"<td class='mono'>{_safe(_price(p.get('entry')))}</td><td class='mono'>{_safe(_price(p.get('stop')))}</td>"
            f"<td class='mono'>{_safe(invalid.get('side') or '')} {_safe(_price(invalid.get('level')))}</td><td class='mono'>{_safe(targets)}</td>"
            f"<td class='mono'>{_safe(_r(eco.get('gross_r_tp1')))}</td><td class='mono'>{_safe(_r(eco.get('net_r_tp1')))}</td>"
            f"<td class='mono'>{_safe(_r(eco.get('net_r_plan')))}</td><td class='mono'>{_safe(_r(eco.get('net_r_stop')))}</td>"
            f"<td class='mono'>{_safe(str(eco.get('round_trip_pct', '–')).replace('.', ','))} %</td>"
            f"<td class='mono'>{_safe(_rate(eco))}</td>"
            f"<td>{_safe((p.get('evidence') or {}).get('status'))}</td><td><b>{_safe(p.get('decision'))}</b></td></tr>"
        )
    return "".join(rows) or "<tr><td colspan='14' class='empty'>Kein Plan in diesem Zeitrahmen.</td></tr>"


def _card_section(card: dict[str, Any] | None) -> str:
    """The analysis card (Steckbrief): every field of a full analysis in one block."""
    if not card or not card.get("data"):
        return ""
    data, structure, trend = card["data"], card.get("structure") or {}, card.get("trend") or {}
    liquidity, orderflow, decision = card.get("liquidity") or {}, card.get("orderflow") or {}, card.get("decision") or {}
    primary = next((p for p in card.get("plans") or [] if p.get("id") == card.get("primary")), None)

    def levels(items: list[dict[str, Any]]) -> str:
        return "<br>".join(f"{_safe(i['label'])} {_safe(_price(i['price']))} <small>({_safe(str(i['distance_pct']).replace('.', ','))} %)</small>" for i in items) or "–"

    def item(key: str, name: str, value: str, sub: str = "") -> str:
        return f"<div class='tc-card__item' data-field='{key}'><dt>{_safe(name)}</dt><dd>{value}{f'<small>{sub}</small>' if sub else ''}</dd></div>"

    age = data.get("age_seconds") or 0
    items = [
        item("symbol", "Symbol · Zeitrahmen", f"{_safe(card['symbol'])} · {_safe(card['timeframe'])}", _safe(data.get("provenance") or "")),
        item("structure", "Marktstruktur", _safe(structure.get("text")), f"Markt {_safe(structure.get('market_state') or '–')} · Auktion {_safe(structure.get('auction_state') or '–')}"),
        item("trend", "Trendrichtung", f"1D/4h: {_safe(trend.get('htf_bias') or 'kein Bias')} · {_safe(card['timeframe'])}: {_safe(trend.get('tf_trend'))}",
             _safe(" · ".join(x for x in (trend.get("htf_text"), trend.get("location")) if x))),
        item("liquidity", "Liquiditätszonen", f"über dem Kurs:<br>{levels(liquidity.get('above') or [])}", f"unter dem Kurs:<br>{levels(liquidity.get('below') or [])}"),
        item("orderflow", "Orderflow-Beobachtungen", "<br>".join(_safe(o) for o in orderflow.get("observations") or []) or "–", _safe(orderflow.get("limits") or "")),
    ]
    if primary:
        eco = primary.get("economics") or {}
        invalid = primary.get("invalidation") or {}
        items += [
            item("entry", "Einstiegsszenario", _safe(primary.get("plan_text") or primary["id"]), _safe(" · ".join(primary.get("missing_confirmations") or []))),
            item("stop", "Stop und Invalidierung", f"Stop {_safe(_price(primary['stop']))}", f"ungültig bei 30m-Schluss {_safe(invalid.get('side') or '')} {_safe(_price(invalid.get('level')))}"),
            item("targets", "Ziele", " / ".join(_safe(_price(t)) for t in primary.get("targets") or []), _safe(" · ".join(primary.get("target_labels") or []))),
            item("r", "R brutto / netto", f"Ziel 1: {_safe(_r(eco.get('gross_r_tp1')))} / {_safe(_r(eco.get('net_r_tp1')))}",
                 f"Drittel-Plan netto {_safe(_r(eco.get('net_r_plan')))} · Stop netto {_safe(_r(eco.get('net_r_stop')))}"),
            item("costs", "Kosten Hin und Zurück", f"{_safe(str(eco.get('round_trip_pct')).replace('.', ','))} % vom Einstieg · {_safe(_r(eco.get('costs_r_tp1')).lstrip('+'))} des Risikos",
                 f"Gebühr 0,05 % + Slippage 0,03 % je Seite, Stop-Slippage 0,05 % ({_safe(eco.get('cost_model'))}). Nötige Trefferquote {_safe(_rate(eco))}"),
            item("evidence", "Forschungs-Evidenz", _safe((primary.get("evidence") or {}).get("status")),
                 _safe(f"{primary.get('scenario_type')} {(primary.get('evidence') or {}).get('timeframe')}: {(primary.get('evidence') or {}).get('reason') or ', '.join((primary.get('evidence') or {}).get('variant_ids') or [])}")),
        ]
    else:
        items.append(item("entry", "Einstiegsszenario", "kein Plan", _safe(" · ".join(card.get("dropped") or [])[:400])))
    items.append(item("data", "Datenqualität und Datenalter", f"{_safe(data.get('quality') or '–')} · letzte Kerze vor {age // 60} min",
                      ("<b>veraltet</b> · " if data.get("stale") else "") + _safe(", ".join([*data.get("missing", []), *data.get("problems", [])]) or "keine Mängel gemeldet")))
    check = card.get("journal_check")
    if check:
        items.append(item("journal", "Abgleich mit Plan-Journal level/1", _safe(check.get("text")),
                          _safe(f"Journal {check.get('journal_last_close') or '–'} · Chart {check.get('chart_last_close') or '–'}")))
    sev = "blocked" if decision.get("status") == "NO_TRADE" else "warn"
    reasons = "".join(f"<li>{_safe(r)}</li>" for r in decision.get("reasons_text") or [])
    return (
        f"<section class='cc-section tc-card' data-card='{_safe(card.get('schema'))}'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Analyse-Steckbrief</p>"
        f"<h2>{_safe(card['symbol'])} {_safe(card['timeframe'])}: <span class='sev sev--{sev}' data-field='decision'>{_safe(decision.get('status'))}</span></h2>"
        f"<p class='cc-section__note'>{_safe(decision.get('summary'))}</p></div></div>"
        + (f"<p class='cc-note'>Warum kein Trade:</p><ul class='cc-note tc-card__reasons'>{reasons}</ul>" if reasons else "")
        + f"<dl class='tc-card__grid'>{''.join(items)}</dl>"
        "<div class='table-wrap'><table class='tc-card__plans'><thead><tr><th>Plan</th><th>Richtung</th><th>Einstieg</th><th>Stop</th><th>Ungültig</th><th>Ziele</th>"
        "<th>R brutto Ziel 1</th><th>R netto Ziel 1</th><th>R netto Drittel</th><th>R netto Stop</th><th>Kosten</th><th>Trefferquote nötig</th><th>Evidenz</th><th>Entscheidung</th></tr></thead>"
        f"<tbody>{_card_plan_rows(card)}</tbody></table></div>"
        "<p class='cc-note'>Nur Papier. Kosten nach Protokoll 1.1 wie im Plan-Journal. Die Entscheidung kommt aus demselben Gate wie das Journal: "
        "Evidenz PASSED_HOLDOUT, Papier-Freigabe, Pipeline TRADE_PLAN, bestätigtes Szenario, ausführbares Instrument, Datenqualität PASS.</p></section>"
    )


def _live_section(symbol: str, view: str) -> str:
    """Toolbar and container of the interactive chart; tim_chart.js fills it."""
    symbols = "".join(
        f"<a href='/chart?symbol={item}&amp;tf={view}' class='tc-tab{' tc-tab--active' if item == symbol else ''}'"
        f"{' aria-current=\'page\'' if item == symbol else ''} title='{_safe(SYMBOL_NAMES[item])}'>{item.removesuffix('USDT')}</a>"
        for item in SYMBOLS)
    frames = "".join(
        f"<a href='/chart?symbol={symbol}&amp;tf={item}' data-tf='{item}' class='tc-tab{' tc-tab--active' if item == view else ''}'"
        f"{' aria-current=\'page\'' if item == view else ''}>{item}</a>"
        for item in VIEW_TIMEFRAMES)
    return (
        f"<section class='cc-section tc-live' id='tc-live' data-keep-view='chart' data-symbol='{_safe(symbol)}' data-tf='{_safe(view)}'>"
        f"<nav class='tc-tabs' aria-label='Coin'>{symbols}<span class='tc-tabs__sep'>Zeitrahmen:</span>{frames}</nav>"
        "<div class='tc-live__bar'><div id='tc-live-layers' class='tc-live__layers' aria-label='Linien ein- und ausblenden'></div>"
        "<div class='tc-live__actions'><button type='button' class='tc-tab' data-action='now'>Zu jetzt</button>"
        "<button type='button' class='tc-tab' data-action='fit'>Alles zeigen</button><button type='button' class='tc-tab' data-action='footprint' title='Letzte Kerzen groß, Footprint mit Zahlen'>Footprint</button>"
        "<button type='button' class='tc-tab' data-action='plans'>Nur TIMs Trades</button><button type='button' class='tc-tab' data-action='none'>Alle Haken weg</button><button type='button' class='tc-tab' data-action='reset'>Linien zurücksetzen</button></div></div>"
        "<div class='tc-live__frame'><p id='tc-live-legend' class='tc-live__legend'></p>"
        "<div id='tc-live-chart' class='tc-live__chart' role='img' aria-label='Interaktiver Kerzenchart'></div></div>"
        "<p id='tc-live-status' class='cc-note tc-live__status'>Chart lädt… (braucht JavaScript)</p>"
        "<p class='cc-note'>Mausrad = zoomen, ziehen = verschieben, Preisachse ziehen = Höhe ändern, Doppelklick auf die Achse = zurücksetzen. "
        "Jede Linie beginnt dort, wo das Level entstanden ist (Hochs/Tiefs an ihrer Kerze, Profile am Beginn ihres Tages/ihrer Woche), "
        "und trägt Zeitrahmen und Namen, z. B. <b>1D VAH</b> oder <b>1W POC</b>. Ein ← heißt: Beginn liegt links außerhalb der geladenen Kerzen. "
        "<b>TPO</b>: Tagesprofil aus 30-Minuten-Perioden (Buchstaben A, B, C … ab 00:00 UTC) hinter den Kerzen, Value Area heller, POC gelb, Single Prints orange; "
        "auf Zeitrahmen bis 4h. <b>Volume Profile</b> und <b>Footprint</b> kommen aus TIMs eigenen Trades (Datenbank, nur BTC): "
        "das Profil je Tag rechts am Tagesende (Volumen je Preisstufe, Value Area, POC gelb, grüner/roter Strich = Delta), "
        "der <b>Footprint</b> (5m bis 4h, Knopf „Footprint“) folgt dem Zoom: mittel = Farbsäule je Kerze (grün/rot = Delta, kräftig = viel Volumen), nah = Bid × Ask je Preisstufe neben einer schmalen Kerze, Preisstufen werden beim Reinzoomen feiner, POC gelb umrandet, Imbalances 4:1 fett (grün = Käufer, rot = Verkäufer), gestapelte Imbalances (3+) als Balken an der Seite, unfertige Auktion am Hoch/Tief orange gepunktet, Δ und Volumen (V) unter der Kerze. "
        "<b>BOS / MSS</b> zählen nur per Schlusskurs (ein Docht durch das Level ist ein Sweep): BOS = Bruch des letzten Swings in Trendrichtung, "
        "MSS = Schlusskurs jenseits des <b>Strong Low</b> (im Aufwärtstrend) bzw. <b>Strong High</b> (im Abwärtstrend), also des Tiefs/Hochs, "
        "aus dem der letzte Schub kam. Gestrichelt und bis jetzt: das offene Strong Low/High und das <b>BOS-Ziel</b>. Swings: 3 Kerzen je Seite. "
        "Zeiten in deiner Ortszeit. Nur Anzeige, keine Order. "
        "Chart: <a href='https://www.tradingview.com/' rel='noopener noreferrer'>TradingView Lightweight Charts</a> (Apache 2.0).</p>"
        f"<script src='{LIB_PATH}'></script><script src='{APP_PATH}'></script></section>"
    )


def render_chart_page(state: Any, timeframe: str | None = None, levels_mode: str | None = None, symbol: str | None = None) -> str:
    from datetime import timezone

    from src.dashboard.analysis_card import with_journal_check

    symbol = symbol if symbol in SYMBOLS else DEFAULT_SYMBOL
    view = timeframe if timeframe in VIEW_TIMEFRAMES else DEFAULT_TIMEFRAME
    data = state.snapshot()
    body = _hero("TIM-Chart", "BTC, ETH und SOL in jedem Zeitrahmen: zoomen, verschieben, Fadenkreuz. Level als beschriftete Strecken ab ihrer Entstehung.")
    body += _live_section(symbol, view)
    if symbol != "BTCUSDT":
        body += ("<section class='cc-section'><p class='cc-note'>Steckbrief, Szenarien, Level-Pläne und Plan-Journale gibt es nur für BTC. "
                 f"{_safe(SYMBOL_NAMES[symbol])} ist reine Anzeige aus öffentlichen Binance-Kerzen; die Multi-Coin-Runtime ist aus.</p></section>")
        return _layout("TIM-Chart", "Chart", body, strip=_strip_states(data))

    series, now = state.chart_series(), datetime.now(timezone.utc)
    model = with_journal_check(build_chart_model(series, timeframe or DEFAULT_TIMEFRAME, now=now, card=True),
                               series, getattr(state, "plan_journal_level_path", None), now)
    tf = model["timeframe"]
    show_all = levels_mode == "alle"
    keep = "&levels=alle" if show_all else ""
    tabs = "".join(
        f"<a href='/chart?tf={item}{keep}' class='tc-tab{' tc-tab--active' if item == tf else ''}'"
        f"{' aria-current=\'page\'' if item == tf else ''}>{item}{'' if item in model['available_timeframes'] else ' ·'}</a>"
        for item in CHART_TIMEFRAMES
    )
    body += f"<nav class='tc-tabs' aria-label='Analyse-Zeitrahmen'><span class='tc-tabs__sep'>Analyse (BTC):</span>{tabs}"
    body += (f"<span class='tc-tabs__sep'>Level:</span><a href='/chart?tf={tf}' class='tc-tab{'' if show_all else ' tc-tab--active'}'>nahe Hauptlevel</a>"
             f"<a href='/chart?tf={tf}&levels=alle' class='tc-tab{' tc-tab--active' if show_all else ''}'>alle</a></nav>")
    if not model["candles"]:
        body += "<section class='cc-section'><p class='empty'>Noch keine Kerzen für diesen Zeitrahmen. Der Chart erscheint, sobald die Runtime Daten liefert.</p></section>"
        return _layout("TIM-Chart", "Chart", body, strip=_strip_states(data))

    analysis = model.get("analysis") or {}
    decision = analysis.get("decision") or {}
    quality = analysis.get("data_quality") or {}
    levels = model["levels"]
    profile = model.get("profile") or {}
    status = decision.get("status", "UNAVAILABLE")
    sev = "blocked" if status == "NO_TRADE" else "warn"
    body += (
        f"<section class='state-banner state-banner--{sev}'><div class='state-banner__primary'><span class='sev sev--{sev}'>{_safe(status)}</span>"
        f"<h2 class='state-banner__state'>Entscheidung der Pipeline</h2><p class='state-banner__sub'>{_safe(', '.join(decision.get('reasons', [])) or 'keine Gründe gemeldet')}</p></div>"
        f"<dl class='state-banner__metrics'><div class='state-banner__metric'><dt>Markt</dt><dd>{_safe(analysis.get('market_state', '–'))}<small>Auktion {_safe(analysis.get('auction_state', '–'))}</small></dd></div>"
        f"<div class='state-banner__metric'><dt>Datenqualität</dt><dd>{_safe(quality.get('status', '–'))}<small>Konfidenz {_safe(quality.get('confidence'))}</small></dd></div>"
        f"<div class='state-banner__metric'><dt>Letzter Kurs</dt><dd>{_safe(_price(levels.get('last')))}<small>vor {_safe(levels.get('age_seconds'))} s</small></dd></div></dl></section>"
    )
    body += _card_section(model.get("analysis_card"))
    body += (f"<section class='cc-section'><details class='tc-plan-view'><summary>Plan-Ansicht {_safe(tf)}: Zonen, Stop und Ziele von TIMs Plänen (Bild)</summary>"
             f"<div class='cc-surface tc-chart'>{_chart_svg(model, show_all)}</div>")
    body += (
        "<p class='cc-note tc-legend'><span class='tc-key tc-key--day'>Vortag</span><span class='tc-key tc-key--week'>Vorwoche</span>"
        "<span class='tc-key tc-key--naked'>naked POC</span><span class='tc-key tc-key--minor'>Session / IB / laufender POC (kurz am Rand)</span>"
        f"<span>Gezeigt: {'alle Level' if show_all else f'die {MAX_MAIN_LEVELS} nächsten Hauptlevel und {MAX_MINOR_LEVELS} Nebenlevel'}; alle stehen in der Tabelle unten.</span></p>"
    )
    body += (
        "<p class='cc-note'>Grün/Rot: Einstiegszonen von TIMs Long-/Short-Szenarien. Stop und Ziele sind eine <b>Vorschau nach TIMs Regeln</b> "
        "(Stop 0,5–1 % hinter der Zone, Ziele 1,5R/2R/3R) für ein <b>nicht bestätigtes</b> Szenario. Scores sind unkalibriert. Keine Order, kein Handel.</p>"
    )
    body += f"<p class='cc-note'>Volume Profile: {_safe(profile.get('source', 'nicht verfügbar'))}. Value Area {int(profile.get('value_area_share', 0.7) * 100)} %. BOS: erster Schlusskurs jenseits eines bestätigten Swing-Hochs/-Tiefs. Zeiten in UTC.</p>"
    for note in model.get("notes", []):
        body += f"<p class='cc-note'>{_safe(note)}</p>"
    body += "</details></section>"
    body += (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Szenarien</p><h2>Was TIM aus diesen Kerzen ableitet</h2>"
        "<p class='cc-section__note'>Orderflow-Pipeline im OBSERVE-Modus, gleiche Regeln wie die CLI.</p></div></div>"
        "<div class='table-wrap'><table><thead><tr><th>ID</th><th>Richtung</th><th>Szenario</th><th>Einstiegszone</th><th>Trigger</th><th>Stop (Vorschau)</th>"
        f"<th>Ziele (Vorschau)</th><th>Status</th><th>Score</th><th>Fehlende Bestätigung</th></tr></thead><tbody>{_scenario_rows(analysis)}</tbody></table></div></section>"
    )
    level_plans = model.get("level_plans") or {}
    dropped = "".join(f"<li>{_safe(reason)}</li>" for reason in level_plans.get("dropped") or [])
    body += (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Level-Pläne (level/1)</p><h2>Pläne an den Hauptleveln</h2>"
        "<p class='cc-section__note'>Nächstes Hauptlevel unter und über dem Kurs (Vortag, Vorwoche, naked POC). Stop hinter dem 30m-Swing, "
        "Ziele an den nächsten Leveln, erstes Ziel mindestens 1,5 R. Nur Papier, nicht bestätigt.</p></div></div>"
        "<div class='table-wrap'><table><thead><tr><th>ID</th><th>Richtung</th><th>Level</th><th>Trend 1D/4h</th><th>Zone</th><th>Einstieg</th><th>Stop</th>"
        f"<th>Ziele</th><th>R bis Ziel 1</th><th>Ungültig</th><th>Bestätigung nötig</th></tr></thead><tbody>{_level_plan_rows(level_plans)}</tbody></table></div>"
        + (f"<p class='cc-note'>Verworfen:</p><ul class='cc-note'>{dropped}</ul>" if dropped else "")
        + "</section>"
    )
    level_rows = [("Range-High", levels.get("range_high")), ("Range-Low", levels.get("range_low")), ("VAH", profile.get("vah")), ("POC", profile.get("poc")), ("VAL", profile.get("val"))]
    level_rows += [(f"{b.get('kind', 'BOS')} {b['timeframe']} {'↑' if b['direction'] == 'UP' else '↓'}", b["level"]) for b in model.get("bos", [])]
    level_rows += [(r["label"], r["price"]) for r in model.get("reference_levels", [])]
    body += (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Marken</p><h2>Levels im Chart</h2></div></div>"
        "<div class='metricstrip'>" + "".join(f"<dl class='metricstrip__item'><dt>{_safe(name)}</dt><dd>{_safe(_price(value))}</dd></dl>" for name, value in level_rows) + "</div>"
        "<p class='cc-note'>Rohdaten als JSON: <a href='/api/chart?tf=" + _safe(tf) + "'>/api/chart?tf=" + _safe(tf) + "</a></p></section>"
    )
    return _layout("TIM-Chart", "Chart", body, strip=_strip_states(data))
