"""Real liquidations for the chart from the S12 collector's raw record (src/dashboard/liquidation_events.py)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.dashboard import liquidation_events as le
from src.research_lab.liquidations import store

NOW = datetime(2026, 11, 9, 14, 0, tzinfo=timezone.utc)


def _binance(ms: int, side: str, price: str, qty: str, status: str = "FILLED") -> str:
    return json.dumps({"e": "forceOrder", "E": ms, "o": {"s": "BTCUSDT", "S": side, "o": "LIMIT", "f": "IOC", "q": qty, "p": price,
                                                           "ap": price, "X": status, "l": qty, "z": qty, "T": ms}})


def _bybit(ms: int, side: str, price: str, qty: str) -> str:
    return json.dumps({"topic": "allLiquidation.BTCUSDT", "type": "snapshot", "ts": ms,
                       "data": [{"T": ms, "s": "BTCUSDT", "S": side, "v": qty, "p": price}]})


def _write(root, venue: str, payloads: list[tuple[int, str]]) -> None:
    for ms, payload in payloads:
        store.append(root, store.make_record("message", venue, "s1", ms * 1_000_000, ms * 1_000_000, payload=payload))


def test_items_from_both_venues_largest_first_with_counts(tmp_path) -> None:
    first = int((NOW - timedelta(hours=6)).timestamp())
    t1 = int((NOW - timedelta(hours=5)).timestamp() * 1000)
    t2 = int((NOW - timedelta(hours=2)).timestamp() * 1000)
    old = int((NOW - timedelta(hours=9)).timestamp() * 1000)  # before the window: counted nowhere
    _write(tmp_path, "binance", [(t1, _binance(t1, "SELL", "74000", "2.0")), (t2, _binance(t2, "BUY", "74500", "0.01")),
                                 (old, _binance(old, "SELL", "73000", "5")), (t2 + 1, _binance(t2 + 1, "SELL", "74400", "1", status="NEW"))])
    _write(tmp_path, "bybit", [(t2, _bybit(t2, "Buy", "74490", "0.5")), (t2, _bybit(t2, "Buy", "74490", "0.5"))])  # duplicate once
    part = le.chart_items(tmp_path, "BTCUSDT", first, NOW)
    assert part["counts"] == {"binance": 2, "bybit": 1} and part["note"] is None
    assert [i["venue"] for i in part["items"]] == ["binance", "bybit"]  # the 745 $ Binance short is under the 5 000 $ floor
    assert part["items"][0]["side"] == "long" and part["items"][0]["usd"] == 148_000 and part["items"][0]["time"] == t1 / 1000
    assert part["items"][1]["side"] == "long" and part["items"][1]["quantity"] == 0.5
    assert part["usd"]["binance"] == 148_745 and part["max_usd"] == 148_000


def test_incremental_read_picks_up_appended_lines_and_waits_for_a_cut_line(tmp_path) -> None:
    first = int((NOW - timedelta(hours=3)).timestamp())
    t1 = int((NOW - timedelta(hours=1)).timestamp() * 1000)
    _write(tmp_path, "binance", [(t1, _binance(t1, "SELL", "74000", "1"))])
    assert le.chart_items(tmp_path, "BTCUSDT", first, NOW)["counts"]["binance"] == 1
    path = store.raw_path(tmp_path, "binance", store.utc_day(t1 * 1_000_000))
    _write(tmp_path, "binance", [(t1 + 1000, _binance(t1 + 1000, "BUY", "74100", "1"))])
    with path.open("ab") as handle:  # a record still being written
        handle.write(b'{"kind":"message","venue":"binance","receive_ns":1,"mono_ns":1,"payload":"{\\"e\\":')
    assert le.chart_items(tmp_path, "BTCUSDT", first, NOW)["counts"]["binance"] == 2
    with path.open("ab") as handle:
        handle.write(b'x"}\n')
    assert le.chart_items(tmp_path, "BTCUSDT", first, NOW)["counts"]["binance"] == 2  # the finished line is no event


def test_missing_record_and_missing_venue_are_said(tmp_path) -> None:
    first = int((NOW - timedelta(hours=3)).timestamp())
    assert le.chart_items(tmp_path, "BTCUSDT", first, NOW)["note"].startswith("Liquidationen: kein Mitschnitt")
    assert le.chart_items(tmp_path, "ETHUSDT", first, NOW) == {"items": [], "counts": {}, "usd": {}, "min_usd": None, "max_usd": None,
                                                               "source": le.SOURCE, "note": None}
    (tmp_path / "raw" / "binance").mkdir(parents=True)
    part = le.chart_items(tmp_path, "BTCUSDT", first, NOW)
    assert part["note"] == "Liquidationen: nur Binance im Mitschnitt, Bybit fehlt." and part["items"] == []
    (tmp_path / "raw" / "bybit").mkdir(parents=True)
    assert le.chart_items(tmp_path, "BTCUSDT", first, NOW)["note"] == "Liquidationen: keine Ereignisse im gezeigten Fenster."


def test_live_chart_carries_real_liquidations_and_translates_the_note(tmp_path) -> None:
    from src.dashboard.chart_live import KlineCache, build_live_chart
    from src.dashboard.public_en import english_chart_model as english_model
    from tests.test_chart_live import NOW as CHART_NOW, fake_fetch

    t1 = int((CHART_NOW - timedelta(hours=2)).timestamp() * 1000)
    _write(tmp_path, "binance", [(t1, _binance(t1, "BUY", "60000", "3"))])
    (tmp_path / "raw" / "bybit").mkdir(parents=True)
    model = build_live_chart("BTCUSDT", "1h", cache=KlineCache(fake_fetch()), now=CHART_NOW, liquidation_root=tmp_path)
    assert model["liquidations"]["items"][0]["side"] == "short" and model["liquidations"]["counts"] == {"binance": 1, "bybit": 0}
    assert "liqev" in model["default_groups"] and model["groups"]["liqev"].startswith("Liquidationen (echt")
    english = english_model(model)
    assert english["groups"]["liqev"] == "Liquidations (real, Binance + Bybit)"
    skipped = build_live_chart("BTCUSDT", "1h", cache=KlineCache(fake_fetch()), now=CHART_NOW, liquidation_root=False)
    assert skipped["liquidations"] is None
    eth = build_live_chart("ETHUSDT", "1h", cache=KlineCache(fake_fetch()), now=CHART_NOW, liquidation_root=tmp_path)
    assert eth["liquidations"] is None
