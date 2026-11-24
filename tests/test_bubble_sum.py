"""Summed bubbles: orders at one price within minutes are added up and drawn as lines (display, no signal)."""
from __future__ import annotations

from src.dashboard import bubble_sum
from src.research_lab.ki_entry import zones

T = 1_795_400_000.0


def test_orders_at_one_price_within_five_minutes_are_summed():
    orders = [(T, 63400.0, 348.0, 1), (T + 30, 63420.0, 311.0, 1), (T + 90, 63390.0, 150.0, 1), (T + 200, 63410.0, 250.0, 1),
              (T + 60, 63405.0, 90.0, -1),            # other side: not added
              (T + 100, 63900.0, 300.0, 1),           # 0.8 % away: own cluster, too small
              (T + 400, 63400.0, 500.0, 1)]           # after the window: own cluster, one order only
    found = bubble_sum.clusters(orders)
    assert len(found) == 1
    c = found[0]
    assert c["quantity"] == 1059.0 and c["orders"] == 4 and c["side"] == 1 and c["biggest"] == 348.0
    assert 63390 <= c["price"] <= 63420 and c["time"] == T and c["end"] == T + 200


def test_single_big_order_and_small_sums_are_no_summed_bubble():
    assert bubble_sum.clusters([(T, 60000.0, 900.0, 1)]) == []
    assert bubble_sum.clusters([(T + i, 60000.0, 100.0, -1) for i in range(3)]) == []
    assert len(bubble_sum.clusters([(T + i, 60000.0, 150.0, -1) for i in range(3)])) == 1


def test_store_window_and_drawings_keep_the_biggest_recent_sums():
    store = {"bubbles": {"2026-11-23": [[int(T * 1000) + i * 1000, 60000.0, 200.0, -1] for i in range(3)]
                                       + [[int((T - 9000) * 1000), 60000.0, 999.0, 1]]}}
    orders = bubble_sum.orders_from_store(store, T - 60, T + 600)
    assert len(orders) == 3 and orders[0][3] == -1
    found = [{"time": T - 60 * 3600, "end": T - 60 * 3600, "price": 1.0, "quantity": 5000.0, "orders": 9, "biggest": 900.0, "side": 1}]
    found += [{"time": T + i, "end": T + i + 120, "price": 60000.0 + i, "quantity": 400.0 + i, "orders": 5, "biggest": 200.0, "side": -1 if i % 2 else 1}
              for i in range(10)]
    lines = bubble_sum.drawings(found, T + 3600)
    assert len(lines) == bubble_sum.LINES and all(d["group"] == "absorb" for d in lines)
    assert min(d["price"] for d in lines) == 60002.0                      # the two smallest and the 60-hour-old one are left out
    assert {d["color"] for d in lines} == {"#35d39a", "#ff5c6c"} and "Summe 409 Verkäufe" in [d["label"] for d in lines]
    assert bubble_sum.drawings([{**found[0], "time": T, "end": T}], T)[0]["label"] == "Summe 5.0K Käufe"


def test_summed_bubble_line_counts_as_a_zone_mark():
    assert zones.weight("absorb", "Summe 634 Käufe") == 2.0
    model = {"drawings": [{"group": "absorb", "label": "Summe 634 Käufe", "price": 60500.0}], "footprint": {"bars": []}}
    assert [m["weight"] for m in zones.marks(model, 60400.0)] == [2.0]


def test_live_chart_draws_the_summed_bubble_as_a_line():
    from datetime import datetime, timedelta

    from src.dashboard.chart_live import (
        DEFAULT_GROUPS,
        GROUP_NAMES,
        KlineCache,
        build_live_chart,
    )
    from tests.test_chart_live import fake_fetch

    fetch = fake_fetch()
    candles = fetch("BTCUSDT", "5m", 1000)
    moment = datetime.fromisoformat(candles[-6]["open_time"]) + timedelta(seconds=20)
    price, day, ms = float(candles[-6]["close"]), moment.date().isoformat(), int(moment.timestamp() * 1000)
    store = {"symbol": "BTCUSDT", "tick": 5.0, "bucket_seconds": 300, "bubble_min_usd": 100_000.0,
             "days": {day: [[int(moment.timestamp()) // 300 * 300, price, 1.0, 1.0]]},
             "bubbles": {day: [[ms + i * 20_000, price, 180.0, 1] for i in range(3)]}}
    now = datetime.fromisoformat(candles[-1]["open_time"]) + timedelta(minutes=1)
    model = build_live_chart("BTCUSDT", "5m", cache=KlineCache(fetch), now=now, footprint=store)
    assert [(c["quantity"], c["orders"]) for c in model["bubble_sums"]["items"]] == [(540.0, 3)]
    lines = [d for d in model["drawings"] if d["group"] == "absorb"]
    assert len(lines) == 1 and lines[0]["label"] == "Summe 540 Käufe" and lines[0]["price"] == round(price, 1) and lines[0]["finished"] is False
    assert lines[0]["t1"] == int(datetime.fromisoformat(candles[-6]["open_time"]).timestamp())
    assert "absorb" in DEFAULT_GROUPS and "absorb" in GROUP_NAMES
    assert "bubble_sums" not in build_live_chart("ETHUSDT", "5m", cache=KlineCache(fetch), now=now, footprint=store)
