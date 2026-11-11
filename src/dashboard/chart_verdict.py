"""Chart-Urteil: TIM reads the whole chart for every plan, not only price and structure (paper shadow only).

Uzi 11.11.2026: "mir ist es sehr wichtig, dass TIM wirklich den Chart sich angucken und beurteilen kann. Nur Preis
und Struktur macht keinen Sinn." Until now the plan journals and the engine saw candles and a few candle levels;
1D/1W value levels, BOS targets, trend lines, absorption and CVD were drawn in the chart but never weighed.

Paket 1, Chart-Lage (``chart_lage``): what the chart shows at one moment, built from the same functions that draw
the chart (``chart_live.level_drawings``, ``market_structure``, ``trend_drawings``) and from the Live-Orderflow-Lage
(``src/orderflow/live_state.py``). Candles are cut at the moment with ``analytical_series`` (closed candles only),
the orderflow counts only when it was taken within ``LAGE_MAX_AGE`` of that moment. No look-ahead.

Paket 2, Chart-Urteil (``judge``): fixed rules, frozen before the start as ``RULESET``, each one a point for or
against the plan with its reason in words. No fitted weights: score = points for minus points against.
``update`` runs as a shadow next to the Orderflow-Schatten: it records the Lage and the Urteil for every new
15m/1h plan and later the journal's result. Nothing here filters, changes or places a plan. Judgement after
``MIN_CLOSED`` closed plans and ``MIN_DAYS`` days, by Uzi; only his word moves anything into the journals.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "tim_chart_verdict/1"
RULESET = "chart-urteil/1.0"  # frozen 11.11.2026; a rule change needs a new version and a new start
DEFAULT_PATH = Path("data/journal/tim_chart_verdict.json")
MIN_CLOSED = 30
MIN_DAYS = 28
LAGE_MAX_AGE = timedelta(minutes=10)
NEAR_PCT = 0.15  # "at a level": entry within 0.15 % (about 110 USD at 74k)
LINE_PCT = 0.30  # "at a trend line": entry within 0.30 % of the line's value
OBSTACLE_MIN_R = 0.25  # a level counts as obstacle only beyond 0.25 R from the entry
STRUCTURE_TFS = ("1h", "4h")
TREND_TF = "1h"
TAKE, SKIP, NEUTRAL = "NEHMEN", "AUSLASSEN", "NEUTRAL"
TAKE_AT, SKIP_AT = 2, -2
FOR, AGAINST = "dafür", "dagegen"
MAJOR_GROUPS = ("day", "week", "naked")


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _time(value: Any) -> datetime:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _num(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _p(value: float | None) -> str:
    return "–" if value is None else f"{value:,.0f}".replace(",", ".")


# --- Paket 1: Chart-Lage -----------------------------------------------------------------------------------------


def orderflow_view(lage: Mapping[str, Any] | None, at: datetime) -> dict[str, Any] | None:
    """The Live-Orderflow-Lage, only when fresh and taken within ``LAGE_MAX_AGE`` around ``at``, never after it plus that."""
    if not lage or lage.get("stale") or lage.get("price") is None or not lage.get("as_of"):
        return None
    taken = _time(lage["as_of"])
    if abs((taken - at).total_seconds()) > LAGE_MAX_AGE.total_seconds():
        return None
    wave = dict(lage.get("wave") or {})
    levels = [{"name": str(l.get("name")), "price": _num(l.get("price")), "absorption": bool(l.get("absorption")),
               "imbalance": l.get("imbalance")} for l in (lage.get("levels") or []) if _num(l.get("price")) is not None]
    return {"as_of": _iso(taken), "price": _num(lage.get("price")), "direction": wave.get("direction"),
            "strength": wave.get("strength"), "exhaustion": bool(wave.get("exhaustion")),
            "day_cvd": _num((lage.get("day") or {}).get("cvd")), "perp_delta_15m": _num((lage.get("perp") or {}).get("delta_15m")),
            "levels": levels}


def chart_lage(series: Mapping[str, Sequence[Mapping[str, Any]]], at: datetime, lage: Mapping[str, Any] | None = None,
               trades: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """What the chart shows at ``at``: value levels, structure, trend lines and orderflow. Only data known by then."""
    from src.dashboard.chart_live import level_drawings, market_structure, trend_drawings
    from src.dashboard.chart_model import analytical_series

    at = _time(at)
    clean = analytical_series(series, at)  # closed candles with close_time <= at only
    base = clean.get("30m") or clean.get("15m") or []
    if not base:
        return None
    levels = []
    for drawing in level_drawings(clean, at, trades):
        if drawing["group"] in MAJOR_GROUPS and drawing.get("price"):
            levels.append({"label": drawing["label"], "price": round(float(drawing["price"]), 2)})
    day = {d["label"].split(" ", 1)[1].split(" ")[0]: d["price"] for d in levels if d["label"].startswith("1D ") and "nPOC" not in d["label"]}
    structure = {}
    for tf in STRUCTURE_TFS:
        candles = clean.get(tf) or []
        if len(candles) < 10:
            continue
        state = market_structure(candles, tf)
        structure[tf] = {"trend": state["trend"],
                         "protected": round(state["protected"]["price"], 2) if state.get("protected") else None,
                         "target": round(state["target"]["price"], 2) if state.get("target") else None}
    lines = []
    for line in trend_drawings(clean.get(TREND_TF) or [], TREND_TF):
        if line.get("broken"):
            continue
        kind = "LOW" if line["name"].startswith("Trend Tiefs") else "HIGH"
        slope = line["price"] - line["anchor_price"]
        lines.append({"tf": TREND_TF, "kind": kind, "price": round(float(line["price"]), 2),
                      "rising": slope > 0, "label": line["label"]})
    return {"as_of": _iso(at), "price": float(base[-1]["close"]), "candle_close": _iso(base[-1]["close_time"]),
            "day": {k.lower(): v for k, v in day.items() if k in ("VAH", "POC", "VAL")}, "levels": levels,
            "structure": structure, "trendlines": lines, "orderflow": orderflow_view(lage, at),
            "levels_source": "echte Trades" if trades and trades.get("days") else "Kerzen-Näherung"}


# --- Paket 2: Chart-Urteil ---------------------------------------------------------------------------------------


def _near(a: float, b: float, pct: float) -> bool:
    return abs(a - b) / b * 100 <= pct


def judge(direction: str, entry: float, chart: Mapping[str, Any] | None, stop: float | None = None,
          target: float | None = None) -> dict[str, Any]:
    """Points for and against a plan from the chart. Every point carries its rule and its reason."""
    from src.dashboard.orderflow_shadow import BESTAETIGT, GEGEN, gate

    long = direction == "LONG"
    up = "UP" if long else "DOWN"
    points: list[dict[str, str]] = []
    skipped: list[str] = []

    def add(rule: str, side: str, text: str) -> None:
        points.append({"rule": rule, "side": side, "text": text})

    if not chart:
        return {"ruleset": RULESET, "points": [], "for": 0, "against": 0, "score": 0, "decision": NEUTRAL,
                "skipped": ["keine Chart-Lage"]}
    # R1 Wert-Lage am Vortages-Value (1D VAH/POC/VAL)
    day = chart.get("day") or {}
    vah, poc, val = day.get("vah"), day.get("poc"), day.get("val")
    if vah and val and poc:
        # Only "at" a level counts; far outside the value (acceptance or breakout) gives no point.
        cheap, dear = (val, vah) if long else (vah, val)
        if _near(entry, cheap, NEAR_PCT):
            add("R1", FOR, f"{'Long am' if long else 'Short am'} 1D {'VAL' if long else 'VAH'} {_p(cheap)}, Rand des Werts")
        elif _near(entry, dear, NEAR_PCT):
            add("R1", AGAINST, f"{'Long am' if long else 'Short am'} 1D {'VAH' if long else 'VAL'} {_p(dear)}, falsche Seite des Werts")
        elif _near(entry, poc, NEAR_PCT):
            add("R1", AGAINST, f"Einstieg am 1D POC {_p(poc)}, Mitte des Werts, kein Lagevorteil")
    else:
        skipped.append("R1 kein Vortages-Value")
    # R2 Struktur 1h und 4h
    for tf, state in (chart.get("structure") or {}).items():
        trend = state.get("trend")
        if trend is None:
            continue
        words = "aufwärts" if trend == "UP" else "abwärts"
        detail = f" (BOS-Ziel {_p(state.get('target'))})" if state.get("target") else ""
        add("R2", FOR if trend == up else AGAINST, f"{tf}-Struktur {words}{detail}")
    # R3 Stop hinter dem Strong Low/High der 1h-Struktur
    h1 = (chart.get("structure") or {}).get("1h") or {}
    if stop is not None and h1.get("protected") and h1.get("trend") == up:
        if (stop < h1["protected"]) if long else (stop > h1["protected"]):
            add("R3", FOR, f"Stop hinter dem 1h-Strong-{'Low' if long else 'High'} {_p(h1['protected'])}")
    # R4 Hindernis zwischen Einstieg und erstem Ziel (Level oder BOS-Ziel der Gegenrichtung)
    if stop is not None and target is not None and abs(entry - stop) > 0:
        risk = abs(entry - stop)
        start = entry + (OBSTACLE_MIN_R * risk if long else -OBSTACLE_MIN_R * risk)
        blockers = [(l["label"], l["price"]) for l in chart.get("levels") or []]
        for tf, state in (chart.get("structure") or {}).items():
            if state.get("trend") and state["trend"] != up and state.get("target"):
                blockers.append((f"{tf} BOS-Ziel", state["target"]))
        hit = sorted({(price, label) for label, price in blockers if (start < price < target if long else target < price < start)},
                     key=lambda x: abs(x[0] - entry))
        if hit:
            names = ", ".join(f"{label} {_p(price)}" for price, label in hit[:3])
            add("R4", AGAINST, f"vor dem Ziel {_p(target)} liegt {names}")
    else:
        skipped.append("R4 ohne Stop/Ziel")
    # R5 Trendlinie 1h (ungebrochen)
    for line in chart.get("trendlines") or []:
        value = line["price"]
        if line["kind"] == ("LOW" if long else "HIGH") and line["rising"] == long:
            if ((entry >= value) if long else (entry <= value)) and _near(entry, value, LINE_PCT):
                add("R5", FOR, f"Einstieg an der {'steigenden' if long else 'fallenden'} {line['label']} {_p(value)}")
        elif line["kind"] == ("HIGH" if long else "LOW") and line["rising"] != long:
            if ((entry <= value) if long else (entry >= value)) and _near(entry, value, LINE_PCT):
                add("R5", AGAINST, f"Einstieg direkt {'unter' if long else 'über'} der {line['label']} {_p(value)}")
    flow = chart.get("orderflow")
    if not flow:
        skipped.append("R6-R8 keine frische Orderflow-Lage")
    else:
        # R6 Absorption an einem Level nahe dem Einstieg (Stütze) oder auf dem Weg zum Ziel (Bremse)
        for level in flow.get("levels") or []:
            if not level.get("absorption") or level.get("price") is None:
                continue
            price = level["price"]
            support = (price <= entry * (1 + NEAR_PCT / 100)) if long else (price >= entry * (1 - NEAR_PCT / 100))
            if support and _near(entry, price, NEAR_PCT * 2):
                add("R6", FOR, f"Absorption am {level['name']} {_p(price)}")
            elif target is not None and ((entry < price < target) if long else (target < price < entry)):
                add("R6", AGAINST, f"Absorption auf dem Weg zum Ziel am {level['name']} {_p(price)}")
        # R7 Orderflow-Welle (dieselbe Regel wie der Orderflow-Schatten)
        verdict = gate(direction, flow)
        if verdict == BESTAETIGT:
            add("R7", FOR, f"Orderflow-Welle {'auf' if long else 'ab'}, Stärke {flow.get('strength')}")
        elif verdict == GEGEN:
            add("R7", AGAINST, f"Orderflow-Welle gegen den Plan ({flow.get('direction')}, Stärke {flow.get('strength')})")
        # R8 CVD des Tages und Perp-Delta 15 min
        cvd, perp = flow.get("day_cvd"), flow.get("perp_delta_15m")
        if cvd is not None and perp is not None and cvd != 0 and perp != 0:
            sign = 1 if long else -1
            if cvd * sign > 0 and perp * sign > 0:
                add("R8", FOR, "Tages-CVD und Perp-Delta laufen mit dem Plan")
            elif cvd * sign < 0 and perp * sign < 0:
                add("R8", AGAINST, "Tages-CVD und Perp-Delta laufen gegen den Plan")
    pro = sum(1 for p in points if p["side"] == FOR)
    con = len(points) - pro
    score = pro - con
    decision = TAKE if score >= TAKE_AT else SKIP if score <= SKIP_AT else NEUTRAL
    return {"ruleset": RULESET, "points": points, "for": pro, "against": con, "score": score, "decision": decision,
            "skipped": skipped}


def text(verdict: Mapping[str, Any]) -> str:
    """One German line: decision, counts and the reasons."""
    pro = [p["text"] for p in verdict.get("points") or [] if p["side"] == FOR]
    con = [p["text"] for p in verdict.get("points") or [] if p["side"] == AGAINST]
    line = f"{verdict.get('decision')}: {verdict.get('for', 0)} dafür, {verdict.get('against', 0)} dagegen."
    if pro:
        line += " Dafür: " + "; ".join(pro) + "."
    if con:
        line += " Dagegen: " + "; ".join(con) + "."
    return line


def current(series: Mapping[str, Sequence[Mapping[str, Any]]], lage: Mapping[str, Any] | None, now: datetime | None = None,
            trades: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """The chart read right now for a Long and a Short at the current price (display only, no stop or target)."""
    now = now or datetime.now(timezone.utc)
    chart = chart_lage(series, now, lage, trades)
    if not chart:
        return None
    return {"chart": chart, "LONG": judge("LONG", chart["price"], chart), "SHORT": judge("SHORT", chart["price"], chart)}


# --- Schatten ----------------------------------------------------------------------------------------------------


def load(path: Path) -> dict[str, Any] | None:
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


def summary(state: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """Closed plans by the Urteil's decision against all closed plans (the journal as it trades now)."""
    plans = list((state.get("plans") or {}).values())
    closed = [p for p in plans if (p.get("journal") or {}).get("status") == "CLOSED" and p["journal"].get("net_r") is not None
              and p.get("urteil")]
    rows: dict[str, dict[str, Any]] = {}
    for plan in closed:
        for key in ("alle", plan["urteil"]["decision"]):
            row = rows.setdefault(key, {"n": 0, "sum_net_r": 0.0})
            row["n"] += 1
            row["sum_net_r"] = round(row["sum_net_r"] + float(plan["journal"]["net_r"]), 4)
    for row in rows.values():
        row["avg_net_r"] = round(row["sum_net_r"] / row["n"], 4)
    kept = [p for p in closed if p["urteil"]["decision"] != SKIP]
    days = (now - _time(state["started_at"])).days
    return {"ruleset": RULESET, "plans": len(plans), "closed": len(closed), "days": days,
            "min_closed": MIN_CLOSED, "min_days": MIN_DAYS, "judgeable": len(closed) >= MIN_CLOSED and days >= MIN_DAYS,
            "by_decision": rows,
            "ohne_auslassen": {"n": len(kept), "sum_net_r": round(sum(float(p["journal"]["net_r"]) for p in kept), 4)}}


def update(path: Path, journal_paths: Sequence[Path], series: Mapping[str, Sequence[Mapping[str, Any]]],
           lage: Mapping[str, Any] | None, now: datetime | None = None, trades: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """One step: every new plan gets the Chart-Lage and the Urteil at its creation, closed plans get the journal result."""
    from src.dashboard.plan_journal import load_view

    now = now or datetime.now(timezone.utc)
    state = load(Path(path)) or {"schema": SCHEMA, "ruleset": RULESET, "started_at": _iso(now),
                                 "sources": [Path(p).name for p in journal_paths], "plans": {}}
    started = _time(state["started_at"])
    plans = state["plans"]
    for journal_path in journal_paths:
        journal = load_view(Path(journal_path))
        if journal.get("blocked"):
            continue
        for entry in journal.get("entries") or []:
            if entry.get("excluded") or not entry.get("created_at") or _time(entry["created_at"]) < started:
                continue
            key = f"{Path(journal_path).name}:{entry['id']}"
            record = plans.get(key)
            if record is None:
                created = _time(entry["created_at"])
                entry_price, stop = _num(entry.get("entry")), _num(entry.get("stop"))
                targets = [t for t in (entry.get("targets") or []) if _num(t) is not None]
                target = _num(targets[0]) if targets else None
                # The live Lage counts only if this step runs close to the plan's creation (orderflow_view checks it).
                chart = chart_lage(series, created, lage, trades)
                urteil = judge(str(entry.get("direction")), entry_price, chart, stop, target) if entry_price else None
                record = plans[key] = {"id": entry["id"], "journal_file": Path(journal_path).name, "timeframe": entry.get("timeframe"),
                                       "direction": entry.get("direction"), "created_at": entry["created_at"],
                                       "entry": entry_price, "stop": stop, "target_1": target,
                                       "seen_at": _iso(now), "chart_at_plan": chart, "urteil": urteil}
            record["journal"] = {"status": entry.get("status"), "filled_at": entry.get("filled_at"), "closed_at": entry.get("closed_at"),
                                 "exit_reason": entry.get("exit_reason"), "net_r": entry.get("net_r")}
    state["checked_at"] = _iso(now)
    state["summary"] = summary(state, now)
    _save(state, Path(path))
    return state


# --- Anzeige (Control Center, Deutsch) ---------------------------------------------------------------------------


def render_de(now_view: Mapping[str, Any] | None, state: Mapping[str, Any] | None) -> str:
    """Section "TIM liest den Chart": Long and Short at the current price with reasons, plus the shadow's progress."""
    from src.dashboard.helpers import _safe

    head = "<section class='cc-section tc-verdict' data-verdict='" + RULESET + "'><p class='cc-section__eyebrow'>TIM liest den Chart</p>"
    if not now_view:
        return head + "<p class='empty'>Keine Kerzen: kein Chart-Urteil.</p></section>"
    chart = now_view["chart"]
    rows = []
    for side in ("LONG", "SHORT"):
        verdict = now_view[side]
        items = "".join(f"<li class='tc-verdict__{'pro' if p['side'] == FOR else 'con'}'>{'+' if p['side'] == FOR else '−'} {_safe(p['text'])}</li>"
                        for p in verdict["points"])
        rows.append(f"<p><b>{side} hier ({_safe(_p(chart['price']))})</b>: {_safe(verdict['decision'])}, "
                    f"{verdict['for']} dafür, {verdict['against']} dagegen</p><ul>{items or '<li>keine Punkte</li>'}</ul>")
    flow = "" if chart.get("orderflow") else "<p class='cc-note'>Orderflow-Lage nicht frisch: Absorption, Welle und CVD fehlen im Urteil.</p>"
    progress = ""
    if state and state.get("summary"):
        s = state["summary"]
        progress = (f"<p class='cc-note'>Schatten seit {_safe(str(state.get('started_at', ''))[:10])}: {s['plans']} Pläne, "
                    f"{s['closed']}/{s['min_closed']} geschlossen, Tag {s['days']}/{s['min_days']}. "
                    + ("Vergleich bereit, Urteil durch Uzi." if s.get("judgeable") else "Noch kein Vergleich.") + "</p>")
    note = ("<p class='cc-note'>Regeln " + RULESET + " (vor dem Start eingefroren): 1D-Value-Rand, 1h/4h-Struktur, Stop hinter Strong Low/High, "
            "Level und BOS-Ziele vor dem Ziel, 1h-Trendlinien, Absorption, Orderflow-Welle, CVD. Level aus "
            + _safe(chart.get("levels_source", "")) + ". Nur Papier-Schatten: filtert und ändert keinen Plan, keine Order.</p>")
    return head + "".join(rows) + flow + progress + note + "</section>"
