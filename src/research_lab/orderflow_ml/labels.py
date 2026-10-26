"""Five-minute direction label (up / down / neutral), kept apart from features.

Start price: last trade at or before t. Target price: last trade at or before
t + horizon. A start or target trade older than ``stale_limit_ms`` makes the
label missing with its own reason; a missing label is never written as neutral.
The threshold uses only what was known at t: ``max(k * vol_60 * sqrt(h), cost_floor)``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from src.research_lab.orderflow_ml.bars import MINUTE_MS
from src.research_lab.orderflow_ml.features import BarSeries

LABEL_VERSION = "1.0.0"
UP, DOWN, NEUTRAL = "up", "down", "neutral"
OK = "ok"


@dataclass(frozen=True, slots=True)
class LabelConfig:
    horizon_min: int = 5
    stale_limit_ms: int = 60_000
    threshold_k: float = 0.5
    cost_floor: float = 0.0016  # round trip of the protocol taker model: 2 x (0.05 % fee + 0.03 % slippage)

    def __post_init__(self) -> None:
        if self.horizon_min <= 0 or self.stale_limit_ms <= 0 or self.threshold_k < 0 or self.cost_floor < 0:
            raise ValueError("invalid label configuration")


@dataclass(frozen=True, slots=True)
class LabelRow:
    decision_ms: int
    status: str
    start_price_e8: int | None = None
    target_price_e8: int | None = None
    log_return: float | None = None
    threshold: float | None = None
    label: str | None = None


def label_at(s: BarSeries, i: int, vol_60: float | None, cfg: LabelConfig) -> LabelRow:
    t = s.decision_ms(i)
    if not s.last_ms[i] or t - s.last_ms[i] > cfg.stale_limit_ms:
        return LabelRow(t, "stale_start")
    j = i + cfg.horizon_min
    if j >= len(s):
        return LabelRow(t, "beyond_data")
    horizon_end = t + cfg.horizon_min * MINUTE_MS
    if s.decision_ms(j) != horizon_end:
        raise AssertionError("series is not contiguous")
    if not s.last_ms[j] or horizon_end - s.last_ms[j] > cfg.stale_limit_ms:
        return LabelRow(t, "stale_target")
    if vol_60 is None:
        return LabelRow(t, "no_volatility")
    start, target = s.px[i], s.px[j]
    move = math.log(target / start)
    threshold = max(cfg.threshold_k * vol_60 * math.sqrt(cfg.horizon_min), cfg.cost_floor)
    label = UP if move > threshold else DOWN if move < -threshold else NEUTRAL
    return LabelRow(t, OK, start, target, move, threshold, label)
