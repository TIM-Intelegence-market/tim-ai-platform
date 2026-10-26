"""Long-horizon outcome documentation for orderflow observations.

The live engine in ``validation.py`` documents what the price did 5, 15 and 30
minutes after an observation, from persisted aggTrades. This module adds the
higher timeframes Uzi asked for on 25.10.2026: 1 hour, 4 hours and 24 hours.

Differences to the short engine, on purpose:

- Input is the persisted 1-minute candles, not aggTrades. A 24-hour window of
  aggTrades is millions of rows; 1 440 candles are cheap and carry high/low.
- Nothing is classified. The short engine labels PRICE_INCREASED / DECREASED /
  SIDEWAYS with a 0.10 % threshold that makes no sense at 24 hours. Here only
  the measured numbers are stored (close change, best and worst excursion,
  candle coverage). Any threshold is a research decision taken later, on the
  stored data, never baked into the record.
- Each horizon is evaluated once, when its target time has passed. Gaps in the
  candle history are recorded as coverage below 100 % and make the horizon
  incomplete; they are not retried live. Offline reconciliation may do that.

The baseline is the close of the last 1-minute candle that closed at or before
``observed_at``. The candle that contains ``observed_at`` closes after it and
is therefore not used (no look-ahead).

This is documentation of outcomes, not prediction. Mode OBSERVE only.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable

from src.models.market_data import Candle

LONG_VALIDATION_VERSION = "long-1.0.0"
LONG_HORIZONS = (60, 240, 1440)
CANDLE_TIMEFRAME = "1m"


def _d(value: float | int | str | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _s(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def _pct(value: Decimal, baseline: Decimal) -> Decimal:
    return (value - baseline) / baseline * Decimal("100")


@dataclass(frozen=True, slots=True)
class LongHorizonResult:
    minutes: int
    target_at: datetime
    price: Decimal
    price_change_percent: Decimal
    max_high_percent: Decimal
    min_low_percent: Decimal
    candle_count: int
    expected_candles: int
    complete: bool
    source_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "minutes": self.minutes,
            "target_at": self.target_at.isoformat(),
            "price": _s(self.price),
            "price_change_percent": _s(self.price_change_percent),
            "max_high_percent": _s(self.max_high_percent),
            "min_low_percent": _s(self.min_low_percent),
            "candle_count": self.candle_count,
            "expected_candles": self.expected_candles,
            "coverage_percent": _s(_d(self.candle_count) / _d(self.expected_candles) * Decimal("100")),
            "complete": self.complete,
            "source_hash": self.source_hash,
        }


@dataclass(frozen=True, slots=True)
class OrderflowLongValidation:
    observation_id: str
    symbol: str
    observed_at: datetime
    baseline_price: Decimal
    baseline_close_time: datetime
    horizons: tuple[LongHorizonResult, ...]
    complete: bool
    validation_hash: str
    validated_through: datetime
    validation_version: str = LONG_VALIDATION_VERSION
    mode: str = "OBSERVE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "symbol": self.symbol,
            "observed_at": self.observed_at.isoformat(),
            "baseline_price": _s(self.baseline_price),
            "baseline_close_time": self.baseline_close_time.isoformat(),
            "horizons": [item.to_dict() for item in self.horizons],
            "complete": self.complete,
            "validation_hash": self.validation_hash,
            "validated_through": self.validated_through.isoformat(),
            "validation_version": self.validation_version,
            "mode": self.mode,
        }


class OrderflowLongValidationEngine:
    """Documents 1h / 4h / 24h outcomes from persisted 1-minute candles."""

    def __init__(self, horizons: tuple[int, ...] = LONG_HORIZONS) -> None:
        if not horizons or any(m <= 0 for m in horizons) or list(horizons) != sorted(set(horizons)):
            raise ValueError("Long horizons must be unique, positive and ascending")
        self.horizons = tuple(horizons)

    def validate(self, observation: dict[str, Any], candles: Iterable[Candle], as_of: datetime) -> OrderflowLongValidation | None:
        observed_at = datetime.fromisoformat(str(observation["observed_at"]).replace("Z", "+00:00"))
        if observed_at.tzinfo is None or as_of.tzinfo is None:
            raise ValueError("Validation timestamps must be timezone-aware")
        symbol = str(observation["symbol"])
        ordered = sorted((c for c in candles if c.close_time <= as_of), key=lambda c: c.open_time)
        if any(c.symbol != symbol for c in ordered):
            raise ValueError("Validation input cannot mix symbols")
        if any(c.timeframe != CANDLE_TIMEFRAME for c in ordered):
            raise ValueError(f"Long validation needs {CANDLE_TIMEFRAME} candles")
        if len({c.open_time for c in ordered}) != len(ordered):
            raise ValueError("Duplicate candle in validation input")
        baseline_candidates = [c for c in ordered if c.close_time <= observed_at]
        if not baseline_candidates:
            return None
        baseline = baseline_candidates[-1]
        baseline_price = _d(baseline.close)
        results: list[LongHorizonResult] = []
        for minutes in self.horizons:
            target = observed_at + timedelta(minutes=minutes)
            if target > as_of:
                continue
            window = [c for c in ordered if baseline.close_time <= c.open_time and c.close_time <= target]
            if not window:
                continue
            expected = int((target - baseline.close_time) // timedelta(minutes=1))
            last = window[-1]
            price = _d(last.close)
            high = max(_d(c.high) for c in window)
            low = min(_d(c.low) for c in window)
            canonical = [[c.symbol, c.open_time.isoformat(), str(c.open), str(c.high), str(c.low), str(c.close), str(c.volume), c.trade_count] for c in window]
            digest = hashlib.sha256(json.dumps({"observation_hash": observation["input_hash"], "minutes": minutes, "candles": canonical}, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
            complete = expected > 0 and len(window) == expected and last.close_time == target
            results.append(LongHorizonResult(minutes, target, price, _pct(price, baseline_price), _pct(high, baseline_price), _pct(low, baseline_price), len(window), max(expected, 1), complete, digest))
        if not results:
            return None
        complete = {r.minutes for r in results} == set(self.horizons) and all(r.complete for r in results)
        payload = {"observation_id": observation["observation_id"], "version": LONG_VALIDATION_VERSION, "baseline_price": _s(baseline_price), "baseline_close_time": baseline.close_time.isoformat(), "horizons": [r.to_dict() for r in results]}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return OrderflowLongValidation(str(observation["observation_id"]), symbol, observed_at, baseline_price, baseline.close_time, tuple(results), complete, digest, results[-1].target_at)
