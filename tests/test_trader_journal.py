from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

from src.dashboard.app import DashboardServer, DashboardState
from src.dashboard.pages.trader_journal import journal_csp, render_trader_journal
from src.dashboard import trader_journal as tj

T0 = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)  # a Wednesday


def _form(**overrides: str) -> dict[str, str]:
    form = {"direction": "LONG", "entry": "100", "stop": "95", "target": "110", "thesis": "Rücklauf zum VAH, gefangene Shorts",
            "in_plan": "ja", "saw_setup": "ja", "timing": "ja", "rules": "ja", "c_htf_bias": "1", "c_value_edge": "1"}
    form.update(overrides)
    return form


def _m(minute: int, o: float, h: float, l: float, c: float) -> dict:
    opened = T0 + timedelta(minutes=minute)
    return {"symbol": "BTCUSDT", "timeframe": "1m", "open_time": opened.isoformat(), "close_time": (opened + timedelta(seconds=59.999)).isoformat(),
            "open": o, "high": h, "low": l, "close": c, "volume": 1.0}


def test_entry_validates_direction_and_levels() -> None:
    entry = tj.build_entry(_form(), {"bias": "LONG"}, T0, 1)
    assert entry["id"] == "TJ-0001" and entry["kind"] == "TRADE" and entry["status"] == "OPEN"
    assert entry["planned_r"] == 2.0 and entry["confluences"] == ["htf_bias", "value_edge"] and entry["warnings"] == []
    with pytest.raises(tj.JournalError, match="Long: Stop unter"):
        tj.build_entry(_form(stop="105"), {}, T0, 1)
    with pytest.raises(tj.JournalError, match="Short: Stop über"):
        tj.build_entry(_form(direction="SHORT"), {}, T0, 1)
    with pytest.raises(tj.JournalError, match="Richtung"):
        tj.build_entry(_form(direction="BUY"), {}, T0, 1)
    with pytest.raises(tj.JournalError, match="Zahl"):
        tj.build_entry(_form(entry="viel"), {}, T0, 1)
    with pytest.raises(tj.JournalError, match="Bereich"):
        tj.build_entry(_form(entry="inf"), {}, T0, 1)
    with pytest.raises(tj.JournalError, match="These"):
        tj.build_entry(_form(thesis="  "), {}, T0, 1)
    with pytest.raises(tj.JournalError, match="Timing"):
        tj.build_entry(_form(timing=""), {}, T0, 1)


def test_entry_accepts_german_and_english_number_formats() -> None:
    entry = tj.build_entry(_form(entry="83.250,5", stop="83 000", target="83,900.25"), {}, T0, 1)
    assert (entry["entry"], entry["stop"], entry["target"]) == (83250.5, 83000.0, 83900.25)


def test_one_no_in_the_flowchart_books_a_no_trade() -> None:
    entry = tj.build_entry(_form(timing="nein", rules="nein"), {}, T0, 2)
    assert entry["kind"] == "NO_TRADE" and entry["status"] == "NO_TRADE" and entry["gate_failed"] == ["timing", "rules"]
    journal = {"schema": tj.SCHEMA, "entries": [entry]}
    tj.evaluate(journal, [_m(1, 100, 101, 90, 91)], T0 + timedelta(minutes=5))
    assert entry["status"] == "NO_TRADE"


def test_warnings_flag_bias_weekend_and_small_reward() -> None:
    entry = tj.build_entry(_form(target="104"), {"bias": "SHORT", "weekend": True, "ny_open_block": True}, T0, 1)
    assert entry["warnings"] == ["gegen den HTF-Bias (SHORT)", "Wochenende: Broncx handelt am Wochenende nicht", "im NY-Open-Block", "Chance-Risiko nur 0.80 R"]


def test_context_snapshot_marks_weekend_and_ny_block() -> None:
    saturday = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
    assert tj.context_snapshot(None, saturday) == {"weekend": True, "ny_open_block": False}
    model = {"bias": {"bias": "LONG", "text": "Long-Bias"}, "location": {"state": "IN_VALUE", "label": "im Vortages-Value"}, "levels": [], "last": 100.0}
    context = tj.context_snapshot(model, T0)
    assert context["bias"] == "LONG" and context["location"] == "IN_VALUE" and "Long-Bias" in context["summary"] and context["weekend"] is False


def _journal(*forms: dict[str, str]) -> dict:
    return {"schema": tj.SCHEMA, "entries": [tj.build_entry(f, {}, T0, i + 1) for i, f in enumerate(forms)]}


def test_evaluate_fills_then_hits_target_with_excursions() -> None:
    journal = _journal(_form())
    candles = [_m(0, 103, 104, 102, 103), _m(1, 103, 103, 99.5, 101), _m(2, 101, 106, 97, 105), _m(3, 105, 111, 104, 110)]
    tj.evaluate(journal, candles, T0 + timedelta(minutes=5))
    entry = journal["entries"][0]
    # Minute 0 opened at T0, the moment of the entry: it already counts (open_time >= created_at).
    assert entry["status"] == "CLOSED" and entry["exit_reason"] == "TARGET" and entry["result_r"] == 2.0
    assert entry["filled_at"] == "2026-10-21T10:01:00Z"
    assert entry["max_adverse_r"] == -0.6 and entry["max_favorable_r"] == 2.2


def test_evaluate_counts_the_stop_first_and_on_the_fill_candle() -> None:
    both = _journal(_form())
    tj.evaluate(both, [_m(1, 100, 100, 99, 99.5), _m(2, 99, 111, 94, 100)], T0 + timedelta(minutes=5))
    assert both["entries"][0]["exit_reason"] == "STOP" and both["entries"][0]["result_r"] == -1.0
    fill_and_stop = _journal(_form())
    tj.evaluate(fill_and_stop, [_m(1, 101, 101, 94, 95)], T0 + timedelta(minutes=5))
    assert fill_and_stop["entries"][0]["status"] == "CLOSED" and fill_and_stop["entries"][0]["exit_reason"] == "STOP"


def test_evaluate_short_and_limit_above_market() -> None:
    short = _journal(_form(direction="SHORT", entry="100", stop="104", target="92"))
    tj.evaluate(short, [_m(1, 99, 100.5, 98, 99), _m(2, 99, 99, 91, 92)], T0 + timedelta(minutes=5))
    assert short["entries"][0]["exit_reason"] == "TARGET" and short["entries"][0]["result_r"] == 2.0
    # A buy limit above the market fills at once (recorded at the limit price).
    above = _journal(_form(entry="100", stop="95", target="110"))
    tj.evaluate(above, [_m(1, 97, 98, 96, 97)], T0 + timedelta(minutes=5))
    assert above["entries"][0]["status"] == "FILLED"


def test_evaluate_expires_and_times_out() -> None:
    pending = _journal(_form(entry="90", stop="85", target="100"))
    tj.evaluate(pending, [_m(60 * 24, 99, 100, 98, 99)], T0 + timedelta(days=2))
    assert pending["entries"][0]["status"] == "EXPIRED"
    running = _journal(_form())
    tj.evaluate(running, [_m(1, 100, 101, 99, 100), _m(60 * 72 + 2, 102, 103, 101, 102)], T0 + timedelta(days=4))
    entry = running["entries"][0]
    assert entry["exit_reason"] == "TIMEOUT" and entry["result_r"] == 0.4 and "data_gap" in entry


def test_evaluate_continues_from_where_it_stopped() -> None:
    journal = _journal(_form())
    tj.evaluate(journal, [_m(1, 100, 101, 99, 100)], T0 + timedelta(minutes=2))
    tj.evaluate(journal, [_m(1, 100, 101, 99, 100), _m(2, 100, 100, 94, 95)], T0 + timedelta(minutes=3))
    assert journal["entries"][0]["exit_reason"] == "STOP" and journal["entries"][0]["closed_at"] == "2026-10-21T10:02:59.999000Z"


def test_file_round_trip_review_cancel_and_summary(tmp_path) -> None:
    path = tmp_path / "trader_journal.json"
    first = tj.add_entry(path, _form(), None, now=T0)
    second = tj.add_entry(path, _form(rules="nein"), None, now=T0)
    third = tj.add_entry(path, _form(entry="80", stop="75", target="90"), None, now=T0)
    with pytest.raises(tj.JournalError, match="läuft noch"):
        tj.add_review(path, {"id": first["id"], "happened": "a", "why": "b", "again": "ja", "learned": "c"})
    tj.update(path, {"1m": [_m(1, 100, 100, 99, 99.5), _m(2, 100, 111, 99, 110)]}, now=T0 + timedelta(minutes=5))
    tj.cancel_entry(path, {"id": third["id"]})
    with pytest.raises(tj.JournalError, match="Nur ein noch nicht"):
        tj.cancel_entry(path, {"id": first["id"]})
    with pytest.raises(tj.JournalError, match="Würde ich"):
        tj.add_review(path, {"id": first["id"], "happened": "a", "why": "b", "learned": "c"})
    tj.add_review(path, {"id": first["id"], "happened": "Ziel erreicht", "why": "Value angenommen", "again": "ja", "learned": "geduldig sein"})
    journal = tj.load(path)
    assert [e["status"] for e in journal["entries"]] == ["CLOSED", "NO_TRADE", "CANCELLED"]
    assert journal["entries"][0]["review"]["learned"] == "geduldig sein"
    stats = tj.summary(journal)
    assert stats["trades"] == 2 and stats["no_trades"] == 1 and stats["closed"] == 1 and stats["sum_r"] == 2.0
    assert stats["gate_failures"]["rules"] == 1 and stats["review_open"] == 2
    assert stats["weeks"] == [{"week": "2026-W43", "trades": 2, "no_trades": 1, "closed": 1, "wins": 1, "sum_r": 2.0, "reviewed": 1}]
    assert second["id"] == "TJ-0002"
    # Nothing open any more: the runtime step leaves the file alone.
    assert tj.update(path, {"1m": []}) is None


def test_load_rejects_foreign_files(tmp_path) -> None:
    path = tmp_path / "x.json"
    path.write_text('{"schema": "other", "entries": []}', encoding="utf-8")
    assert tj.load(path) == tj.empty_journal()
    path.write_text("kaputt", encoding="utf-8")
    assert tj.load(path) == tj.empty_journal()


def test_page_escapes_input_and_has_no_script() -> None:
    entry = tj.build_entry(_form(thesis="<script>alert(1)</script>"), {}, T0, 1)
    page = render_trader_journal({}, {"schema": tj.SCHEMA, "entries": [entry]}, "tok", "Long-Bias", form={"entry": "'><b>x"}, error="<i>kaputt</i>")
    assert "<script>alert" not in page and "&lt;script&gt;" in page and "<i>kaputt" not in page and "'><b>x" not in page
    assert "<script" not in page
    csp = journal_csp(page)
    assert "form-action 'self'" in csp and "script-src 'none'" in csp
    assert "action='/trader-journal/entry'" in page and "zurückziehen" in page


def _state(tmp_path) -> DashboardState:
    state = DashboardState()
    state.trader_journal_path = tmp_path / "trader_journal.json"
    return state


def _post(port: int, path: str, fields: dict[str, str], origin: str | None = None, content_type: str = "application/x-www-form-urlencoded"):
    body = urlencode(fields).encode()
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Content-Type": content_type, "Host": f"127.0.0.1:{port}"}
    if origin is not None:
        headers["Origin"] = origin
    connection.request("POST", path, body=body, headers=headers)
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response, payload


def test_server_journal_form_round_trip_and_guards(tmp_path) -> None:
    server = DashboardServer(_state(tmp_path), port=0)
    server.start()
    port = server.server.server_address[1]
    token = server.form_token
    try:
        with urlopen(f"http://127.0.0.1:{port}/trader-journal", timeout=5) as response:
            page = response.read().decode()
            assert response.status == 200 and token in page
            assert response.headers["Referrer-Policy"] == "same-origin"
            assert "form-action 'self'" in response.headers["Content-Security-Policy"]
        origin = f"http://127.0.0.1:{port}"
        response, _ = _post(port, "/trader-journal/entry", {**_form(), "token": token}, origin=origin)
        assert response.status == 303 and response.headers["Location"] == "/trader-journal?saved=TJ-0001"
        # Wrong token, foreign origin, wrong encoding: refused, nothing written.
        assert _post(port, "/trader-journal/entry", {**_form(), "token": "falsch"}, origin=origin)[0].status == 403
        assert _post(port, "/trader-journal/entry", {**_form(), "token": token}, origin="https://evil.example")[0].status == 403
        assert _post(port, "/trader-journal/entry", {**_form(), "token": token}, content_type="text/plain")[0].status == 415
        response, payload = _post(port, "/trader-journal/entry", {**_form(stop="120"), "token": token}, origin=origin)
        assert response.status == 400 and "Long: Stop unter" in payload.decode() and "value='120'" in payload.decode()
        response, _ = _post(port, "/trader-journal/cancel", {"id": "TJ-0001", "token": token}, origin=origin)
        assert response.status == 303
        with urlopen(f"http://127.0.0.1:{port}/api/trader-journal", timeout=5) as response:
            data = json.loads(response.read())
        assert [e["status"] for e in data["entries"]] == ["CANCELLED"] and data["summary"]["trades"] == 1
        with urlopen(f"http://127.0.0.1:{port}/trader-journal?saved=TJ-0001", timeout=5) as response:
            assert "Gespeichert: TJ-0001" in response.read().decode()
    finally:
        server.stop()


def test_empty_form_fields_stay_empty() -> None:
    page = render_trader_journal({}, tj.empty_journal(), "tok", "–")
    assert "name='entry' inputmode='decimal' required value=''" in page and "required></textarea>" in page
