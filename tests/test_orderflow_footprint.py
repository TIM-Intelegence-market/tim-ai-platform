"""Footprint per price level: builders, patterns F1-F6 and their effect on the reaction read.

docs/knowledge/ORDERFLOW_REGELN.md, section 2a. The footprint confirms or refutes
what candles and a window delta only suggest: an absorption cluster at the defended
edge, a finished auction or thin extreme for exhaustion, stacked imbalances against it.
"""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.models.market_data import Candle, Trade
from src.orderflow_scenario.adapters import GenericOrderflowAdapter
from src.orderflow_scenario.adapters.openmarket import DEFAULT_CONTEXT_TYPES, OpenMarketAdapter
from src.orderflow_scenario.domain import MarketContext, OrderflowStatementKind
from src.orderflow_scenario.engines.orderflow_interpretation import OrderflowInputs, OrderflowInterpretationEngine
from src.orderflow_scenario.engines.pipeline import Pipeline, PipelineInputs
from src.orderflow_scenario.engines.scenario_generator import LevelSet, ScenarioGenerator
from src.orderflow_scenario.footprint import (
    FootprintBar,
    FootprintLevel,
    FootprintSeries,
    analyze_footprint,
    footprint_from_levels,
    footprint_from_trades,
)
from src.orderflow_scenario.report import build_report

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
ENGINE = OrderflowInterpretationEngine()
D = Decimal


def candle(index: int, open_: float, high: float, low: float, close: float, volume: float = 100.0) -> Candle:
    return Candle(
        symbol="BTCUSDT", timeframe="4H",
        open_time=NOW - timedelta(minutes=240 * (60 - index)), close_time=NOW - timedelta(minutes=240 * (59 - index)),
        open=open_, high=high, low=low, close=close, volume=volume, trade_count=1000, closed=True,
    )


def bar(levels: list[tuple[str, str, str]], *, open_: str | None = None, close: str | None = None, open_time: datetime | None = None) -> FootprintBar:
    return FootprintBar(
        levels=tuple(FootprintLevel(D(p), D(bid), D(ask)) for p, bid, ask in levels),
        open_time=open_time, open=D(open_) if open_ else None, close=D(close) if close else None,
    )


def series(*bars: FootprintBar, source: str = "test") -> FootprintSeries:
    return FootprintSeries(bars=bars, source=source)


def texts(result, kind: OrderflowStatementKind) -> list[str]:
    return [s.text for s in result.statements if s.kind == kind]


# --- domain ---------------------------------------------------------------------------

def test_bar_requires_ascending_unique_levels():
    with pytest.raises(ValueError, match="ascending"):
        bar([("101", "1", "1"), ("100", "1", "1")])
    with pytest.raises(ValueError, match="ascending"):
        bar([("100", "1", "1"), ("100", "1", "1")])
    with pytest.raises(ValueError, match="negative"):
        FootprintLevel(D("100"), D("-1"), D("0"))


def test_bar_delta_total_poc_direction():
    b = bar([("100", "5", "1"), ("101", "2", "8"), ("102", "1", "1")], open_="100", close="102")
    assert b.delta == D("2")
    assert b.total == D("18")
    assert b.poc.price == D("101")
    assert b.direction == "UP"
    assert bar([("100", "5", "1")]).direction == "DOWN"  # no open/close: delta sign decides
    assert series(b).delta_series == (D("2"),)


# --- F1/F2 imbalances ------------------------------------------------------------------

def test_diagonal_imbalances_and_stacks():
    # Buyers lift 4x the bid one tick lower on three consecutive levels: a stacked buy imbalance.
    b = bar([("100", "2", "1"), ("101", "2", "8"), ("102", "2", "9"), ("103", "1", "8"), ("104", "1", "1")], open_="100", close="104")
    reading = analyze_footprint(series(b))
    assert reading.buy_imbalances == 3
    assert reading.stacked_buy == 3
    assert reading.sell_imbalances == 0
    assert "stacked_buy_imbalances=3" in [s.text for s in reading.statements]
    assert reading.summary["stacked_buy"] == 3


def test_zero_opposite_side_counts_as_imbalance_but_a_lone_one_is_not_a_stack():
    b = bar([("100", "0", "1"), ("101", "3", "9"), ("102", "3", "2"), ("103", "2", "1")], open_="100", close="103")
    reading = analyze_footprint(series(b))
    # 9 at 101 against bid 0 at 100 is an imbalance; 2 at 102 against bid 3 is not.
    assert reading.buy_imbalances == 1
    assert reading.stacked_buy == 1


def test_sell_imbalances_look_one_tick_up():
    b = bar([("100", "9", "1"), ("101", "9", "2"), ("102", "8", "1"), ("103", "1", "1")], open_="103", close="100")
    reading = analyze_footprint(series(b))
    assert reading.sell_imbalances == 3 and reading.stacked_sell == 3


# --- F3 auction edges ----------------------------------------------------------------

def test_finished_and_unfinished_auction_edges():
    finished_top = bar([("100", "3", "3"), ("101", "3", "3"), ("102", "0", "2")], open_="100", close="102")
    reading = analyze_footprint(series(finished_top))
    assert reading.finished_high is True and reading.unfinished_high is False
    assert reading.finished_low is False and reading.unfinished_low is True
    assert {"finished_auction_high", "unfinished_auction_low"} <= set(s.text for s in reading.statements)


# --- F4/F5 cluster and thin extreme -------------------------------------------------------

def test_absorption_cluster_at_the_top_means_passive_sellers():
    # Buyers push up and pile 30 at the top level against a mean of ~8: sellers absorb.
    b = bar([("100", "2", "2"), ("101", "2", "3"), ("102", "2", "3"), ("103", "3", "3"), ("104", "10", "30")], open_="100", close="104")
    reading = analyze_footprint(series(b))
    assert reading.absorption_cluster == "PASSIVE_SELLERS"
    assert any(s.text.startswith("footprint_absorption_cluster=passive_sellers") for s in reading.statements)
    assert reading.thin_extreme is None


def test_cluster_at_the_bottom_with_sellers_means_passive_buyers():
    b = bar([("100", "30", "10"), ("101", "3", "3"), ("102", "3", "2"), ("103", "3", "2"), ("104", "2", "2")], open_="104", close="100")
    assert analyze_footprint(series(b)).absorption_cluster == "PASSIVE_BUYERS"


def test_thin_extreme_in_the_direction_of_the_move():
    # Up bar whose top level carries almost nothing: buyers thin at the high.
    b = bar([("100", "5", "5"), ("101", "5", "6"), ("102", "4", "6"), ("103", "4", "5"), ("104", "0", "1")], open_="100", close="104")
    reading = analyze_footprint(series(b))
    assert reading.thin_extreme == "BUYERS_THIN_AT_HIGH"
    assert reading.finished_high is True
    down = bar([("100", "1", "0"), ("101", "6", "4"), ("102", "6", "4"), ("103", "5", "5"), ("104", "5", "5")], open_="104", close="100")
    assert analyze_footprint(series(down)).thin_extreme == "SELLERS_THIN_AT_LOW"


def test_poc_location_thirds():
    assert analyze_footprint(series(bar([("100", "1", "1"), ("101", "1", "1"), ("102", "9", "9")]))).poc_location == "UPPER"
    assert analyze_footprint(series(bar([("100", "9", "9"), ("101", "1", "1"), ("102", "1", "1")]))).poc_location == "LOWER"
    assert analyze_footprint(series(bar([("100", "1", "1"), ("101", "9", "9"), ("102", "1", "1")]))).poc_location == "MIDDLE"


# --- builders ---------------------------------------------------------------------------

def test_footprint_from_trades_buckets_by_tick_and_candle():
    candles = (candle(58, 100.0, 101.0, 99.0, 100.5), candle(59, 100.5, 102.0, 100.0, 101.5))
    start = candles[1].open_time
    trades = [
        Trade("BTCUSDT", 101.52, 2.0, start + timedelta(minutes=1), trade_id=1, buyer_is_maker=False),  # buy at 101.5 bucket
        Trade("BTCUSDT", 101.58, 1.0, start + timedelta(minutes=2), trade_id=2, buyer_is_maker=True),  # sell at 101.5 bucket
        Trade("BTCUSDT", 100.01, 3.0, start + timedelta(minutes=3), trade_id=3, buyer_is_maker=True),
        Trade("BTCUSDT", 100.9, 1.0, candles[0].open_time + timedelta(minutes=5), trade_id=4, buyer_is_maker=False),
        Trade("BTCUSDT", 100.9, 1.0, start + timedelta(minutes=4), trade_id=5, buyer_is_maker=None),  # no side: skipped
        Trade("BTCUSDT", 100.9, 1.0, NOW + timedelta(hours=1), trade_id=6, buyer_is_maker=False),  # outside: skipped
    ]
    fp = footprint_from_trades(trades, candles, D("0.5"))
    assert fp is not None and len(fp.bars) == 2 and fp.skipped_trades == 2
    last = fp.last
    assert [(str(l.price), str(l.bid_volume), str(l.ask_volume)) for l in last.levels] == [("100.0", "3.0", "0"), ("101.5", "1.0", "2.0")]
    assert last.open == D("100.5") and last.close == D("101.5")
    assert fp.delta_series == (D("1.0"), D("-2.0"))
    assert footprint_from_trades([], candles, D("0.5")) is None
    with pytest.raises(ValueError):
        footprint_from_trades(trades, candles, D("0"))


def test_footprint_from_levels_infers_tick_and_direction():
    candles = (candle(59, 100.0, 102.0, 99.5, 101.5),)
    fp = footprint_from_levels(
        [(candles[0].open_time, [(D("101"), D("1"), D("2")), (D("100"), D("2"), D("1")), (D("100.5"), D("1"), D("1"))])],
        source="x", candles=candles,
    )
    assert fp is not None and fp.tick_size == D("0.5")
    assert [str(l.price) for l in fp.last.levels] == ["100", "100.5", "101"]
    assert fp.last.direction == "UP"
    assert footprint_from_levels([(None, [])], source="x") is None


# --- engine integration -------------------------------------------------------------------

def base_candles(last_close: float, last_volume: float = 100.0) -> tuple[Candle, ...]:
    base = tuple(candle(50 + i, 100.0 - 0.1 * (i % 2), 100.5, 99.5, 100.0 - 0.1 * ((i + 1) % 2)) for i in range(5))
    prev = base[-1].close
    return base + (candle(59, prev, max(prev, last_close) + 0.1, min(prev, last_close) - 0.1, last_close, volume=last_volume),)


def test_footprint_supplies_delta_series_and_net_delta():
    fp = series(bar([("99", "5", "1")]), bar([("99", "2", "9"), ("100", "1", "1")]))
    result = ENGINE.evaluate(OrderflowInputs(candles=base_candles(100.4), footprint=fp))
    assert result.aggressive_side == "BUYERS"
    assert "net_delta_derived_from_footprint_last_bar" in texts(result, OrderflowStatementKind.OBSERVATION)
    assert result.footprint["last_delta"] == "7"
    assert "delta_series" not in result.missing_data


def test_footprint_cluster_confirms_absorption():
    cluster = bar([("99", "2", "2"), ("99.5", "2", "3"), ("100", "2", "3"), ("100.5", "3", "3"), ("101", "10", "30")], open_="99", close="101")
    heavy = base_candles(99.0, 150.0)  # buyers aggressive, price down, heavy volume: absorption hypothesis
    plain = ENGINE.evaluate(OrderflowInputs(candles=heavy, net_delta=D("120")))
    with_fp = ENGINE.evaluate(OrderflowInputs(candles=heavy, net_delta=D("120"), footprint=series(cluster)))
    assert plain.absorption_hypothesis == "PASSIVE_SELLERS" and plain.absorption_confirmed is False
    assert with_fp.absorption_confirmed is True
    assert "absorption_supported_by_footprint_cluster" in texts(with_fp, OrderflowStatementKind.CONFIRMATION)
    assert with_fp.footprint["absorption_cluster"] == "PASSIVE_SELLERS"


def test_finished_auction_confirms_exhaustion():
    thin = base_candles(99.0, 40.0)  # buyers aggressive, price down, thin volume: exhaustion hypothesis
    finished_top = bar([("99", "3", "3"), ("99.5", "3", "3"), ("100", "0", "2")], open_="99", close="100")
    result = ENGINE.evaluate(OrderflowInputs(candles=thin, net_delta=D("120"), footprint=series(finished_top)))
    assert result.exhaustion_hypothesis == "BUYERS_EXHAUSTED"
    assert result.exhaustion_confirmed is True
    assert "exhaustion_supported_by_finished_auction" in texts(result, OrderflowStatementKind.CONFIRMATION)


def test_stacked_imbalances_refute_exhaustion():
    thin = base_candles(99.0, 40.0)
    stacked = bar([("99", "2", "1"), ("99.5", "2", "8"), ("100", "2", "9"), ("100.5", "1", "8"), ("101", "1", "1")], open_="99", close="101")
    result = ENGINE.evaluate(OrderflowInputs(candles=thin, net_delta=D("120"), footprint=series(stacked)))
    assert result.exhaustion_hypothesis is None and result.exhaustion_confirmed is False
    assert "exhaustion_refuted_stacked_imbalances" in texts(result, OrderflowStatementKind.REFUTATION)
    assert result.footprint["stacked_buy"] == 3


def test_footprint_without_signal_leaves_the_read_alone():
    neutral = bar([("99", "3", "3"), ("99.5", "3", "3"), ("100", "3", "3")], open_="99", close="100")
    result = ENGINE.evaluate(OrderflowInputs(candles=base_candles(99.0, 40.0), net_delta=D("120"), footprint=series(neutral)))
    assert result.exhaustion_hypothesis == "BUYERS_EXHAUSTED" and result.exhaustion_confirmed is False
    assert result.to_dict()["footprint"]["bars"] == 1


def test_stacked_imbalances_reach_scenarios():
    stacked = bar([("99", "2", "1"), ("99.5", "2", "8"), ("100", "2", "9"), ("100.5", "1", "8"), ("101", "1", "1")], open_="99", close="101")
    candles = base_candles(100.9)
    orderflow = ENGINE.evaluate(OrderflowInputs(candles=candles, net_delta=D("120"), footprint=series(stacked)))
    from src.orderflow_scenario.engines.market_state import AuctionStateEngine, MarketStateEngine

    market_state = MarketStateEngine().evaluate(candles)
    auction = AuctionStateEngine().evaluate(candles, market_state)
    levels = LevelSet(range_high=D("100.6"), range_low=D("99.5"), last_price=D("100.9"))
    scenarios = ScenarioGenerator().generate(market_state, auction, orderflow, levels)
    by_id = {s.scenario_id: s for s in scenarios}
    assert "footprint_stacked_buy_imbalances" in by_id["A"].evidence_for
    assert "footprint_stacked_buy_imbalances" in by_id["C"].evidence_against


# --- adapters, CLI, pipeline, report -------------------------------------------------------

def test_generic_adapter_reads_footprint_json():
    adapted = GenericOrderflowAdapter().adapt({
        "symbol": "BTCUSDT", "observed_at": NOW.isoformat(), "candles": [],
        "footprint": [{"open_time": NOW.isoformat(), "levels": [[100, 2, 1], ["100.5", "1", "4"]]}],
        "footprint_tick_size": "0.5",
    })
    assert adapted.footprint is not None and adapted.footprint.source == "generic_json"
    assert adapted.footprint.last.delta == D("2")
    assert adapted.footprint_tick_size == D("0.5")
    with pytest.raises(ValueError, match="price, bid, ask"):
        GenericOrderflowAdapter().adapt({"symbol": "X", "observed_at": NOW.isoformat(), "candles": [], "footprint": [{"levels": [[1, 2]]}]})


def test_cli_builds_footprint_from_trades_when_tick_size_given(tmp_path, capsys):
    from src.orderflow_scenario import cli

    candles = tuple(candle(i, 100.0 - 0.1 * (i % 2), 100.5, 99.5, 100.0 - 0.1 * ((i + 1) % 2)) for i in range(60))
    start = candles[-1].open_time
    trades = [
        {"symbol": "BTCUSDT", "price": 100.0 + 0.5 * (i % 3), "quantity": 1.0, "event_time": (start + timedelta(minutes=i)).isoformat(),
         "trade_id": i, "buyer_is_maker": i % 2 == 0}
        for i in range(30)
    ]
    payload = {
        "symbol": "BTCUSDT", "venue": "BINANCE", "timeframe": "4H", "observed_at": NOW.isoformat(),
        "candles": [{"symbol": c.symbol, "timeframe": c.timeframe, "open_time": c.open_time.isoformat(), "close_time": c.close_time.isoformat(),
                     "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume, "trade_count": c.trade_count, "closed": True} for c in candles],
        "trades": trades, "price_now": candles[-1].close, "footprint_tick_size": "0.5",
    }
    path = tmp_path / "input.json"
    path.write_text(json.dumps(payload))
    code = cli.main(["--input", str(path)])
    out = capsys.readouterr()
    assert code == 0, out.err
    output = json.loads(out.out)
    fp = output["orderflow"]["footprint"]
    assert fp["source"] == "trades" and fp["bars"] == 1 and fp["levels"] == 3


def test_pipeline_report_shows_footprint_line():
    candles = tuple(candle(i, 100.0 - 0.1 * (i % 2), 100.5, 99.5, 100.0 - 0.1 * ((i + 1) % 2)) for i in range(60))
    fp = series(bar([("99.5", "3", "3"), ("100", "4", "4"), ("100.5", "0", "2")], open_="99.9", close="100", open_time=candles[-1].open_time), source="trades")
    analysis = Pipeline().run(PipelineInputs(
        market_context=MarketContext("BTCUSDT", "BINANCE", "FUTURES", "4H", NOW), candles=candles,
        trades=tuple(Trade("BTCUSDT", 100.0, 0.01, NOW, trade_id=i, buyer_is_maker=i % 2 == 0) for i in range(50)),
        price_now=D("100"), price_timestamp=NOW, footprint=fp, observed_at=NOW,
    ))
    assert analysis.orderflow.footprint["finished_high"] is True
    report = build_report(analysis)
    assert "Footprint (trades, 1 Kerzen, 3 Stufen)" in report
    assert any(item.get("input") == "footprint" for item in analysis.audit.get("inputs", []))


# --- OpenMarket adapter ---------------------------------------------------------------------

def _openmarket_adapter(*, side_is_aggressor: bool):
    from pathlib import Path

    from src.market_data.providers.openmarket.client import HttpResult, OpenMarketClient
    from src.market_data.providers.openmarket.context_schemas import FUNDING_RATE, LIQUIDATION, OPEN_INTEREST, VOLUME_PROFILE

    fixtures = Path(__file__).parent / "fixtures" / "openmarket_2026_10_21"
    frm, hour = 1792562400, 3600
    expected = {"exchange": "BINANCE_FUTURES", "rawSymbol": "BTCUSDT", "interval": "HOUR"}

    def candles(side: str | None = None, scale: float = 1.0) -> dict:
        points = []
        for index in range(7):
            start = frm + index * hour
            close = 82700 + index * 120
            points.append({"Point": {"open": close - 60, "high": close + 50, "low": close - 90, "close": close, "volume": (1000.5 + index * 10) * scale,
                                     "timestamp": {"s": start}, "firstTimestamp": {"s": start, "ns": 1}, "lastTimestamp": {"s": start + hour - 1, "ns": 0}}})
        series_id = {"type": "TRADE_AGG" if side else "TRADE_SIDE_AGNOSTIC_AGG", **expected}
        if side:
            series_id["side"] = side
        return {"id": series_id, "points": points}

    responses = {
        "TRADE_SIDE_AGNOSTIC_AGG": HttpResult(200, {}, json.dumps({"series": [candles()]}).encode()),
        "TRADE_AGG": HttpResult(200, {}, json.dumps({"series": [candles("BUY", 0.6), candles("SELL", 0.4)]}).encode()),
        OPEN_INTEREST: HttpResult(200, {}, (fixtures / f"{OPEN_INTEREST}.json").read_bytes()),
        FUNDING_RATE: HttpResult(200, {}, (fixtures / f"{FUNDING_RATE}.json").read_bytes()),
        LIQUIDATION: HttpResult(200, {}, (fixtures / f"{LIQUIDATION}.json").read_bytes()),
        VOLUME_PROFILE: HttpResult(200, {}, (fixtures / f"{VOLUME_PROFILE}.json").read_bytes()),
    }

    def transport(method, path, headers, timeout):
        return responses[path.split("type=")[1].split("&")[0]]

    env = {"TIM_OPENMARKET_SECRET_PROVIDER": "env", "TIM_OPENMARKET_API_KEY": "om_test_fixture_value_0123456789",
           "TIM_OPENMARKET_BASE_URL": "https://openmarket.invalid"}
    client = OpenMarketClient(env=env, transport=transport, sleep=lambda _: None, max_retries=0)
    now = datetime.fromtimestamp(1792584436, timezone.utc)
    adapter = OpenMarketAdapter(client, include_per_side=True, side_is_aggressor=side_is_aggressor, context_types=DEFAULT_CONTEXT_TYPES, now=lambda: now)
    request = {"exchange": "BINANCE_FUTURES", "raw_symbol": "BTCUSDT", "interval": "HOUR", "from": frm, "period": 21600, "market_type": "FUTURES"}
    return adapter.adapt(request)


def test_openmarket_adapter_derives_delta_series_and_footprint_once_sides_are_proven():
    adapted = _openmarket_adapter(side_is_aggressor=True)
    assert adapted.delta_series is not None and len(adapted.delta_series) == 6  # running hour excluded
    assert all(delta > 0 for delta in adapted.delta_series)  # BUY series scaled 0.6 vs SELL 0.4
    assert adapted.net_delta == sum(adapted.delta_series)
    assert adapted.footprint is not None and adapted.footprint.source == "openmarket_volume_profile"
    assert adapted.footprint.last.levels[0].price < adapted.footprint.last.levels[-1].price
    assert any(note.startswith("derived:delta_series=TRADE_AGG") for note in adapted.extra_notes)
    assert any(note.startswith("derived:footprint=VOLUME_PROFILE_AGG_rows") for note in adapted.extra_notes)


def test_openmarket_adapter_keeps_footprint_and_delta_out_while_sides_are_unproven():
    adapted = _openmarket_adapter(side_is_aggressor=False)
    assert adapted.delta_series is None and adapted.net_delta is None
    assert adapted.footprint is None
    assert "footprint:VOLUME_PROFILE_AGG_side_semantics_unverified" in adapted.missing_fields
    assert adapted.profile is not None  # levels-only profile still works
