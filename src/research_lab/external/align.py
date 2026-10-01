"""Explicit, deterministic alignment of external data with BTC candles.

Uses the research lab's BTC klines and holdout lock. A candle's decision time is
its close boundary (open_time + interval): only external data with
``available_at <= decision time`` is attached, so nothing is forward-filled over a
release that came later.

Event alignment only fixes the reference price before the release and the candle
windows after it (5m to 7d). It computes no returns, responses or signals.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.research_lab.data.archive import INTERVAL_MS
from src.research_lab.data.parse import Kline, check_completeness
from src.research_lab.data.store import HoldoutLocked, HoldoutPermission
from src.research_lab.external.events import EventStatus, ReleaseEvent
from src.research_lab.external.pit import PointInTimeStore
from src.research_lab.external.records import iso, ms_to_utc, require_utc, utc_to_ms
from src.research_lab.protocol import HOLDOUT_START_MS, split_of

HORIZONS: dict[str, timedelta] = {
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


class WindowStatus:
    COMPLETE = "COMPLETE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # candles missing inside the window
    RESOLUTION_TOO_COARSE = "RESOLUTION_TOO_COARSE"  # horizon shorter than one full candle after the release
    NOT_AVAILABLE_AT_REPLAY_TIME = "NOT_AVAILABLE_AT_REPLAY_TIME"  # window ends after replay time
    HOLDOUT_LOCKED = "HOLDOUT_LOCKED"  # window reaches the protocol holdout without permission
    EVENT_TIME_UNKNOWN = "EVENT_TIME_UNKNOWN"


@dataclass(frozen=True, slots=True)
class BtcSeries:
    """Validated BTC candles of one interval, cut at replay time."""

    interval: str
    interval_ms: int
    klines: tuple[Kline, ...]
    by_open: dict[int, Kline]
    cutoff_ms: int  # replay time the series was cut at
    # Candles left out under invalid_candles="exclude": [{"open_time_ms", "reason"}]; they count as missing.
    excluded: tuple[dict[str, Any], ...] = ()
    # [first, end) grid range of the closed candles before exclusion, so excluded edge candles stay missing.
    coverage_ms: tuple[int, int] | None = None

    @classmethod
    def build(
        cls,
        klines: Sequence[Kline],
        interval: str,
        *,
        replay_at: datetime,
        permission: HoldoutPermission | None = None,
        invalid_candles: str = "raise",
    ) -> "BtcSeries":
        """Validate the candles closed at replay time.

        ``invalid_candles="raise"`` (default) aborts on the first defective candle. ``"exclude"``
        leaves defective candles out one by one and lists them in ``excluded`` (the real Binance
        spot archive has candles cut short by outages and candles off the hourly grid); they then
        count as missing, so every window touching them is INSUFFICIENT_DATA. Duplicates, disorder
        and holdout candles abort under both policies."""
        if interval not in INTERVAL_MS:
            raise ValueError(f"unsupported interval: {interval}")
        if invalid_candles not in CANDLE_POLICIES:
            raise ValueError(f"unknown invalid_candles policy: {invalid_candles!r}")
        step = INTERVAL_MS[interval]
        cutoff = utc_to_ms(require_utc(replay_at, "replay_at"))
        # Only candles closed at replay time exist for this replay; later ones are neither used nor
        # validated, so a defect in a future candle cannot change an earlier replay.
        closed = [kline for kline in klines if kline.open_time + step <= cutoff]
        for previous, current in zip(closed, closed[1:]):
            if current.open_time <= previous.open_time:
                raise ValueError("BTC klines must be strictly increasing by open_time (duplicates or disorder)")
        if permission is None and any(kline.open_time + step > HOLDOUT_START_MS for kline in closed):
            raise HoldoutLocked("BTC klines reach into the protocol holdout; alignment needs the holdout permission")
        kept, excluded = [], []
        for kline in closed:
            reason = _defect(kline, step)
            if reason is None:
                kept.append(kline)
            elif invalid_candles == "exclude":
                excluded.append({"open_time_ms": kline.open_time, "reason": reason})
            else:
                raise ValueError(f"kline {kline.open_time} is defective ({reason}) for the {interval} grid")
        on_grid = [kline.open_time for kline in closed if kline.open_time % step == 0]
        coverage = (on_grid[0], on_grid[-1] + step) if on_grid else None
        return cls(interval, step, tuple(kept), {kline.open_time: kline for kline in kept}, cutoff, tuple(excluded), coverage)

    def gaps(self) -> dict[str, Any]:
        coverage = self.coverage_ms
        if coverage is None and self.klines:
            coverage = (self.klines[0].open_time, self.klines[-1].open_time + self.interval_ms)
        if coverage is None:
            return {"expected": 0, "present": 0, "missing": 0}
        report = check_completeness(list(self.klines), self.interval_ms, *coverage)
        return {"expected": report.expected, "present": report.present, "missing": report.missing}


CANDLE_POLICIES = ("raise", "exclude")


def _defect(kline: Kline, step: int) -> str | None:
    if kline.open_time % step:
        return "OFF_GRID"
    if kline.close_time != kline.open_time + step - 1:
        return "WRONG_SPAN"
    prices = (kline.open, kline.high, kline.low, kline.close)
    if not all(math.isfinite(value) and value > 0 for value in prices):
        return "INVALID_PRICE"
    if not (math.isfinite(kline.volume) and kline.volume >= 0 and math.isfinite(kline.taker_buy_volume) and kline.taker_buy_volume >= 0):
        return "INVALID_VOLUME"
    if kline.low > min(kline.open, kline.close) or kline.high < max(kline.open, kline.close):
        return "INVALID_OHLC"
    return None


def align_series(store: PointInTimeStore, btc: BtcSeries) -> list[dict[str, Any]]:
    """One row per closed candle: the external value as known at the candle's close."""
    rows = []
    for kline in btc.klines:
        decision = ms_to_utc(kline.open_time + btc.interval_ms)
        known = store.latest(decision)
        if known.available_at is not None and known.available_at > decision:
            raise AssertionError("lookahead: aligned value became available after the decision time")
        rows.append(
            {
                "open_time": iso(ms_to_utc(kline.open_time)),
                "decision_time": iso(decision),
                "split": split_of(kline.open_time).value,
                "btc_close": repr(kline.close),
                "btc_volume": repr(kline.volume),
                "external": known.to_dict(),
            }
        )
    return rows


def align_event(
    event: ReleaseEvent,
    btc: BtcSeries,
    *,
    replay_at: datetime,
    horizons: Sequence[str] = tuple(HORIZONS),
    permission: HoldoutPermission | None = None,
) -> dict[str, Any]:
    """Reference candle before the release and candle windows after it."""
    replay_ms = utc_to_ms(require_utc(replay_at, "replay_at"))
    if replay_ms > btc.cutoff_ms:
        raise ValueError("BTC series was cut before replay_at; build it with the same replay time")
    base: dict[str, Any] = {"event_id": event.event_id, "interval": btc.interval}
    if utc_to_ms(event.available_at) > replay_ms:
        return {**base, "status": WindowStatus.NOT_AVAILABLE_AT_REPLAY_TIME, "anchor": None, "windows": {}}
    if event.status is EventStatus.RELEASE_TIME_UNKNOWN or event.event_time is None:
        return {**base, "status": WindowStatus.EVENT_TIME_UNKNOWN, "anchor": None, "windows": {}}
    step = btc.interval_ms
    release = utc_to_ms(event.event_time)
    base["split"] = split_of(release).value
    if permission is None and release >= HOLDOUT_START_MS:
        # Nothing about a holdout release, not even the price before it, without the protocol permission.
        return {**base, "status": WindowStatus.HOLDOUT_LOCKED, "anchor": None, "windows": {}}
    straddle_open = release - release % step
    straddles = release % step != 0
    anchor_open = straddle_open - step  # last candle that closed at or before the release
    anchor = btc.by_open.get(anchor_open)
    base["anchor"] = {
        "open_time": iso(ms_to_utc(anchor_open)),
        "close_boundary": iso(ms_to_utc(anchor_open + step)),
        "btc_close_before": repr(anchor.close) if anchor else None,
        "status": WindowStatus.COMPLETE if anchor else WindowStatus.INSUFFICIENT_DATA,
    }
    base["release_inside_candle"] = iso(ms_to_utc(straddle_open)) if straddles else None
    first_open = straddle_open + step if straddles else release
    windows = {}
    for name in horizons:
        end = release + HORIZONS[name] // timedelta(milliseconds=1)
        last_boundary = end - end % step
        expected = (last_boundary - first_open) // step
        window: dict[str, Any] = {
            "start": iso(ms_to_utc(first_open)),
            "end": iso(ms_to_utc(last_boundary)) if expected > 0 else None,
            "expected_candles": max(expected, 0),
        }
        if expected <= 0:
            window["status"] = WindowStatus.RESOLUTION_TOO_COARSE
        elif last_boundary > replay_ms:
            window["status"] = WindowStatus.NOT_AVAILABLE_AT_REPLAY_TIME
        elif last_boundary > HOLDOUT_START_MS and permission is None:
            window["status"] = WindowStatus.HOLDOUT_LOCKED
        else:
            present = sum(1 for open_time in range(first_open, last_boundary, step) if open_time in btc.by_open)
            window["present_candles"] = present
            window["status"] = WindowStatus.COMPLETE if present == expected else WindowStatus.INSUFFICIENT_DATA
        windows[name] = window
    return {**base, "status": "ALIGNED", "windows": windows}


__all__ = ["HORIZONS", "BtcSeries", "WindowStatus", "align_event", "align_series"]
