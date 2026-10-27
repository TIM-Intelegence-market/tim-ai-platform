"""Daily prep ("Mein Tag"): validation, append-only log, suggested levels, page and server guards."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http.client import HTTPConnection
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

from src.dashboard import daily_prep as dp
from src.dashboard.app import DashboardServer, DashboardState
from src.dashboard.pages.my_day import my_day_csp, prep_banner, render_my_day
from src.dashboard.pages.prep import _prep_page

T0 = datetime(2026, 10, 28, 7, 30, tzinfo=timezone.utc)  # 08:30 in Germany


def _form(**changes: str) -> dict[str, str]:
    form = {"kind": "PREP", "f_BTC": "1", "body": "3", "head": "4", "carry": "1", "carrying": "nichts",
            "lv_0": "1D VAH|80500.0", "lv_1": "1M VAL|79850.5", "extra_levels": "26150 Monthly VAL\n25900 Yearly VAL",
            "plan": "Long am 1M VAL mit CVD-Divergenz, Stop unter dem Swing.", "max_risk_r": "2,5", "max_trades": "3",
            "cutoff": "21:30", "breathing": "1", "oath": "1"}
    form.update(changes)
    return {key: value for key, value in form.items() if value is not None}


def test_prep_entry_keeps_answers_levels_and_limits() -> None:
    entry = dp.build_entry(_form(), T0, 1, {"bias": "LONG"})
    assert (entry["id"], entry["kind"], entry["day"]) == ("DP-0001", "PREP", "2026-10-28")
    assert entry["focus"] == ["BTC"] and entry["mood"] == {"body": 3, "head": 4, "carry": 1}
    assert entry["levels"] == [{"label": "1D VAH", "price": 80500.0}, {"label": "1M VAL", "price": 79850.5}]
    assert entry["extra_levels"] == "26150 Monthly VAL\n25900 Yearly VAL"
    assert entry["limits"] == {"max_risk_r": 2.5, "max_trades": 3, "cutoff": "21:30"}
    assert entry["breathing"] is True and entry["oath"] is True and entry["counter_trend"] is False
    assert entry["context"] == {"bias": "LONG"} and entry["hints"] == []


@pytest.mark.parametrize("changes, message", [
    ({"f_BTC": None}, "Fokus fehlt"),
    ({"oath": None}, "Eid fehlt"),
    ({"plan": "  "}, "Plan fehlt"),
    ({"cutoff": "25:00"}, "Schlusszeit"),
    ({"body": "6"}, "Körper: ganze Zahl zwischen 0 und 5"),
    ({"head": "2.5"}, "Kopf: ganze Zahl"),
    ({"max_risk_r": "0"}, r"Max\. Risiko am Tag \(R\): Zahl zwischen 0\.1 und 20"),
    ({"max_trades": "abc"}, "Max. Trades: bitte eine Zahl"),
    ({"lv_0": "kaputt"}, "Level-Liste beschädigt"),
    ({"lv_0": "|80500"}, "Level-Liste beschädigt"),
    ({"kind": "ORDER"}, "Unbekannte Aktion"),
    ({"plan": "x" * 1001}, "höchstens 1000 Zeichen"),
])
def test_prep_entry_refuses_bad_input(changes, message) -> None:
    with pytest.raises(dp.PrepError, match=message):
        dp.build_entry(_form(**changes), T0, 1)


def test_too_many_levels_are_refused() -> None:
    levels = {f"lv_{i}": f"L{i}|{80000 + i}" for i in range(dp.MAX_LEVELS + 1)}
    with pytest.raises(dp.PrepError, match="Höchstens 16 Level"):
        dp.build_entry({**_form(), **levels}, T0, 1)


def test_skip_and_no_trade_day_need_nothing_else() -> None:
    entry = dp.build_entry({"kind": "SKIP"}, T0, 2)
    assert entry["kind"] == "SKIP" and entry["note"] == "" and "plan" not in entry
    entry = dp.build_entry({"kind": "no_trade_day", "note": "FOMC heute"}, T0, 3)
    assert (entry["kind"], entry["note"]) == ("NO_TRADE_DAY", "FOMC heute")


def test_hints_from_own_answers() -> None:
    entry = dp.build_entry(_form(body="1", carry="4", counter_trend="1", lv_0=None, lv_1=None, extra_levels=""), T0, 1)
    assert entry["hints"] == ["Körper oder Kopf sehr schwach: heute kleiner oder gar nicht", "schwere Altlast: Tilt-Gefahr, Grenzen halbieren?",
                              "Gegentrend geplant: nur mit klarer Bestätigung", "keine Level gewählt"]


def test_day_is_the_german_local_day() -> None:
    assert dp.local_day(datetime(2026, 10, 27, 23, 30, tzinfo=timezone.utc)).isoformat() == "2026-10-28"


def test_log_is_append_only_and_today_takes_the_newest(tmp_path) -> None:
    path = tmp_path / "daily_prep.json"
    first = dp.add_entry(path, _form(), None, T0)
    second = dp.add_entry(path, {"kind": "NO_TRADE_DAY"}, None, T0.replace(hour=9))
    log = dp.load(path)
    assert [e["id"] for e in log["entries"]] == [first["id"], second["id"]] == ["DP-0001", "DP-0002"]
    assert dp.today(log, T0.replace(hour=10))["id"] == "DP-0002"
    assert dp.today(log, datetime(2026, 10, 29, 8, tzinfo=timezone.utc)) is None
    assert [e["id"] for e in dp.latest_per_day(log["entries"])] == ["DP-0002"]
    with pytest.raises(dp.PrepError):
        dp.add_entry(path, _form(plan=""), None, T0)
    assert len(dp.load(path)["entries"]) == 2  # a refused form writes nothing


def test_load_rejects_foreign_files(tmp_path) -> None:
    path = tmp_path / "daily_prep.json"
    path.write_text(json.dumps({"schema": "other", "entries": [1]}))
    assert dp.load(path) == dp.empty_log()
    path.write_text("{kaputt")
    assert dp.load(path) == dp.empty_log()


def test_suggested_levels_are_the_nearest_including_higher_timeframes() -> None:
    model = {"last": 100.0,
             "levels": [{"label": f"L{p}", "price": float(p)} for p in (90, 99, 101, 130, 60)],
             "htf_levels": {"levels": [{"label": "1Y VAL", "price": 100.5}, {"label": "12M VWAP", "price": 70.0}, {"label": "x", "price": float("nan")}]}}
    levels = dp.suggested_levels(model, count=4)
    assert [level["label"] for level in levels] == ["L101", "1Y VAL", "L99", "L90"]
    assert dp.suggested_levels(None) == [] and dp.level_value(levels[1]) == "1Y VAL|100.5"


def test_page_escapes_input_has_no_script_and_prefills_levels() -> None:
    levels = [{"label": "1D VAH", "price": 80500.0}, {"label": "<b>x</b>", "price": 80000.0}]
    page = render_my_day({}, dp.empty_log(), "tok", levels, 80250.0, None)
    assert "<script" not in page and "<b>x</b>" not in page and "&lt;b&gt;x&lt;/b&gt;" in page
    assert "name='lv_0' value='1D VAH|80500.0' checked" in page and "Heute noch keine Vorbereitung" in page
    assert "formnovalidate" in page and "action='/my-day/save'" in page
    csp = my_day_csp(page)
    assert "form-action 'self'" in csp and "script-src 'none'" in csp
    # After an error the trader's own answers come back, untouched levels stay unticked.
    page = render_my_day({}, dp.empty_log(), "tok", levels, None, None, form={"plan": "'><i>p", "lv_1": "x"}, error="<i>kaputt</i>")
    assert "'><i>p" not in page and "<i>kaputt" not in page
    assert "name='lv_0' value='1D VAH|80500.0'>" in page and "name='lv_1' value='&lt;b&gt;x&lt;/b&gt;|80000.0' checked" in page


def test_prep_banner_links_the_form() -> None:
    assert "noch nicht vorbereitet" in prep_banner(None) and "href='/my-day'" in prep_banner(None)
    entry = dp.build_entry(_form(), T0, 1)
    assert "max 2,5 R, 3 Trades, Schluss 21:30" in prep_banner(entry)
    assert "No-Trade-Tag" in prep_banner(dp.build_entry({"kind": "NO_TRADE_DAY"}, T0, 2))
    assert "noch nicht vorbereitet" in _prep_page({}, {"levels": [], "htf": {}, "notes": ["Keine Daten."]}, None, with_day=True)
    assert "noch nicht vorbereitet" not in _prep_page({}, {"levels": [], "htf": {}, "notes": []})


def _post(port: int, fields: dict[str, str], origin: str | None = None, content_type: str = "application/x-www-form-urlencoded"):
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Content-Type": content_type, "Host": f"127.0.0.1:{port}"}
    if origin is not None:
        headers["Origin"] = origin
    connection.request("POST", "/my-day/save", body=urlencode(fields).encode(), headers=headers)
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response, payload


def test_server_round_trip_and_guards(tmp_path) -> None:
    state = DashboardState()
    state.daily_prep_path = tmp_path / "daily_prep.json"
    server = DashboardServer(state, port=0)
    server.start()
    port = server.server.server_address[1]
    token, origin = server.form_token, f"http://127.0.0.1:{port}"
    try:
        with urlopen(f"http://127.0.0.1:{port}/my-day", timeout=5) as response:
            assert response.status == 200 and token in response.read().decode()
            assert response.headers["Referrer-Policy"] == "same-origin"
            assert "form-action 'self'" in response.headers["Content-Security-Policy"]
        response, _ = _post(port, {**_form(), "token": token}, origin=origin)
        assert response.status == 303 and response.headers["Location"] == "/my-day?saved=DP-0001"
        assert _post(port, {**_form(), "token": "falsch"}, origin=origin)[0].status == 403
        assert _post(port, {**_form(), "token": token}, origin="https://evil.example")[0].status == 403
        assert _post(port, {**_form(), "token": token}, content_type="text/plain")[0].status == 415
        response, payload = _post(port, {**_form(oath=None, plan="Mein Plan"), "token": token}, origin=origin)
        assert response.status == 400 and "Eid fehlt" in payload.decode() and "Mein Plan" in payload.decode()
        with urlopen(f"http://127.0.0.1:{port}/api/my-day", timeout=5) as response:
            data = json.loads(response.read())
        assert [e["id"] for e in data["entries"]] == ["DP-0001"]
        with urlopen(f"http://127.0.0.1:{port}/my-day?saved=DP-0001", timeout=5) as response:
            assert "Gespeichert: DP-0001" in response.read().decode()
        with urlopen(f"http://127.0.0.1:{port}/prep", timeout=5) as response:
            page = response.read().decode()
        assert "Mein Tag" in page
    finally:
        server.stop()
