"""The three OF2 models as pure detectors over closed candles and pre-session levels.

M1 Failed Auction / 80-%-Regel (Bootcamp p. 46/51, Dalton): price traded outside yesterday's value area,
   two consecutive 30-min closes back inside, stop-entry at the second candle's high (long) / low (short),
   stop beyond the outside extreme, target the opposite value-area edge.
   Orderflow confirmation: the candle that made the outside extreme carried delta *against* the trade
   (aggressive sellers at the low who got trapped).
M2 Akzeptanz + Retest (Bootcamp p. 46/53/103, Broncx' BTC intraday model): two consecutive 30-min closes
   beyond yesterday's VAH/VAL, limit entry at the retest of that edge within 8 candles, stop under the
   lowest low of the acceptance candles, target the nearest naked POC or one value-area width.
   Orderflow confirmation: positive delta over the acceptance candles and relative volume >= relvol_min.
M3 SFP / gefangene Trader am HTF-Ort (Bootcamp p. 14/78/102): 15-min candle wicks through a marked level and
   closes back, wick >= 50 % and body <= 30 % of the range, the next candle makes no new extreme and closes
   on the inside; market entry after that candle, stop beyond the wick, target the nearest opposing level.
   Orderflow confirmation: delta of the sweep candle against the trade and relative volume >= relvol_min.

Every detector returns the *same* signal with ``confirmed`` True or False, so one run yields both the
orderflow rule and its price-only comparator (protocol N4: price rule against price rule + one filter).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from src.research_lab.of2.candles import Candle, relative_volume
from src.research_lab.of2.config import MINUTE_MS, Config
from src.research_lab.of2.levels import Levels

MARKET, STOP, LIMIT = "MARKET", "STOP", "LIMIT"


@dataclass(frozen=True, slots=True)
class Signal:
    model: str
    direction: int            # +1 long, -1 short
    signal_ms: int            # close time of the deciding candle; entry never before this minute
    kind: str                 # MARKET (open of next minute), STOP or LIMIT at ``trigger``
    trigger: float | None
    valid_until: int          # pending order expires at this minute start
    stop: float
    target: float
    level_name: str
    level: float
    confirmed: bool           # orderflow confirmation present
    session: str = ""
    regime: str = "UNBEKANNT"
    relvol: float | None = None
    cancel_beyond: float | None = None  # M2: cancel the pending limit when a 30-min close falls back beyond this level
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def reference_price(self) -> float:
        return self.trigger if self.trigger is not None else self.level

    @property
    def stop_distance(self) -> float:
        return abs(self.reference_price - self.stop)

    @property
    def reward_risk(self) -> float | None:
        dist = self.stop_distance
        return abs(self.target - self.reference_price) / dist if dist > 0 else None


def _inside(close: float, lv: Levels) -> bool:
    return lv.prev_day.val <= close <= lv.prev_day.vah


def failed_auction(c30: Sequence[Candle], lv: Levels, cfg: Config) -> Signal | None:
    """M1 on the 30-min candles of the current day (closed ones only). Needs at least three."""
    if len(c30) < 3 or not all(c.has_trades for c in c30[-3:]):
        return None
    second, first, before = c30[-1], c30[-2], c30[-3]
    if not (_inside(second.close, lv) and _inside(first.close, lv)) or _inside(before.close, lv):
        return None
    d = lv.prev_day
    direction = 1 if before.close < d.val else -1
    outside = [c for c in c30[:-2] if c.has_trades and (c.close < d.val if direction > 0 else c.close > d.vah)]
    if not outside:
        return None
    extreme = min(outside, key=lambda c: c.low) if direction > 0 else max(outside, key=lambda c: c.high)
    ext_price = extreme.low if direction > 0 else extreme.high
    stop = ext_price - ext_price * cfg.stop_buffer * direction
    trigger = second.high if direction > 0 else second.low
    target = d.vah if direction > 0 else d.val
    confirmed = (extreme.delta < 0) if direction > 0 else (extreme.delta > 0)
    return Signal("M1", direction, second.end, STOP, trigger, second.end + cfg.tf_value * MINUTE_MS, stop, target,
                  "VAL" if direction > 0 else "VAH", d.val if direction > 0 else d.vah, confirmed,
                  notes=(f"extrem_delta={extreme.delta}",))


def acceptance(c30: Sequence[Candle], lv: Levels, cfg: Config) -> Signal | None:
    """M2: fresh acceptance beyond VAH/VAL on the last ``acceptance_closes`` candles; arms a limit at the edge."""
    n = cfg.acceptance_closes
    if len(c30) < n + 1 or not all(c.has_trades for c in c30[-(n + 1):]):
        return None
    recent, before = c30[-n:], c30[-(n + 1)]
    d = lv.prev_day
    if all(c.close > d.vah for c in recent) and before.close <= d.vah:
        direction, edge = 1, d.vah
    elif all(c.close < d.val for c in recent) and before.close >= d.val:
        direction, edge = -1, d.val
    else:
        return None
    swing = min(c.low for c in recent) if direction > 0 else max(c.high for c in recent)
    stop = swing - swing * cfg.stop_buffer * direction
    ahead = [p for _, p in lv.targets(direction, edge) if (p > edge if direction > 0 else p < edge)]
    npoc_ahead = [p for name, p in lv.targets(direction, edge) if name == "NPOC"]
    target = npoc_ahead[0] if npoc_ahead else edge + direction * d.va_width
    relvol = relative_volume(c30[:-n], recent[0], cfg.relvol_bars)
    delta = sum(c.delta for c in recent)
    confirmed = (delta > 0 if direction > 0 else delta < 0) and relvol is not None and relvol >= cfg.relvol_min
    last = recent[-1]
    return Signal("M2", direction, last.end, LIMIT, edge, last.end + cfg.retest_candles * cfg.tf_value * MINUTE_MS,
                  stop, target, "VAH" if direction > 0 else "VAL", edge, confirmed, relvol=relvol, cancel_beyond=edge,
                  notes=(f"akzeptanz_delta={delta}", f"ziele_voraus={len(ahead)}"))


def sfp(c15: Sequence[Candle], lv: Levels, cfg: Config) -> Signal | None:
    """M3: the candle before the last swept a level and closed back; the last candle confirmed (no new extreme)."""
    if len(c15) < 3 or not all(c.has_trades for c in c15[-3:]):
        return None
    confirm, sweep, prior = c15[-1], c15[-2], c15[-3]
    if sweep.range <= 0:
        return None
    for direction in (1, -1):
        for name, level in lv.sweep_levels(direction):
            if direction > 0:
                pierced = sweep.low < level < sweep.close and prior.low >= level
                wick = min(sweep.open, sweep.close) - sweep.low
                held = confirm.low > sweep.low and confirm.close > level
                ext = sweep.low
            else:
                pierced = sweep.high > level > sweep.close and prior.high <= level
                wick = sweep.high - max(sweep.open, sweep.close)
                held = confirm.high < sweep.high and confirm.close < level
                ext = sweep.high
            if not (pierced and held):
                continue
            if wick < cfg.sfp_wick_min * sweep.range or sweep.body > cfg.sfp_body_max * sweep.range:
                continue
            stop = ext - ext * cfg.stop_buffer * direction
            entry_ref = confirm.close
            targets = lv.targets(direction, entry_ref)
            dist = abs(entry_ref - stop)
            viable = [(n, p) for n, p in targets if dist > 0 and abs(p - entry_ref) / dist >= cfg.min_rr]
            if not viable:
                continue
            tname, target = viable[0]
            relvol = relative_volume(c15[:-2], sweep, cfg.relvol_bars)
            confirmed = (sweep.delta < 0 if direction > 0 else sweep.delta > 0) and relvol is not None and relvol >= cfg.relvol_min
            return Signal("M3", direction, confirm.end, MARKET, None, confirm.end + MINUTE_MS, stop, target, name, level,
                          confirmed, relvol=relvol, notes=(f"sweep_delta={sweep.delta}", f"ziel={tname}"))
    return None
