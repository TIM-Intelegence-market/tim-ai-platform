"""Level-Übersicht (src/dashboard/level_overview.py): zones, range, readings and the shadow log of zone visits."""
from __future__ import annotations

from datetime import datetime, timedelta

from src.dashboard import level_overview as lo
from tests.test_analysis_summary import NOW, _trending_series


def line(label: str, price: float, weight: int = 1) -> dict:
    return {"label": label, "price": price, "weight": weight, "group": "x"}


def view(price: float, here: dict | None = None, as_of: str = "2026-11-12T12:00:00+00:00") -> dict:
    return {"as_of": as_of, "price": price, "pad": 50.0, "bias": "gemischt", "here": here}


def test_lines_close_together_become_one_zone_with_summed_weight():
    lines = [line("1D VAL", 100.0, 2), line("1W VWAP", 100.4, 3), line("1M POC", 100.9, 4), line("1D High", 110.0, 2)]
    out = lo.zones(lines, 105.0, tolerance=0.5)
    assert [(z["low"], z["high"], z["weight"]) for z in out] == [(100.0, 100.9, 9), (110.0, 110.0, 2)]
    assert out[0]["strength"] == "stark" and out[0]["side"] == "unter" and out[1]["strength"] == "schwach" and out[1]["side"] == "über"
    assert out[0]["labels"] == ["1D VAL", "1W VWAP", "1M POC"]


def test_same_label_counts_once_and_price_inside_a_zone_is_am_kurs():
    out = lo.zones([line("1D POC", 100.0, 2), line("1D POC", 100.1, 2)], 100.3, tolerance=0.5)
    assert out[0]["weight"] == 2 and out[0]["side"] == "am Kurs"


def test_absorption_marks_the_zone_it_was_seen_in():
    flow = {"levels": [{"price": 100.2, "absorption": True}, {"price": 110.0, "absorption": False}]}
    out = lo.zones([line("a", 100.0), line("b", 110.0)], 105.0, 0.5, flow)
    assert out[0]["absorption"] and not out[1]["absorption"]


def test_watch_prefers_the_nearest_zone_of_medium_weight():
    weak, medium = {"weight": 1}, {"weight": lo.MEDIUM}
    assert lo._watch([weak, medium]) is medium and lo._watch([weak]) is weak and lo._watch([]) is None


def test_reading_runs_from_edge_to_edge_with_the_stop_behind_the_zone():
    lower = {"low": 99.0, "high": 100.0}
    upper = {"low": 110.0, "high": 111.0}
    long = lo._reading("LONG", lower, upper, 1.0, "aufwärts")
    assert (long["entry"], long["stop"], long["target"], long["rr"], long["structure"]) == (100.0, 98.0, 110.0, 5.0, "mit der Struktur")
    short = lo._reading("SHORT", upper, lower, 1.0, "aufwärts")
    assert (short["entry"], short["stop"], short["target"], short["structure"]) == (110.0, 112.0, 100.0, "gegen die Struktur")
    assert lo._reading("LONG", None, upper, 1.0, "gemischt") is None


def test_build_uses_only_closed_candles_and_renders():
    series = _trending_series()
    now_view = lo.build(series, NOW)
    assert now_view and now_view["ruleset"] == lo.RULESET and now_view["lines"] > 0 and now_view["zones"] <= now_view["lines"]
    earlier = NOW - timedelta(hours=10)
    cut = {tf: [c for c in rows if datetime.fromisoformat(str(c["close_time"]).replace("Z", "+00:00")) <= earlier] for tf, rows in series.items()}
    past, same = lo.build(series, earlier), lo.build(cut, earlier)
    assert past["price"] == same["price"] and past["zones"] == same["zones"]  # candles closing after ``earlier`` change nothing
    assert past["price"] != now_view["price"]
    html = lo.render_de(now_view, None)
    assert "Level-Übersicht" in html and "keine Order" in html and "S22 bis S30" in html
    assert "Kurs" in lo.text(now_view) and lo.text(None) == "Level-Übersicht: keine Kerzen."
    assert "keine Level-Übersicht" in lo.render_de(None)


def test_track_opens_a_visit_and_closes_it_as_rejected_or_accepted():
    zone = {"low": 100.0, "high": 101.0, "labels": ["1D VAL"], "weight": 3, "strength": "mittel", "absorption": True}
    state = lo.track(None, view(105.0))
    assert state["open"] == [] and state["last_price"] == 105.0
    state = lo.track(state, view(100.5, zone))  # came from above into the zone
    assert len(state["open"]) == 1 and state["open"][0]["from"] == "oben" and state["open"][0]["absorption"]
    state = lo.track(state, view(100.8, zone))  # still inside: no second visit
    assert len(state["open"]) == 1 and not state["visits"]
    rejected = lo.track(state, view(160.0))  # left above, where it came from
    assert rejected["visits"][-1]["outcome"] == "abgelehnt" and rejected["open"] == []
    accepted = lo.track(state, view(40.0))  # went through
    assert accepted["visits"][-1]["outcome"] == "akzeptiert"
    assert lo.summary(accepted) == {"open": 0, "closed": 1, "rejected": 0, "accepted": 1}


def test_track_needs_to_know_the_side_the_price_came_from():
    zone = {"low": 100.0, "high": 101.0, "labels": ["x"], "weight": 1, "strength": "schwach"}
    assert lo.track(None, view(100.5, zone))["open"] == []  # first step ever: origin unknown


def test_update_writes_its_own_file_only(tmp_path):
    path = tmp_path / "watch.json"
    state = lo.update(path, _trending_series(), None, NOW)
    assert state["schema"] == lo.SCHEMA and lo.load(path)["ruleset"] == lo.RULESET
    assert sorted(p.name for p in tmp_path.iterdir()) == ["watch.json"]
    assert lo.update(tmp_path / "none.json", {}, None, NOW) is None
