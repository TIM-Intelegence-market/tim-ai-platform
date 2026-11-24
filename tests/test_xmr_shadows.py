"""XMR Paket 3: Live-Orderflow-Lage from the perp batches, the three shadows on the XMR plans, BTC untouched."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.dashboard import perp_flow, xmr_shadows
from src.dashboard import plan_journal as pj
from src.orderflow import xmr_live

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def _rows(start_id: int, start: datetime, count: int, price: float = 340.0, sell_every: int = 3) -> list[dict]:
    """aggTrade rows: two buys per sell, one every second."""
    return [{"a": start_id + i, "p": str(price + (i % 5) * 0.1), "q": "1.5", "T": int((start + timedelta(seconds=i)).timestamp() * 1000),
             "m": i % sell_every == 0, "f": start_id + i, "l": start_id + i} for i in range(count)]


def test_rows_become_trades_and_bad_rows_drop_out() -> None:
    rows = _rows(10, NOW, 3) + [{"a": 99, "p": "0", "q": "1", "T": 0, "m": False}, {"a": "x"}]
    trades = xmr_live.trades_from_rows("XMRUSDT", rows)
    assert [t.trade_id for t in trades] == [10, 11, 12]
    assert trades[0].buyer_is_maker is True and trades[1].buyer_is_maker is False
    assert trades[0].event_time == NOW


def test_xmr_lage_describes_buyers_and_ignores_other_symbols_and_replays() -> None:
    live = xmr_live.XmrOrderflowLive(tick=0.1)
    rows = _rows(1, NOW - timedelta(minutes=10), 600)
    live.on_rows("BTCUSDT", rows)  # not XMR: ignored
    assert live.tracker.ingested == 0
    live.on_rows("XMRUSDT", rows)
    live.on_rows("XMRUSDT", rows)  # the same batch again (overlap after a restart): counted once
    assert live.tracker.ingested == 600
    state = live.snapshot(NOW, None)
    assert state["symbol"] == "XMRUSDT" and not state["stale"] and 340 <= state["price"] < 341
    assert state["windows"]["5m"]["delta"] > 0  # two buys per sell
    assert "Perp" in state["source"]


def test_perp_flow_feeds_listeners_and_a_broken_listener_cannot_stop_it(tmp_path: Path) -> None:
    seen: list[tuple[str, int]] = []
    rows = _rows(100, NOW - timedelta(minutes=1), 5)

    def fetch(path: str, params) -> list:
        if "fromId" in params:
            return [r for r in rows if r["a"] >= int(params["fromId"])]
        return rows[:1]

    flow = perp_flow.PerpFlow(tmp_path, fetch=fetch, clock=lambda: NOW.timestamp(), symbol="XMRUSDT")
    flow.listeners.append(lambda symbol, batch: seen.append((symbol, len(batch))))
    flow.listeners.append(lambda symbol, batch: 1 / 0)
    assert flow.step() == 5
    assert seen == [("XMRUSDT", 5)] and flow.next_id == 105  # the record went on despite the failing reader
    btc = perp_flow.PerpFlow(tmp_path / "btc", fetch=fetch, clock=lambda: NOW.timestamp(), symbol="BTCUSDT")
    assert btc.listeners == []  # BTC has no reader: unchanged


def test_for_symbol_drops_a_lage_of_another_symbol() -> None:
    assert xmr_live.for_symbol({"symbol": "BTCUSDT", "price": 1}) is None
    assert xmr_live.for_symbol(None) is None
    assert xmr_live.for_symbol({"symbol": "XMRUSDT", "price": 340})["price"] == 340


def _journals(tmp_path: Path) -> dict[str, Path]:
    from tests.test_xmr_journal import _xmr_series

    start = NOW - timedelta(minutes=30 * 90)
    paths = {"15m": tmp_path / "xmr_15m.json", "1h": tmp_path / "xmr_1h.json"}
    journal = pj.update(paths["15m"], _xmr_series(start), NOW, market_type="USDM")
    assert journal["entries"]
    return paths


def _own(tmp_path: Path) -> dict[str, Path]:
    return {k: tmp_path / f"{k}_xmr.json" for k in xmr_shadows.PATHS}


def test_shadows_follow_the_xmr_plans_in_their_own_files(tmp_path: Path, monkeypatch) -> None:
    from tests.test_xmr_journal import _xmr_series

    from src.dashboard import chart_verdict, orderflow_shadow

    journals, own = _journals(tmp_path), _own(tmp_path)
    # the shadows only take plans created after they started: start them before the journal's plans
    for name, module in (("orderflow", orderflow_shadow), ("verdict", chart_verdict)):
        own[name].write_text(json.dumps({"schema": module.SCHEMA, "started_at": "2020-01-01T00:00:00Z", "plans": {},
                                         **({"ruleset": chart_verdict.RULESET} if name == "verdict" else {}),
                                         "sources": [p.name for p in journals.values()]}), encoding="utf-8")
    lage = xmr_live.XmrOrderflowLive(tick=0.1)
    lage.on_rows("XMRUSDT", _rows(1, NOW - timedelta(minutes=10), 600))
    status = xmr_shadows.update(_xmr_series(NOW - timedelta(minutes=30 * 90)), lage.snapshot(NOW, None), None, NOW,
                                journal_paths=journals, paths=own)
    assert status["lage"] is True
    assert status["orderflow"]["plans"] > 0 and status["verdict"]["plans"] > 0
    shadow = json.loads(own["orderflow"].read_text(encoding="utf-8"))
    assert all(p["journal_file"].startswith("xmr_") for p in shadow["plans"].values())
    counts = xmr_shadows.counts(own)
    assert counts["orderflow"] > 0 and counts["verdict"] > 0 and counts["opinion"] is None


def test_btc_lage_never_reaches_an_xmr_shadow(tmp_path: Path) -> None:
    journals, own = _journals(tmp_path), _own(tmp_path)
    status = xmr_shadows.update({}, {"symbol": "BTCUSDT", "price": 90_000.0, "as_of": NOW.isoformat()}, None, NOW,
                                journal_paths=journals, paths=own)
    assert status["lage"] is False


def test_shadows_refuse_btc_files(tmp_path: Path) -> None:
    from src.dashboard.orderflow_shadow import DEFAULT_PATH as BTC_SHADOW
    from src.dashboard.perp_journal import PATHS as BTC_PERP

    with pytest.raises(ValueError, match="BTC shadow"):
        xmr_shadows.update({}, None, None, NOW, journal_paths=_journals(tmp_path), paths={"orderflow": BTC_SHADOW})
    with pytest.raises(ValueError, match="BTC perp journals"):
        xmr_shadows.update({}, None, None, NOW, journal_paths=BTC_PERP, paths=_own(tmp_path))
    assert set(xmr_shadows.PATHS.values()).isdisjoint({BTC_SHADOW})


def test_opinion_asks_with_the_xmr_symbol(tmp_path: Path) -> None:
    from src.dashboard import plan_opinion

    journals, own = _journals(tmp_path), _own(tmp_path)
    own["opinion"].write_text(json.dumps({"schema": plan_opinion.SCHEMA, "started_at": "2020-01-01T00:00:00Z", "plans": {},
                                          "sources": [p.name for p in journals.values()]}), encoding="utf-8")
    prompts: list[str] = []

    def ask(text: str) -> dict:
        prompts.append(text)
        return {"ok": True, "answer": "DAFÜR: a\nDAGEGEN: b\nURTEIL: c", "seconds": 1}

    latest = max(pj.load_view(journals["15m"])["entries"], key=lambda e: e["created_at"])
    state = xmr_shadows.update_opinion(None, datetime.fromisoformat(latest["created_at"].replace("Z", "+00:00")) + timedelta(minutes=1),
                                       ask=ask, journal_paths=journals, paths=own)
    assert prompts and "XMRUSDT" in prompts[0] and "BTCUSDT" not in prompts[0]
    assert any(p.get("opinion") for p in state["plans"].values())
