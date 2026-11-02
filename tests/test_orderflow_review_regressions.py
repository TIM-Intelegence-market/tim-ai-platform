"""Regression cases from the BTC orderflow plan review; synthetic inputs only."""

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.models.market_data import Candle, Trade
from src.orderflow_scenario import cli, footprint_sources as sources
from src.orderflow_scenario.adapters import GenericOrderflowAdapter
from src.orderflow_scenario.footprint import FootprintBar, FootprintLevel, FootprintSeries, analyze_footprint
from src.orderflow_scenario.engines.data_quality import DataQualityGate, DataQualityInputs
from src.orderflow_scenario.engines.pipeline import Pipeline, PipelineInputs
from src.orderflow_scenario.domain import MarketContext


START = datetime(2024, 1, 1, tzinfo=timezone.utc)
END = START + timedelta(minutes=15)
SYMBOL = "BTCUSDT"


@pytest.mark.parametrize("raw, expected", [("false", False), ("true", True), (False, False), (True, True)])
def test_text_aggressor_flags_keep_their_meaning(raw, expected):
    trades, missing = GenericOrderflowAdapter().parse_trades([
        {"symbol": SYMBOL, "price": 100, "quantity": 1, "event_time": START,
         "buyer_is_maker": raw},
    ])
    assert not missing
    assert trades[0].buyer_is_maker is expected


@pytest.mark.parametrize("raw", ["unknown", "0", 2, [], {}])
def test_unknown_aggressor_flags_are_rejected_instead_of_guessed(raw):
    trades, missing = GenericOrderflowAdapter().parse_trades([
        {"symbol": SYMBOL, "price": 100, "quantity": 1, "event_time": START,
         "buyer_is_maker": raw},
    ])
    assert not trades
    assert any("buyer_is_maker" in item for item in missing)


@pytest.mark.parametrize("bid, ask, field", [("1", "8", "buy"), ("8", "1", "sell")])
def test_price_gaps_cannot_create_diagonal_or_stacked_imbalances(bid, ask, field):
    bar = FootprintBar(tuple(FootprintLevel(Decimal(price), Decimal(bid), Decimal(ask))
                             for price in (100, 102, 104, 106)))
    reading = analyze_footprint(FootprintSeries((bar,), tick_size=Decimal("1")))
    assert getattr(reading, f"{field}_imbalances") == 0
    assert getattr(reading, f"stacked_{field}") == 0


def test_an_internal_gap_breaks_a_run_but_keeps_real_neighbors():
    bar = FootprintBar(tuple(FootprintLevel(Decimal(price), Decimal("1"), Decimal("8"))
                             for price in (100, 101, 103, 104)))
    reading = analyze_footprint(FootprintSeries((bar,), tick_size=Decimal("1")))
    assert reading.buy_imbalances == 2
    assert reading.stacked_buy == 1


def test_partial_boundary_candles_are_not_presented_as_complete_history():
    trades = [Trade(SYMBOL, 100 + i, 1, START + timedelta(minutes=i), i, False)
              for i in range(15)]
    candles = sources.candles_from_trades(
        trades, SYMBOL, "5m", START + timedelta(seconds=1), END - timedelta(seconds=1),
    )
    assert [c.open_time for c in candles] == [START + timedelta(minutes=5)]
    assert candles[0].trade_count == 5
    assert all(c.closed for c in candles)


def test_repository_does_not_supply_a_running_candle_as_closed_evidence():
    class Repo:
        async def agg_trades_between(self, *args):
            return []

        async def candles_between(self, *args):
            return [Candle(SYMBOL, "5m", START, START + timedelta(minutes=5),
                           100, 101, 99, 100, 1, 1, False)]

    candles, _, _ = asyncio.run(sources.load_from_repository(Repo(), SYMBOL, "5m", START, END))
    assert candles == []


def test_cache_corruption_is_checked_against_the_saved_official_digest(tmp_path):
    original = b"synthetic archive bytes"
    name = sources.archive_filename(SYMBOL, START.date())
    digest = hashlib.sha256(original).hexdigest()
    calls = []

    def fetch(url):
        calls.append(url)
        return f"{digest}  {name}\n".encode() if url.endswith(".CHECKSUM") else original

    path = sources.download_archive(SYMBOL, START.date(), tmp_path, fetcher=fetch)
    path.write_bytes(b"truncated or replaced archive")
    with pytest.raises(ValueError, match="checksum mismatch"):
        sources.download_archive(SYMBOL, START.date(), tmp_path, fetcher=fetch)
    assert len(calls) == 2  # verification uses the saved checksum, without network


def test_existing_unattested_cache_requires_an_official_checksum(tmp_path):
    name = sources.archive_filename(SYMBOL, START.date())
    path = tmp_path / "spot" / name
    path.parent.mkdir()
    path.write_bytes(b"unverified local data")
    calls = []

    def fetch(url):
        calls.append(url)
        return f"{'0' * 64}  {name}\n".encode()

    with pytest.raises(ValueError, match="checksum mismatch"):
        sources.download_archive(SYMBOL, START.date(), tmp_path, fetcher=fetch)
    assert len(calls) == 1 and calls[0].endswith(".CHECKSUM")


def test_database_spot_trades_cannot_be_relabelled_as_futures(monkeypatch, capsys):
    def forbidden_database_read(*args, **kwargs):
        pytest.fail("market mismatch must be rejected before connecting")

    monkeypatch.setattr(sources, "load_from_database", forbidden_database_read)
    code = cli.main(["--footprint-source", "db", "--market", "futures-um",
                     "--start", START.isoformat(), "--end", END.isoformat()])
    assert code == 2
    assert "spot" in capsys.readouterr().err.lower()


def test_observation_time_survives_the_adapter_and_pipeline_boundary():
    inputs = cli._pipeline_inputs(GenericOrderflowAdapter(), {
        "symbol": SYMBOL, "venue": "BINANCE", "market_type": "SPOT", "timeframe": "5m",
        "observed_at": END.isoformat(), "candles": [],
    }, observed_at=END)
    assert inputs.observed_at == END
    assert inputs.market_context.timestamp == END


def test_generic_input_uses_its_explicit_historical_cutoff():
    adapted = GenericOrderflowAdapter().adapt({"symbol": SYMBOL, "candles": [], "observed_at": END.isoformat()})
    assert adapted.observed_at == END


def test_explicit_json_footprint_step_is_used_for_adjacency():
    adapted = GenericOrderflowAdapter().adapt({
        "symbol": SYMBOL, "candles": [], "footprint_tick_size": "1",
        "footprint": [{"levels": [[100, 1, 8], [102, 1, 8], [104, 1, 8], [106, 1, 8]]}],
    })
    assert adapted.footprint.tick_size == Decimal("1")
    assert analyze_footprint(adapted.footprint).stacked_buy == 0


@pytest.mark.parametrize("problem", ["future_candle", "unclosed_candle", "future_trade", "future_price"])
def test_temporal_leakage_stops_interpretation(problem):
    candle = Candle(SYMBOL, "5m", START, START + timedelta(minutes=5), 100, 101, 99, 100, 1, 1)
    trade = Trade(SYMBOL, 100, 1, END, 1, False)
    price_time = END
    if problem == "future_candle":
        candle = Candle(SYMBOL, "5m", END, END + timedelta(minutes=5), 100, 101, 99, 100, 1, 1)
    elif problem == "unclosed_candle":
        candle = Candle(SYMBOL, "5m", START, START + timedelta(minutes=5), 100, 101, 99, 100, 1, 1, False)
    elif problem == "future_trade":
        trade = Trade(SYMBOL, 100, 1, END + timedelta(microseconds=1), 1, False)
    else:
        price_time = END + timedelta(microseconds=1)
    report = DataQualityGate(min_candles=1).evaluate(
        DataQualityInputs(candles=(candle,), trades=(trade,), price_now=100, price_timestamp=price_time),
        observed_at=END,
    )
    assert report.status == "INSUFFICIENT_DATA"
    assert problem in report.problems


def test_full_footprint_history_is_bound_to_the_audit_hash():
    last = FootprintBar((FootprintLevel(Decimal("100"), Decimal("1"), Decimal("2")),))
    def digest(previous_bid):
        previous = FootprintBar((FootprintLevel(Decimal("100"), Decimal(previous_bid), Decimal("2")),))
        result = Pipeline().run(PipelineInputs(
            market_context=MarketContext(SYMBOL, "BINANCE", "SPOT", "5m", END), candles=(),
            observed_at=END, footprint=FootprintSeries((previous, last), tick_size=Decimal("1")),
        ))
        return next(item["hash"] for item in result.audit["inputs"] if item["input"] == "footprint")
    assert digest("1") != digest("8")


def test_offline_archive_loader_rejects_corruption_before_parsing(tmp_path):
    name = sources.archive_filename(SYMBOL, START.date())
    path = tmp_path / "spot" / name
    path.parent.mkdir()
    path.write_bytes(b"corrupt archive")
    path.with_suffix(".zip.CHECKSUM").write_text(f"{'0' * 64}  {name}\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        sources.load_from_archives(tmp_path, SYMBOL, "5m", START, END)
