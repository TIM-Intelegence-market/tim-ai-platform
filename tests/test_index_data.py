"""Twelve Data with TIM's own API key as Nasdaq-100 source for the chart (Uzi 16.11.2026)."""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import pytest

from config.secrets import SecretValue
from src.dashboard import chart_live, index_data
from src.dashboard.chart_live import KlineCache, build_live_chart

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
KEY = "fakeTwelveDataKeyForTests0000000"


def answer(n: int = 300, step_minutes: int = 30) -> dict:
    start = datetime(2026, 11, 3, 14, 30, tzinfo=timezone.utc).timestamp()
    values = []
    for i in range(n):
        t = datetime.fromtimestamp(start + i * step_minutes * 60, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        b = 25_000 + i
        values.append({"datetime": t, "open": str(b), "high": str(b + 5), "low": str(b - 5), "close": str(b + 1), "volume": "0"})
    return {"meta": {"symbol": "NDX", "interval": "30min"}, "values": values, "status": "ok"}


def test_parse_rows_and_open_candle() -> None:
    rows = index_data.parse(answer(4), "NDX", "30m", 1000, now=datetime(2026, 11, 3, 15, 45, tzinfo=timezone.utc))
    assert [r["closed"] for r in rows] == [True, True, False, False]
    assert rows[0]["open"] == 25_000.0 and rows[0]["provenance"] == index_data.PROVENANCE


def test_parse_daily_dates_and_month_end() -> None:
    data = {"status": "ok", "values": [{"datetime": "2026-10-01", "open": "1", "high": "2", "low": "1", "close": "2"},
                                       {"datetime": "2026-11-01", "open": "2", "high": "3", "low": "2", "close": "3"}]}
    rows = index_data.parse(data, "NDX", "1M", 10, now=NOW)
    assert rows[0]["close_time"].startswith("2026-11-01") and rows[0]["closed"] and not rows[1]["closed"]


def test_error_answer_names_code_only() -> None:
    with pytest.raises(ValueError, match="Twelve Data error 401") as info:
        index_data.parse({"status": "error", "code": 401, "message": f"bad key {KEY}"}, "NDX", "1h", 10)
    assert KEY not in str(info.value)


def test_fetch_sends_key_and_never_leaks_it_in_errors() -> None:
    seen = []

    def opener(request, timeout):
        seen.append(request.full_url)
        return io.BytesIO(json.dumps(answer(5)).encode())

    rows = index_data.fetch("NDX", "30m", 5, key=lambda: SecretValue(KEY), opener=opener)
    assert len(rows) == 5 and "apikey=" + KEY in seen[0] and "symbol=QQQ" in seen[0] and "interval=30min" in seen[0]

    def broken(request, timeout):
        raise OSError(f"failed {request.full_url}")

    with pytest.raises(ConnectionError) as info:
        index_data.fetch("NDX", "1h", 5, key=lambda: SecretValue(KEY), opener=broken)
    assert KEY not in str(info.value) and info.value.__cause__ is None and info.value.__context__ is None


def test_key_shape_and_env_provider() -> None:
    assert index_data.api_key({index_data.PROVIDER_ENV: "env", index_data.KEY_ENV: KEY}).reveal() == KEY
    with pytest.raises(index_data.IndexSecretError) as info:
        index_data.api_key({index_data.PROVIDER_ENV: "env", index_data.KEY_ENV: "bad key!"})
    assert "bad key" not in str(info.value)
    assert not index_data.has_key({"TIM_RUNTIME_ENV": "test", index_data.PROVIDER_ENV: "env", index_data.KEY_ENV: KEY})


def test_symbol_only_from_allowlist() -> None:
    assert index_data.symbol({}) == "QQQ" and index_data.symbol({index_data.SYMBOL_ENV: "ndx"}) == "NDX"
    assert index_data.symbol({index_data.SYMBOL_ENV: "AAPL&apikey=x"}) == "QQQ"


def test_chart_says_twelve_data_when_rows_come_from_the_key() -> None:
    cache = KlineCache(lambda s, i, n: index_data.parse(answer(300), s, i, n, now=NOW))
    model = build_live_chart("NDX", "30m", cache=cache, now=NOW)
    assert model["index_source"] == "twelvedata" and model["candles"]
    assert any(n.startswith("Nasdaq-100 über Twelve Data") for n in model["notes"])
    assert model["level_source"] == "Twelve-Data-Kerzen (nur Anzeige)"


def test_without_key_the_index_falls_back_to_yahoo(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(index_data, "has_key", lambda env=None: False)
    monkeypatch.setattr(chart_live, "fetch_yahoo_index", lambda s, i, n: called.append(i) or [])
    assert chart_live.fetch_index_klines("NDX", "1h", 10) == [] and called == ["1h"]


def test_index_cache_keeps_answers_longer() -> None:
    assert chart_live.INDEX_CACHE.ttl("1h") >= 900 and chart_live.CACHE.ttl("1h") == 30.0


def test_keychain_accepts_both_service_names(monkeypatch) -> None:
    asked = []

    class Done:
        def __init__(self, ok: bool) -> None:
            self.returncode, self.stdout = (0, KEY.encode()) if ok else (44, b"")

    def run(cmd, **kwargs):
        asked.append(cmd[cmd.index("-s") + 1])
        return Done(cmd[cmd.index("-s") + 1] == "twelvedata")

    monkeypatch.setattr(index_data.subprocess, "run", run)
    assert index_data.api_key({index_data.PROVIDER_ENV: "keychain"}).reveal() == KEY
    assert asked == ["com.tim.twelvedata", "twelvedata"]
