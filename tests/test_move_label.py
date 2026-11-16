"""P4 (Uzi 16.11.2026): market-event label on closed paper trades, written once after the close, never an input."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.dashboard import journal_log, move_context, move_label as ml, plan_journal as pj
from src.dashboard.pages.plan_journal import _plan_journal_page

T = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _trade(opened: datetime = T, hours: float = 3.0, **extra) -> dict:
    return {"id": "p1", "status": "CLOSED", "direction": "LONG", "filled_at": _iso(opened), "closed_at": _iso(opened + timedelta(hours=hours)),
            "gross_r": 1.0, "net_r": 0.8, "fee_r": 0.15, "slippage_r": 0.05, **extra}


def _move(start: datetime, hours: float = 1.0, findings: list | None = None, explained: bool = False, ident: str = "m1") -> dict:
    return {"schema": "tim_move_event/1", "rules": "move-context/0.2", "id": ident, "start": start.isoformat(),
            "end": (start + timedelta(hours=hours)).isoformat(), "direction": "DOWN", "change_pct": -3.0,
            "findings": findings or [], "explained": explained}


def _write(path: Path, rows: list[dict], through: datetime, since: datetime = T - timedelta(hours=2), gap: tuple | None = None) -> Path:
    """Move record plus an hourly heartbeat from ``since`` to ``through`` (``gap`` = hours left out)."""
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    t = since
    while t <= through:
        if not (gap and gap[0] <= t < gap[1]):
            move_context.beat(path, t)
        t += timedelta(hours=1)
    return path


def test_move_kind_follows_the_fixed_order() -> None:
    liq = {"key": "liq", "level": "BELEGT"}
    assert ml.move_kind(_move(T, findings=[liq, {"key": "news", "level": "VERMUTUNG"}])) == "liquidations_kaskade"
    assert ml.move_kind(_move(T, findings=[{"key": "liq", "level": "VERMUTUNG"}, {"key": "macro", "level": "VERMUTUNG"}])) == "makro_termin"
    # A cause beats a date or a headline (those are only ever VERMUTUNG).
    assert ml.move_kind(_move(T, findings=[{"key": "news", "level": "VERMUTUNG"}, {"key": "flow", "level": "BELEGT"}], explained=True)) == "markt_druck"
    assert ml.move_kind(_move(T, findings=[{"key": "news", "level": "VERMUTUNG"}])) == "news_notiz"
    assert ml.move_kind(_move(T, findings=[{"key": "flow", "level": "BELEGT"}], explained=True)) == "markt_druck"
    assert ml.move_kind(_move(T, findings=[{"key": "volume", "level": "BELEGT"}])) == "unerklaert"


def test_label_needs_an_overlap_while_the_trade_was_open() -> None:
    inside = _move(T + timedelta(hours=1), findings=[{"key": "liq", "level": "WAHRSCHEINLICH"}])
    before = _move(T - timedelta(hours=2), hours=1.0, ident="m0")  # ended before the fill
    after = _move(T + timedelta(hours=3), ident="m2")  # starts at the close
    assert ml.label_trade(_trade(), [before, after])["label"] == ml.CALM
    got = ml.label_trade(_trade(), [before, inside, after])
    assert got == {"id": "p1", "label": "liquidations_kaskade", "moves": ["m1"], "rule": ml.RULE, "move_rules": ["move-context/0.2"]}
    # Several moves: the stronger kind wins.
    news = _move(T + timedelta(minutes=30), findings=[{"key": "news", "level": "VERMUTUNG"}], ident="m3")
    assert ml.label_trade(_trade(), [news, inside])["label"] == "liquidations_kaskade"
    # A move that started in the trade and ended long after the close still counts.
    late = _move(T + timedelta(hours=2), hours=20.0, ident="m4")
    assert ml.label_trade(_trade(), [late])["label"] == "unerklaert"


def test_no_label_before_recording_without_fill_or_twice() -> None:
    early = ml.RECORDING_SINCE - timedelta(hours=1)
    assert ml.label_trade(_trade(early), []) is None  # no recording then: no evidence of calm
    assert ml.label_trade({**_trade(), "filled_at": None}, []) is None
    assert ml.label_trade({**_trade(), "status": "EXPIRED"}, []) is None
    assert ml.label_trade(_trade(market_event={"label": "ruhig"}), []) is None
    assert ml.label_trade(_trade(excluded={"reason": "x"}), []) is None


def test_labels_wait_until_the_moves_are_recorded_and_the_recorder_ran(tmp_path: Path) -> None:
    journal = {"entries": [_trade()]}
    closed = T + timedelta(hours=3)
    missing = tmp_path / "none.jsonl"
    assert ml.labels(journal, missing, closed + timedelta(days=2)) == []  # no recorder, no heartbeat
    path = _write(tmp_path / "moves.jsonl", [], closed + timedelta(days=2))
    assert ml.labels(journal, path, closed + ml.WAIT - timedelta(minutes=1)) == []  # moves may still be recorded
    assert ml.labels(journal, path, closed + ml.WAIT)[0]["label"] == ml.CALM
    stale = _write(tmp_path / "stale.jsonl", [], closed)  # recorder stopped at the close
    assert ml.labels(journal, stale, closed + timedelta(days=2)) == []
    # A gap longer than MAX_GAP between fill and due time could hide a move: no label, even with a fresh heartbeat.
    gap = _write(tmp_path / "gap.jsonl", [], closed + timedelta(days=2), gap=(closed + timedelta(hours=2), closed + timedelta(hours=9)))
    assert ml.labels(journal, gap, closed + timedelta(days=2)) == []
    short = _write(tmp_path / "short.jsonl", [], closed + timedelta(days=2), gap=(closed + timedelta(hours=2), closed + timedelta(hours=4)))
    assert ml.labels(journal, short, closed + timedelta(days=2))[0]["label"] == ml.CALM


def test_fold_accepts_the_label_once_and_only_after_the_close() -> None:
    entry = _trade()
    label = ml.label_trade(entry, [])
    events = [{"kind": pj.PLAN_RECORDED, "recorded_at": "x", "payload": {"entry": dict(entry)}},
              {"kind": pj.MARKET_EVENT_LABELED, "recorded_at": "y", "payload": label}]
    folded = pj.fold(events)
    assert folded["entries"][0]["market_event"] == {"label": "ruhig", "moves": [], "rule": ml.RULE, "move_rules": [], "at": "y"}
    with pytest.raises(pj.journal_log.LogError):
        pj.fold([*events, events[1]])
    open_entry = {**entry, "status": "FILLED"}
    with pytest.raises(pj.journal_log.LogError):
        pj.fold([{"kind": pj.PLAN_RECORDED, "recorded_at": "x", "payload": {"entry": open_entry}}, events[1]])


def test_summary_counts_per_label_without_a_verdict_under_thirty() -> None:
    labelled = [_trade(market_event={"label": "ruhig"}) for _ in range(3)]
    stats = ml.by_label([*labelled, _trade()])
    assert stats["unlabelled"] == 1 and stats["min_group"] == 30
    assert stats["groups"] == {"ruhig": {"closed": 3, "sum_net_r": 2.4, "sum_cost_r": 0.6, "enough": False}}
    # Old journals without the field still load and summarise.
    assert pj.summary({"entries": [{**_trade(), "gross_r": 1.0}]})["market_event"]["unlabelled"] == 1


def test_update_writes_the_label_event_once(tmp_path: Path) -> None:
    path = tmp_path / "journal.json"
    entry = {**_trade(), "created_at": _iso(T - timedelta(hours=1)), "timeframe": "30m"}
    state = journal_log.read(pj.events_path_for(path))
    journal_log.append(pj.events_path_for(path), [{"event_id": "seed", "kind": pj.PLAN_RECORDED, "aggregate_id": "p1", "recorded_at": _iso(T),
                                                   "source_hash": "s", "source_range": {}, "payload": {"entry": entry}}], state)
    now = T + timedelta(days=2)
    moves = _write(tmp_path / "moves.jsonl", [_move(T + timedelta(hours=1), findings=[{"key": "macro", "level": "VERMUTUNG"}])], now)
    series = {"30m": [], "1m": []}
    assert "market_event" not in pj.update(path, series, now)["entries"][0]  # without moves_path nothing is labelled
    journal = pj.update(path, series, now, moves_path=moves)
    assert journal["entries"][0]["market_event"]["label"] == "makro_termin"
    again = pj.update(path, series, now + timedelta(minutes=5), moves_path=moves)
    kinds = [e["kind"] for e in journal_log.read(pj.events_path_for(path)).events]
    assert kinds.count(pj.MARKET_EVENT_LABELED) == 1 and again["entries"][0]["market_event"]["label"] == "makro_termin"
    page = _plan_journal_page({}, again)
    assert "Ergebnis nach Marktereignis" in page and "Makro-Termin" in page and "zu wenig für eine Aussage" in page


def test_heartbeat_writes_one_line_per_hour(tmp_path: Path) -> None:
    path = tmp_path / "moves.jsonl"
    for minutes in (0, 10, 59, 61):
        move_context.beat(path, T + timedelta(minutes=minutes))
    assert move_context.beats(path) == [T, T + timedelta(hours=1)]
    assert path.exists() and path.read_text() == ""  # the record exists, empty: watched, no move
    # A naive or broken line (not written by beat) is skipped, never a crash.
    with move_context.heartbeat_path(path).open("a") as handle:
        handle.write('"2026-11-17T15:00:00"\n{broken\n')
    assert move_context.beats(path) == [T, T + timedelta(hours=1)]


def test_lost_record_or_broken_bytes_never_read_as_calm_or_crash(tmp_path: Path) -> None:
    journal = {"entries": [_trade()]}
    now = T + timedelta(days=2)
    path = _write(tmp_path / "moves.jsonl", [], now)
    path.unlink()  # heartbeat stays, record lost
    assert ml.labels(journal, path, now) == []
    broken = _write(tmp_path / "broken.jsonl", [_move(T + timedelta(hours=1), findings=[{"key": "liq", "level": "BELEGT"}])], now)
    with broken.open("ab") as handle:
        handle.write(b'{"id": "\xc3')  # cut multi-byte tail
    assert ml.labels(journal, broken, now)[0]["label"] == "liquidations_kaskade"


def test_a_label_error_never_stops_the_journal_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args, **_kwargs):
        raise TypeError("bad record")

    monkeypatch.setattr(ml, "labels", boom)
    journal = pj.update(tmp_path / "journal.json", {"30m": [], "1m": []}, T, moves_path=tmp_path / "moves.jsonl")
    assert journal["entries"] == [] and journal["checked_at"]


def test_gap_of_exactly_max_gap_is_covered_one_hour_more_is_not() -> None:
    first, last = T, T + timedelta(hours=10)
    beats = [T, T + ml.MAX_GAP, T + timedelta(hours=8), last]
    assert ml.covered(beats, first, last)
    assert not ml.covered([T, T + ml.MAX_GAP + timedelta(hours=1), last], first, last)
