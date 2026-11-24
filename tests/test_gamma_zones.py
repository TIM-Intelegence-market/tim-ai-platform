"""Gamma zones confirmed by the order book: walls, archive reader, confirmation, chart band and shadow log."""
from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from types import SimpleNamespace

from src.dashboard import gamma_zones
from src.research_lab.orderbook import walls
from src.research_lab.orderbook.book import Book

T0 = 1_800_000_000_000  # ms


def _book(wall_bid: float = 0.0, wall_ask: float = 0.0) -> Book:
    """Mid 100 000, one unit per 50 USD bucket on 40 buckets per side, optional walls at 99 000 and 101 000."""
    book = Book()
    snap = {"lastUpdateId": 1,
            "bids": [[f"{99_990 - 50 * i:.1f}", "1"] for i in range(40)],
            "asks": [[f"{100_010 + 50 * i:.1f}", "1"] for i in range(40)]}
    if wall_bid:
        snap["bids"].append(["99010.0", str(wall_bid)])
    if wall_ask:
        snap["asks"].append(["101020.0", str(wall_ask)])
    book.load_snapshot(snap)
    return book


def test_wall_needs_enter_factor_and_thirty_minutes() -> None:
    tracker = walls.Tracker(50.0)
    tracker.scan(T0, _book(wall_bid=3.0))            # bucket 99 000 holds 4, below 5 x median 1
    assert not tracker.walls
    for minute in range(30):
        tracker.scan(T0 + minute * 60_000, _book(wall_bid=9.0))
    assert tracker.walls and tracker.standing() == []  # 29 minutes old
    tracker.scan(T0 + 30 * 60_000, _book(wall_bid=9.0))
    (wall,) = tracker.standing()
    assert (wall["side"], wall["low"], wall["high"], wall["qty"]) == ("bid", 99_000.0, 99_050.0, 10.0)
    assert wall["notional_usd"] == (10 * 99_025)


def test_wall_stays_on_stay_factor_and_goes_when_pulled_or_after_a_hole() -> None:
    tracker = walls.Tracker(50.0)
    for minute in range(31):
        tracker.scan(T0 + minute * 60_000, _book(wall_ask=9.0))
    assert len(tracker.standing()) == 1
    tracker.scan(T0 + 31 * 60_000, _book(wall_ask=2.0))   # 3 x median: kept (stay factor 2.5)
    assert len(tracker.standing()) == 1
    tracker.scan(T0 + 32 * 60_000, _book(wall_ask=0.5))   # pulled
    assert tracker.standing() == []
    for minute in range(33, 70):
        tracker.scan(T0 + minute * 60_000, _book(wall_ask=9.0))
    assert len(tracker.standing()) == 1
    tracker.scan(T0 + 80 * 60_000, _book(wall_ask=9.0))   # 10 minutes without a scan: age starts again
    assert tracker.standing() == []


def _rows(start_ms: int, minutes: int, wall: str, first_u: int = 2) -> list[dict]:
    rows = []
    for i in range(minutes):
        u = first_u + i
        rows.append({"kind": "depth", "recv_ms": start_ms + i * 60_000,
                     "msg": {"e": "depthUpdate", "E": start_ms + i * 60_000, "s": "BTCUSDT", "U": u - 1, "u": u, "pu": u - 1,
                             "b": [["99010.0", wall]], "a": []}})
    return rows


def _snapshot_row(at_ms: int) -> dict:
    book = _book()
    return {"kind": "snapshot", "recv_ms": at_ms,
            "msg": {"lastUpdateId": 1, "bids": [[p, str(q)] for p, q in book.bids.items()],
                    "asks": [[p, str(q)] for p, q in book.asks.items()]}}


def test_tail_follows_a_growing_segment_and_the_next_day(tmp_path: Path) -> None:
    folder = tmp_path / "BTCUSDT"
    folder.mkdir()
    first = folder / "2027-01-15.100.jsonl.gz"
    fh = gzip.open(first, "xb")
    rows = [_snapshot_row(T0)] + _rows(T0, 20, "9")
    fh.write(("\n".join(json.dumps(r) for r in rows) + "\n").encode())
    fh.flush()                                           # the recorder's sync flush: file still open
    tail = walls.Tail(tmp_path, "BTCUSDT")
    assert tail.advance() is True
    assert tail.book.synced and tail.view()["walls"] == [] and tail.view()["candidates"] == 1
    more = _rows(T0 + 20 * 60_000, 15, "9", first_u=22)
    fh.write(("\n".join(json.dumps(r) for r in more) + "\n").encode())
    fh.flush()
    assert tail.advance() is True
    assert [w["low"] for w in tail.view()["walls"]] == [99_000.0]
    fh.close()
    second = folder / "2027-01-16.100.jsonl.gz"          # same run, next day: the book goes on
    with gzip.open(second, "xb") as fh2:
        fh2.write((json.dumps(_rows(T0 + 35 * 60_000, 1, "0", first_u=37)[0]) + "\n").encode())
    assert tail.advance() is True
    assert tail.path == second and tail.book.synced and tail.view()["walls"] == []


def test_tail_reads_in_small_steps_and_survives_a_missing_archive(tmp_path: Path) -> None:
    assert walls.Tail(tmp_path, "BTCUSDT").advance() is False
    folder = tmp_path / "BTCUSDT"
    folder.mkdir()
    rows = [_snapshot_row(T0)] + _rows(T0, 40, "9")
    with gzip.open(folder / "2027-01-15.100.jsonl.gz", "xb") as fh:
        fh.write(("\n".join(json.dumps(r) for r in rows) + "\n").encode())
    tail = walls.Tail(tmp_path, "BTCUSDT")
    steps = 0
    while not tail.advance(max_bytes=200):
        steps += 1
        assert steps < 500
    assert steps > 1 and len(tail.view()["walls"]) == 1


WALL = {"side": "bid", "low": 99_000.0, "high": 99_050.0, "qty": 400.0, "ratio": 8.0, "notional_usd": 39_610_000,
        "since_ms": T0}
LEVELS = [{"key": "put_wall", "name": "Put Wall", "price": 99_200.0, "note": ""},
          {"key": "oi_put", "name": "Put-OI-Wand", "price": 99_000.0, "note": ""},
          {"key": "call_wall", "name": "Call Wall", "price": 105_000.0, "note": ""},
          {"key": "max_pain", "name": "Max Pain", "price": 99_020.0, "note": ""}]


def test_confirm_only_gamma_levels_near_a_wall_and_merges_levels_on_one_wall() -> None:
    (zone,) = gamma_zones.confirm(LEVELS, [WALL])
    assert zone["name"] == "Put-OI-Wand + Put Wall" and (zone["low"], zone["high"]) == (99_000.0, 99_200.0)
    far = [{**LEVELS[0], "price": 99_400.0}]             # 350 USD above the wall edge, tolerance 298
    assert gamma_zones.confirm(far, [WALL]) == []
    assert gamma_zones.confirm([LEVELS[3]], [WALL]) == []  # max pain is not a gamma level


def _walls_view(now: datetime, **over) -> dict:
    return {"last_event_ms": int(now.timestamp() * 1000) - 5_000, "caught_up": True, "synced": True,
            "mid": 99_500.0, "walls": [WALL], **over}


def _gamma(now: datetime, age: timedelta = timedelta(minutes=2)) -> dict:
    return {"levels": LEVELS, "as_of": (now - age).isoformat()}


def _view(now: datetime, **over) -> dict:
    return gamma_zones.build(_gamma(now), _walls_view(now, **over), now)


def test_build_hides_zones_when_the_book_is_old_or_still_read_in() -> None:
    now = datetime(2027, 1, 15, 12, tzinfo=timezone.utc)
    assert _view(now)["status"] == "OK" and len(_view(now)["zones"]) == 1
    stale = _view(now, last_event_ms=int((now - timedelta(minutes=11)).timestamp() * 1000))
    assert (stale["status"], stale["zones"]) == ("STALE", [])
    assert _view(now, caught_up=False)["status"] == "CATCHING_UP"
    assert _view(now, synced=False)["status"] == "STALE"
    assert gamma_zones.build({"levels": LEVELS}, None, now)["status"] == "MISSING"
    assert gamma_zones.build(None, {"last_event_ms": int(now.timestamp() * 1000), "caught_up": True, "synced": True, "walls": [WALL]}, now)["status"] == "NO_GAMMA"


def test_chart_drawing_is_a_band_with_a_plain_note() -> None:
    now = datetime(2027, 1, 15, 12, tzinfo=timezone.utc)
    watch = {"visits": [{"outcome": "gehalten", "ruleset": gamma_zones.RULESET}, {"outcome": "gebrochen", "ruleset": gamma_zones.RULESET}]}
    drawings, notes = gamma_zones.chart_drawings(_view(now), watch, now)
    (drawing,) = drawings
    assert drawing["group"] == "gamma_ob" and drawing["band"] == [99_000.0, 99_200.0] and drawing["price"] == 99_000.0
    assert "Kaufmauer" in drawing["note"] and "zurückgezogen" in drawing["note"]
    assert notes == ["Gamma-Level mit Orderbuch-Mauer: 1, Berührungen 2 (1 gehalten, 1 gebrochen), Urteil ab 30."]
    assert gamma_zones.chart_drawings(_view(now), None, now + timedelta(minutes=11)) == ([], [])


def test_shadow_log_counts_held_broken_and_pulled() -> None:
    now = datetime(2027, 1, 15, 12, tzinfo=timezone.utc)
    view = _view(now)

    def step(state, price, minute, v=view):
        return gamma_zones.track(state, v, price, (now + timedelta(minutes=minute)).isoformat())

    state = step(None, 99_500.0, 0)
    assert state["open"] == []
    state = step(state, 99_150.0, 1)                      # into the zone from above
    assert state["open"][0]["from"] == "oben" and state["open"][0]["wall_pulled"] is False
    state = step(state, 99_100.0, 2)
    assert len(state["open"]) == 1 and state["visits"] == []
    state = step(state, 99_400.0, 3)                      # out on the side it came from
    assert state["visits"][-1]["outcome"] == "gehalten" and state["open"] == []
    state = step(state, 99_100.0, 4)
    pulled = {**view, "zones": []}
    state = step(state, 99_050.0, 5, pulled)              # wall gone while the visit runs
    assert state["open"][0]["wall_pulled"] is True
    state = step(state, 98_800.0, 6, pulled)              # through
    assert state["visits"][-1]["outcome"] == "gebrochen" and state["visits"][-1]["wall_pulled"] is True
    assert gamma_zones.summary(state) == {"open": 0, "closed": 2, "held": 1, "broken": 1, "pulled": 1,
                                          "earlier_open": 0, "earlier_closed": 0}
    state = step(state, 99_500.0, 7)
    state = step(state, 99_100.0, 30)                     # 23 minutes without a step: side unknown, no visit
    assert state["open"] == []


def test_refresh_and_update_write_only_state_and_their_own_file(tmp_path: Path) -> None:
    folder = tmp_path / "book" / "BTCUSDT"
    folder.mkdir(parents=True)
    now = datetime.fromtimestamp((T0 + 39 * 60_000) / 1000, timezone.utc)
    with gzip.open(folder / "2027-01-15.100.jsonl.gz", "xb") as fh:
        fh.write(("\n".join(json.dumps(r) for r in [_snapshot_row(T0)] + _rows(T0, 40, "9")) + "\n").encode())
    state = SimpleNamespace(lock=RLock(), gamma={"BTCUSDT": {"as_of": (now - timedelta(minutes=3)).isoformat(),
                                                             "levels": [{"key": "put_wall", "name": "Put Wall", "price": 99_100.0, "note": ""}]}}, gamma_zones={})
    gamma_zones._TAILS.clear()
    view = gamma_zones.refresh(state, "BTCUSDT", root=tmp_path / "book", now=now)
    assert view["status"] == "OK" and state.gamma_zones["BTCUSDT"]["zones"][0]["name"] == "Put Wall"
    assert gamma_zones.refresh(state, "ETHUSDT", root=tmp_path / "book") is None
    path = tmp_path / "journal" / "watch.json"
    saved = gamma_zones.update(path, view, view["mid"], now)
    assert saved["ruleset"] == gamma_zones.RULESET and gamma_zones.load(path)["last_price"] == view["mid"]
    assert gamma_zones.update(path, None, 1.0) is None
    assert sorted(p.name for p in (tmp_path / "journal").iterdir()) == ["watch.gamma-orderbuch-1.2.json"]


def test_chart_model_carries_the_group_and_the_script_draws_the_band() -> None:
    from src.dashboard.chart_live import DEFAULT_GROUPS, GROUP_NAMES
    from src.dashboard.public_en import GROUPS_EN

    assert "gamma_ob" in DEFAULT_GROUPS and "gamma_ob" in GROUP_NAMES and "gamma_ob" in GROUPS_EN
    script = (Path(__file__).resolve().parents[1] / "src/dashboard/assets/tim_chart.js").read_text(encoding="utf-8")
    assert "d.group === 'gamma_ob' && Array.isArray(d.band)" in script
    assert "zoneFill.visible = groups.has('gamma_ob')" in script


def test_tail_skips_old_rows_unparsed_and_starts_at_the_first_snapshot_in_the_window(tmp_path: Path) -> None:
    folder = tmp_path / "BTCUSDT"
    folder.mkdir()
    later = T0 + 100 * 60_000
    rows = [_snapshot_row(T0)] + _rows(T0, 100, "9") + [_snapshot_row(later)] + _rows(later, 5, "9")
    with gzip.open(folder / "2027-01-15.100.jsonl.gz", "xb") as fh:
        fh.write(("\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n").encode())
    tail = walls.Tail(tmp_path, "BTCUSDT", skip_before_ms=later)
    assert tail.advance() is True
    assert tail.book.synced and tail.view()["candidates"] == 1 and tail.view()["walls"] == []  # the wall is 4 minutes old here
    assert walls._recv_ms(b'{"kind":"gap","from_ms":1,"to_ms":2}') > later
    assert walls._recv_ms(b'{"kind":"depth","recv_ms":123,"msg":{}}') == 123


def test_zone_uses_every_standing_wall_not_only_the_five_largest() -> None:
    """Offline check 22.11.2026: a smaller wall right at the put wall dropped out behind five larger walls further away."""
    book = Book()
    bids = [[f"{99_990 - 50 * i:.1f}", "1"] for i in range(40)]
    for k in range(5):                                         # five large walls far below the level
        bids.append([f"{98_060 + 50 * k:.1f}", "20"])
    bids.append(["99010.0", "6"])                                # the small wall at the level (bucket 99 000 holds 7)
    book.load_snapshot({"lastUpdateId": 1, "bids": bids, "asks": [[f"{100_010 + 50 * i:.1f}", "1"] for i in range(40)]})
    tracker = walls.Tracker(50.0)
    for minute in range(31):
        tracker.scan(T0 + minute * 60_000, book)
    shown, every = tracker.standing(), tracker.standing(None)
    assert len(shown) == 5 and all(w["low"] < 98_400 for w in shown)
    assert any(w["low"] == 99_000.0 for w in every) and len(every) == 6
    now = datetime(2027, 1, 15, 12, tzinfo=timezone.utc)
    view = _view(now, walls=shown, walls_all=every)
    assert view["ruleset"] == "gamma-orderbuch/1.2" and len(view["walls"]) == 5
    (zone,) = view["zones"]
    assert zone["wall_low"] == 99_000.0 and "Put Wall" in zone["name"]
    assert _view(now, walls=shown)["zones"] == []               # an old reader without walls_all keeps the old answer


def test_public_page_gets_the_zones_in_english() -> None:
    """Uzi 22.11.2026 "öffentlich": the yellow zones on tim-online.online too, without German text."""
    from src.dashboard.public_en import english_chart_model

    now = datetime(2027, 1, 15, 12, tzinfo=timezone.utc)
    watch = {"visits": [{"outcome": "gehalten", "ruleset": gamma_zones.RULESET}, {"outcome": "gebrochen", "ruleset": gamma_zones.RULESET}]}
    drawings, notes = gamma_zones.chart_drawings(_view(now), watch, now)
    model = english_chart_model({"drawings": drawings, "notes": notes, "groups": {"gamma_ob": "x"}})
    (drawing,) = model["drawings"]
    assert drawing["label"].startswith("Gamma zone ") and drawing["band"] == [99_000.0, 99_200.0]
    assert drawing["note"].startswith("Gamma level ") and "buy wall" in drawing["note"] and "pulled at any time" in drawing["note"]
    assert model["notes"] == ["Gamma levels with an order book wall nearby: 1, touches 2 (1 held, 1 broken), verdict from 30. Display only, not a signal."]
    script = (Path(__file__).resolve().parents[1] / "src/dashboard/public_server.py").read_text(encoding="utf-8")
    assert "gamma_zones=gamma_zones" in script


# --- 1.2: both sources fresh (24.11.2026) -------------------------------------------------------------------------

NOW = datetime(2027, 1, 15, 12, tzinfo=timezone.utc)


def _status(gamma, walls_view, now: datetime = NOW) -> dict:
    view = gamma_zones.build(gamma, walls_view, now)
    if view["status"] != "OK":
        assert view["zones"] == [], view["status"]
    return view


def test_missing_gamma_or_gamma_without_a_valid_time_hides_the_zones() -> None:
    for gamma in (None, {}, {"levels": []}, {"levels": LEVELS}, {"levels": LEVELS, "as_of": None},
                  {"levels": LEVELS, "as_of": "gestern"}, {"levels": LEVELS, "as_of": "2027-01-15T11:58:00"}):  # naive: no zone
        view = _status(gamma, _walls_view(NOW))
        assert view["status"] == "NO_GAMMA" and view["gamma_as_of"] is None and view["gamma_age_seconds"] is None
        assert view["walls_as_of"] is not None and view["walls"]          # the book is fresh, its walls are still shown


def test_stale_gamma_with_a_fresh_book_is_not_ok() -> None:
    """The bug of 1.1: an old gamma snapshot plus a fresh book gave status OK and zones."""
    limit = gamma_zones.GAMMA_STALE_AFTER
    assert limit is gamma_zones.gamma_data.STALE_AFTER
    old = _status(_gamma(NOW, limit + timedelta(seconds=1)), _walls_view(NOW))
    assert old["status"] == "STALE_GAMMA" and old["gamma_age_seconds"] == int(limit.total_seconds()) + 1
    at_limit = _status(_gamma(NOW, limit), _walls_view(NOW))
    assert at_limit["status"] == "OK" and len(at_limit["zones"]) == 1


def test_future_gamma_is_never_ok_and_a_large_skew_is_flagged_apart() -> None:
    """Codex #378: a gamma snapshot 30 s ahead is not yet available; no zone, even inside the clock tolerance."""
    skew = gamma_zones.FUTURE_SKEW
    ahead = _status(_gamma(NOW, -(skew + timedelta(seconds=1))), _walls_view(NOW))
    assert ahead["status"] == "FUTURE_GAMMA" and ahead["gamma_age_seconds"] < 0 and ahead["gamma_clock_skew_suspect"]
    small = _status(_gamma(NOW, -timedelta(seconds=30)), _walls_view(NOW))
    assert small["status"] == "FUTURE_GAMMA" and small["zones"] == [] and small["gamma_age_seconds"] == -30
    assert small["gamma_clock_skew_suspect"] is False                  # diagnosis apart from the gate
    assert _status(_gamma(NOW, timedelta(0)), _walls_view(NOW))["status"] == "OK"


def test_old_book_and_future_book_are_not_ok() -> None:
    old = _status(_gamma(NOW), _walls_view(NOW, last_event_ms=int((NOW - timedelta(minutes=11)).timestamp() * 1000)))
    assert old["status"] == "STALE"
    future_ms = int((NOW + gamma_zones.FUTURE_SKEW + timedelta(seconds=1)).timestamp() * 1000)
    future = _status(_gamma(NOW), _walls_view(NOW, last_event_ms=future_ms))
    assert future["status"] == "FUTURE_BOOK" and future["walls"] == []
    assert future["walls_clock_skew_suspect"] is True
    near_ms = int((NOW + timedelta(seconds=1)).timestamp() * 1000)
    near = _status(_gamma(NOW), _walls_view(NOW, last_event_ms=near_ms))
    assert near["status"] == "FUTURE_BOOK" and near["walls_clock_skew_suspect"] is False
    assert _status(_gamma(NOW), _walls_view(NOW, last_event_ms=int(NOW.timestamp() * 1000)))["status"] == "OK"


def test_every_view_carries_both_source_times() -> None:
    gamma = _gamma(NOW)
    for walls_view in (None, _walls_view(NOW), _walls_view(NOW, caught_up=False), _walls_view(NOW, synced=False)):
        view = _status(gamma, walls_view)
        assert {"gamma_as_of", "gamma_age_seconds", "walls_as_of"} <= set(view)
        assert view["gamma_as_of"] == gamma["as_of"] and view["gamma_age_seconds"] == 120
    assert _status(gamma, None)["walls_as_of"] is None
    assert _status(gamma, _walls_view(NOW))["walls_as_of"] == (NOW - timedelta(seconds=5)).isoformat()


def test_recovery_from_stale_gamma_gives_ok_again() -> None:
    walls_view = _walls_view(NOW)
    assert _status(_gamma(NOW, timedelta(minutes=30)), walls_view)["status"] == "STALE_GAMMA"
    fresh = _status(_gamma(NOW, timedelta(seconds=10)), walls_view)
    assert fresh["status"] == "OK" and len(fresh["zones"]) == 1 and fresh["gamma_age_seconds"] == 10


def test_invalid_states_never_open_a_visit_and_open_visits_close_by_price() -> None:
    ok = _view(NOW)
    future_ms = int((NOW + timedelta(hours=1)).timestamp() * 1000)
    invalid = [gamma_zones.build(_gamma(NOW, timedelta(hours=1)), _walls_view(NOW), NOW),
               gamma_zones.build(_gamma(NOW, -timedelta(hours=1)), _walls_view(NOW), NOW),
               gamma_zones.build(None, _walls_view(NOW), NOW),
               gamma_zones.build(_gamma(NOW), _walls_view(NOW, synced=False), NOW),
               gamma_zones.build(_gamma(NOW), _walls_view(NOW, last_event_ms=future_ms), NOW),
               {**ok, "status": "STALE_GAMMA"}]                       # zones left over in the view: still no visit
    assert [v["status"] for v in invalid] == ["STALE_GAMMA", "FUTURE_GAMMA", "NO_GAMMA", "STALE", "FUTURE_BOOK", "STALE_GAMMA"]

    def at(minute: int) -> str:
        return (NOW + timedelta(minutes=minute)).isoformat()

    for view in invalid:                                               # from above into the zone while invalid
        state = gamma_zones.track(gamma_zones.track(None, view, 99_500.0, at(0)), view, 99_150.0, at(1))
        assert state["open"] == [] and state["visits"] == [], view["status"]
    state = gamma_zones.track(gamma_zones.track(None, ok, 99_500.0, at(0)), ok, 99_150.0, at(1))
    assert len(state["open"]) == 1 and state["open"][0]["ruleset"] == gamma_zones.RULESET
    state = gamma_zones.track(state, invalid[0], 99_100.0, at(2))     # gamma turns stale: the visit stays open
    assert len(state["open"]) == 1 and state["open"][0]["wall_pulled"] is False   # zones unknown, not gone
    state = gamma_zones.track(state, invalid[0], 99_450.0, at(3))     # and closes by price
    assert state["open"] == [] and state["visits"][-1]["outcome"] == "gehalten"
    assert set(gamma_zones.WATCH_STATUSES) == {"OK", "NO_GAMMA", "STALE_GAMMA", "FUTURE_GAMMA"}   # only with a fresh book


def test_update_in_an_invalid_state_writes_no_visit(tmp_path: Path) -> None:
    path = tmp_path / "watch.json"
    stale = gamma_zones.build(_gamma(NOW, timedelta(hours=1)), _walls_view(NOW), NOW)
    gamma_zones.update(path, stale, 99_500.0, NOW)
    saved = gamma_zones.update(path, stale, 99_150.0, NOW + timedelta(minutes=1))
    assert saved["open"] == [] and saved["visits"] == [] and gamma_zones.load(path)["open"] == []


def test_rollback_1_1_to_1_2_to_1_1_mixes_nothing_and_loses_nothing(tmp_path: Path) -> None:
    """Codex #378: the 1.1 log stays byte for byte; 1.2 writes its own file; a revert sees only 1.1 visits."""
    old_visit = {"opened_at": "2026-11-22T10:00:00+00:00", "key": "put_wall", "name": "Put Wall", "level": 99_000.0,
                 "low": 99_000.0, "high": 99_050.0, "side": "bid", "wall_low": 99_000.0, "pad": 99.0, "from": "oben",
                 "wall_pulled": False, "closed_at": "2026-11-22T10:10:00+00:00", "exit_price": 99_300.0, "left": "oben",
                 "outcome": "gehalten"}
    old_open = {**{k: v for k, v in old_visit.items() if k not in ("closed_at", "exit_price", "left", "outcome")},
                "low": 105_000.0, "high": 105_050.0, "wall_low": 105_000.0}
    path = tmp_path / "watch.json"
    path.write_text(json.dumps({"schema": gamma_zones.SCHEMA, "ruleset": "gamma-orderbuch/1.1",
                                "started_at": "2026-11-22T09:00:00+00:00", "open": [old_open], "visits": [old_visit] * 3,
                                "last_price": 99_500.0, "updated_at": NOW.isoformat()}), encoding="utf-8")
    before = path.read_bytes()
    assert gamma_zones.load(path) is None                              # 1.2 starts its own log
    ok = _view(NOW)
    gamma_zones.update(path, ok, 99_500.0, NOW)
    gamma_zones.update(path, ok, 99_150.0, NOW + timedelta(minutes=1))   # into the zone from above: a 1.2 visit
    state = gamma_zones.update(path, ok, 99_450.0, NOW + timedelta(minutes=2))
    assert path.read_bytes() == before                                 # 1.1 log untouched (also its open visit)
    assert [v["ruleset"] for v in state["visits"]] == [gamma_zones.RULESET]
    assert gamma_zones.summary(state) == {"open": 0, "closed": 1, "held": 1, "broken": 0, "pulled": 0,
                                          "earlier_open": 0, "earlier_closed": 0}
    reverted = json.loads(path.read_text(encoding="utf-8"))           # what 1.1 code reads after a revert
    assert len(reverted["visits"]) == 3 and all("ruleset" not in v for v in reverted["visits"])
    again = gamma_zones.update(path, ok, 99_500.0, NOW + timedelta(minutes=3))   # back on 1.2: its file goes on
    assert len(again["visits"]) == 1 and again["started_at"] == NOW.isoformat()
    _, notes = gamma_zones.chart_drawings(ok, gamma_zones.load(path), NOW)
    assert notes == ["Gamma-Level mit Orderbuch-Mauer: 1, Berührungen 1 (1 gehalten, 0 gebrochen), Urteil ab 30."]


def test_retention_archives_visits_beyond_the_cap(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(gamma_zones, "MAX_VISITS", 2)
    path, ok = tmp_path / "watch.json", _view(NOW)
    minute = 0
    for _ in range(3):                                                 # three visits: in from above, out above
        for price in (99_500.0, 99_150.0, 99_450.0):
            state = gamma_zones.update(path, ok, price, NOW + timedelta(minutes=minute))
            minute += 1
    assert len(state["visits"]) == 2 and state["archived"] == 1
    lines = gamma_zones.archive_path(path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["opened_at"] == (NOW + timedelta(minutes=1)).isoformat()


def test_future_gamma_end_to_end_build_then_track_opens_no_visit(tmp_path: Path) -> None:
    path = tmp_path / "watch.json"
    ahead = gamma_zones.build(_gamma(NOW, -timedelta(seconds=30)), _walls_view(NOW), NOW)
    assert ahead["status"] in gamma_zones.WATCH_STATUSES             # the runtime does advance the log ...
    gamma_zones.update(path, ahead, 99_500.0, NOW)
    saved = gamma_zones.update(path, ahead, 99_150.0, NOW + timedelta(minutes=1))
    assert saved["open"] == [] and saved["visits"] == []             # ... but never opens a visit on it


def test_gamma_data_with_age_marks_a_future_snapshot_stale() -> None:
    from src.dashboard import gamma_data
    snap = {"as_of": (NOW + timedelta(seconds=30)).isoformat()}
    aged = gamma_data.with_age(snap, NOW)
    assert aged["future"] is True and aged["stale"] is True and aged["age_seconds"] == -30
    now_snap = gamma_data.with_age({"as_of": NOW.isoformat()}, NOW)
    assert now_snap["future"] is False and now_snap["stale"] is False


def test_gamma_notes_are_english_on_the_public_page() -> None:
    from src.dashboard.public_en import GROUPS_EN, english_note

    assert "confirmed" not in GROUPS_EN["gamma_ob"]
    cases = ((None, "no gamma snapshot"), (_gamma(NOW, timedelta(hours=1)), "gamma snapshot is old"),
             (_gamma(NOW, -timedelta(hours=1)), "lies in the future"), ({"levels": LEVELS, "as_of": "x"}, "without a valid time"))
    for gamma, english in cases:
        _, notes = gamma_zones.chart_drawings(gamma_zones.build(gamma, _walls_view(NOW), NOW), None, NOW)
        (note,) = notes
        assert english in english_note(note), note


def test_archive_is_idempotent_after_a_crash_between_archive_and_log(tmp_path: Path, monkeypatch) -> None:
    """Mission 05: a crash after the archive append and before the log save must not duplicate or lose visits."""
    monkeypatch.setattr(gamma_zones, "MAX_VISITS", 1)
    path, ok = tmp_path / "watch.json", _view(NOW)
    archive = gamma_zones.archive_path(path)

    def step(minute: int, price: float) -> dict:
        return gamma_zones.update(path, ok, price, NOW + timedelta(minutes=minute))

    for minute, price in enumerate((99_500.0, 99_150.0, 99_450.0, 99_500.0, 99_150.0)):   # visit 1 closed, visit 2 open
        step(minute, price)
    before = gamma_zones.load(path)
    real_save = gamma_zones._save

    def crash(*_args):
        raise OSError("crash")

    monkeypatch.setattr(gamma_zones, "_save", crash)
    try:
        step(5, 99_450.0)                                              # visit 2 closes: visit 1 archived, log not saved
    except OSError:
        pass
    assert gamma_zones.load(path) == before and len(gamma_zones.read_archive(archive)) == 1
    with archive.open("ab") as fh:                                     # plus a half-written line from the crash
        fh.write(b'{"opened_at": "cut')
    monkeypatch.setattr(gamma_zones, "_save", real_save)
    state = step(6, 99_450.0)                                          # restart: the same overflow is offered again
    rows = gamma_zones.read_archive(archive)
    assert len(rows) == 1 and rows[0]["opened_at"] == (NOW + timedelta(minutes=1)).isoformat()   # once, not twice
    assert len(state["visits"]) == 1 and state["visits"][0]["opened_at"] == (NOW + timedelta(minutes=4)).isoformat()
    assert state["archived"] == 1                                      # counter follows the archive, not the crash
    for minute, price in ((7, 99_500.0), (8, 99_150.0), (9, 99_450.0)):
        state = step(minute, price)
    assert [r["opened_at"][11:16] for r in gamma_zones.read_archive(archive)] == ["12:01", "12:04"]
