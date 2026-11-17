"""Kritik-Backlog (src/dashboard/critic_backlog.py): Punkte aus der Kritik, Zusammenführen, Alter, Erledigt, Prompt."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.dashboard import critic_backlog as cb
from src.dashboard import daily_critic
from src.dashboard.cockpit.hermes import build_hermes, render_hermes
from tests.test_dashboard_cockpit import _live_state

NOW = datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc)
TEXT = ("PROJEKT:\n- [Projekt] Kleine Stichprobe der Papier-Journale: Urteile erst nach 30 Plänen.\n"
        "**- [Chart] Chart-Startansicht überladen**: Weniger Ebenen beim Start.\nFreitext ohne Punkt.\n")


def test_parse_reads_points_and_done_lines() -> None:
    points, done = cb.parse(TEXT + "ERLEDIGT: Liquidations-Karte unklar benannt\n- ERLEDIGT: Zweiter Punkt\n")
    assert [(p["area"], p["title"]) for p in points] == [("Projekt", "Kleine Stichprobe der Papier-Journale"), ("Chart", "Chart-Startansicht überladen")]
    assert done == ["Liquidations-Karte unklar benannt", "Zweiter Punkt"]


def test_same_point_merges_ages_and_closes(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    assert cb.apply(path, TEXT, NOW) == {"added": 2, "repeated": 0, "done": 0}
    later = NOW + timedelta(days=2)
    again = "- [Projekt] Stichprobe der Papier-Journale klein: noch gleich.\n- [Chart] Neuer Punkt zur Ladezeit: Live-Daten kürzen.\n"
    assert cb.apply(path, again, later) == {"added": 1, "repeated": 1, "done": 0}
    points = cb.open_points(path, later)
    assert [p["days"] for p in points] == [2, 2, 0]
    assert next(p for p in points if p["area"] == "Projekt")["times_seen"] == 2
    assert cb.apply(path, "ERLEDIGT: Chart-Startansicht überladen\n", later) == {"added": 0, "repeated": 0, "done": 1}
    assert cb.summary(path, later)["counts"] == {"offen": 2, "erledigt": 1, "nicht mehr genannt": 0}


def test_points_not_named_for_a_week_are_dropped_from_open(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    cb.apply(path, TEXT, NOW)
    cb.apply(path, "- [Chart] Etwas ganz anderes zur Ladezeit: x\n", NOW + timedelta(days=8))
    counts = cb.summary(path, NOW + timedelta(days=8))["counts"]
    assert counts["nicht mehr genannt"] == 2 and counts["offen"] == 1


def test_critic_gets_the_backlog_and_feeds_it(tmp_path: Path) -> None:
    path, backlog = tmp_path / "c.json", tmp_path / "b.json"
    asked: list[str] = []
    answers = iter([TEXT, "- [Projekt] Kleine Stichprobe der Papier-Journale: weiter.\nERLEDIGT: Chart-Startansicht überladen\n"])

    def ask(text: str) -> dict:
        asked.append(text)
        return {"ok": True, "answer": next(answers)}

    sources = {"x": lambda: ["Fakt eins."]}
    day1 = datetime(2026, 11, 17, 6, 30, tzinfo=timezone.utc)
    assert daily_critic.update(path, sources, day1, ask, backlog=backlog)
    assert "Backlog der offenen Punkte" not in asked[0] and "- [Projekt] Kurztitel" in asked[0]
    assert daily_critic.update(path, sources, day1 + timedelta(days=1), ask, backlog=backlog)
    assert "Backlog der offenen Punkte" in asked[1] and "[Projekt] Kleine Stichprobe der Papier-Journale (offen seit 1 Tag(en), 1x genannt)" in asked[1]
    assert len(asked[1]) <= daily_critic.MAX_PROMPT
    assert cb.summary(backlog, day1 + timedelta(days=1))["counts"]["erledigt"] == 1


def test_page_shows_the_backlog(tmp_path: Path) -> None:
    state = _live_state(tmp_path, NOW)
    state.critic_backlog_path = tmp_path / "b.json"
    cb.apply(state.critic_backlog_path, TEXT, NOW)
    html = render_hermes(build_hermes(state, NOW))
    assert "Kritik-Backlog" in html and "Chart-Startansicht überladen" in html and "offen seit 0 Tag(en)" in html
