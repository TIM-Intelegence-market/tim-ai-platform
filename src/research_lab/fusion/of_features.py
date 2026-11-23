"""P3: order-flow signals F1-F10 of the plan as pure functions (FORSCHUNGSPLAN.md, section 4).

Time rule (mandatory): a signal evaluated "at bar i" uses bars ``0..i`` only and stands at the **close of bar i**.
A swing high with R right-hand bars is known only R bars after the high; a sweep or failed breakout only after the
m-th bar has closed. Entry is at the open of bar i+1 (caller's job). Each function is tested for look-ahead by
changing bars after i.

Trades: ``{"ts_ms", "recv_ms", "price", "qty", "side"}`` with side +1 = aggressive buyer, -1 = aggressive seller.
Bars: ``Bar`` built by ``bars_from_trades``. Thresholds are passed in; they are fixed in a calibration window before a
study looks at its test data. The names describe patterns, not intent (F9 says "spoofing-like", nothing more).
Standard library only.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Bar:
    open_ms: int
    open: float
    high: float
    low: float
    close: float
    buy: float   # aggressive buy volume
    sell: float  # aggressive sell volume
    known_ms: int | None = None  # when TIM knew the whole bar (latest recv_ms of its trades)

    @property
    def delta(self) -> float:
        return self.buy - self.sell

    @property
    def volume(self) -> float:
        return self.buy + self.sell


MISSING_RECV_LATENCY_MS = 2_000  # same fixed delay as historisch.LATENCY_MS for rows without a receive time


def bars_from_trades(trades: Iterable[Mapping], bar_ms: int) -> list[Bar]:
    """Time bars by exchange time; empty intervals produce no bar (gaps stay visible to the caller).

    ``known_ms`` of a bar is the latest receive time of its trades (``ts_ms + 2 s`` where ``recv_ms`` is missing) and
    never earlier than the bar's end. Entries must not happen before it (see ``walkforward.forward_label``)."""
    if bar_ms <= 0:
        raise ValueError("bar_ms must be positive")
    rows: dict[int, list] = {}
    for t in sorted(trades, key=lambda r: (r["ts_ms"], r.get("id", 0))):
        if t["side"] not in (1, -1):
            raise ValueError("side must be +1 or -1")
        start = t["ts_ms"] - t["ts_ms"] % bar_ms
        b = rows.get(start)
        p, q = float(t["price"]), float(t["qty"])
        recv = int(t.get("recv_ms", t["ts_ms"] + MISSING_RECV_LATENCY_MS))
        if b is None:
            rows[start] = [p, p, p, p, q if t["side"] == 1 else 0.0, q if t["side"] == -1 else 0.0,
                           max(recv, start + bar_ms)]
        else:
            b[1], b[2], b[3] = max(b[1], p), min(b[2], p), p
            b[4 if t["side"] == 1 else 5] += q
            b[6] = max(b[6], recv)
    return [Bar(k, *v) for k, v in sorted(rows.items())]


def cvd(bars: Sequence[Bar], i: int) -> float:
    return sum(b.delta for b in bars[: i + 1])


def atr(bars: Sequence[Bar], i: int, n: int = 14) -> float | None:
    """Average true range of the n bars ending at i (inclusive)."""
    if i < n:
        return None
    trs = []
    for j in range(i - n + 1, i + 1):
        prev = bars[j - 1].close
        trs.append(max(bars[j].high - bars[j].low, abs(bars[j].high - prev), abs(bars[j].low - prev)))
    return sum(trs) / n


def confirmed_swings(bars: Sequence[Bar], i: int, right: int, high: bool = True) -> list[int]:
    """Indices j whose high (low) is strictly above (below) the ``right`` bars on each side, all known by bar i."""
    out = []
    for j in range(right, i - right + 1):
        v = bars[j].high if high else bars[j].low
        side = [bars[k].high if high else bars[k].low for k in range(j - right, j + right + 1) if k != j]
        if (high and all(v > s for s in side)) or (not high and all(v < s for s in side)):
            out.append(j)
    return out


# F1 ---------------------------------------------------------------------------------------------------------------
def cvd_divergence(bars: Sequence[Bar], i: int, *, lookback: int, right: int, k_sigma: float) -> int:
    """-1: new ``lookback``-bar high while CVD sits more than k sigma(delta) below its value at the last confirmed swing
    high. +1: mirror at lows. 0 otherwise."""
    if i < lookback + 1:
        return 0
    deltas = [b.delta for b in bars[max(0, i - lookback): i + 1]]
    sd = statistics.pstdev(deltas) if len(deltas) > 1 else 0.0
    now = cvd(bars, i)
    prev_high = max(b.high for b in bars[i - lookback: i])
    prev_low = min(b.low for b in bars[i - lookback: i])
    if bars[i].high > prev_high:
        sw = confirmed_swings(bars, i, right, high=True)
        if sw and now < cvd(bars, sw[-1]) - k_sigma * sd:
            return -1
    if bars[i].low < prev_low:
        sw = confirmed_swings(bars, i, right, high=False)
        if sw and now > cvd(bars, sw[-1]) + k_sigma * sd:
            return 1
    return 0


# F2 ---------------------------------------------------------------------------------------------------------------
def aggressor_imbalance(bars: Sequence[Bar], i: int, window: int, *, history: int, min_volume: float = 0.0
                        ) -> tuple[float | None, float | None]:
    """(AI, z) with AI = delta / volume over the last ``window`` bars and z against the previous ``history`` AI values
    (computed only from bars before the current window)."""
    def ai(end: int) -> float | None:
        seg = bars[end - window + 1: end + 1]
        v = sum(b.volume for b in seg)
        return sum(b.delta for b in seg) / v if v > min_volume and v > 0 else None
    if i < window - 1:
        return None, None
    now = ai(i)
    past = [x for x in (ai(e) for e in range(max(window - 1, i - history), i - window + 1)) if x is not None]
    if now is None or len(past) < 2:
        return now, None
    sd = statistics.pstdev(past)
    return now, ((now - statistics.fmean(past)) / sd) if sd > 0 else None


# F3 ---------------------------------------------------------------------------------------------------------------
def absorption(bars: Sequence[Bar], i: int, *, level: float, band: float, history: int, z_min: float,
               max_move_atr: float, atr_n: int = 14) -> int:
    """+1: bar i touches ``level +- band`` with unusually high aggressive **selling** (z of sell volume >= z_min vs the
    previous ``history`` bars) but closes no more than ``max_move_atr`` ATR below its open (sellers absorbed).
    -1: mirror with buying. The level must be fixed before the bar (for example a higher-timeframe level)."""
    a = atr(bars, i - 1, atr_n) if i >= 1 else None
    if a is None or i < history:
        return 0
    b = bars[i]
    if not (b.low <= level + band and b.high >= level - band):
        return 0
    def z(vals: list[float], v: float) -> float | None:
        sd = statistics.pstdev(vals)
        return (v - statistics.fmean(vals)) / sd if sd > 0 else None
    sells = [x.sell for x in bars[i - history: i]]
    buys = [x.buy for x in bars[i - history: i]]
    zs, zb = z(sells, b.sell), z(buys, b.buy)
    if zs is not None and zs >= z_min and b.sell > b.buy and (b.open - b.close) <= max_move_atr * a:
        return 1
    if zb is not None and zb >= z_min and b.buy > b.sell and (b.close - b.open) <= max_move_atr * a:
        return -1
    return 0


# F4 ---------------------------------------------------------------------------------------------------------------
def book_imbalance(bids: Sequence[tuple[float, float]], asks: Sequence[tuple[float, float]], levels: int) -> float | None:
    """OBI over the best ``levels`` price levels; books as (price, qty), best first."""
    b = sum(q for _, q in bids[:levels])
    a = sum(q for _, q in asks[:levels])
    return (b - a) / (b + a) if b + a > 0 else None


def microprice(bid: float, bid_qty: float, ask: float, ask_qty: float) -> float:
    if bid_qty + ask_qty <= 0:
        return (bid + ask) / 2
    return (ask * bid_qty + bid * ask_qty) / (bid_qty + ask_qty)


def ofi(prev: tuple[float, float, float, float], cur: tuple[float, float, float, float]) -> float:
    """Order-flow imbalance of one book update (Cont, Kukanov, Stoikov 2014). Tuples: (bid, bid_qty, ask, ask_qty)."""
    pb, qb0, pa, qa0 = prev
    cb, qb1, ca, qa1 = cur
    e = 0.0
    e += qb1 if cb >= pb else 0.0
    e -= qb0 if cb <= pb else 0.0
    e -= qa1 if ca <= pa else 0.0
    e += qa0 if ca >= pa else 0.0
    return e


# F5 ---------------------------------------------------------------------------------------------------------------
def pulling_stacking(prev: Mapping[float, float], cur: Mapping[float, float], executed: Mapping[float, float],
                     ref: float, max_bp: float) -> dict[str, float]:
    """Depth change on one side within ``max_bp`` basis points of ``ref`` not explained by trades.

    pulled = sum of decreases beyond what traded there; stacked = sum of increases.
    """
    pulled = stacked = 0.0
    for p in set(prev) | set(cur):
        if abs(p / ref - 1.0) * 10_000 > max_bp:
            continue
        change = cur.get(p, 0.0) - prev.get(p, 0.0)
        if change > 0:
            stacked += change
        else:
            pulled += max(0.0, -change - executed.get(p, 0.0))
    return {"pulled": pulled, "stacked": stacked}


# F6 / F7 ----------------------------------------------------------------------------------------------------------
def sweep(bars: Sequence[Bar], i: int, *, lookback: int, m: int, min_excess: float, vol_mult: float) -> int:
    """-1: within the last ``m`` bars (ending at i) price traded above the prior ``lookback``-bar high H by more than
    ``min_excess`` (fraction) on volume >= vol_mult x median volume, and bar i closes back below H. +1: mirror at lows.
    The prior range ends before the sweep window."""
    start = i - m + 1
    if start - lookback < 0:
        return 0
    prior = bars[start - lookback: start]
    med = statistics.median(b.volume for b in prior)
    window = bars[start: i + 1]
    hi, lo = max(b.high for b in prior), min(b.low for b in prior)
    if any(b.high > hi * (1 + min_excess) and b.volume >= vol_mult * med for b in window) and bars[i].close < hi:
        return -1
    if any(b.low < lo * (1 - min_excess) and b.volume >= vol_mult * med for b in window) and bars[i].close > lo:
        return 1
    return 0


def failed_breakout(bars: Sequence[Bar], i: int, *, lookback: int, m: int, min_width_atr: float) -> int:
    """-1: a close above the prior range within the last m bars, bar i closes back inside, and the m-bar delta is
    negative. +1: mirror. Range must be at least ``min_width_atr`` ATR wide (ATR known before the window)."""
    start = i - m + 1
    if start - lookback < 1:
        return 0
    prior = bars[start - lookback: start]
    hi, lo = max(b.high for b in prior), min(b.low for b in prior)
    a = atr(bars, start - 1, min(14, start - 1))
    if a is None or hi - lo < min_width_atr * a:
        return 0
    window = bars[start: i + 1]
    d = sum(b.delta for b in window)
    if any(b.close > hi for b in window[:-1]) and lo <= bars[i].close <= hi and d < 0:
        return -1
    if any(b.close < lo for b in window[:-1]) and lo <= bars[i].close <= hi and d > 0:
        return 1
    return 0


# F8 ---------------------------------------------------------------------------------------------------------------
def _dominates(a: float, b: float, ratio: float) -> bool:
    """a >= ratio * b; a positive volume against zero counts as an imbalance."""
    return a > 0 and (b == 0 or a / b >= ratio)


def stacked_imbalances(levels: Sequence[tuple[float, float, float]], *, ratio: float, run: int, tick: float) -> int:
    """Footprint levels (price, bid_vol=aggr. sells, ask_vol=aggr. buys), any order. Diagonal comparison as in common
    footprint tools: ask at level k vs bid at level k-1. +1 if ``run`` consecutive buy imbalances, -1 for sells.
    Levels further apart than one ``tick`` break a run."""
    lv = sorted(levels)
    buy = sell = best_buy = best_sell = 0
    for k in range(1, len(lv)):
        if abs(lv[k][0] - lv[k - 1][0] - tick) > 1e-9 * max(1.0, abs(tick)):
            buy = sell = 0
            continue
        ask_k, bid_below = lv[k][2], lv[k - 1][1]
        buy = buy + 1 if _dominates(ask_k, bid_below, ratio) else 0
        sell = sell + 1 if _dominates(bid_below, ask_k, ratio) else 0
        best_buy, best_sell = max(best_buy, buy), max(best_sell, sell)
    if best_buy >= run and best_sell < run:
        return 1
    if best_sell >= run and best_buy < run:
        return -1
    return 0


def volume_nodes(levels: Sequence[tuple[float, float]], *, hvn_q: float = 0.8, lvn_q: float = 0.2) -> dict:
    """High/low volume nodes and POC of a finished profile (price, volume). Use only completed sessions."""
    if not levels:
        return {"poc": None, "hvn": [], "lvn": []}
    vols = sorted(v for _, v in levels)
    def q(x: float) -> float:
        return vols[min(len(vols) - 1, int(x * (len(vols) - 1)))]
    hi, lo = q(hvn_q), q(lvn_q)
    return {"poc": max(levels, key=lambda pv: (pv[1], -pv[0]))[0],
            "hvn": sorted(p for p, v in levels if v >= hi), "lvn": sorted(p for p, v in levels if v <= lo)}


# F9 ---------------------------------------------------------------------------------------------------------------
def spoofing_like(snapshots: Sequence[tuple[int, Mapping[float, float]]], trades: Sequence[tuple[int, float, float]],
                  *, k_median: float, max_life_ms: int, max_fill_share: float = 0.1) -> list[dict]:
    """Large resting size that appears and vanishes again within ``max_life_ms`` with little traded at that price.

    Aggregated L2 shows quantity per price, not single orders, so this flags a size pattern only. No intent is
    assigned. ``snapshots`` = (ts_ms, {price: qty}) of one side, oldest first; ``trades`` = (ts_ms, price, qty).
    Only trades between appearance and disappearance count as filled. The size may vanish over several snapshots;
    a pattern still open after ``max_life_ms`` is dropped."""
    events = []
    open_: dict[float, tuple[int, float, float]] = {}  # price -> (start, size, quantity before it appeared)
    for idx in range(1, len(snapshots)):
        prev = snapshots[idx - 1][1]
        t1, cur = snapshots[idx]
        for p in [p for p, (start, _, _) in open_.items() if t1 - start > max_life_ms]:
            del open_[p]
        depth = [q for q in prev.values() if q > 0]
        med = statistics.median(depth) if depth else 0.0
        for p in set(prev) | set(cur):
            now = cur.get(p, 0.0)
            add = now - prev.get(p, 0.0)
            if p not in open_:
                if med > 0 and add >= k_median * med:
                    open_[p] = (t1, add, prev.get(p, 0.0))
                continue
            start, size, base = open_[p]
            if now <= base + 0.1 * size:
                filled = sum(q for ts, px, q in trades if px == p and start <= ts <= t1)
                if filled <= max_fill_share * size:
                    events.append({"price": p, "size": size, "life_ms": t1 - start, "filled": filled,
                                   "label": "spoofing-like (pattern only)"})
                del open_[p]
    return events


# F10 --------------------------------------------------------------------------------------------------------------
def multi_exchange(signs: Mapping[str, int], *, min_agree: int = 2) -> int:
    """Sign that at least ``min_agree`` venues share while no venue shows the opposite sign; else 0."""
    pos = sum(1 for s in signs.values() if s > 0)
    neg = sum(1 for s in signs.values() if s < 0)
    if pos >= min_agree and neg == 0:
        return 1
    if neg >= min_agree and pos == 0:
        return -1
    return 0


def clock_offset_ms(rows: Iterable[Mapping]) -> float | None:
    """Median receive delay (recv_ms - ts_ms) of one venue; used to put venues on a common grid."""
    d = [r["recv_ms"] - r["ts_ms"] for r in rows if "recv_ms" in r and "ts_ms" in r]
    return float(statistics.median(d)) if d else None


def finite(x: float | None) -> bool:
    return x is not None and math.isfinite(x)
