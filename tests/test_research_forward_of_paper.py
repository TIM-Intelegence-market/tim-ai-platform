"""Orderflow paper journal: prospective start, day-by-day equals one pass, waits for missing archives."""
from __future__ import annotations

import dataclasses
import json
import random
from datetime import date, datetime, timedelta, timezone

import pytest

from src.research_lab.data.store import HoldoutLocked
from src.research_lab.forward import of_paper
from src.research_lab.of2 import engine
from src.research_lab.orderflow_ml.store import (
    PAPER_FIRST_DAY,
    PAPER_RELEASE,
    MinuteBarStore,
    guard,
)
from tests.test_research_lab_of2 import synthetic_day

CFG = dataclasses.replace(of_paper.PAPER_CONFIG, max_cost_r=100.0)  # let the tiny synthetic stops through
START = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
FIRST = date(2026, 11, 11)


class FakeStore:
    """Synthetic days; ``published`` is the last day the archive already offers."""

    def __init__(self) -> None:
        self.days: dict[date, tuple] = {}
        rng, price = random.Random(5), 30_000.0
        day = FIRST - timedelta(days=of_paper.LEAD_DAYS)
        for _ in range(of_paper.LEAD_DAYS + 40):
            bars, profile, price = synthetic_day(engine._ms(day), rng, price)
            self.days[day] = (bars, profile)
            day += timedelta(days=1)
        self.have: set[date] = set()
        self.published = date(2100, 1, 1)
        self.fetches = 0

    def cached(self, day):
        return {} if day in self.have else None

    def fetch(self, day):
        self.fetches += 1
        if day > self.published:
            raise FileNotFoundError("404")
        self.have.add(day)

    def load(self, day):
        return self.days[day][0]

    def load_profile(self, day):
        return self.days[day][1]


def journal(tmp_path, store, now):
    return of_paper.PaperJournal(tmp_path, cfg=CFG, store=store, clock=lambda: now[0])


def test_start_is_prospective_and_frozen(tmp_path):
    now = [START]
    j = journal(tmp_path, FakeStore(), now)
    start = j.start()
    assert start["first_day"] == "2026-11-11" and start["config"]["of_gate"] is True
    now[0] = START + timedelta(days=3)
    assert j.start() == start
    with pytest.raises(of_paper.PaperError):
        of_paper.PaperJournal(tmp_path, cfg=dataclasses.replace(CFG, min_rr=9.0), store=FakeStore()).start()


def test_daily_steps_equal_one_pass_and_events_are_logged_once(tmp_path):
    store, now = FakeStore(), [START]
    j = journal(tmp_path / "daily", store, now)
    first = j.step()
    assert first["trades"] == 0 and first["last_day"] == "2026-11-09"  # only lead days so far: nothing counts
    for d in range(1, 31):
        now[0] = START + timedelta(days=d)
        status = j.step()
    daily = json.loads((tmp_path / "daily" / "journal.json").read_text())
    events = [json.loads(x) for x in (tmp_path / "daily" / "events.jsonl").read_text().splitlines()]
    assert status["trades"] == len(daily["trades"]) == len(events) >= 1
    assert all(t["signal_ms"] >= engine._ms(FIRST) and t["confirmed"] for t in daily["trades"])
    assert status["trichter"] and sum(r["geschlossen"] for r in status["trichter"].values()) == status["trades"]
    once = journal(tmp_path / "once", FakeStore(), [START])
    once.start()
    late = of_paper.PaperJournal(tmp_path / "once", cfg=CFG, store=FakeStore(), clock=lambda: START + timedelta(days=30))
    assert json.loads(json.dumps(late.step()["trichter"])) == status["trichter"]
    assert json.loads((tmp_path / "once" / "journal.json").read_text())["trades"] == daily["trades"]
    # a step without a new day does not run the engine again and keeps the numbers
    again = j.step()
    assert again["new_events"] == 0 and again["trades"] == status["trades"] and again["trichter"] == status["trichter"]


def test_missing_archive_waits_and_is_asked_once_an_hour(tmp_path):
    store, now = FakeStore(), [START + timedelta(days=5)]
    store.published = date(2026, 11, 12)
    j = journal(tmp_path, store, now)
    j.folder.mkdir(parents=True, exist_ok=True)
    (j.folder / "start.json").write_text(json.dumps({"started_at": "2026-11-10T12:00:00Z", "first_day": "2026-11-11",
                                                      "config_digest": CFG.digest(), "config": CFG.as_dict()}))
    status = j.step()
    assert status["last_day"] == "2026-11-12" and status["waiting_for"] == "2026-11-13"
    fetches = store.fetches
    now[0] += timedelta(minutes=15)
    assert j.step()["waiting_for"] == "2026-11-13" and store.fetches == fetches     # not asked again yet
    now[0] += timedelta(hours=1)
    store.published = date(2026, 11, 14)
    status = j.step()
    assert status["last_day"] == "2026-11-14" and status["waiting_for"] is None


def test_paper_release_reads_only_its_window(tmp_path):
    guard(PAPER_FIRST_DAY, PAPER_RELEASE, today=date(2026, 11, 10))
    with pytest.raises(HoldoutLocked):
        guard(PAPER_FIRST_DAY - timedelta(days=1), PAPER_RELEASE, today=date(2026, 11, 10))
    with pytest.raises(HoldoutLocked):
        guard(date(2026, 11, 10), PAPER_RELEASE, today=date(2026, 11, 10))
    with pytest.raises(HoldoutLocked):
        MinuteBarStore(tmp_path).load(date(2026, 10, 5))


def test_workshop_runs_the_journal_only_where_it_was_started(tmp_path):
    from src.research_lab.workshop.schedule import _of_paper_step
    assert _of_paper_step(tmp_path) == {"new_events": 0, "started": False}


def test_card_shows_the_journal():
    from src.dashboard.screens import _of_paper_card
    assert "Noch nicht gestartet" in _of_paper_card(None)
    html = _of_paper_card({"first_day": "2026-11-11", "last_day": "2026-11-20", "checked_at": "2026-11-21T01:10:00Z",
                           "trades": 2, "min_trades": 100, "net_r": 1.2, "mean_r": 0.6, "max_drawdown_r": 0.4,
                           "waiting_for": "2026-11-21", "open": [], "recent": [
                               {"model": "M1", "direction": 1, "session": "LONDON", "reason": "TARGET", "net_r": 1.6, "exit_ms": 0}],
                           "trichter": {"M1": {"kandidat": 9, "bestaetigt": 4, "frei": 3, "risiko_ok": 2, "geschlossen": 2}}})
    assert "2 von 100 Trades" in html and "9 Kandidaten" in html and "wartet auf Archiv 2026-11-21" in html and "Ziel" in html
