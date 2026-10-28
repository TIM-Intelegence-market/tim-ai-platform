"""Estimated liquidation heatmap: pure model, Binance read, chart layer, Control Center and public view."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from src.dashboard import chart_live, liquidation_data
from src.dashboard.app import DashboardServer, DashboardState
from src.dashboard.chart_live import KlineCache, build_live_chart
from src.dashboard.public_en import english_chart_model
from src.liquidation_map import Candle, build_heatmap, nice_step
from tests.test_chart_live import NOW as CHART_NOW, fake_fetch

P = 1800
T0 = 1_800_000_000 - (1_800_000_000 % P)
AS_OF = datetime.fromtimestamp(T0 + 10 * P, tz=timezone.utc)
ONLY_10X = ((10, 1.0),)


def _flat(n: int, price: float = 100.0, start: int = T0) -> list[Candle]:
    return [Candle(time=start + i * P, high=price + 0.5, low=price - 0.5, close=price) for i in range(n)]


# --- pure model --------------------------------------------------------------------------------


@pytest.mark.parametrize("price,step", [(80_000, 100.0), (3_000, 5.0), (150, 0.2), (1.0, 0.001)])
def test_nice_step(price, step) -> None:
    assert nice_step(price) == pytest.approx(step)


def test_new_open_interest_lands_at_the_liquidation_prices_of_both_sides() -> None:
    candles = _flat(3)
    oi = {T0: 1000.0, T0 + P: 1010.0, T0 + 2 * P: 1010.0, T0 + 3 * P: 1010.0}
    heat = build_heatmap(candles, oi, AS_OF, symbol="TEST", period_seconds=P, leverage_mix=ONLY_10X)
    step = heat["step"]
    by_side = {c["side"]: c for c in heat["cells"]}
    # 10 coins at 100 $ -> 1000 $ notional, half long (liquidated at 90), half short (at 110).
    assert by_side["long"]["price"] <= 90.0 + 1e-9 < by_side["long"]["price"] + step
    assert by_side["short"]["price"] <= 110.0 < by_side["short"]["price"] + step
    assert by_side["long"]["usd"] == pytest.approx(500.0) and by_side["short"]["usd"] == pytest.approx(500.0)
    assert by_side["long"]["end"] is None and by_side["long"]["start"] == T0
    assert heat["estimate"] is True and heat["mode"] == "OBSERVE" and heat["periods_with_oi"] == 3
    assert heat["analysis"]["cluster_below"]["usd"] == pytest.approx(500.0)
    assert heat["analysis"]["cluster_above"]["usd"] == pytest.approx(500.0)


def test_a_candle_through_the_level_sweeps_it_and_keeps_it_as_history() -> None:
    candles = _flat(2) + [Candle(time=T0 + 2 * P, high=100.5, low=89.0, close=95.0)]
    oi = {T0: 1000.0, T0 + P: 1010.0, T0 + 2 * P: 1010.0}
    heat = build_heatmap(candles, oi, AS_OF, period_seconds=P, leverage_mix=ONLY_10X)
    longs = [c for c in heat["cells"] if c["side"] == "long"]
    assert len(longs) == 1 and longs[0]["end"] == T0 + 2 * P  # swept by the third candle
    assert heat["analysis"]["cluster_below"] is None and heat["analysis"]["active_usd_below"] == 0
    shorts = [c for c in heat["cells"] if c["side"] == "short"]
    assert shorts and shorts[0]["end"] is None  # 110 was never reached


def test_falling_open_interest_shrinks_all_open_estimates() -> None:
    candles = _flat(3)
    oi = {T0: 1000.0, T0 + P: 1100.0, T0 + 2 * P: 550.0}
    heat = build_heatmap(candles, oi, AS_OF, period_seconds=P, leverage_mix=ONLY_10X)
    total = sum(c["usd"] for c in heat["cells"])
    assert total == pytest.approx(100 * 100.0 * 0.5)  # 10 000 $ opened, then half the open interest closed


def test_periods_without_open_interest_are_skipped_and_bad_inputs_rejected() -> None:
    heat = build_heatmap(_flat(4), {T0: 1000.0}, AS_OF, period_seconds=P)
    assert heat["cells"] == [] and heat["periods_with_oi"] == 0 and heat["max_usd"] == 0
    with pytest.raises(ValueError):
        build_heatmap(_flat(1), {}, AS_OF)
    with pytest.raises(ValueError):
        build_heatmap(_flat(3), {}, AS_OF, leverage_mix=((10, 0.0),))


def test_small_cells_are_dropped_and_the_input_hash_is_stable() -> None:
    candles = [Candle(time=T0 + i * P, high=100.5 + i, low=99.5 + i, close=100.0 + i) for i in range(6)]
    oi = {T0 + i * P: 1000.0 + (100 if i == 1 else 0) + i * 0.01 for i in range(7)}
    heat = build_heatmap(candles, oi, AS_OF, period_seconds=P)
    floor = heat["max_usd"] * 0.02
    assert all(c["usd"] >= floor for c in heat["cells"])
    assert heat["input_hash"] == build_heatmap(candles, oi, AS_OF, period_seconds=P)["input_hash"]


# --- Binance read ------------------------------------------------------------------------------


def _fake_binance(n: int = 20, calls: list | None = None):
    def fetch(path: str, params):
        if calls is not None:
            calls.append((path, dict(params)))
        if path == "/futures/data/openInterestHist":
            assert params["period"] == "30m" and params["symbol"] in liquidation_data.SYMBOLS
            return [{"symbol": params["symbol"], "sumOpenInterest": str(80_000 + 50 * i), "sumOpenInterestValue": "0",
                     "timestamp": (T0 + i * P) * 1000} for i in range(n + 1)]
        assert path == "/fapi/v1/klines" and params["interval"] == "30m"
        return [[(T0 + i * P) * 1000, "80000", str(80_100 + i), str(79_900 + i), str(80_000 + i), "1", (T0 + (i + 1) * P) * 1000 - 1]
                for i in range(n)]
    return fetch


def test_refresh_reads_two_public_endpoints_and_stores_the_estimate() -> None:
    state, calls = DashboardState(), []
    heat = liquidation_data.refresh(state, "BTCUSDT", fetch=_fake_binance(calls=calls), now=AS_OF)
    assert [c[0] for c in calls] == ["/futures/data/openInterestHist", "/fapi/v1/klines"]
    assert state.liquidation["BTCUSDT"] is heat and heat["source"] == "BINANCE_FUTURES_OPEN_INTEREST_HIST_ESTIMATE"
    assert heat["step"] == 100.0 and heat["cells"]
    assert liquidation_data.refresh(state, "PAXGUSDT", fetch=_fake_binance()) is None


def test_parsers_skip_broken_rows_and_reject_non_lists() -> None:
    assert liquidation_data.parse_open_interest([{"timestamp": 1_000, "sumOpenInterest": "5"}, {"x": 1}]) == {1: 5.0}
    assert liquidation_data.parse_candles([[1_000, "1", "2", "0.5", "1.5"], ["bad"]]) == [Candle(1, 2.0, 0.5, 1.5)]
    with pytest.raises(ValueError):
        liquidation_data.parse_open_interest({"code": -1})
    with pytest.raises(ValueError):
        liquidation_data.fetch_heatmap("BTCUSDT", fetch=lambda path, params: [] if "open" in path.lower() else [])


# --- chart, Control Center, public view --------------------------------------------------------


def _chart_heat(as_of: datetime) -> dict:
    start = int(as_of.timestamp()) - int(as_of.timestamp()) % P - 30 * P
    candles = [Candle(time=start + i * P, high=113_100.0, low=112_900.0, close=113_000.0) for i in range(30)]
    oi = {start + i * P: 90_000.0 + 20 * i for i in range(31)}
    return build_heatmap(candles, oi, as_of, symbol="BTCUSDT", period_seconds=P)


def test_chart_carries_heat_cells_and_cluster_levels_also_in_english() -> None:
    heat = _chart_heat(CHART_NOW - timedelta(minutes=3))
    model = build_live_chart("BTCUSDT", "30m", None, cache=KlineCache(fake_fetch()), now=CHART_NOW, liquidation={"BTCUSDT": heat})
    layer = model["liquidation"]
    assert layer["cells"] and layer["step"] == heat["step"] and layer["max_usd"] == heat["max_usd"]
    liq = {d["name"]: d for d in model["drawings"] if d["group"] == "liq"}
    assert set(liq) == {"Liq-Cluster oben", "Liq-Cluster unten"}
    assert liq["Liq-Cluster oben"]["price"] > 113_000 > liq["Liq-Cluster unten"]["price"]
    assert liq["Liq-Cluster oben"]["color"] == liquidation_data.LEVEL_COLOR["above"]
    assert "liq" in model["groups"] and "liq" in model["default_groups"]
    # Other coins without an estimate carry none.
    assert build_live_chart("ETHUSDT", "30m", None, cache=KlineCache(fake_fetch()), now=CHART_NOW,
                            liquidation={"BTCUSDT": heat})["liquidation"] is None
    public = english_chart_model(model)
    assert public["groups"]["liq"] == "Liquidation heatmap (estimate)"
    names = {d["name"] for d in public["drawings"] if d["group"] == "liq"}
    assert names == {"Liq cluster above", "Liq cluster below"}
    for d in public["drawings"]:
        if d["group"] == "liq":
            assert not re.search(r"[äöüß]|oben|unten|geschätzt", f"{d['name']} {d['label']} {d['note']}"), d


def test_stale_estimate_draws_nothing_and_says_so_in_english() -> None:
    heat = _chart_heat(CHART_NOW - timedelta(hours=1))
    model = build_live_chart("BTCUSDT", "30m", None, cache=KlineCache(fake_fetch()), now=CHART_NOW, liquidation={"BTCUSDT": heat})
    assert model["liquidation"] is None and not any(d["group"] == "liq" for d in model["drawings"])
    note = next(n for n in model["notes"] if n.startswith("Liquidations-Heatmap"))
    assert english_chart_model({"notes": [note]})["notes"] == ["Liquidation heatmap: Binance data is 60 min old, hidden."]


def test_server_serves_the_estimate(monkeypatch) -> None:
    monkeypatch.setattr(chart_live, "CACHE", KlineCache(fake_fetch()))
    state = DashboardState()
    server = DashboardServer(state, port=0)
    server.start()
    port = server.server.server_address[1]
    try:
        with pytest.raises(HTTPError) as missing:
            urlopen(f"http://127.0.0.1:{port}/api/liquidation", timeout=5)
        assert missing.value.code == 404
        liquidation_data.refresh(state, "BTCUSDT", fetch=_fake_binance(), now=datetime.now(timezone.utc))
        with urlopen(f"http://127.0.0.1:{port}/api/liquidation?symbol=BTCUSDT", timeout=5) as response:
            body = json.loads(response.read())
        assert body["stale"] is False and body["estimate"] is True and body["cells"]
    finally:
        server.stop()
