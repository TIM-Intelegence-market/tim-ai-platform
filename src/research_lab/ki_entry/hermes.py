"""Hermes (DeepSeek) next to R-KI-1: a second opinion on every KI decision and a Bitunix paper account (Uzi 23.11.2026 "go hermes").

Two parts, both paper only:

1. ``opinion``: after a KI decision, Hermes gets the public picture (price, zone and its marks, the AI's action,
   entry, stop, target and reason, the last candles' delta, big orders) and answers DAFÜR / DAGEGEN / URTEIL
   (same three lines as ``plan_opinion``). Hermes runs DeepSeek in the cloud, so the prompt holds public market
   numbers only: no key, no account data, no code. Asked within ``OPINION_WINDOW_S`` of the decision; a failed
   call writes nothing and is tried again on the next run inside that window.
2. ``bitunix_fill``: every finished KI paper trade is booked on a Bitunix paper account: ``EQUITY`` USDT,
   ``RISK_SHARE`` of the equity at risk, maker fee in (limit entry), taker fee out, slippage at the stop
   (fees from ``bitunix.contract``, Uzi's VIP0 figures), margin at most ``MARGIN_MAX`` of the equity (Uzi:
   0,5 to 5 %, cross), the leverage that needs, and whether Bitunix allows it. No order, no key is used.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from src.dashboard.plan_opinion import parse
from src.research_lab.bitunix.contract import (
    BTCUSDT,
    FEE_MAKER,
    FEE_TAKER,
    FEES_VERIFIED,
)
from src.research_lab.ki_entry import SCHEMA
from src.research_lab.ki_filter.decide import append_log

OPINION_WINDOW_S = 20 * 60
MAX_PROMPT = 1800
EQUITY = 1000.0          # Bitunix paper account, USDT
RISK_SHARE = 0.01        # 1 % of the equity at risk per trade
MARGIN_MAX = 0.05        # Uzi: margin 0,5 to 5 % of the account
STOP_SLIPPAGE = 0.0005   # 0,05 % when the stop fills (as in the Bitunix study)


def prompt(decision: Mapping[str, Any]) -> str:
    ctx = decision.get("context") or {}
    zone = decision.get("zone") or {}
    plan = decision.get("plan") or {}
    head = ("Du gibst eine Zweitmeinung zu einer Papier-Entscheidung einer anderen KI (BTC-Perp, 15 Minuten). "
            "Nutze keine Werkzeuge, urteile nur aus diesen Angaben.")
    where = (f"Zeit {ctx.get('zeit')}, Preis {decision.get('price')}. Zone {zone.get('low')}–{zone.get('high')} "
             f"(Stärke {zone.get('strength')}, Marken: {', '.join(map(str, (zone.get('sources') or [])[:6]))}), "
             f"Annäherung {((ctx.get('zone') or {}).get('annaeherung'))}.")
    lines = [head, where]
    if decision.get("action") in ("LONG", "SHORT"):
        lines.append(f"Entscheidung der KI: {decision['action']}, Einstieg {plan.get('entry')}, Stop {plan.get('stop')}, "
                     f"Ziel {plan.get('target')}. Grund: {decision.get('reason')}")
    else:
        lines.append(f"Entscheidung der KI: {decision.get('action')} (kein Trade). Grund: {decision.get('reason') or decision.get('problem')}")
    candles = ctx.get("kerzen") or []
    if candles:
        lines.append("Letzte Kerzen (Zeit, Schluss, Delta BTC): " + "; ".join(f"{c[0][-5:]} {c[4]} {c[5]}" for c in candles[-4:]) + ".")
    big = ctx.get("grosse_orders_3h") or []
    if big:
        lines.append("Große Orders: " + "; ".join(f"{b['zeit'][-5:]} {b['seite']} {b['btc']} BTC bei {b['preis']}" for b in big[-4:]) + ".")
    trend = ctx.get("trend") or {}
    lines.append(f"Trend 4 h {trend.get('aenderung_4h_pct')} %, 24 h {trend.get('aenderung_24h_pct')} %, letzter Bruch {trend.get('letzter_bruch')}; "
                 f"Funding {ctx.get('funding_pct')} %, OI 24 h {ctx.get('oi_aenderung_24h_pct')} %.")
    lines.append("Antworte auf Deutsch in genau drei Zeilen und sonst nichts:\nDAFÜR: <ein Satz>\nDAGEGEN: <ein Satz>\n"
                 "URTEIL: DAFÜR oder DAGEGEN oder NEUTRAL")
    return "\n".join(lines)[:MAX_PROMPT]


def opinions(records: list[dict[str, Any]], log_path: Path, ask: Callable[[str], Mapping[str, Any]], now: float,
             written_at: str) -> list[dict[str, Any]]:
    """At most one Hermes call per run: the oldest decision inside the window without an opinion."""
    done = {r.get("decision_id") for r in records if r.get("kind") == "hermes"}
    for d in records:
        if d.get("kind") != "decision" or d["id"] in done or not 0 <= now - float(d["candle_epoch"]) <= OPINION_WINDOW_S:
            continue
        text = prompt(d)
        answer = ask(text)
        if not answer.get("ok"):
            return [{"decision_id": d["id"], "failed": str(answer.get("error") or "")[:200]}]
        opinion = parse(str(answer.get("answer") or ""))
        record = append_log(log_path, {"schema": SCHEMA, "kind": "hermes", "decision_id": d["id"], "action": d.get("action"),
                                       **opinion, "seconds": answer.get("seconds"), "prompt_chars": len(text),
                                       "written_at": written_at}, records)
        return [{k: record[k] for k in ("decision_id", "verdict", "pro", "contra")}]
    return []


def bitunix_fill(decision: Mapping[str, Any], result: Mapping[str, Any], equity: float = EQUITY) -> dict[str, Any] | None:
    """USDT figures of one finished paper trade on a Bitunix paper account, or None (not filled, no data)."""
    if result.get("outcome") in ("nicht gefüllt", "Daten fehlen") or result.get("fill") is None:
        return None
    plan = decision["plan"]
    fill, exit_price = float(result["fill"]), float(result["exit"])
    risk_price = abs(float(plan["entry"]) - float(plan["stop"]))
    qty = math.floor(equity * RISK_SHARE / risk_price / BTCUSDT.min_qty) * BTCUSDT.min_qty
    if qty < BTCUSDT.min_qty:
        return None
    notional = qty * fill
    leverage = max(1, math.ceil(notional / (equity * MARGIN_MAX)))
    sign = 1 if decision["action"] == "LONG" else -1
    slip = exit_price * STOP_SLIPPAGE if result["outcome"] == "Stop" else 0.0
    gross = (exit_price - fill) * sign * qty - slip * qty
    fees = notional * FEE_MAKER + qty * exit_price * FEE_TAKER
    return {"equity": equity, "qty_btc": round(qty, 4), "notional_usdt": round(notional, 2), "leverage": leverage,
            "margin_usdt": round(notional / leverage, 2), "allowed": BTCUSDT.leverage_allowed(leverage, notional),
            "fees_usdt": round(fees, 3), "pnl_usdt": round(gross - fees, 3), "fees_verified": FEES_VERIFIED}


def bitunix(records: Sequence[Mapping[str, Any]], equity: float = EQUITY) -> dict[str, Any]:
    """The Bitunix paper account over all finished KI trades, in order."""
    decisions = {r["id"]: r for r in records if r.get("kind") == "decision"}
    balance, trades = equity, []
    for r in records:
        if r.get("kind") != "result" or r.get("decision_id") not in decisions:
            continue
        row = bitunix_fill(decisions[r["decision_id"]], r, balance)
        if row is None:
            continue
        balance = round(balance + row["pnl_usdt"], 3)
        trades.append({"decision_id": r["decision_id"], **row, "balance": balance})
    return {"start_usdt": equity, "balance_usdt": balance, "trades": len(trades), "pnl_usdt": round(balance - equity, 3),
            "fees_usdt": round(sum(t["fees_usdt"] for t in trades), 3), "last": trades[-5:],
            "note": f"Papier, {int(RISK_SHARE * 100)} % Risiko je Trade, Marge höchstens {int(MARGIN_MAX * 100)} %, "
                    f"Gebühren {FEE_MAKER * 100:.2f} % rein / {FEE_TAKER * 100:.2f} % raus"
                    + ("" if FEES_VERIFIED else " (Uzis VIP0-Angaben, nicht amtlich bestätigt)")}


def hermes_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    results = {r["decision_id"]: r for r in records if r.get("kind") == "result"}
    rows: dict[str, dict[str, Any]] = {}
    for h in (r for r in records if r.get("kind") == "hermes"):
        row = rows.setdefault(h.get("verdict") or "UNKLAR", {"n": 0, "trades": 0, "sum_r": 0.0})
        row["n"] += 1
        res = results.get(h["decision_id"])
        if res and res.get("r") is not None and res.get("outcome") != "nicht gefüllt":
            row["trades"] += 1
            row["sum_r"] = round(row["sum_r"] + float(res["r"]), 3)
    return {"opinions": sum(r["n"] for r in rows.values()), "by_verdict": rows}
