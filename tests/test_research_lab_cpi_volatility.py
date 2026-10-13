"""Study S1 (BTC range around CPI releases): offline tests on the real ALFRED fixture and synthetic candles."""
from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from src.research_lab.data.parse import Kline
from src.research_lab.external.alfred import parse_bundle
from src.research_lab.external.align import BtcSeries
from src.research_lab.external.events import EventStatus, release_events
from src.research_lab.external.fixture_window import load_fixture
from src.research_lab.external.pit import PointInTimeStore
from src.research_lab.external.realcheck import FINAL_REPLAY_AT
from src.research_lab.external.records import utc_to_ms
from src.research_lab.studies import cpi_volatility as s1

HOUR = 3_600_000


def _ms(*args: int) -> int:
    return utc_to_ms(datetime(*args, tzinfo=timezone.utc))


def _klines(start_ms: int, end_ms: int, *, wide: set[int] = frozenset(), factor: float = 3.0, skip: set[int] = frozenset(), narrow: set[int] = frozenset()) -> list[Kline]:
    out = []
    for i, open_time in enumerate(range(start_ms, end_ms, HOUR)):
        if open_time in skip:
            continue
        spread = 0.002 * (1 + (i * 37 % 11) / 11)
        if open_time in wide:
            spread *= factor
        if open_time in narrow:
            spread *= 0.3
        price = 20_000.0
        out.append(Kline(open_time, price, price * (1 + spread), price * (1 - spread), price, 1.0, open_time + HOUR - 1, 0.5))
    return out


def _series(klines: list[Kline]) -> BtcSeries:
    return BtcSeries.build(klines, "1h", replay_at=FINAL_REPLAY_AT, invalid_candles="exclude")


def _fixture_events():
    raw, _ = load_fixture()
    return release_events(PointInTimeStore(parse_bundle(raw)), until=FINAL_REPLAY_AT)


def _release_candle(event) -> int:
    t = utc_to_ms(event.event_time)
    return t - t % HOUR


def _synthetic_events(base, months: list[tuple[int, int]]):
    """Copies of a real OK event moved to the 13th of each month at 08:30 New York (12:30/13:30 UTC)."""
    events = []
    for year, month in months:
        hour = 12 if 3 < month < 11 else 13
        t = datetime(year, month, 13, hour, 30, tzinfo=timezone.utc)
        events.append(replace(base, event_id=f"{base.event_id}#{year}-{month}", event_time=t, available_at=t))
    return events


def test_sign_test_p_exact_values():
    assert s1.sign_test_p(0, 0) == 1.0
    assert s1.sign_test_p(10, 10) == pytest.approx(1 / 1024)
    assert s1.sign_test_p(5, 10) == pytest.approx(sum(math.comb(10, k) for k in range(5, 11)) / 1024)


def test_window_range_needs_every_candle():
    start = _ms(2020, 1, 6)
    btc = _series(_klines(start, start + 48 * HOUR, skip={start + 3 * HOUR}))
    assert s1.window_range(btc, start, 3) is not None
    assert s1.window_range(btc, start, 4) is None


def test_fixture_events_are_eligible_and_measured_at_the_release_candle():
    events = _fixture_events()
    eligible = s1.eligible_events(events)
    assert eligible and all(e.status is EventStatus.OK for e in eligible)
    # BLS 08:30 New York lies inside the 12:00 or 13:00 UTC candle.
    assert {datetime.fromtimestamp(_release_candle(e) / 1000, timezone.utc).hour for e in eligible} <= {12, 13}


def test_effect_in_fixture_without_validation_events_is_not_confirmed():
    events = _fixture_events()
    wide = {_release_candle(e) for e in s1.eligible_events(events)}
    btc = _series(_klines(_ms(2018, 11, 1), _ms(2021, 3, 1), wide=wide))
    result = s1.run_study(events, btc)
    one = result["windows"]["1h"]
    # The fixture holds three first prints (2019-12 to 2020-02): a large ratio, but far too few for the test.
    assert one["overall"]["n"] == 3 and one["overall"]["positive"] == 3
    assert one["overall"]["median_ratio"] > 2
    assert one["overall"]["p_sign"] == pytest.approx(1 / 8)
    assert not one["holm_significant"]
    assert one["by_split"]["validation"]["n"] == 0
    assert result["primary_verdict"] == "NICHT_BESTAETIGT"


def test_confirmed_only_with_effect_in_both_splits():
    base = s1.eligible_events(_fixture_events())[0]
    months = [(y, m) for y in range(2019, 2025) for m in range(1, 13)]
    events = _synthetic_events(base, months)
    wide = {_release_candle(e) for e in events}
    start, end = _ms(2018, 11, 1), _ms(2024, 12, 31, 22)
    confirmed = s1.run_study(events, _series(_klines(start, end, wide=wide)))
    assert confirmed["primary_verdict"] == "BESTAETIGT"
    assert confirmed["windows"]["1h"]["by_split"]["validation"]["n"] > 0
    flat = s1.run_study(events, _series(_klines(start, end)))
    assert flat["primary_verdict"] == "NICHT_BESTAETIGT"
    only_train = {c for c in wide if c < _ms(2023, 1, 1)}
    split = s1.run_study(events, _series(_klines(start, end, wide=only_train, narrow=wide - only_train)))
    assert split["windows"]["1h"]["holm_significant"] and not split["windows"]["1h"]["splits_positive"]
    assert split["primary_verdict"] == "NICHT_BESTAETIGT"


def test_controls_skip_holdout_and_other_releases():
    base = s1.eligible_events(_fixture_events())[0]
    december = _synthetic_events(base, [(2024, 12)])[0]  # 2024-12-13 13:30 UTC
    btc = _series(_klines(_ms(2024, 10, 1), _ms(2024, 12, 31, 22)))
    alone = s1.measure_event(december, btc, 1, [utc_to_ms(december.available_at)])
    # -4..-1 and +1, +2 weeks; +3 and +4 weeks lie in the holdout (2025).
    assert alone["controls"] == 6 and alone["status"] == "OK"
    november = replace(december, event_id="nov", event_time=datetime(2024, 11, 22, 13, 30, tzinfo=timezone.utc),
                       available_at=datetime(2024, 11, 22, 13, 30, tzinfo=timezone.utc))
    both = s1.measure_event(december, btc, 1, sorted(utc_to_ms(e.available_at) for e in (november, december)))
    assert both["controls"] == 5  # the -3 week control sits on another release


def test_too_few_controls_and_missing_event_candle():
    base = s1.eligible_events(_fixture_events())[0]
    event = _synthetic_events(base, [(2020, 6)])[0]
    candle = _release_candle(event)
    short = _series(_klines(candle - 3 * 7 * 24 * HOUR, candle + 2 * HOUR))
    assert s1.measure_event(event, short, 1, [])["status"] == "TOO_FEW_CONTROLS"
    gap = _series(_klines(candle - 30 * 24 * HOUR, candle + 30 * 24 * HOUR, skip={candle}))
    assert s1.measure_event(event, gap, 1, [])["status"] == "EVENT_WINDOW_INCOMPLETE"


def test_study_refuses_holdout_series_and_other_intervals():
    late = datetime(2025, 1, 2, tzinfo=timezone.utc)
    btc = BtcSeries.build(_klines(_ms(2024, 12, 1), _ms(2024, 12, 31, 22)), "1h", replay_at=late, invalid_candles="exclude")
    with pytest.raises(ValueError):
        s1.run_study([], btc)


def test_deterministic():
    events = _fixture_events()
    wide = {_release_candle(e) for e in s1.eligible_events(events)}
    btc = _series(_klines(_ms(2018, 11, 1), _ms(2021, 3, 1), wide=wide, factor=1.5))
    assert s1.run_study(events, btc) == s1.run_study(events, btc)
    assert "Primärurteil" in s1.render_markdown(s1.run_study(events, btc), {"bundle_id": "x"})
