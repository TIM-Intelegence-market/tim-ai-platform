"""Versioned trade-only features at a decision time, strictly from the past.

Decision time t of bar i is the end of that minute (``window_start_ms + 60 s``).
``features_at(series, i)`` reads bars 0..i only; ``BarSeries`` derives every
helper array causally (carry-forward price, one-minute returns), so cutting the
series after i or changing later bars cannot change a feature at i. The tests
check both properties.

Archive bars carry exchange event times, not the local receive time of back
then: offline features are an event-time approximation (``TIME_BASIS``). A live
adapter must build bars from what had arrived by t.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from src.research_lab.orderflow_ml.bars import E8, MINUTE_MS, MinuteBar

FEATURE_VERSION = "1.0.0"
TIME_BASIS = "exchange_event_time_proxy"
HOUR_MS = 3_600_000
WARMUP_BARS = 121  # the previous closed clock hour can reach 120 minutes back

FEATURE_NAMES: tuple[str, ...] = (
    "delta_norm_1", "cvd_norm_5", "cvd_norm_15", "cvd_norm_60", "cvd_btc_5", "cvd_btc_15", "cvd_btc_60",
    "buy_count_share_5", "trades_5", "trade_rate_5_vs_60", "volume_btc_5", "volume_usdt_5", "volume_rel_5_vs_60",
    "mean_trade_btc_5", "largest_trade_btc_5", "large_trade_share_5",
    "ret_1", "ret_5", "ret_15", "ret_60", "vol_60", "range_15", "pos_in_range_60",
    "prev_hour_ret", "prev_hour_dist_high", "prev_hour_dist_low", "hour_utc", "weekday",
)
QUALITY_NAMES: tuple[str, ...] = ("stale_ms", "empty_minutes_60")

# One line per feature for the data dictionary; units are part of the text.
DEFINITIONS: dict[str, str] = {
    "delta_norm_1": "(Kauf-BTC − Verkauf-BTC) / Gesamt-BTC der Entscheidungsminute; aggressorseitig",
    "cvd_norm_5": "Summe Delta / Summe Volumen über die letzten 5 Minuten (−1..1)",
    "cvd_norm_15": "wie cvd_norm_5 über 15 Minuten",
    "cvd_norm_60": "wie cvd_norm_5 über 60 Minuten",
    "cvd_btc_5": "rollierendes CVD in BTC über 5 Minuten",
    "cvd_btc_15": "rollierendes CVD in BTC über 15 Minuten",
    "cvd_btc_60": "rollierendes CVD in BTC über 60 Minuten",
    "buy_count_share_5": "Anteil aggressiver Käufe an aggTrade-Ereignissen, 5 Minuten",
    "trades_5": "Zahl der aggTrade-Ereignisse (nicht Einzel-Fills), 5 Minuten",
    "trade_rate_5_vs_60": "trades_5 / (aggTrades der letzten 60 Minuten / 12)",
    "volume_btc_5": "Volumen in BTC, 5 Minuten",
    "volume_usdt_5": "Volumen in USDT (Σ Preis × Menge), 5 Minuten",
    "volume_rel_5_vs_60": "volume_btc_5 / (BTC-Volumen 60 Minuten / 12)",
    "mean_trade_btc_5": "mittlere aggTrade-Größe in BTC, 5 Minuten",
    "largest_trade_btc_5": "größter aggTrade in BTC, 5 Minuten",
    "large_trade_share_5": "Anteil aggTrades ≥ 1 BTC, 5 Minuten",
    "ret_1": "ln(letzter Preis bei t / letzter Preis 1 Minute vorher)",
    "ret_5": "ln-Preisänderung über 5 Minuten bis t",
    "ret_15": "ln-Preisänderung über 15 Minuten bis t",
    "ret_60": "ln-Preisänderung über 60 Minuten bis t",
    "vol_60": "Wurzel des Mittels der quadrierten 1-Minuten-ln-Renditen der letzten 60 Minuten (nicht zentriert)",
    "range_15": "ln(Hoch / Tief) der letzten 15 Minuten",
    "pos_in_range_60": "(Preis − Tief60) / (Hoch60 − Tief60); fehlt bei Hoch = Tief",
    "prev_hour_ret": "ln-Rendite der letzten bei t geschlossenen Uhrstunde (UTC)",
    "prev_hour_dist_high": "ln(Preis bei t / Hoch dieser geschlossenen Stunde)",
    "prev_hour_dist_low": "ln(Preis bei t / Tief dieser geschlossenen Stunde)",
    "hour_utc": "Stunde von t in UTC (0..23)",
    "weekday": "Wochentag von t in UTC (0 = Montag)",
}


class BarSeries:
    """A contiguous run of minute bars with causal helper arrays."""

    def __init__(self, bars: Sequence[MinuteBar]) -> None:
        if not bars:
            raise ValueError("empty series")
        for a, b in zip(bars, bars[1:]):
            if b.window_start_ms != a.window_start_ms + MINUTE_MS:
                raise ValueError("bars must be contiguous minutes")
        self.bars = list(bars)
        self.start = [b.window_start_ms for b in bars]
        self.count = [b.trade_count for b in bars]
        self.buy_count = [b.buy_count for b in bars]
        self.buy = [b.buy_sats for b in bars]
        self.sell = [b.sell_sats for b in bars]
        self.delta = [b.buy_sats - b.sell_sats for b in bars]
        self.volume = [b.buy_sats + b.sell_sats for b in bars]
        self.quote = [b.buy_quote_e8 + b.sell_quote_e8 for b in bars]
        self.largest = [b.largest_sats for b in bars]
        self.large = [b.large_count for b in bars]
        self.high = [b.high_price_e8 for b in bars]  # 0 for empty minutes
        self.low = [b.low_price_e8 if b.has_trades else math.inf for b in bars]
        self.empty = [0 if b.has_trades else 1 for b in bars]
        px: list[int] = []
        last_ms: list[int] = []
        current_px = current_ms = 0
        for b in bars:
            if b.has_trades:
                current_px, current_ms = b.last_price_e8, b.last_trade_ms
            px.append(current_px)
            last_ms.append(current_ms)
        self.px = px  # last trade price at or before the end of each minute (0 = none yet)
        self.last_ms = last_ms
        self.ret1: list[float | None] = [None] + [math.log(px[j] / px[j - 1]) if px[j] and px[j - 1] else None for j in range(1, len(px))]

    def __len__(self) -> int:
        return len(self.bars)

    def decision_ms(self, i: int) -> int:
        return self.start[i] + MINUTE_MS


def _ratio(num: float, den: float) -> float | None:
    return num / den if den else None


def _log_ratio(a: int, b: int) -> float | None:
    return math.log(a / b) if a and b else None


@dataclass(frozen=True, slots=True)
class FeatureRow:
    decision_ms: int
    values: tuple[float | int | None, ...]  # in FEATURE_NAMES order
    stale_ms: int | None
    empty_minutes_60: int
    warm: bool

    @property
    def complete(self) -> bool:
        return self.warm and all(v is not None for v in self.values)


def features_at(s: BarSeries, i: int) -> FeatureRow:
    """Features at the end of bar i, using bars 0..i only."""
    if not 0 <= i < len(s):
        raise IndexError(i)
    t = s.decision_ms(i)
    warm = i >= WARMUP_BARS - 1

    def window(arr: list, w: int) -> list:
        return arr[max(0, i - w + 1): i + 1]

    d5, d15, d60 = sum(window(s.delta, 5)), sum(window(s.delta, 15)), sum(window(s.delta, 60))
    v1, v5, v15, v60 = s.volume[i], sum(window(s.volume, 5)), sum(window(s.volume, 15)), sum(window(s.volume, 60))
    n5, n60 = sum(window(s.count, 5)), sum(window(s.count, 60))
    px = s.px[i]

    def ret(k: int) -> float | None:
        return _log_ratio(px, s.px[i - k]) if i - k >= 0 else None

    rets = window(s.ret1, 60)
    vol_60 = math.sqrt(math.fsum(r * r for r in rets) / 60) if len(rets) == 60 and all(r is not None for r in rets) else None
    hi15, lo15 = max(window(s.high, 15)), min(window(s.low, 15))
    hi60, lo60 = max(window(s.high, 60)), min(window(s.low, 60))
    range_15 = _log_ratio(hi15, lo15) if hi15 and lo15 != math.inf else None
    pos_60 = (px - lo60) / (hi60 - lo60) if px and hi60 and lo60 != math.inf and hi60 > lo60 else None

    hour_end = t - t % HOUR_MS
    j_last = i - (t - hour_end) // MINUTE_MS
    j_first = j_last - 59
    prev_ret = dist_hi = dist_lo = None
    if j_first - 1 >= 0:
        h_hi, h_lo = max(s.high[j_first: j_last + 1]), min(s.low[j_first: j_last + 1])
        prev_ret = _log_ratio(s.px[j_last], s.px[j_first - 1])
        if h_hi and h_lo != math.inf:
            dist_hi, dist_lo = _log_ratio(px, h_hi), _log_ratio(px, int(h_lo))
    stamp = datetime.fromtimestamp(t / 1000, tz=timezone.utc)
    values = (
        _ratio(s.delta[i], v1), _ratio(d5, v5), _ratio(d15, v15), _ratio(d60, v60),
        d5 / E8, d15 / E8, d60 / E8,
        _ratio(sum(window(s.buy_count, 5)), n5), n5, _ratio(n5, n60 / 12), v5 / E8, sum(window(s.quote, 5)) / E8,
        _ratio(v5, v60 / 12), _ratio(v5 / E8, n5), max(window(s.largest, 5)) / E8, _ratio(sum(window(s.large, 5)), n5),
        ret(1), ret(5), ret(15), ret(60), vol_60, range_15, pos_60,
        prev_ret, dist_hi, dist_lo, stamp.hour, stamp.weekday(),
    )
    stale = t - s.last_ms[i] if s.last_ms[i] else None
    return FeatureRow(t, values, stale, sum(window(s.empty, 60)), warm)
