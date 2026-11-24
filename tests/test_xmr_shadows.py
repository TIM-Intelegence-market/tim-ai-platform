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


@pytest.mark.parametrize("flag", ["false", "true", None, 0, 1, "", []])
def test_a_flag_that_is_not_a_bool_never_becomes_a_side(flag) -> None:
    """Codex review PR #369: bool("false") is True; such rows are dropped and counted, never booked as a buy or sell."""
    rejected: dict[str, int] = {}
    row = {**_rows(1, NOW, 1)[0], "m": flag}
    assert xmr_live.trades_from_rows("XMRUSDT", [row], rejected) == [] and rejected == {"flag": 1}
    missing = {k: v for k, v in _rows(2, NOW, 1)[0].items() if k != "m"}
    assert xmr_live.trades_from_rows("XMRUSDT", [missing], rejected) == [] and rejected == {"flag": 2}


def test_invalid_flags_are_counted_on_the_lage_and_leave_the_delta_alone() -> None:
    live = xmr_live.XmrOrderflowLive(tick=0.1)
    good = _rows(1, NOW - timedelta(minutes=5), 300)
    bad = [{**r, "a": 1000 + i, "m": "false"} for i, r in enumerate(_rows(1, NOW - timedelta(minutes=5), 50))]
    live.on_rows("XMRUSDT", good + bad)
    state = live.snapshot(NOW, None)
    assert live.tracker.ingested == 300 and state["rejected_rows"] == {"flag": 50}


def _lage_at(live: xmr_live.XmrOrderflowLive, moments: list[datetime]) -> None:
    for moment in moments:
        live.snapshot(moment, None)


def test_lage_at_never_looks_ahead_and_never_reaches_far_back() -> None:
    live = xmr_live.XmrOrderflowLive(tick=0.1)
    live.on_rows("XMRUSDT", _rows(1, NOW - timedelta(minutes=10), 600))
    t = NOW - timedelta(seconds=30)
    _lage_at(live, [t, t + timedelta(seconds=10), t + timedelta(seconds=20), NOW])
    assert live.lage_at(t) == live._history[0][1]  # taken exactly at the moment: allowed
    assert live.lage_at(t + timedelta(seconds=15)) == live._history[1][1]  # the latest one at or before
    assert live.lage_at(t - timedelta(seconds=1)) is None  # only later snapshots: none, never a look-ahead
    assert live.lage_at(NOW + xmr_live.LOOKBACK) == live._history[-1][1]  # boundary: exactly LOOKBACK old
    assert live.lage_at(NOW + xmr_live.LOOKBACK + timedelta(seconds=1)) is None  # older: UNKNOWN
    for moment in (t, NOW):
        found = live.lage_at(moment)
        assert found and datetime.fromisoformat(found["as_of"]) <= moment


def test_lage_at_keeps_no_stale_lage_and_forgets_after_history() -> None:
    live = xmr_live.XmrOrderflowLive(tick=0.1)
    live.snapshot(NOW, None)  # no trades yet: stale, not kept
    assert live.lage_at(NOW) is None
    live.on_rows("XMRUSDT", _rows(1, NOW - timedelta(minutes=10), 600))
    live.snapshot(NOW, None)
    live.on_rows("XMRUSDT", _rows(5000, NOW + xmr_live.HISTORY, 30))
    live.snapshot(NOW + xmr_live.HISTORY + timedelta(seconds=31), None)
    assert len(live._history) == 1  # the first one is older than HISTORY and dropped


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
    from src.dashboard import chart_verdict, orderflow_shadow
    from tests.test_xmr_journal import _xmr_series

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
    state = xmr_shadows.update_opinion(datetime.fromisoformat(latest["created_at"].replace("Z", "+00:00")) + timedelta(minutes=1),
                                       ask=ask, journal_paths=journals, paths=own)
    assert prompts and "XMRUSDT" in prompts[0] and "BTCUSDT" not in prompts[0]
    assert any(p.get("opinion") for p in state["plans"].values())


def test_run_attaches_the_reader_to_xmr_only(tmp_path: Path) -> None:
    import asyncio
    import threading

    flows = [perp_flow.PerpFlow(tmp_path / s, fetch=lambda *_: [], clock=lambda: NOW.timestamp(), symbol=s) for s in ("BTCUSDT", "XMRUSDT")]
    reader = lambda symbol, rows: None

    class State:
        lock = threading.Lock()

    stop = asyncio.Event()
    stop.set()  # attach, then end at once
    asyncio.run(perp_flow.run(State(), stop, flows=flows, listeners={"XMRUSDT": reader}))
    assert flows[0].listeners == [] and flows[1].listeners == [reader]


PLAN, FILL, LATE = NOW - timedelta(hours=1), NOW - timedelta(minutes=45), NOW  # Codex: plan 11:00, fill 11:15, Lage 12:00


def _lage(moment: datetime, direction: str = "auf") -> dict:
    return {"symbol": "XMRUSDT", "as_of": moment.isoformat(), "stale": False, "price": 340.0,
            "wave": {"direction": direction, "strength": 2, "phase": "läuft", "exhaustion": False}, "levels": []}


def _fake_journal(monkeypatch, filled: bool = True) -> list[Path]:
    entry = {"id": "x1", "timeframe": "15m", "direction": "LONG", "created_at": PLAN.isoformat(), "entry": 340.0,
             "stop": 335.0, "targets": [350.0], "status": "FILLED" if filled else "OPEN",
             "filled_at": FILL.isoformat() if filled else None, "fill_price": 340.0}
    monkeypatch.setattr(pj, "load_view", lambda path: {"entries": [entry]})
    return [Path("xmr_15m.json")]


def _started(path: Path, module, **extra) -> Path:
    path.write_text(json.dumps({"schema": module.SCHEMA, "started_at": "2020-01-01T00:00:00Z", "plans": {}, **extra}), encoding="utf-8")
    return path


def test_a_late_lage_never_stands_in_for_plan_or_fill(tmp_path: Path, monkeypatch) -> None:
    """Codex review PR #369 finding 1: the 12:00 Lage must not become the Lage at the 11:00 plan or the 11:15 fill."""
    from src.dashboard import orderflow_shadow

    journals = _fake_journal(monkeypatch)
    state = orderflow_shadow.update(_started(tmp_path / "of.json", orderflow_shadow), journals, _lage(LATE), LATE,
                                    lage_at=xmr_shadows._point_in_time(lambda moment: None))
    plan = state["plans"]["x1"]
    assert plan["lage_at_plan"] is None and plan["lage_at_fill"] is None  # UNKNOWN, not the later Lage
    assert plan["gate_at_plan"] == plan["gate_at_fill"] == orderflow_shadow.gate("LONG", None)


@pytest.mark.parametrize("offset, kept", [(timedelta(0), True), (-timedelta(seconds=10), True), (-xmr_live.LOOKBACK, True),
                                          (-xmr_live.LOOKBACK - timedelta(seconds=1), False), (timedelta(seconds=1), False)])
def test_plan_and_fill_get_only_a_lage_from_their_moment(tmp_path: Path, monkeypatch, offset: timedelta, kept: bool) -> None:
    """Lage taken at, shortly before (up to LOOKBACK), too long before or one second after the plan and the fill."""
    from src.dashboard import orderflow_shadow

    live = xmr_live.XmrOrderflowLive(tick=0.1)
    for moment in (PLAN, FILL):
        live.on_rows("XMRUSDT", _rows(int(moment.timestamp()), moment + offset - timedelta(minutes=5), 300))
        live.snapshot(moment + offset, None)
    state = orderflow_shadow.update(_started(tmp_path / "of.json", orderflow_shadow), _fake_journal(monkeypatch), _lage(LATE), LATE,
                                    lage_at=xmr_shadows._point_in_time(live.lage_at))
    plan = state["plans"]["x1"]
    for name, moment in (("plan", PLAN), ("fill", FILL)):
        view = plan[f"lage_at_{name}"]
        if kept:
            assert view and datetime.fromisoformat(view["as_of"]) <= moment and datetime.fromisoformat(view["as_of"]) == moment + offset
        else:
            assert view is None


def test_chart_verdict_and_opinion_take_the_lage_at_plan_time(tmp_path: Path, monkeypatch) -> None:
    from src.dashboard import chart_verdict, plan_opinion

    journals = _fake_journal(monkeypatch, filled=False)
    seen: list = []
    monkeypatch.setattr(chart_verdict, "chart_lage", lambda series, at, lage, trades: seen.append((at, lage)) or None)
    before = _lage(PLAN - timedelta(seconds=5))
    lookup = xmr_shadows._point_in_time(lambda moment: before if moment == PLAN else _lage(LATE))
    chart_verdict.update(_started(tmp_path / "v.json", chart_verdict, ruleset=chart_verdict.RULESET), journals, {}, None, LATE,
                         lage_at=lookup)
    assert seen == [(PLAN, before)]
    opinion = plan_opinion.update(_started(tmp_path / "o.json", plan_opinion), journals, None, PLAN + timedelta(minutes=1),
                                  ask=lambda text: {"ok": True, "answer": "URTEIL: c", "seconds": 1}, symbol="XMRUSDT", lage_at=lookup)
    assert opinion["plans"]["x1"]["lage_at_plan"]["as_of"] == before["as_of"]


def test_a_btc_lage_from_the_lookup_is_dropped(tmp_path: Path, monkeypatch) -> None:
    from src.dashboard import orderflow_shadow

    btc = {**_lage(PLAN), "symbol": "BTCUSDT"}
    state = orderflow_shadow.update(_started(tmp_path / "of.json", orderflow_shadow), _fake_journal(monkeypatch), None, LATE,
                                    lage_at=xmr_shadows._point_in_time(lambda moment: btc))
    assert state["plans"]["x1"]["lage_at_plan"] is None


def test_without_lage_at_the_shadows_keep_their_call_shape(tmp_path: Path, monkeypatch) -> None:
    """BTC passes no ``lage_at``: the BTC call works as before (its point-in-time fix is a separate package, #372)."""
    from src.dashboard import orderflow_shadow

    state = orderflow_shadow.update(_started(tmp_path / "of.json", orderflow_shadow), _fake_journal(monkeypatch), None, LATE)
    assert state["plans"]["x1"]["lage_at_plan"] is None
