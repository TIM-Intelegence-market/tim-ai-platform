"""Tests for V2.8 paper trading (src/tim_v2/paper)."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest

from src.tim_v2.paper import (
    AdapterConfig,
    Bar,
    CostModel,
    FakeExecutionAdapter,
    KillLimits,
    KillSwitch,
    OrderRequest,
    OrderStatus,
    OrderType,
    Side,
    reconcile,
)
from src.tim_v2.paper.isolation import scan
from src.tim_v2.paper.runner import replay

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
NO_COSTS = CostModel(taker_fee_bps=D(0), maker_fee_bps=D(0), slippage_bps=D(0), stop_extra_slippage_bps=D(0))


def t(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def bar(minute: int, o, h, l, c, symbol="BTCUSDT", funding=None) -> Bar:
    return Bar(symbol, t(minute), D(str(o)), D(str(h)), D(str(l)), D(str(c)),
               D(str(funding)) if funding is not None else None)


def adapter(costs: CostModel = NO_COSTS, equity="100000", kill: KillSwitch | None = None) -> FakeExecutionAdapter:
    a = FakeExecutionAdapter(AdapterConfig(initial_equity=D(equity), costs=costs), kill)
    a.on_bar(bar(0, 100, 100, 100, 100))  # mark price 100
    return a


def buy(cid="o1", qty="1", **kw) -> OrderRequest:
    return OrderRequest(cid, "BTCUSDT", Side.BUY, D(qty), **kw)


def sell(cid="s1", qty="1", **kw) -> OrderRequest:
    return OrderRequest(cid, "BTCUSDT", Side.SELL, D(qty), **kw)


# --------------------------------------------------------------------------- fills


def test_market_fills_at_next_open_with_costs():
    a = adapter(CostModel())  # taker 6 bp, slippage 3 bp
    a.submit(buy(), t(1))
    fills = a.on_bar(bar(1, 110, 112, 108, 111))
    assert len(fills) == 1
    f = fills[0]
    assert f.reference_price == D(110)
    assert f.price == D(110) * (1 + D(3) / D(10000))
    assert f.fee == f.price * D(6) / D(10000)
    assert a.positions["BTCUSDT"].quantity == D(1)
    assert reconcile(a, t(1)).ok


def test_no_look_ahead_order_after_bar_open_waits_for_next_bar():
    a = adapter()
    a.submit(buy(), t(1) + timedelta(seconds=1))
    assert a.on_bar(bar(1, 110, 112, 108, 111)) == []
    assert len(a.on_bar(bar(2, 120, 121, 119, 120))) == 1
    assert a.fills[0].price == D(120)


def test_limit_maker_fill_gap_and_miss():
    a = adapter(CostModel())
    a.submit(buy("l1", order_type=OrderType.LIMIT, price=D(95)), t(1))
    assert a.on_bar(bar(1, 100, 101, 96, 98)) == []  # not touched
    f = a.on_bar(bar(2, 98, 99, 94, 97))[0]  # trades through 95
    assert (f.price, f.liquidity.value) == (D(95), "MAKER")
    a.submit(buy("l2", order_type=OrderType.LIMIT, price=D(95)), t(3))
    f2 = a.on_bar(bar(3, 90, 92, 89, 91))[0]  # gap below the limit: taker at the open
    assert f2.liquidity.value == "TAKER" and f2.reference_price == D(90)


def test_stop_entry_gap_uses_worse_open_and_extra_slippage():
    a = adapter(CostModel(slippage_bps=D(3), stop_extra_slippage_bps=D(5)))
    a.submit(buy("st", order_type=OrderType.STOP, price=D(105)), t(1))
    f = a.on_bar(bar(1, 107, 110, 106, 109))[0]
    assert f.reference_price == D(107)
    assert f.price == D(107) * (1 + D(8) / D(10000))


def test_stop_loss_wins_when_both_brackets_hit_in_same_bar():
    a = adapter()
    a.submit(buy(stop_loss=D(95), take_profit=D(110)), t(1))
    a.on_bar(bar(1, 100, 100, 100, 100))
    fills = a.on_bar(bar(2, 100, 111, 94, 105))
    assert [f.kind for f in fills] == ["STOP_LOSS"]
    assert a.positions["BTCUSDT"].quantity == 0
    assert a.cash == D(100000) - D(5)
    assert reconcile(a, t(2)).ok


def test_take_profit_maker_and_gap():
    a = adapter()
    a.submit(buy(take_profit=D(110)), t(1))
    a.on_bar(bar(1, 100, 100, 100, 100))
    f = a.on_bar(bar(2, 112, 113, 111, 112))[0]
    assert f.kind == "TAKE_PROFIT" and f.reference_price == D(112)  # gapped above target


def test_flip_realizes_closed_part_and_reopens_at_fill_price():
    a = adapter()
    a.submit(buy(qty="2"), t(1))
    a.on_bar(bar(1, 100, 100, 100, 100))
    a.submit(sell(qty="3"), t(2))
    a.on_bar(bar(2, 110, 110, 110, 110))
    pos = a.positions["BTCUSDT"]
    assert pos.quantity == D(-1) and pos.entry_price == D(110)
    assert a.cash == D(100000) + D(20)
    assert reconcile(a, t(2)).ok


def test_funding_long_pays_positive_rate():
    a = adapter()
    a.submit(buy(), t(1))
    a.on_bar(bar(1, 100, 100, 100, 100, funding="0.001"))
    assert a.cash == D(100000) - D("0.1")
    assert reconcile(a, t(1)).ok


# --------------------------------------------------------------------------- validation


@pytest.mark.parametrize("req,reason", [
    (buy(qty="0"), "quantity_must_be_positive"),
    (OrderRequest("x", "DOGEUSDT", Side.BUY, D(1)), "symbol_not_allowed"),
    (buy(order_type=OrderType.LIMIT), "price_required"),
    (sell(reduce_only=True), "reduce_only_without_position"),
    (buy(qty="20000"), "leverage_limit"),
    (buy(stop_loss=D(101)), "stop_loss_on_wrong_side"),
    (buy(take_profit=D(99)), "take_profit_on_wrong_side"),
])
def test_rejects(req, reason):
    order = adapter().submit(req, t(1))
    assert order.status is OrderStatus.REJECTED and order.reason == reason


def test_no_mark_price_rejects_market_order():
    a = FakeExecutionAdapter(AdapterConfig(costs=NO_COSTS))
    assert a.submit(buy(), t(0)).reason == "no_mark_price"


def test_client_id_is_idempotent_and_conflicts_rejected():
    a = adapter()
    first = a.submit(buy(), t(1))
    assert a.submit(buy(), t(1)) is first
    assert a.submit(buy(qty="2"), t(1)).reason == "duplicate_client_id"
    assert a.metrics.orders_submitted == 1


def test_reduce_only_is_clipped_to_position():
    a = adapter()
    a.submit(buy(), t(1))
    a.on_bar(bar(1, 100, 100, 100, 100))
    a.submit(sell(qty="5", reduce_only=True), t(2))
    a.on_bar(bar(2, 101, 101, 101, 101))
    assert a.positions["BTCUSDT"].quantity == 0 and a.fills[-1].quantity == D(1)


def test_bars_must_increase():
    a = adapter()
    with pytest.raises(ValueError):
        a.on_bar(bar(0, 100, 100, 100, 100))


def test_leverage_cap_cannot_exceed_repo_limit():
    with pytest.raises(ValueError):
        AdapterConfig(max_leverage=D(11))


def test_live_execution_cannot_be_enabled():
    a = adapter()
    assert a.live_execution is False
    with pytest.raises(AttributeError):
        a.live_execution = True


# --------------------------------------------------------------------------- kill switch


def test_manual_kill_cancels_openers_blocks_new_and_allows_flatten():
    a = adapter()
    a.submit(buy("pos"), t(1))
    a.on_bar(bar(1, 100, 100, 100, 100))
    a.submit(buy("pending", order_type=OrderType.LIMIT, price=D(90)), t(2))
    a.engage_kill(t(2), "test")
    assert a.orders["pending"].status is OrderStatus.CANCELLED
    assert a.submit(buy("new"), t(2)).reason == "kill_switch_engaged"
    assert a.flatten("BTCUSDT", t(2)).status is OrderStatus.NEW
    a.on_bar(bar(2, 101, 101, 101, 101))
    assert a.positions["BTCUSDT"].quantity == 0
    assert a.metrics.kill_events == 1


def test_kill_file_engages_and_blocks_release_until_removed(tmp_path):
    kill_file = tmp_path / "KILL"
    a = adapter(kill=KillSwitch(kill_file=kill_file))
    kill_file.write_text("stop")
    a.on_bar(bar(1, 100, 100, 100, 100))
    assert a.kill.engaged and a.kill.events[0].source == "FILE"
    with pytest.raises(RuntimeError):
        a.kill.release(t(2), "Uzi")
    kill_file.unlink()
    with pytest.raises(ValueError):
        a.kill.release(t(2), " ")
    a.kill.release(t(2), "Uzi")
    assert not a.kill.engaged


def test_daily_loss_limit_engages():
    a = adapter(equity="1000", kill=KillSwitch(KillLimits(max_daily_loss_fraction=D("0.03"))))
    a.submit(buy(qty="5"), t(1))
    a.on_bar(bar(1, 100, 100, 100, 100))
    a.on_bar(bar(2, 100, 100, 93, 93))  # -35 USD = 3.5 %
    assert a.kill.engaged and a.kill.events[0].source == "DAILY_LOSS"


def test_consecutive_rejects_engage():
    a = adapter(kill=KillSwitch(KillLimits(max_consecutive_rejects=3)))
    for i in range(3):
        a.submit(buy(f"bad{i}", qty="0"), t(1))
    assert a.kill.engaged and a.kill.events[0].source == "REJECTS"


# --------------------------------------------------------------------------- reconciliation


def test_reconciliation_detects_tampering_and_kills():
    a = adapter()
    a.submit(buy(), t(1))
    a.on_bar(bar(1, 100, 100, 100, 100))
    a.positions["BTCUSDT"].quantity = D(2)  # state no longer matches the fills
    report = reconcile(a, t(1))
    assert not report.ok and "quantity" in report.differences[0]
    assert a.kill.engaged and a.kill.events[-1].source == "RECONCILIATION"


def test_replay_runner_end_to_end():
    bars = [bar(i, 100 + i, 101 + i, 99 + i, 100 + i) for i in range(0, 6)]
    orders = [
        {"at": t(1).isoformat(), "client_id": "a", "symbol": "BTCUSDT", "side": "BUY", "quantity": "1",
         "stop_loss": "90", "take_profit": "104"},
        {"at": t(4).isoformat(), "action": "kill", "reason": "drill"},
        {"at": t(4).isoformat(), "client_id": "b", "symbol": "BTCUSDT", "side": "BUY", "quantity": "1"},
    ]
    result = replay(bars, orders, AdapterConfig(initial_equity=D(10000)))
    events = [r["event"] for r in result.journal]
    assert "FILL" in events and "KILL" in events
    assert result.reconciliation_failures == 0
    assert result.adapter.orders["b"].reason == "kill_switch_engaged"
    assert result.adapter.fills[-1].kind == "TAKE_PROFIT"


# --------------------------------------------------------------------------- isolation proof


def test_static_isolation_scan_passes():
    report = scan()
    assert report.ok, report.violations
    assert "adapter.py" in report.files


@pytest.mark.parametrize("bad", [
    "import socket\n",
    "import requests\n",
    "from src.research_lab.bitunix import client\n",
    "import src.orderflow_scenario\n",
    "URL = 'https:' '//api.example'\nX = 'wss://x'\n",
    "import os\nos.system('curl x')\n",
    "__import__('socket')\n",
])
def test_isolation_scan_catches_violations(tmp_path, bad):
    (tmp_path / "evil.py").write_text(bad)
    assert not scan(tmp_path).ok


def test_runtime_replay_with_network_disabled(tmp_path):
    bars = tmp_path / "bars.jsonl"
    orders = tmp_path / "orders.jsonl"
    bars.write_text("\n".join(json.dumps({"symbol": "BTCUSDT", "opened_at": t(i).isoformat(), "open": "100",
                                          "high": "101", "low": "99", "close": "100"}) for i in range(5)))
    orders.write_text(json.dumps({"at": t(1).isoformat(), "client_id": "a", "symbol": "BTCUSDT", "side": "BUY",
                                  "quantity": "0.5"}))
    script = textwrap.dedent(f"""
        import socket, sys
        def blocked(*a, **k):
            raise RuntimeError("network blocked in paper test")
        socket.socket = blocked
        socket.create_connection = blocked
        before = set(sys.modules)
        sys.path.insert(0, {str(ROOT)!r})
        from src.tim_v2.paper.__main__ import main
        rc = main(["replay", "--bars", {str(bars)!r}, "--orders", {str(orders)!r}, "--out", {str(tmp_path / "out")!r}])
        loaded = set(sys.modules) - before
        bad = sorted(m for m in loaded if m.split(".")[0] in {{"ssl", "http", "urllib", "requests", "httpx",
                     "aiohttp", "websockets", "ccxt", "asyncpg", "psycopg", "psycopg2", "subprocess"}})
        print(rc, bad)
        sys.exit(rc if not bad else 9)
    """)
    proc = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True, cwd=tmp_path,
                          timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert summary["live_execution"] is False and summary["isolation"]["ok"] is True
    assert summary["reconciliation_failures"] == 0
