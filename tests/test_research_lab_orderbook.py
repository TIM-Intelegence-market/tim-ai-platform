"""Order-book recorder (Uzi 17.11.2026 "go Orderbuch"): Binance USD-M diff depth + snapshots, book rebuild,
and the Bitunix recorder's optional deeper depth channels. Public feeds only, no orders."""
from __future__ import annotations

import asyncio
import json

import pytest

from src.research_lab.bitunix import recorder as bitunix
from src.research_lab.orderbook import binance, book
from src.research_lab.orderbook.__main__ import main

T0 = 1_763_337_600.0   # 2025-11-17 00:00 UTC is irrelevant here; any fixed epoch works


def ev(first: int, last: int, prev: int, bids=(), asks=(), symbol: str = "BTCUSDT") -> dict:
    return {"e": "depthUpdate", "E": first, "T": first, "s": symbol, "U": first, "u": last, "pu": prev,
            "b": [list(x) for x in bids], "a": [list(x) for x in asks]}


SNAP = {"lastUpdateId": 100, "bids": [["99.0", "1"], ["98.0", "2"]], "asks": [["101.0", "1"], ["102.0", "3"]]}


# -- book rebuild ---------------------------------------------------------------------------------------------
def test_chain_applies_and_drops_old_events():
    b = book.Book()
    assert b.apply(ev(90, 95, 89)) == "nobook"
    b.load_snapshot(SNAP)
    assert b.apply(ev(90, 99, 89)) == "old"                          # u < lastUpdateId
    assert b.apply(ev(98, 103, 97, bids=[("99.0", "0"), ("99.5", "4")])) == "applied"
    assert b.synced and "99.0" not in b.bids and b.bids["99.5"] == 4.0
    assert b.apply(ev(104, 110, 103, asks=[("100.5", "2")])) == "applied"
    bids, asks = b.top(2)
    assert bids == [(99.5, 4.0), (98.0, 2.0)] and asks == [(100.5, 2.0), (101.0, 1.0)]


def test_first_event_must_straddle_the_snapshot():
    b = book.Book()
    b.load_snapshot(SNAP)
    assert b.apply(ev(105, 110, 104)) == "break"                     # U > lastUpdateId: events are missing
    assert b.last_u is None and not b.bids


def test_broken_pu_chain_waits_for_the_next_snapshot():
    rows = [{"kind": "snapshot", "recv_ms": 1, "msg": SNAP},
            {"kind": "depth", "recv_ms": 2, "msg": ev(99, 101, 98)},
            {"kind": "depth", "recv_ms": 3, "msg": ev(105, 106, 104)},   # pu 104 != 101
            {"kind": "depth", "recv_ms": 4, "msg": ev(107, 108, 106)},   # no book
            {"kind": "snapshot", "recv_ms": 5, "msg": dict(SNAP, lastUpdateId=107)},
            {"kind": "depth", "recv_ms": 6, "msg": ev(107, 109, 106)}]
    assert [t for t, _ in book.replay(rows)] == [99, 107]


def test_gap_row_resets_the_book():
    rows = [{"kind": "snapshot", "recv_ms": 1, "msg": SNAP},
            {"kind": "depth", "recv_ms": 2, "msg": ev(99, 101, 98)},
            {"kind": "gap", "from_ms": 2, "to_ms": 9},
            {"kind": "depth", "recv_ms": 10, "msg": ev(102, 103, 101)}]
    assert len(list(book.replay(rows))) == 1


def test_crossed_book_is_seen():
    b = book.Book()
    b.load_snapshot({"lastUpdateId": 1, "bids": [["101.0", "1"]], "asks": [["100.0", "1"]]})
    assert b.crossed


# -- recorder -------------------------------------------------------------------------------------------------
class _FakeWS:
    def __init__(self, msgs):
        self.msgs = list(msgs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def recv(self):
        if self.msgs:
            return self.msgs.pop(0)
        raise ConnectionError("closed")


def _clock(step: float = 0.5):
    t = [T0]

    def clock():
        t[0] += step
        return t[0]

    return clock


def _run(coro, monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(binance.asyncio, "sleep", no_sleep)
    return asyncio.run(coro)


def _wrap(data: dict) -> str:
    return json.dumps({"stream": "btcusdt@depth@100ms", "data": data})


def test_record_writes_depth_snapshot_and_a_rebuildable_book(tmp_path, monkeypatch):
    msgs = [_wrap(ev(95, 99, 94)), _wrap(ev(99, 101, 99)), _wrap(ev(102, 104, 101, bids=[("99.5", "2")])),
            _wrap(ev(105, 106, 104)), '{"result":null,"id":1}', _wrap(ev(1, 2, 0, symbol="ETHUSDT"))]
    conns = [_FakeWS(msgs)]
    seen = []

    def connect(url, **k):
        seen.append(url)
        if conns:
            return conns.pop(0)
        raise ConnectionError("refused")

    counts = _run(binance.record(tmp_path, ["BTCUSDT"], stop_after=20, connect=connect,
                                 snapshot=lambda s, n: SNAP, clock=_clock(), disk_free=lambda _: 10**12), monkeypatch)
    assert seen[0] == "wss://fstream.binance.com/stream?streams=btcusdt@depth@100ms"
    assert counts["depth"] == 4 and counts["snapshot"] >= 1 and counts["rejected"] == 1
    summary = book.check((tmp_path / "BTCUSDT").glob("*.jsonl.gz"))
    assert summary["complete"] and summary["breaks"] == 0 and summary["applied"] >= 1
    assert not (tmp_path / "ETHUSDT").exists()
    assert json.loads((tmp_path / "status.json").read_text())["state"] == "stopped"


def test_snapshot_failure_is_counted_not_fatal(tmp_path, monkeypatch):
    def broken(symbol, limit):
        raise OSError("timeout")

    conns = [_FakeWS([_wrap(ev(1, 2, 0))] * 5)]

    def connect(url, **k):
        if conns:
            return conns.pop(0)
        raise ConnectionError("refused")

    counts = _run(binance.record(tmp_path, ["BTCUSDT"], stop_after=60, connect=connect, snapshot=broken,
                                 clock=_clock(), disk_free=lambda _: 10**12), monkeypatch)
    assert counts["snapshot_errors"] >= 1 and counts["depth"] == 5


def test_low_disk_space_stops_the_recorder(tmp_path, monkeypatch):
    with pytest.raises(bitunix.StorageError, match="free space"):
        _run(binance.record(tmp_path, ["BTCUSDT"], stop_after=5, connect=lambda *a, **k: _FakeWS([]),
                            snapshot=lambda s, n: SNAP, clock=_clock(), disk_free=lambda _: 1), monkeypatch)
    assert json.loads((tmp_path / "status.json").read_text())["state"] == "failed"


def test_restart_writes_a_gap_row(tmp_path, monkeypatch):
    (tmp_path / "status.json").write_text(json.dumps({"last_recv_ms": 1}))
    conns = [_FakeWS([_wrap(ev(1, 2, 0))])]

    def connect(url, **k):
        if conns:
            return conns.pop(0)
        raise ConnectionError("refused")

    counts = _run(binance.record(tmp_path, ["BTCUSDT"], stop_after=10, connect=connect, snapshot=lambda s, n: SNAP,
                                 clock=_clock(), disk_free=lambda _: 10**12), monkeypatch)
    assert counts["gaps"] >= 1
    assert book.check((tmp_path / "BTCUSDT").glob("*.gz"))["rows"]["gap"] >= 1


def test_bad_snapshot_limit_and_symbols_refused(tmp_path):
    with pytest.raises(ValueError):
        asyncio.run(binance.record(tmp_path, ["BTCUSDT"], snapshot_limit=7, connect=lambda *a, **k: _FakeWS([])))
    with pytest.raises(ValueError):
        binance.stream_url(bitunix.validate_symbols(["../x"]))


def test_check_cli(tmp_path, capsys):
    w = bitunix.DayWriter(tmp_path, ["BTCUSDT"], run_id=1)
    w.write("BTCUSDT", {"kind": "snapshot", "recv_ms": 1_763_337_600_000, "msg": SNAP}, 1_763_337_600_000)
    w.write("BTCUSDT", {"kind": "depth", "recv_ms": 1_763_341_200_000, "msg": ev(99, 101, 98)}, 1_763_341_200_000)
    w.close()
    assert main(["check", "--root", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["applied"] == 1 and out["hours"] == 1.0 and out["bytes_per_day_estimate"] > 0


# -- Bitunix deeper depth (opt-in) ----------------------------------------------------------------------------
def test_bitunix_default_channels_unchanged_and_depth15_opt_in(tmp_path):
    assert bitunix.CHANNELS == ("trade", "depth_book1")
    m = bitunix.subscribe_message(["BTCUSDT"], bitunix.validate_channels(["trade", "depth_book15"]))
    assert {"symbol": "BTCUSDT", "ch": "depth_book15"} in m["args"]
    w = bitunix.DayWriter(tmp_path, ["BTCUSDT"])
    msg = json.dumps({"ch": "depth_book15", "symbol": "BTCUSDT", "ts": 1, "data": {"b": [], "a": []}})
    assert bitunix.handle(msg, w, 1_763_337_600_000) is None                       # not subscribed by default
    assert bitunix.handle(msg, w, 1_763_337_600_000, ("trade", "depth_book15")) == "depth_book15"
    w.close()
    with pytest.raises(ValueError):
        bitunix.validate_channels(["depth_book999"])
