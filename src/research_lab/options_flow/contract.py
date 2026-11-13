"""A2 data contract: raw Deribit option trades stay unchanged on disk, derived columns are computed here.

Rules (docs/research_lab/OPTIONSFLOW_DATENVERTRAG.md):
- Raw rows are never edited. ``normalize_trade`` builds a separate derived row.
- Time is UTC milliseconds. ``recv_ms`` is when TIM saw the row; a feature at time t may only use rows with
  ``recv_ms <= t`` (the exchange time alone is not enough, the row may arrive later).
- ``side`` is the taker side (Deribit ``direction``): buy = taker lifted the ask. Aggressor side is therefore known
  for on-book trades. Block trades (``block_trade_id``) and liquidations are flagged, not mixed in silently.
- Premium: Deribit quotes option prices in the underlying (BTC). ``premium_usd = price * amount * index_price``.
"""
from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from datetime import UTC
from pathlib import Path
from typing import Any

from src.options_gamma.snapshot import parse_instrument
from src.research_lab.bitunix.recorder import read_segment

REQUIRED = ("trade_id", "timestamp", "instrument_name", "direction", "price", "amount", "index_price")


class Rejected(ValueError):
    """Raw row cannot be used; ``args[0]`` is a short reason code for the audit counters."""


def _num(value: Any, field: str, *, positive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Rejected(f"bad_{field}")
    if positive and value <= 0:
        raise Rejected(f"bad_{field}")
    return float(value)


def normalize_trade(raw: Mapping[str, Any], recv_ms: int) -> dict[str, Any]:
    for key in REQUIRED:
        if key not in raw:
            raise Rejected(f"missing_{key}")
    trade_id = raw["trade_id"]
    if not isinstance(trade_id, str) or not trade_id:
        raise Rejected("bad_trade_id")
    ts = raw["timestamp"]
    if isinstance(ts, bool) or not isinstance(ts, int) or ts <= 0:
        raise Rejected("bad_timestamp")
    side = raw["direction"]
    if side not in ("buy", "sell"):
        raise Rejected("bad_direction")
    try:
        currency, expiry, strike, is_call = parse_instrument(str(raw["instrument_name"]))
    except ValueError as exc:
        raise Rejected("bad_instrument") from exc
    price = _num(raw["price"], "price", positive=False)
    if price < 0:
        raise Rejected("bad_price")
    amount = _num(raw["amount"], "amount")
    index_price = _num(raw["index_price"], "index_price")
    iv = raw.get("iv")
    iv = float(iv) if isinstance(iv, (int, float)) and not isinstance(iv, bool) and math.isfinite(iv) and iv > 0 else None
    return {
        "trade_id": trade_id,
        "ts_ms": ts,
        "recv_ms": recv_ms,
        "latency_ms": recv_ms - ts,
        "instrument": raw["instrument_name"],
        "currency": currency,
        "expiry_ms": int(expiry.astimezone(UTC).timestamp() * 1000),
        "strike": strike,
        "is_call": is_call,
        "side": side,
        "price": price,
        "amount": amount,
        "index_price": index_price,
        "premium_usd": price * amount * index_price,
        "notional_usd": amount * index_price,
        "iv": iv,
        "block": bool(raw.get("block_trade_id")),
        "liquidation": bool(raw.get("liquidation")),
    }


def segments(root: Path, currency: str, stream: str = "TRADES") -> list[Path]:
    return sorted((root / f"{currency}OPT{stream}").glob("*.jsonl.gz"))


def iter_trades(root: Path, currency: str = "BTC") -> Iterator[dict[str, Any]]:
    """Derived trades, de-duplicated by trade_id (first receive wins), ordered by exchange time then id."""
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for path in segments(root, currency):
        for row in read_segment(path)[0]:
            if row.get("kind") != "trade":
                continue
            try:
                norm = normalize_trade(row["raw"], int(row["recv_ms"]))
            except (Rejected, KeyError, TypeError, ValueError):
                continue
            if norm["trade_id"] in seen:
                continue
            seen.add(norm["trade_id"])
            rows.append(norm)
    rows.sort(key=lambda r: (r["ts_ms"], r["trade_id"]))
    yield from rows


def audit(root: Path, currency: str = "BTC") -> dict[str, Any]:
    """Counts for the data-quality gate: rows, duplicates, rejected, gap rows, unclean segments, latency."""
    seen: set[str] = set()
    out: dict[str, Any] = {"trades": 0, "duplicates": 0, "rejected": {}, "gaps": [], "unclean_segments": 0,
                           "first_ts_ms": None, "last_ts_ms": None}
    lat: list[int] = []
    for path in segments(root, currency):
        rows, complete = read_segment(path)
        if not complete:
            out["unclean_segments"] += 1
        for row in rows:
            if row.get("kind") == "gap":
                out["gaps"].append([row.get("from_ms"), row.get("to_ms")])
                continue
            if row.get("kind") != "trade":
                continue
            try:
                norm = normalize_trade(row["raw"], int(row["recv_ms"]))
            except Rejected as exc:
                out["rejected"][exc.args[0]] = out["rejected"].get(exc.args[0], 0) + 1
                continue
            except (KeyError, TypeError, ValueError):
                out["rejected"]["malformed"] = out["rejected"].get("malformed", 0) + 1
                continue
            if norm["trade_id"] in seen:
                out["duplicates"] += 1
                continue
            seen.add(norm["trade_id"])
            out["trades"] += 1
            lat.append(norm["latency_ms"])
            ts = norm["ts_ms"]
            out["first_ts_ms"] = ts if out["first_ts_ms"] is None else min(out["first_ts_ms"], ts)
            out["last_ts_ms"] = ts if out["last_ts_ms"] is None else max(out["last_ts_ms"], ts)
    if lat:
        lat.sort()
        out["latency_ms_p50"] = lat[len(lat) // 2]
        out["latency_ms_p95"] = lat[min(len(lat) - 1, int(len(lat) * 0.95))]
        out["negative_latency"] = sum(1 for x in lat if x < 0)
    return out


__all__ = ["Rejected", "audit", "iter_trades", "normalize_trade", "segments"]
