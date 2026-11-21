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


def _view(now: datetime, **over) -> dict:
    walls_view = {"last_event_ms": int(now.timestamp() * 1000) - 5_000, "caught_up": True, "synced": True,
                  "mid": 99_500.0, "walls": [WALL], **over}
    return gamma_zones.build({"levels": LEVELS}, walls_view, now)


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
    drawings, notes = gamma_zones.chart_drawings(_view(now), {"visits": [{"outcome": "gehalten"}, {"outcome": "gebrochen"}]}, now)
    (drawing,) = drawings
    assert drawing["group"] == "gamma_ob" and drawing["band"] == [99_000.0, 99_200.0] and drawing["price"] == 99_000.0
    assert "Kaufmauer" in drawing["note"] and "zurückgezogen" in drawing["note"]
    assert notes == ["Gamma-Zonen mit Orderbuch: 1 bestätigt, Berührungen 2 (1 gehalten, 1 gebrochen), Urteil ab 30."]
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
    assert gamma_zones.summary(state) == {"open": 0, "closed": 2, "held": 1, "broken": 1, "pulled": 1}
    state = step(state, 99_500.0, 7)
    state = step(state, 99_100.0, 30)                     # 23 minutes without a step: side unknown, no visit
    assert state["open"] == []


def test_refresh_and_update_write_only_state_and_their_own_file(tmp_path: Path) -> None:
    folder = tmp_path / "book" / "BTCUSDT"
    folder.mkdir(parents=True)
    now = datetime.fromtimestamp((T0 + 39 * 60_000) / 1000, timezone.utc)
    with gzip.open(folder / "2027-01-15.100.jsonl.gz", "xb") as fh:
        fh.write(("\n".join(json.dumps(r) for r in [_snapshot_row(T0)] + _rows(T0, 40, "9")) + "\n").encode())
    state = SimpleNamespace(lock=RLock(), gamma={"BTCUSDT": {"levels": [{"key": "put_wall", "name": "Put Wall", "price": 99_100.0, "note": ""}]}}, gamma_zones={})
    gamma_zones._TAILS.clear()
    view = gamma_zones.refresh(state, "BTCUSDT", root=tmp_path / "book", now=now)
    assert view["status"] == "OK" and state.gamma_zones["BTCUSDT"]["zones"][0]["name"] == "Put Wall"
    assert gamma_zones.refresh(state, "ETHUSDT", root=tmp_path / "book") is None
    path = tmp_path / "journal" / "watch.json"
    saved = gamma_zones.update(path, view, view["mid"], now)
    assert saved["ruleset"] == gamma_zones.RULESET and gamma_zones.load(path)["last_price"] == view["mid"]
    assert gamma_zones.update(path, None, 1.0) is None
    assert sorted(p.name for p in (tmp_path / "journal").iterdir()) == ["watch.json"]


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
