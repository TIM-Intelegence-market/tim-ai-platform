"""Search space: engine parameters (one engine run each) and trade filters (applied to the run's trades).

Filters only drop trades. The OF2 tracker follows every signal on its own (trades never block each other), so a
filter on a finished run gives the same trades as an engine that never took the dropped ones.
"""
from __future__ import annotations

import dataclasses
import random
from dataclasses import dataclass

from src.research_lab.of2.config import DEFAULT_CONFIG, Config
from src.research_lab.protocol import PRE_PERP_FUNDING

# OFX base: OF2 1.0 with the new section split (training 2020-2023, validation 2024).
# ``of_gate``: only confirmed signals trade and take the day's slot (in OF2 1.0 a price-only signal blocked a later
# confirmed one of the same model and direction).
# ``funding_per_8h`` (10.11., with the swing track): 0,01 % per 8-h mark, the flat protocol rate, charged in both
# directions. Trades that run for days must pay it; the intraday trades pay it too from then on.
BASE_CONFIG = dataclasses.replace(DEFAULT_CONFIG, training_end="2023-12-31", last_day="2024-12-31", of_gate=True,
                                  funding_per_8h=PRE_PERP_FUNDING)

# Values per parameter, ordered; the OF2 1.0 value is always one of them (neighbours = one step left/right).
# Time frames (Uzi 10.11.): the engine builds its candles anew every UTC day, so a time frame must divide the day
# and leave enough candles inside one day; 4h and longer need candles that reach across days (not built yet).
ENGINE_SPACE: dict[str, tuple] = {
    "tf_value": (5, 15, 30, 60),
    "tf_sfp": (1, 5, 15, 30, 60),
    # Swing track: off, 4h or 1d candles across days; marks of the last week or month; hard holding limit in days.
    "swing_tf": (0, 240, 1440),
    "swing_level": ("W", "M"),
    "swing_hold_days": (3, 7, 14),
    "relvol_min": (1.5, 2.0, 2.5, 3.0),
    "stop_buffer": (0.0005, 0.001, 0.002, 0.003),
    "min_rr": (1.0, 1.5, 2.0, 3.0),
    "max_cost_r": (0.10, 0.15, 0.20, 0.25, 0.35),
    "time_stop_bars": (4, 8, 16, 32),
    "time_stop_mfe_r": (0.25, 0.5, 1.0),
    "max_hold_minutes": (240, 720, 1440),
    "fp_imbalance": (2.5, 3.0, 4.0),
    "fp_absorb_ratio": (1.5, 2.0, 3.0),
    "fp_zero_levels": (1, 2),
    "acceptance_closes": (1, 2, 3),
    "retest_candles": (4, 8, 12),
    "sfp_wick_min": (0.4, 0.5, 0.6),
    "ib_minutes": (30, 60),
}

MODELS = ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "S1", "S2", "S3")   # S = swing track
SESSIONS = ("ASIA", "LONDON", "NY", "SPAET")
REGIMES = ("TREND", "RANGE", "NEUTRAL", "UNBEKANNT")


def engine_config(values: dict) -> Config:
    unknown = set(values) - set(ENGINE_SPACE)
    if unknown:
        raise KeyError(f"not in the search space: {sorted(unknown)}")
    return dataclasses.replace(BASE_CONFIG, **values)


def base_values() -> dict:
    return {name: getattr(BASE_CONFIG, name) for name in ENGINE_SPACE}


def sample_engine(rng: random.Random) -> dict:
    return {name: rng.choice(choices) for name, choices in ENGINE_SPACE.items()}


def neighbours(values: dict) -> list[dict]:
    """Every parameter one step left and right (where the space has one), the rest unchanged."""
    out = []
    for name, choices in ENGINE_SPACE.items():
        i = choices.index(values[name])
        for j in (i - 1, i + 1):
            if 0 <= j < len(choices):
                out.append({**values, name: choices[j]})
    return out


@dataclass(frozen=True)
class TradeFilter:
    """Which orderflow trades are taken. Only confirmed (orderflow) trades ever count (Uzi: price-only loses)."""
    models: tuple[str, ...] = MODELS
    sessions: tuple[str, ...] = SESSIONS
    regimes: tuple[str, ...] = REGIMES
    max_trades_day: int | None = None       # Uzi 10.11.: guide value, not a duty; skipping bad days is allowed
    stop_after_losses_day: int | None = None
    skip_weekend: bool = False
    # Direction of the completed day / week / month at signal time (``trend.py``): None, "MIT" or "GEGEN".
    trend_d: str | None = None
    trend_w: str | None = None
    trend_m: str | None = None

    @property
    def trends(self) -> tuple[tuple[str, str | None], ...]:
        return (("d", self.trend_d), ("w", self.trend_w), ("m", self.trend_m))

    def key(self) -> str:
        return "|".join([",".join(self.models), ",".join(self.sessions), ",".join(self.regimes),
                         str(self.max_trades_day), str(self.stop_after_losses_day), str(int(self.skip_weekend)),
                         *(str(mode) for _, mode in self.trends)])


def _subset(rng: random.Random, items: tuple[str, ...]) -> tuple[str, ...]:
    while True:
        picked = tuple(x for x in items if rng.random() < 0.7)
        if picked:
            return picked


TREND_CHOICES = (None, None, None, "MIT", "GEGEN")


def sample_filter(rng: random.Random, *, trend: bool = False) -> TradeFilter:
    """``trend``: also draw the direction filters (only where the loop has the daily closes)."""
    base = _sample_base(rng)
    if not trend:
        return base
    return dataclasses.replace(base, trend_d=rng.choice(TREND_CHOICES), trend_w=rng.choice(TREND_CHOICES),
                               trend_m=rng.choice(TREND_CHOICES))


def _sample_base(rng: random.Random) -> TradeFilter:
    return TradeFilter(models=_subset(rng, MODELS), sessions=_subset(rng, SESSIONS),
                       regimes=_subset(rng, REGIMES) if rng.random() < 0.5 else REGIMES,
                       max_trades_day=rng.choice((None, None, 1, 2)), stop_after_losses_day=rng.choice((None, None, 1, 2)),
                       skip_weekend=rng.random() < 0.25)
