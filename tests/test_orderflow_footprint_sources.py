"""Footprint trade sources: TIM agg_trades (repository) and Binance daily archives, plus the ofsc path.

No network and no database: the repository is a fake, the archive is a synthetic zip
with a checksum sidecar served from a directory (docs/knowledge/ORDERFLOW_REGELN.md, 2b).
"""
import asyncio
import csv
import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.models.market_data import Candle, Trade
from src.orderflow_scenario import cli
from src.orderflow_scenario import footprint_sources as sources

DAY = date(2026, 10, 25)
START = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
END = START + timedelta(minutes=15)
SYMBOL = "BTCUSDT"


def _rows(count: int = 90, first_id: int = 1000) -> list[list[str]]:
    """Three 5-minute buckets of trades: price steps 100000 / 100010 / 100020, alternating sides."""
    rows = []
    for index in range(count):
        moment = START + timedelta(seconds=10 * index)
        price = 100000 + 10 * ((index // 30) % 3) + (5 if index % 7 == 0 else 0)
        rows.append([str(first_id + index), f"{price}.00", "0.5", "1", "1", str(int(moment.timestamp() * 1000)), "true" if index % 2 else "false", "true"])
    # One trade before the window and one after: both must be ignored.
    rows.append(["999", "99000.00", "1", "1", "1", str(int((START - timedelta(seconds=1)).timestamp() * 1000)), "false", "true"])
    rows.append(["2000", "101000.00", "1", "1", "1", str(int(END.timestamp() * 1000)), "true", "true"])
    return rows


def _archive(rows: list[list[str]], *, header: bool = False) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if header:
        writer.writerow(["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id", "transact_time", "is_buyer_maker", "is_best_match"])
    writer.writerows(rows)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(f"{SYMBOL}-aggTrades-{DAY.isoformat()}.csv", buffer.getvalue())
    return out.getvalue()


def _served(tmp_path: Path, payload: bytes, *, bad_checksum: bool = False):
    name = sources.archive_filename(SYMBOL, DAY)
    digest = hashlib.sha256(payload).hexdigest() if not bad_checksum else "0" * 64
    files = {name: payload, name + ".CHECKSUM": f"{digest}  {name}\n".encode()}
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        return files[url.rsplit("/", 1)[1]]

    return fetcher, calls


# --- archives ---------------------------------------------------------------------------

def test_archive_url_and_markets():
    assert sources.archive_url(SYMBOL, DAY) == "https://data.binance.vision/data/spot/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2026-10-25.zip"
    assert "/futures/um/daily/" in sources.archive_url(SYMBOL, DAY, "futures-um")
    with pytest.raises(ValueError, match="market"):
        sources.archive_url(SYMBOL, DAY, "options")


def test_download_archive_verifies_checksum_and_caches(tmp_path):
    payload = _archive(_rows())
    fetcher, calls = _served(tmp_path, payload)
    path = sources.download_archive(SYMBOL, DAY, tmp_path, fetcher=fetcher)
    assert path == tmp_path / "spot" / sources.archive_filename(SYMBOL, DAY) and path.read_bytes() == payload
    assert len(calls) == 2 and calls[1].endswith(".CHECKSUM")
    assert sources.download_archive(SYMBOL, DAY, tmp_path, fetcher=fetcher) == path and len(calls) == 2  # cached
    bad_fetcher, _ = _served(tmp_path, payload, bad_checksum=True)
    with pytest.raises(ValueError, match="checksum mismatch"):
        sources.download_archive(SYMBOL, DAY, tmp_path / "fresh", fetcher=bad_fetcher)
    assert not (tmp_path / "fresh" / "spot" / sources.archive_filename(SYMBOL, DAY)).exists()


def test_trades_from_archive_keeps_the_window_and_sides(tmp_path):
    path = tmp_path / "a.zip"
    path.write_bytes(_archive(_rows(), header=True))
    trades = sources.trades_from_archive(path, SYMBOL, START, END)
    assert len(trades) == 90
    assert trades[0].trade_id == 1000 and trades[0].buyer_is_maker is False and trades[1].buyer_is_maker is True
    assert all(START <= t.event_time < END for t in trades)
    with pytest.raises(ValueError, match="end must be after start"):
        sources.trades_from_archive(path, SYMBOL, END, START)


def test_candles_from_trades_buckets_without_filling(tmp_path):
    path = tmp_path / "a.zip"
    path.write_bytes(_archive(_rows()))
    trades = sources.trades_from_archive(path, SYMBOL, START, END)
    candles = sources.candles_from_trades(trades, SYMBOL, "5m", START, END)
    assert [c.open_time for c in candles] == [START, START + timedelta(minutes=5), START + timedelta(minutes=10)]
    assert candles[0].trade_count == 30 and candles[0].volume == pytest.approx(15.0)
    assert candles[0].low == 100000.0 and candles[0].high == 100005.0 and candles[2].close in (100020.0, 100025.0)
    assert all(c.closed for c in candles)
    # A gap stays a gap: trades only in the first bucket give one candle.
    assert len(sources.candles_from_trades(trades[:30], SYMBOL, "5m", START, END)) == 1
    with pytest.raises(ValueError, match="Unsupported timeframe"):
        sources.candles_from_trades(trades, SYMBOL, "7m", START, END)


def test_load_from_archives_reports_missing_days_or_downloads(tmp_path):
    payload = _archive(_rows())
    fetcher, calls = _served(tmp_path, payload)
    candles, trades, missing = sources.load_from_archives(tmp_path, SYMBOL, "5m", START, END)
    assert (candles, trades, missing) == ([], [], ["2026-10-25"])
    candles, trades, missing = sources.load_from_archives(tmp_path, SYMBOL, "5m", START, END, download=True, fetcher=fetcher)
    assert missing == [] and len(trades) == 90 and len(candles) == 3 and calls
    with pytest.raises(ValueError, match="archive days"):
        sources.load_from_archives(tmp_path, SYMBOL, "1d", START, START + timedelta(days=40))


# --- repository -----------------------------------------------------------------------------

class FakeRepository:
    def __init__(self, trades, candles):
        self.trades, self.candles, self.calls = trades, candles, []

    async def agg_trades_between(self, symbol, start, end):
        self.calls.append(("trades", symbol, start, end))
        return [t for t in self.trades if start <= t.event_time < end]

    async def candles_between(self, symbol, timeframe, start, end):
        self.calls.append(("candles", symbol, timeframe, start, end))
        return list(self.candles)


def test_load_from_repository_prefers_table_candles_and_derives_otherwise(tmp_path):
    path = tmp_path / "a.zip"
    path.write_bytes(_archive(_rows()))
    trades = sources.trades_from_archive(path, SYMBOL, START, END)
    table_candle = Candle(SYMBOL, "5m", START, START + timedelta(minutes=5), 1.0, 2.0, 0.5, 1.5, 9.0, 3, True)
    outside = Candle(SYMBOL, "5m", START - timedelta(minutes=5), START, 1.0, 2.0, 0.5, 1.5, 9.0, 3, True)
    repo = FakeRepository(trades, [outside, table_candle])
    candles, loaded, notes = asyncio.run(sources.load_from_repository(repo, SYMBOL, "5m", START, END))
    assert candles == [table_candle] and len(loaded) == 90 and notes == []
    assert repo.calls[0][0] == "trades" and repo.calls[1][0] == "candles"
    derived, _, notes = asyncio.run(sources.load_from_repository(FakeRepository(trades, []), SYMBOL, "5m", START, END))
    assert len(derived) == 3 and derived[0].trade_count == 30 and notes == ["candles_derived_from_trades"]


def test_load_from_database_uses_repository(monkeypatch):
    created = {}

    class FakeDatabase:
        def __init__(self, url, min_size=1, max_size=5):
            created["url"] = url
            self.closed = False

        async def connect(self):
            created["connected"] = True

        async def close(self):
            created["closed"] = True

    class FakeMarketRepository(FakeRepository):
        def __init__(self, database):
            super().__init__([Trade(SYMBOL, 100000.0, 1.0, START, 1, False)], [])

    import src.database.connection as connection
    import src.database.repository as repository

    monkeypatch.setattr(connection, "Database", FakeDatabase)
    monkeypatch.setattr(repository, "MarketRepository", FakeMarketRepository)
    candles, trades, notes = sources.load_from_database("postgresql://x:1/y", SYMBOL, "5m", START, END)
    assert created == {"url": "postgresql://x:1/y", "connected": True, "closed": True}
    assert len(trades) == 1 and len(candles) == 1 and notes == ["candles_derived_from_trades"]


# --- payload and CLI --------------------------------------------------------------------------

def test_payload_for_pipeline_carries_tick_and_source(tmp_path):
    path = tmp_path / "a.zip"
    path.write_bytes(_archive(_rows()))
    trades = sources.trades_from_archive(path, SYMBOL, START, END)
    candles = sources.candles_from_trades(trades, SYMBOL, "5m", START, END)
    payload = sources.payload_for_pipeline(symbol=SYMBOL, timeframe="5m", candles=candles, trades=trades, tick_size=Decimal("10"), observed_at=END, source="test")
    assert payload["footprint_tick_size"] == "10" and payload["extra_notes"] == ["footprint_source=test"]
    assert payload["price_now"] == candles[-1].close and len(payload["trades"]) == 90
    with pytest.raises(ValueError):
        sources.payload_for_pipeline(symbol=SYMBOL, timeframe="5m", candles=candles, trades=trades, tick_size=Decimal("0"), observed_at=END, source="test")


def test_cli_footprint_from_archive(tmp_path, capsys):
    (tmp_path / "spot").mkdir()
    (tmp_path / "spot" / sources.archive_filename(SYMBOL, DAY)).write_bytes(_archive(_rows()))
    code = cli.main([
        "--footprint-source", "archive", "--archive-root", str(tmp_path), "--symbol", SYMBOL, "--timeframe", "5m",
        "--start", START.isoformat().replace("+00:00", "Z"), "--end", END.isoformat(), "--tick", "10", "--validate",
    ])
    out = capsys.readouterr()
    assert code == 0, out.err
    assert "footprint_evidence=" in out.err and '"trades": 90' in out.err and "schema_validation=PASS" in out.err
    output = json.loads(out.out)
    fp = output["orderflow"]["footprint"]
    assert fp["source"] == "trades" and fp["bars"] == 3 and fp["levels"] >= 1 and fp["tick_size"] == "10"
    assert output["orderflow"]["reaction"] in {"ABSORPTION", "EXHAUSTION", "CONTINUATION", "UNRESOLVED"}


def test_cli_footprint_archive_without_data_fails_closed(tmp_path, capsys):
    code = cli.main(["--footprint-source", "archive", "--archive-root", str(tmp_path), "--start", START.isoformat(), "--end", END.isoformat()])
    out = capsys.readouterr()
    assert code == 2 and "no trades" in out.err
    assert cli.main(["--footprint-source", "archive", "--start", START.isoformat()]) == 2
    assert "requires --end" in capsys.readouterr().err
    assert cli.main(["--footprint-source", "archive", "--start", START.isoformat(), "--end", END.isoformat(), "--tick", "x"]) == 2
