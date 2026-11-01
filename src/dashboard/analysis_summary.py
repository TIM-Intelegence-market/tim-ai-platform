"""Short text summary of what TIM's analysis says right now (BTC, read-only, paper only).

Uzi 31.10.2026: "bei der Chart-Seite einmal einen Text zusammenfassen, was TIM aktuell
auf seiner Analyse hat". The chart page (German, Control Center) and the public English
chart page show the same facts as a few sentences above the interactive chart.

Every fact comes from code that already draws or plans on the chart, nothing is made up:

- price and data age: last closed 30m candle of the runtime series,
- higher-timeframe bias: ``session_map.htf_bias`` (1D and 4h decide, 1W confirms),
- structure per timeframe: ``chart_live.market_structure`` (the BOS/MSS drawn in the chart),
- location against the prior day's value area: ``session_map.location``,
- nearest main levels above and below: the session map's reference levels,
- TIM's paper plans: waiting (OPEN) and running (FILLED) entries of the plan journals.

``build_summary`` returns language-neutral data; ``render_de`` / ``render_en`` turn it
into HTML. Nothing here is a signal or advice.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.dashboard.helpers import _safe

SCHEMA = "analysis_summary/1"
LOCAL = ZoneInfo("Europe/Berlin")
STRUCTURE_TIMEFRAMES = ("15m", "30m", "1h", "4h", "1d")
STRUCTURE_CANDLES = 500  # same depth as the runtime chart history
LEVELS_PER_SIDE = 2
STALE_SECONDS = 1800 + 300  # one 30m candle plus five minutes, as the analysis card
# Main levels only (prior day, prior week, running day/week POC, naked POCs); sessions and IB stay in the chart.
MAIN_LEVEL_PREFIXES = ("Vortag ", "PDH", "PDL", "PWH", "PWL", "Vorwoche ", "heute POC", "Woche POC", "naked POC")
# Journals summarised: the three horizons and the earlier 30m versions that still run (level/1 is retired).
JOURNALS = (("short", "15m"), ("mid", "1h"), ("long", "1D"), ("tim", "30m TIM"), ("struct", "30m Struktur"))
JOURNALS_EN = {"30m Struktur": "30m structure"}

BIAS_DE = {"LONG": "Long-Bias (1D und 4h aufwärts)", "SHORT": "Short-Bias (1D und 4h abwärts)",
           "NEUTRAL": "kein klarer Bias (1D und 4h uneins)", "UNKNOWN": "Bias unbekannt (zu wenig 1D/4h-Kerzen)"}
BIAS_EN = {"LONG": "long bias (1D and 4h up)", "SHORT": "short bias (1D and 4h down)",
           "NEUTRAL": "no clear bias (1D and 4h disagree)", "UNKNOWN": "bias unknown (too few 1D/4h candles)"}
LOCATION_DE = {"ABOVE_ACCEPTED": "über dem Vortages-Value und dort angenommen",
               "ABOVE_NOT_ACCEPTED": "über dem Vortages-VAH, aber noch nicht angenommen",
               "IN_VALUE": "im Vortages-Value", "BELOW_NOT_ACCEPTED": "unter dem Vortages-VAL, aber noch nicht angenommen",
               "BELOW_ACCEPTED": "unter dem Vortages-Value und dort angenommen"}
LOCATION_EN = {"ABOVE_ACCEPTED": "above the prior day's value area and accepted there",
               "ABOVE_NOT_ACCEPTED": "above the prior day's VAH, not accepted yet",
               "IN_VALUE": "inside the prior day's value area", "BELOW_NOT_ACCEPTED": "below the prior day's VAL, not accepted yet",
               "BELOW_ACCEPTED": "below the prior day's value area and accepted there"}
TREND_DE = {"UP": "aufwärts", "DOWN": "abwärts", None: "noch ohne Trend"}
TREND_EN = {"UP": "up", "DOWN": "down", None: "no trend yet"}
LEVEL_EN = (
    ("PDH · Vortag Hoch", "PDH (prior day high)"), ("PDL · Vortag Tief", "PDL (prior day low)"),
    ("PWH · Vorwoche Hoch", "PWH (prior week high)"), ("PWL · Vorwoche Tief", "PWL (prior week low)"),
    ("Vortag ", "Prior day "), ("Vorwoche ", "Prior week "),
    ("heute POC (laufend)", "Today POC (running)"), ("Woche POC (laufend)", "Week POC (running)"),
)


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else (str(value) if value else None)


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    elif value:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _structure(series: Mapping[str, Sequence[Mapping[str, Any]]], now: datetime) -> list[dict[str, Any]]:
    from src.dashboard.chart_live import market_structure
    from src.dashboard.chart_model import clean_candles

    rows = []
    for tf in STRUCTURE_TIMEFRAMES:
        candles = [c for c in clean_candles(series.get(tf) or [], tf) if c["close_time"] <= now][-STRUCTURE_CANDLES:]
        if len(candles) < 10:
            continue
        state = market_structure(candles, tf)
        last = state["events"][-1] if state["events"] else None
        rows.append({
            "timeframe": tf, "trend": state["trend"],
            "last_event": {"kind": last["kind"], "direction": last["direction"], "level": round(float(last["level"]), 2),
                           "time": last["break_time"]} if last else None,
            "protected": round(float(state["protected"]["price"]), 2) if state.get("protected") else None,
            "target": round(float(state["target"]["price"]), 2) if state.get("target") else None,
        })
    return rows


def _levels(references: Sequence[Mapping[str, Any]], last: float) -> dict[str, list[dict[str, Any]]]:
    main = [r for r in references if r.get("price") and str(r.get("label", "")).startswith(MAIN_LEVEL_PREFIXES)]

    def item(r: Mapping[str, Any]) -> dict[str, Any]:
        price = float(r["price"])
        return {"label": str(r["label"]), "price": round(price, 2), "distance_pct": round((price - last) / last * 100, 2)}

    above = sorted((item(r) for r in main if float(r["price"]) > last), key=lambda x: x["price"])[:LEVELS_PER_SIDE]
    below = sorted((item(r) for r in main if float(r["price"]) < last), key=lambda x: -x["price"])[:LEVELS_PER_SIDE]
    return {"above": above, "below": below}


def _plans(journals: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for key, name in JOURNALS:
        for entry in journals.get(key) or []:
            if entry.get("excluded") or entry.get("status") not in ("OPEN", "FILLED") or entry.get("entry") is None:
                continue
            rows.append({"journal": key, "name": name, "status": entry["status"], "direction": entry.get("direction"),
                         "entry": round(float(entry.get("fill_price") or entry["entry"]), 2),
                         "stop": round(float(entry["stop"]), 2) if entry.get("stop") is not None else None})
    return rows


def build_summary(series: Mapping[str, Sequence[Mapping[str, Any]]], journals: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
                  now: datetime | None = None) -> dict[str, Any]:
    """The facts behind the summary text (pure; ``series`` is the runtime chart series)."""
    from src.dashboard.chart_model import analytical_series, clean_candles
    from src.dashboard.session_map import build_session_map

    now = now or datetime.now(timezone.utc)
    result: dict[str, Any] = {"schema": SCHEMA, "symbol": "BTCUSDT", "generated_at": now.isoformat(),
                              "read_only": True, "paper_only": True, "available": False}
    clean = analytical_series(series, now)
    closes = [c for c in clean_candles(clean.get("30m") or [], "30m") if c["close_time"] <= now]
    if not closes:
        result["reason"] = "no_candles"
        return result
    last = closes[-1]
    age = max(0, int((now - last["close_time"]).total_seconds()))
    prep = build_session_map(clean, now)
    result.update(
        available=True, last=float(last["close"]), last_close_time=_iso(last["close_time"]), age_seconds=age,
        stale=age > STALE_SECONDS,
        bias=(prep.get("bias") or {}).get("bias") or "UNKNOWN",
        weekly_confirms=bool((prep.get("bias") or {}).get("weekly_confirms")),
        htf={label: (info or {}).get("state", "UNKNOWN") for label, info in (prep.get("htf") or {}).items()},
        location=(prep.get("location") or {}).get("state", "UNKNOWN"),
        structure=_structure(clean, now),
        levels=_levels(prep.get("levels") or [], float(last["close"])),
        plans=_plans(journals or {}),
    )
    return result


# --- text ---------------------------------------------------------------------------------------------------------


def _price_de(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value:,.0f}".replace(",", ".") if value >= 1000 else f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _price_en(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value:,.0f}" if value >= 1000 else f"{value:,.2f}"


def _pct(value: float, de: bool) -> str:
    text = f"{value:+.2f} %"
    return text.replace(".", ",").replace("-", "−") if de else text.replace("-", "−")


def _local(value: Any, with_day: bool = True) -> str:
    moment = _as_datetime(value)
    if moment is None:
        return "–"
    return moment.astimezone(LOCAL).strftime("%d.%m. %H:%M" if with_day else "%H:%M")


def level_en(label: str) -> str:
    for german, english in LEVEL_EN:
        label = label.replace(german, english)
    return label


def _structure_items(rows: Sequence[Mapping[str, Any]], de: bool) -> str:
    items = []
    for row in rows:
        trend = (TREND_DE if de else TREND_EN).get(row["trend"], "–")
        event = row.get("last_event")
        price = _price_de if de else _price_en
        text = f"<b>{_safe(row['timeframe'])}</b> {_safe(trend)}"
        if event:
            arrow = "↑" if event["direction"] == "UP" else "↓"
            since = "seit" if de else "since"
            text += f" <small>({since} {_safe(event['kind'])} {arrow} {_safe(_local(event['time']))}"
            if row.get("protected") is not None:
                text += f", {'MSS bei' if de else 'MSS at'} {_safe(price(row['protected']))}"
            text += ")</small>"
        items.append(f"<li data-tf='{_safe(row['timeframe'])}'>{text}</li>")
    return "".join(items)


def _level_text(items: Sequence[Mapping[str, Any]], de: bool, side: str) -> str:
    if not items:
        if de:
            return f"keins (Kurs {'über' if side == 'above' else 'unter'} allen Hauptleveln)"
        return f"none (price {side} all main levels)"
    price = _price_de if de else _price_en
    return ", ".join(f"{_safe(i['label'] if de else level_en(i['label']))} {_safe(price(i['price']))} ({_safe(_pct(i['distance_pct'], de))})"
                     for i in items)


def _plan_text(plans: Sequence[Mapping[str, Any]], de: bool) -> str:
    running = [p for p in plans if p["status"] == "FILLED"]
    waiting = [p for p in plans if p["status"] == "OPEN"]
    price = _price_de if de else _price_en

    def one(p: Mapping[str, Any]) -> str:
        name = p["name"] if de else JOURNALS_EN.get(p["name"], p["name"])
        return f"{_safe(p['direction'])} {_safe(name)} {'ab' if de else 'from'} {_safe(price(p['entry']))}"

    if not plans:
        return ("Keine offenen Papier-Pläne: TIM wartet." if de else "No open paper plans: TIM is waiting.")
    parts = []
    if running:
        parts.append((f"{len(running)} {'läuft' if len(running) == 1 else 'laufen'} " if de else f"{len(running)} running ")
                     + f"({'; '.join(one(p) for p in running)})")
    if waiting:
        parts.append((f"{len(waiting)} {'wartet' if len(waiting) == 1 else 'warten'} auf den Einstieg " if de else f"{len(waiting)} waiting for entry ")
                     + f"({'; '.join(one(p) for p in waiting)})")
    return ("Papier-Pläne: " if de else "Paper plans: ") + (", " if de else ", ").join(parts) + "."


def _render(summary: Mapping[str, Any], de: bool) -> str:
    eyebrow = "Was TIM gerade sagt" if de else "What TIM's analysis says now"
    if not summary.get("available"):
        text = ("Noch keine BTC-Kerzen aus der Runtime: keine Zusammenfassung." if de
                else "No BTC candles from the runtime yet: no summary.")
        return f"<section class='cc-section tc-summary' data-summary='{SCHEMA}'><p class='cc-section__eyebrow'>{eyebrow}</p><p class='empty'>{text}</p></section>"
    price = _price_de if de else _price_en
    bias = (BIAS_DE if de else BIAS_EN).get(summary["bias"], summary["bias"])
    if summary.get("weekly_confirms"):
        bias += ", Woche bestätigt" if de else ", week confirms"
    location = (LOCATION_DE if de else LOCATION_EN).get(summary.get("location"))
    stamp = _local(summary["last_close_time"], with_day=False)
    moment = _as_datetime(summary["last_close_time"])
    zone = moment.astimezone(LOCAL).tzname() if moment else ""
    if de:
        head = f"BTC {_safe(price(summary['last']))} $ (30m-Schluss {_safe(stamp)}). Übergeordnet: {_safe(bias)}."
        where = f" Der Kurs liegt {_safe(location)}." if location else ""
        levels = (f"Nächste Level darüber: {_level_text(summary['levels']['above'], True, 'above')}. "
                  f"Darunter: {_level_text(summary['levels']['below'], True, 'below')}.")
        structure_head = "Struktur je Zeitrahmen (BOS/MSS wie im Chart, nur per Schlusskurs):"
        footer = ("Automatisch aus TIMs Analyse, neu bei jedem Laden der Seite. Nur Beobachtung und Papier, keine Order, keine Empfehlung.")
        stale = "<p class='sev sev--warn'>Achtung: Daten veraltet, die Zusammenfassung ist nicht aktuell.</p>" if summary.get("stale") else ""
    else:
        head = f"BTC ${_safe(price(summary['last']))} (30m close {_safe(stamp)} {_safe(zone)}). Higher timeframes: {_safe(bias)}."
        where = f" Price is {_safe(location)}." if location else ""
        levels = (f"Nearest levels above: {_level_text(summary['levels']['above'], False, 'above')}. "
                  f"Below: {_level_text(summary['levels']['below'], False, 'below')}.")
        structure_head = "Structure per timeframe (BOS/MSS as drawn in the chart, closes only):"
        footer = "Generated automatically from TIM's analysis, refreshed on every page load. Observation and paper tracking only: no orders, not advice."
        stale = "<p class='sev sev--warn'>Note: data is stale, this summary is not current.</p>" if summary.get("stale") else ""
    structure = _structure_items(summary.get("structure") or [], de)
    return (
        f"<section class='cc-section tc-summary' data-summary='{SCHEMA}'><p class='cc-section__eyebrow'>{eyebrow}</p>{stale}"
        f"<p class='tc-summary__lead'>{head}{where}</p><p>{levels}</p>"
        + (f"<p>{structure_head}</p><ul class='tc-summary__tf'>{structure}</ul>" if structure else "")
        + f"<p>{_plan_text(summary.get('plans') or [], de)}</p><p class='cc-note'>{footer}</p></section>"
    )


def render_de(summary: Mapping[str, Any]) -> str:
    return _render(summary, True)


def render_en(summary: Mapping[str, Any]) -> str:
    return _render(summary, False)

