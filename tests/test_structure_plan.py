from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen

from src.dashboard.app import DashboardServer, DashboardState
from src.dashboard.pages.plan_journal import _plan_journal_page
from src.dashboard.plan_journal import RULE_STRUCT, SCHEMA, empty_journal, load, record_plans, update
from src.dashboard.structure_plan import candles_until, liquidity, structural_plan, structural_plans

T0 = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)


def _plan(direction: str = "LONG", entry: float = 100.0, low: float = 99.0, high: float = 101.0) -> dict:
    stop = low * 0.995 if direction == "LONG" else high * 1.005
    risk = abs(entry - stop)
    sign = 1 if direction == "LONG" else -1
    return {"scenario_id": "S1", "direction": direction, "entry": entry, "stop": stop, "entry_low": low, "entry_high": high,
            "targets": [entry + sign * risk * r for r in (1.5, 2, 3)], "invalidation_level": low - 2 if direction == "LONG" else high + 2,
            "invalidation_side": "<" if direction == "LONG" else ">", "plan_text": "PLAN"}


def _places(*prices: float) -> list[dict]:
    return [{"price": p, "label": f"L{p:g}"} for p in prices]


def test_long_stop_goes_behind_the_nearest_swing_low_below_the_zone() -> None:
    plan, reason = structural_plan(_plan(), highs=[108.0], lows=[95.0, 97.0, 99.5], places=_places(106, 108, 112))
    assert reason is None and plan["rule"] == RULE_STRUCT
    # 99.5 is inside the zone (low 99), so the nearest swing below it is 97.
    assert plan["stop_swing"] == 97.0 and plan["stop"] == round(97 * 0.9995, 2)
    assert plan["targets"] == [106.0, 108.0, 112.0] and plan["target_labels"] == ["L106", "L108", "L112"]
    assert plan["tim_stop"] == _plan()["stop"] and plan["entry"] == 100.0


def test_short_mirrors_the_long_rule() -> None:
    plan, reason = structural_plan(_plan("SHORT"), highs=[103.0, 105.0], lows=[], places=_places(94, 90, 103))
    assert reason is None and plan["stop_swing"] == 103.0 and plan["targets"] == [94.0, 90.0, 90.0]


def test_plan_is_dropped_without_swing_target_or_room() -> None:
    assert structural_plan(_plan(), highs=[], lows=[], places=_places(110))[1] == "kein Swing-Tief unter der Einstiegszone"
    assert structural_plan(_plan(), highs=[], lows=[97.0], places=_places(90))[1] == "kein Liquiditätsziel jenseits des Einstiegs"
    # Risk ≈ 3.05; the next liquidity at 103 is under 1.5R away: no trade, even though 110 would be far enough.
    _, reason = structural_plan(_plan(), highs=[], lows=[97.0], places=_places(103, 110))
    assert reason.startswith("nächstes Ziel nur 0.98 R")


def test_close_levels_merge_into_one_place() -> None:
    plan, _ = structural_plan(_plan(), highs=[], lows=[97.0], places=_places(106, 106.03, 108))
    assert plan["targets"] == [106.0, 108.0, 108.0]


def test_liquidity_combines_prep_levels_and_swings() -> None:
    prep = {"levels": [{"price": 105, "label": "Vortag VAH"}]}
    assert liquidity(prep, [110.0], [90.0]) == [{"price": 105.0, "label": "Vortag VAH"}, {"price": 110.0, "label": "30m Swing-Hoch"}, {"price": 90.0, "label": "30m Swing-Tief"}]
    assert liquidity(None, [], []) == []


def _c(tf: str, opened: datetime, seconds: int, o: float, h: float, l: float, c: float) -> dict:
    return {"symbol": "BTCUSDT", "timeframe": tf, "open_time": opened.isoformat(), "close_time": (opened + timedelta(seconds=seconds)).isoformat(),
            "open": o, "high": h, "low": l, "close": c, "volume": 1.0}


def test_candles_until_drops_running_candles() -> None:
    series = {"30m": [_c("30m", T0, 1800, 1, 2, 0.5, 1.5), _c("30m", T0 + timedelta(minutes=30), 1800, 1, 2, 0.5, 1.5)],
              "1h": [_c("1h", T0, 3600, 1, 2, 0.5, 1.5)]}
    closed = candles_until(series, T0 + timedelta(minutes=30))
    assert len(closed["30m"]) == 1 and closed["1h"] == []


def test_structural_plans_report_dropped_directions() -> None:
    zigzag = []
    for i, (h, l) in enumerate([(101, 99), (102, 100), (104, 101), (103, 97), (101, 96), (102, 98), (105, 99), (109, 104), (108, 103), (106, 101), (107, 102)]):
        zigzag.append({"open_time": T0 + timedelta(minutes=30 * i), "high": float(h), "low": float(l)})
    kept, dropped = structural_plans([_plan(entry=98.5, low=98, high=99), _plan("SHORT", entry=120, low=119, high=121)], zigzag, None)
    assert len(kept) == 1 and kept[0]["direction"] == "LONG" and kept[0]["stop_swing"] == 96.0 and kept[0]["targets"] == [104.0, 109.0, 109.0]
    assert dropped == ["SHORT: kein Swing-Hoch über der Einstiegszone"]


def test_struct_entries_are_recorded_and_followed_like_tim_plans() -> None:
    journal = empty_journal()
    plan, _ = structural_plan(_plan(), highs=[], lows=[97.0], places=_places(106, 108, 112))
    added = record_plans(journal, [plan], T0)
    assert added[0]["rule"] == RULE_STRUCT and added[0]["targets"] == [106.0, 108.0, 112.0]


def _runtime_series() -> dict:
    import math

    end = datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc)
    series = {}
    for tf, seconds, count in (("1m", 60, 500), ("5m", 300, 500), ("30m", 1800, 500), ("1h", 3600, 500)):
        start = end - timedelta(seconds=seconds * count)
        rows, price = [], 80000.0
        for i in range(count):
            close = 80000.0 + 300 * math.sin(i / 6) + (i % 5)
            up = close >= price
            rows.append(_c(tf, start + timedelta(seconds=seconds * i), seconds, price, max(price, close) + 5 + up, min(price, close) - 5 - (not up), close))
            price = close
        series[tf] = rows
    return series


def test_update_with_struct_rule_writes_its_own_file(tmp_path) -> None:
    path = tmp_path / "struct.json"
    now = datetime(2026, 10, 24, 14, 0, 30, tzinfo=timezone.utc)
    journal = update(path, _runtime_series(), now=now, rule=RULE_STRUCT)
    assert journal["rule"] == RULE_STRUCT and journal["last_plan_candle"] == "2026-10-24T14:00:00Z"
    stored = load(path)
    assert stored["rule"] == RULE_STRUCT
    for entry in stored["entries"]:
        assert entry["rule"] == RULE_STRUCT and len(entry["targets"]) == 3
    assert isinstance(stored.get("last_skips"), list) and isinstance(stored.get("structure_skips"), dict)
    # The view stays the fold of the log, also for the struct rule.
    from src.dashboard import journal_log
    from src.dashboard.plan_journal import events_path_for, fold

    replay = fold(journal_log.read(events_path_for(path)).events)
    assert {k: v for k, v in replay.items() if k not in {"checked_at", "log_seq", "log_head"}} == {
        k: v for k, v in stored.items() if k not in {"checked_at", "log_seq", "log_head"}}


def test_page_compares_both_rule_versions() -> None:
    tim = {**empty_journal(), "rule": "tim/1"}
    struct = {**empty_journal(), "rule": RULE_STRUCT, "structure_skips": {"nächstes Ziel": 3}}
    page = _plan_journal_page({}, tim, other=struct)
    assert "Zwei Regelversionen parallel" in page and "nächstes Ziel: 3" in page and "/journal/struct" in page
    page = _plan_journal_page({}, struct, other=tim)
    assert "Plan-Journal: Struktur-Regel" in page and "Struktur-Regel: Stop 0,05 %" in page


def test_server_serves_struct_journal(tmp_path) -> None:
    state = DashboardState()
    state.plan_journal_path = tmp_path / "tim.json"
    state.plan_journal_struct_path = tmp_path / "struct.json"
    server = DashboardServer(state, port=0)
    server.start()
    port = server.server.server_address[1]
    try:
        with urlopen(f"http://127.0.0.1:{port}/journal/struct", timeout=5) as response:
            assert "Struktur-Regel" in response.read().decode()
        with urlopen(f"http://127.0.0.1:{port}/journal", timeout=5) as response:
            assert "Zwei Regelversionen parallel" in response.read().decode()
        with urlopen(f"http://127.0.0.1:{port}/api/plan-journal?rule=struct", timeout=5) as response:
            assert json.loads(response.read())["schema"] == SCHEMA
    finally:
        server.stop()


def test_struct_skip_counts_survive_the_fold() -> None:
    from src.dashboard.plan_journal import CANDLE_CLOSE_PROCESSED, STRUCTURE_PLANS_DROPPED, fold

    reasons = ["LONG: nächstes Ziel nur 1,2 R entfernt"]
    events = [
        {"kind": CANDLE_CLOSE_PROCESSED, "recorded_at": "2026-10-24T14:00:30Z", "payload": {"close_time": "2026-10-24T14:00:00Z", "source_hash": "a", "rule": RULE_STRUCT}},
        {"kind": STRUCTURE_PLANS_DROPPED, "recorded_at": "2026-10-24T14:00:30Z", "payload": {"close_time": "2026-10-24T14:00:00Z", "reasons": reasons}},
        {"kind": STRUCTURE_PLANS_DROPPED, "recorded_at": "2026-10-24T14:15:30Z", "payload": {"close_time": "2026-10-24T14:15:00Z", "reasons": reasons}},
        {"kind": CANDLE_CLOSE_PROCESSED, "recorded_at": "2026-10-24T14:30:30Z", "payload": {"close_time": "2026-10-24T14:30:00Z", "source_hash": "b", "rule": RULE_STRUCT}},
    ]
    journal = fold(events)
    assert journal["rule"] == RULE_STRUCT and journal["structure_skips"] == {"nächstes Ziel": 2}
    assert journal["last_skips"] == []  # the newest close dropped nothing
