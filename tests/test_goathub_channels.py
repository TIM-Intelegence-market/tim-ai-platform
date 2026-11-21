"""Three GoatHub channel readers, outcome check, scorecard and board preview.

Message texts here are test fixtures, not real GoatHub posts.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from scripts import goathub_channels as cli
from src.knowledge.goathub_channels import (
    BOARD_LIMIT_CHARS,
    PROFILES,
    PriceBar,
    chart_reading,
    check_outcome,
    evaluate,
    load_bars_csv,
    parse_transcript,
    read_call,
    read_calls,
    render_board,
    scorecard,
)
from src.knowledge.goathub_feed import GoatHubMessage

T0 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)

TRANSCRIPT = """# #📈 | FUTURES-TRADING-BRONCX (Kategorie TRADING LOUNGE)

Zeiten: Berlin (CEST)

---

### 01.10.26 12:00 | Broncx [GOAT]
looking for a long here towards 105k (Bearbeitet)
Anhang: Bild, TradingView-Chart BTC/Tether Perpetual Futures 15m, Long-Positionsbox; Kurs ca. 100.000,0, Ziel ca. 104.000,5, Stop ca. 99.000,0 [?]
Reaktionen: 👍 2, 🐐 3

---
### 01.10.26 12:00 (Folgenachricht) | Broncx
(kein Text)
Anhang: GIF, jubelnde Spieler

---
### 01.10.26 12:05 | Tree Capital [APP]
Anhang: Bild, Chart-Karte BTCUSDT 1h
Antwort auf: @Broncx, "Fc btc 1h"

---
### 01.10.26 13:00 | Broncx [GOAT]
Hinweis: nur Test
(kein Text)
"""


def msg(content: str, *, channel: str = "futures-trading-broncx", author: str = "Broncx", minutes: int = 0, attachments: tuple[str, ...] = ()) -> GoatHubMessage:
    posted = T0 + timedelta(minutes=minutes)
    return GoatHubMessage(message_id=f"m{minutes}-{abs(hash(content)) % 10_000}", channel_id=channel, posted_at=posted, content=content,
                          received_at=posted, author_name=author, channel_name=channel.upper(), attachments=attachments)


def bars(path: list[tuple[float, float]], start: datetime = T0, step: timedelta = timedelta(hours=1)) -> list[PriceBar]:
    """Bars from (low, high) pairs; open is the middle of the first bar."""
    result = []
    for index, (low, high) in enumerate(path):
        middle = Decimal(str((low + high) / 2))
        result.append(PriceBar(start + step * index, middle, Decimal(str(high)), Decimal(str(low)), middle))
    return result


def test_transcript_parsing_berlin_time_reactions_and_skips(tmp_path: Path) -> None:
    path = tmp_path / "11-futures-t-1.md"
    path.write_text(TRANSCRIPT, encoding="utf-8")
    messages = parse_transcript(path, received_at=T0)
    # The GIF-only follow-up keeps its attachment, the APP chart card stays (filtered later by author),
    # the block with only a note and "(kein Text)" is dropped.
    assert [m.author_name for m in messages] == ["Broncx", "Broncx", "Tree Capital"]
    first = messages[0]
    assert first.posted_at == datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)  # 12:00 CEST
    assert first.channel_id == "futures-trading-broncx"
    assert first.reactions == 5
    assert first.content == "looking for a long here towards 105k"  # transcriber note removed
    assert "Long-Positionsbox" in first.attachments[0]
    assert parse_transcript(path, received_at=T0)[0].message_id == first.message_id  # stable ids


def test_winter_time_is_one_hour() -> None:
    from src.knowledge.goathub_channels import BERLIN
    assert datetime(2026, 11, 2, 12, 0, tzinfo=BERLIN).utcoffset() == timedelta(hours=1)


def test_chart_reading_german_numbers() -> None:
    bias, levels = chart_reading(["Short-Positionsbox; Kurs ca. 78.607,9, Stop ca. 78.843,7, Ziele ca. 77.777,0 / 77.737,5 [?]"])
    assert bias == "SHORT"
    assert {(level.role, level.value, level.source) for level in levels} == {
        ("STOP", Decimal("78843.7"), "chart"), ("TARGET", Decimal("77777.0"), "chart")}
    assert chart_reading(["Bild, Chart ohne Box"]) == (None, ())


def test_futures_reader_btc_default_chart_only_post_and_bots_skipped() -> None:
    profile = PROFILES["futures_broncx"]
    image_only = msg("(Bild)", attachments=("Long-Positionsbox; Kurs ca. 100.000,0, Ziel ca. 104.000,0, Stop ca. 99.000,0",))
    tracked = read_call(image_only, profile)
    assert tracked is not None and tracked.bias == "LONG" and tracked.symbol == "BTC" and tracked.call.grade == "A"
    assert read_call(msg("long here", author="Tree Capital"), profile) is None
    assert read_call(msg("tp hit, letting 25% run"), profile) is None  # report on an earlier trade
    eth = read_call(msg("short eth below 3800"), profile)
    assert eth is not None and eth.symbol == "ETH"
    # A chart box against the text direction keeps the text and does not mix in the chart levels.
    conflict = read_call(msg("short from here", attachments=("Long-Positionsbox; Stop ca. 99.000,0",)), profile)
    assert conflict is not None and conflict.bias == "SHORT" and not conflict.call.guidance.levels


def test_spot_reader_extras_and_cashtag() -> None:
    profile = PROFILES["spot_goatfather"]
    tracked = read_call(msg("Risky trade: long ABC from here with SL 0.5, 5% of account, add every 5% dip", channel="goatfather-channel", author="goatfather"), profile)
    assert tracked is not None and tracked.symbol == "ABC"
    assert tracked.extras == {"bucket": "risky", "account_pct": 5.0, "dca_step_pct": 5.0}
    tagged = read_call(msg("Short set up: $XYZ entry 155 SL 175 target 70", channel="goatfather-channel", author="goatfather"), profile)
    assert tagged is not None and tagged.symbol == "XYZ"


def test_gold_reader_symbol() -> None:
    profile = PROFILES["gold_eydu"]
    gold = read_call(msg("Looking for longs to 4400", channel="xau-xag", author="EyDu"), profile)
    assert gold is not None and gold.symbol == "XAU"
    silver = read_call(msg("silver short below 48", channel="xau-xag", author="EyDu"), profile)
    assert silver is not None and silver.symbol == "XAG"


def test_read_calls_routes_by_channel() -> None:
    calls = read_calls([
        msg("long towards 105k", channel="#📈 | FUTURES-TRADING-BRONCX"),
        msg("short gold below 4100", channel="xau-xag", author="EyDu", minutes=1),
        msg("long xyz", channel="general", author="someone", minutes=2),
    ])
    assert [len(calls[key]) for key in ("futures_broncx", "spot_goatfather", "gold_eydu")] == [1, 0, 1]


def futures_call(text: str = "long here", minutes: int = 0, **extra):
    tracked = read_call(msg(text, minutes=minutes, **extra), PROFILES["futures_broncx"])
    assert tracked is not None
    return tracked


BOX = ("Long-Positionsbox; Ziel ca. 104.000,0, Stop ca. 99.000,0",)


def test_outcome_target_stop_same_bar_and_no_lookahead() -> None:
    tracked = futures_call(attachments=BOX)
    # A bar before the post must not count, even though it touches the stop.
    before = bars([(98000, 101000)], start=T0 - timedelta(hours=1))
    hit = check_outcome(tracked, before + bars([(99500, 100500), (100000, 104500)]), observed_at=T0 + timedelta(hours=5))
    assert hit.status == "target_hit" and hit.entry == Decimal("100000") and hit.resolved_at == T0 + timedelta(hours=1)
    stopped = check_outcome(tracked, bars([(99500, 100500), (98900, 100200)]), observed_at=T0 + timedelta(hours=5))
    assert stopped.status == "stopped"
    both = check_outcome(tracked, bars([(99500, 100500), (98000, 105000)]), observed_at=T0 + timedelta(hours=5))
    assert both.status == "stopped" and "same bar" in both.note


def test_outcome_open_expired_and_wrong_side_levels() -> None:
    tracked = futures_call(attachments=BOX)
    flat = bars([(99500, 100500)] * 5)
    assert check_outcome(tracked, flat, observed_at=T0 + timedelta(hours=5)).status == "open"
    long_flat = bars([(99500, 100500)] * 80)
    expired = check_outcome(tracked, long_flat, observed_at=T0 + timedelta(hours=80))
    assert expired.status == "expired" and expired.resolved_at == T0 + PROFILES["futures_broncx"].horizon
    # Entry already above the "target": the level is on the wrong side and is ignored, stop remains.
    above = bars([(104500, 105500), (104000, 105000)])
    result = check_outcome(tracked, above, observed_at=T0 + timedelta(hours=2))
    assert result.target is None and result.stop == Decimal("99000.0") and result.status == "open"


def test_outcome_shorthand_scaled_with_entry_and_not_checkable() -> None:
    tracked = futures_call("long towards 104k, sl 99k")
    result = check_outcome(tracked, bars([(99500, 100500), (100000, 104200)]), observed_at=T0 + timedelta(hours=3))
    assert result.status == "target_hit" and result.target == Decimal("104000")
    vague = futures_call("bullish here")
    assert check_outcome(vague, bars([(99500, 100500)]), observed_at=T0 + timedelta(hours=1)).status == "not_checkable"
    assert check_outcome(tracked, [], observed_at=T0 + timedelta(hours=1)).status == "no_price_data"


def test_evaluate_scorecard_and_missing_feed() -> None:
    calls = read_calls([
        msg("(Bild)", attachments=BOX),
        msg("(Bild)", minutes=120, attachments=("Long-Positionsbox; Ziel ca. 101.000,0, Stop ca. 99.500,0",)),
        msg("short gold towards 4000, sl 4200", channel="xau-xag", author="EyDu", minutes=5),
    ])
    btc = bars([(99800, 100200), (99900, 100300), (99600, 100400), (99100, 100100), (99800, 104500)])
    outcomes = evaluate(calls, {"BTC": btc}, observed_at=T0 + timedelta(hours=5))
    assert [item.status for item in outcomes["futures_broncx"]] == ["target_hit", "stopped"]
    assert outcomes["gold_eydu"][0].status == "no_price_data"
    card = scorecard(outcomes["futures_broncx"])
    assert card["target_hit"] == 1 and card["stopped"] == 1 and card["hit_rate"] == 0.5 and card["hit_rate_basis"] == 2
    assert scorecard(outcomes["gold_eydu"])["hit_rate"] is None


def test_hit_rate_ignores_calls_without_target_and_stop() -> None:
    stop_only = futures_call(attachments=("Long-Positionsbox; Stop ca. 99.000,0",))
    full = futures_call(minutes=1, attachments=BOX)
    path = bars([(99500, 100500), (98500, 100000)])
    outcomes = [check_outcome(stop_only, path, observed_at=T0 + timedelta(hours=2)), check_outcome(full, path, observed_at=T0 + timedelta(hours=2))]
    assert [item.status for item in outcomes] == ["stopped", "stopped"]
    card = scorecard(outcomes)
    assert card["stopped"] == 2 and card["with_target_and_stop"] == 1 and card["hit_rate_basis"] == 1 and card["hit_rate"] == 0.0


def test_board_fits_one_discord_message_and_has_no_mentions() -> None:
    many = [msg("(Bild)", minutes=i, attachments=BOX) for i in range(200)]
    outcomes = evaluate(read_calls(many), {"BTC": bars([(99500, 100500)] * 300, step=timedelta(minutes=1))}, observed_at=T0 + timedelta(hours=4))
    text = render_board(outcomes, generated_at=T0 + timedelta(hours=4))
    assert len(text) <= BOARD_LIMIT_CHARS
    assert "not advice" in text and "Broncx futures" in text and "EyDu gold" in text
    assert "@everyone" not in text and "@here" not in text


def test_load_bars_csv(tmp_path: Path) -> None:
    path = tmp_path / "btc.csv"
    path.write_text("open_time,open,high,low,close\n1759312800000,1,2,0.5,1.5\n2025-10-01T09:00:00+00:00,1,2,0.5,1.5\n", encoding="utf-8")
    loaded = load_bars_csv(path)
    assert [bar.open_time for bar in loaded] == [datetime(2025, 10, 1, 9, 0, tzinfo=timezone.utc), datetime(2025, 10, 1, 10, 0, tzinfo=timezone.utc)]


def test_cli_read_and_evaluate(tmp_path: Path, capsys) -> None:
    transcript = tmp_path / "t.md"
    transcript.write_text(TRANSCRIPT, encoding="utf-8")
    csv_path = tmp_path / "btc.csv"
    csv_path.write_text("open_time,open,high,low,close\n2026-10-01T10:00:00+00:00,100000,100500,99500,100000\n"
                        "2026-10-01T11:00:00+00:00,100000,104500,99800,104000\n", encoding="utf-8")
    assert cli.main(["read", "--transcript", str(transcript), "--out", str(tmp_path / "calls.json")]) == 0
    assert "Broncx futures: 1 calls (A 1" in capsys.readouterr().out
    board = tmp_path / "board.txt"
    out = tmp_path / "eval.json"
    assert cli.main(["evaluate", "--transcript", str(transcript), "--bars", f"BTC={csv_path}", "--observed-at", "2026-10-01T13:00:00+00:00",
                     "--out", str(out), "--board", str(board)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["scorecards"]["futures_broncx"]["target_hit"] == 1
    assert board.read_text(encoding="utf-8").startswith("**TIM × GoatHub board**")


# --- reader repairs of 21.11.2026: words taken for coins, status posts, jokes, follow-up levels -----------------

def test_chart_words_are_no_coins() -> None:
    gold = PROFILES["gold_eydu"]
    futures = PROFILES["futures_broncx"]
    for text in ("Broke lower, backtesting rn!u can try short under 3865", "Took short sl @3755", "ETF flows are high tho and banks keep buying physicall"):
        tracked = read_call(msg(text, channel="xau-xag", author="EyDu"), gold)
        assert tracked is None or tracked.symbol == "XAU"
    for text in ("Probably going for sell imbal at 62.1", "(Antwort an Broncx) this is first level for swing long reaction for me",
                 "Well longing will have to see the right bottom"):
        tracked = read_call(msg(text), futures)
        assert tracked is None or tracked.symbol == "BTC"


def test_status_posts_and_jokes_are_no_calls() -> None:
    spot = PROFILES["spot_goatfather"]
    for text in ("I closed 75% of ake short and moved SL to breakeven @everyone", "Taking profits on swing shorts here!",
                 "Pull SL little lower to 0.48", "Yoo imagine now we long ake and it runs back to 0.001", "61k we short??"):
        assert read_call(msg(text, channel="goatfather-channel", author="goatfather"), spot) is None


def test_round_number_and_clock_time_are_no_levels() -> None:
    spot = PROFILES["spot_goatfather"]
    tracked = read_call(msg("Short ake round 2\n\n2% capital max SL 0.012", channel="goatfather-channel", author="goatfather"), spot)
    assert tracked is not None and tracked.symbol == "AKE"
    assert [(level.role, level.value) for level in tracked.call.guidance.levels] == [("STOP", Decimal("0.012"))]
    clock = read_call(msg("Respect 9:30 level bearish for continuation lower again"), PROFILES["futures_broncx"])
    assert clock is None or not clock.call.guidance.levels


def test_target_follow_up_joins_the_call_before_it() -> None:
    first = msg("Short strc", channel="goatfather-channel", author="goatfather", minutes=0)
    second = msg("Target 77$", channel="goatfather-channel", author="goatfather", minutes=0)
    later = msg("Target 99$", channel="goatfather-channel", author="goatfather", minutes=10)
    for order in ([first, second, later], [second, later, first]):  # same-minute posts may arrive in any order
        calls = read_calls(order)["spot_goatfather"]
        assert len(calls) == 1 and calls[0].symbol == "STRC"
        assert any(level.role == "TARGET" for level in calls[0].call.guidance.levels)
        assert "99" not in calls[0].call.message.content


def test_crypto_chat_reads_only_the_named_authors_and_only_full_calls() -> None:
    from dataclasses import replace
    from src.knowledge.goathub_feed import ROLE_KNOWLEDGE
    chat = PROFILES["chat_altcoins"]
    def chat_msg(text: str, author: str = "goatfather") -> GoatHubMessage:
        return replace(msg(text, channel="crypto-chat", author=author), channel_role=ROLE_KNOWLEDGE)
    call = read_call(chat_msg("Short ake round 2\n\n2% capital max SL 0.012"), chat)
    assert call is not None and call.symbol == "AKE" and call.call.grade == "B"
    assert read_call(chat_msg("Short ake round 2\n\n2% capital max SL 0.012", author="jenser111"), chat) is None
    assert read_call(chat_msg("Fc ake 15min"), chat) is None
    assert read_call(chat_msg("Dropped small short tp listing price", author="Broncx"), chat) is None  # no coin, no level
    assert read_calls([chat_msg("Short ake SL 0.012")])["chat_altcoins"]  # still a knowledge channel for everyone else


def test_far_stop_on_a_cheap_coin_is_kept_when_a_price_is_known() -> None:
    from src.knowledge.goathub_feed import extract_call
    call = extract_call(msg("Short ake\nSL 0.012", channel="goatfather-channel", author="goatfather"), reference_price=Decimal("0.0082"))
    assert call is not None and [(l.role, l.value, l.ambiguous) for l in call.guidance.levels] == [("STOP", Decimal("0.012"), False)]
    btc = extract_call(msg("Short btc\nSL 0.5"), reference_price=Decimal("60000"))
    assert btc is None or not btc.guidance.levels  # a size, not a BTC price


# --- chart images: box labels without names, charts in every channel --------------------------------------------

def test_three_unnamed_box_labels_get_roles_from_the_box_shape() -> None:
    short = chart_reading(["Bild: TradingView BTC/Tether 15m, Short-Positionsbox; Preislabels 65,112.5 / 64,965.8 / 63,484.9 [unsicher: kleine Labels]"])
    assert short[0] == "SHORT"
    assert {(l.role, l.value) for l in short[1]} == {("STOP", Decimal("65112.5")), ("ENTRY", Decimal("64965.8")), ("TARGET", Decimal("63484.9"))}
    long = chart_reading(["Long-Positionsbox; Preislabels 0.30 / 0.25 / 0.22"])
    assert {(l.role, l.value) for l in long[1]} == {("TARGET", Decimal("0.30")), ("ENTRY", Decimal("0.25")), ("STOP", Decimal("0.22"))}
    assert chart_reading(["Short-Positionsbox; Preislabels 65,112.5 / 63,484.9"])[1] == ()  # two labels name no role


def test_chart_box_counts_in_the_gold_and_chat_channels_too() -> None:
    from dataclasses import replace
    from src.knowledge.goathub_feed import ROLE_KNOWLEDGE
    gold = read_call(msg("(Bild)", channel="xau-xag", author="EyDu",
                         attachments=("Gold-Chart, Long-Positionsbox; Kurs ca. 3.800,0, Ziel ca. 3.900,0, Stop ca. 3.760,0 [?]",)), PROFILES["gold_eydu"])
    assert gold is not None and gold.symbol == "XAU" and gold.call.grade == "A"
    chat_message = replace(msg("(Bild)", channel="crypto-chat", author="goatfather",
                               attachments=("Bild: AKE/USDT-Chart, Short-Positionsbox; Stop ca. 0,0100, Ziel ca. 0,0050",)), channel_role=ROLE_KNOWLEDGE)
    chat = read_call(chat_message, PROFILES["chat_altcoins"])
    assert chat is not None and chat.symbol == "AKE" and chat.bias == "SHORT" and chat.call.grade == "A"
