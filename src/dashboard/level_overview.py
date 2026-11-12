"""Level-Übersicht: every level on the chart compressed into a few zones, for the trader to read at a glance.

Uzi 12.11.2026: "alle Level aufm Chart zu einer Analyse", "komprimieren und übersichtlich darstellen". The chart
draws dozens of lines (day/week/month/quarter/year value, highs and lows, naked POCs, anchored VWAPs with the
weekly ±2σ band, sessions, Initial Balance, 1h/4h trend lines, Strong High/Low and BOS targets). This module puts
all of them on one price axis, merges lines that lie close together into zones, weighs each zone with a fixed
table (higher timeframe = more weight) and names, for the current price: the zones above and below, the structure,
and for each side where a reaction would start, where it would be wrong and where it would aim.

Uzi, same day: TIM should decide which zones to watch, track the price decisions there and read the range as the
trade (edge to edge), spotting where volume decides and decides again. So the overview picks a watch zone on each
side (the nearest one of at least medium weight), calls the space between them the range, marks zones where the
Live-Orderflow-Lage shows absorption, and ``update`` keeps a shadow log of every visit to a watch zone with its
outcome: abgelehnt (price left on the side it came from) or akzeptiert (price went through).

Display and shadow log only. It places no order and changes no plan. The weights are fixed by hand
(``RULESET``), not learned: the studies S22 to S30 found no proven edge in level reactions on BTC after costs, and
the section says so. It does not touch the frozen Chart-Urteil (src/dashboard/chart_verdict.py).

Only values known at ``at`` are used (closed candles with close_time <= at), as in ``chart_verdict.chart_lage``.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

RULESET = "level-uebersicht/1.0"
ATR_PERIOD = 14
ZONE_ATR = 0.25  # lines closer than this share of the 1h ATR(14) form one zone
ZONE_PCT = 0.0015  # fallback width without an ATR: 0.15 % of the price
STOP_ATR = 0.5  # "wrong beyond the zone": zone edge plus this share of the ATR
STRUCTURE_TFS = ("1h", "4h")
TREND_TFS = ("1h", "4h")
SHOWN = 3  # zones listed per side
LABELS_SHOWN = 5  # line names listed per zone
STRONG, MEDIUM = 6, 3  # zone weight from which it is called stark / mittel
# Fixed weights per timeframe of a line. Higher timeframe = more weight; set by hand before any look at results.
TF_WEIGHT = {"1Y": 5, "1Q": 4, "1M": 4, "1W": 3, "1D": 2, "4h": 2, "1h": 1}
GROUP_WEIGHT = {"session": 1, "ib": 1, "running": 1}
SKIPPED_GROUPS = ("fib",)
DEFAULT_PATH = Path("data/journal/tim_level_watch.json")
SCHEMA = "tim_level_watch/1"
MAX_VISITS = 500  # closed visits kept in the shadow log
MISSING = ("Single Prints der Woche", "Liquidations-Heatmap", "Footprint je Preisstufe")  # on the chart, not in this overview


def _time(value: Any) -> datetime:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _p(value: float | None) -> str:
    return "–" if value is None else f"{value:,.0f}".replace(",", ".")


def atr(candles: Sequence[Mapping[str, Any]], period: int = ATR_PERIOD) -> float | None:
    """Mean true range of the last ``period`` closed candles."""
    if len(candles) < period + 1:
        return None
    ranges = []
    for previous, candle in zip(candles[-period - 1:-1], candles[-period:]):
        ranges.append(max(candle["high"] - candle["low"], abs(candle["high"] - previous["close"]), abs(candle["low"] - previous["close"])))
    return sum(ranges) / period


def collect(series: Mapping[str, Sequence[Mapping[str, Any]]], at: datetime, trades: Mapping[str, Any] | None = None,
            lage: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """Every line of the chart as ``{"label", "price", "weight", "group"}`` plus price, ATR and structure at ``at``."""
    from src.dashboard.chart_live import level_drawings, market_structure, trend_drawings
    from src.dashboard.chart_model import analytical_series
    from src.dashboard.chart_verdict import orderflow_view
    from src.dashboard.htf_levels import build_htf_levels

    at = _time(at)
    clean = analytical_series(series, at)  # closed candles with close_time <= at only
    base = clean.get("30m") or clean.get("15m") or clean.get("1h") or []
    if not base:
        return None
    price = float(base[-1]["close"])
    lines: list[dict[str, Any]] = []

    def add(label: str, value: Any, weight: int, group: str) -> None:
        if value is None or float(value) <= 0:
            return
        lines.append({"label": label, "price": round(float(value), 2), "weight": weight, "group": group})

    for drawing in level_drawings(clean, at, trades):
        if drawing["group"] in SKIPPED_GROUPS:
            continue
        weight = TF_WEIGHT.get(drawing.get("tf") or "", GROUP_WEIGHT.get(drawing["group"], 1))
        add(drawing["label"].split(" · ")[0], drawing.get("price"), weight, drawing["group"])
    htf = build_htf_levels(clean, at, price)
    for item in htf.get("vwaps") or []:
        add(f"{item['tf']} VWAP", item.get("value"), TF_WEIGHT.get(item["tf"], 1), "vwap")
        if item.get("key") == "week":  # the weekly VWAP carries its ±2σ band on the chart
            add("1W VWAP +2σ", item.get("upper2"), 2, "vwap_bands")
            add("1W VWAP −2σ", item.get("lower2"), 2, "vwap_bands")
    for profile in htf.get("profiles") or []:
        if profile["tf"] in ("1Q", "1Y") and profile.get("high") and profile.get("low"):
            add(f"{profile['tf']} Mitte", (profile["high"] + profile["low"]) / 2, TF_WEIGHT[profile["tf"]], "mid")
    structure: dict[str, Any] = {}
    for tf in STRUCTURE_TFS:
        candles = clean.get(tf) or []
        if len(candles) < 10:
            continue
        state = market_structure(candles, tf)
        structure[tf] = state["trend"] or "unklar"
        if state.get("protected"):
            name = "Strong Low" if state["trend"] == "UP" else "Strong High" if state["trend"] == "DOWN" else "geschütztes Level"
            add(f"{tf} {name}", state["protected"]["price"], TF_WEIGHT[tf] + 1, "structure")
        if state.get("target"):
            add(f"{tf} BOS-Ziel", state["target"]["price"], TF_WEIGHT[tf], "structure")
    for tf in TREND_TFS:
        for line in trend_drawings(clean.get(tf) or [], tf):
            if not line.get("broken"):
                add(line["label"], line["price"], TF_WEIGHT[tf], "trend")
    return {"as_of": at.isoformat(), "price": price, "atr": atr(clean.get("1h") or []), "lines": lines, "structure": structure,
            "orderflow": orderflow_view(lage, at),  # None unless fresh and taken around ``at``
            "source": "echte Trades" if trades and trades.get("days") else "Kerzen-Näherung"}


def zones(lines: Sequence[Mapping[str, Any]], price: float, tolerance: float,
          orderflow: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Lines merged into zones: a line joins the zone below it when it lies within ``tolerance`` of that zone's top.

    With a fresh orderflow view a zone is marked ``absorption`` when the Lage saw absorption at a level inside it.
    """
    absorbed = [level["price"] for level in (orderflow or {}).get("levels") or [] if level.get("absorption")]
    out: list[dict[str, Any]] = []
    for line in sorted(lines, key=lambda item: item["price"]):
        if out and line["price"] - out[-1]["high"] <= tolerance:
            zone = out[-1]
            zone["high"] = line["price"]
            if line["label"] not in zone["labels"]:
                zone["labels"].append(line["label"])
                zone["weight"] += line["weight"]
        else:
            out.append({"low": line["price"], "high": line["price"], "labels": [line["label"]], "weight": line["weight"]})
    for zone in out:
        zone["mid"] = round((zone["low"] + zone["high"]) / 2, 2)
        zone["strength"] = "stark" if zone["weight"] >= STRONG else "mittel" if zone["weight"] >= MEDIUM else "schwach"
        zone["side"] = "am Kurs" if zone["low"] - tolerance <= price <= zone["high"] + tolerance else "über" if zone["low"] > price else "unter"
        zone["distance_pct"] = round((zone["mid"] - price) / price * 100, 2)
        zone["absorption"] = any(zone["low"] - tolerance <= value <= zone["high"] + tolerance for value in absorbed)
    return out


def _bias(structure: Mapping[str, str]) -> str:
    states = [structure[tf] for tf in STRUCTURE_TFS if tf in structure]
    if states and all(state == "UP" for state in states):
        return "aufwärts"
    if states and all(state == "DOWN" for state in states):
        return "abwärts"
    return "gemischt" if states else "unbekannt"


def _reading(side: str, start: Mapping[str, Any] | None, aim: Mapping[str, Any] | None, pad: float, bias: str) -> dict[str, Any] | None:
    """One side read from the zones: react at ``start``, wrong beyond it, aim at the next zone on the way."""
    if not start or not aim:
        return None
    long = side == "LONG"
    entry = start["high"] if long else start["low"]  # the zone's edge facing the price
    stop = start["low"] - pad if long else start["high"] + pad
    target = aim["low"] if long else aim["high"]
    risk, reward = abs(entry - stop), abs(target - entry)
    if risk <= 0 or reward <= 0:
        return None
    with_structure = (bias == "aufwärts" and long) or (bias == "abwärts" and not long)
    against = (bias == "aufwärts" and not long) or (bias == "abwärts" and long)
    return {"side": side, "zone": start, "entry": round(entry, 2), "stop": round(stop, 2), "target": round(target, 2),
            "stop_pct": round(risk / entry * 100, 2), "rr": round(reward / risk, 2), "aim": aim,
            "structure": "mit der Struktur" if with_structure else "gegen die Struktur" if against else "Struktur gemischt"}


def _watch(side_zones: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The zone to watch on one side: the nearest of at least medium weight, else the nearest."""
    return next((zone for zone in side_zones if zone["weight"] >= MEDIUM), side_zones[0] if side_zones else None)


def build(series: Mapping[str, Sequence[Mapping[str, Any]]], now: datetime | None = None,
          trades: Mapping[str, Any] | None = None, lage: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """The whole overview at ``now``; None without candles."""
    now = now or datetime.now(timezone.utc)
    data = collect(series, now, trades, lage)
    if not data:
        return None
    price = data["price"]
    tolerance = ZONE_ATR * data["atr"] if data["atr"] else ZONE_PCT * price
    pad = STOP_ATR * data["atr"] if data["atr"] else 2 * tolerance
    all_zones = zones(data["lines"], price, tolerance, data["orderflow"])
    here = next((zone for zone in all_zones if zone["side"] == "am Kurs"), None)
    above = [zone for zone in all_zones if zone["side"] == "über"]
    below = [zone for zone in all_zones if zone["side"] == "unter"][::-1]  # nearest first
    bias = _bias(data["structure"])
    upper, lower = _watch(above), _watch(below)
    span = None
    if upper and lower and upper["low"] > lower["high"]:
        width = upper["low"] - lower["high"]
        span = {"low": lower["high"], "high": upper["low"], "mid": round((upper["low"] + lower["high"]) / 2, 2),
                "width_pct": round(width / price * 100, 2), "position": round((price - lower["high"]) / width, 2)}
    flow = data["orderflow"]
    return {"ruleset": RULESET, "as_of": data["as_of"], "price": price, "atr": data["atr"], "tolerance": round(tolerance, 2),
            "pad": round(pad, 2), "lines": len(data["lines"]), "zones": len(all_zones), "here": here,
            "above": above[:SHOWN], "below": below[:SHOWN], "watch": {"upper": upper, "lower": lower}, "range": span,
            "structure": data["structure"], "bias": bias, "source": data["source"],
            "orderflow": {"direction": flow.get("direction"), "strength": flow.get("strength")} if flow else None,
            "long": _reading("LONG", lower, upper, pad, bias), "short": _reading("SHORT", upper, lower, pad, bias)}


def _zone_text(zone: Mapping[str, Any]) -> str:
    span = _p(zone["low"]) if zone["high"] - zone["low"] < 1 else f"{_p(zone['low'])}–{_p(zone['high'])}"
    flow = ", Absorption gesehen" if zone.get("absorption") else ""
    labels = list(zone["labels"][:LABELS_SHOWN]) + ([f"+{len(zone['labels']) - LABELS_SHOWN} weitere"] if len(zone["labels"]) > LABELS_SHOWN else [])
    return f"{span} ({zone['strength']}, {zone['distance_pct']:+.2f} %{flow}): {', '.join(labels)}"


def _range_text(view: Mapping[str, Any]) -> str:
    span, watch = view.get("range"), view.get("watch") or {}
    if view.get("here"):
        return "Kurs steht in einer Zone: hier wird gerade entschieden. Abwarten, ob sie hält oder bricht."
    if not span:
        missing = "oben" if not watch.get("upper") else "unten"
        return f"Keine Range: {missing} liegt keine Zone mehr."
    where = "im unteren Drittel" if span["position"] < 1 / 3 else "im oberen Drittel" if span["position"] > 2 / 3 else "in der Mitte"
    return (f"Range {_p(span['low'])} bis {_p(span['high'])} ({span['width_pct']:.2f} % breit), Mitte {_p(span['mid'])}. "
            f"Kurs {where}. Im Auge behalten: unten {_p(watch['lower']['low'])}, oben {_p(watch['upper']['high'])}.")


def _reading_text(reading: Mapping[str, Any] | None, side: str) -> str:
    if not reading:
        return f"{side}: keine Zone auf dieser Seite."
    return (f"{side} an {_p(reading['entry'])}, falsch unter {_p(reading['stop'])}, Ziel {_p(reading['target'])} "
            f"(Stop {reading['stop_pct']:.2f} %, {reading['rr']:.1f} R, {reading['structure']})"
            if side == "Long" else
            f"{side} an {_p(reading['entry'])}, falsch über {_p(reading['stop'])}, Ziel {_p(reading['target'])} "
            f"(Stop {reading['stop_pct']:.2f} %, {reading['rr']:.1f} R, {reading['structure']})")


def text(view: Mapping[str, Any] | None) -> str:
    """The overview as a few plain lines (for a message or a log)."""
    if not view:
        return "Level-Übersicht: keine Kerzen."
    rows = [f"Kurs {_p(view['price'])}, Struktur {view['bias']} "
            f"({', '.join(f'{tf} {state}' for tf, state in view['structure'].items()) or 'keine Daten'}). "
            f"{view['lines']} Linien in {view['zones']} Zonen."]
    rows.append(_range_text(view))
    if view.get("here"):
        rows.append("Am Kurs: " + _zone_text(view["here"]))
    rows += ["Darüber: " + _zone_text(zone) for zone in view["above"]] or ["Darüber: keine Zone."]
    rows += ["Darunter: " + _zone_text(zone) for zone in view["below"]] or ["Darunter: keine Zone."]
    rows += [_reading_text(view.get("long"), "Long"), _reading_text(view.get("short"), "Short")]
    return "\n".join(rows)


def render_de(view: Mapping[str, Any] | None, state: Mapping[str, Any] | None = None) -> str:
    """Section "Level-Übersicht" for the chart page: short, readable on a phone."""
    from src.dashboard.helpers import _safe

    head = f"<section class='cc-section tc-levels' data-levels='{RULESET}'><p class='cc-section__eyebrow'>Level-Übersicht</p>"
    if not view:
        return head + "<p class='empty'>Keine Kerzen: keine Level-Übersicht.</p></section>"
    structure = ", ".join(f"{tf} {state}" for tf, state in view["structure"].items()) or "keine Daten"
    out = [head, f"<p><b>Kurs {_safe(_p(view['price']))}</b>, Struktur <b>{_safe(view['bias'])}</b> ({_safe(structure)}). "
                 f"{view['lines']} Linien zu {view['zones']} Zonen zusammengefasst.</p>",
           f"<p>{_safe(_range_text(view))}</p>"]
    if view.get("orderflow") and view["orderflow"].get("direction"):
        out.append(f"<p class='cc-note'>Orderflow-Welle: {_safe(str(view['orderflow']['direction']))}"
                   f"{' (' + _safe(str(view['orderflow']['strength'])) + ')' if view['orderflow'].get('strength') else ''}.</p>")
    else:
        out.append("<p class='cc-note'>Orderflow-Lage nicht frisch: ob an den Zonen Volumen entscheidet, ist gerade nicht zu sehen.</p>")

    def rows(title: str, items: Sequence[Mapping[str, Any]]) -> str:
        if not items:
            return f"<p><b>{title}:</b> keine Zone.</p>"
        return f"<p><b>{title}:</b></p><ul>" + "".join(f"<li>{_safe(_zone_text(zone))}</li>" for zone in items) + "</ul>"

    if view.get("here"):
        out.append(rows("Am Kurs", [view["here"]]))
    out.append(rows("Darüber", view["above"]))
    out.append(rows("Darunter", view["below"]))
    out.append("<p><b>Lesart:</b></p><ul>" + f"<li>{_safe(_reading_text(view.get('long'), 'Long'))}</li>"
               + f"<li>{_safe(_reading_text(view.get('short'), 'Short'))}</li></ul>")
    if state:
        counts = summary(state)
        out.append(f"<p class='cc-note'>Beobachtet seit {_safe(str(state.get('started_at', ''))[:10])}: {counts['closed']} Besuche an "
                   f"beobachteten Zonen, {counts['rejected']} abgelehnt, {counts['accepted']} akzeptiert, {counts['open']} offen.</p>")
    out.append("<p class='cc-note'>Nur Analyse und Anzeige (" + RULESET + "): keine Order, kein Plan wird geändert. Zonen = Linien näher als "
               f"{ZONE_ATR} × 1h-ATR; Gewicht nach Zeitrahmen fest von Hand gesetzt, nicht aus Daten gelernt. "
               "Level-Reaktionen haben in den Studien S22 bis S30 nach Kosten keinen belegten Vorteil gezeigt. "
               f"Level aus {_safe(view.get('source', ''))}. Nicht enthalten: {_safe(', '.join(MISSING))}.</p>")
    return "".join(out) + "</section>"


# --- Schatten: Besuche an beobachteten Zonen ---------------------------------------------------------------------


def load(path: Path = DEFAULT_PATH) -> dict[str, Any] | None:
    target = Path(path)
    if not target.is_file():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _save(state: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def summary(state: Mapping[str, Any]) -> dict[str, int]:
    visits = state.get("visits") or []
    return {"open": len(state.get("open") or []), "closed": len(visits),
            "rejected": sum(1 for visit in visits if visit["outcome"] == "abgelehnt"),
            "accepted": sum(1 for visit in visits if visit["outcome"] == "akzeptiert")}


def track(state: Mapping[str, Any] | None, view: Mapping[str, Any], previous_price: float | None = None) -> dict[str, Any]:
    """One step of the shadow log, pure: close visits the price has left, open one when it stands in a zone.

    A visit starts when the price stands in a zone and it is known from which side it came (the price of the step
    before). It ends when the price is more than ``pad`` outside the zone: on the side it came from = abgelehnt,
    on the other side = akzeptiert. Nothing here feeds a plan or an order.
    """
    out = {"schema": SCHEMA, "ruleset": RULESET, "started_at": (state or {}).get("started_at") or view["as_of"],
           "open": [], "visits": list((state or {}).get("visits") or []), "last_price": view["price"], "updated_at": view["as_of"]}
    price, last = view["price"], previous_price if previous_price is not None else (state or {}).get("last_price")
    for visit in (state or {}).get("open") or []:
        if price < visit["low"] - visit["pad"] or price > visit["high"] + visit["pad"]:
            left = "unten" if price < visit["low"] else "oben"
            out["visits"].append({**visit, "closed_at": view["as_of"], "exit_price": price, "left": left,
                                  "outcome": "abgelehnt" if left == visit["from"] else "akzeptiert"})
        else:
            out["open"].append(visit)
    here = view.get("here")
    if here and last is not None and not any(v["low"] <= here["high"] and here["low"] <= v["high"] for v in out["open"]):
        if last < here["low"] or last > here["high"]:  # the side it came from must be known
            out["open"].append({"opened_at": view["as_of"], "low": here["low"], "high": here["high"], "labels": list(here["labels"]),
                                "weight": here["weight"], "strength": here["strength"], "pad": view["pad"], "entry_price": price,
                                "from": "unten" if last < here["low"] else "oben", "absorption": bool(here.get("absorption")),
                                "bias": view["bias"]})
    out["visits"] = out["visits"][-MAX_VISITS:]
    return out


def update(path: Path, series: Mapping[str, Sequence[Mapping[str, Any]]], lage: Mapping[str, Any] | None = None,
           now: datetime | None = None, trades: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """Runtime hook: build the overview, advance the shadow log and save it. Reads only, apart from its own file."""
    view = build(series, now, trades, lage)
    if not view:
        return None
    state = track(load(path), view)
    _save(state, Path(path))
    return state
