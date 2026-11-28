"""E1 (Mission 06, #372): versioned shadow files, rollback-safe, every reader on the file of the running version."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from src.dashboard import chart_verdict as cv
from src.dashboard import orderflow_shadow as shadow
from src.dashboard import pit_lage as pit
from src.dashboard import plan_opinion, waiting_on_uzi
from tests.test_orderflow_shadow import T0, lage, plan, write_journal

OLD = {"schema": shadow.SCHEMA, "started_at": (T0 - timedelta(days=1)).isoformat(),
       "plans": {"old": {"id": "old", "created_at": (T0 - timedelta(hours=5)).isoformat(), "gate_at_plan": shadow.GEGEN,
                         "lage_at_plan": {"price": 1.0}, "journal": {"status": "FILLED"}}}}


@pytest.fixture(autouse=True)
def _fresh_history():
    pit.reset()
    yield
    pit.reset()


def test_versioned_path_is_per_symbol_and_idempotent():
    base = Path("data/journal/tim_orderflow_shadow.json")
    btc = pit.versioned_path(base)
    assert btc.name == "tim_orderflow_shadow.BTCUSDT.pit-1.json" and pit.versioned_path(btc) == btc
    assert pit.versioned_path(base, "xmrusdt").name == "tim_orderflow_shadow.XMRUSDT.pit-1.json"
    assert shadow.current_path(base) == plan_opinion.current_path(base) == cv.current_path(base) == btc


def test_upgrade_rollback_upgrade_mixes_nothing_and_keeps_open_cases_with_their_version(tmp_path):
    journal, path = tmp_path / "tim_plan_journal_short.json", tmp_path / "tim_orderflow_shadow.json"
    path.write_text(json.dumps(OLD), encoding="utf-8")
    before = path.read_bytes()
    shadow.update(path, [journal], None, now=T0 - timedelta(minutes=1))                 # upgrade: pit/1 starts
    write_journal(journal, plan("OPEN"))
    up = shadow.update(path, [journal], lage("auf", at=T0 - timedelta(seconds=10)), now=T0 + timedelta(seconds=5))
    assert path.read_bytes() == before                                                   # 1.x file byte for byte
    assert set(up["plans"]) == {"p1"} and up["plans"]["p1"]["pit"] == pit.PIT_VERSION    # open old case stays in 1.x
    # rollback: the earlier code reads the plain file and sees only its own records
    rolled = json.loads(path.read_text(encoding="utf-8"))
    assert set(rolled["plans"]) == {"old"} and "pit" not in rolled["plans"]["old"]
    rolled["plans"]["old"]["journal"] = {"status": "CLOSED", "net_r": -1.0}              # the 1.x code goes on alone
    path.write_text(json.dumps(rolled), encoding="utf-8")
    # upgrade again: pit/1 continues its own file, the 1.x progress is not pulled in
    again = shadow.update(path, [journal], lage("auf", at=T0 + timedelta(minutes=2)), now=T0 + timedelta(minutes=2))
    assert set(again["plans"]) == {"p1"} and again["started_at"] == up["started_at"]
    assert again["summary"]["plans"] == 1 and again["previous_version"]["plans"] == 1


def test_a_crash_while_saving_leaves_the_last_good_file(tmp_path, monkeypatch):
    journal, path = tmp_path / "tim_plan_journal_short.json", tmp_path / "tim_orderflow_shadow.json"
    shadow.update(path, [journal], None, now=T0 - timedelta(minutes=1))
    good = shadow.current_path(path).read_bytes()
    write_journal(journal, plan("OPEN"))

    def crash(src, dst):
        raise OSError("power loss before the rename")

    monkeypatch.setattr(shadow.os, "replace", crash)
    with pytest.raises(OSError):
        shadow.update(path, [journal], lage("auf", at=T0), now=T0 + timedelta(seconds=5))
    assert shadow.current_path(path).read_bytes() == good                               # never half a file
    monkeypatch.undo()
    pit.observe(lage("auf", at=T0), T0)
    state = shadow.update(path, [journal], lage("auf", at=T0), now=T0 + timedelta(seconds=5))   # rerun: same result
    twice = shadow.update(path, [journal], lage("auf", at=T0), now=T0 + timedelta(seconds=5))
    assert state["plans"]["p1"] == twice["plans"]["p1"] and not list(tmp_path.glob("*.tmp"))


def test_btc_and_xmr_files_are_apart(tmp_path):
    journal, path = tmp_path / "tim_plan_journal_xmr_15m.json", tmp_path / "tim_orderflow_shadow.json"
    shadow.update(path, [journal], None, now=T0, symbol="BTCUSDT")
    shadow.update(path, [journal], None, now=T0, symbol="XMRUSDT")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["tim_orderflow_shadow.BTCUSDT.pit-1.json",
                                                           "tim_orderflow_shadow.XMRUSDT.pit-1.json"]


def test_all_three_consumers_write_only_their_versioned_file(tmp_path):
    journal = tmp_path / "tim_plan_journal_short.json"
    for name, run in (("of.json", lambda p: shadow.update(p, [journal], None, now=T0)),
                      ("op.json", lambda p: plan_opinion.update(p, [journal], None, now=T0, ask=lambda t: {"ok": False})),
                      ("cv.json", lambda p: cv.update(p, [journal], {}, None, now=T0))):
        old = tmp_path / name
        old.write_text("{}", encoding="utf-8")
        run(old)
        assert old.read_text(encoding="utf-8") == "{}" and pit.versioned_path(old).is_file()


def test_readers_follow_the_versioned_file(tmp_path):
    closed = {str(i): {"pit": pit.PIT_VERSION, "journal": {"status": "CLOSED", "net_r": 0.1}} for i in range(shadow.TARGET_TRADES)}
    for target, body in ((tmp_path / shadow.DEFAULT_PATH, {"plans": {}}),
                         (tmp_path / shadow.current_path(), {"plans": closed})):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(body), encoding="utf-8")
    assert waiting_on_uzi.items(tmp_path) == [f"Orderflow-Schatten: {shadow.TARGET_TRADES} geschlossene Pläne erreicht "
                                              f"(Ziel {shadow.TARGET_TRADES}), Urteil fällig."]
