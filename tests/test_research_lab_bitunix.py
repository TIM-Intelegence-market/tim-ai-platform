import asyncio
import gzip
import json
import math
from pathlib import Path

import pytest

from src.research_lab.bitunix import gate, leverage, recorder, target
from src.research_lab.bitunix.contract import BTCUSDT
from src.research_lab.of2.config import DEFAULT_CONFIG as OF2

REPORTS = Path(__file__).resolve().parents[1] / "docs" / "research_lab" / "reports" / "bitunix"
SRC = Path(__file__).resolve().parents[1] / "src"


def _rows(folder):
    out = []
    for f in sorted(folder.glob("*.gz")):
        with gzip.open(f) as fh:
            out.extend(json.loads(x) for x in fh.read().decode().splitlines())
    return out


def test_tier_lookup_and_leverage_cap():
    assert BTCUSDT.tier_for(0).max_leverage == 200
    assert BTCUSDT.tier_for(99_999).mmr == 0.003
    assert BTCUSDT.tier_for(100_000).max_leverage == 150
    assert BTCUSDT.leverage_allowed(200, 50_000)
    assert not BTCUSDT.leverage_allowed(200, 150_000)
    with pytest.raises(ValueError):
        BTCUSDT.tier_for(500_000_000)


def test_size_comes_from_risk_not_leverage():
    rows = leverage.table(equity=1000, risk_fraction=0.0025, stop_distance=0.013)
    assert len({r.notional for r in rows}) == 1  # same notional at every leverage
    assert all(r.loss_at_stop == pytest.approx(2.5, abs=1e-3) for r in rows)
    margins = [r.initial_margin for r in rows]
    assert margins == sorted(margins, reverse=True)


def test_200x_liquidates_before_a_1_3_percent_stop():
    s = leverage.scenario(equity=1000, risk_fraction=0.0025, stop_distance=0.013, leverage=200)
    assert s.liq_distance == pytest.approx(0.002)
    assert s.liq_before_stop
    assert s.verdict.startswith("NOT APPROVED")
    assert leverage.scenario(equity=1000, risk_fraction=0.0025, stop_distance=0.013, leverage=25).verdict == "OK"


def test_max_safe_leverage_formula():
    lev = leverage.max_safe_leverage(0.013, 0.003)
    assert 1 / lev - 0.003 == pytest.approx(1.5 * 0.013)


def test_costs_in_r_grow_when_stop_shrinks():
    wide = leverage.scenario(equity=1000, risk_fraction=0.01, stop_distance=0.013, leverage=5)
    tight = leverage.scenario(equity=1000, risk_fraction=0.01, stop_distance=0.002, leverage=5)
    assert tight.cost_in_r > wide.cost_in_r
    assert tight.cost_in_r > 0.4  # 0.2 % stop: costs eat ~44 % of R


def test_required_equity_and_no_edge():
    edge = target.Edge(win_rate=0.39, win_r=2.4, trades_per_day=0.2)
    assert edge.expectancy_r == pytest.approx(0.39 * 2.4 - 0.61)
    eq = target.required_equity(50, edge, 0.0025)
    assert eq == pytest.approx(50 / (0.2 * edge.expectancy_r * 0.0025))
    flat = target.Edge(win_rate=0.3, win_r=2.0, trades_per_day=1)
    assert math.isinf(target.required_equity(50, flat, 0.01))
    assert edge.breakeven_win_rate() == pytest.approx(1 / 3.4)


def test_simulation_is_reproducible_and_consistent():
    edge = target.Edge(win_rate=0.5, win_r=1.5, trades_per_day=1)
    a = target.simulate(equity=10_000, edge=edge, risk_fraction=0.01, days=60, paths=200, seed=1)
    b = target.simulate(equity=10_000, edge=edge, risk_fraction=0.01, days=60, paths=200, seed=1)
    assert a == b
    assert a.mean_day == pytest.approx(10_000 * 0.01 * edge.expectancy_r, rel=0.15)
    assert 0.3 < a.share_days_no_trade < 0.45  # Poisson(1): e^-1


def test_edge_ci():
    lo, hi = target.edge_ci(0.27, 1.9, 56)
    assert lo < 0 < hi


@pytest.mark.parametrize("value", [None, "NO", "yes", "1", " YES", "YES "])
def test_gate_fails_closed(value, tmp_path):
    env = {gate.KILL_SWITCH_ENV: str(tmp_path / "KILL")}
    if value is not None:
        env[gate.ENV_VAR] = value
    assert not gate.is_authorized(env)
    with pytest.raises(gate.TradingNotAuthorized):
        gate.require_authorized(env)


def test_gate_kill_switch_wins(tmp_path):
    kill = tmp_path / "KILL"
    env = {gate.ENV_VAR: "YES", gate.KILL_SWITCH_ENV: str(kill)}
    assert gate.is_authorized(env)
    kill.write_text("")
    assert gate.authorization_status(env) == (False, "kill switch present")


def test_recorder_handle_and_day_files(tmp_path):
    w = recorder.DayWriter(tmp_path, ["BTCUSDT"])
    trade = {"ch": "trade", "symbol": "BTCUSDT", "ts": 1, "data": [{"t": "x", "p": "1", "v": "2", "s": "buy"}]}
    assert recorder.handle(json.dumps(trade), w, 1_762_819_200_000) == "trade"
    assert recorder.handle('{"op":"ping","pong":1}', w, 1) is None
    assert recorder.handle("not json", w, 1) is None
    w.close()
    files = list((tmp_path / "BTCUSDT").glob("*.jsonl.gz"))
    assert [f.name for f in files] == ["2025-11-11.jsonl.gz"]
    row = _rows(tmp_path / "BTCUSDT")[0]
    assert row["kind"] == "trade" and row["msg"] == trade and row["recv_ms"] == 1_762_819_200_000


def test_subscribe_message_shape():
    m = recorder.subscribe_message(["BTCUSDT", "ETHUSDT"])
    assert m["op"] == "subscribe" and len(m["args"]) == 4
    assert {"symbol": "BTCUSDT", "ch": "trade"} in m["args"]


class _FakeWS:
    def __init__(self, msgs):
        self.msgs = list(msgs)
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, m):
        self.sent.append(json.loads(m))

    async def recv(self):
        if self.msgs:
            return self.msgs.pop(0)
        raise ConnectionError("closed")


def test_record_reconnects_and_writes_gap(tmp_path):
    trade = json.dumps({"ch": "trade", "symbol": "BTCUSDT", "ts": 1, "data": []})
    conns = [_FakeWS([trade]), _FakeWS([trade])]
    t = [1_762_819_200.0]

    def clock():
        t[0] += 0.5
        return t[0]

    async def no_sleep(_):
        return None

    def connect(*a, **k):
        if conns:
            return conns.pop(0)
        raise ConnectionError("refused")

    orig = asyncio.sleep
    asyncio.sleep = no_sleep
    try:
        counts = asyncio.run(recorder.record(tmp_path, ["BTCUSDT"], stop_after=30, connect=connect, clock=clock,
                                             disk_free=lambda _: 10**12))
    finally:
        asyncio.sleep = orig
    assert counts["trade"] == 2
    rows = _rows(tmp_path / "BTCUSDT")
    assert any(r["kind"] == "gap" for r in rows)


def test_slippage_matches_of2_spec():
    assert leverage.SLIPPAGE == OF2.slippage == 0.0003
    assert leverage.STOP_SLIPPAGE == OF2.stop_slippage == 0.0005
    s = leverage.scenario(equity=1000, risk_fraction=0.01, stop_distance=0.01, leverage=10)
    stop_costs = 2 * 0.0006 + 0.0003 + 0.0005
    assert s.notional == pytest.approx(10 / (0.01 + stop_costs), abs=0.01)


@pytest.mark.parametrize("sym", ["../escaped", "BTC/USDT", "", "btcusdt", "A" * 30])
def test_invalid_symbols_refused(sym):
    with pytest.raises(ValueError):
        recorder.validate_symbols([sym])


def test_foreign_symbol_never_leaves_root(tmp_path):
    root = tmp_path / "root"
    w = recorder.DayWriter(root, ["BTCUSDT"])
    evil = json.dumps({"ch": "trade", "symbol": "../escaped", "ts": 1, "data": []})
    other = json.dumps({"ch": "trade", "symbol": "ETHUSDT", "ts": 1, "data": []})
    assert recorder.handle(evil, w, 1_762_819_200_000) == "rejected"
    assert recorder.handle(other, w, 1_762_819_200_000) == "rejected"
    with pytest.raises(ValueError):
        w.write("../escaped", {}, 1_762_819_200_000)
    w.close()
    assert not (tmp_path / "escaped").exists()
    assert not root.exists() or not any(root.rglob("*.gz"))


def _trade_ws():
    return _FakeWS([json.dumps({"ch": "trade", "symbol": "BTCUSDT", "ts": 1, "data": []})] * 3)


def _fast_clock():
    t = [1_762_819_200.0]

    def clock():
        t[0] += 0.5
        return t[0]

    return clock


def test_storage_error_is_fatal_not_reconnect(tmp_path, monkeypatch):
    def broken_open(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(recorder.gzip, "open", broken_open)
    calls = []

    def connect(*a, **k):
        calls.append(1)
        return _trade_ws()

    with pytest.raises(recorder.StorageError):
        asyncio.run(recorder.record(tmp_path, ["BTCUSDT"], stop_after=30, connect=connect, clock=_fast_clock(),
                                    disk_free=lambda _: 10**12))
    assert len(calls) == 1  # no reconnect loop
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["state"] == "failed" and "No space" in status["error"]


def test_low_disk_space_stops(tmp_path):
    with pytest.raises(recorder.StorageError, match="free space"):
        asyncio.run(recorder.record(tmp_path, ["BTCUSDT"], stop_after=5, connect=lambda *a, **k: _trade_ws(),
                                    clock=_fast_clock(), disk_free=lambda _: 1))
    assert json.loads((tmp_path / "status.json").read_text())["state"] == "failed"


def test_restart_writes_gap_from_status(tmp_path):
    (tmp_path / "status.json").write_text(json.dumps({"last_recv_ms": 1_762_819_000_000}))
    conns = [_trade_ws()]

    def connect(*a, **k):
        if conns:
            return conns.pop(0)
        raise ConnectionError("refused")

    async def no_sleep(_):
        return None

    orig = asyncio.sleep
    asyncio.sleep = no_sleep
    try:
        counts = asyncio.run(recorder.record(tmp_path, ["BTCUSDT"], stop_after=30, connect=connect,
                                             clock=_fast_clock(), disk_free=lambda _: 10**12))
    finally:
        asyncio.sleep = orig
    rows = _rows(tmp_path / "BTCUSDT")
    gap = next(r for r in rows if r["kind"] == "gap")
    assert gap["from_ms"] == 1_762_819_000_000
    assert counts["trade"] == 3
    st = json.loads((tmp_path / "status.json").read_text())
    assert st["state"] == "stopped" and st["last_recv_ms"] > 1_762_819_000_000


PRIVATE_ORDER_MARKERS = ("/api/v1/futures/trade/", "/api/v1/futures/tp_sl/", "/api/v1/futures/account/change",
                         "fapi.bitunix.com/private")


def test_no_bitunix_order_path_without_gate():
    """Any module that talks to a private Bitunix trading endpoint must call require_authorized()."""
    offenders = []
    for py in SRC.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        if any(m in text for m in PRIVATE_ORDER_MARKERS) and "require_authorized(" not in text:
            offenders.append(str(py.relative_to(SRC)))
    assert offenders == []


def test_report_is_reproducible():
    trades = json.loads((REPORTS / "of2_training_of_trades_aa853e1.json").read_text())
    committed = json.loads((REPORTS / "target_50usd_of2_training.json").read_text())
    assert target.build_report(trades) == committed
    assert committed["trades"]["n"] == 56
    assert committed["inputs"]["source"]["sha256"].startswith("91eda094")
    assert committed["verdict"] == "TARGET NOT PROVEN"
