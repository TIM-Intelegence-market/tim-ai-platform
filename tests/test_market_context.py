"""Funding rate and Coinbase premium for the chart (src/dashboard/market_context.py)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.dashboard import market_context as mc
from src.dashboard.chart_live import DEFAULT_GROUPS, GROUP_NAMES, build_live_chart
from src.dashboard.public_en import GROUPS_EN, english_chart_model, english_note

NOW = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)
HOUR0 = int(NOW.timestamp()) // 3600 * 3600


def funding_fetch(interval_hours: int = 8, count: int = 30, symbol: str = "BTCUSDT"):
    rows = [{"symbol": symbol, "fundingTime": (HOUR0 - i * interval_hours * 3600) * 1000 + 3, "fundingRate": "0.0001" if i % 3 else "-0.00005",
             "markPrice": "77000"} for i in range(count)]

    def fetch(url: str):
        if "/fapi/v1/fundingRate" in url:
            assert f"symbol={symbol}" in url
            return list(reversed(rows))
        if "/fapi/v1/premiumIndex" in url:
            return {"symbol": symbol, "lastFundingRate": "0.00012", "nextFundingTime": (HOUR0 + 3600) * 1000}
        raise AssertionError(url)
    return fetch


def premium_fetch(hours: int = 48, gap: int | None = None):
    def coinbase(price: float, skip: int | None = None):
        return [[HOUR0 - i * 3600, price - 1, price + 1, price, price, 10.0] for i in range(hours) if i != skip]

    def fetch(url: str):
        if "/products/BTC-USD/candles" in url:
            return coinbase(100_100.0)
        if "/products/USDT-USD/candles" in url:
            return coinbase(0.999, gap)
        if "/api/v3/klines" in url:
            return [[(HOUR0 - i * 3600) * 1000, "1", "1", "1", "100000", "1"] for i in reversed(range(hours))]
        raise AssertionError(url)
    return fetch


def test_funding_history_interval_and_scaling():
    snap = mc.funding(funding_fetch(), now=NOW)
    assert snap["interval_hours"] == 8.0 and len(snap["points"]) == 30
    assert snap["points"][-1] == [HOUR0, -0.005] and snap["points"][-2][1] == 0.01  # % per settlement, oldest first
    assert snap["current"] == 0.012 and snap["current_8h"] == 0.012 and snap["next_time"] == HOUR0 + 3600
    gold = mc.funding(funding_fetch(interval_hours=4, symbol="PAXGUSDT"), symbol="PAXGUSDT", now=NOW)
    assert gold["interval_hours"] == 4.0 and gold["current_8h"] == 0.024  # 4 h settlements scaled to 8 h
    part = mc.funding_chart(gold, HOUR0 - 10 * 3600, NOW)
    assert part and part["points"][-1][2] == pytest.approx(part["points"][-1][1] * 2)
    assert part["points"][0][0] >= HOUR0 - 14 * 3600  # one settlement before the first candle


def test_funding_rejects_bad_answers():
    with pytest.raises(ValueError):
        mc.funding(lambda url: {"code": -1121})
    rows = [{"fundingTime": HOUR0 * 1000, "fundingRate": "nan"}, {"fundingTime": "x", "fundingRate": "0.1"}]
    with pytest.raises(ValueError):
        mc.funding(lambda url: rows if "fundingRate" in url else {})


def test_funding_without_running_rate_keeps_history():
    base = funding_fetch()

    def fetch(url: str):
        if "premiumIndex" in url:
            raise OSError("down")
        return base(url)
    snap = mc.funding(fetch, now=NOW)
    assert snap["current"] is None and len(snap["points"]) == 30


def test_premium_uses_usdt_correction_and_skips_missing_hours():
    snap = mc.coinbase_premium(premium_fetch(gap=5), now=NOW)
    assert len(snap["points"]) == 47  # the hour without USDT-USD is left out, not filled
    assert HOUR0 - 5 * 3600 not in [p[0] for p in snap["points"]]
    # 100,100 / (100,000 * 0.999) - 1 = +0.2002 %; without the correction it would be +0.1 %
    assert snap["last"] == pytest.approx(0.2002, abs=1e-4) and snap["last_usd"] == pytest.approx(200.0)
    with pytest.raises(ValueError):
        mc.coinbase_premium(premium_fetch(), symbol="DOGEUSDT")


def test_chart_parts_go_stale():
    snap = mc.coinbase_premium(premium_fetch(), now=NOW)
    assert not mc.premium_chart(snap, HOUR0 - 5 * 3600, NOW)["stale"]
    assert len(mc.premium_chart(snap, HOUR0 - 5 * 3600, NOW)["points"]) == 7
    assert mc.premium_chart(snap, HOUR0, NOW + timedelta(hours=4))["stale"]
    assert mc.funding_chart(None, HOUR0) is None and mc.premium_chart({"points": []}, HOUR0) is None


def test_cache_refreshes_per_symbol_and_keeps_last_value():
    calls: list[str] = []
    state = {"fail": False}

    def build(symbol: str):
        calls.append(symbol)
        if state["fail"]:
            raise OSError("down")
        return {"symbol": symbol, "n": len(calls)}
    cache = mc.ContextCache({"funding": build}, ttl=0.0, fail_pause=0.0)
    assert cache.snapshot("BTCUSDT", background=False)["funding"]["n"] == 1
    state["fail"] = True
    assert cache.snapshot("BTCUSDT", background=False)["funding"]["n"] == 1  # failure keeps the last value
    assert cache.snapshot("ETHUSDT", background=False)["funding"] is None
    slow = mc.ContextCache({"funding": build}, ttl=3600.0)
    state["fail"] = False
    slow.snapshot("BTCUSDT", background=False)
    before = len(calls)
    slow.snapshot("BTCUSDT", background=False)
    assert len(calls) == before  # within TTL no new request


def test_chart_context_is_off_in_tests_and_limited_to_chart_symbols(monkeypatch):
    assert mc.chart_context("BTCUSDT") is None  # TIM_RUNTIME_ENV=test
    seen = []
    monkeypatch.setenv("TIM_RUNTIME_ENV", "local")
    monkeypatch.setattr(mc.CACHE, "snapshot", lambda symbol: seen.append(symbol) or {})
    monkeypatch.setattr(mc.DOMINANCE, "snapshot", lambda: {"points": []})  # no Coin Metrics request in tests
    mc.chart_context("../../evil")
    assert mc.chart_context("ETHUSDT") == {"dominance": {"points": []}}
    assert seen == ["BTCUSDT", "ETHUSDT"]


class _Cache:
    def __init__(self, rows):
        self.rows = rows

    def get(self, symbol, timeframe, limit):
        return self.rows, None


def _candles(hours: int = 40):
    out = []
    for i in reversed(range(hours)):
        start = NOW - timedelta(hours=i + 1)
        out.append({"open_time": start.isoformat(), "close_time": (start + timedelta(hours=1) - timedelta(milliseconds=1)).isoformat(),
                    "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0, "closed": True})
    return out


def test_live_chart_carries_funding_and_premium_hidden_by_default():
    context = {"funding": mc.funding(funding_fetch(), now=NOW), "premium": mc.coinbase_premium(premium_fetch(), now=NOW)}
    model = build_live_chart("BTCUSDT", "1h", cache=_Cache(_candles()), now=NOW, context=context)
    assert model["funding"]["points"] and model["premium"]["points"]
    assert "funding" in GROUP_NAMES and "premium" in GROUP_NAMES and "funding" in GROUPS_EN and "premium" in GROUPS_EN
    assert "funding" not in DEFAULT_GROUPS and "premium" not in DEFAULT_GROUPS  # opt-in: four bands would squash the candles
    other = build_live_chart("ETHUSDT", "1h", cache=_Cache(_candles()), now=NOW, context=context)
    assert other["funding"] is None and other["premium"] is None  # BTC data never drawn under ETH
    old = build_live_chart("BTCUSDT", "1h", cache=_Cache(_candles()), now=NOW + timedelta(hours=4), context=context)
    assert old["funding"] is None and any(n.startswith("Funding Rate: Stand älter") for n in old["notes"])
    english = english_chart_model(model)
    assert "public" in english["funding"]["source"] and "öffentlich" not in english["premium"]["source"]
    assert english_note("Coinbase-Premium: Stand älter als 3 h, ausgeblendet.").startswith("Coinbase premium: data older")
    plain = build_live_chart("BTCUSDT", "1h", cache=_Cache(_candles()), now=NOW)
    assert plain["funding"] is None and plain["premium"] is None


DAY0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _dominance_fetch(days: int = 31):
    """Coin Metrics catalogue and one page with btc/usdt/eth caps per day (shares 60/7/33 % plus a drift)."""
    import json

    def fetch(url: str) -> bytes:
        if "catalog-v2" in url:
            daily = [{"metric": "CapMrktEstUSD", "frequencies": [{"frequency": "1d", "community": True}]}]
            return json.dumps({"data": [{"asset": a, "metrics": daily} for a in ("btc", "usdt", "eth", "wbtc")]}).encode()
        assert url.startswith("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?")
        rows = []
        for i in range(days):
            d = (DAY0 + timedelta(days=i)).date().isoformat() + "T00:00:00.000000000Z"
            rows += [{"asset": "btc", "time": d, "CapMrktEstUSD": str(60.0 + i / 10)}, {"asset": "usdt", "time": d, "CapMrktEstUSD": "7"},
                     {"asset": "eth", "time": d, "CapMrktEstUSD": str(33.0 - i / 10)}, {"asset": "wbtc", "time": d, "CapMrktEstUSD": "50"}]
        return json.dumps({"data": rows}).encode()
    return fetch


def test_dominance_points_sit_at_the_next_midnight_and_skip_wrapped_tokens():
    now = DAY0 + timedelta(days=31, hours=6)
    snap = mc.dominance(_dominance_fetch(), now=now)
    first = snap["points"][0]
    assert first[0] == int((DAY0 + timedelta(days=1)).timestamp())  # day 1 known from day 2 00:00 UTC
    assert first[1] == pytest.approx(60.0) and first[2] == pytest.approx(7.0)  # wbtc not counted twice
    assert snap["last_day"] == (DAY0 + timedelta(days=30)).date().isoformat()
    part = mc.dominance_chart(snap, int((DAY0 + timedelta(days=29)).timestamp()), now)
    assert part["points"][0][0] == int((DAY0 + timedelta(days=28)).timestamp())  # one day before the first candle
    assert part["stale"] is False and part["last_btc"] == pytest.approx(63.0)
    assert mc.dominance_chart(snap, 0, now + timedelta(days=4))["stale"] is True
    assert mc.dominance_chart(None, 0, now) is None


def test_live_chart_carries_dominance_hidden_and_drops_stale():
    snap = mc.dominance(_dominance_fetch(60), now=NOW)
    model = build_live_chart("ETHUSDT", "1h", cache=_Cache(_candles()), now=NOW, context={"dominance": snap})
    assert model["dominance"]["points"] and "dominance" in GROUP_NAMES and "dominance" in GROUPS_EN
    assert "dominance" not in DEFAULT_GROUPS
    old = build_live_chart("BTCUSDT", "1h", cache=_Cache(_candles()), now=NOW + timedelta(days=5), context={"dominance": snap})
    assert old["dominance"] is None and any(n.startswith("Dominanz: letzter Tageswert") for n in old["notes"])
    english = english_chart_model(model)
    assert "about 830 assets" in english["dominance"]["source"]
    assert english_note("Dominanz: letzter Tageswert älter als 3 Tage, ausgeblendet.").startswith("Dominance: last daily value")


def test_dominance_cache_keeps_last_value_and_waits_after_failure():
    calls, state = [], {"fail": False}

    def build():
        calls.append(1)
        if state["fail"]:
            raise OSError("down")
        return {"points": [[1, 60.0, 7.0]]}

    cache = mc.DominanceCache(build, ttl=0.0, fail_pause=3600.0)
    assert cache.snapshot(background=False) == {"points": [[1, 60.0, 7.0]]}
    state["fail"] = True
    assert cache.snapshot(background=False) == {"points": [[1, 60.0, 7.0]]}  # failure keeps the last value
    before = len(calls)
    cache.snapshot(background=False)
    assert len(calls) == before  # fail pause: no new request
