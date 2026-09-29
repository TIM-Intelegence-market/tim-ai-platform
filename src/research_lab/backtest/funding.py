"""Funding series used by the engine (protocol section 4.4)."""
from __future__ import annotations

from collections.abc import Sequence

from src.research_lab.data.parse import FundingRate
from src.research_lab.protocol import FUNDING_INTERVAL_MS, PRE_PERP_FUNDING, PRE_PERP_FUNDING_STRESS


def with_pre_perp_proxy(funding: Sequence[FundingRate], start_ms: int, *, stressed: bool = False) -> list[FundingRate]:
    """Prepend a flat cost (charged to longs and shorts) for every 8 h slot
    (00/08/16 UTC) from start_ms until the first real funding event."""
    rate = PRE_PERP_FUNDING_STRESS if stressed else PRE_PERP_FUNDING
    first_real = funding[0].time if funding else None
    slot = -(-start_ms // FUNDING_INTERVAL_MS) * FUNDING_INTERVAL_MS
    proxy = []
    while first_real is None or slot < first_real:
        proxy.append(FundingRate(slot, rate, proxy=True))
        slot += FUNDING_INTERVAL_MS
        if first_real is None and len(proxy) > 20_000:
            raise ValueError("no real funding given; pass the perpetual funding series")
    return proxy + list(funding)
