"""Calibration of the move detector on synthetic hour candles (no real data, no holdout)."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import pytest

from src.research_lab.studies import move_calibration as C
from src.research_lab.studies.s17 import Candle


def _candles(first: date, days: int, spikes: set[int]) -> dict[int, Candle]:
    start = datetime(first.year, first.month, first.day, tzinfo=timezone.utc)
    out, price = {}, 30000.0
    for i in range(days * 24):
        ms = int((start + timedelta(hours=i)).timestamp() * 1000)
        step = -0.04 if i in spikes else 0.002 * math.sin(i * 1.7)
        close = price * (1 + step)
        out[ms] = Candle(ms, True, price, max(price, close), min(price, close), close, 10, 100, 100)
        price = close
    return out


def test_calibration_counts_spikes_and_picks_on_training_only():
    days = (date(2024, 12, 31) - date(2020, 1, 1)).days + 1
    spikes = {i for i in range(24 * 20, days * 24, 24 * 18)}  # about 20 per year
    rows = C.hour_rows(_candles(date(2020, 1, 1), days, spikes))
    result = C.calibrate(rows)
    assert 10 <= result["chosen"]["training"]["per_year"] <= 30
    assert result["chosen"]["validation"]["moves"] > 0
    assert set(result["chosen"]["training"]["by_year"]) <= {2020, 2021, 2022, 2023}
    assert "Validierung 2024" in C.report(result)


def test_calibration_refuses_holdout_hours():
    rows = C.hour_rows(_candles(date(2024, 12, 20), 20, set()))
    with pytest.raises(PermissionError):
        C.calibrate(rows)


def test_four_hour_blocks_need_four_hours():
    rows = C.hour_rows(_candles(date(2021, 1, 1), 1, set()))
    assert len(C.four_hour_rows(rows)) == 6
    assert len(C.four_hour_rows(rows[1:])) == 5
