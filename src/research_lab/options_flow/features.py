"""A3: options-flow features as plain numbers. No rule, no score, no decision is made here.

Point-in-time rule (data contract): a feature at time ``t_ms`` uses only rows TIM had **received** by then
(``recv_ms <= t_ms``), not only rows the exchange stamped before ``t_ms``. Thresholds such as ``big_usd`` are passed in
by the caller; they must be fixed from training data before a study looks at validation (S33 draft).

Directional sign of a trade (taker view): call bought or put sold = +1 (bullish exposure), call sold or put bought = -1.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

DAY_MS = 86_400_000


def direction(trade: Mapping[str, Any]) -> int:
    buy = trade["side"] == "buy"
    return 1 if trade["is_call"] == buy else -1


def visible(trades: Iterable[Mapping[str, Any]], t_ms: int, span_ms: int) -> list[Mapping[str, Any]]:
    """Trades in the window ``(t - span, t]`` by exchange time that had been received by ``t``."""
    lo = t_ms - span_ms
    return [r for r in trades if r["recv_ms"] <= t_ms and lo < r["ts_ms"] <= t_ms]


def _ratio(a: float, b: float) -> float | None:
    return a / b if b > 0 else None


def flow_features(trades: Iterable[Mapping[str, Any]], t_ms: int, span_ms: int, *, big_usd: float,
                  short_days: float = 7.0) -> dict[str, Any]:
    """Flow numbers over one window. ``trades`` are derived rows from ``contract.normalize_trade``."""
    if big_usd <= 0 or span_ms <= 0:
        raise ValueError("big_usd and span_ms must be positive")
    rows = visible(trades, t_ms, span_ms)
    total = signed = call_p = put_p = buy_p = 0.0
    big_n = big_signed = 0
    block_p = block_signed = short_p = 0.0
    liq_n = 0
    for r in rows:
        if r.get("liquidation"):
            liq_n += 1
            continue  # forced flow is counted, not read as an opinion
        p = float(r["premium_usd"])
        d = direction(r)
        total += p
        signed += d * p
        if r["is_call"]:
            call_p += p
        else:
            put_p += p
        if r["side"] == "buy":
            buy_p += p
        if p >= big_usd:
            big_n += 1
            big_signed += d
        if r.get("block"):
            block_p += p
            block_signed += d * p
        if r["expiry_ms"] - r["ts_ms"] <= short_days * DAY_MS:
            short_p += p
    return {
        "t_ms": t_ms, "span_ms": span_ms, "n": len(rows) - liq_n, "liquidations": liq_n,
        "premium_usd": total,
        "signed_premium_usd": signed,
        "signed_share": _ratio(signed, total),
        "put_call_premium": _ratio(put_p, call_p),
        "buy_share": _ratio(buy_p, total),
        "big_n": big_n, "big_signed": big_signed,
        "block_share": _ratio(block_p, total), "block_signed_usd": block_signed,
        "short_share": _ratio(short_p, total),
    }


def _oi(rows: Sequence[Mapping[str, Any]]) -> tuple[float, float]:
    calls = puts = 0.0
    for r in rows:
        name = str(r.get("instrument_name", ""))
        oi = r.get("open_interest")
        if not isinstance(oi, (int, float)) or isinstance(oi, bool) or oi < 0:
            continue
        if name.endswith("-C"):
            calls += oi
        elif name.endswith("-P"):
            puts += oi
    return calls, puts


def oi_features(prev: Sequence[Mapping[str, Any]] | None, now: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Open-interest level and change between two book summaries (both must be received by the feature time)."""
    c1, p1 = _oi(now)
    out: dict[str, Any] = {"call_oi": c1, "put_oi": p1, "put_call_oi": _ratio(p1, c1),
                           "call_oi_change": None, "put_oi_change": None}
    if prev is not None:
        c0, p0 = _oi(prev)
        out["call_oi_change"], out["put_oi_change"] = c1 - c0, p1 - p0
    return out


def dvol_change(result: Any, t_ms: int, lookback_ms: int) -> float | None:
    """Relative DVOL change over ``lookback_ms`` from a ``get_volatility_index_data`` result ([ts, o, h, l, c] rows).

    Uses candle closes stamped at or before ``t_ms`` only. Returns None if the shape is not as documented.
    """
    data = result.get("data") if isinstance(result, Mapping) else None
    if not isinstance(data, list):
        return None
    closes = []
    for row in data:
        if (isinstance(row, list) and len(row) >= 5 and isinstance(row[0], int)
                and isinstance(row[4], (int, float)) and row[0] <= t_ms):
            closes.append((row[0], float(row[4])))
    if len(closes) < 2:
        return None
    closes.sort()
    last_ts, last = closes[-1]
    base = [c for ts, c in closes if ts <= last_ts - lookback_ms]
    if not base or base[-1] <= 0:
        return None
    return last / base[-1] - 1.0
