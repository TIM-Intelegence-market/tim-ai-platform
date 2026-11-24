"""Paket E (#372): point-in-time Lage for Orderflow-Schatten, Zweitmeinung and Chart-Urteil, BTC and XMR."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from src.dashboard import chart_verdict as cv
from src.dashboard import orderflow_shadow as shadow
from src.dashboard import pit_lage as pit
from src.dashboard import plan_opinion
from tests.test_orderflow_shadow import T0, lage, plan, write_journal

H11 = T0 - timedelta(hours=1)  # 11:00 UTC
H1115 = H11 + timedelta(minutes=15)


@pytest.fixture(autouse=True)
def _fresh_history():
    pit.reset()
    yield
    pit.reset()


def test_codex_case_plan_11_fill_1115_with_only_a_12_lage_is_unknown():
    pit.observe(lage("auf", at=T0), T0)
    assert pit.lage_at("BTCUSDT", H11) == (None, pit.UNKNOWN_NO_HISTORY)
    assert pit.lage_at("BTCUSDT", H1115) == (None, pit.UNKNOWN_NO_HISTORY)


def test_one_sided_no_lage_after_the_moment_and_max_age():
    before = H11 - timedelta(seconds=50)
    after = H11 + timedelta(seconds=5)
    pit.observe(lage("ab", at=before), before + timedelta(seconds=10))
    pit.observe(lage("auf", at=after), after + timedelta(seconds=1))
    known, status = pit.lage_at("BTCUSDT", H11)
    assert status == pit.OK and known["as_of"] == before.isoformat() and known["wave"]["direction"] == "ab"
    assert pit.lage_at("BTCUSDT", H11 + pit.MAX_AGE + timedelta(minutes=1)) == (None, pit.UNKNOWN_TOO_OLD)


def test_late_availability_and_trades_after_the_moment_do_not_count():
    taken = H11 - timedelta(seconds=30)
    pit.observe(lage("auf", at=taken), H11 + timedelta(minutes=2))  # first seen two minutes after the plan
    assert pit.lage_at("BTCUSDT", H11) == (None, pit.UNKNOWN_NO_HISTORY)
    pit.reset()
    pit.observe({**lage("auf", at=taken), "last_trade_at": (H11 + timedelta(seconds=1)).isoformat()}, taken)
    assert pit.lage_at("BTCUSDT", H11) == (None, pit.UNKNOWN_NO_HISTORY)


def test_stale_lage_and_bad_times_are_unknown():
    pit.observe({**lage("auf", at=H11), "stale": True}, H11)
    assert pit.lage_at("BTCUSDT", H11) == (None, pit.UNKNOWN_STALE)
    assert pit.lage_at("BTCUSDT", "kein Datum") == (None, pit.UNKNOWN_NO_TIME)
    assert pit.lage_at("BTCUSDT", "2026-11-08T11:00:00") == (None, pit.UNKNOWN_NO_TIME)  # no time zone


def test_xmr_and_btc_histories_are_apart():
    pit.observe({**lage("ab", at=H11), "symbol": "XMRUSDT"}, H11)
    assert pit.lage_at("BTCUSDT", H11)[1] == pit.UNKNOWN_NO_HISTORY
    assert pit.lage_at("XMRUSDT", H11)[0]["symbol"] == "XMRUSDT"


def test_store_until_cuts_buckets_complete_days_and_bubbles():
    t = int(H11.timestamp())
    store = {"bucket_seconds": 300, "tick": 1.0,
             "days": {"2026-11-07": [[t - 86400, 1.0, 1.0, 1.0]], "2026-11-08": [[t - 600, 1.0, 1.0, 2.0], [t - 120, 1.0, 5.0, 0.0], [t + 60, 1.0, 9.0, 9.0]]},
             "complete": {"2026-11-07": t - 3600, "2026-11-08": t + 7200},
             "bubbles": {"2026-11-08": [[(t - 300) * 1000, 1.0, 2.0, 1], [(t + 30) * 1000, 1.0, 3.0, -1]]}}
    cut = pit.store_until(store, H11)
    assert cut["days"]["2026-11-08"] == [[t - 600, 1.0, 1.0, 2.0]]  # running bucket and later ones gone
    assert cut["complete"] == {"2026-11-07": t - 3600} and cut["bubbles"]["2026-11-08"] == [[(t - 300) * 1000, 1.0, 2.0, 1]]
    assert store["days"]["2026-11-08"][-1][0] == t + 60  # the input is not changed
    assert pit.store_until(None, H11) is None


def test_shadow_after_restart_notes_unknown_and_keeps_old_records(tmp_path):
    journal, path = tmp_path / "tim_plan_journal_short.json", tmp_path / "shadow.json"
    legacy = {"id": "old", "created_at": (H11 - timedelta(hours=1)).isoformat(), "lage_at_plan": {"price": 1.0},
              "gate_at_plan": shadow.GEGEN, "journal": {"status": "CLOSED", "net_r": -1.0}}
    path.write_text(json.dumps({"schema": shadow.SCHEMA, "started_at": (H11 - timedelta(hours=2)).isoformat(), "plans": {"old": legacy}}))
    shadow.update(path, [journal], None, now=H11 - timedelta(minutes=1))   # pit/1 starts its own file before the plan
    pit.reset()                                                              # restart between 11:00 and 12:00
    write_journal(journal, plan("FILLED", created_at=H11.isoformat(), filled_at=H1115.isoformat(), fill_price=75000.0))
    state = shadow.update(path, [journal], lage("ab", strength=3, at=T0), now=T0)  # first run after a restart at 12:00
    record = state["plans"]["p1"]
    assert record["pit"] == pit.PIT_VERSION and record["lage_at_plan"] is None and record["lage_at_fill"] is None
    assert record["lage_at_plan_status"] == record["lage_at_fill_status"] == pit.UNKNOWN_NO_HISTORY
    assert record["gate_at_plan"] == record["gate_at_fill"] == shadow.NEUTRAL
    before = path.read_bytes()
    assert "old" not in state["plans"] and json.loads(path.read_text())["plans"]["old"] == legacy  # old file untouched
    assert state["previous_version"] == {"file": "shadow.json", "plans": 1, "untouched": True,
                                         "note": "Datei der früheren Version, wird nicht mehr geschrieben"}
    assert state["summary"]["plans"] == 1 and state["summary"]["legacy"]["plans"] == 0
    shadow.update(path, [journal], lage("ab", strength=3, at=T0), now=T0 + timedelta(minutes=1))
    assert path.read_bytes() == before
    assert record["of_exit"]["at"] == T0.isoformat()  # live exit: Lage of 12:00 is after the fill, allowed


def test_shadow_live_exit_never_uses_a_lage_from_before_the_fill(tmp_path):
    journal, path = tmp_path / "tim_plan_journal_short.json", tmp_path / "shadow.json"
    shadow.update(path, [journal], None, now=H11 - timedelta(minutes=1))
    write_journal(journal, plan("FILLED", created_at=H11.isoformat(), filled_at=H1115.isoformat(), fill_price=75000.0))
    early = H1115 - timedelta(minutes=1)
    state = shadow.update(path, [journal], lage("ab", strength=3, at=early), now=H1115 + timedelta(seconds=10))
    assert "of_exit" not in state["plans"]["p1"]


def test_shadow_takes_the_lage_known_at_plan_and_fill(tmp_path):
    journal, path = tmp_path / "tim_plan_journal_short.json", tmp_path / "shadow.json"
    shadow.update(path, [journal], lage("ab", at=H11 - timedelta(seconds=40)), now=H11 - timedelta(seconds=30))
    write_journal(journal, plan("OPEN", created_at=H11.isoformat()))
    state = shadow.update(path, [journal], lage("auf", at=H11 + timedelta(seconds=50)), now=H11 + timedelta(minutes=1))
    assert state["plans"]["p1"]["gate_at_plan"] == shadow.GEGEN  # the 10:59 wave, not the 11:00:50 one
    assert state["plans"]["p1"]["lage_at_plan_status"] == pit.OK


def test_xmr_shadow_uses_its_own_history(tmp_path):
    journal, path = tmp_path / "tim_plan_journal_xmr_15m.json", tmp_path / "xmr.json"
    xmr = {**lage("auf", at=H11 - timedelta(seconds=30)), "symbol": "XMRUSDT"}
    shadow.update(path, [journal], lage("ab", at=H11 - timedelta(seconds=30)), now=H11 - timedelta(seconds=20))  # BTC
    shadow.update(path, [journal], xmr, now=H11 - timedelta(seconds=20), symbol="XMRUSDT")
    write_journal(journal, plan("OPEN", created_at=H11.isoformat()))
    state = shadow.update(path, [journal], xmr, now=H11 + timedelta(seconds=30), symbol="XMRUSDT")
    assert state["plans"]["p1"]["symbol"] == "XMRUSDT" and state["plans"]["p1"]["gate_at_plan"] == shadow.BESTAETIGT


def test_chart_verdict_orderflow_view_is_one_sided():
    assert cv.orderflow_view(lage("auf", at=H11 + timedelta(seconds=5)), H11) is None
    assert cv.orderflow_view(lage("auf", at=H11 - timedelta(seconds=5)), H11) is not None
    assert cv.orderflow_view(lage("auf", at=H11 - cv.LAGE_MAX_AGE - timedelta(seconds=1)), H11) is None


def test_plan_opinion_prompt_says_unknown_without_a_lage_of_that_time(tmp_path):
    journal, path = tmp_path / "short.json", tmp_path / "opinion.json"
    plan_opinion.update(path, [journal], None, now=H11 - timedelta(minutes=1), ask=lambda text: {"ok": False})
    write_journal(journal, plan("OPEN", created_at=H11.isoformat()))
    asked: list[str] = []
    state = plan_opinion.update(path, [journal], lage("auf", at=H11 + timedelta(minutes=2)), now=H11 + timedelta(minutes=3),
                                ask=lambda text: asked.append(text) or {"ok": True, "answer": "URTEIL: NEUTRAL"})
    record = state["plans"]["p1"]
    assert record["lage_at_plan"] is None and record["lage_at_plan_status"] == pit.UNKNOWN_NO_HISTORY
    assert "Orderflow zur Planzeit: unbekannt" in asked[0]


def test_store_until_cannot_see_a_backfill_and_says_so():
    """Mission 05: rows carry no arrival time; a bucket backfilled after t still counts, so the cut is UNVERIFIED."""
    t = int(H11.timestamp())
    early = {"bucket_seconds": 300, "updated_at": (H11 - timedelta(seconds=5)).isoformat(),
             "days": {"2026-11-08": [[t - 600, 1.0, 1.0, 2.0]]}}
    assert pit.store_until(early, H11)["rows_arrival"] == "OK"        # written before t: nothing can be later
    backfilled = {**early, "updated_at": (H11 + timedelta(hours=1)).isoformat(),
                  "days": {"2026-11-08": [[t - 600, 1.0, 1.0, 2.0], [t - 900, 1.0, 7.0, 0.0]]}}  # gap filled at 12:00
    cut = pit.store_until(backfilled, H11)
    assert [t - 900, 1.0, 7.0, 0.0] in cut["days"]["2026-11-08"]       # the backfilled bucket is still in ...
    assert cut["rows_arrival"] == "UNVERIFIED"                         # ... and the cut does not claim otherwise
    assert pit.store_until({**early, "updated_at": None}, H11)["rows_arrival"] == "UNVERIFIED"


def test_shadow_summary_keeps_plans_without_a_lage_apart(tmp_path):
    journal, path = tmp_path / "tim_plan_journal_short.json", tmp_path / "shadow.json"
    shadow.update(path, [journal], None, now=H11 - timedelta(minutes=1))
    pit.reset()                                                         # the runtime restarts before the plan
    write_journal(journal, plan("CLOSED", created_at=H11.isoformat(), filled_at=H1115.isoformat(), fill_price=75000.0, net_r=1.0))
    state = shadow.update(path, [journal], lage("ab", strength=3, at=T0), now=T0)   # restart: no Lage of 11:00
    assert state["plans"]["p1"]["gate_at_plan"] == shadow.NEUTRAL
    assert state["summary"]["by_gate"] == {shadow.OHNE_LAGE: {"n": 1, "sum_net_r": 1.0}}
