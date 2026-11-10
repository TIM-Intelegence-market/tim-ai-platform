"""All OF2 parameters in one frozen record. Values marked PROVISORISCH wait for the P0 calibration on the Mac."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from src.research_lab.protocol import CostModel

VERSION = "1.0.0"

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
    max_cost_r: float = 0.15        # cost gate in R (fee + slippage, round trip, costs below)
    max_hold_minutes: int = 1440    # 24 h, then exit at the close of that minute
    time_stop_bars: int = 8         # R70: after 8 bars of the model's time frame without 0,5 R MFE -> exit
    time_stop_mfe_r: float = 0.5
    # Footprint (P1b, models M4-M6 on 15-min candles). All PROVISORISCH: P0 measured 10-USD steps on 18 days, the S8
    # profile has 0.05-0.1 % steps; bins are merged to ``fp_step_pct`` of price and recalibrated on training only.
    fp_step_pct: float = 0.001        # merged bin width, share of price (0,1 %)
    fp_min_bins: int = 4              # a candle needs at least this many merged bins to be read
    fp_imbalance: float = 3.0         # diagonal ratio, both sides > 0; calibrated 10.11.2026 (stack share 2,8 %, none of 3-8 reached 5 %)
    fp_stack: int = 3                 # consecutive imbalance bins for a stack (R02)
    fp_absorb_levels: int = 2         # outermost bins read for absorption (R05)
    fp_absorb_ratio: float = 2.0      # attacker volume >= ratio x defender volume on each of those bins; calibrated 10.11.2026: 5,7 %
    fp_zero_levels: int = 1           # outermost bins without opposite-side prints (R13/M11); calibrated 10.11.2026: 14,7 % (2 bins: 0,3 %)
    fp_impulse_body: float = 0.6      # M5: impulse candle body >= 60 % of its range
    fp_zone_candles: int = 5          # M5: the stacked zone stays valid for 5 candles (Valtos)
    fp_min_day_candles: int = 4       # M6: the day needs this many closed 15-min candles before a "new day extreme" counts
    # M7 poor volume at the range edge (Uzi 10.11.2026: "sniper entries where the volume gets weak"). The touch candle
    # trades below ``poor_relvol_max`` x the mean of the last 15 candles and its extreme bin holds at most
    # ``poor_extreme_share`` x the mean bin volume (a poor high/low, no excess). 0,7 = the engine's thin-volume ratio,
    # 0,25 = its thin-extreme ratio (S19 tested both alone on BTC: no effect, here only at the range edge).
    poor_relvol_max: float = 0.7
    poor_extreme_share: float = 0.25
    # Costs per side, fractions of price (Uzi 10.11.2026: Bitunix). Bitunix USDT-M VIP0 taker 0,06 % (maker 0,02 %
    # is not used: the limit fills here touch the price, they do not trade through it, protocol entry 1.3). Slippage
    # as protocol 4.4. Stricter than BASE_COSTS (fee 0,05 %).
    fee: float = 0.0006
    slippage: float = 0.0003
    stop_slippage: float = 0.0005
    # Leverage report only (Uzi 10.11.: Bitunix 200x). Isolated margin liquidates at 1/leverage - MMR against the
    # entry (BTCUSDT tier 1 up to 100 000 USDT: 200x, MMR 0,3 % -> 0,2 %). Counted in the report, never a filter.
    report_leverage: int = 200
    report_mmr: float = 0.003
    # Uzi 10.11.: at most 0,5-5 % of the account as margin. In cross margin at 200x that is a position of 1-10x the
    # account; the report also counts liquidations for the upper end (10x, cross: about 10 % - MMR against the entry).
    report_cross_multiple: int = 10
    # Study window (UTC days, inclusive). Holdout 2025 is refused by the store before any byte is read.
    first_day: str = "2020-01-01"
    training_end: str = "2022-12-31"
    last_day: str = "2024-12-31"
    seed: int = 2026_11_07

    def costs(self) -> CostModel:
        return CostModel(self.fee, self.slippage, self.stop_slippage)

    @property
    def liquidation_pct(self) -> float:
        """Adverse move (share of entry) that liquidates an isolated position at ``report_leverage``."""
        return 1 / self.report_leverage - self.report_mmr

    @property
    def cross_liquidation_pct(self) -> float:
        """Adverse move that empties a cross account carrying a position of ``report_cross_multiple`` x the account."""
        return 1 / self.report_cross_multiple - self.report_mmr

    def as_dict(self) -> dict:
        return asdict(self)

    def digest(self) -> str:
        """SHA-256 over the frozen parameter set; written into every result file."""
        return hashlib.sha256(json.dumps(self.as_dict(), sort_keys=True).encode()).hexdigest()


DEFAULT_CONFIG = Config()
