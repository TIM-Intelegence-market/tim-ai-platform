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

Footprint models (P1b, 15-min candles, footprint from the S8 day profile, see ``footprint.py``):
M4 Absorption am Level (Bootcamp p. 67, Axia/Futex reloader): a candle touches a marked level without closing
   through it and closes back in the direction of the level's defence; the next candle holds the extreme.
   Orderflow confirmation: the outermost bins at the level show the attacking side >= fp_absorb_ratio x the
   defending side (aggressive sellers into bids that held), and the candle's delta runs against the trade.
M5 Stacked-Imbalance-Retest (Valtos, Bootcamp p. 82): an impulse candle (body >= 60 % of range) leaving a marked
   level, zone = its origin third; limit entry at the zone top on the retest within fp_zone_candles candles,
   cancelled by a close beyond the zone bottom; stop beyond the zone, target the nearest opposing level.
   Orderflow confirmation: a stack of >= fp_stack imbalances in trade direction inside the zone.
M6 Stop-Run-Fade / Zeros (DeepCharts, Axia, FH 15): a candle makes a new day extreme and closes back below
   (above) the previous extreme; market entry against the run after that close, stop beyond the run.
   Orderflow confirmation: the outermost bins print only the chasing side (zeros on the other side) and the
   candle's delta is in the direction of the run (chasers trapped).

M7 Poor Volume am Range-Rand (Uzi 10.11.2026, AMT poor high/low, Bootcamp unfinished auction): a candle tests a
   range edge (yesterday's VAH/VAL or high/low, the previous session's high/low) for the first time in three candles
   and closes back inside; market entry back into the range at the next minute, stop beyond the extreme, target
   the first opposing level with R:R >= 1.5. Not on trend days.
   Orderflow confirmation: weak volume at the edge, i.e. relative volume of the touch candle < poor_relvol_max and
   its extreme bin carries <= poor_extreme_share x the mean bin volume of the candle.

Every detector returns the *same* signal with ``confirmed`` True or False, so one run yields both the
orderflow rule and its price-only comparator (protocol N4: price rule against price rule + one filter).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from src.research_lab.of2.candles import Candle, relative_volume
from src.research_lab.of2.config import MINUTE_MS, Config
from src.research_lab.of2.footprint import Footprint
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
    cancel_beyond: float | None = None  # M2/M5: cancel the pending limit when a close falls back beyond this level
    notes: tuple[str, ...] = field(default_factory=tuple)
    tf: int = 30                        # time frame of the deciding candle (minutes); the time stop counts in it

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
                  notes=(f"extrem_delta={extreme.delta}",), tf=cfg.tf_value)


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
                  notes=(f"akzeptanz_delta={delta}", f"ziele_voraus={len(ahead)}"), tf=cfg.tf_value)


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
                          confirmed, relvol=relvol, notes=(f"sweep_delta={sweep.delta}", f"ziel={tname}"), tf=cfg.tf_sfp)
    return None


# -- footprint models (P1b) ---------------------------------------------------------------------------------
def _first_target(lv: Levels, direction: int, entry_ref: float, stop: float, cfg: Config) -> tuple[str, float] | None:
    dist = abs(entry_ref - stop)
    if dist <= 0:
        return None
    for name, price in lv.targets(direction, entry_ref):
        if abs(price - entry_ref) / dist >= cfg.min_rr:
            return name, price
    return None


def absorption(c15: Sequence[Candle], fp15: Sequence[Footprint], lv: Levels, cfg: Config) -> Signal | None:
    """M4: the candle before the last touched a level and held it; the last candle kept the extreme."""
    if len(c15) < 3 or len(fp15) != len(c15) or not all(c.has_trades for c in c15[-3:]):
        return None
    confirm, touch, prior = c15[-1], c15[-2], c15[-3]
    fp = fp15[-2]
    if touch.range <= 0 or fp.empty:
        return None
    step = fp.step
    for direction in (1, -1):
        for name, level in lv.sweep_levels(direction):
            if direction > 0:
                touched = touch.low <= level + step and touch.low >= level - step and prior.low > level + step
                held = touch.close > level and touch.close >= touch.open and confirm.low >= touch.low and confirm.close > level
                ext = touch.low
            else:
                touched = touch.high >= level - step and touch.high <= level + step and prior.high < level - step
                held = touch.close < level and touch.close <= touch.open and confirm.high <= touch.high and confirm.close < level
                ext = touch.high
            if not (touched and held):
                continue
            stop = ext - ext * cfg.stop_buffer * direction
            entry_ref = confirm.close
            target = _first_target(lv, direction, entry_ref, stop, cfg)
            if target is None:
                continue
            readable = fp.n_bins >= cfg.fp_min_bins
            absorbed = readable and fp.absorption(direction, cfg.fp_absorb_levels, cfg.fp_absorb_ratio)
            against = (touch.delta < 0) if direction > 0 else (touch.delta > 0)
            confirmed = absorbed and against
            return Signal("M4", direction, confirm.end, MARKET, None, confirm.end + MINUTE_MS, stop, target[1], name, level,
                          confirmed, notes=(f"touch_delta={touch.delta}", f"bins={fp.n_bins}", f"ziel={target[0]}"), tf=cfg.tf_sfp)
    return None


def stacked_retest(c15: Sequence[Candle], fp15: Sequence[Footprint], lv: Levels, cfg: Config) -> Signal | None:
    """M5: the last closed candle is an impulse; arms a limit at the top (long) / bottom (short) of its origin third."""
    if len(c15) < 2 or len(fp15) != len(c15):
        return None
    impulse, fp = c15[-1], fp15[-1]
    if not impulse.has_trades or impulse.range <= 0 or fp.empty:
        return None
    if impulse.body < cfg.fp_impulse_body * impulse.range:
        return None
    direction = 1 if impulse.close > impulse.open else -1
    third = impulse.range / 3
    if direction > 0:
        zone_lo, zone_hi = impulse.low, impulse.low + third
        trigger, beyond = zone_hi, zone_lo
    else:
        zone_lo, zone_hi = impulse.high - third, impulse.high
        trigger, beyond = zone_lo, zone_hi
    # location first (Valtos: imbalances at the origin of a move at a level, never mid-move): the zone must hold
    # or touch a marked level on the side the impulse came from
    anchors = [p for _, p in lv.sweep_levels(direction)]
    if not any(zone_lo - third <= p <= zone_hi + third for p in anchors):
        return None
    stop = beyond - beyond * cfg.stop_buffer * direction
    target = _first_target(lv, direction, trigger, stop, cfg)
    if target is None:
        return None
    readable = fp.n_bins >= cfg.fp_min_bins
    buys, sells = fp.stacks(cfg.fp_imbalance, cfg.fp_stack) if readable else ([], [])
    runs = buys if direction > 0 else sells
    lo_bin, hi_bin = int(zone_lo // fp.step), int(zone_hi // fp.step)
    in_zone = any(a <= hi_bin and b >= lo_bin for a, b in runs)
    return Signal("M5", direction, impulse.end, LIMIT, trigger, impulse.end + cfg.fp_zone_candles * cfg.tf_sfp * MINUTE_MS,
                  stop, target[1], "IMPULS", trigger, in_zone, cancel_beyond=beyond,
                  notes=(f"impuls_delta={impulse.delta}", f"stacks={len(runs)}", f"ziel={target[0]}"), tf=cfg.tf_sfp)


def stop_run(c15: Sequence[Candle], fp15: Sequence[Footprint], lv: Levels, cfg: Config) -> Signal | None:
    """M6: the last candle ran the day's extreme so far and closed back inside; fade it at the next open."""
    n = cfg.fp_min_day_candles
    if len(c15) < n + 1 or len(fp15) != len(c15):
        return None
    run, fp = c15[-1], fp15[-1]
    earlier = [c for c in c15[:-1] if c.has_trades]
    if not run.has_trades or len(earlier) < n or fp.empty:
        return None
    day_high, day_low = max(c.high for c in earlier), min(c.low for c in earlier)
    if run.high > day_high and run.close < day_high:
        direction, ext, level, name = -1, run.high, day_high, "TAG_HOCH_LAUFEND"
    elif run.low < day_low and run.close > day_low:
        direction, ext, level, name = 1, run.low, day_low, "TAG_TIEF_LAUFEND"
    else:
        return None
    stop = ext - ext * cfg.stop_buffer * direction
    target = _first_target(lv, direction, run.close, stop, cfg)
    if target is None:
        return None
    readable = fp.n_bins >= cfg.fp_min_bins
    zeros = readable and fp.zeros_at(direction, cfg.fp_zero_levels)
    chased = (run.delta > 0) if direction < 0 else (run.delta < 0)
    return Signal("M6", direction, run.end, MARKET, None, run.end + MINUTE_MS, stop, target[1], name, level, zeros and chased,
                  notes=(f"run_delta={run.delta}", f"bins={fp.n_bins}", f"ziel={target[0]}"), tf=cfg.tf_sfp)


RANGE_EDGES = {1: ("VAL", "TAG_TIEF", "SESSION_TIEF"), -1: ("VAH", "TAG_HOCH", "SESSION_HOCH")}


def poor_edge(c15: Sequence[Candle], fp15: Sequence[Footprint], lv: Levels, cfg: Config) -> Signal | None:
    """M7: the last closed candle tested a range edge with weak volume and closed back inside; fade at the next open."""
    if len(c15) < 3 or len(fp15) != len(c15) or not all(c.has_trades for c in c15[-3:]):
        return None
    touch, fp = c15[-1], fp15[-1]
    if touch.range <= 0 or fp.empty:
        return None
    step = fp.step
    for direction in (1, -1):
        for name, level in lv.sweep_levels(direction):
            if name not in RANGE_EDGES[direction]:
                continue
            if direction > 0:
                fresh = all(c.low > level + step for c in c15[-3:-1])
                tested = touch.low <= level + step and touch.close > level
                ext = touch.low
            else:
                fresh = all(c.high < level - step for c in c15[-3:-1])
                tested = touch.high >= level - step and touch.close < level
                ext = touch.high
            if not (fresh and tested):
                continue
            stop = ext - ext * cfg.stop_buffer * direction
            target = _first_target(lv, direction, touch.close, stop, cfg)
            if target is None:
                continue
            relvol = relative_volume(c15[:-1], touch, cfg.relvol_bars)
            readable = fp.n_bins >= cfg.fp_min_bins
            poor = False
            if readable:
                volumes = [buy + sell for _, buy, sell in fp.bins]
                mean = sum(volumes) / len(volumes)
                edge = volumes[0] if direction > 0 else volumes[-1]
                poor = mean > 0 and edge <= cfg.poor_extreme_share * mean
            weak = relvol is not None and relvol < cfg.poor_relvol_max
            return Signal("M7", direction, touch.end, MARKET, None, touch.end + MINUTE_MS, stop, target[1], name, level,
                          weak and poor, relvol=relvol, notes=(f"bins={fp.n_bins}", f"poor={poor}", f"ziel={target[0]}"),
                          tf=cfg.tf_sfp)
    return None
