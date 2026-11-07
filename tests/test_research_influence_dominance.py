"""BTC/USDT dominance substitute for the influence research (Coin Metrics, chain-linked, holdout closed)."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from src.research_lab.forward.macro_filters import MacroDataError
from src.research_lab.influence import __main__ as cli
from src.research_lab.influence import dominance as dom
from src.research_lab.influence.catalog import all_series, by_key
from src.research_lab.influence.states import driver_weeks, weeks

_DAILY = [{"metric": "CapMrktEstUSD", "frequencies": [{"frequency": "1d", "community": True}]}]
_HOURLY = [{"metric": "CapMrktEstUSD", "frequencies": [{"frequency": "1h", "community": True}]}]
_NAMES = ("btc", "eth", "usdt", "usdt_eth", "usdt_trx", "wbtc", "leo_eth", "leo_eos", "bnb")
CATALOG = json.dumps({"data": [{"asset": a, "metrics": _DAILY} for a in _NAMES]
                      + [{"asset": "xyz", "metrics": _HOURLY}]}).encode()


def page(rows, nxt=None) -> bytes:
    body = {"data": [{"asset": a, "time": f"{d}T00:00:00.000000000Z", "CapMrktEstUSD": str(v)} for a, d, v in rows]}
    if nxt:
        body["next_page_url"] = nxt
    return json.dumps(body).encode()


def test_basket_drops_chain_variants_and_wrapped_tokens():
    assets = dom.community_assets(CATALOG)
    assert "xyz" not in assets
    assert dom.basket(assets) == ["bnb", "btc", "eth", "leo_eos", "leo_eth", "usdt"]


def test_share_uses_basket_assets_present_that_day():
    caps = {
        date(2020, 1, 1): {"btc": 60.0, "eth": 20.0, "bnb": 20.0, "wbtc": 50.0},
        date(2020, 1, 2): {"btc": 60.0, "eth": 20.0},
        date(2020, 1, 3): {"eth": 1.0},  # no BTC value: no entry
    }
    assert dom.raw_share(caps[date(2020, 1, 2)], "btc") == pytest.approx(75.0)
    series = dom.share_series(caps, "btc", ["btc", "eth", "bnb"])
    assert series == [(date(2020, 1, 1), pytest.approx(60.0)), (date(2020, 1, 2), pytest.approx(75.0))]
    assert dom.share_series({date(2020, 1, 1): {"btc": 25.0, "usdt": 75.0}}, "usdt", ["btc", "usdt"])[0][1] == pytest.approx(75.0)


def test_parse_caps_skips_broken_rows_and_follows_pages():
    calls = []
    p2 = dom.BASE + "timeseries/asset-metrics?next_page_token=x"
    pages = {1: page([("btc", "2020-01-01", 2.0), ("eth", "2020-01-01", "bad")], nxt=p2), 2: page([("btc", "2020-01-02", 0)])}

    def fetch(url):
        calls.append(url)
        return pages[2] if "next_page_token" in url else pages[1]

    bodies = dom.fetch_pages(fetch, ["btc", "eth"], "2020-01-01", "2020-01-02")
    assert len(bodies) == 2 and len(calls) == 2
    assert dom.parse_caps(bodies) == {date(2020, 1, 1): {"btc": 2.0}}


def test_next_page_elsewhere_and_foreign_host_refused():
    with pytest.raises(MacroDataError):
        dom.fetch_pages(lambda url: page([], nxt="https://evil.example/x"), ["btc"], "2020-01-01", "2020-01-02")
    with pytest.raises(MacroDataError):
        dom.http_fetcher(sleep=lambda s: None)("https://evil.example/v4/x")


def _fake_cm(url: str) -> bytes:
    if "catalog-v2" in url:
        return CATALOG
    assert "end_time=2024-12-31" in url
    rows = []
    for i, day in enumerate(weeks(date(2019, 7, 1), date(2020, 4, 6))):
        for k in range(7):
            d = date.fromordinal(day.toordinal() + k).isoformat()
            rows += [("btc", d, 60.0 + i), ("eth", d, 30.0), ("usdt", d, 10.0 - i * 0.1)]
    return page(rows)


def test_fetch_and_load_history_with_hash_check_and_holdout(tmp_path):
    hashes = dom.fetch_history(tmp_path, _fake_cm)
    assert "meta.json" not in hashes and "catalog.json" in hashes
    data, h = dom.load_history(tmp_path)
    assert set(data) == {dom.BTC_SERIES, dom.USDT_SERIES} and "coinmetrics_dominanz" in h
    assert all(d < date(2025, 1, 1) for s in data.values() for d, _ in s)
    rows = driver_weeks(by_key("BTCD"), data, weeks(date(2019, 7, 1), date(2020, 4, 6)))
    assert rows[14].state == "gestiegen" and rows[14].change_13w > 0
    assert driver_weeks(by_key("USDTD"), data, weeks(date(2019, 7, 1), date(2020, 4, 6)))[14].state == "gefallen"
    (tmp_path / "roh" / "dominanz" / "seite_000.json").write_bytes(b"{}")
    with pytest.raises(MacroDataError):
        dom.load_history(tmp_path)
    with pytest.raises(MacroDataError):
        dom.fetch_history(tmp_path, _fake_cm, end="2025-01-01")


def test_load_history_empty_without_fetch(tmp_path):
    assert dom.load_history(tmp_path) == ({}, {})


def test_catalog_drivers_are_crypto_with_lead_rule_and_not_sent_to_fred():
    for key in ("BTCD", "USDTD"):
        d = by_key(key)
        assert d.family == "krypto" and d.needs_lead and d.source == "coinmetrics" and d.change == "diff"
    assert "CM_BTC_DOMINANCE" not in all_series() and all_series("coinmetrics") == ("CM_BTC_DOMINANCE", "CM_USDT_DOMINANCE")


def test_cli_dominanz_command(tmp_path, monkeypatch):
    monkeypatch.setattr(dom, "http_fetcher", lambda **kw: _fake_cm)
    assert cli.main(["dominanz", "--folder", str(tmp_path)], now=datetime(2026, 11, 7, tzinfo=timezone.utc)) == 0
    assert (tmp_path / "roh" / "dominanz" / "meta.json").exists()


def test_crypto_drivers_stay_out_of_the_joint_view():
    from src.research_lab.influence import report

    data, _ = {}, None
    btc = {w: 1.0 for w in weeks()}
    result = report.build(data, btc, now=datetime(2026, 11, 7, tzinfo=timezone.utc))
    joint = result["gemeinsam"]
    assert joint["krypto_getrennt"] == ["BTCD", "USDTD"]
    assert "BTCD" not in joint["treiber"] and "BTCD" not in joint["ausgelassen"]
    assert "Krypto-interne Reihen" in report.markdown(result)


def test_fetcher_retries_network_errors_then_fails_cleanly(monkeypatch):
    import urllib.error

    calls = []

    def boom(url, timeout):
        calls.append(url)
        raise urllib.error.URLError("down")

    monkeypatch.setattr(dom.urllib.request, "urlopen", boom)
    with pytest.raises(MacroDataError, match="not reachable"):
        dom.http_fetcher(sleep=lambda s: None, attempts=3)(dom.catalog_url())
    assert len(calls) == 3


def test_recent_builds_today_series_from_the_last_days():
    def fetch(url):
        if "catalog-v2" in url:
            return CATALOG
        assert "start_time=2026-07-10" in url and "end_time=2026-11-07" in url
        return page([("btc", "2026-11-06", 59.3), ("usdt", "2026-11-06", 6.9), ("eth", "2026-11-06", 33.8)])

    data = dom.recent(fetch, date(2026, 11, 7))
    assert data[dom.BTC_SERIES] == [(date(2026, 11, 6), pytest.approx(59.3))]
