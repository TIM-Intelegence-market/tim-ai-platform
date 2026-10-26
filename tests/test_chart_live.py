"""Interactive TIM chart: data endpoint, drawings with origin time and labels, local scripts."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from src.dashboard import chart_live
from src.dashboard.app import DashboardServer, DashboardState
from src.dashboard.chart_live import (INTERVAL_SECONDS, KlineCache, build_live_chart, fetch_klines, place_drawings,
                                      trend_drawings)
from src.dashboard.pages.chart import APP_PATH, CHART_SCRIPTS, LIB_PATH, render_chart_page

NOW = datetime(2026, 10, 26, 21, 10, tzinfo=timezone.utc)  # Monday evening
BASE = {"BTCUSDT": 113_000.0, "ETHUSDT": 4_050.0, "SOLUSDT": 196.0}
LIB_SHA256 = "c7dda807d662a95b3d257119ed315cec669e3bdf5aaece75c480a39307f23540"


def _start(moment: datetime, interval: str) -> datetime:
    if interval == "1M":
        return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if interval == "1w":
        day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        return day - timedelta(days=day.weekday())
    seconds = INTERVAL_SECONDS[interval]
    epoch = int(moment.timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, timezone.utc)


def _next(start: datetime, interval: str) -> datetime:
    if interval == "1M":
        return start.replace(year=start.year + (start.month == 12), month=start.month % 12 + 1)
    return start + timedelta(seconds=INTERVAL_SECONDS[interval] if interval != "1w" else 7 * 86400)


def fake_fetch(calls: list | None = None):
    """Deterministic klines; the newest candle is still open, as on the exchange."""
    def fetch(symbol: str, interval: str, limit: int) -> list[dict]:
        if calls is not None:
            calls.append((symbol, interval, limit))
        assert symbol in BASE and interval in INTERVAL_SECONDS
        starts = [_start(NOW, interval)]
        while len(starts) < limit:
            previous = starts[0] - timedelta(seconds=INTERVAL_SECONDS[interval] if interval not in ("1w", "1M") else 1)
            starts.insert(0, _start(previous, interval))
        rows = []
        for start in starts:
            k = start.timestamp() / 3600
            mid = BASE[symbol] * (1 + 0.02 * math.sin(k / 9) + 0.01 * math.sin(k / 2.3))
            open_, close = mid * 0.999, mid * 1.001 if int(k) % 2 else mid * 0.998
            end = _next(start, interval)
            rows.append(dict(symbol=symbol, timeframe=interval, open_time=start.isoformat(), close_time=end.isoformat(),
                             open=open_, high=max(open_, close) * 1.002, low=min(open_, close) * 0.998, close=close,
                             volume=10 + int(k) % 7, provenance="TEST", closed=end <= NOW))
        return rows
    return fetch


def _model(symbol="ETHUSDT", tf="4h", runtime=None, calls=None) -> dict:
    return build_live_chart(symbol, tf, runtime, cache=KlineCache(fake_fetch(calls)), now=NOW)


def test_live_chart_draws_labelled_segments_from_their_origin() -> None:
    model = _model()
    assert model["symbol"] == "ETHUSDT" and model["timeframe"] == "4h" and len(model["candles"]) > 100
    assert model["candles"][-1]["closed"] is False and all(c["closed"] for c in model["candles"][:-1])
    labels = {d["label"] for d in model["drawings"]}
    for expected in ("1D VAH", "1D POC", "1D VAL", "1W POC", "1W VAH", "1M High"):
        assert expected in labels, expected
    times = [c["time"] for c in model["candles"]]
    for d in model["drawings"]:
        assert d["label"].startswith(d["tf"]) and d["label"].strip()
        assert d["t1"] in times and d["t2"] in times and d["t1"] < d["t2"], d
        if d["group"] not in ("trend", "structure"):
            assert d["t2"] == times[-1] and d["p1"] == d["p2"] == d["price"]
    # Levels are segments, not lines across the chart: the previous day starts yesterday, not at the first candle.
    day = next(d for d in model["drawings"] if d["label"] == "1D VAH")
    assert day["t1"] == int(datetime(2026, 10, 25, tzinfo=timezone.utc).timestamp()) and not day["clipped"]
    high = next(d for d in model["drawings"] if d["label"].startswith("1D High"))
    assert high["t1"] >= day["t1"] and high["bars"] < len(times)


def test_open_candle_never_feeds_levels_or_structure() -> None:
    model = _model(tf="1h")
    open_time = model["candles"][-1]["time"]
    for d in model["drawings"]:
        if d["group"] in ("structure", "trend"):
            assert d["t2"] < open_time or d["group"] == "trend" and not d.get("broken")


def test_unknown_symbol_and_timeframe_fall_back_and_fetch_rejects_them() -> None:
    calls: list = []
    model = _model(symbol="DOGEUSDT", tf="7m", calls=calls)
    assert model["symbol"] == "BTCUSDT" and model["timeframe"] == "30m"
    assert {c[0] for c in calls} == {"BTCUSDT"}
    with pytest.raises(ValueError):
        fetch_klines("DOGEUSDT", "1h", 10)
    with pytest.raises(ValueError):
        fetch_klines("BTCUSDT", "7m", 10)


def test_btc_levels_come_from_the_runtime_series() -> None:
    runtime = {tf: [r for r in fake_fetch()("BTCUSDT", tf, 500) if r["closed"]] for tf in ("30m", "1h", "4h", "1d", "1w", "1M")}
    calls: list = []
    model = _model(symbol="BTCUSDT", runtime=runtime, calls=calls)
    assert model["level_source"].startswith("TIM-Runtime")
    assert calls == [("BTCUSDT", "4h", 1000)]  # only the shown candles are fetched
    eth = _model(symbol="ETHUSDT", runtime=runtime)
    assert eth["level_source"].startswith("Binance")


def test_intraday_groups_are_left_out_on_daily_charts() -> None:
    intraday = {d["group"] for d in _model(tf="1h")["drawings"]}
    daily = {d["group"] for d in _model(tf="1d")["drawings"]}
    assert "session" in intraday
    assert not daily & set(chart_live.INTRADAY_ONLY)


def test_cache_keeps_last_good_rows_when_the_exchange_fails() -> None:
    state = {"fail": False, "count": 0}

    def fetch(symbol, interval, limit):
        state["count"] += 1
        if state["fail"]:
            raise OSError("down")
        return [{"open_time": "2026-10-26T00:00:00+00:00", "close": 1.0}]

    cache = KlineCache(fetch)
    rows, error = cache.get("ETHUSDT", "1m", 5)
    assert rows and error is None
    assert cache.get("ETHUSDT", "1m", 5)[0] == rows and state["count"] == 1  # cached
    cache.rows[("ETHUSDT", "1m", 5)] = (cache.rows[("ETHUSDT", "1m", 5)][0] - 60, rows)
    state["fail"] = True
    again, error = cache.get("ETHUSDT", "1m", 5)
    assert again == rows and "nicht erreichbar" in error and "Stand von vor" in error
    # After a failure the exchange gets a pause: no further request, no second timeout for the page.
    count = state["count"]
    assert cache.get("SOLUSDT", "1h", 5) == ([], "Börse nicht erreichbar, neuer Versuch in Kürze.") and state["count"] == count
    assert KlineCache(fetch).get("ETHUSDT", "1m", 5) == ([], "Börse nicht erreichbar (OSError).")


def test_trend_line_ends_where_a_close_breaks_it() -> None:
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    highs = [10, 11, 12, 20, 12, 11, 10, 11, 12, 18, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 25, 26, 27]
    candles = [{"open_time": start + timedelta(hours=i), "open": h - 1, "high": h, "low": h - 2, "close": h - 0.5, "closed": True}
               for i, h in enumerate(highs)]
    lines = trend_drawings(candles, "1h", width=2)
    upper = next(d for d in lines if "Hochs" in d["label"])
    assert upper["start_price"] == 20 and upper["anchor_price"] == 18 and upper["broken"] and "gebrochen" in upper["label"]
    assert upper["end"] == candles[20]["open_time"].isoformat()  # first close above the falling line
    times = [int(c["open_time"].timestamp()) for c in candles]
    placed = place_drawings(lines, times)
    line = next(d for d in placed if "Hochs" in d["label"])
    assert line["finished"] and line["p1"] == pytest.approx(20) and line["p2"] == pytest.approx(20 - 17 / 3)


def test_page_for_eth_has_the_chart_but_no_btc_plans() -> None:
    page = render_chart_page(DashboardState(), "4h", None, "ETHUSDT")
    assert "data-symbol='ETHUSDT'" in page and "data-tf='4h'" in page
    assert "aria-current='page' title='Ethereum'>ETH</a>" in page
    assert "nur für BTC" in page and "eyebrow'>Analyse-Steckbrief" not in page and "class='tc-svg'" not in page
    assert "Lightweight Charts" in page and "Apache 2.0" in page


def test_vendored_library_is_the_checked_release() -> None:
    assert hashlib.sha256(CHART_SCRIPTS[LIB_PATH]).hexdigest() == LIB_SHA256
    assert CHART_SCRIPTS[LIB_PATH].startswith(b"/*!\n * @license\n * TradingView Lightweight Charts\xe2\x84\xa2 v4.2.3")
    assert (Path("src/dashboard/assets/vendor/LICENSE-lightweight-charts")).read_text().count("Apache License") >= 1
    app = CHART_SCRIPTS[APP_PATH].decode()
    assert "attributionLogo: false" in app and "http" not in app.replace("https://www.tradingview.com", "")
    assert "[data-keep-view]" in Path("src/dashboard/assets/auto_refresh.html").read_text()


def test_server_serves_scripts_and_live_json(monkeypatch) -> None:
    monkeypatch.setattr(chart_live, "CACHE", KlineCache(fake_fetch()))
    server = DashboardServer(DashboardState(), port=0)
    server.start()
    port = server.server.server_address[1]
    try:
        for path in (LIB_PATH, APP_PATH):
            with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
                assert response.status == 200 and response.headers["Content-Type"].startswith("text/javascript")
                assert response.read() == CHART_SCRIPTS[path]
        with pytest.raises(HTTPError):
            urlopen(f"http://127.0.0.1:{port}/assets/chart/../vendor/LICENSE-lightweight-charts", timeout=5)
        with urlopen(f"http://127.0.0.1:{port}/api/chart/live?symbol=SOLUSDT&tf=15m", timeout=10) as response:
            model = json.loads(response.read())
        assert model["symbol"] == "SOLUSDT" and model["timeframe"] == "15m" and model["candles"] and model["drawings"]
        with urlopen(f"http://127.0.0.1:{port}/chart?symbol=SOLUSDT&tf=15m", timeout=5) as response:
            assert "script-src 'self' " in response.headers["Content-Security-Policy"]
            assert b"tc-live" in response.read()
    finally:
        server.stop()


def test_tpo_profiles_count_periods_per_price_with_letters() -> None:
    from src.dashboard.chart_live import tpo_profiles

    day = datetime(2026, 10, 25, tzinfo=timezone.utc)
    rows = []
    for slot in range(48):  # a day that trades 100-110 all day and 110-120 only in period C (01:00)
        high, low = (120.0, 100.0) if slot == 2 else (110.0, 100.0)
        rows.append({"symbol": "ETHUSDT", "timeframe": "30m", "open_time": (day + timedelta(minutes=30 * slot)).isoformat(),
                     "close_time": (day + timedelta(minutes=30 * (slot + 1))).isoformat(), "open": low + 1, "high": high, "low": low, "close": high - 1, "volume": 1})
    profiles = tpo_profiles({"30m": rows}, datetime(2026, 10, 26, 3, tzinfo=timezone.utc))
    assert [p["day"] for p in profiles] == ["2026-10-25"]
    profile = profiles[0]
    assert profile["periods"] == 48 and not profile["running"] and profile["max_count"] == 48
    top = [r for r in profile["rows"] if r["price"] > 110]
    assert top and all(r["letters"] == "C" for r in top)
    assert all(r["single"] for r in top[:-1]) and not top[-1]["single"]  # single prints inside the profile; the extreme row is the tail
    body = [r for r in profile["rows"] if r["price"] < 110]
    assert all(r["count"] == 48 and r["letters"].startswith("ABC") and not r["single"] for r in body)
    assert profile["val"] <= profile["poc"] <= profile["vah"] <= 110.5  # VAH = top of the highest value row


def test_live_chart_carries_tpo_only_on_intraday_views() -> None:
    intraday = _model(tf="30m")
    assert intraday["tpo"] and intraday["tpo"][-1]["running"] and "tpo" in intraday["default_groups"]
    assert all(set(p) >= {"day", "label", "start", "end", "rows", "poc", "vah", "val", "step", "max_count"} for p in intraday["tpo"])
    assert _model(tf="1d")["tpo"] == []
    app = CHART_SCRIPTS[APP_PATH].decode()
    assert "attachPrimitive(tpo)" in app and "useMediaCoordinateSpace" in app
