"""Market check and paper diary for the group's calls. Texts and prices are test fixtures, not real data."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from src.knowledge.goathub_channels import PROFILES, TrackedCall, read_call, set_source_names
from src.knowledge.goathub_feed import GoatHubMessage
from src.knowledge.goathub_market_check import (
    COST_PER_SIDE,
    DiaryEntry,
    Instrument,
    MarketBar,
    MarketSnapshot,
    author_scorecards,
    build_diary,
    check_market,
    merge_diary,
    render_diary_report,
)

set_source_names({})

T0 = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
STEP = timedelta(minutes=15)


def series(path: list[tuple[float, float]], *, start: datetime, volume: float = 1_000_000.0) -> list[MarketBar]:
    bars = []
    for index, (low, high) in enumerate(path):
        middle = Decimal(str((low + high) / 2))
        bars.append(MarketBar(start + STEP * index, middle, Decimal(str(high)), Decimal(str(low)), middle, Decimal(str(volume))))
    return bars


def snapshot(path: list[tuple[float, float]], *, symbol: str = "ABCUSDT", status: str = "OPEN", volume: float = 1_000_000.0,
             history: int = 96) -> MarketSnapshot:
    """24 h of flat history before T0, then ``path`` from T0 on."""
    first = path[0]
    before = series([first] * history, start=T0 - STEP * history, volume=volume)
    bars = before + series(path, start=T0, volume=volume)
    return MarketSnapshot(T0 + STEP * len(path), STEP, {symbol: Instrument(symbol, status, 50)}, {symbol: bars})


def tracked(text: str = "Short abc SL 1.1\nTarget 0.8", *, known_after: int = 0, author: str = "Autor B") -> TrackedCall:
    posted = T0
    chat = author == "Autor A"  # Autor A's altcoin posts are read from the chat channel
    message = GoatHubMessage(message_id=f"m-{abs(hash((text, author, known_after))) % 100000}", channel_id="kanal-5" if chat else "kanal-3",
                             posted_at=posted, content=text, received_at=posted + STEP * known_after, author_name=author,
                             channel_name="KANAL-5" if chat else "KANAL-3", channel_role="knowledge" if chat else "calls")
    result = read_call(message, PROFILES["chat_altcoins" if chat else "spot_coins"], reference_price=Decimal("1.0"))
    assert result is not None
    return result


FLAT = [(0.99, 1.01)] * 8  # price about 1.00


def test_tradable_call_gets_entry_stop_target() -> None:
    verdict = check_market(tracked(), snapshot(FLAT))
    assert verdict.tradable and verdict.code == "tradable"
    assert verdict.entry == Decimal("1.00") and verdict.stop == Decimal("1.1") and verdict.target == Decimal("0.8")


def test_unknown_or_closed_coin_is_not_tradable() -> None:
    assert check_market(tracked(), snapshot(FLAT, symbol="OTHERUSDT")).code == "not_listed"
    assert check_market(tracked(), snapshot(FLAT, status="CLOSE_ONLY")).code == "not_open"


def test_thin_trading_is_not_tradable() -> None:
    verdict = check_market(tracked(), snapshot(FLAT, volume=1_000.0))
    assert verdict.code == "thin_volume" and not verdict.tradable


def test_missing_history_is_no_prices_not_a_guess() -> None:
    assert check_market(tracked(), snapshot(FLAT, history=10)).code == "no_prices"


def test_call_without_stop_is_never_entered() -> None:
    assert check_market(tracked("Short abc\nTarget 0.8"), snapshot(FLAT)).code == "no_stop"


def test_price_ran_away_while_tim_was_reading() -> None:
    drop = [(0.99, 1.01)] + [(0.89, 0.91)] * 7  # fell about 10 % of 20 % way to the target after the first bar
    verdict = check_market(tracked(known_after=3), snapshot(drop))
    assert verdict.code == "ran_away" and "Wegs" in verdict.reason
    assert check_market(tracked(known_after=0), snapshot(drop)).tradable  # read at once: still fine


def test_stop_or_target_reached_before_entry() -> None:
    spike = [(0.99, 1.01), (1.0, 1.2)] + [(0.99, 1.01)] * 6
    assert check_market(tracked(known_after=4), snapshot(spike)).code == "stop_hit_before_entry"
    dip = [(0.99, 1.01), (0.7, 0.99)] + [(0.99, 1.01)] * 6
    assert check_market(tracked(known_after=4), snapshot(dip)).code == "target_reached_before_entry"


def test_tight_stop_is_too_expensive() -> None:
    tight = tracked("Short abc SL 1.002")
    assert COST_PER_SIDE * 2 > Decimal("0.002") * Decimal("0.1")
    assert check_market(tight, snapshot(FLAT)).code == "too_expensive"
    poor = tracked("Short abc SL 1.1\nTarget 0.95")  # reward 5 % against risk 10 %
    assert check_market(poor, snapshot(FLAT)).code == "too_expensive"


def test_diary_follows_trade_to_target_and_stop_net_of_costs() -> None:
    win = snapshot(FLAT + [(0.85, 0.95), (0.75, 0.85)])
    entry = build_diary({"x": [tracked()]}, win)[0]
    assert entry.status == "target_hit" and entry.entry == Decimal("1.00") and entry.exit_price == Decimal("0.8")
    assert Decimal("1.5") < entry.net_r < Decimal("2.0")  # 2 R gross minus costs
    loss = snapshot(FLAT + [(1.05, 1.15)])
    entry = build_diary({"x": [tracked()]}, loss)[0]
    assert entry.status == "stopped" and entry.net_r < Decimal("-1")


def test_diary_marks_open_trade_and_lists_untradable_with_reason() -> None:
    entries = build_diary({"x": [tracked(), tracked("Short abc\nTarget 0.8", author="Autor A")]}, snapshot(FLAT))
    by_author = {item.author: item for item in entries}
    assert by_author["Autor B"].status == "open" and by_author["Autor B"].net_r is not None
    assert by_author["Autor A"].status == "not_entered" and by_author["Autor A"].verdict == "no_stop"


def test_merge_keeps_first_decision_and_updates_outcome(tmp_path: Path) -> None:
    open_entry = build_diary({"x": [tracked()]}, snapshot(FLAT))[0]
    later = build_diary({"x": [tracked()]}, snapshot(FLAT + [(0.75, 0.85)]))[0]
    merged = merge_diary([open_entry], [later])
    assert len(merged) == 1 and merged[0].status == "target_hit"
    moved = replace(later, entry=Decimal("0.9"))  # a changed entry never overwrites the first one
    assert merge_diary([open_entry], [moved])[0].entry == open_entry.entry
    assert DiaryEntry.from_dict(open_entry.to_dict()) == open_entry


def test_scorecards_and_report_are_per_author_and_say_when_sample_is_small() -> None:
    entries = build_diary({"x": [tracked(), tracked("Short abc\nTarget 0.8", author="Autor A")]}, snapshot(FLAT + [(0.75, 0.85)]))
    cards = author_scorecards(entries)
    assert cards["autor b"]["target_hit"] == 1 and cards["autor a"]["tradable"] == 0
    report = render_diary_report(entries, T0)
    assert "## Autor B" in report and "## Autor A" in report and "zu wenige Trades" in report and "kein Stop genannt" in report


def test_snapshot_loads_bitunix_rows() -> None:
    payload = {"taken_at": T0.isoformat(), "interval_minutes": 15,
               "instruments": [{"symbol": "ABCUSDT", "symbolStatus": "OPEN", "maxLeverage": 50, "minTradeVolume": "1"}],
               "bars": {"ABCUSDT": [{"time": "1795000000000", "open": "1", "high": "1.1", "low": "0.9", "close": "1.0", "quoteVol": "5"}]}}
    loaded = MarketSnapshot.from_dict(payload)
    assert loaded.instruments["ABCUSDT"].status == "OPEN" and loaded.bars["ABCUSDT"][0].quote_volume == Decimal("5")


def test_call_with_a_chart_image_but_no_stop_is_marked_for_manual_check() -> None:
    from src.knowledge.goathub_channels import has_chart_image
    call = tracked("Short abc\nTarget 0.8")
    image = replace(call, call=replace(call.call, message=replace(call.call.message, attachments=("Bild: ABC/USDT-Chart",))))
    assert has_chart_image(image.call.message) and not has_chart_image(call.call.message)
    assert check_market(image, snapshot(FLAT)).code == "stop_maybe_in_image"
    assert check_market(call, snapshot(FLAT)).code == "no_stop"


def test_stop_far_from_the_price_is_not_a_trade() -> None:
    assert check_market(tracked("Long abc SL 0.55"), snapshot(FLAT)).code == "stop_too_far"


def test_chart_calls_without_a_stop_are_listed_not_dropped() -> None:
    message = GoatHubMessage(message_id="b1", channel_id="kanal-6", posted_at=T0, content="Small gamble long", received_at=T0,
                             author_name="Autor D", channel_name="KANAL-6")
    from src.knowledge.goathub_channels import read_calls
    calls = read_calls([replace(message, message_id="b0", content="Fc abc", posted_at=T0 - STEP, received_at=T0 - STEP), message])
    entries = build_diary(calls, snapshot(FLAT))
    assert len(entries) == 1 and entries[0].symbol == "ABC"
    assert entries[0].rule == "tim_analyse" and entries[0].analysis  # only a coin named: TIM writes its own analysis


def test_coin_call_without_levels_gets_tims_own_analysis_stop_and_target() -> None:
    entry = build_diary({"x": [tracked("Short abc")]}, snapshot(FLAT + [(0.93, 0.99), (0.90, 0.95)]))[0]
    # flat coin around 1.00, usual candle 2 %: stop one candle range above the 6 h high, target at twice the risk
    assert entry.rule == "tim_analyse" and entry.verdict == "tradable"
    assert entry.stop == Decimal("1.03") and entry.target == Decimal("0.94")
    assert entry.status == "target_hit" and Decimal("1.5") < entry.net_r < Decimal("2.0")
    assert "Empfehlung: SHORT" in entry.analysis and "ABC" in entry.analysis
    lost = build_diary({"x": [tracked("Short abc")]}, snapshot(FLAT + [(1.00, 1.05)]))[0]
    assert lost.status == "stopped" and lost.net_r < Decimal("-1")


def test_tim_declines_a_coin_call_against_the_last_hours() -> None:
    rising = snapshot([(0.99, 1.01)], history=96)
    bars = list(rising.bars["ABCUSDT"])
    lifted = [replace(bar, open=bar.open * Decimal("1.10"), high=bar.high * Decimal("1.10"), low=bar.low * Decimal("1.10"), close=bar.close * Decimal("1.10"))
              for bar in bars[-12:]]  # the last 3 hours trade 10 % higher: a short would fight the move
    market = replace(rising, bars={"ABCUSDT": bars[:-12] + lifted})
    entry = build_diary({"x": [tracked("Short abc")]}, market)[0]
    assert entry.verdict == "tim_no_trade" and entry.status == "not_entered" and "NICHT HANDELN" in entry.analysis


def test_author_levels_are_never_replaced_by_tims_analysis() -> None:
    entry = build_diary({"x": [tracked("Short abc SL 1.1\nTarget 0.8")]}, snapshot(FLAT))[0]
    assert entry.rule == "autor" and entry.stop == Decimal("1.1") and entry.analysis == ""


def test_analysis_reads_no_candle_after_the_entry() -> None:
    from src.knowledge.goathub_coin_analysis import analyse_coin
    market = snapshot(FLAT + [(0.50, 0.60)] * 4)
    bars = market.bars["ABCUSDT"]
    early = analyse_coin(bars, at=T0, side="SHORT", interval=STEP)
    assert early == analyse_coin([bar for bar in bars if bar.open_time < T0], at=T0, side="SHORT", interval=STEP)
    assert analyse_coin(bars[-10:], at=T0 + STEP * 12, side="SHORT", interval=STEP) is None  # too few candles: no opinion


def test_direction_check_counts_every_call_with_prices_per_author() -> None:
    entries = build_diary({"x": [tracked("Short abc SL 1.1\nTarget 0.8"), tracked("Short abc")]}, snapshot(FLAT[:2] + [(0.93, 0.95)] * 6))
    cards = author_scorecards(entries)
    assert len(cards) == 2 and any("TIM analysiert selbst" in card["author"] for card in cards.values())
    assert all(card["direction"]["1h"] == {"calls": 1, "right": 1} for card in cards.values())
    report = render_diary_report(entries, T0)
    assert "in Richtung des Calls" in report and "## TIM-Analysen" in report
