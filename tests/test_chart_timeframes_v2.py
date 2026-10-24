from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import patch
import json

from src.dashboard.chart_history import TIMEFRAMES, fetch_history
from src.dashboard.chart_model import build_chart_model, clean_candles, structure_events


UTC = timezone.utc


def candle(index: int, high: float, low: float, close: float) -> dict:
    opened = datetime(2026, 10, 20, tzinfo=UTC) + timedelta(minutes=30 * index)
    return {"symbol": "BTCUSDT", "timeframe": "30m", "open_time": opened.isoformat(),
            "close_time": (opened + timedelta(minutes=30)).isoformat(), "open": 100.0,
            "high": high, "low": low, "close": close, "volume": 10.0, "closed": True}


def test_chart_offers_only_requested_timeframes():
    model = build_chart_model({"30m": [candle(i, 110, 90, 100) for i in range(10)]}, "15m", now=datetime(2026, 10, 21, tzinfo=UTC))
    assert model["timeframe"] == "30m"
    assert model["timeframes"] == list(TIMEFRAMES)


def test_mss_requires_a_close_against_established_structure():
    ranges = [(102, 98, 100), (110, 99, 105), (104, 97, 100), (106, 98, 103),
              (112, 100, 111), (108, 99, 103), (106, 95, 96), (107, 97, 100)]
    rows = clean_candles([candle(i, *values) for i, values in enumerate(ranges)])
    events = structure_events(rows, "30m", width=1)
    assert [(item["kind"], item["direction"]) for item in events] == [("BOS", "UP"), ("MSS", "DOWN")]
    rows[6]["close"] = 100
    assert not any(item["kind"] == "MSS" for item in structure_events(rows, "30m", width=1))


def test_exchange_context_omits_an_unclosed_month():
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 10, 1, tzinfo=UTC)
    def row(a, b):
        return [int(a.timestamp() * 1000), "100", "110", "90", "105", "10", int(b.timestamp() * 1000) - 1]
    with patch("src.dashboard.chart_history.urlopen", return_value=BytesIO(json.dumps([row(start, end), row(end, datetime(2026, 11, 1, tzinfo=UTC))]).encode())):
        result = fetch_history("BTCUSDT", "1M", datetime(2026, 10, 24, tzinfo=UTC))
    assert len(result) == 1
    assert result[0]["provenance"] == "BINANCE_PUBLIC_KLINES_CHART_CONTEXT"
