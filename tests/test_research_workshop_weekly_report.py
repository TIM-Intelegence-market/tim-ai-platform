"""Wochenbericht der Lernschleife: höchstens eine Ja/Nein-Frage, Antwort im Lern-Log, TIM bleibt unverändert."""
from __future__ import annotations

import random
from datetime import timedelta

import pytest

from src.research_lab.workshop import self_improve as si
from src.research_lab.workshop import weekly_report as wr
from tests.test_research_workshop_self_improve import T0, _forward, journal, reflections, trade


def _passed(tmp_path):
    log = si.LearningLog(tmp_path / "log.jsonl")
    old = [trade(i, -1.0, costly=True) for i in range(10)] + [trade(10 + i, 0.5) for i in range(15)]
    si.step(journal(*old), reflections(), log, T0)
    fresh = _forward(random.Random(1), 60, -0.8, 0.2, T0 + timedelta(hours=1))
    data = journal(*old, *fresh)
    now = T0 + timedelta(days=30, hours=1)
    return log, data, si.step(data, reflections(), log, now), now


def test_no_question_while_a_filter_is_only_watched(tmp_path):
    log = si.LearningLog(tmp_path / "log.jsonl")
    old = [trade(i, -1.0, costly=True) for i in range(10)] + [trade(10 + i, 0.5) for i in range(15)]
    data = journal(*old)
    learning = si.step(data, reflections(), log, T0)
    week = wr.build(data, learning, log.events(), T0)
    assert week["proposal"] is None and week["changes_tim"] is False
    watched = {f["filter"]: f for f in week["filters"]}["KOSTEN_DECKEL"]
    assert watched["status"] == "beobachtung" and watched["fresh"] == 0
    text = wr.render(week)
    assert "Keine Entscheidung nötig" in text and "ja/nein" not in text


def test_a_passed_filter_becomes_the_one_question(tmp_path):
    log, data, learning, now = _passed(tmp_path)
    week = wr.build(data, learning, log.events(), now)
    assert week["proposal"]["filter"] == "KOSTEN_DECKEL"
    assert week["proposal"]["figures"]["trades"] == 60
    text = wr.render(week)
    assert text.count("ja/nein") == 1 and "Kosten" in text


def test_week_counts_only_trades_closed_in_the_last_seven_days():
    now = T0
    recent = {**trade(1, 1.0), "closed_at": (now - timedelta(days=2)).isoformat()}
    old = {**trade(2, -2.0), "closed_at": (now - timedelta(days=9)).isoformat()}
    week = wr.build({"tim_plan_journal_mid": {"entries": [recent, old]}}, {"filters": {}}, [], now)
    row = week["journals"][0]
    assert (row["label"], row["closed"], row["net_r"], row["week_closed"], row["week_net_r"]) == ("1h", 2, -1.0, 1, 1.0)
    assert "1h: Woche 1 Trades +1,00 R, gesamt 2 Trades -1,00 R" in wr.render(week)


def test_decision_is_logged_once_and_ends_the_question(tmp_path):
    log, data, _, now = _passed(tmp_path)
    with pytest.raises(ValueError, match="Beleg"):
        wr.record_decision(log, "KOSTEN_DECKEL", "ja", by="Uzi", reference=" ", at=now)
    with pytest.raises(ValueError, match="ja oder nein"):
        wr.record_decision(log, "KOSTEN_DECKEL", "vielleicht", by="Uzi", reference="x", at=now)
    event = wr.record_decision(log, "KOSTEN_DECKEL", "Ja", by="Uzi", reference="Uzi 08.11. im Thread", at=now)
    assert event["answer"] == "ja" and event["changes_tim"] is False and "Pull Request" in event["next"]
    with pytest.raises(ValueError, match="schon entschieden"):
        wr.record_decision(log, "KOSTEN_DECKEL", "nein", by="Uzi", reference="x", at=now)
    later = now + timedelta(days=7)
    learning = si.step(data, reflections(), log, later)
    assert learning["filters"]["KOSTEN_DECKEL"]["status"] == "uebernommen"
    week = wr.build(data, learning, log.events(), later)
    assert week["proposal"] is None
    states = {f["key"]: f["state"] for f in si.status(data, reflections(), log, later)["filters"]}
    assert states["KOSTEN_DECKEL"] == "uebernommen"
    log.events()  # hash chain intact


def test_only_passed_filters_can_be_decided(tmp_path):
    log = si.LearningLog(tmp_path / "log.jsonl")
    with pytest.raises(ValueError, match="nichts zu entscheiden"):
        wr.record_decision(log, "MIT_TREND", "ja", by="Uzi", reference="x", at=T0)
    with pytest.raises(ValueError, match="unbekannter Filter"):
        wr.record_decision(log, "GIBT_ES_NICHT", "ja", by="Uzi", reference="x", at=T0)
    assert not (tmp_path / "log.jsonl").exists()
