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
    monkeypatch.setattr(index_data, "runtime_key", lambda: None)
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


def test_runtime_key_is_read_at_most_every_ten_minutes(monkeypatch) -> None:
    calls = []
    clock = [1000.0]
    monkeypatch.delenv("TIM_RUNTIME_ENV", raising=False)
    monkeypatch.setattr(index_data, "_KEY_STATE", {"at": None, "value": None})

    def missing():
        calls.append(1)
        raise index_data.IndexSecretError("unavailable")

    monkeypatch.setattr(index_data, "api_key", missing)
    assert index_data.runtime_key(lambda: clock[0]) is None
    clock[0] += 599
    assert index_data.runtime_key(lambda: clock[0]) is None and len(calls) == 1
    clock[0] += 2
    monkeypatch.setattr(index_data, "api_key", lambda: calls.append(1) or SecretValue(KEY))
    assert index_data.runtime_key(lambda: clock[0]).reveal() == KEY and len(calls) == 2


def test_mac_prefers_the_private_key_file_over_the_keychain(monkeypatch, tmp_path) -> None:
    import os

    path = tmp_path / "twelvedata-api-key"
    path.write_text(KEY)
    os.chmod(path, 0o600)
    monkeypatch.setattr(index_data.sys, "platform", "darwin")
    monkeypatch.setattr(index_data.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no keychain")))
    assert index_data.api_key({index_data.FILE_ENV: str(path)}).reveal() == KEY


def minute_rows(n: int = 600) -> list[dict]:
    start = datetime(2026, 11, 8, 14, 30, tzinfo=timezone.utc).timestamp()  # inside the 30m candles of answer(300)
    rows = []
    for i in range(n):
        opened = datetime.fromtimestamp(start + i * 60, timezone.utc)
        b = 600 + (i % 30) * 0.1
        rows.append({"open_time": opened.isoformat(), "open": b, "high": b + 0.3, "low": b - 0.2, "close": b + 0.3 if i % 2 else b - 0.2,
                     "volume": 1000.0})
    return rows


def test_candle_store_spreads_volume_and_splits_by_close() -> None:
    store = index_data.candle_store(minute_rows(2), "NDX", now=NOW)
    rows = [r for day in store["days"].values() for r in day]
    assert store["approximation"] and store["bucket_seconds"] == 60
    assert round(sum(r[2] + r[3] for r in rows)) == 2000  # all volume kept
    first = [r for r in rows if r[0] == rows[0][0]]
    assert sum(r[2] for r in first) > sum(r[3] for r in first)  # first candle closes at its low: sellers
    assert index_data.candle_store([{**minute_rows(1)[0], "volume": 0}], "NDX") is None


def test_ndx_chart_gets_approximate_footprint_profile_and_cvd() -> None:
    def fetch(symbol, interval, limit):
        if interval == "1m":
            return minute_rows()
        return index_data.parse(answer(300), symbol, interval, limit, now=NOW)

    model = build_live_chart("NDX", "30m", cache=KlineCache(fetch), now=NOW)
    assert model["footprint"]["bars"] and model["volume_profile"] and model["cvd"]["spot"]
    assert model["trade_source"].startswith("Näherung aus 1m-Kerzen")
    assert any(n.startswith("Nasdaq: Footprint, Volume Profile und CVD sind eine Näherung") for n in model["notes"])
    assert model["bubbles"]["items"] == []
    from src.dashboard.public_en import english_chart_model

    english = english_chart_model(model)
    assert english["trade_source"].startswith("Approximation from 1m candles")
    assert any(n.startswith("Nasdaq: footprint, volume profile and CVD are an approximation") for n in english["notes"])


def daily(closes: dict[str, float]) -> dict:
    ts = [int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp()) + 21 * 3600 for d in closes]
    return {"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [{"close": list(closes.values())}]}}]}}


def test_ratio_uses_last_common_daily_close_and_rejects_nonsense() -> None:
    ndx = daily({"2026-11-12": 25_800.0, "2026-11-13": 26_000.0})
    qqq = daily({"2026-11-12": 630.0, "2026-11-13": 634.0, "2026-11-14": 999.0})
    assert round(index_data.ratio_from(ndx, qqq), 3) == round(26_000 / 634, 3)
    assert index_data.ratio_from(ndx, daily({"2026-11-13": 26_000.0})) is None  # factor 1: broken answer


def test_index_ratio_is_cached_and_survives_failures(monkeypatch) -> None:
    monkeypatch.setattr(index_data, "_RATIO_STATE", {"at": None, "value": None, "failed": False})
    clock, calls = [0.0], []
    pages = {"%5ENDX": daily({"2026-11-13": 26_000.0}), "QQQ": daily({"2026-11-13": 634.0})}

    def fetch(url):
        calls.append(url)
        return pages["%5ENDX" if "%5ENDX" in url else "QQQ"]

    first = index_data.index_ratio(fetch, lambda: clock[0])
    assert first and len(calls) == 2
    clock[0] += 3600
    assert index_data.index_ratio(fetch, lambda: clock[0]) == first and len(calls) == 2
    clock[0] += 6 * 3600

    def broken(url):
        raise OSError("down")

    assert index_data.index_ratio(broken, lambda: clock[0]) == first  # last factor kept


def test_scaled_rows_and_chart_note(monkeypatch) -> None:
    rows = index_data.scale_to_index(index_data.parse(answer(300), "NDX", "30m", 1000, now=NOW), ratio=41.0)
    assert rows[0]["open"] == 25_000 * 41.0 and rows[0]["index_ratio"] == 41.0
    model = build_live_chart("NDX", "30m", cache=KlineCache(lambda s, i, n: [dict(r) for r in rows]), now=NOW)
    assert model["index_ratio"] == 41.0 and model["candles"][0]["open"] > 1_000_000
    assert any(n.startswith("Nasdaq-100 in Indexpunkten") and "41,00" in n for n in model["notes"])
    from src.dashboard.public_en import english_chart_model

    assert any(n.startswith("Nasdaq-100 in index points") for n in english_chart_model(model)["notes"])
