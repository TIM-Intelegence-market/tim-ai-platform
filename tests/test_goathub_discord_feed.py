"""GoatHub community feed: store, call grading, memory export, Discord reader and TIM report.

Message texts here are test fixtures, not real GoatHub posts.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from config.secrets import SecretValue
from src.knowledge.goathub_feed import (
    GoatHubFeedStore,
    GoatHubMessage,
    extract_call,
    good_calls,
    render_summary_markdown,
    write_memory_export,
)
from src.models.market_data import Candle
from src.orderflow_scenario.domain import MarketContext
from src.orderflow_scenario.engines.pipeline import Pipeline, PipelineInputs
from src.orderflow_scenario.report import build_report
from src.orderflow_scenario.schema_validation import validate_analysis
from src.sources.broncx_discord import DiscordFeedError
from src.sources.goathub_discord import GoatHubChannel, GoatHubConfig, GoatHubReader, message_to_goathub

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
CHANNEL = "123456789012345678"
OWNER = "223456789012345678"
MEMBER = "323456789012345678"


def message(message_id: str, content: str, posted_at: datetime = NOW - timedelta(hours=2), **extra) -> GoatHubMessage:
    return GoatHubMessage(message_id=message_id, channel_id=CHANNEL, posted_at=posted_at, content=content,
                          received_at=posted_at, author_id=MEMBER, author_name="trader1", channel_name="calls", **extra)


def candle(index: int, close: float) -> Candle:
    open_time = NOW - timedelta(minutes=15 * (60 - index))
    return Candle(symbol="BTCUSDT", timeframe="15m", open_time=open_time, close_time=open_time + timedelta(minutes=15),
                  open=close, high=close + 20, low=close - 20, close=close, volume=100.0, trade_count=1000)


def pipeline_inputs(**extra) -> PipelineInputs:
    candles = tuple(candle(i, 84000 - i * 12) for i in range(60))
    return PipelineInputs(
        market_context=MarketContext(symbol="BTCUSDT", venue="BINANCE", market_type="FUTURES", timeframe="15m", timestamp=NOW),
        candles=candles, price_now=Decimal(str(candles[-1].close)), price_timestamp=NOW,
        net_delta=Decimal("120"), aggressive_buy_volume=Decimal("400"), aggressive_sell_volume=Decimal("520"),
        total_volume=Decimal("920"), open_interest_with_price="RISING_WITH_PRICE_DOWN", source_name="TEST",
        observed_at=NOW, **extra,
    )


# --- grading -----------------------------------------------------------------------------------

def test_call_grades_follow_completeness() -> None:
    full = extract_call(message("1", "btc short from 83800, tp 82000, invalid above 84500"), Decimal("83300"))
    assert full is not None and full.grade == "A" and full.is_good
    no_stop = extract_call(message("2", "btc long 83000 tp 85k"), Decimal("83300"))
    assert no_stop is not None and no_stop.grade == "B"
    no_symbol = extract_call(message("3", "shorting here, tp 82000"), Decimal("83300"))
    assert no_symbol is not None and no_symbol.grade == "C" and not no_symbol.is_good


def test_conversation_and_closed_positions_are_no_calls() -> None:
    assert extract_call(message("1", "gm everyone")) is None
    assert extract_call(message("2", "closed my short on btc at 82000")) is None
    assert extract_call(message("3", "btc short squeeze incoming")) is None


def test_good_calls_never_use_messages_from_after_the_analysis() -> None:
    late = message("9", "btc short 83800 invalid above 84500", posted_at=NOW + timedelta(minutes=5))
    old = message("8", "btc short 83800 invalid above 84500", posted_at=NOW - timedelta(days=3))
    fresh = message("7", "btc long 83000 invalid below 82500")
    found = good_calls([late, old, fresh], observed_at=NOW, max_age=timedelta(hours=24))
    assert [call.message.message_id for call in found] == ["7"]


# --- storage and export ------------------------------------------------------------------------

def test_store_is_idempotent_per_channel_and_keeps_cursors(tmp_path: Path) -> None:
    store = GoatHubFeedStore(tmp_path)
    assert store.append(message("1", "hello")) is True
    assert GoatHubFeedStore(tmp_path).append(message("1", "hello")) is False
    with store.messages_path.open("a", encoding="utf-8") as stream:
        stream.write('{"message_id": "torn')
    assert [item.message_id for item in GoatHubFeedStore(tmp_path).load()] == ["1"]
    store.set_cursor(CHANNEL, "5")
    store.set_cursor("923456789012345678", "7")
    assert GoatHubFeedStore(tmp_path).cursors() == {CHANNEL: "5", "923456789012345678": "7"}


def test_memory_export_holds_every_message_verbatim(tmp_path: Path) -> None:
    store = GoatHubFeedStore(tmp_path / "feed")
    texts = ["gm", "btc short from 83800, tp 82000, invalid above 84500", "line one\n\nline two"]
    for index, text in enumerate(texts):
        store.append(message(str(index + 1), text, posted_at=NOW - timedelta(hours=3 - index)))
    written = write_memory_export(store, [tmp_path / "a", tmp_path / "b"], generated_at=NOW)
    assert len(written) == 6
    full = (tmp_path / "a" / "GOATHUB_KANAL.md").read_text(encoding="utf-8")
    for text in texts:
        for line in text.splitlines():
            assert line in full
    assert "## #calls" in full and "| trader1 | A |" in full
    calls = json.loads((tmp_path / "b" / "goathub_calls.json").read_text(encoding="utf-8"))
    assert calls["messages"] == 3 and [call["message_id"] for call in calls["calls"]] == ["2"]
    assert len((tmp_path / "a" / "GOATHUB_KURZ.md").read_bytes()) < 4096


def test_summary_stays_under_the_memory_limit() -> None:
    messages = [message(str(index), f"btc short {83000 + index} invalid above 85000 " + "x" * 200) for index in range(200)]
    summary = render_summary_markdown(messages, NOW, "/x/GOATHUB_KANAL.md")
    assert len(summary.encode("utf-8")) <= 3800 and "200 Nachrichten" in summary


# --- Discord reader ----------------------------------------------------------------------------

class FakeDiscord:
    def __init__(self, responses: list[tuple[int, object, dict]]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]):
        self.urls.append(url)
        return self.responses.pop(0)


def discord_message(message_id: int, author: str, content: str, *, bot: bool = False, reactions: int = 0) -> dict:
    return {"id": str(message_id), "timestamp": "2026-10-12T10:00:00+00:00", "content": content,
            "author": {"id": author, "username": "member", "global_name": "Member One", "bot": bot},
            "reactions": [{"count": reactions, "emoji": {"name": "fire"}}] if reactions else []}


def reader(tmp_path: Path, fake: FakeDiscord, mode: str = "direct") -> GoatHubReader:
    config = GoatHubConfig((GoatHubChannel(CHANNEL, "calls"),), mode, frozenset({OWNER}) if mode == "forward" else frozenset())
    return GoatHubReader(SecretValue("test-secret"), config, GoatHubFeedStore(tmp_path), http_get=fake, clock=lambda: NOW, sleep=lambda _: None)


def test_direct_mode_reads_whole_history_page_by_page(tmp_path: Path) -> None:
    first_page = [discord_message(100000000000000000 + index, MEMBER, f"msg {index}") for index in range(100)]
    second_page = [discord_message(200000000000000000, MEMBER, "btc short 83800 invalid above 84500", reactions=4),
                   discord_message(200000000000000001, "999999999999999999", "bot says hi", bot=True)]
    fake = FakeDiscord([(200, first_page, {}), (200, second_page, {})])
    result = reader(tmp_path, fake).sync()[0]
    assert (result.fetched, result.stored, result.rejected_author, result.complete) == (102, 101, 1, True)
    assert "after=0&" in fake.urls[0] and "after=100000000000000099&" in fake.urls[1]
    stored = GoatHubFeedStore(tmp_path).load()
    assert stored[-1].author_name == "Member One" and stored[-1].reactions == 4
    # The next sync starts at the cursor and stores nothing twice.
    fake.responses = [(200, [], {})]
    again = reader(tmp_path, fake).sync()[0]
    assert again.stored == 0 and "after=200000000000000001&" in fake.urls[-1]


def test_forward_mode_only_accepts_the_owner(tmp_path: Path) -> None:
    forward = {"id": "300000000000000001", "timestamp": "2026-10-12T11:00:00+00:00", "content": "", "author": {"id": OWNER},
               "message_reference": {"type": 1, "message_id": "300000000000000000"},
               "message_snapshots": [{"message": {"content": "btc long 83000", "timestamp": "2026-10-12T10:59:00+00:00"}}]}
    fake = FakeDiscord([(200, [forward, discord_message(300000000000000002, MEMBER, "spam")], {})])
    result = reader(tmp_path, fake, mode="forward").sync()[0]
    assert (result.stored, result.rejected_author) == (1, 1)
    stored = GoatHubFeedStore(tmp_path).load()[0]
    assert stored.message_id == "300000000000000000" and stored.author_label.startswith("weitergeleitet")


def test_reader_errors_never_contain_the_secret(tmp_path: Path) -> None:
    fake = FakeDiscord([(401, {}, {})])
    with pytest.raises(DiscordFeedError) as error:
        reader(tmp_path, fake).sync()
    assert "test-secret" not in str(error.value)


def test_config_validation(tmp_path: Path) -> None:
    with pytest.raises(DiscordFeedError):
        GoatHubConfig((GoatHubChannel(CHANNEL),), "forward", frozenset())
    with pytest.raises(DiscordFeedError):
        GoatHubChannel("general")
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"channels": [{"id": CHANNEL, "name": "calls"}], "mode": "direct"}), encoding="utf-8")
    assert GoatHubConfig.load(path).channels[0].name == "calls"


def test_typed_message_without_text_or_files_is_skipped() -> None:
    assert message_to_goathub(discord_message(1, MEMBER, "  "), GoatHubChannel(CHANNEL), NOW) is None


# --- TIM report --------------------------------------------------------------------------------

def test_community_calls_are_shown_but_change_nothing() -> None:
    calls = (message("1", "btc short from 83800, tp 82000, invalid above 84500"), message("2", "eth long 2500 invalid below 2400"))
    baseline = Pipeline().run(pipeline_inputs())
    with_calls = Pipeline().run(pipeline_inputs(community_messages=calls))
    before, after = baseline.to_dict(), with_calls.to_dict()
    for key in ("decision", "orderflow", "market_state", "data_quality", "scenarios"):
        assert after[key] == before[key], key
    engine = next(item["result"] for item in after["audit"]["engines"] if item["engine"] == "community_calls")
    assert engine["influences_scores"] is False and [entry["message_id"] for entry in engine["entries"]] == ["1"]
    assert {level["level"] for level in engine["entries"][0]["levels"]} >= {"83800", "82000"}
    assert validate_analysis(after)[0]
    report = build_report(with_calls)
    assert "GOATHUB-COMMUNITY-CALLS" in report and "trader1 [A] SHORT BTC" in report


def test_cli_reads_the_goathub_directory(tmp_path: Path, capsys, monkeypatch) -> None:
    from src.orderflow_scenario import cli

    store = GoatHubFeedStore(tmp_path / "feed")
    store.append(message("1", "btc short from 83800, invalid above 84500"))
    source = tmp_path / "input.json"
    source.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "_pipeline_inputs", lambda adapter, data: pipeline_inputs())
    assert cli.main(["--input", str(source), "--goathub-feed", str(store.root)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert any(item["engine"] == "community_calls" for item in output["audit"]["engines"])
    assert cli.main(["--input", str(source), "--goathub-feed", str(tmp_path / "typo")]) == 2
    assert cli.main(["--input", str(source), "--goathub-feed", str(store.root), "--goathub-max-age-hours", "0"]) == 2


def test_bot_export_command_writes_files(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("goathub_discord_bot", Path(__file__).resolve().parents[1] / "scripts/goathub_discord_bot.py")
    bot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bot)
    GoatHubFeedStore(tmp_path / "feed").append(message("1", "gm"))
    assert bot.main(["export", "--feed-dir", str(tmp_path / "feed"), "--memory-dir", str(tmp_path / "vault")]) == 0
    assert (tmp_path / "feed" / "memory" / "GOATHUB_KANAL.md").exists() and (tmp_path / "vault" / "GOATHUB_KURZ.md").exists()
