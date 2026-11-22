"""TIM's own look at a coin a GoatHub call names (paper only).

Many calls only name a coin and a direction ("Short ake"). The call is then the trigger, not the
trade: TIM reads the coin's candles up to the moment it knew about the call and gives its own
recommendation, LONG, SHORT or NO TRADE, with a stop behind the last swing and a target at the
next level. Rules are fixed (``RULES_VERSION``) so results are not bent afterwards; changing a
number means a new version.

Only candles are used (trend, swing levels, range, turnover). There is no orderflow for altcoins,
so this is weaker than TIM's BTC analysis and stays an observation until the paper diary has
enough closed trades. No candle after the analysis time is read (no look-ahead).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Sequence

__all__ = ["RULES_VERSION", "CoinAnalysis", "analyse_coin"]

RULES_VERSION = "coin-analyse/1.0"

LOOKBACK = timedelta(hours=24)  # candles the analysis reads
SWING_WINDOW = timedelta(hours=6)  # the stop goes behind the extreme of this window
RANGE_WINDOW = timedelta(hours=4)  # average candle range over this window ("usual swing")
STOP_BUFFER_RANGES = Decimal("1")  # stop sits one usual candle range behind the swing
MIN_STOP = Decimal("0.01")  # stop closer than 1 % is noise for an altcoin
MAX_STOP = Decimal("0.15")  # stop further than 15 % is no trade
MIN_REWARD_TO_RISK = Decimal("1.5")  # the 24 h level is the target only if it pays at least 1.5 times the risk
DEFAULT_REWARD_TO_RISK = Decimal("2")  # otherwise the target is twice the risk
TREND_AGAINST = Decimal("0.03")  # no trade against a move of 3 % or more over the last 6 h ...
EXHAUSTED = Decimal("0.15")  # ... and none after the coin already ran 15 % in the call's direction in 24 h
MIN_COVERAGE = Decimal("0.8")


@dataclass(frozen=True, slots=True)
class CoinAnalysis:
    recommendation: str  # LONG | SHORT | NO_TRADE
    reason: str  # one plain German sentence
    price: Decimal
    change_6h_pct: Decimal
    change_24h_pct: Decimal
    high_24h: Decimal
    low_24h: Decimal
    usual_range_pct: Decimal
    stop: Decimal | None = None
    target: Decimal | None = None
    rules: str = RULES_VERSION

    @property
    def tradable(self) -> bool:
        return self.recommendation in ("LONG", "SHORT")

    def text(self, symbol: str) -> str:
        """Short German analysis for the diary."""
        head = (f"{symbol}: Kurs {self.price.normalize():f}, 6 h {self.change_6h_pct:+.1f} %, 24 h {self.change_24h_pct:+.1f} %, "
                f"Spanne 24 h {self.low_24h.normalize():f} bis {self.high_24h.normalize():f}, übliche Kerze {self.usual_range_pct:.1f} %.")
        if not self.tradable:
            return f"{head} Empfehlung: NICHT HANDELN, {self.reason}."
        return (f"{head} Empfehlung: {self.recommendation}, Stop {self.stop.normalize():f}, Ziel {self.target.normalize():f}. "
                f"{self.reason}.")

    def to_dict(self) -> dict[str, Any]:
        return {key: (str(value) if isinstance(value, Decimal) else value) for key in self.__slots__ for value in [getattr(self, key)]}


def _round(value: Decimal, like: Decimal) -> Decimal:
    """Round a computed level to the price's own number of decimals plus two."""
    places = max(-like.normalize().as_tuple().exponent, 0) + 2
    return value.quantize(Decimal(1).scaleb(-places))


def analyse_coin(bars: Sequence[Any], *, at: datetime, side: str, interval: timedelta) -> CoinAnalysis | None:
    """Recommendation for a coin call in direction ``side`` from the candles that closed before ``at``.

    ``bars`` need open_time, open, high, low, close. Returns None when the 24 h before ``at`` are not
    covered: without candles TIM says nothing, it never guesses.
    """
    history = [bar for bar in bars if at - LOOKBACK <= bar.open_time and bar.open_time + interval <= at]
    if Decimal(len(history)) < Decimal(LOOKBACK / interval) * MIN_COVERAGE:
        return None
    price = history[-1].close
    if price <= 0:
        return None
    long = side == "LONG"
    swing = [bar for bar in history if bar.open_time >= at - SWING_WINDOW]
    recent = [bar for bar in history if bar.open_time >= at - RANGE_WINDOW]
    high_24h, low_24h = max(bar.high for bar in history), min(bar.low for bar in history)
    usual_range = sum((bar.high - bar.low for bar in recent), Decimal(0)) / len(recent)
    change_6h = (price - swing[0].open) / swing[0].open
    change_24h = (price - history[0].open) / history[0].open
    facts = dict(price=price, change_6h_pct=change_6h * 100, change_24h_pct=change_24h * 100, high_24h=high_24h, low_24h=low_24h,
                 usual_range_pct=usual_range / price * 100)

    def no_trade(reason: str) -> CoinAnalysis:
        return CoinAnalysis("NO_TRADE", reason, **facts)

    direction = Decimal(1) if long else Decimal(-1)
    if change_6h * direction <= -TREND_AGAINST:
        return no_trade(f"der Kurs läuft seit 6 Stunden deutlich gegen den Call ({change_6h * 100:+.1f} %)")
    if change_24h * direction >= EXHAUSTED:
        return no_trade(f"der Coin ist in 24 Stunden schon {change_24h * 100:+.1f} % in Richtung des Calls gelaufen")
    extreme = min(bar.low for bar in swing) if long else max(bar.high for bar in swing)
    stop = extreme - direction * usual_range * STOP_BUFFER_RANGES
    risk = (price - stop) * direction
    if risk <= 0 or risk / price < MIN_STOP:
        return no_trade("der Stop hinter dem letzten Hoch/Tief läge zu nah am Kurs")
    if risk / price > MAX_STOP:
        return no_trade(f"der Stop hinter dem letzten Hoch/Tief wäre {risk / price * 100:.0f} % entfernt")
    level = high_24h if long else low_24h
    if (level - price) * direction >= risk * MIN_REWARD_TO_RISK:
        target, where = level, "am 24-Stunden-" + ("Hoch" if long else "Tief")
    else:
        target, where = price + direction * risk * DEFAULT_REWARD_TO_RISK, "beim Doppelten des Risikos"
    if target <= 0:
        return no_trade("das Ziel läge unter null")
    return CoinAnalysis(side, f"Stop hinter dem {'Tief' if long else 'Hoch'} der letzten 6 Stunden, Ziel {where}", stop=_round(stop, price),
                        target=_round(target, price), **facts)
