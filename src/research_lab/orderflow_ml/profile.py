"""Volume Profile and TPO summaries (POC, value area) on integer price bins.

Rules (fixed for feature version 1.1.0):

- POC: bin with the largest count; on a tie the lowest price bin.
- Value area: start at the POC and add one neighbouring bin at a time, the one
  with the larger count (empty bins inside the range count as 0; on a tie the
  upper bin), until it holds at least 70 % of the total.
- TPO: the day is split into 48 periods of 30 minutes; a period marks every bin
  from the bin of its lowest to the bin of its highest trade once.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from src.research_lab.orderflow_ml.bars import MinuteBar

VALUE_AREA_SHARE = (7, 10)  # 70 %
TPO_PERIOD_MINUTES = 30


def value_area(hist: Mapping[int, int]) -> tuple[int, int, int] | None:
    """(poc, val, vah) bins of a histogram with positive total, else None."""
    total = sum(hist.values())
    if total <= 0:
        return None
    top = max(hist.values())
    poc = min(b for b, v in hist.items() if v == top)
    lo_edge, hi_edge = min(hist), max(hist)
    lo = hi = poc
    acc = hist[poc]
    num, den = VALUE_AREA_SHARE
    while acc * den < total * num:
        up = hist.get(hi + 1, 0) if hi < hi_edge else None
        down = hist.get(lo - 1, 0) if lo > lo_edge else None
        if up is not None and (down is None or up >= down):
            hi += 1
            acc += up
        else:
            lo -= 1
            acc += down or 0
    return poc, lo, hi


def tpo_histogram(bars: Sequence[MinuteBar], width_e8: int) -> dict[int, int]:
    """TPO counts per bin from one day of minute bars (30-minute periods)."""
    hist: dict[int, int] = {}
    for start in range(0, len(bars), TPO_PERIOD_MINUTES):
        period = [b for b in bars[start:start + TPO_PERIOD_MINUTES] if b.has_trades]
        if not period:
            continue
        low = min(b.low_price_e8 for b in period) // width_e8
        high = max(b.high_price_e8 for b in period) // width_e8
        for b in range(low, high + 1):
            hist[b] = hist.get(b, 0) + 1
    return hist


def volume_histogram(entries: Sequence[tuple[int, int, int, int]], last_minute: int = 1439) -> dict[int, int]:
    hist: dict[int, int] = {}
    for minute, b, buy, sell in entries:
        if minute > last_minute:
            break
        hist[b] = hist.get(b, 0) + buy + sell
    return hist
