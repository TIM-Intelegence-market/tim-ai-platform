"""Options gamma in TIM's analyses: Deribit snapshot, Control Center, chart group, orderflow context."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from src.dashboard import chart_live, gamma_data
from src.dashboard.app import DashboardServer, DashboardState
from src.dashboard.chart_live import KlineCache, build_live_chart
from src.dashboard.public_en import english_chart_model
from src.options_gamma import OptionQuote, build_gamma_snapshot, gex_at, parse_instrument
from src.options_gamma.snapshot import flip_nearest, max_pain, quotes_from_book_summary
from src.orderflow_scenario.positioning import GammaContext, interpret_gamma, parse_context
from tests.test_chart_live import NOW as CHART_NOW, fake_fetch

FIXTURE = Path(__file__).parent / "fixtures" / "options_gamma" / "deribit_book_summary_sample.json"
DATA = json.loads(FIXTURE.read_text())
AS_OF = datetime.fromisoformat(DATA["as_of"])
SPOT = DATA["index_price"]


def _snapshot(as_of: datetime = AS_OF) -> dict:
    return build_gamma_snapshot(DATA["result"], SPOT, as_of)


def _fake_deribit(calls: list | None = None):
    def fetch(method: str, params):
        if calls is not None:
            calls.append((method, dict(params)))
        if method == "get_book_summary_by_currency":
            assert params == {"currency": "BTC", "kind": "option"}
            return {"jsonrpc": "2.0", "result": DATA["result"]}
        assert method == "get_index_price" and params == {"index_name": "btc_usd"}
        return {"jsonrpc": "2.0", "result": {"index_price": SPOT}}
    return fetch


# --- pure snapshot -------------------------------------------------------------------------------


@pytest.mark.parametrize("name,expected", [
    ("BTC-30OCT26-80000-C", ("BTC", datetime(2026, 10, 30, 8, tzinfo=timezone.utc), 80000.0, True)),
    ("BTC-5NOV26-75000-P", ("BTC", datetime(2026, 11, 5, 8, tzinfo=timezone.utc), 75000.0, False)),
    ("ETH-27NOV26-3500-C", ("ETH", datetime(2026, 11, 27, 8, tzinfo=timezone.utc), 3500.0, True)),
    ("XRP_USDC-30OCT26-2d5-P", None),
    ("BTC-PERPETUAL", None),
    ("BTC-30XYZ26-80000-C", None),
])
def test_parse_instrument(name, expected) -> None:
    if expected is None:
        with pytest.raises(ValueError):
            parse_instrument(name)
    else:
        assert parse_instrument(name) == expected


def test_quotes_skip_rows_without_open_interest_expired_and_foreign() -> None:
    rows = DATA["result"] + [{"instrument_name": "ETH-30OCT26-3500-C", "open_interest": 5, "mark_iv": 50},
                             {"instrument_name": "BTC-26OCT26-80000-C", "open_interest": 5, "mark_iv": 50},
                             {"instrument_name": "BTC-30OCT26-81000-C", "open_interest": 5, "mark_iv": None},
                             {"instrument_name": "nonsense", "open_interest": 5, "mark_iv": 50}]
    quotes, skipped = quotes_from_book_summary(rows, "BTC", AS_OF)
    assert len(quotes) == 20
    assert skipped == {"unparsed": 1, "other_currency": 1, "expired": 1, "no_open_interest": 4, "no_iv": 1}
    assert all(q.implied_vol < 1 for q in quotes)  # mark_iv is in percent


def test_snapshot_from_real_deribit_excerpt() -> None:
    snap = _snapshot()
    overall, main = snap["all_expiries"], snap["main_expiry"]
    assert snap["source"] == "DERIBIT_PUBLIC_OPTIONS_BOOK_SUMMARY" and snap["mode"] == "OBSERVE"
    assert overall["contracts"] == 20 and overall["regime"] == "POSITIVE_GAMMA"
    # Walls sit on their side of the price instead of both at the ATM strike.
    assert overall["call_wall"] >= SPOT and overall["put_wall"] <= SPOT
    assert overall["call_wall"] == 80000.0 and overall["put_wall"] == 78000.0
    assert SPOT * 0.85 < overall["gamma_flip"] < SPOT * 1.15
    # Main expiry: the Friday with by far the most open interest in the next seven days.
    assert main["expiry"] == "2026-10-30T08:00:00+00:00" and main["share_of_open_interest"] > 0.9
    move = snap["expected_move"]
    assert move["atm_iv"] == pytest.approx(0.3506)
    years = (datetime(2026, 10, 30, 8, tzinfo=timezone.utc) - AS_OF).total_seconds() / (365 * 86400)
    assert move["move"] == pytest.approx(SPOT * 0.3506 * math.sqrt(years), abs=0.01)
    assert move["low"] == pytest.approx(77385.24, abs=0.01) and move["high"] == pytest.approx(82360.22, abs=0.01)
    assert [item["key"] for item in snap["levels"]] == ["flip", "call_wall", "put_wall", "max_pain", "em_high", "em_low"]
    assert snap["analysis_input"]["gamma_flip"] == overall["gamma_flip"]
    assert snap["skipped"]["no_open_interest"] == 4
    assert len(snap["input_hash"]) == 64 and _snapshot()["input_hash"] == snap["input_hash"]


def test_flip_is_the_crossing_nearest_to_spot() -> None:
    expiry = AS_OF + timedelta(days=3)
    quotes = [OptionQuote(90.0, expiry, False, 100, 0.5), OptionQuote(100.0, expiry, True, 100, 0.5),
              OptionQuote(110.0, expiry, False, 100, 0.5)]
    flip = flip_nearest(quotes, 100.0, AS_OF)
    assert flip is not None
    assert gex_at(quotes, flip, AS_OF) == pytest.approx(0, abs=gex_at(quotes, 100.0, AS_OF) * 0.02)
    # Only calls: gamma is positive everywhere, so there is no flip.
    assert flip_nearest([quotes[1]], 100.0, AS_OF) is None
    assert flip_nearest([], 100.0, AS_OF) is None


def test_max_pain_minimises_holder_payout() -> None:
    expiry = AS_OF + timedelta(days=3)
    quotes = [OptionQuote(100.0, expiry, False, 10, 0.5), OptionQuote(100.0, expiry, True, 10, 0.5),
              OptionQuote(110.0, expiry, True, 1, 0.5), OptionQuote(90.0, expiry, False, 1, 0.5)]
    # Payout at 90: 100 (puts at 100); at 100: 0; at 110: 100 (calls at 100).
    assert max_pain(quotes) == 100.0
    assert max_pain([]) is None


def test_snapshot_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        build_gamma_snapshot(DATA["result"], 0, AS_OF)
    with pytest.raises(ValueError):
        build_gamma_snapshot(DATA["result"], SPOT, AS_OF.replace(tzinfo=None))
    with pytest.raises(ValueError):
        build_gamma_snapshot([], SPOT, AS_OF)
    with pytest.raises(ValueError):  # everything expired
        build_gamma_snapshot(DATA["result"], SPOT, AS_OF + timedelta(days=10))


# --- Control Center ------------------------------------------------------------------------------


def test_refresh_stores_snapshot_and_reads_two_public_endpoints() -> None:
    state, calls = DashboardState(), []
    snap = gamma_data.refresh(state, "BTCUSDT", fetch=_fake_deribit(calls), now=AS_OF)
    assert state.gamma["BTCUSDT"] is snap and snap["spot"] == SPOT
    assert [method for method, _ in calls] == ["get_book_summary_by_currency", "get_index_price"]
    assert gamma_data.refresh(state, "SOLUSDT", fetch=_fake_deribit()) is None  # no options data for SOL
    assert gamma_data.DERIBIT_PUBLIC.startswith("https://www.deribit.com/api/v2/public")


def test_fetch_rejects_malformed_answers() -> None:
    with pytest.raises(ValueError):
        gamma_data.fetch_snapshot(fetch=lambda method, params: {"error": {"code": 10028}})
    with pytest.raises(ValueError):
        gamma_data.fetch_snapshot(fetch=lambda method, params: {"result": {"oops": 1}})

    def no_index(method, params):
        return {"result": DATA["result"]} if method == "get_book_summary_by_currency" else {"result": {"index_price": None}}

    with pytest.raises(ValueError):
        gamma_data.fetch_snapshot(fetch=no_index, now=AS_OF)


def test_prep_block_status_and_staleness() -> None:
    assert gamma_data.prep_block(None)["status"] == "MISSING"
    snap = _snapshot()
    fresh = gamma_data.prep_block(snap, AS_OF + timedelta(minutes=5))
    assert fresh["status"] == "OK" and fresh["age_seconds"] == 300
    assert fresh["levels"][0]["name"] == "Gamma Flip" and fresh["analysis_input"]["call_wall"] == 80000.0
    assert gamma_data.prep_block(snap, AS_OF + timedelta(minutes=21))["status"] == "STALE"
    drawings, notes = gamma_data.chart_drawings(snap, AS_OF + timedelta(minutes=21))
    assert drawings == [] and notes and "ausgeblendet" in notes[0]


def test_chart_draws_gamma_group_with_own_colours_also_in_the_public_view() -> None:
    snap = _snapshot(as_of=CHART_NOW - timedelta(minutes=3))
    model = build_live_chart("BTCUSDT", "30m", None, cache=KlineCache(fake_fetch()), now=CHART_NOW, gamma={"BTCUSDT": snap})
    gamma = [d for d in model["drawings"] if d["group"] == "gamma"]
    assert {d["label"] for d in gamma} >= {"Opt Gamma Flip", "Opt Call Wall", "Opt Put Wall"}
    flip = next(d for d in gamma if d["name"] == "Gamma Flip")
    assert flip["color"] == gamma_data.LEVEL_STYLE["flip"][0] and flip["p1"] == flip["p2"] == flip["price"]
    assert flip["t2"] == model["candles"][-1]["time"] and flip["bars"] > 1
    assert "gamma" in model["groups"] and "gamma" in model["default_groups"]
    # Other symbols carry no gamma.
    eth = build_live_chart("ETHUSDT", "30m", None, cache=KlineCache(fake_fetch()), now=CHART_NOW, gamma={"BTCUSDT": snap})
    assert not any(d["group"] == "gamma" for d in eth["drawings"])
    # The public English view shows gamma too, with English labels and notes (Uzi 27.10.2026).
    public = english_chart_model(model)
    assert public["groups"]["gamma"] == "Options gamma (Deribit)" and "gamma" in public["default_groups"]
    public_gamma = [d for d in public["drawings"] if d["group"] == "gamma"]
    labels = {d["label"] for d in public_gamma}
    assert {"Opt Gamma Flip", "Opt Call Wall", "Opt Put Wall"} <= labels
    assert any(label.startswith("Opt EM high ") for label in labels) and any(label.startswith("Opt EM low ") for label in labels)
    for d in public_gamma:
        assert not re.search(r"[äöüß]|hoch|tief|Händler|Verfall", f"{d['name']} {d['label']} {d['note']}"), d
    stale_note = gamma_data.chart_drawings(snap, CHART_NOW + timedelta(hours=1))[1][0]
    assert english_chart_model({"notes": [stale_note]})["notes"] == ["Gamma: Deribit data is 63 min old, levels hidden."]


def test_server_serves_gamma_and_adds_it_to_prep(monkeypatch) -> None:
    monkeypatch.setattr(chart_live, "CACHE", KlineCache(fake_fetch()))
    state = DashboardState()
    server = DashboardServer(state, port=0)
    server.start()
    port = server.server.server_address[1]
    try:
        with pytest.raises(HTTPError) as missing:
            urlopen(f"http://127.0.0.1:{port}/api/gamma", timeout=5)
        assert missing.value.code == 404
        with urlopen(f"http://127.0.0.1:{port}/api/prep", timeout=10) as response:
            assert json.loads(response.read())["gamma"]["status"] == "MISSING"
        gamma_data.refresh(state, "BTCUSDT", fetch=_fake_deribit(), now=AS_OF)
        with state.lock:  # the fixture's expiries lie in the past later on: only the age is made current
            state.gamma["BTCUSDT"] = {**state.gamma["BTCUSDT"], "as_of": datetime.now(timezone.utc).isoformat()}
        with urlopen(f"http://127.0.0.1:{port}/api/gamma?symbol=BTCUSDT", timeout=5) as response:
            body = json.loads(response.read())
        assert body["stale"] is False and body["all_expiries"]["call_wall"] == 80000.0
        with urlopen(f"http://127.0.0.1:{port}/api/prep", timeout=10) as response:
            prep = json.loads(response.read())["gamma"]
        assert prep["status"] == "OK" and prep["analysis_input"]["put_wall"] == 78000.0
    finally:
        server.stop()


# --- orderflow analysis context ----------------------------------------------------------------


def test_parse_context_reads_gamma_and_rejects_nonsense() -> None:
    parsed = parse_context({"gamma": _snapshot()["analysis_input"]})
    assert isinstance(parsed.gamma, GammaContext) and parsed.rejected == []
    assert parsed.gamma.call_wall == Decimal("80000.0") and parsed.gamma.as_of == AS_OF
    bad = parse_context({"gamma": {"gamma_flip": -5, "call_wall": 70000, "put_wall": 80000}})
    assert bad.gamma is None and any(item.startswith("gamma.gamma_flip") for item in bad.rejected)
    assert any(item.startswith("gamma:call_wall") for item in bad.rejected)
    assert parse_context({"gamma": "high"}).rejected == ["gamma:not_an_object"]
    assert parse_context({}).gamma is None


def test_interpret_gamma_reads_location_without_score() -> None:
    gamma = parse_context({"gamma": _snapshot()["analysis_input"]}).gamma
    above, summary = interpret_gamma(gamma, Decimal("80500"))
    texts = [s.text for s in above]
    assert summary["price_vs_flip"] == "ABOVE_FLIP" and summary["regime"] == "POSITIVE_GAMMA"
    assert "above_gamma_flip_dealer_hedging_dampens_moves" in texts
    assert summary["expected_move_location"] == "INSIDE_EXPECTED_MOVE"
    assert all(s.kind.value != "CONFIRMATION" for s in above)
    below, summary = interpret_gamma(gamma, Decimal("76000"))
    assert summary["price_vs_flip"] == "BELOW_FLIP" and summary["expected_move_location"] == "OUTSIDE_EXPECTED_MOVE"
    assert "below_gamma_flip_dealer_hedging_amplifies_moves" in [s.text for s in below]
    at, summary = interpret_gamma(gamma, Decimal(str(gamma.gamma_flip)))
    assert summary["price_vs_flip"] == "AT_FLIP"
    assert interpret_gamma(None, Decimal("80000")) == ((), {})


def test_pipeline_carries_gamma_into_the_analysis_output() -> None:
    from src.orderflow_scenario.adapters.generic import GenericOrderflowAdapter
    from src.orderflow_scenario.cli import _pipeline_inputs
    from src.orderflow_scenario.engines.pipeline import Pipeline

    base = {"symbol": "BTCUSDT", "venue": "BINANCE", "market_type": "FUTURES", "timeframe": "30m", "price_now": 80500,
            "candles": [{"open_time": "2026-10-27T10:00:00+00:00", "timeframe": "30m", "open": 80300, "high": 80600,
                         "low": 80200, "close": 80500, "volume": 10, "closed": True}]}
    with_gamma = dict(base, gamma=_snapshot()["analysis_input"])
    outputs = []
    for data in (base, with_gamma):
        inputs = _pipeline_inputs(GenericOrderflowAdapter(), data, observed_at=datetime(2026, 10, 27, 11, tzinfo=timezone.utc))
        outputs.append(Pipeline().run(inputs).to_dict())
    plain, gamma = outputs
    assert plain["orderflow"]["gamma"] == {}
    assert gamma["orderflow"]["gamma"]["price_vs_flip"] == "ABOVE_FLIP"
    # Context only: decision and confidence do not move.
    assert gamma["decision"]["status"] == plain["decision"]["status"]
    assert gamma["orderflow"]["confidence"] == plain["orderflow"]["confidence"]
