"""Holdout and backward-timestamp checks of scripts/data_quality_report.py."""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from src.models.market_data import Trade

_spec = importlib.util.spec_from_file_location("dqr", Path(__file__).resolve().parents[1] / "scripts" / "data_quality_report.py")
dqr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dqr)


def _trade(i, year, second):
    return Trade("BTCUSDT", 100.0, 0.1, datetime(year, 6, 1, 10, 0, second, tzinfo=timezone.utc), str(i), None)


def test_holdout_record_is_reported_as_error():
    codes = [i["code"] for i in dqr.extra_issues([_trade(1, 2024, 0), _trade(2, 2025, 1)])]
    assert codes == ["HOLDOUT_VIOLATION"]


def test_backward_timestamp_is_reported_and_clean_input_is_silent():
    assert [i["code"] for i in dqr.extra_issues([_trade(1, 2024, 5), _trade(2, 2024, 3)])] == ["TIMESTAMP_BACKWARD"]
    assert dqr.extra_issues([_trade(1, 2024, 1), _trade(2, 2024, 3)]) == []
