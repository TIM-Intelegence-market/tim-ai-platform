"""TIM chart zones for R-ABS-2: a snapshot is only used from the moment it was written."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.research_lab.forward.chart_zones import ChartZoneRecorder, zones_at

NOW = datetime(2026, 11, 19, 12, 0, 30, tzinfo=timezone.utc)
STEP = {"30m": 30, "1h": 60, "4h": 240, "1d": 1440, "1w": 10_080, "1M": 43_200}


def candles(symbol: str, timeframe: str, now: datetime) -> list[dict]:
    minutes, out = STEP[timeframe], []
    end = datetime.fromtimestamp(now.timestamp() // (minutes * 60) * minutes * 60, tz=timezone.utc)
    for k in range(60, 0, -1):
        opened = end - timedelta(minutes=minutes * k)
        mid = 64_000 + 300 * ((k * 7) % 5) - 20 * k
        out.append({"symbol": symbol, "timeframe": timeframe, "open_time": opened.isoformat(),
                        "close_time": (opened + timedelta(minutes=minutes)).isoformat(), "open": mid - 50, "high": mid + 200,
                        "low": mid - 200, "close": mid + 50, "volume": 100.0 + k, "closed": True})
    return out


def test_snapshot_is_written_and_never_read_before_its_time(tmp_path):
    clock = [NOW.timestamp()]
    rec = ChartZoneRecorder(tmp_path, fetch=candles, clock=lambda: clock[0])
    assert rec.poll() > 0
    at = int(clock[0] * 1000)
    zones = zones_at(tmp_path, at, 30 * 60_000)
    assert zones and all(z["low"] <= z["mid"] <= z["high"] and z["weight"] >= 1 and z["labels"] for z in zones)
    assert zones_at(tmp_path, at - 1, 30 * 60_000) is None            # not known yet
    assert zones_at(tmp_path, at + 31 * 60_000, 30 * 60_000) is None  # too old
    clock[0] += 300
    rec.poll()
    assert zones_at(tmp_path, at + 299_000, 30 * 60_000) == zones     # the later snapshot is not used earlier
