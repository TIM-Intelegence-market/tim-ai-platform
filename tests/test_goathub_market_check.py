"""Market check and paper diary for GoatHub calls. Texts and prices are test fixtures, not real data."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from src.knowledge.goathub_channels import PROFILES, TrackedCall, read_call
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

T0 = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
STEP = timedelta(minutes=15)


def series(path: list[tuple[float, float]], *, start: datetime, volume: float = 1_000_000.0) -> list[MarketBar]:
    bars = []
    for index, (low, high) in enumerate(path):
        middle = Decimal(str((low + high) / 2))
        bars.append(MarketBar(start + STEP * index, middle, Decimal(str(high)), Decimal(str(low)), middle, Decimal(str(volume))))
    return bars


def snapshot(path: list[tuple[float, float]], *, symbol: str = "AKEUSDT", status: str = "OPEN", volume: float = 1_000_000.0,
             history: int = 96) -> MarketSnapshot:
    """24 h of flat history before T0, then ``path`` from T0 on."""
    first = path[0]
    before = series([first] * history, start=T0 - STEP * history, volume=volume)
    bars = before + series(path, start=T0, volume=volume)
    return MarketSnapshot(T0 + STEP * len(path), STEP, {symbol: Instrument(symbol, status, 50)}, {symbol: bars})


def tracked(text: str = "Short ake SL 1.1\nTarget 0.8", *, known_after: int = 0, author: str = "goatfather") -> TrackedCall:
    posted = T0
    chat = author == "Broncx"  # Broncx's altcoin posts are read from the crypto chat
    message = GoatHubMessage(message_id=f"m-{abs(hash((text, author, known_after))) % 100000}", channel_id="crypto-chat" if chat else "goatfather-channel",
                             posted_at=posted, content=text, received_at=posted + STEP * known_after, author_name=author,
                             channel_name="CRYPTO-CHAT" if chat else "GOATFATHER-CHANNEL", channel_role="knowledge" if chat else "calls")
    result = read_call(message, PROFILES["chat_altcoins" if chat else "spot_goatfather"], reference_price=Decimal("1.0"))
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
    assert check_market(tracked("Short ake\nTarget 0.8"), snapshot(FLAT)).code == "no_stop"


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
    tight = tracked("Short ake SL 1.002")
    assert COST_PER_SIDE * 2 > Decimal("0.002") * Decimal("0.1")
    assert check_market(tight, snapshot(FLAT)).code == "too_expensive"
    poor = tracked("Short ake SL 1.1\nTarget 0.95")  # reward 5 % against risk 10 %
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
    entries = build_diary({"x": [tracked(), tracked("Short ake\nTarget 0.8", author="Broncx")]}, snapshot(FLAT))
    by_author = {item.author: item for item in entries}
    assert by_author["goatfather"].status == "open" and by_author["goatfather"].net_r is not None
    assert by_author["Broncx"].status == "not_entered" and by_author["Broncx"].verdict == "no_stop"


def test_merge_keeps_first_decision_and_updates_outcome(tmp_path: Path) -> None:
    open_entry = build_diary({"x": [tracked()]}, snapshot(FLAT))[0]
    later = build_diary({"x": [tracked()]}, snapshot(FLAT + [(0.75, 0.85)]))[0]
    merged = merge_diary([open_entry], [later])
    assert len(merged) == 1 and merged[0].status == "target_hit"
    moved = replace(later, entry=Decimal("0.9"))  # a changed entry never overwrites the first one
    assert merge_diary([open_entry], [moved])[0].entry == open_entry.entry
    assert DiaryEntry.from_dict(open_entry.to_dict()) == open_entry


def test_scorecards_and_report_are_per_author_and_say_when_sample_is_small() -> None:
    entries = build_diary({"x": [tracked(), tracked("Short ake\nTarget 0.8", author="Broncx")]}, snapshot(FLAT + [(0.75, 0.85)]))
    cards = author_scorecards(entries)
    assert cards["goatfather"]["target_hit"] == 1 and cards["broncx"]["tradable"] == 0
    report = render_diary_report(entries, T0)
    assert "## goatfather" in report and "## Broncx" in report and "zu wenige Trades" in report and "kein Stop genannt" in report


def test_snapshot_loads_bitunix_rows() -> None:
    payload = {"taken_at": T0.isoformat(), "interval_minutes": 15,
               "instruments": [{"symbol": "AKEUSDT", "symbolStatus": "OPEN", "maxLeverage": 50, "minTradeVolume": "1"}],
               "bars": {"AKEUSDT": [{"time": "1795000000000", "open": "1", "high": "1.1", "low": "0.9", "close": "1.0", "quoteVol": "5"}]}}
    loaded = MarketSnapshot.from_dict(payload)
    assert loaded.instruments["AKEUSDT"].status == "OPEN" and loaded.bars["AKEUSDT"][0].quote_volume == Decimal("5")
