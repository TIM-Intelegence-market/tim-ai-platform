"""Wartet auf Uzi (docs/MULTI_AGENTEN_SYSTEM.md, Paket P6)."""
import json
from datetime import datetime, timezone
from pathlib import Path

from src.dashboard import daily_report, orderflow_shadow, plan_opinion, waiting_on_uzi
from src.research_lab.workshop import self_improve


def _write(root: Path, relative: Path, payload) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")


def _closed(count: int) -> dict:
    return {f"plan-{i}": {"journal": {"status": "CLOSED", "net_r": 1.0}} for i in range(count)}


def test_nothing_waiting_in_an_empty_root(tmp_path):
    assert waiting_on_uzi.items(tmp_path) == []


def test_watchdog_hold_is_listed(tmp_path):
    _write(tmp_path, waiting_on_uzi.WATCHDOG_STATE, {"restart_hold": True, "restart_hold_since": "2026-11-10T12:00:00Z"})
    assert waiting_on_uzi.items(tmp_path) == [
        "Watchdog hat die Neustarts angehalten (seit 2026-11-10T12:00:00Z): Neustart-Budget verbraucht, Ursache prüfen."]
    _write(tmp_path, waiting_on_uzi.WATCHDOG_STATE, {"restart_hold": False})
    assert waiting_on_uzi.items(tmp_path) == []


def test_unreadable_watchdog_state_is_named(tmp_path):
    target = tmp_path / waiting_on_uzi.WATCHDOG_STATE
    target.parent.mkdir(parents=True)
    target.write_text("{kaputt", encoding="utf-8")
    assert waiting_on_uzi.items(tmp_path) == ["Watchdog-Zustand data/operational/watchdog_recovery_state.json nicht lesbar."]


def test_passed_filter_is_listed_once_and_failed_is_not(tmp_path):
    log = self_improve.LearningLog(tmp_path / self_improve.LOG_PATH)
    log.path.parent.mkdir(parents=True)
    log.append({"event": "verdict", "filter": "gegen_trend", "window": 1, "verdict": "bestanden"})
    log.append({"event": "verdict", "filter": "gegen_trend", "window": 2, "verdict": "bestanden"})
    log.append({"event": "verdict", "filter": "spaet", "window": 1, "verdict": "nicht_bestanden"})
    assert waiting_on_uzi.items(tmp_path) == ["F11-Filter gegen_trend bestanden: bereit für deine Entscheidung."]


def test_broken_learning_log_is_named(tmp_path):
    target = tmp_path / self_improve.LOG_PATH
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"event": "verdict", "previous": "x", "hash": "y"}) + "\n", encoding="utf-8")
    assert waiting_on_uzi.items(tmp_path) == ["F11-Lernlog: Hash-Kette gebrochen, nichts davon zählt bis zur Prüfung."]


def test_shadow_and_opinion_due_after_target(tmp_path):
    _write(tmp_path, orderflow_shadow.DEFAULT_PATH, {"plans": _closed(orderflow_shadow.TARGET_TRADES)})
    _write(tmp_path, plan_opinion.DEFAULT_PATH, {"plans": _closed(plan_opinion.TARGET_TRADES - 1)})
    lines = waiting_on_uzi.items(tmp_path)
    assert lines == [f"Orderflow-Schatten: {orderflow_shadow.TARGET_TRADES} geschlossene Pläne erreicht "
                     f"(Ziel {orderflow_shadow.TARGET_TRADES}), Urteil fällig."]


def test_daily_report_lists_waiting_items_and_survives_errors(tmp_path):
    now = datetime(2026, 11, 10, 7, 5, tzinfo=timezone.utc)  # 08:05 Berlin
    since = datetime(2026, 11, 9, 21, 0, tzinfo=timezone.utc)
    lines = daily_report.facts({}, None, [], since, now, ["Watchdog hält"])
    assert lines[-1] == "Wartet auf Uzi: Watchdog hält"
    assert daily_report.facts({}, None, [], since, now, [])[-1] == "Wartet auf Uzi: nichts."
    assert daily_report.facts({}, None, [], since, now, None)[-1] == "Wartet auf Uzi: nicht lesbar."

    def broken():
        raise RuntimeError("kaputt")

    report = daily_report.update(tmp_path / "r.json", {}, None, now=now,
                                 ask=lambda text: {"ok": True, "answer": "ok"}, waiting=broken)
    assert report["facts"][-1] == "Wartet auf Uzi: nicht lesbar."


def test_decided_or_later_failed_filter_is_not_listed(tmp_path):
    log = self_improve.LearningLog(tmp_path / self_improve.LOG_PATH)
    log.path.parent.mkdir(parents=True)
    name = sorted(self_improve.FILTERS)[0]
    other = sorted(self_improve.FILTERS)[1]
    log.append({"event": "verdict", "filter": name, "window": 1, "verdict": "bestanden"})
    log.append({"event": "verdict", "filter": other, "window": 1, "verdict": "bestanden"})
    log.append({"event": "verdict", "filter": other, "window": 2, "verdict": "nicht_bestanden"})
    assert waiting_on_uzi.items(tmp_path) == [f"F11-Filter {name} bestanden: bereit für deine Entscheidung."]
    log.append({"event": "decision", "filter": name, "filter_hash": self_improve.filter_hash(name), "answer": "ja"})
    assert waiting_on_uzi.items(tmp_path) == []


def test_one_bad_file_is_named_and_others_still_listed(tmp_path):
    _write(tmp_path, orderflow_shadow.DEFAULT_PATH, ["kein", "objekt"])
    _write(tmp_path, waiting_on_uzi.WATCHDOG_STATE, {"restart_hold": True})
    assert waiting_on_uzi.items(tmp_path) == [
        "Watchdog hat die Neustarts angehalten (seit unbekannt): Neustart-Budget verbraucht, Ursache prüfen.",
        "Orderflow-Schatten: Datei nicht lesbar."]
