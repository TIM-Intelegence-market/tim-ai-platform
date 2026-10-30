"""Public exchange candles for chart context, separate from scientific collection.

Never write these backfilled candles to the research database or journal outcomes.
Only completed exchange intervals enter the chart analysis.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen

TIMEFRAMES = ("30m", "1h", "4h", "1d", "1w", "1M")
DEFAULT_TIMEFRAME = "30m"
# Fetched for the SHORT horizon journal (15m plans) only; not an analysis or chart tab timeframe.
JOURNAL_TIMEFRAMES = ("15m",)


def fetch_history(symbol: str, timeframe: str, now: datetime | None = None) -> list[dict]:
    if timeframe not in TIMEFRAMES and timeframe not in JOURNAL_TIMEFRAMES:
        raise ValueError("Unsupported chart timeframe")
    now = now or datetime.now(timezone.utc)
    query = urlencode({"symbol": symbol, "interval": timeframe, "limit": 500})
    with urlopen("https://api.binance.com/api/v3/klines?" + query, timeout=10) as response:
        rows = json.load(response)
    if not isinstance(rows, list):
        raise ValueError("Invalid exchange candle response")
    result = []
    for row in rows:
        opened = datetime.fromtimestamp(row[0] / 1000, timezone.utc)
        end = datetime.fromtimestamp((row[6] + 1) / 1000, timezone.utc)
        if end > now:
            continue
        result.append(dict(symbol=symbol, timeframe=timeframe, open_time=opened.isoformat(),
                           close_time=end.isoformat(), open=float(row[1]), high=float(row[2]),
                           low=float(row[3]), close=float(row[4]), volume=float(row[5]),
                           provenance="BINANCE_PUBLIC_KLINES_CHART_CONTEXT", closed=True))
    return result
