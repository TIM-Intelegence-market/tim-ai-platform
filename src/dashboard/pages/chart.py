"""TIM chart page: candles from TIM's own data with levels and scenarios (read-only SVG)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from src.dashboard.chart_model import CHART_TIMEFRAMES, build_chart_model
from src.dashboard.helpers import _safe
from src.dashboard.layout import _hero, _layout, _strip_states

WIDTH, HEIGHT = 1000, 520
PLOT_LEFT, PLOT_RIGHT = 12, 760
PROFILE_LEFT, PROFILE_RIGHT = 764, 850
LABEL_X = 856
TOP, BOTTOM = 18, 478
LABEL_GAP = 13
ZONE_SPACE = 140  # px right of the last candle reserved for scenario zones
SCENARIO_NAMES = {
    "BREAKOUT_ACCEPTANCE": "Ausbruch + Annahme",
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


def _time_label(value: str, timeframe: str) -> str:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return ""
    return moment.strftime("%d.%m. %H:%M") if timeframe == "1h" else moment.strftime("%H:%M")


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


def _chart_svg(model: dict[str, Any]) -> str:
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
    for scenario in analysis.get("scenarios", []):
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
    slot = (PLOT_RIGHT - PLOT_LEFT - ZONE_SPACE) / count  # free space right of the last candle for zones
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
    for index in range(0, count, step):
        parts.append(f"<line x1='{x(index):.1f}' x2='{x(index):.1f}' y1='{TOP}' y2='{BOTTOM}' class='tc-grid'/>")
        parts.append(f"<text x='{x(index):.1f}' y='{BOTTOM + 16}' text-anchor='{'start' if index == 0 else 'middle'}' class='tc-axis'>{_safe(_time_label(candles[index]['open_time'], timeframe))}</text>")

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

    # Scenarios: entry zone, trigger, preview stop and targets.
    zone_start = x(count - 1) + slot + 46  # the drawing below starts 40 px before this
    for scenario in analysis.get("scenarios", []):
        sid, direction = scenario["id"], scenario["direction"]
        kind = "long" if direction == "LONG" else "short" if direction == "SHORT" else "neutral"
        lo, hi = scenario.get("entry_low"), scenario.get("entry_high")
        if lo is not None and hi is not None:
            if visible(lo) or visible(hi):
                top_price, bottom_price = min(max(lo, hi), y_high), max(min(lo, hi), y_low)
                parts.append(f"<rect x='{zone_start - 40:.1f}' y='{y(top_price):.1f}' width='{PROFILE_LEFT - zone_start + 40:.1f}' height='{max(2.0, y(bottom_price) - y(top_price)):.1f}' class='tc-zone tc-zone--{kind}'/>")
                parts.append(f"<text x='{zone_start - 36:.1f}' y='{y(top_price) + 12:.1f}' class='tc-zone-text tc-zone-text--{kind}'>{_safe(f'Plan {sid} {direction}')}</text>")
                parts.append(f"<text x='{zone_start - 36:.1f}' y='{y(top_price) + 24:.1f}' class='tc-zone-text tc-zone-text--{kind}'>{_safe(f'{_price(min(lo, hi))}–{_price(max(lo, hi))}')}</text>")
            else:
                (above if lo > y_high else below).append(f"Zone {sid} {_price(min(lo, hi))}–{_price(max(lo, hi))}")
        elif scenario.get("trigger") is not None:
            hline(scenario["trigger"], f"tc-trigger tc-trigger--{kind}", f"Trigger {sid}", zone_start - 40)
        preview = scenario.get("preview") or {}
        if preview.get("stop") is not None:
            hline(preview["stop"], "tc-stop", f"Stop {sid}", zone_start - 40)
            for number, target in enumerate((preview.get("targets") or [])[:2], start=1):
                hline(target, "tc-target", f"Ziel {sid}{number}", zone_start - 40)

    for bos in model.get("bos", []):
        arrow = "↑" if bos["direction"] == "UP" else "↓"
        start = next((x(i) for i, c in enumerate(candles) if c["open_time"] >= bos["swing_time"]), PLOT_LEFT)
        hline(bos["level"], f"tc-bos tc-bos--{bos['direction'].lower()}", f"BOS {bos['timeframe']} {arrow}", start)

    hline(levels.get("range_high"), "tc-range", "Range-High")
    hline(levels.get("range_low"), "tc-range", "Range-Low")
    hline(profile.get("vah"), "tc-va", "VAH")
    hline(profile.get("val"), "tc-va", "VAL")
    hline(profile.get("poc"), "tc-poc", "POC")

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

    for item in _spread_labels(labels):
        parts.append(f"<text x='{LABEL_X}' y='{item['ly']:.1f}' class='tc-label {item['cls'].split()[0]}-text'>{_safe(item['text'])}</text>")
    if above:
        parts.append(f"<text x='{PLOT_LEFT + 60}' y='{TOP + 14}' class='tc-edge'>{_safe('↑ über dem Bild: ' + ' · '.join(above[:4]))}</text>")
    if below:
        parts.append(f"<text x='{PLOT_LEFT + 60}' y='{BOTTOM - 6}' class='tc-edge'>{_safe('↓ unter dem Bild: ' + ' · '.join(below[:4]))}</text>")

    title = f"BTCUSDT {timeframe} · {count} Kerzen · TIM-Chart"
    return f"<svg viewBox='0 0 {WIDTH} {HEIGHT}' role='img' aria-label='{_safe(title)}' class='tc-svg'>{''.join(parts)}</svg>"


def _scenario_rows(analysis: dict[str, Any]) -> str:
    rows = []
    for s in analysis.get("scenarios", []):
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


def render_chart_page(state: Any, timeframe: str | None = None) -> str:
    data = state.snapshot()
    model = build_chart_model(state.chart_series(), timeframe or "15m")
    tf = model["timeframe"]
    tabs = "".join(
        f"<a href='/chart?tf={item}' class='tc-tab{' tc-tab--active' if item == tf else ''}'"
        f"{' aria-current=\'page\'' if item == tf else ''}>{item}{'' if item in model['available_timeframes'] else ' ·'}</a>"
        for item in CHART_TIMEFRAMES
    )
    body = _hero("TIM-Chart", "Kerzen aus TIMs eigenen Binance-Daten mit den Marken, die TIM selbst berechnet: Range, Value Area, BOS und Szenarien.")
    body += f"<nav class='tc-tabs' aria-label='Zeitrahmen'>{tabs}</nav>"
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
    body += f"<section class='cc-section'><div class='cc-surface tc-chart'>{_chart_svg(model)}</div>"
    body += (
        "<p class='cc-note'>Grün/Rot: Einstiegszonen von TIMs Long-/Short-Szenarien. Stop und Ziele sind eine <b>Vorschau nach TIMs Regeln</b> "
        "(Stop 0,5–1 % hinter der Zone, Ziele 1,5R/2R/3R) für ein <b>nicht bestätigtes</b> Szenario. Scores sind unkalibriert. Keine Order, kein Handel.</p>"
    )
    body += f"<p class='cc-note'>Volume Profile: {_safe(profile.get('source', 'nicht verfügbar'))}. Value Area {int(profile.get('value_area_share', 0.7) * 100)} %. BOS: erster Schlusskurs jenseits eines bestätigten Swing-Hochs/-Tiefs. Zeiten in UTC.</p>"
    for note in model.get("notes", []):
        body += f"<p class='cc-note'>{_safe(note)}</p>"
    body += "</section>"
    body += (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Szenarien</p><h2>Was TIM aus diesen Kerzen ableitet</h2>"
        "<p class='cc-section__note'>Orderflow-Pipeline im OBSERVE-Modus, gleiche Regeln wie die CLI.</p></div></div>"
        "<div class='table-wrap'><table><thead><tr><th>ID</th><th>Richtung</th><th>Szenario</th><th>Einstiegszone</th><th>Trigger</th><th>Stop (Vorschau)</th>"
        f"<th>Ziele (Vorschau)</th><th>Status</th><th>Score</th><th>Fehlende Bestätigung</th></tr></thead><tbody>{_scenario_rows(analysis)}</tbody></table></div></section>"
    )
    level_rows = [("Range-High", levels.get("range_high")), ("Range-Low", levels.get("range_low")), ("VAH", profile.get("vah")), ("POC", profile.get("poc")), ("VAL", profile.get("val"))]
    level_rows += [(f"BOS {b['timeframe']} {'↑' if b['direction'] == 'UP' else '↓'}", b["level"]) for b in model.get("bos", [])]
    body += (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Marken</p><h2>Levels im Chart</h2></div></div>"
        "<div class='metricstrip'>" + "".join(f"<dl class='metricstrip__item'><dt>{_safe(name)}</dt><dd>{_safe(_price(value))}</dd></dl>" for name, value in level_rows) + "</div>"
        "<p class='cc-note'>Rohdaten als JSON: <a href='/api/chart?tf=" + _safe(tf) + "'>/api/chart?tf=" + _safe(tf) + "</a></p></section>"
    )
    return _layout("TIM-Chart", "Chart", body, strip=_strip_states(data))
