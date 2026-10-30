"""Control Center P2 (Beirat 29.10.2026): plan notes, "Heute zu tun", research logbook."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.dashboard import plan_notes
from src.dashboard.app import DashboardServer, DashboardState
from src.dashboard.cockpit.areas import LOGBOOK_PATH, LOGBOOK_STATUS, _logbook_section
from src.dashboard.cockpit.page import lage_body
from src.dashboard.plan_journal import SCHEMA

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _journal(path: Path, entries: list[dict]) -> Path:
    path.write_text(json.dumps({"schema": SCHEMA, "entries": entries}), encoding="utf-8")
    return path


def _plan(pid: str, created: datetime, **extra) -> dict:
    return {"id": pid, "created_at": _iso(created), "direction": "LONG", "scenario_id": "A", "entry": 80000.0,
            "stop": 79000.0, "status": "CLOSED", "targets": [81000.0], **extra}


# --- plan notes -------------------------------------------------------------

def test_note_is_appended_and_the_newest_counts(tmp_path: Path) -> None:
    path = tmp_path / "notes.json"
    known = {plan_notes.key("tim/1", "abcdef012345")}
    form = {"plan_id": "abcdef012345", "rule": "tim/1", "decision": "skipped", "reason": "  zu nah  an NY-Open "}
    first = plan_notes.add_note(path, form, known, now=NOW)
    second = plan_notes.add_note(path, {**form, "decision": "TAKEN", "reason": "doch genommen"}, known, now=NOW)
    assert first["id"] == "PN-00001" and first["reason"] == "zu nah an NY-Open" and first["decision"] == "SKIPPED"
    latest = plan_notes.latest(plan_notes.load(path))
    assert latest[plan_notes.key("tim/1", "abcdef012345")]["id"] == second["id"]
    assert len(plan_notes.load(path)["notes"]) == 2  # history stays


@pytest.mark.parametrize("change,message", [
    ({"plan_id": "000000000000"}, "gibt es im Journal nicht"),
    ({"rule": "struct/1"}, "gibt es im Journal nicht"),  # same id, other rule: not a known plan
    ({"plan_id": "../etc"}, "gibt es im Journal nicht"),
    ({"decision": "MAYBE"}, "Bitte wählen"),
    ({"reason": "ok"}, "mindestens"),
    ({"reason": "x" * 501}, "zu lang"),
])
def test_invalid_notes_are_refused(tmp_path: Path, change: dict, message: str) -> None:
    form = {"plan_id": "abcdef012345", "rule": "tim/1", "decision": "TAKEN", "reason": "guter Grund", **change}
    with pytest.raises(plan_notes.NoteError, match=message):
        plan_notes.add_note(tmp_path / "n.json", form, {plan_notes.key("tim/1", "abcdef012345")}, now=NOW)
    assert not (tmp_path / "n.json").exists()


def test_missing_skips_old_excluded_and_noted_plans() -> None:
    entries = [_plan("aaaaaaaaaaaa", NOW - timedelta(days=1)), _plan("bbbbbbbbbbbb", NOW - timedelta(days=8)),
               _plan("cccccccccccc", NOW - timedelta(hours=2), excluded={"reason": "Phantom"}),
               _plan("dddddddddddd", NOW - timedelta(hours=1))]
    notes = {plan_notes.key("tim/1", "dddddddddddd"): {}}
    assert [e["id"] for e in plan_notes.missing(entries, "tim/1", notes, now=NOW)] == ["aaaaaaaaaaaa"]


def test_journal_page_takes_a_note_end_to_end(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    state = DashboardState(plan_journal_path=_journal(tmp_path / "tim.json", [_plan("abcdef012345", now - timedelta(hours=3))]),
                           plan_journal_struct_path=tmp_path / "s.json", plan_journal_level_path=tmp_path / "l.json",
                           plan_notes_path=tmp_path / "notes.json")
    server = DashboardServer(state, port=0)
    server.start()
    port = server.server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/journal", timeout=10) as response:
            page = response.read().decode()
            assert "form-action 'self'" in response.headers["Content-Security-Policy"]
        assert "1 Plan wartet auf deine Zeile" in page
        token = re.search(r"name='token' value='([^']+)'", page).group(1)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        body = urllib.parse.urlencode({"token": token, "plan_id": "abcdef012345", "rule": "tim/1", "decision": "WATCHED",
                                       "reason": "Nur zugeschaut", "back": "/journal"}).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{port}/journal/note", data=body,
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
        with pytest.raises(urllib.error.HTTPError) as redirect:
            urllib.request.build_opener(NoRedirect).open(request, timeout=10)
        assert redirect.value.code == 303 and redirect.value.headers["Location"] == "/journal?saved=PN-00001"
        bad = urllib.request.Request(f"http://127.0.0.1:{port}/journal/note", data=body.replace(token.encode(), b"wrong"),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(bad, timeout=10)
        assert refused.value.code == 403
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/journal?saved=PN-00001", timeout=10) as response:
            page = response.read().decode()
        assert "Notiz gespeichert: PN-00001" in page and "Alles notiert" in page
        assert "Deine Notiz: nur beobachtet, Nur zugeschaut" in page
    finally:
        server.stop()


# --- Heute ------------------------------------------------------------------

def _lage(system_states: list[str], today: list[dict]) -> str:
    system = [{"id": f"s{i}", "label": f"S{i}", "state": state, "value": "x"} for i, state in enumerate(system_states)]
    return lage_body({"generated_at": NOW.isoformat(), "overall": "ok", "system": system, "today": today, "market": [], "plans": []})


def test_system_folds_to_one_line_when_green_and_opens_on_trouble() -> None:
    green = _lage(["ok", "ok"], [])
    assert "<details class='fold'><summary class='s-ok'>System läuft: 2 von 2 grün</summary>" in green
    trouble = _lage(["ok", "fail"], [])
    assert "<details class='fold' open><summary class='s-warn'>System: 1 von 2 grün, bitte ansehen</summary>" in trouble


def test_today_list_shows_open_and_done_items() -> None:
    page = _lage(["ok"], [{"label": "Mein Tag", "done": False, "text": "heute noch nicht ausgefüllt", "href": "/my-day"},
                          {"label": "Notizen zu TIMs Plänen", "done": True, "text": "alle notiert", "href": "/journal"}])
    assert "Heute zu tun" in page and "<li class='open'>" in page and "<li class='done'>" in page
    assert "<a href='/my-day'>Mein Tag</a>" in page


# --- Forschung --------------------------------------------------------------

def test_logbook_entries_are_complete_and_point_to_real_files() -> None:
    data = json.loads(LOGBOOK_PATH.read_text(encoding="utf-8"))
    ids = [entry["id"] for entry in data["entries"]]
    assert len(ids) == len(set(ids))
    for entry in data["entries"]:
        assert entry["status"] in LOGBOOK_STATUS and entry["title"] and entry["result"]
        datetime.strptime(entry["started"], "%Y-%m-%d")
        if entry["doc"] and not entry["doc"].startswith("/"):
            assert Path(entry["doc"]).exists(), entry["doc"]


def test_logbook_section_sorts_newest_first_and_survives_a_broken_file(tmp_path: Path) -> None:
    section = _logbook_section(LOGBOOK_PATH, NOW)
    dates = [row[1]["text"] for row in section["table"]["rows"]]
    as_dates = [datetime.strptime(d, "%d.%m.%Y") for d in dates]
    assert as_dates == sorted(as_dates, reverse=True)
    broken = tmp_path / "LOGBUCH.json"
    broken.write_text("{kaputt", encoding="utf-8")
    tile = _logbook_section(broken, NOW)["tiles"][0]
    assert tile.state == "unknown" and "nicht lesbar" in tile.reason
