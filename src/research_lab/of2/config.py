"""All OF2 parameters in one frozen record. Values marked PROVISORISCH wait for the P0 calibration on the Mac."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

VERSION = "0.1.0"

MINUTE_MS = 60_000
HOUR_MS = 60 * MINUTE_MS
DAY_MS = 24 * HOUR_MS


@dataclass(frozen=True, slots=True)
class Config:
    # Time frames (minutes). M1/M2 decide on 30-min closes (Dalton 80 % rule), M3 on 15-min candles (Bootcamp p. 78).
    tf_value: int = 30
    tf_sfp: int = 15
    # Sessions in UTC hours [start, end): attribution windows, non-overlapping on purpose (one session per signal).
    sessions: tuple[tuple[str, int, int], ...] = (("ASIA", 0, 7), ("LONDON", 7, 13), ("NY", 13, 21), ("SPAET", 21, 24))
    # Initial balance per session (minutes) and the regime bands against the mean of the last ``ib_history`` sessions.
    ib_minutes: int = 60            # PROVISORISCH: Bootcamp 90, library mostly 60
    ib_history: int = 20
    ib_trend_below: float = 0.5     # IB / mean < 0.5 -> trend day (P0 07.11.: 0,5 / 1,5, only 13 sessions, PROVISORISCH)
    ib_range_above: float = 1.5     # IB / mean > 1.5 -> range day (wide IB)
    # Levels
    npoc_days: int = 5              # naked POCs of the last 5 days
    value_area_share: float = 0.70  # same rule as the S8 profile (single-row rule, TIM standard)
    # Confirmation and filters
    relvol_bars: int = 15           # R18: candle volume / mean of the last 15 candles of the same time frame
    relvol_min: float = 2.0         # P0 07.11.: 1,4 hits ~20 % of bars, 2,0 hits 7–9 % in every time frame; M2 acceptance and M3 sweep candle
    sfp_wick_min: float = 0.5       # M3: wick through the level >= 50 % of the candle range
    sfp_body_max: float = 0.3       # M3: body <= 30 % of the candle range
    acceptance_closes: int = 2      # M2: two consecutive 30-min closes outside the value area (criterion d)
    retest_candles: int = 8         # M2: the retest must come within 8 candles (4 h) after acceptance
    # Entry, stop, target
    stop_buffer: float = 0.0005     # 0,05 % of price beyond the invalidation extreme (PROVISORISCH)
    min_rr: float = 1.5             # R72: minimum reward/risk to the first obstacle
    max_cost_r: float = 0.15        # cost gate in R (fee + slippage, round trip, protocol BASE_COSTS)
    max_hold_minutes: int = 1440    # 24 h, then exit at the close of that minute
    time_stop_bars: int = 8         # R70: after 8 bars of the model's time frame without 0,5 R MFE -> exit
    time_stop_mfe_r: float = 0.5
    # Study window (UTC days, inclusive). Holdout 2025 is refused by the store before any byte is read.
    first_day: str = "2020-01-01"
    training_end: str = "2022-12-31"
    last_day: str = "2024-12-31"
    seed: int = 2026_11_07

    def as_dict(self) -> dict:
        return asdict(self)

    def digest(self) -> str:
        """SHA-256 over the frozen parameter set; written into every result file."""
        return hashlib.sha256(json.dumps(self.as_dict(), sort_keys=True).encode()).hexdigest()


DEFAULT_CONFIG = Config()
