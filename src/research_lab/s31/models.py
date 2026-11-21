"""B6 and B7 as detectors on closed 15-min candles of one day (same Signal type as OF2; ``confirmed`` = orderflow rule,
unconfirmed = price twin of the same trigger). Thresholds are fixed in the S31 preregistration 1.0.

B6 Spot-/Perp-Divergenz (Bootcamp CVD, R27): the candle makes a new high (low) of the day so far (>= 8 candles in),
   closes against its direction (red at the high / green at the low). Confirmation: over the last 4 candles the
   perp taker pressure does not confirm the move (mean log taker ratio <= 0 at a high, >= 0 at a low) and the spot
   delta runs against it (sum < 0 at a high, > 0 at a low). Entry market after the close, stop beyond the extreme,
   target the first opposing level (R72).
B7 Sweep mit Open Interest (Bootcamp M4 checklist): the candle wicks through a marked level and closes back. Confirmation
   (long, mirrored for short): open interest over the last 4 candles rose (> 0) and spot delta over them fell (< 0).
"""
from __future__ import annotations

from collections.abc import Sequence

from src.research_lab.of2.candles import Candle
from src.research_lab.of2.config import MINUTE_MS, Config
from src.research_lab.of2.levels import Levels
from src.research_lab.of2.models import MARKET, Signal, _first_target
from src.research_lab.s31.metrics import Metrics

WINDOW = 4          # candles
MIN_CANDLES = 8     # B6: candles of the day before "new high of the day" means something


def _targets(lv: Levels, direction: int, entry: float, stop: float, cfg: Config):
    return _first_target(lv, direction, entry, stop, cfg)


def b6_divergence(metrics: Metrics, hist: Sequence[Candle], lv: Levels, cfg: Config) -> Signal | None:
    if len(hist) < MIN_CANDLES or not all(c.has_trades for c in hist[-WINDOW - 1:]):
        return None
    c, before = hist[-1], hist[:-1]
    win = metrics.window(c.end, WINDOW * cfg.tf_sfp)
    if win is None:
        return None
    _, taker = win
    spot = sum(x.delta for x in hist[-WINDOW:])
    for direction in (-1, 1):
        if direction < 0:
            new_ext = c.high > max(x.high for x in before if x.has_trades) and c.close < c.open
            ext = c.high
            confirmed = taker <= 0 and spot < 0
        else:
            new_ext = c.low < min(x.low for x in before if x.has_trades) and c.close > c.open
            ext = c.low
            confirmed = taker >= 0 and spot > 0
        if not new_ext:
            continue
        stop = ext - ext * cfg.stop_buffer * direction
        target = _targets(lv, direction, c.close, stop, cfg)
        if target is None:
            continue
        return Signal("B6", direction, c.end, MARKET, None, c.end + MINUTE_MS, stop, target[1], "TAGES_EXTREM", ext,
                      confirmed, notes=(f"taker={taker:.4f}", f"spot_delta={spot}"), tf=cfg.tf_sfp)
    return None


def b7_oi_sweep(metrics: Metrics, hist: Sequence[Candle], lv: Levels, cfg: Config) -> Signal | None:
    if len(hist) < WINDOW + 1 or not all(c.has_trades for c in hist[-WINDOW:]):
        return None
    c = hist[-1]
    win = metrics.window(c.end, WINDOW * cfg.tf_sfp)
    if win is None:
        return None
    oi_change, _ = win
    spot = sum(x.delta for x in hist[-WINDOW:])
    for direction in (1, -1):
        for name, level in lv.sweep_levels(direction):
            if direction > 0:
                swept = c.low < level and c.close > level
                ext = c.low
                confirmed = oi_change > 0 and spot < 0
            else:
                swept = c.high > level and c.close < level
                ext = c.high
                confirmed = oi_change > 0 and spot > 0
            if not swept:
                continue
            stop = ext - ext * cfg.stop_buffer * direction
            target = _targets(lv, direction, c.close, stop, cfg)
            if target is None:
                continue
            return Signal("B7", direction, c.end, MARKET, None, c.end + MINUTE_MS, stop, target[1], name, level,
                          confirmed, notes=(f"oi={oi_change:.5f}", f"spot_delta={spot}", f"ziel={target[0]}"), tf=cfg.tf_sfp)
    return None
