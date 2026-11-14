"""QM, OB and SFP as pure, causal detectors over closed candles (Uzi 14.11.2026, GOAT trading model).

Rule set ``muster-schatten/1.0``, frozen before the first run. Nothing here trades; the shadow in
``src/dashboard/pattern_shadow.py`` records what these detectors find (paper only).

HTF -> exec flow: a setup is found on the higher time frame (HTF), the entry is looked for on the exec time frame
with a clean exec order block in the same direction near the HTF zone.

- OB: after a close-confirmed BOS/MSS (``chart_live.market_structure``) the last bearish (bullish) candle at the
  origin of the impulse. Clean = the six candles before it are not a tight box (span >= ``COMPRESSION_ATR`` x ATR),
  otherwise INVALID ("compression below").
- QM (Quasimodo): an MSS. Short: head = highest swing high of the last leg, left shoulder = last swing high before
  the protected low; zone around the shoulder high, target the broken protected low, invalid above the head.
- SFP: an HTF candle wicks through an untaken confirmed swing and closes back. A bias tool: entry only after the
  HTF close, via an exec OB; target the nearest swing on the other side.

Known gaps (listed, not hidden): no 5m series on the chart (day profile uses 15m), no TPO poor high/low, single
prints or orderbook skew in the confluences yet.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from src.dashboard.chart_live import market_structure, structure_swings

RULESET = "muster-schatten/1.0"
# (name, HTF, exec): the three flows of the model; 5m execution is not on the chart series, 15m stands in for it.
PROFILES = (("day", "1h", "15m"), ("week_a", "4h", "15m"), ("week_b", "1d", "30m"), ("swing_a", "1d", "1h"), ("swing_b", "1w", "4h"))
ATR_PERIOD = 14
COMPRESSION_BARS = 6
COMPRESSION_ATR = 2.5
ZONE_PAD_ATR = 0.1
QM_ZONE_ATR = 0.5
PROXIMITY_ATR = 0.5
MIN_RR = 1.5
MAX_COST_R = 0.25  # same cut as the plan journals
RELVOL_MIN = 1.5
RELVOL_BARS = 20
DELTA_SHARE_MIN = 0.1
HTF_MAX_AGE = 20  # HTF bars a setup stays alive
WAIT_BARS = 24  # exec bars an armed plan waits for its retest
HOLD_BARS = 96
COST_PCT = 0.0014  # Bitunix taker both ways 0.12 % + 0.02 % slippage, deliberately pessimistic
LONG, SHORT = "LONG", "SHORT"


def to_time(value: Any) -> datetime:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def prep(candles: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Closed candles with datetime times, oldest first."""
    rows = [{**c, "open_time": to_time(c["open_time"]), "close_time": to_time(c["close_time"])} for c in candles if c.get("closed", True)]
    return sorted(rows, key=lambda c: c["open_time"])


def atr_at(candles: Sequence[Mapping[str, Any]], i: int, period: int = ATR_PERIOD) -> float | None:
    """Mean true range of the ``period`` candles ending at index ``i`` (inclusive)."""
    if i < period or i >= len(candles):
        return None
    total = 0.0
    for j in range(i - period + 1, i + 1):
        c, p = candles[j], candles[j - 1]
        total += max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"]))
    return total / period


def relvol(candles: Sequence[Mapping[str, Any]], i: int) -> float | None:
    """Volume of candle ``i`` against the mean of the ``RELVOL_BARS`` candles before it."""
    if i < RELVOL_BARS:
        return None
    mean = sum(c["volume"] for c in candles[i - RELVOL_BARS:i]) / RELVOL_BARS
    return candles[i]["volume"] / mean if mean > 0 else None


def _fate(candles: Sequence[Mapping[str, Any]], start: int, direction: str, invalid: float, target: float | None) -> str:
    """What the HTF did after the setup: ``gebrochen`` (close beyond the invalidation), ``Ziel`` (target reached first), ``offen``."""
    for c in candles[start + 1:]:
        if (c["close"] < invalid) if direction == LONG else (c["close"] > invalid):
            return "gebrochen"
        if target is not None and ((c["high"] >= target) if direction == LONG else (c["low"] <= target)):
            return "Ziel"
    return "offen"


def _setup(kind: str, direction: str, tf: str, candles: Sequence[Mapping[str, Any]], created: int, low: float, high: float,
           invalid: float, target: float | None, **extra: Any) -> dict[str, Any]:
    fate = _fate(candles, created, direction, invalid, target)
    age = len(candles) - 1 - created
    alive = fate == "offen" and age <= HTF_MAX_AGE
    return {"id": f"{kind}|{tf}|{direction}|{candles[created]['close_time'].isoformat()}", "kind": kind, "direction": direction, "tf": tf,
            "created": candles[created]["close_time"], "zone_low": low, "zone_high": high, "invalid_beyond": invalid, "target": target,
            "fate": fate, "alive": alive, "age_bars": age, **extra}


def order_blocks(candles: Sequence[Mapping[str, Any]], tf: str, structure: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every order block of the history (valid and invalid), one per BOS/MSS event."""
    structure = structure or market_structure(candles, tf)
    out = []
    for event in structure["events"]:
        up = event["direction"] == "UP"
        i, s = event["break_index"], event["swing_index"]
        span = range(s, i + 1)
        origin = min(span, key=lambda j: (candles[j]["low"], -j)) if up else max(span, key=lambda j: (candles[j]["high"], j))
        k = next((j for j in (origin, origin - 1, origin - 2) if j >= 0 and ((candles[j]["close"] < candles[j]["open"]) if up else (candles[j]["close"] > candles[j]["open"]))), None)
        if k is None:
            continue
        zone_low, zone_high = candles[k]["low"], candles[k]["high"]
        atr = atr_at(candles, k)
        before = candles[k - COMPRESSION_BARS:k]
        if atr is None or len(before) < COMPRESSION_BARS:
            continue  # not enough history to judge the compression
        box = max(c["high"] for c in before) - min(c["low"] for c in before)
        clean = box >= COMPRESSION_ATR * atr
        leg = candles[k:i + 1]
        target = max(c["high"] for c in leg) if up else min(c["low"] for c in leg)
        direction = LONG if up else SHORT
        out.append(_setup("OB", direction, tf, candles, i, zone_low, zone_high, zone_low if up else zone_high, target,
                          valid=clean, reason=None if clean else "Kompression darunter", ob_index=k, origin_time=candles[k]["close_time"],
                          rvol_origin=relvol(candles, k), event=event["kind"]))
    return out


def quasimodos(candles: Sequence[Mapping[str, Any]], tf: str, structure: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    structure = structure or market_structure(candles, tf)
    swings = structure_swings(candles)
    out = []
    for event in structure["events"]:
        if event["kind"] != "MSS":
            continue
        short = event["direction"] == "DOWN"  # MSS down = QM short at the old left shoulder
        p, i = event["swing_index"], event["break_index"]
        side, other = ("HIGH", "LOW") if short else ("LOW", "HIGH")
        leg = [x for x in swings if x["kind"] == side and p < x["index"] < i]
        shoulders = [x for x in swings if x["kind"] == side and x["index"] < p]
        if not leg or not shoulders:
            continue
        head = max(leg, key=lambda x: x["price"]) if short else min(leg, key=lambda x: x["price"])
        shoulder = shoulders[-1]
        if (head["price"] <= shoulder["price"]) if short else (head["price"] >= shoulder["price"]):
            continue  # no head beyond the shoulder, no quasimodo
        atr = atr_at(candles, shoulder["index"]) or atr_at(candles, i)
        if atr is None:
            continue
        price = shoulder["price"]
        low, high = (price - QM_ZONE_ATR * atr, price + ZONE_PAD_ATR * atr) if short else (price - ZONE_PAD_ATR * atr, price + QM_ZONE_ATR * atr)
        out.append(_setup("QM", SHORT if short else LONG, tf, candles, i, low, high, head["price"], event["level"],
                          valid=True, reason=None, head=head["price"], shoulder=price))
    return out


def sfps(candles: Sequence[Mapping[str, Any]], tf: str, width: int = 3) -> list[dict[str, Any]]:
    """HTF swing failures: wick beyond an untaken confirmed swing, close back inside.

    Keeps the list of swings nobody has traded through yet; a candle that wicks through one and closes back is the SFP,
    a candle that closes beyond it takes it out of the list.
    """
    by_ready: dict[int, list[dict[str, Any]]] = {}
    for s in structure_swings(candles, width):
        by_ready.setdefault(s["index"] + width + 1, []).append(s)  # usable from the candle after its confirmation
    open_swings: list[dict[str, Any]] = []
    confirmed: dict[str, list[dict[str, Any]]] = {"HIGH": [], "LOW": []}
    out = []
    for j, c in enumerate(candles):
        for s in by_ready.get(j, []):
            open_swings.append(s)
            confirmed[s["kind"]].append(s)
        keep = []
        for s in open_swings:
            short, level = s["kind"] == "HIGH", s["price"]
            beyond = c["high"] > level if short else c["low"] < level
            if not beyond:
                keep.append(s)
                continue
            if (c["close"] < level) if short else (c["close"] > level):
                opposite = [x for x in confirmed["LOW" if short else "HIGH"] if x["index"] + width < j and ((x["price"] < c["close"]) if short else (x["price"] > c["close"]))]
                if opposite:
                    wick = c["high"] if short else c["low"]
                    low, high = (level, wick) if short else (wick, level)
                    out.append(_setup("SFP", SHORT if short else LONG, tf, candles, j, low, high, wick, opposite[-1]["price"], valid=True, reason=None, swing=level))
            # a wick through the swing, whether it closed back or beyond, ends its life as an untaken level
        open_swings = keep
    seen: set[str] = set()
    return [x for x in out if not (x["id"] in seen or seen.add(x["id"]))]


def htf_setups(candles: Sequence[Mapping[str, Any]], tf: str) -> list[dict[str, Any]]:
    structure = market_structure(candles, tf)
    return order_blocks(candles, tf, structure) + quasimodos(candles, tf, structure) + sfps(candles, tf)


def exec_blocks(setup: Mapping[str, Any], exec_candles: Sequence[Mapping[str, Any]], exec_tf: str, htf_atr: float,
                blocks: Sequence[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Clean exec order blocks in the setup's direction, formed after the setup and near its zone."""
    if not setup["valid"]:
        return []
    low, high = setup["zone_low"] - PROXIMITY_ATR * htf_atr, setup["zone_high"] + PROXIMITY_ATR * htf_atr
    return [ob for ob in (blocks if blocks is not None else order_blocks(exec_candles, exec_tf))
            if ob["valid"] and ob["direction"] == setup["direction"] and ob["created"] >= setup["created"]
            and ob["zone_low"] <= high and ob["zone_high"] >= low]


def delta_share(trades: Mapping[str, Any] | None, start: datetime, end: datetime) -> float | None:
    """(buy - sell) / total of the aggressive volume in [start, end) from the footprint store; None when not covered."""
    if not trades or not trades.get("days"):
        return None
    a, b = start.timestamp(), end.timestamp()
    buy = sell = 0.0
    covered = 0
    first = min((rows[0][0] for rows in trades["days"].values() if rows), default=None)
    for rows in trades["days"].values():
        for t, _level, bid, ask in rows:
            if a <= t < b:
                sell += bid
                buy += ask
                covered += 1
    if not covered or first is None or a < first:
        return None
    total = buy + sell
    return (buy - sell) / total if total > 0 else None


def confluences(direction: str, exec_candles: Sequence[Mapping[str, Any]], origin_rvol: float | None, retest_index: int,
                trades: Mapping[str, Any] | None) -> dict[str, Any]:
    """Valid orderflow confluences at the retest: RVOL at the origin, RVOL at the retest, trapped traders (delta against the trade)."""
    c = exec_candles[retest_index]
    rv = relvol(exec_candles, retest_index)
    share = c.get("delta_share")  # studies hand the candle its own delta share; the live shadow reads the footprint store
    if share is None:
        share = delta_share(trades, c["open_time"], c["close_time"])
    found = {"rvol_origin": bool(origin_rvol is not None and origin_rvol >= RELVOL_MIN),
             "rvol_retest": bool(rv is not None and rv >= RELVOL_MIN),
             "trapped": bool(share is not None and ((share <= -DELTA_SHARE_MIN) if direction == LONG else (share >= DELTA_SHARE_MIN)))}
    return {"count": sum(found.values()), "found": found, "rvol_retest": rv, "delta_share": share}


def risk_multiplier(count: int, htf: str) -> float:
    """0.7R with one confluence, 1R with two or more, doubled from 4h up (the model's own sizing)."""
    base = 0.7 if count == 1 else 1.0
    return base * (2.0 if htf in ("4h", "1d", "1w") else 1.0)
