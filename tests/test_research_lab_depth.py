import asyncio
import gzip
import json
import math
from datetime import date

import pytest

from src.research_lab.bitunix.recorder import StorageError
from src.research_lab.depth import recorder, replay, tardis
from src.research_lab.depth.book import ASK, BID, LocalBook, to_units
from src.research_lab.depth.sync import DepthSync

T0 = 1_762_819_200_000  # 2025-11-11 00:00 UTC in ms


def ev(U, u, pu, b=(), a=(), E=None):
    return {"e": "depthUpdate", "E": E if E is not None else T0 + u * 100, "T": 0, "s": "BTCUSDT",
            "U": U, "u": u, "pu": pu, "b": [list(x) for x in b], "a": [list(x) for x in a]}


SNAP = {"lastUpdateId": 10, "bids": [["100.0", "1"], ["99.9", "2"]], "asks": [["100.1", "3"], ["100.2", "4"]]}


# --- units and book -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["nan", "inf", "-1", "0.000000001", "abc", True, None])
def test_to_units_refuses_bad_values(bad):
    with pytest.raises((ValueError, TypeError)):
        to_units(bad)


def test_to_units_is_exact():
    assert to_units("0.1") == 10_000_000
    assert to_units("101234.5") == 10_123_450_000_000
    assert to_units("0") == 0


def test_book_levels_best_and_removal():
    b = LocalBook()
    b.load(SNAP["bids"], SNAP["asks"])
    assert b.best_bid() == to_units("100.0") and b.best_ask() == to_units("100.1")
    b.set(BID, "100.0", "0")
    assert b.best_bid() == to_units("99.9")
    b.set(ASK, "500", "0")  # unknown level: normal, ignored
    assert len(b) == 3
    b.set(BID, "100.1", "1")
    assert b.crossed()
    assert b.band_qty(5) is None


def test_band_qty_boundaries_are_exact():
    b = LocalBook()
    # mid = 10000, 5 bp = 5.0 -> bids in [9995, 10000), asks in (10000, 10005]
    b.load([["9999.5", "1"], ["9995", "2"], ["9994.9", "100"]], [["10000.5", "3"], ["10005", "4"], ["10005.1", "100"]])
    assert b.band_qty(5) == (to_units("3"), to_units("7"))


def test_checksum_equal_for_equal_books_and_changes_with_qty():
    x, y = LocalBook(), LocalBook()
    x.load(SNAP["bids"], SNAP["asks"])
    y.load(list(reversed(SNAP["bids"])), SNAP["asks"])
    assert x.checksum() == y.checksum()
    y.set(BID, "99.9", "2.5")
    assert x.checksum() != y.checksum()


# --- sync -----------------------------------------------------------------------------------------------------

def test_sync_buffers_drops_old_and_bridges_snapshot():
    s = DepthSync()
    assert s.on_event(ev(5, 8, 4, b=[("100.0", "9")])) == "buffered"
    assert s.on_event(ev(9, 12, 8, a=[("100.1", "0")])) == "buffered"
    assert s.needs_snapshot
    s.on_snapshot(SNAP)
    assert s.valid and s.last_u == 12
    assert s.counts.dropped == 1  # u=8 < 10
    assert s.book.best_ask() == to_units("100.2")
    assert s.book.levels[BID][to_units("100.0")] == to_units("1")  # dropped event did not touch the book
    assert s.on_event(ev(13, 14, 12, b=[("100.05", "1")])) == "applied"
    assert s.book.best_bid() == to_units("100.05")


def test_sync_gap_invalidates_until_new_snapshot():
    s = DepthSync()
    s.on_snapshot(SNAP)
    assert s.on_event(ev(9, 11, 8)) == "applied"
    assert s.on_event(ev(15, 16, 14)) == "gap"  # pu 14 != last u 11
    assert not s.valid and s.needs_snapshot
    s.on_snapshot({**SNAP, "lastUpdateId": 15})
    assert s.valid and s.last_u == 16


def test_sync_duplicate_message_never_corrupts_book():
    s = DepthSync()
    s.on_snapshot(SNAP)
    e1 = ev(9, 11, 8, b=[("99.8", "1")])
    s.on_event(e1)
    assert s.on_event(e1) == "gap"  # pu 8 != 11: treated as a break, book invalid, no double apply
    assert not s.valid


def test_sync_snapshot_older_than_stream_is_stale():
    s = DepthSync()
    s.on_event(ev(20, 22, 19))
    s.on_snapshot(SNAP)  # lastUpdateId 10 < U 20: events 11..19 are lost
    assert not s.valid and s.counts.stale_snapshots == 1 and s.needs_snapshot
    s.on_snapshot({**SNAP, "lastUpdateId": 21})
    assert s.valid and s.last_u == 22


def test_sync_crossed_book_invalidates():
    s = DepthSync()
    s.on_snapshot(SNAP)
    s.on_event(ev(9, 11, 8, b=[("100.5", "1")]))
    assert not s.valid


# --- recorder + replay ---------------------------------------------------------------------------------------

class _FakeWS:
    def __init__(self, msgs):
        self.msgs = list(msgs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def recv(self):
        await asyncio.sleep(0)
        if self.msgs:
            return self.msgs.pop(0)
        raise ConnectionError("closed")


def _wrap(stream, data):
    return json.dumps({"stream": stream, "data": data})


def _clock(start=T0 / 1000):
    t = [start]

    def clock():
        t[0] += 0.01
        return t[0]

    return clock


async def _yield(_):
    await asyncio.sleep(0)


def _trade(price, buyer_maker, E):
    return {"e": "aggTrade", "E": E, "s": "BTCUSDT", "a": 1, "p": price, "q": "0.5", "f": 1, "l": 1, "T": E,
            "m": buyer_maker}


def _run(tmp_path, depth_conns, trade_conns, snaps, stop_after=20.0, **kw):
    depth_conns, trade_conns, snaps = list(depth_conns), list(trade_conns), list(snaps)

    def connect(url, **_):
        pool = depth_conns if "/public/" in url else trade_conns
        if pool:
            return pool.pop(0)
        raise ConnectionError("refused")

    def fetch():
        if snaps:
            return snaps.pop(0)
        raise OSError("no snapshot")

    return asyncio.run(recorder.record(tmp_path, stop_after=stop_after, connect=connect, clock=kw.pop("clock", _clock()),
                                       fetch_snapshot=fetch, sleep=_yield, disk_free=kw.pop("disk_free", lambda _: 10**12),
                                       **kw))


SNAP_STREAM = {**SNAP, "lastUpdateId": 11}  # taken after the stream opened: first event U=11 <= 11 <= u=12


def _depth_stream(n_seconds=5):
    msgs, u = [], 10
    for i in range(n_seconds * 10):
        msgs.append(_wrap("btcusdt@depth@100ms",
                          ev(u + 1, u + 2, u, b=[(f"{99.0 + (i % 7) / 10:.1f}", str(1 + i % 3))],
                             a=[(f"{100.3 + (i % 5) / 10:.1f}", str(1 + i % 4))], E=T0 + i * 100)))
        u += 2
    return msgs


def test_recorder_writes_rows_and_replay_reproduces_checksums(tmp_path):
    depth = _FakeWS(_depth_stream())
    trades = _FakeWS([_wrap("btcusdt@aggTrade", _trade("100.1", False, T0 + 50)),
                      _wrap("btcusdt@aggTrade", _trade("100.0", True, T0 + 60))])
    counts = _run(tmp_path, [depth], [trades], [SNAP_STREAM])
    assert counts["depth"] == 50 and counts["aggTrade"] == 2 and counts["snapshots"] == 1
    assert counts["seconds"] >= 4 and counts["valid_seconds"] >= 3
    res = replay.replay(tmp_path)
    d = res.as_dict()
    assert d["ok"], d
    assert res.matches == res.seconds == counts["seconds"]
    assert res.trades.checked + res.trades.skipped_invalid == 2
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["state"] == "stopped"


def test_replay_detects_tampered_rows(tmp_path):
    _run(tmp_path, [_FakeWS(_depth_stream())], [], [SNAP_STREAM])
    f = next((tmp_path / "BTCUSDT").glob("*.jsonl.gz"))
    with gzip.open(f, "rt") as fh:
        rows = [json.loads(line) for line in fh]
    depth_rows = [r for r in rows if r["kind"] == "depth"]
    depth_rows[9]["msg"]["b"][0][1] = "123"  # last event before the first checkpoint, level not touched again
    with gzip.open(f, "wt") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in rows))
    res = replay.replay(tmp_path)
    assert res.mismatches > 0 and not res.as_dict()["ok"]


def test_restart_writes_gap_row(tmp_path):
    _run(tmp_path, [_FakeWS(_depth_stream(1))], [], [SNAP_STREAM], clock=_clock())
    _run(tmp_path, [_FakeWS(_depth_stream(1))], [], [SNAP_STREAM], clock=_clock(T0 / 1000 + 100))
    res = replay.replay(tmp_path)
    assert res.runs == 2 and res.gaps >= 1 and res.mismatches == 0


def test_snapshot_failure_is_retried_not_fatal(tmp_path):
    counts = _run(tmp_path, [_FakeWS(_depth_stream(2))], [], [], stop_after=5)
    assert counts["snapshot_errors"] >= 1 and counts["valid_seconds"] == 0


def test_low_disk_is_fatal_and_marked(tmp_path):
    with pytest.raises(StorageError):
        _run(tmp_path, [_FakeWS(_depth_stream(1))], [], [SNAP_STREAM], disk_free=lambda _: 10)
    assert json.loads((tmp_path / "status.json").read_text())["state"] == "failed"


def test_foreign_symbol_is_not_written(tmp_path):
    bad = ev(11, 12, 10)
    bad["s"] = "ETHUSDT"
    counts = _run(tmp_path, [_FakeWS([_wrap("x", bad)])], [], [SNAP_STREAM], stop_after=2)
    assert counts["foreign"] == 1 and counts["depth"] == 0


# --- tardis ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("day", [date(2020, 6, 2), date(2025, 1, 1), date(2026, 11, 1), date(2020, 3, 1)])
def test_tardis_day_rules(day):
    with pytest.raises(ValueError):
        tardis.url_for("trades", day)


def test_tardis_url():
    assert tardis.url_for("incremental_book_L2", date(2020, 6, 1)) == (
        "https://datasets.tardis.dev/v1/binance-futures/incremental_book_L2/2020/06/01/BTCUSDT.csv.gz")


def _csv(path, header, rows):
    with gzip.open(path, "wt", newline="") as fh:
        fh.write(",".join(header) + "\n")
        for r in rows:
            fh.write(",".join(str(x) for x in r) + "\n")


def test_tardis_check_on_small_files(tmp_path):
    bh = ["exchange", "symbol", "timestamp", "local_timestamp", "is_snapshot", "side", "price", "amount"]
    th = ["exchange", "symbol", "timestamp", "local_timestamp", "id", "side", "price", "amount"]
    s = 1_590_969_600_000_000  # 2020-06-01 in µs
    book = [("binance-futures", "BTCUSDT", s, s, "true", "bid", "9500.0", "1"),
            ("binance-futures", "BTCUSDT", s, s, "true", "ask", "9500.1", "1"),
            ("binance-futures", "BTCUSDT", s + 10, s + 10, "false", "ask", "9500.1", "0"),
            ("binance-futures", "BTCUSDT", s + 10, s + 10, "false", "ask", "9500.2", "2"),
            ("binance-futures", "BTCUSDT", s + 2_000_000, s + 2_000_000, "false", "bid", "9500.0", "3")]
    trades = [("binance-futures", "BTCUSDT", s + 5, s + 5, 1, "buy", "9500.1", "1"),
              ("binance-futures", "BTCUSDT", s + 20, s + 20, 2, "sell", "9500.0", "1"),
              ("binance-futures", "BTCUSDT", s + 30, s + 30, 3, "buy", "9499.0", "1")]  # far below the ask
    _csv(tmp_path / "b.csv.gz", bh, book)
    _csv(tmp_path / "t.csv.gz", th, trades)
    res = tardis.check(tmp_path / "b.csv.gz", tmp_path / "t.csv.gz", date(2020, 6, 1))
    assert res.book_rows == 5 and res.trades == 3 and res.snapshot_resets == 1
    assert res.trade_check.checked == 3 and res.trade_check.inside == 2
    assert res.trade_check.worst_units == to_units("1.2")
    assert math.isclose(res.as_dict()["trade_check"]["share"], 2 / 3)
    assert res.seconds_with_book == 1
