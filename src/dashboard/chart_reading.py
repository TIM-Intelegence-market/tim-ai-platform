"""TIM chart reading for traders: a few plain sentences and a small marked chart (Uzi 23.11.2026).

Uzi 23.11.2026: "im Benutzer-Zugang eine TIM Chart-Interpretation für Trader bauen", after a hand-made
example (BTC 30m footprint with boxes: the pump, the top at the call wall, sellers taking over,
the key levels, the thin zone, where price is now). This module makes the same kind of reading
automatically from the chart model the interactive chart already draws (``chart_live.build_live_chart``):

- candles of the last ``WINDOW`` bars of the chosen timeframe,
- footprint bars (real Binance trades TIM collects, BTC only): delta per bar and traded volume per price,
- the level drawings already in the chart (day, week, month, naked POC, options gamma).

Fixed rules (``RULES``), no fitting, no prediction model:

1. The move: change over the window and the net delta (bought minus sold, BTC) of the window.
2. The extreme: the window high after a rise (low after a fall); a chart level within ``NEAR_PCT`` is named;
   when the next bar's delta points the other way, "buyers ran out" / "sellers ran out".
3. Who is in control now: the sign of the delta of the last ``CONTROL_BARS`` bars (all the same = that side).
4. Key levels: nearest level below (support) and above (resistance), at least ``MIN_GAP_PCT`` away; the
   window's busiest price (most volume traded) joins the candidates.
5. Thin zone: the longest run of price rows between the window's low and high with under ``THIN_SHARE`` of
   the median row volume (at least ``THIN_MIN_ROWS`` rows): few trades there, little to slow price down.

Everything here describes what already happened. It is information, not a signal and not advice;
the page says so. Without footprint data the delta parts are left out, not guessed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from src.dashboard.helpers import _safe

SCHEMA = "chart_reading/1"
LOCAL = ZoneInfo("Europe/Berlin")
TIMEFRAMES = ("15m", "30m", "1h", "4h")
DEFAULT_TF = "30m"
WINDOW = 24            # bars read and drawn (30m: 12 hours)
CONTROL_BARS = 3       # bars that decide who is in control now
NEAR_PCT = 0.3         # a level this close (in %) to the extreme counts as "at" it
MIN_GAP_PCT = 0.1      # support/resistance at least this far from the price
THIN_SHARE = 0.25      # a row with less than this share of the median row volume is thin
THIN_MIN_ROWS = 3
LEVEL_GROUPS = ("day", "week", "month", "quarter", "year", "naked", "gamma")
RULES = (f"window {WINDOW} bars", f"control = last {CONTROL_BARS} bar deltas", f"near = {NEAR_PCT} %",
         f"thin = rows under {int(THIN_SHARE * 100)} % of the median volume, at least {THIN_MIN_ROWS} rows")


LANGS = ("en", "de")
TEXT = {
    "en": {
        "few": "Not enough candles to read the chart right now.",
        "hours": "{n} hours", "days": "{n} days",
        "move": "Last {span}: price {dir} {pct} % ({a} → {b}).", "up": "up", "down": "down",
        "net_buy": " Buyers were stronger: about {btc} net bought.", "net_sell": " Sellers were stronger: about {btc} net sold.",
        "t_move": "The move", "t_top": "Top", "t_low": "Low", "top": "Top {p} at {t}", "low": "Low {p} at {t}",
        "at": ", right at the {label}.", "dot": ".",
        "buyers_out": " Buyers ran out there: the next bar was net selling.",
        "sellers_out": " Sellers ran out there: the next bar was net buying.",
        "t_control": "Now in control",
        "c_sell": "Sellers in control: the last {n} bars were all net selling ({btc}).",
        "c_buy": "Buyers in control: the last {n} bars were all net buying ({btc}).",
        "c_flat": "No side in control: the last {n} bars were mixed.",
        "busiest": "busiest price of the window", "t_levels": "Key levels",
        "res": "resistance {p} ({label}) above", "sup": "support {p} ({label}) below", "and": " and ",
        "levels": "Key levels: {parts}.",
        "levels_both": " Above {r} buyers have the upper hand again; below {s} sellers do.",
        "t_thin": "Thin zone",
        "thin": "Thin zone {a}–{b}: few trades happened there, so there is little to slow price down if it goes back in.",
        "below_res": "{pct} % below resistance", "above_sup": "{pct} % above support", "now": "Now ~{p}",
        "read_at": "Read at {stamp}.",
        "stamp": "Read at {stamp} (Central European time) from the last {n} {tf} bars. {note} Describes what already happened; not a signal, not advice.",
        "delta_yes": "Blue bar = more buying than selling in that bar, red = more selling (real Binance trades).",
        "delta_no": "No trade data for this view: bars are coloured by close only, the buying/selling parts are left out.",
        "nfa": "Not financial advice", "aria": "Chart with TIM reading",
        "o_res": "{p} = resistance", "o_res_t": "{label}. Above it: buyers have the upper hand again",
        "o_sup": "{p} = support", "o_sup_t": "{label}. Below it: sellers have the upper hand",
        "o_thin": "Thin zone {a} – {b}", "o_thin_t": "Few trades here = little to slow price down",
        "o_flip": "Gamma flip ~{p}", "o_flip_below": "Below it: bigger swings both ways (options estimate)",
        "o_flip_above": "Above it: swings tend to be damped (options estimate)",
        "o_now": "Now ~{p}", "o_now_both": "Between support and resistance", "o_now_one": "See the levels",
        "o_head": "TIM reading · {stamp} · not financial advice",
    },
    "de": {
        "few": "Gerade zu wenige Kerzen, um den Chart zu deuten.",
        "hours": "{n} Stunden", "days": "{n} Tage",
        "move": "Letzte {span}: Preis {dir} {pct} % ({a} → {b}).", "up": "gestiegen", "down": "gefallen",
        "net_buy": " Käufer waren stärker: netto etwa {btc} gekauft.", "net_sell": " Verkäufer waren stärker: netto etwa {btc} verkauft.",
        "t_move": "Die Bewegung", "t_top": "Hoch", "t_low": "Tief", "top": "Hoch {p} um {t}", "low": "Tief {p} um {t}",
        "at": ", genau an der Marke {label}.", "dot": ".",
        "buyers_out": " Dort ging den Käufern die Kraft aus: die nächste Kerze war netto Verkauf.",
        "sellers_out": " Dort ging den Verkäufern die Kraft aus: die nächste Kerze war netto Kauf.",
        "t_control": "Wer führt jetzt",
        "c_sell": "Verkäufer führen: die letzten {n} Kerzen waren alle netto Verkauf ({btc}).",
        "c_buy": "Käufer führen: die letzten {n} Kerzen waren alle netto Kauf ({btc}).",
        "c_flat": "Keine Seite führt: die letzten {n} Kerzen waren gemischt.",
        "busiest": "meistgehandelter Preis im Ausschnitt", "t_levels": "Wichtige Marken",
        "res": "Widerstand {p} ({label}) darüber", "sup": "Stütze {p} ({label}) darunter", "and": " und ",
        "levels": "Wichtige Marken: {parts}.",
        "levels_both": " Über {r} sind Käufer wieder im Vorteil, unter {s} die Verkäufer.",
        "t_thin": "Dünne Zone",
        "thin": "Dünne Zone {a}–{b}: dort wurde wenig gehandelt, also bremst wenig, falls der Preis wieder hineinläuft.",
        "below_res": "{pct} % unter dem Widerstand", "above_sup": "{pct} % über der Stütze", "now": "Jetzt ~{p}",
        "read_at": "Gedeutet am {stamp}.",
        "stamp": "Gedeutet am {stamp} (deutsche Zeit) aus den letzten {n} {tf}-Kerzen. {note} Beschreibt, was schon passiert ist; kein Signal, keine Anlageberatung.",
        "delta_yes": "Blaue Kerze = mehr Kauf als Verkauf in dieser Kerze, rot = mehr Verkauf (echte Binance-Trades).",
        "delta_no": "Für diese Ansicht keine Tradedaten: Kerzen nur nach Schlusskurs gefärbt, Kauf/Verkauf weggelassen.",
        "nfa": "Keine Anlageberatung", "aria": "Chart mit TIM-Deutung",
        "o_res": "{p} = Widerstand", "o_res_t": "{label}. Darüber sind Käufer wieder im Vorteil",
        "o_sup": "{p} = Stütze", "o_sup_t": "{label}. Darunter sind Verkäufer im Vorteil",
        "o_thin": "Dünne Zone {a} – {b}", "o_thin_t": "Wenig Handel hier = wenig bremst den Preis",
        "o_flip": "Gamma-Flip ~{p}", "o_flip_below": "Darunter: größere Ausschläge in beide Richtungen (Optionen-Schätzung)",
        "o_flip_above": "Darüber: Ausschläge eher gedämpft (Optionen-Schätzung)",
        "o_now": "Jetzt ~{p}", "o_now_both": "Zwischen Stütze und Widerstand", "o_now_one": "Siehe die Marken",
        "o_head": "TIM-Deutung · {stamp} · keine Anlageberatung",
    },
}
# German names for the level labels the English chart model carries (prefix match, first hit wins).
LABEL_DE = (("Opt Call Wall", "Call-Wand"), ("Opt Put Wall", "Put-Wand"), ("Opt Gamma Flip", "Gamma-Flip"),
            ("Prior day", "Vortag"), ("Prior week", "Vorwoche"), ("Prior month", "Vormonat"), ("Today POC", "heute POC"),
            ("Week POC", "Woche POC"))


def _lang(lang: str | None) -> str:
    return lang if lang in LANGS else "en"


def _label(label: str, lang: str) -> str:
    if lang != "de":
        return label
    for en, de in LABEL_DE:
        if label.startswith(en):
            return de + label[len(en):]
    return label


def _dec(text: str, lang: str) -> str:
    """German decimal comma and thousands dot."""
    if lang != "de":
        return text
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _k(price: float | None, lang: str = "en") -> str:
    """64512.3 -> '64.5k' (prices above 1,000), else two decimals."""
    if price is None:
        return "–"
    return _dec(f"{price / 1000:.1f}k" if abs(price) >= 1000 else f"{price:,.2f}", lang)


def _num(price: float | None) -> str:
    return "–" if price is None else (f"{price:,.0f}" if abs(price) >= 1000 else f"{price:,.2f}")


def _clock(epoch: int | float | None) -> str:
    if epoch is None:
        return "–"
    return datetime.fromtimestamp(float(epoch), timezone.utc).astimezone(LOCAL).strftime("%H:%M")


def _btc(value: float, lang: str = "en") -> str:
    return _dec(f"{abs(value):,.0f} BTC" if abs(value) >= 10 else f"{abs(value):,.1f} BTC", lang)


def _pct(value: float, lang: str) -> str:
    return _dec(f"{abs(value):.1f}", lang)


def _levels(model: Mapping[str, Any], low: float, high: float) -> list[dict[str, Any]]:
    """Live chart levels near the window (finished history lines are left out)."""
    span = max(high - low, 1e-9)
    out, seen = [], set()
    for d in model.get("drawings") or []:
        if d.get("group") not in LEVEL_GROUPS or d.get("finished") or d.get("curve") or d.get("price") is None:
            continue
        price = float(d["price"])
        if not (low - span <= price <= high + span):
            continue
        key = (str(d.get("label")), round(price, 2))
        if key in seen:
            continue
        seen.add(key)
        out.append({"price": price, "label": str(d.get("label") or d.get("name") or "level"), "group": d["group"]})
    return out


def _window_rows(bars: Sequence[Mapping[str, Any]]) -> dict[float, float]:
    """Traded volume per footprint price row over the window."""
    rows: dict[float, float] = {}
    for bar in bars:
        for price, bid, ask in bar.get("levels") or []:
            rows[float(price)] = rows.get(float(price), 0.0) + float(bid) + float(ask)
    return rows


def _thin_zone(rows: Mapping[float, float], step: float | None, low: float, high: float, price: float) -> dict[str, float] | None:
    """Longest run of thin rows inside the window's range; ties go to the run nearest the price."""
    if not rows or not step or step <= 0:
        return None
    start = int(low // step)
    end = int(high // step)
    grid = [round(i * step, 8) for i in range(start, end + 1)]
    volumes = [rows.get(p, 0.0) for p in grid]
    busy = [v for v in volumes if v > 0]
    if len(busy) < 5:
        return None
    limit = median(busy) * THIN_SHARE
    runs, current = [], []
    for p, v in zip(grid, volumes):
        if v < limit:
            current.append(p)
        else:
            if current:
                runs.append(current)
            current = []
    if current:
        runs.append(current)
    runs = [r for r in runs if len(r) >= THIN_MIN_ROWS and r[0] > grid[0] and r[-1] < grid[-1]]  # inside, not at the edges
    if not runs:
        return None
    best = max(runs, key=lambda r: (len(r), -abs((r[0] + r[-1] + step) / 2 - price)))
    return {"low": best[0], "high": best[-1] + step}


def build_reading(model: Mapping[str, Any], now: datetime | None = None, lang: str = "en") -> dict[str, Any]:
    """Language-neutral facts plus sentences (``lang`` "en" or "de") for one English chart model."""
    now = now or datetime.now(timezone.utc)
    lang = _lang(lang)
    T = TEXT[lang]
    candles = list(model.get("candles") or [])[-WINDOW:]
    reading: dict[str, Any] = {"schema": SCHEMA, "lang": lang, "symbol": model.get("symbol"), "timeframe": model.get("timeframe"),
                               "generated_at": now.isoformat(), "rules": list(RULES), "candles": candles, "points": [],
                               "levels": [], "thin": None, "support": None, "resistance": None, "price": None, "ok": False}
    if len(candles) < 6:
        reading["sentences"] = [T["few"]]
        return reading
    times = {c["time"] for c in candles}
    footprint = model.get("footprint") or {}
    bars = [b for b in footprint.get("bars") or [] if b.get("time") in times]
    delta = {b["time"]: float(b.get("delta") or 0.0) for b in bars}
    has_delta = len(bars) >= len(candles) // 2
    price = float(candles[-1]["close"])
    low = min(float(c["low"]) for c in candles)
    high = max(float(c["high"]) for c in candles)
    first = float(candles[0]["open"])
    change = (price - first) / first * 100 if first else 0.0
    up = change >= 0
    reading.update({"price": price, "low": low, "high": high, "change_pct": round(change, 2), "has_delta": has_delta,
                    "delta": {str(t): round(v, 2) for t, v in delta.items()}, "ok": True})
    sentences: list[dict[str, Any]] = []

    # 1. The move.
    net = sum(delta.values())
    hours = (candles[-1]["time"] - candles[0]["time"]) / 3600 + (model.get("interval_seconds") or 0) / 3600
    span = T["hours"].format(n=f"{hours:.0f}") if hours < 48 else T["days"].format(n=f"{hours / 24:.0f}")
    text = T["move"].format(span=span, dir=T["up"] if up else T["down"], pct=_pct(change, lang), a=_k(first, lang), b=_k(price, lang))
    if has_delta and abs(net) > 0:
        text += T["net_buy" if net > 0 else "net_sell"].format(btc=_btc(net, lang))
    strongest = max(candles, key=lambda c: abs(delta.get(c["time"], 0.0)) if has_delta else abs(c["close"] - c["open"]))
    sentences.append({"n": 1, "title": T["t_move"], "text": text, "tone": "buy" if up else "sell",
                      "time": strongest["time"], "price": float(strongest["close"])})

    # 2. The extreme of the move.
    extreme = max(candles, key=lambda c: c["high"]) if up else min(candles, key=lambda c: c["low"])
    extreme_price = float(extreme["high"] if up else extreme["low"])
    levels = _levels(model, low, high)
    near = sorted((lv for lv in levels if abs(lv["price"] - extreme_price) / extreme_price * 100 <= NEAR_PCT),
                  key=lambda lv: abs(lv["price"] - extreme_price))
    text = T["top" if up else "low"].format(p=_k(extreme_price, lang), t=_clock(extreme["time"]))
    text += T["at"].format(label=_label(near[0]["label"], lang)) if near else T["dot"]
    reading["extreme_level"] = near[0] if near else None
    index = candles.index(extreme)
    if has_delta and index + 1 < len(candles):
        after = delta.get(candles[index + 1]["time"], 0.0)
        if up and after < 0:
            text += T["buyers_out"]
        elif not up and after > 0:
            text += T["sellers_out"]
    sentences.append({"n": 2, "title": T["t_top" if up else "t_low"], "text": text, "tone": "warn",
                      "time": extreme["time"], "price": extreme_price})

    # 3. Who is in control now.
    last = candles[-CONTROL_BARS:]
    if has_delta:
        signs = [delta.get(c["time"], 0.0) for c in last]
        recent = sum(signs)
        if all(v < 0 for v in signs):
            key, tone = "c_sell", "sell"
        elif all(v > 0 for v in signs):
            key, tone = "c_buy", "buy"
        else:
            key, tone = "c_flat", "flat"
        sentences.append({"n": 3, "title": T["t_control"], "text": T[key].format(n=CONTROL_BARS, btc=_btc(recent, lang)), "tone": tone,
                          "time": last[0]["time"], "price": float(last[0]["close"])})

    # 4. Key levels (chart levels plus the window's busiest price).
    rows = _window_rows(bars) if has_delta else {}
    step = float(footprint.get("step") or 0)
    if rows:
        busiest = max(rows, key=lambda p: (rows[p], -p))
        levels.append({"price": busiest + step / 2, "label": T["busiest"], "group": "window"})
    below = sorted((lv for lv in levels if lv["price"] < price * (1 - MIN_GAP_PCT / 100)), key=lambda lv: -lv["price"])
    above = sorted((lv for lv in levels if lv["price"] > price * (1 + MIN_GAP_PCT / 100)), key=lambda lv: lv["price"])
    support = below[0] if below else None
    resistance = above[0] if above else None
    reading.update({"support": support, "resistance": resistance, "levels": levels})
    if support or resistance:
        parts = []
        if resistance:
            parts.append(T["res"].format(p=_k(resistance["price"], lang), label=_label(resistance["label"], lang)))
        if support:
            parts.append(T["sup"].format(p=_k(support["price"], lang), label=_label(support["label"], lang)))
        text = T["levels"].format(parts=T["and"].join(parts))
        if resistance and support:
            text += T["levels_both"].format(r=_k(resistance["price"], lang), s=_k(support["price"], lang))
        sentences.append({"n": len(sentences) + 1, "title": T["t_levels"], "text": text, "tone": "level", "time": None, "price": None})

    # 5. Thin zone.
    thin = _thin_zone(rows, step, low, high, price) if rows else None
    reading["thin"] = thin
    if thin:
        sentences.append({"n": len(sentences) + 1, "title": T["t_thin"], "tone": "sell", "time": None, "price": None,
                          "text": T["thin"].format(a=_k(thin["low"], lang), b=_k(thin["high"], lang))})

    # Now.
    where = []
    if resistance:
        where.append(T["below_res"].format(pct=_pct((resistance["price"] - price) / price * 100, lang)))
    if support:
        where.append(T["above_sup"].format(pct=_pct((price - support["price"]) / price * 100, lang)))
    reading["now_text"] = T["now"].format(p=_k(price, lang)) + (": " + ", ".join(where) + "." if where else ".")
    reading["sentences"] = sentences
    reading["points"] = [s for s in sentences if s.get("time") is not None]
    return reading


# --- rendering -------------------------------------------------------------------------------------------

TONE = {"buy": "#5b8cff", "sell": "#ff6b6b", "warn": "#ffc53d", "flat": "#9aa4b2", "level": "#3ddc97"}
W, H, PAD_L, PAD_R, PAD_T, PAD_B = 960, 420, 10, 78, 16, 28


def svg(reading: Mapping[str, Any]) -> str:
    """Server-drawn chart (no script): candles, key levels, thin zone, numbered points and the price now."""
    candles = reading.get("candles") or []
    if not reading.get("ok") or not candles:
        return ""
    T = TEXT[_lang(reading.get("lang"))]
    lo, hi = reading["low"], reading["high"]
    for lv in (reading.get("support"), reading.get("resistance"), reading.get("extreme_level")):
        if lv:
            lo, hi = min(lo, lv["price"]), max(hi, lv["price"])
    pad = (hi - lo) * 0.06 or 1.0
    lo, hi = lo - pad, hi + pad
    plot_w, plot_h = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    slot = plot_w / len(candles)

    def y(p: float) -> float:
        return PAD_T + (hi - p) / (hi - lo) * plot_h

    def x(i: int) -> float:
        return PAD_L + slot * (i + 0.5)

    index = {c["time"]: i for i, c in enumerate(candles)}
    delta = reading.get("delta") or {}
    parts = [f"<svg class='rd-svg' viewBox='0 0 {W} {H}' role='img' aria-label='{_safe(T['aria'])}'>",
             f"<rect x='0' y='0' width='{W}' height='{H}' fill='#0b0f17'/>"]
    thin = reading.get("thin")
    if thin:
        top, bottom = y(thin["high"]), y(thin["low"])
        parts.append(f"<rect x='{PAD_L}' y='{top:.1f}' width='{plot_w}' height='{max(bottom - top, 1):.1f}' fill='#ff6b6b' fill-opacity='0.12'/>")
    for lv, color in ((reading.get("resistance"), TONE["level"]), (reading.get("support"), TONE["sell"]),
                      (reading.get("extreme_level"), "#b18cff")):
        if lv:
            ly = y(lv["price"])
            parts.append(f"<line x1='{PAD_L}' x2='{PAD_L + plot_w}' y1='{ly:.1f}' y2='{ly:.1f}' stroke='{color}' stroke-dasharray='8 6' stroke-width='1.5'/>")
            parts.append(f"<text x='{W - PAD_R + 6}' y='{ly + 4:.1f}' fill='{color}' font-size='13'>{_safe(_num(lv['price']))}</text>")
    for i, c in enumerate(candles):
        d = delta.get(str(c["time"]))
        rising = (d > 0) if d is not None and d != 0 else c["close"] >= c["open"]
        color = TONE["buy"] if rising else TONE["sell"]
        cx = x(i)
        body_top, body_bottom = y(max(c["open"], c["close"])), y(min(c["open"], c["close"]))
        width = max(slot * 0.6, 2)
        parts.append(f"<line x1='{cx:.1f}' x2='{cx:.1f}' y1='{y(c['high']):.1f}' y2='{y(c['low']):.1f}' stroke='{color}' stroke-width='1.2'/>")
        parts.append(f"<rect x='{cx - width / 2:.1f}' y='{body_top:.1f}' width='{width:.1f}' height='{max(body_bottom - body_top, 1):.1f}' fill='{color}'/>")
        if i % max(1, len(candles) // 6) == 0:
            parts.append(f"<text x='{cx:.1f}' y='{H - 8}' fill='#8b95a5' font-size='12' text-anchor='middle'>{_clock(c['time'])}</text>")
    for point in reading.get("points") or []:
        i = index.get(point["time"])
        if i is None:
            continue
        color = TONE.get(point["tone"], TONE["flat"])
        px, py = x(i), y(point["price"])
        py = min(max(py, PAD_T + 14), PAD_T + plot_h - 14)
        parts.append(f"<circle cx='{px:.1f}' cy='{py:.1f}' r='11' fill='#0b0f17' stroke='{color}' stroke-width='2'/>")
        parts.append(f"<text x='{px:.1f}' y='{py + 4.5:.1f}' fill='{color}' font-size='13' font-weight='700' text-anchor='middle'>{point['n']}</text>")
    price = reading["price"]
    py = y(price)
    parts.append(f"<line x1='{PAD_L}' x2='{PAD_L + plot_w}' y1='{py:.1f}' y2='{py:.1f}' stroke='#e6e9ef' stroke-dasharray='2 4' stroke-width='1'/>")
    parts.append(f"<rect x='{W - PAD_R + 2}' y='{py - 10:.1f}' width='{PAD_R - 4}' height='20' rx='3' fill='#e6e9ef'/>")
    parts.append(f"<text x='{W - PAD_R + 6}' y='{py + 4.5:.1f}' fill='#0b0f17' font-size='13' font-weight='700'>{_safe(_num(price))}</text>")
    parts.append(f"<text x='{PAD_L + 6}' y='{PAD_T + 12}' fill='#8b95a5' font-size='12'>{_safe(T['nfa'])}</text>")
    parts.append("</svg>")
    return "".join(parts)


def render(reading: Mapping[str, Any], drawing: bool = True) -> str:
    """Card body: the drawing (left out when the page shows the live chart), the numbered sentences, the price now
    and the time of the reading."""
    lang = _lang(reading.get("lang"))
    T = TEXT[lang]
    stamp = _safe(datetime.fromisoformat(str(reading["generated_at"])).astimezone(LOCAL).strftime("%d.%m.%Y %H:%M"))
    if not reading.get("ok"):
        return f"<p class='pj-empty'>{_safe((reading.get('sentences') or [''])[0])}</p><p class='rd-stamp'>{T['read_at'].format(stamp=stamp)}</p>"
    items = "".join(
        f"<li class='rd-item rd-{_safe(s['tone'])}'><b>{s['n']})</b> "
        + ("" if s["text"].startswith(s["title"]) else f"<b>{_safe(s['title'])}:</b> ") + f"{_safe(s['text'])}</li>"
        for s in reading["sentences"])
    note = T["delta_yes" if reading.get("has_delta") else "delta_no"]
    footer = T["stamp"].format(stamp=stamp, n=len(reading["candles"]), tf=_safe(reading.get("timeframe")), note=_safe(note))
    picture = f"<div class='rd-chart'>{svg(reading)}</div>" if drawing else ""
    return (picture + f"<ol class='rd-list'>{items}</ol>"
            f"<p class='rd-now'><b>{_safe(reading['now_text'])}</b></p>"
            f"<p class='rd-stamp'>{footer}</p>")


# --- overlay on the interactive chart (Uzi 23.11.2026: "AI overlay chart") ------------------------------

MAX_FLIP_PCT = 15.0  # a gamma flip further away than this is left out of the overlay


def _boxes(reading: Mapping[str, Any], model: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Text boxes for the chart: the numbered points, then one box per key level, the thin zone, the gamma flip and now."""
    lang = _lang(reading.get("lang"))
    T = TEXT[lang]
    boxes = [{"title": f"{p['n']}) {p['title']}", "text": p["text"], "tone": p["tone"], "time": p["time"], "price": p["price"]}
             for p in reading.get("points") or []]
    for key, title, text, tone in (("resistance", "o_res", "o_res_t", "level"), ("support", "o_sup", "o_sup_t", "sell")):
        lv = reading.get(key)
        if lv:
            boxes.append({"title": T[title].format(p=_k(lv["price"], lang)), "text": T[text].format(label=_label(lv["label"], lang)),
                          "tone": tone, "time": None, "price": lv["price"]})
    thin = reading.get("thin")
    if thin:
        boxes.append({"title": T["o_thin"].format(a=_k(thin["low"], lang), b=_k(thin["high"], lang)), "text": T["o_thin_t"],
                      "tone": "sell", "time": None, "price": (thin["low"] + thin["high"]) / 2})
    flip = next((float(d["price"]) for d in model.get("drawings") or []
                 if d.get("group") == "gamma" and str(d.get("label", "")).endswith("Gamma Flip") and d.get("price") is not None), None)
    price = reading["price"]
    if flip and abs(flip - price) / price * 100 <= MAX_FLIP_PCT:
        boxes.append({"title": T["o_flip"].format(p=_k(flip, lang)), "text": T["o_flip_below" if price < flip else "o_flip_above"],
                      "tone": "warn", "time": None, "price": flip})
    candles = reading["candles"]
    both = reading.get("support") and reading.get("resistance")
    boxes.append({"title": T["o_now"].format(p=_k(price, lang)), "text": T["o_now_both" if both else "o_now_one"], "tone": "now",
                  "time": candles[-1]["time"], "price": price})
    return boxes


def overlay(model: Mapping[str, Any], now: datetime | None = None) -> dict[str, Any] | None:
    """Both languages of the reading as boxes, lines and a zone for the chart's "TIM reading" layer.

    None when there is nothing to read; never raises (the chart must load without it)."""
    try:
        return _overlay(model, now)
    except Exception:  # noqa: BLE001 - the reading only hides itself
        return None


def _overlay(model: Mapping[str, Any], now: datetime | None = None) -> dict[str, Any] | None:
    now = now or datetime.now(timezone.utc)
    stamp = now.astimezone(LOCAL).strftime("%d.%m. %H:%M")
    out: dict[str, Any] = {"schema": SCHEMA, "generated_at": now.isoformat(), "window": WINDOW}
    for lang in LANGS:
        reading = build_reading(model, now, lang=lang)
        if not reading.get("ok"):
            return None
        lines = [{"price": lv["price"], "tone": tone} for lv, tone in ((reading.get("resistance"), "level"), (reading.get("support"), "sell"),
                                                                     (reading.get("extreme_level"), "wall")) if lv]
        out[lang] = {"head": TEXT[lang]["o_head"].format(stamp=stamp), "boxes": _boxes(reading, model), "lines": lines,
                     "thin": reading.get("thin"), "from": reading["candles"][0]["time"]}
    return out
