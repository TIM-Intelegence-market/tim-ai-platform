"""The 48 registered variants of protocol section 6, with their data needs."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.research_lab.backtest.engine import Strategy
from src.research_lab.data.archive import INTERVAL_MS, Market
from src.research_lab.data.parse import FundingRate
from src.research_lab.hypotheses import strategies as s

WEEKDAYS = ("mo", "di", "mi", "do", "fr", "sa", "so")


@dataclass(frozen=True, slots=True)
class VariantSpec:
    variant_id: str
    hypothesis: str
    horizon: str  # long | mid | short
    market: Market
    interval: str
    params: dict[str, Any]
    build: Callable[[Sequence[FundingRate]], Strategy] = field(repr=False, compare=False)
    # Ordered numeric parameters for the neighbourhood rule; categorical ones are left out.
    grid_axes: tuple[str, ...] = ()

    @property
    def interval_ms(self) -> int:
        return INTERVAL_MS[self.interval]


def _specs() -> list[VariantSpec]:
    specs: list[VariantSpec] = []
    for n in (100, 150, 200):
        for long_short in (False, True):
            specs.append(VariantSpec(f"L1-n{n}-{'ls' if long_short else 'l'}", "L1", "long", Market.SPOT, "1d",
                                     {"n": n, "long_short": long_short},
                                     lambda f, n=n, ls=long_short: s.l1_trend(n, ls), ("n",)))
    for lookback in (30, 90, 180):
        for long_short in (False, True):
            specs.append(VariantSpec(f"L2-L{lookback}-{'ls' if long_short else 'l'}", "L2", "long", Market.SPOT, "1d",
                                     {"lookback": lookback, "long_short": long_short},
                                     lambda f, lb=lookback, ls=long_short: s.l2_momentum(lb, ls), ("lookback",)))
    for n in (20, 55):
        for k in (2, 3):
            specs.append(VariantSpec(f"M1-N{n}-k{k}", "M1", "mid", Market.USDM, "1d", {"N": n, "k": k},
                                     lambda f, n=n, k=k: s.m1_donchian(n, k), ("N", "k")))
    for q in (0.025, 0.05):
        for h in (3, 7):
            specs.append(VariantSpec(f"M2-q{q}-h{h}", "M2", "mid", Market.USDM, "1h", {"q": q, "h": h},
                                     lambda f, q=q, h=h: s.m2_funding(f, q, h), ("q", "h")))
    for day, name in enumerate(WEEKDAYS):
        for side in (1, -1):
            specs.append(VariantSpec(f"M3-{name}-{'long' if side == 1 else 'short'}", "M3", "mid", Market.USDM, "1d",
                                     {"weekday": day, "side": side}, lambda f, d=day, sd=side: s.m3_weekday(d, sd)))
    for n in (20, 50):
        for interval in ("5m", "15m"):
            specs.append(VariantSpec(f"S1-N{n}-{interval}", "S1", "short", Market.USDM, interval, {"N": n, "interval": interval},
                                     lambda f, n=n, i=interval: s.s1_cvd_divergence(n, INTERVAL_MS[i]), ("N",)))
    for session in ("london", "newyork"):
        for minutes in (30, 60):
            specs.append(VariantSpec(f"S2-{session}-r{minutes}", "S2", "short", Market.USDM, "5m",
                                     {"session": session, "r": minutes},
                                     lambda f, se=session, m=minutes: s.s2_opening_range(se, m), ("r",)))
    for interval in ("15m", "1h"):
        specs.append(VariantSpec(f"T1-bos-{interval}", "T1", "short", Market.USDM, interval, {"interval": interval},
                                 lambda f, i=interval: s.t1_bos(i)))
        specs.append(VariantSpec(f"T2-rejection-{interval}", "T2", "short", Market.USDM, interval, {"interval": interval},
                                 lambda f, i=interval: s.t2_rejection(i)))
        specs.append(VariantSpec(f"T3-failedcont-{interval}", "T3", "short", Market.USDM, interval, {"interval": interval},
                                 lambda f, i=interval: s.t3_failed_continuation(i)))
    return specs


VARIANTS: tuple[VariantSpec, ...] = tuple(_specs())
