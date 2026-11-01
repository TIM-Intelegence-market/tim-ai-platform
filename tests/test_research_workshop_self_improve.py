"""F11 Selbst-Verbesserung: filters from trade lessons, look back, 30-day forward window, one verdict."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from src.research_lab.workshop import self_improve as si

T0 = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def trade(n, net, *, against=False, costly=False, grade="B", missing=(), created=None):
    entry = 100_000.0
    stop = entry - (entry * 0.004 if costly else entry * 0.02)  # 0.4 % stop -> ~0.48 R costs; 2 % -> ~0.1 R
    return {"id": f"t{n}", "status": "CLOSED", "net_r": net, "direction": "LONG",
            "market_state": "TREND_DOWN" if against else "TREND_UP", "setup_grade": grade,
            "missing_confirmations": list(missing), "entry": entry, "stop": stop,
            "created_at": (created or T0 - timedelta(days=60) + timedelta(hours=n)).isoformat().replace("+00:00", "Z")}


def journal(*trades):
    return {"tim_plan_journal": {"entries": list(trades)}}


def reflections(n=25, lesson="COSTS_ATE_PROFIT", share=0.4):
    return [{"lessons": [lesson] if i < n * share else []} for i in range(n)]


def test_planned_cost_matches_the_journal_cost_model():
    assert si.planned_cost_r({"entry": 100.0, "stop": 99.0}) == pytest.approx(0.18)
    assert si.planned_cost_r({"entry": 100.0, "stop": 100.0}) is None
    assert si.planned_cost_r({"entry": None, "stop": 1}) is None


def test_filters_read_only_plan_time_fields():
    t = trade(1, -1.0, against=True, costly=True, grade="C", missing=["volume"])
    assert all(si.FILTERS[k].drops(t) for k in si.FILTERS)
    clean = trade(2, 1.0)
    assert not any(si.FILTERS[k].drops(clean) for k in si.FILTERS)
    # outcome fields are never needed: a trade without them is judged the same way
    stripped = {k: v for k, v in t.items() if k not in {"net_r", "status"}}
    assert all(si.FILTERS[k].drops(stripped) for k in si.FILTERS)


def test_lookback_reports_what_the_dropped_trades_brought():
    trades = [trade(i, -1.0, costly=True) for i in range(10)] + [trade(10 + i, 0.5) for i in range(15)]
    look = si.assess(si.closed(journal(*trades)), "KOSTEN_DECKEL")
    assert (look["trades"], look["dropped"], look["dropped_net_r"], look["kept_net_r"]) == (25, 10, -10.0, 7.5)


def test_a_filter_whose_lookback_lost_money_starts_one_window_and_changes_nothing(tmp_path):
    log = si.LearningLog(tmp_path / "log.jsonl")
    trades = [trade(i, -1.0, costly=True) for i in range(10)] + [trade(10 + i, 0.5, against=True) for i in range(15)]
    data = journal(*trades)
    report = si.step(data, reflections(), log, T0)
    assert report["filters"]["KOSTEN_DECKEL"]["status"] == "beobachtung"
    assert report["filters"]["MIT_TREND"]["status"] == "rueckblick_dagegen"  # dropped trades made money
    events = log.events()
    assert [e["event"] for e in events] == ["watch_start"] and events[0]["changes_tim"] is False
    assert events[0]["end"] == "2026-12-01T12:00:00Z"
    si.step(data, reflections(), log, T0 + timedelta(days=7))
    assert len(log.events()) == 1  # no second window while one runs
    assert data == journal(*trades)


def test_filter_that_drops_almost_everything_is_not_watched(tmp_path):
    log = si.LearningLog(tmp_path / "log.jsonl")
    trades = [trade(i, -0.5, grade="C") for i in range(25)]
    report = si.step(journal(*trades), reflections(), log, T0)
    assert report["filters"]["OHNE_GRADE_C"]["status"] == "trifft_fast_alle"
    assert not log.events()


def _forward(rng, n, drop_mean, keep_mean, start):
    out = []
    for i in range(n):
        costly = i % 3 == 0
        out.append(trade(1000 + i, rng.gauss(drop_mean if costly else keep_mean, 0.3), costly=costly,
                         created=start + timedelta(hours=6 * i)))
    return out


def test_only_trades_planned_in_the_window_count_and_the_window_is_judged_once(tmp_path):
    log = si.LearningLog(tmp_path / "log.jsonl")
    old = [trade(i, -1.0, costly=True) for i in range(10)] + [trade(10 + i, 0.5) for i in range(15)]
    si.step(journal(*old), reflections(), log, T0)
    rng = random.Random(1)
    fresh = _forward(rng, 60, -0.8, 0.2, T0 + timedelta(hours=1))
    late = [trade(5000, -50.0, costly=True, created=T0 + timedelta(days=31))]  # after the window: ignored
    report = si.step(journal(*old, *fresh, *late), reflections(), log, T0 + timedelta(days=30, hours=1))
    assert report["filters"]["KOSTEN_DECKEL"]["status"] == "bestanden"
    verdict = [e for e in log.events() if e["event"] == "verdict"]
    assert len(verdict) == 1 and verdict[0]["figures"]["trades"] == 60
    si.step(journal(*old, *fresh, *late), reflections(), log, T0 + timedelta(days=40))
    assert len([e for e in log.events() if e["event"] == "verdict"]) == 1
    status = si.status(journal(*old, *fresh), reflections(), log, T0 + timedelta(days=40))
    assert {f["key"]: f["state"] for f in status["filters"]}["KOSTEN_DECKEL"] == "bestanden"


def test_noise_does_not_pass_and_a_failed_filter_is_not_retried(tmp_path):
    log = si.LearningLog(tmp_path / "log.jsonl")
    old = [trade(i, -1.0, costly=True) for i in range(10)] + [trade(10 + i, 0.5) for i in range(15)]
    si.step(journal(*old), reflections(), log, T0)
    fresh = _forward(random.Random(2), 60, 0.0, 0.0, T0 + timedelta(hours=1))
    report = si.step(journal(*old, *fresh), reflections(), log, T0 + timedelta(days=31))
    assert report["filters"]["KOSTEN_DECKEL"]["status"] == "nicht_bestanden"
    si.step(journal(*old, *fresh), reflections(), log, T0 + timedelta(days=40))
    assert [e["event"] for e in log.events()] == ["watch_start", "verdict"]


def test_too_few_new_trades_start_a_new_window(tmp_path):
    log = si.LearningLog(tmp_path / "log.jsonl")
    old = [trade(i, -1.0, costly=True) for i in range(10)] + [trade(10 + i, 0.5) for i in range(15)]
    si.step(journal(*old), reflections(), log, T0)
    report = si.step(journal(*old), reflections(), log, T0 + timedelta(days=31))
    assert report["filters"]["KOSTEN_DECKEL"]["status"] == "beobachtung"
    events = log.events()
    assert [e["event"] for e in events] == ["watch_start", "verdict", "watch_start"]
    assert events[1]["verdict"] == "zu_wenig" and events[2]["window"] == 2


def test_random_trades_rarely_pass(tmp_path):
    passed = 0
    for seed in range(40):
        log = si.LearningLog(tmp_path / f"log{seed}.jsonl")
        old = [trade(i, -1.0, costly=True) for i in range(10)] + [trade(10 + i, 0.5) for i in range(15)]
        si.step(journal(*old), reflections(), log, T0)
        fresh = _forward(random.Random(seed), 45, 0.0, 0.0, T0 + timedelta(hours=1))
        report = si.step(journal(*old, *fresh), reflections(), log, T0 + timedelta(days=31))
        passed += report["filters"]["KOSTEN_DECKEL"]["status"] == "bestanden"
    assert passed <= 2


def test_log_detects_tampering(tmp_path):
    log = si.LearningLog(tmp_path / "log.jsonl")
    log.append({"event": "watch_start", "filter": "MIT_TREND", "window": 1, "start": "a", "end": "b"})
    text = (tmp_path / "log.jsonl").read_text().replace("MIT_TREND", "KOSTEN_DECKEL")
    (tmp_path / "log.jsonl").write_text(text)
    with pytest.raises(ValueError, match="Hash-Kette"):
        log.events()
