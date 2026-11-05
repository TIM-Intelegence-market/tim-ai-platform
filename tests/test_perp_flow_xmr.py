"""Perp flow for a second symbol: Monero (XMRUSDT) next to BTC, one shared call budget."""

from __future__ import annotations

import asyncio
import json
import pytest

from src.dashboard import perp_flow
from src.dashboard.app import DashboardState
from src.dashboard.perp_flow import BATCH, SPECS, PerpFlow, RateLimited, chart_inputs, publish, symbol_directory
from tests.test_perp_flow import NOW, NOW_MS, YESTERDAY_MS, FakeBinance, collect, make_trades


def xmr_trades(**kwargs):
    """The BTC fixture moved to an XMR price (~600 $) with small sizes."""
    rows = make_trades(**kwargs)
    for row in rows:
        row["p"] = str(round(float(row["p"]) / 130.0, 2))
        row["q"] = str(float(row["q"]) * 20)
    return rows


class TwoSymbols:
    """Answers per ``symbol`` parameter, like Binance; counts every call."""

    def __init__(self, by_symbol, limited=None):
        self.fakes = {symbol: FakeBinance(trades) for symbol, trades in by_symbol.items()}
        self.calls: list[tuple[str, str]] = []
        self.limited = limited

    def __call__(self, path, params):
        self.calls.append((params.get("symbol"), path))
        if self.limited and self.limited(params.get("symbol"), len(self.calls)):
            raise RateLimited("binance http 429")
        return self.fakes[params["symbol"]](path, params)


def test_specs_and_folders_per_symbol(tmp_path) -> None:
    assert perp_flow.SYMBOLS == ("BTCUSDT", "XMRUSDT")
    assert SPECS["BTCUSDT"].tick == perp_flow.TICK and SPECS["BTCUSDT"].bubble_min_usd == perp_flow.BUBBLE_MIN_USD
    assert SPECS["XMRUSDT"].tick == 0.1 and SPECS["XMRUSDT"].bubble_min_usd == 10_000.0
    assert symbol_directory("BTCUSDT", tmp_path) == tmp_path  # BTC keeps its existing files
    assert symbol_directory("XMRUSDT", tmp_path) == tmp_path / "XMRUSDT"
    with pytest.raises(ValueError):
        PerpFlow(tmp_path, symbol="DOGEUSDT")


def test_xmr_rows_use_its_own_tick_floor_and_source(tmp_path) -> None:
    fake = FakeBinance(xmr_trades())
    flow = PerpFlow(tmp_path / "XMRUSDT", fetch=fake, clock=lambda: NOW.timestamp(), symbol="XMRUSDT")
    collect(flow)
    store = flow.store()
    assert store["symbol"] == "XMRUSDT" and store["tick"] == 0.1 and store["bubble_min_usd"] == 10_000.0
    assert store["source"] == "Binance USD-M Perp aggTrades (XMRUSDT, öffentlich, TIM-Sammler)"
    levels = {row[1] for rows in store["days"].values() for row in rows}
    assert levels and all(abs(level * 10 - round(level * 10)) < 1e-6 for level in levels)  # 0.1 $ grid
    assert all(500 < level < 700 for level in levels)
    # Big orders: two trades of 20 XMR at ~620 $ = ~24,800 $, above the XMR floor, far below BTC's.
    assert any(store["bubbles"].values())
    assert all(params["symbol"] == "XMRUSDT" for _, params in fake.calls)
    flow.check()
    assert flow.checks and all(c["ok"] for c in flow.checks)
    flow.save()
    saved = json.loads((tmp_path / "XMRUSDT" / "state.json").read_text())
    assert saved["symbol"] == "XMRUSDT" and saved["tick"] == 0.1


def test_btc_state_is_not_taken_by_xmr_and_old_btc_files_still_load(tmp_path) -> None:
    btc = PerpFlow(tmp_path, fetch=FakeBinance(make_trades()), clock=lambda: NOW.timestamp())
    collect(btc)
    btc.save()
    again = PerpFlow(tmp_path, fetch=FakeBinance(make_trades()), clock=lambda: NOW.timestamp())
    again.load()
    assert again.next_id == btc.next_id and again.days  # BTC resumes from its saved id
    xmr = PerpFlow(tmp_path, fetch=FakeBinance(xmr_trades()), clock=lambda: NOW.timestamp(), symbol="XMRUSDT")
    xmr.load()
    assert xmr.next_id is None  # another symbol's state.json is never resumed


def test_publish_and_chart_inputs_keep_btc_on_the_old_fields() -> None:
    state = DashboardState()
    with state.lock:
        publish(state, "BTCUSDT", store={"symbol": "BTCUSDT"}, oi={"symbol": "BTCUSDT"})
        publish(state, "XMRUSDT", store={"symbol": "XMRUSDT"}, oi={"symbol": "XMRUSDT"})
        assert state.perp_flow == {"symbol": "BTCUSDT"} and state.open_interest == {"symbol": "BTCUSDT"}
        assert set(state.perp_flows) == set(state.open_interests) == {"BTCUSDT", "XMRUSDT"}
        assert chart_inputs(state, "XMRUSDT") == ({"symbol": "XMRUSDT"}, {"symbol": "XMRUSDT"})
        assert chart_inputs(state, "BTCUSDT")[0] == {"symbol": "BTCUSDT"}
        assert chart_inputs(state, None)[0] == {"symbol": "BTCUSDT"}  # default chart symbol
        assert chart_inputs(state, "ETHUSDT")[0] == {"symbol": "BTCUSDT"}  # the chart drops a foreign symbol itself


def _run(state, flows, fetch, until, rounds=800):
    async def go() -> None:
        stop = asyncio.Event()
        original = perp_flow.IDLE_SECONDS, perp_flow.CALLS_PER_MINUTE
        perp_flow.IDLE_SECONDS, perp_flow.CALLS_PER_MINUTE = 0.01, 60_000
        try:
            task = asyncio.create_task(perp_flow.run(state, stop, flows=flows, oi_fetch=fetch))
            for _ in range(rounds):
                await asyncio.sleep(0.01)
                if until():
                    break
            stop.set()
            await asyncio.wait_for(task, 5)
        finally:
            perp_flow.IDLE_SECONDS, perp_flow.CALLS_PER_MINUTE = original

    asyncio.run(go())


def oi_rows(path, params):
    return [{"timestamp": NOW_MS - i * 3_600_000, "sumOpenInterest": "1000", "sumOpenInterestValue": "6e5"} for i in range(20)]


def test_runtime_loop_collects_both_symbols_in_one_budget(tmp_path) -> None:
    start = YESTERDAY_MS - 86_400_000
    fake = TwoSymbols({"BTCUSDT": make_trades(start_ms=start), "XMRUSDT": xmr_trades(start_ms=start)})
    clock = lambda: NOW.timestamp()  # noqa: E731
    flows = [PerpFlow(symbol_directory(s, tmp_path), fetch=fake, clock=clock, symbol=s) for s in ("BTCUSDT", "XMRUSDT")]
    state = DashboardState()
    _run(state, flows, oi_rows, lambda: len(state.perp_flows) == 2 and len(state.open_interests) == 2)
    assert state.perp_flows["XMRUSDT"]["symbol"] == "XMRUSDT" and state.perp_flows["XMRUSDT"]["days"]
    assert state.perp_flow["symbol"] == "BTCUSDT" and state.open_interest["symbol"] == "BTCUSDT"
    assert state.open_interests["XMRUSDT"]["source"] == "Binance USD-M Open Interest (XMRUSDT, 1h, öffentlich)"
    assert (tmp_path / "state.json").exists() and (tmp_path / "XMRUSDT" / "state.json").exists()
    assert (tmp_path / "XMRUSDT" / "oi-XMRUSDT-1h.jsonl").exists() and (tmp_path / "oi-BTCUSDT-1h.jsonl").exists()
    trade_calls = [symbol for symbol, path in fake.calls if path == "/fapi/v1/aggTrades"]
    # Both symbols are catching up at the same time: they take turns, neither waits for the other to finish.
    first = trade_calls[:6]
    assert first.count("BTCUSDT") >= 2 and first.count("XMRUSDT") >= 2


def test_rate_limit_pauses_every_symbol(tmp_path) -> None:
    trades = {"BTCUSDT": make_trades(), "XMRUSDT": xmr_trades()}
    fake = TwoSymbols(trades, limited=lambda symbol, n: symbol == "XMRUSDT")
    clock = lambda: NOW.timestamp()  # noqa: E731
    flows = [PerpFlow(symbol_directory(s, tmp_path), fetch=fake, clock=clock, symbol=s) for s in ("BTCUSDT", "XMRUSDT")]
    state = DashboardState()
    _run(state, flows, oi_rows, lambda: False, rounds=50)  # 0.5 s: without the pause BTC would call hundreds of times
    xmr_at = next(i for i, (s, _) in enumerate(fake.calls) if s == "XMRUSDT")
    # After XMR hit the limit (and its open-interest call), BTC made no further aggTrades call in this run.
    later = [(s, p) for s, p in fake.calls[xmr_at + 1:] if p == "/fapi/v1/aggTrades" and s == "BTCUSDT"]
    assert later == []


def test_xmr_chart_shows_perp_footprint_and_open_interest(tmp_path) -> None:
    from src.dashboard.chart_live import KlineCache, build_live_chart
    from tests.test_chart_live import NOW as CHART_NOW
    from tests.test_chart_live import fake_fetch

    end_ms = int(CHART_NOW.timestamp() * 1000)
    trades = xmr_trades(start_ms=end_ms - 2 * 86_400_000, end_ms=end_ms)
    flow = PerpFlow(tmp_path, fetch=FakeBinance(trades), clock=lambda: CHART_NOW.timestamp(), symbol="XMRUSDT")
    collect(flow)
    rows = [{"timestamp": end_ms - i * 3_600_000, "sumOpenInterest": "1000", "sumOpenInterestValue": "6e5"} for i in range(20)]
    oi = perp_flow.open_interest(lambda path, params: rows, symbol="XMRUSDT", now=CHART_NOW)
    model = build_live_chart("XMRUSDT", "30m", cache=KlineCache(fake_fetch()), now=CHART_NOW,
                             perp=flow.store(), open_interest=oi)
    assert model["markets"]["available"] == ["perp"] and model["markets"]["active"] == "perp"
    assert model["footprint"]["bars"] and model["volume_profile"] and model["cvd"]["perp"]
    assert model["trade_source"].startswith("Binance USD-M Perp aggTrades (XMRUSDT")
    assert model["oi"] is not None
    assert BATCH == 1000
