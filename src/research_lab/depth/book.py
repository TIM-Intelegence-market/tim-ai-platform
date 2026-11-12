"""Local L2 order book with exact integer prices and quantities.

Prices and quantities arrive as decimal text. They are stored as integers in units of 1e-8 so that no float rounding
enters the book; every derived value (mid, band volume) is computed from these integers. Each side keeps a sorted
price list next to the level dict, so best prices and band sums are bisect lookups instead of full scans.
"""
from __future__ import annotations

import hashlib
from bisect import bisect_left, bisect_right, insort
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

SCALE = 10**8
BID, ASK = "bid", "ask"


def to_units(text: str | float | Decimal) -> int:
    """Decimal text to integer 1e-8 units. Refuses NaN, infinity, negatives and finer precision than 1e-8."""
    if isinstance(text, bool):
        raise TypeError("bool is not a number")
    try:
        d = Decimal(str(text))
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {text!r}") from exc
    if not d.is_finite() or d < 0:
        raise ValueError(f"invalid value: {text!r}")
    scaled = d * SCALE
    if scaled != scaled.to_integral_value():
        raise ValueError(f"more precision than 1e-8: {text!r}")
    return int(scaled)


class LocalBook:
    def __init__(self) -> None:
        self.levels: dict[str, dict[int, int]] = {BID: {}, ASK: {}}
        self._prices: dict[str, list[int]] = {BID: [], ASK: []}

    def clear(self) -> None:
        for side in (BID, ASK):
            self.levels[side].clear()
            self._prices[side].clear()

    def load(self, bids: Iterable[tuple[str, str]], asks: Iterable[tuple[str, str]]) -> None:
        self.clear()
        for p, q in bids:
            self.set(BID, p, q)
        for p, q in asks:
            self.set(ASK, p, q)

    def set(self, side: str, price, qty) -> None:
        """Absolute quantity for one level; 0 removes it. Removing an unknown level is normal and ignored."""
        if side not in self.levels:
            raise ValueError(f"side {side!r}")
        p, q = to_units(price), to_units(qty)
        lv, prices = self.levels[side], self._prices[side]
        if q == 0:
            if lv.pop(p, None) is not None:
                del prices[bisect_left(prices, p)]
            return
        if p not in lv:
            insort(prices, p)
        lv[p] = q

    def best_bid(self) -> int | None:
        return self._prices[BID][-1] if self._prices[BID] else None

    def best_ask(self) -> int | None:
        return self._prices[ASK][0] if self._prices[ASK] else None

    def crossed(self) -> bool:
        b, a = self.best_bid(), self.best_ask()
        return b is not None and a is not None and b >= a

    def mid2(self) -> int | None:
        """Twice the mid price (integer, no rounding)."""
        b, a = self.best_bid(), self.best_ask()
        return None if b is None or a is None else b + a

    def band_qty(self, bp: int) -> tuple[int, int] | None:
        """(bid qty in [mid − bp, mid), ask qty in (mid, mid + bp]); None without a two-sided book."""
        m2 = self.mid2()
        if m2 is None or self.crossed():
            return None
        # mid ± mid*bp/10000, compared in doubled units to stay integer: 2p >= m2 - m2*bp/10000
        lo2 = m2 * (10_000 - bp)  # = 2*low*10000
        hi2 = m2 * (10_000 + bp)
        bids, asks = self._prices[BID], self._prices[ASK]
        lv_b, lv_a = self.levels[BID], self.levels[ASK]
        # bid prices p with 2*p*10000 >= lo2  -> p >= ceil(lo2 / 20000)
        lo = -(-lo2 // 20_000)
        hi = hi2 // 20_000
        bq = sum(lv_b[p] for p in bids[bisect_left(bids, lo):])
        aq = sum(lv_a[p] for p in asks[: bisect_right(asks, hi)])
        return bq, aq

    def top(self, side: str, n: int) -> list[tuple[int, int]]:
        prices = self._prices[side]
        chosen = reversed(prices[-n:]) if side == BID else prices[:n]
        return [(p, self.levels[side][p]) for p in chosen]

    def checksum(self, depth: int = 20) -> str:
        """SHA-256 over the best ``depth`` levels of both sides; equal books give equal sums."""
        h = hashlib.sha256()
        for side in (BID, ASK):
            for p, q in self.top(side, depth):
                h.update(f"{side}:{p}:{q};".encode())
        return h.hexdigest()

    def __len__(self) -> int:
        return len(self.levels[BID]) + len(self.levels[ASK])
