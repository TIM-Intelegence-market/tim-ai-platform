"""Isolated multi-symbol prototype: config, partitioning, ordering, risk, buffers, streams."""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.data_ingestion.binance_ws import BinanceTradeStream
from src.models.market_data import Trade
from src.multi_symbol import backpressure, ordering, risk, streams
from src.multi_symbol.config import MAX_SYMBOLS, resolve_symbols
from src.multi_symbol.instruments import SNAPSHOT_SPECS, parse_exchange_info
from src.multi_symbol.partition import SymbolPartitionedCandles, UnknownSymbolError

T0 = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)


def trade(symbol: str, seconds: float, trade_id: int, price: float = 100.0) -> Trade:
    return Trade(symbol, price, 1.0, T0 + timedelta(seconds=seconds), trade_id, False)


# --- configuration -------------------------------------------------------

def test_default_is_single_symbol_and_ignores_symbol_list():
    config = resolve_symbols({"TIM_SYMBOLS": "BTCUSDT,ETHUSDT"})
    assert config.enabled is False
    assert config.symbols == ("BTCUSDT",)


def test_default_follows_tim_symbol():
    assert resolve_symbols({"TIM_SYMBOL": "ethusdt"}).symbols == ("ETHUSDT",)


def test_enabled_puts_primary_first():
    config = resolve_symbols({
        "TIM_MULTI_SYMBOL_ENABLED": "true",
        "TIM_SYMBOL": "BTCUSDT",
        "TIM_SYMBOLS": "solusdt, ETHUSDT ,BTCUSDT",
    })
    assert config.symbols == ("BTCUSDT", "SOLUSDT", "ETHUSDT")
    assert config.primary == "BTCUSDT"


@pytest.mark.parametrize("env, message", [
    ({"TIM_MULTI_SYMBOL_ENABLED": "true", "TIM_SYMBOLS": ""}, "at least one"),
    ({"TIM_MULTI_SYMBOL_ENABLED": "true", "TIM_SYMBOLS": "BTCUSDT,BTCUSDT"}, "duplicates"),
    ({"TIM_MULTI_SYMBOL_ENABLED": "true", "TIM_SYMBOLS": "ETHUSDT"}, "TIM_SYMBOL must be part"),
    ({"TIM_MULTI_SYMBOL_ENABLED": "true", "TIM_SYMBOLS": "BTCUSDT,ETH/USDT"}, "invalid symbol"),
    ({"TIM_MULTI_SYMBOL_ENABLED": "maybe"}, "true or false"),
    ({"TIM_MULTI_SYMBOL_ENABLED": "true",
      "TIM_SYMBOLS": ",".join(["BTCUSDT"] + [f"X{i}USDT" for i in range(MAX_SYMBOLS)])}, "at most"),
])
def test_invalid_configuration_fails_closed(env, message):
    with pytest.raises(ValueError, match=message):
        resolve_symbols(env)


# --- instruments ---------------------------------------------------------

def test_snapshot_specs_round_on_tick_and_floor_quantity():
    btc = SNAPSHOT_SPECS["BTCUSDT"]
    assert btc.round_price(Decimal("80887.245")) == Decimal("80887.24")  # half-even
    assert btc.round_price(Decimal("80887.2451")) == Decimal("80887.25")
    sol = SNAPSHOT_SPECS["SOLUSDT"]
    assert sol.floor_quantity(Decimal("0.0489")) == Decimal("0.048")


def test_order_size_checks_min_notional_and_step():
    eth = SNAPSHOT_SPECS["ETHUSDT"]
    assert eth.check_order_size(Decimal("2359.14"), Decimal("0.0022")) == (True, "OK")
    assert eth.check_order_size(Decimal("2359.14"), Decimal("0.0021"))[1] == "NOTIONAL_BELOW_MIN"
    assert eth.check_order_size(Decimal("2359.14"), Decimal("0.00215"))[1] == "QTY_NOT_ON_STEP"
    with pytest.raises(ValueError):
        eth.check_order_size(Decimal("0"), Decimal("1"))
    with pytest.raises(ValueError):
        eth.round_price(Decimal("NaN"))


def test_parse_exchange_info_requires_all_filters():
    payload = {"symbols": [{"symbol": "ethusdt", "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
        {"filterType": "LOT_SIZE", "stepSize": "0.00010000", "minQty": "0.00010000"},
        {"filterType": "NOTIONAL", "minNotional": "5.00000000"},
    ]}]}
    spec = parse_exchange_info(payload, as_of="t")["ETHUSDT"]
    assert spec.tick_size == Decimal("0.01") and spec.min_notional == Decimal("5")
    payload["symbols"][0]["filters"].pop()
    with pytest.raises(ValueError, match="incomplete"):
        parse_exchange_info(payload, as_of="t")


# --- per-symbol candle state ----------------------------------------------

def test_partitioned_candles_keep_symbols_apart():
    candles = SymbolPartitionedCandles(["BTCUSDT", "ETHUSDT"], ["1m"])
    for item in (trade("BTCUSDT", 0, 1, 100), trade("ETHUSDT", 1, 1, 10), trade("BTCUSDT", 61, 2, 101)):
        candidate, completed = candles.candidate(item)
        candles.commit(item.symbol, candidate, completed)
    btc = candles.history("BTCUSDT", "1m")
    assert [(c.symbol, c.close) for c in btc] == [("BTCUSDT", 100.0)]
    assert candles.history("ETHUSDT", "1m") == []


def test_candidate_does_not_touch_committed_state_or_other_symbols():
    candles = SymbolPartitionedCandles(["BTCUSDT", "ETHUSDT"], ["1m"])
    for item in (trade("BTCUSDT", 10, 1), trade("ETHUSDT", 10, 1)):
        candidate, completed = candles.candidate(item)
        candles.commit(item.symbol, candidate, completed)
    eth_before = copy.deepcopy(candles.state("ETHUSDT").aggregator.snapshots())
    # Out-of-order BTC trade fails; ETH and the committed BTC state are unchanged.
    with pytest.raises(ValueError, match="Out-of-order"):
        candles.candidate(trade("BTCUSDT", 5, 2))
    assert candles.state("ETHUSDT").aggregator.snapshots() == eth_before
    # An ETH trade older than the BTC trade is fine: time order is per symbol.
    candidate, _ = candles.candidate(trade("ETHUSDT", 11, 2))
    assert candidate is not candles.state("ETHUSDT").aggregator


def test_unknown_symbol_and_foreign_candle_are_rejected():
    candles = SymbolPartitionedCandles(["BTCUSDT"], ["1m"])
    with pytest.raises(UnknownSymbolError):
        candles.candidate(trade("ETHUSDT", 0, 1))
    other = SymbolPartitionedCandles(["ETHUSDT"], ["1m"])
    first, _ = other.candidate(trade("ETHUSDT", 0, 1))
    other.commit("ETHUSDT", first, [])
    _, completed = other.candidate(trade("ETHUSDT", 61, 2))
    with pytest.raises(ValueError, match="another symbol"):
        candles.commit("BTCUSDT", candles.state("BTCUSDT").aggregator, completed)


# --- ordering, dedup, recovery cursors ------------------------------------

def test_cursor_book_classifies_per_symbol():
    book = ordering.SymbolCursorBook({"BTCUSDT": 4_097_206_014, "SOLUSDT": 679_862_649})
    assert book.classify("SOLUSDT", 679_862_650).status == ordering.ACCEPT
    assert book.classify("BTCUSDT", 4_097_206_014).status == ordering.DUPLICATE
    gap = book.classify("BTCUSDT", 4_097_206_020)
    assert (gap.status, gap.missing_from, gap.missing_to) == (ordering.GAP, 4_097_206_015, 4_097_206_019)
    assert book.classify("ETHUSDT", 2_107_348_155).status == ordering.ACCEPT  # no cursor yet


def test_cursor_book_advances_only_in_order_and_recovery_never_rewinds():
    book = ordering.SymbolCursorBook({"BTCUSDT": 10})
    with pytest.raises(ValueError, match="GAP"):
        book.advance("BTCUSDT", 12)
    book.recovered_through("BTCUSDT", 11)
    book.advance("BTCUSDT", 12)
    with pytest.raises(ValueError, match="backwards"):
        book.recovered_through("BTCUSDT", 5)
    assert book.snapshot() == {"BTCUSDT": 12}
    with pytest.raises(ValueError):
        book.classify("BTCUSDT", True)


@dataclass
class Item:
    symbol: str
    aggregate_trade_id: int
    status: str = "PENDING"


def test_global_strict_order_mixes_symbols_and_blocks_on_foreign_head():
    items = [Item("BTCUSDT", 4_000_000_001), Item("BTCUSDT", 4_000_000_002),
             Item("SOLUSDT", 600_000_001, "QUARANTINED"), Item("SOLUSDT", 600_000_002)]
    # Today's claim order: SOL ids are smaller, its quarantined head blocks BTC too.
    assert ordering.global_order_heads(items, 100) == []
    heads = ordering.per_symbol_heads(items, 100)
    assert [i.aggregate_trade_id for i in heads["BTCUSDT"]] == [4_000_000_001, 4_000_000_002]
    assert heads["SOLUSDT"] == []


def test_per_symbol_heads_respect_limit_and_processing_blocker():
    items = [Item("ETHUSDT", 3), Item("ETHUSDT", 1), Item("ETHUSDT", 2, "PROCESSING"),
             Item("BTCUSDT", 7, "COMPLETED"), Item("BTCUSDT", 8), Item("BTCUSDT", 9)]
    heads = ordering.per_symbol_heads(items, 1)
    assert [i.aggregate_trade_id for i in heads["ETHUSDT"]] == [1]
    assert [i.aggregate_trade_id for i in heads["BTCUSDT"]] == [8]
    assert [i.aggregate_trade_id for i in ordering.per_symbol_heads(items, 10)["ETHUSDT"]] == [1]
    with pytest.raises(ValueError):
        ordering.per_symbol_heads(items, 0)


# --- portfolio risk -------------------------------------------------------

LIMITS = risk.PortfolioLimits(max_total_open_r=3.0, max_open_r_per_symbol=1.0, max_open_plans=3,
                              max_same_direction_r=2.0)


def test_risk_allows_within_limits_and_float_edges():
    open_plans = [risk.PaperPlan("BTCUSDT", "LONG", 1.0), risk.PaperPlan("ETHUSDT", "SHORT", 1.0)]
    decision = risk.evaluate(open_plans, risk.PaperPlan("SOLUSDT", "LONG", 1.0), LIMITS)
    assert decision.status == risk.ALLOW and decision.total_open_r_after == 3.0
    tenths = [risk.PaperPlan("BTCUSDT", "LONG", 0.1)] * 2
    assert risk.evaluate(tenths, risk.PaperPlan("ETHUSDT", "LONG", 0.1), LIMITS).status == risk.ALLOW


def test_risk_rejects_with_all_reasons():
    open_plans = [risk.PaperPlan("BTCUSDT", "LONG", 1.0), risk.PaperPlan("ETHUSDT", "LONG", 1.0),
                  risk.PaperPlan("SOLUSDT", "LONG", 0.5)]
    decision = risk.evaluate(open_plans, risk.PaperPlan("BTCUSDT", "LONG", 0.6), LIMITS)
    assert decision.status == risk.REJECT
    assert set(decision.reasons) == {"MAX_OPEN_PLANS", "MAX_TOTAL_OPEN_R", "MAX_OPEN_R_PER_SYMBOL",
                                     "MAX_SAME_DIRECTION_R"}


def test_risk_inputs_fail_closed():
    with pytest.raises(ValueError):
        risk.PaperPlan("BTCUSDT", "UP", 1.0)
    with pytest.raises(ValueError):
        risk.PaperPlan("BTCUSDT", "LONG", float("nan"))
    with pytest.raises(ValueError):
        risk.PortfolioLimits(max_total_open_r=float("inf"))
    with pytest.raises(ValueError):
        risk.PortfolioLimits(max_open_plans=0)


# --- backpressure and metrics ---------------------------------------------

def test_backpressure_is_isolated_per_symbol():
    buffers = backpressure.SymbolBuffers(["BTCUSDT", "SOLUSDT"], limit=2)
    buffers.put("SOLUSDT", 1)
    buffers.put("SOLUSDT", 2)
    with pytest.raises(backpressure.SymbolBackpressure) as error:
        buffers.put("SOLUSDT", 3)
    assert error.value.symbol == "SOLUSDT"
    buffers.put("BTCUSDT", 1)  # BTC still accepts
    assert buffers.reset("SOLUSDT") == 2 and buffers.depth("SOLUSDT") == 0
    assert buffers.take("BTCUSDT") == 1 and buffers.take("BTCUSDT") is None
    rows = buffers.metrics.as_rows()
    assert {"metric_name": "backpressure_total", "metric_value": 1.0, "metadata": {"symbol": "SOLUSDT"}} in rows
    with pytest.raises(ValueError):
        buffers.put("ETHUSDT", 1)


# --- streams and reconnect ------------------------------------------------

class FakeStream:
    def __init__(self, symbol: str, script: list[str], stop_event: asyncio.Event) -> None:
        self.symbol, self.script, self.stop_event = symbol, script, stop_event

    async def run(self) -> None:
        action = self.script.pop(0) if self.script else "run"
        if action == "fail":
            raise ConnectionError(f"{self.symbol} fatal")
        await self.stop_event.wait()

    def stop(self) -> None:
        self.stop_event.set()


def test_one_failing_symbol_does_not_stop_the_others():
    async def scenario():
        stop = asyncio.Event()
        scripts = {"BTCUSDT": ["run"], "ETHUSDT": ["fail", "run"], "SOLUSDT": ["fail", "fail", "fail"]}
        made: list[str] = []

        def factory(symbol: str) -> FakeStream:
            made.append(symbol)
            return FakeStream(symbol, scripts[symbol], stop)

        async def no_sleep(_: float) -> None:
            await asyncio.sleep(0)

        stream_set = streams.MultiSymbolStreamSet(scripts, factory, max_restarts=2, sleep=no_sleep)
        runner = asyncio.create_task(stream_set.run())
        for _ in range(50):
            await asyncio.sleep(0)
        mid = dict(stream_set.state)
        stream_set.stop()
        final = await asyncio.wait_for(runner, 1)
        return mid, final, made, stream_set.metrics

    mid, final, made, metrics = asyncio.run(scenario())
    assert mid == {"BTCUSDT": "RUNNING", "ETHUSDT": "RUNNING", "SOLUSDT": "FAILED"}
    assert final == {"BTCUSDT": "STOPPED", "ETHUSDT": "STOPPED", "SOLUSDT": "FAILED"}
    assert made.count("ETHUSDT") == 2 and made.count("SOLUSDT") == 3 and made.count("BTCUSDT") == 1
    assert metrics.counters[("SOLUSDT", "stream_fatal_total")] == 3
    assert metrics.counters[("ETHUSDT", "stream_restart_total")] == 1


def test_existing_stream_class_gives_one_socket_and_recovery_per_symbol():
    recovered: list[str] = []

    async def handler(_: Trade) -> None:
        return None

    def recovery_for(symbol: str):
        async def recover(first: Trade) -> None:
            recovered.append(f"{symbol}:{first.symbol}")
        return recover

    built = {
        symbol: BinanceTradeStream("wss://stream.binance.com:9443/ws", symbol, handler,
                                   recovery_handler=recovery_for(symbol), recovery_on_connect=True)
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    }
    assert {s.url for s in built.values()} == {
        "wss://stream.binance.com:9443/ws/btcusdt@aggTrade",
        "wss://stream.binance.com:9443/ws/ethusdt@aggTrade",
        "wss://stream.binance.com:9443/ws/solusdt@aggTrade",
    }
    asyncio.run(built["SOLUSDT"].recovery_handler(trade("SOLUSDT", 0, 1)))
    assert recovered == ["SOLUSDT:SOLUSDT"]


def test_prototype_is_not_imported_by_the_runtime():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert "multi_symbol" not in (root / "main.py").read_text(encoding="utf-8")
    assert "multi_symbol" not in (root / "config" / "settings.py").read_text(encoding="utf-8")
