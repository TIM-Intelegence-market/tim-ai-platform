"""Ask the local AI at strong zones, write its answer before the outcome, then play the paper trade forward.

One pass (``run``), every few minutes:

1. ``settle``: every LONG/SHORT answer without a result is played on the closed candles after it (limit entry
   within ``FILL_BARS``, stop first when a candle touches both, at most ``HOLD_BARS``, costs ``COST_PCT``). A final
   result is appended as its own record; nothing earlier is changed.
2. ``trigger``: the last closed candle touched a strong zone (``zones.STRONG``), no paper trade is open, the zone
   was not asked about within ``COOLDOWN_S`` and this candle was not asked about yet.
3. The model gets the picture (``build_context``) and answers JSON; ``check_answer`` rejects impossible plans
   (stop on the wrong side, entry far from the price, target nearer than ``MIN_RR`` x stop). A rejected plan is
   written as UNGUELTIG with the reason and never traded. A failed AI call writes nothing; the next run retries
   while the candle is still the newest.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.research_lab.ki_entry import ACTIONS, PROMPT_VERSION, RULE, SCHEMA, zones
from src.research_lab.ki_filter.decide import append_log, read_log

UTC = timezone.utc
LOCAL = ZoneInfo("Europe/Berlin")
BAR_S = 900               # 15m candles
STALE_S = 20 * 60         # the newest closed candle must have closed at most this long ago
COOLDOWN_S = 6 * 3600     # one question per zone (center rounded to ZONE_KEY_USD) in this time
ZONE_KEY_USD = 100
ENTRY_MAX_PCT = 0.5       # entry at most this far from the price
STOP_MIN_PCT, STOP_MAX_PCT = 0.15, 3.0
MIN_RR = 1.5              # target at least this many times the stop distance
FILL_BARS = 4             # the limit entry has one hour to fill
HOLD_BARS = 96            # a paper trade ends after 24 hours at the close
COST_PCT = 0.10           # fees, spread and slippage, both ways, in % of the entry price (Bitunix, maker in, taker out)
BIG_BTC = 50.0            # big orders shown to the AI
REASON_MAX = 400
PLAN_RULES = (f"15m, strong zone >= {zones.STRONG}", f"cooldown {COOLDOWN_S // 3600} h per zone",
              f"entry <= {ENTRY_MAX_PCT} % from price", f"stop {STOP_MIN_PCT}-{STOP_MAX_PCT} %", f"target >= {MIN_RR} x stop",
              f"fill within {FILL_BARS} bars", f"hold <= {HOLD_BARS} bars", f"costs {COST_PCT} %", "stop first when both")

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"aktion": {"type": "string", "enum": list(ACTIONS)},
                   "einstieg": {"type": "number"}, "stop": {"type": "number"}, "ziel": {"type": "number"},
                   "vertrauen": {"type": "number", "minimum": 0, "maximum": 1},
                   "grund": {"type": "string", "maxLength": REASON_MAX}},
    "required": ["aktion", "einstieg", "stop", "ziel", "vertrauen", "grund"],
}
INSTRUCTIONS = f"""Du bist ein erfahrener BTC-Orderflow-Trader (Bitunix-Perp). Der Preis ist gerade in eine starke Zone gelaufen:
dort liegen mehrere Marken übereinander (zum Beispiel Gamma-Wand, POC, Wochen- oder Monatsmarke, meistgehandelter Preis).
Lies das ganze Bild: Hält die Zone (Absorption: viel Gegendruck im Delta ohne Durchbruch, lange Dochte, große Orders,
die der Markt nicht durchlässt, Schluss zurück aus der Zone) oder bricht sie (Delta in Bruchrichtung, Schluss jenseits,
große Orders in Bruchrichtung)? Beachte Trend, Funding und offene Positionen (OI).
Antworte LONG oder SHORT nur, wenn das Bild klar ist, sonst NICHTS. Bei LONG/SHORT: Einstieg als Limit nahe dem aktuellen
Preis (höchstens {ENTRY_MAX_PCT} % entfernt), Stop hinter der Zone, Ziel an der nächsten Gegenzone, Ziel mindestens {MIN_RR}-mal
so weit weg wie der Stop. Kosten etwa {COST_PCT} % vom Preis pro Trade. Bei NICHTS setze Einstieg, Stop und Ziel auf 0.
Du siehst nur Daten bis jetzt. Erfinde nichts. Grund: ein bis zwei kurze Sätze auf Deutsch. Antworte nur mit JSON."""


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


def _local(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).astimezone(LOCAL).strftime("%d.%m. %H:%M")


def _epoch(value: Any) -> float | None:
    """Chart times come as epoch seconds or ISO text."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def closed_candles(model: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [c for c in model.get("candles") or [] if c.get("closed", True)]


def _delta(model: Mapping[str, Any]) -> dict[int, float]:
    return {int(b["time"]): float(b.get("delta") or 0.0) for b in (model.get("footprint") or {}).get("bars") or []}


def zone_key(zone: Mapping[str, Any]) -> int:
    return int(round(float(zone["center"]) / ZONE_KEY_USD) * ZONE_KEY_USD)


def open_trade(records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    settled = {r.get("decision_id") for r in records if r.get("kind") == "result"}
    for r in records:
        if r.get("kind") == "decision" and r.get("action") in ("LONG", "SHORT") and r["id"] not in settled:
            return r
    return None


def trigger(model: Mapping[str, Any], records: Sequence[Mapping[str, Any]], now: float) -> dict[str, Any] | None:
    """The strong zone the newest closed candle touched, or None (with the reason in ``why`` for the summary)."""
    candles = closed_candles(model)
    if len(candles) < 20:
        return {"why": "zu wenige Kerzen"}
    last = candles[-1]
    if now - (float(last["time"]) + BAR_S) > STALE_S:
        return {"why": "Kerzen veraltet"}
    if open_trade(records):
        return {"why": "Papier-Trade offen"}
    if any(r.get("kind") == "decision" and r.get("candle") == last["time"] for r in records):
        return {"why": "Kerze schon gefragt"}
    price = float(last["close"])
    found = [z for z in zones.build(model, price, candles[:-1])
             if z["strength"] >= zones.STRONG and float(last["low"]) <= z["high"] and float(last["high"]) >= z["low"]]
    if not found:
        return {"why": "keine starke Zone berührt"}
    zone = found[0]
    for r in records:
        if r.get("kind") == "decision" and r.get("zone_key") == zone_key(zone) and now - float(r.get("candle_epoch", 0)) < COOLDOWN_S:
            return {"why": "Zone kürzlich gefragt"}
    return {"zone": zone, "candle": last}


def build_context(model: Mapping[str, Any], zone: Mapping[str, Any], now: float) -> dict[str, Any]:
    """Everything up to the newest closed candle, compact and in plain words."""
    candles = closed_candles(model)
    last = candles[-1]
    price = float(last["close"])
    delta = _delta(model)
    before = candles[-2]
    came = "von oben" if float(before["close"]) > zone["high"] else ("von unten" if float(before["close"]) < zone["low"] else "aus der Zone")
    others = [z for z in zones.build(model, price, candles[:-1]) if z["center"] != zone["center"] and z["strength"] >= 2]
    above = sorted([z for z in others if z["low"] > price], key=lambda z: z["low"])[:3]
    below = sorted([z for z in others if z["high"] < price], key=lambda z: -z["high"])[:3]

    def show(z: Mapping[str, Any]) -> dict[str, Any]:
        return {"von": z["low"], "bis": z["high"], "staerke": z["strength"], "marken": z["sources"][:6],
                "abstand_pct": round((z["center"] - price) / price * 100, 2)}

    def change(bars: int) -> float | None:
        if len(candles) <= bars:
            return None
        ref = float(candles[-1 - bars]["close"])
        return round((price - ref) / ref * 100, 2)

    end = float(last["time"]) + BAR_S
    big = [{"zeit": _local(float(b["time"])), "preis": round(float(b["price"]), 1), "btc": round(float(b["quantity"]), 1),
            "seite": "Kauf" if b.get("side", 0) > 0 else "Verkauf", "boerse": b.get("venue")}
           for b in (model.get("bubbles") or {}).get("items") or []
           if float(b.get("quantity") or 0) >= BIG_BTC and end - 3 * 3600 <= float(b["time"]) < end]
    structure = [d for d in model.get("drawings") or [] if d.get("group") == "structure" and ("BOS" in str(d.get("label")) or "MSS" in str(d.get("label")))
                 and "Ziel" not in str(d.get("label")) and _epoch(d.get("start")) is not None and _epoch(d.get("start")) < end]
    last_break = max(structure, key=lambda d: _epoch(d.get("start")), default=None)
    funding = ((model.get("funding") or {}).get("points") or [])
    oi = [p for p in (model.get("oi") or {}).get("points") or [] if float(p[0]) < end]
    oi_change = round((oi[-1][1] - oi[-25][1]) / oi[-25][1] * 100, 2) if len(oi) >= 25 and oi[-25][1] else None
    return {
        "zeit": _local(float(last["time"]) + BAR_S), "preis": price, "zeitrahmen": "15m (Perp)",
        "zone": {**show(zone), "annaeherung": came, "fruehere_abpraller": zone.get("rejections", 0)},
        "zonen_darueber": [show(z) for z in above], "zonen_darunter": [show(z) for z in below],
        "kerzen": [[_local(float(c["time"])), c["open"], c["high"], c["low"], c["close"], round(delta.get(int(c["time"]), 0.0), 1),
                    round(float(c.get("volume") or 0), 1)] for c in candles[-12:]],
        "kerzen_spalten": ["zeit", "open", "high", "low", "close", "delta_btc", "volumen_btc"],
        "grosse_orders_3h": big[-12:],
        "trend": {"aenderung_4h_pct": change(16), "aenderung_24h_pct": change(96), "aenderung_3t_pct": change(288),
                  "letzter_bruch": (f"{last_break['label']} bei {round(float(last_break['price']))}" if last_break else None)},
        "funding_pct": funding[-1][1] if funding else None, "oi_aenderung_24h_pct": oi_change,
    }


def build_prompt(context: Mapping[str, Any]) -> str:
    return INSTRUCTIONS + "\n\nDATEN:\n" + json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)


def check_answer(answer: Any, price: float) -> tuple[str, dict[str, float], float, str, str | None]:
    """(action, plan, confidence, reason, problem). ``problem`` set = written as UNGUELTIG, never traded."""
    if not isinstance(answer, dict) or answer.get("aktion") not in ACTIONS:
        raise ValueError("answer without a valid aktion")
    confidence = answer.get("vertrauen")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ValueError("answer without a valid vertrauen")
    reason = str(answer.get("grund") or "")[:REASON_MAX]
    action = answer["aktion"]
    if action == "NICHTS":
        return action, {}, float(confidence), reason, None
    try:
        entry, stop, target = (float(answer[k]) for k in ("einstieg", "stop", "ziel"))
    except (KeyError, TypeError, ValueError):
        return action, {}, float(confidence), reason, "Zahlen fehlen"
    plan = {"entry": entry, "stop": stop, "target": target}
    sign = 1 if action == "LONG" else -1
    if not (sign * (target - entry) > 0 and sign * (entry - stop) > 0):
        return action, plan, float(confidence), reason, "Stop oder Ziel auf der falschen Seite"
    if abs(entry - price) / price * 100 > ENTRY_MAX_PCT:
        return action, plan, float(confidence), reason, f"Einstieg mehr als {ENTRY_MAX_PCT} % vom Preis"
    risk = abs(entry - stop) / entry * 100
    if not STOP_MIN_PCT <= risk <= STOP_MAX_PCT:
        return action, plan, float(confidence), reason, f"Stop {risk:.2f} % (erlaubt {STOP_MIN_PCT}-{STOP_MAX_PCT} %)"
    if abs(target - entry) < MIN_RR * abs(entry - stop):
        return action, plan, float(confidence), reason, f"Ziel kleiner als {MIN_RR} x Stop"
    return action, plan, float(confidence), reason, None


def play(decision: Mapping[str, Any], candles: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Paper result on the closed candles after the decision candle, or None while still running."""
    after = [c for c in candles if float(c["time"]) > float(decision["candle"])]
    plan = decision["plan"]
    entry, stop, target = plan["entry"], plan["stop"], plan["target"]
    long = decision["action"] == "LONG"
    fill_at = fill = None
    for i, c in enumerate(after[:FILL_BARS]):
        if (float(c["low"]) <= entry) if long else (float(c["high"]) >= entry):
            fill_at, fill = i, (min(entry, float(c["open"])) if long else max(entry, float(c["open"])))
            break
    if fill_at is None:
        return {"outcome": "nicht gefüllt", "r": 0.0} if len(after) >= FILL_BARS else None
    risk = abs(fill - stop)
    cost_r = fill * COST_PCT / 100 / risk
    for j, c in enumerate(after[fill_at:fill_at + HOLD_BARS]):
        high, low = float(c["high"]), float(c["low"])
        hit_stop = low <= stop if long else high >= stop
        hit_target = (high >= target if long else low <= target) and j > 0   # in the fill candle only the stop counts
        exit_price, outcome = (stop, "Stop") if hit_stop else ((target, "Ziel") if hit_target else (None, None))
        if outcome:
            break
    else:
        if len(after) < fill_at + HOLD_BARS:
            return None
        exit_price, outcome = float(after[fill_at + HOLD_BARS - 1]["close"]), "Zeit"
    gross = (exit_price - fill) / risk * (1 if long else -1)
    return {"outcome": outcome, "fill": round(fill, 1), "exit": round(exit_price, 1), "r_gross": round(gross, 3),
            "r": round(gross - cost_r, 3), "cost_r": round(cost_r, 3)}


def settle(records: list[dict[str, Any]], candles: Sequence[Mapping[str, Any]], log_path: Path, now: float) -> list[dict[str, Any]]:
    out = []
    settled = {r.get("decision_id") for r in records if r.get("kind") == "result"}
    for r in list(records):
        if r.get("kind") != "decision" or r.get("action") not in ("LONG", "SHORT") or r["id"] in settled:
            continue
        result = play(r, candles)
        if result is None:
            continue
        out.append(append_log(log_path, {"schema": SCHEMA, "kind": "result", "decision_id": r["id"], "action": r["action"],
                                         **result, "written_at": _iso(now)}, records))
    return out


def run(model: Mapping[str, Any], log_path: Path, ask: Callable[[str], Any], model_name: str,
        now: float | None = None) -> dict[str, Any]:
    now = now if now is not None else datetime.now(UTC).timestamp()
    records = read_log(log_path)
    candles = closed_candles(model)
    summary: dict[str, Any] = {"results": [], "decision": None}
    for r in settle(records, candles, log_path, now):
        summary["results"].append({k: r[k] for k in ("decision_id", "action", "outcome", "r")})
    hit = trigger(model, records, now)
    if not hit or "zone" not in hit:
        summary["waiting"] = (hit or {}).get("why")
    else:
        zone, candle = hit["zone"], hit["candle"]
        context = build_context(model, zone, now)
        prompt = build_prompt(context)
        try:
            action, plan, confidence, reason, problem = check_answer(ask(prompt), float(candle["close"]))
        except Exception as error:  # noqa: BLE001 - AI down or answer unusable: nothing written, next run retries
            summary["failed"] = type(error).__name__
        else:
            stamp = _iso(float(candle["time"]) + BAR_S)
            record = append_log(log_path, {
                "schema": SCHEMA, "rule": RULE, "prompt_version": PROMPT_VERSION, "model": model_name, "kind": "decision",
                "id": f"ki-{int(candle['time'])}", "candle": candle["time"], "candle_epoch": float(candle["time"]) + BAR_S,
                "decided_at": stamp, "price": float(candle["close"]), "zone_key": zone_key(zone),
                "zone": {k: zone[k] for k in ("low", "high", "strength", "sources", "rejections")},
                "action": "UNGUELTIG" if problem else action, "answer_action": action, "problem": problem, "plan": plan,
                "confidence": round(confidence, 3), "reason": reason, "context_hash": hashlib.sha256(prompt.encode()).hexdigest(),
                "context": context, "rules": list(PLAN_RULES) + list(zones.ZONE_RULES), "written_at": _iso(now),
            }, records)
            summary["decision"] = {k: record[k] for k in ("id", "action", "price", "plan", "reason", "problem")}
    if records:
        summary["head"] = {"count": len(records), "hash": records[-1]["hash"]}
    return summary


def report(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    decisions = [r for r in records if r.get("kind") == "decision"]
    results = {r["decision_id"]: r for r in records if r.get("kind") == "result"}
    filled = [results[d["id"]] for d in decisions if d["id"] in results and results[d["id"]]["outcome"] != "nicht gefüllt"]
    rs = [float(r["r"]) for r in filled]
    count = {a: sum(1 for d in decisions if d["action"] == a) for a in (*ACTIONS, "UNGUELTIG")}
    return {"rule": RULE, "decisions": len(decisions), "by_action": count, "trades": len(rs),
            "open": sum(1 for d in decisions if d["action"] in ("LONG", "SHORT") and d["id"] not in results),
            "not_filled": sum(1 for r in results.values() if r["outcome"] == "nicht gefüllt"),
            "sum_r": round(sum(rs), 3), "mean_r": round(sum(rs) / len(rs), 3) if rs else None,
            "wins": sum(1 for r in rs if r > 0),
            "last": [{"zeit": _local(float(d["candle_epoch"])), "aktion": d["action"], "preis": d["price"], "plan": d.get("plan"),
                      "grund": d.get("reason"), "problem": d.get("problem"), "ergebnis": results.get(d["id"], {}).get("outcome"),
                      "r": results.get(d["id"], {}).get("r")} for d in decisions[-10:]]}
