"""Broncx Discord feed: parsing, storage, external guidance context and the read-only poller.

The fixture posts are the Broncx messages from the TIM owner's screenshot of
2026-09-29 (FUTURES-TRADING-EXPLANATIONS, The Goat Hub).
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.knowledge.broncx_feed import BroncxFeedStore, BroncxPost, parse_guidance
from src.models.market_data import Candle
from src.orderflow_scenario.domain import MarketContext
from src.orderflow_scenario.engines.pipeline import Pipeline, PipelineInputs
from src.orderflow_scenario.external_context import build_external_context
from src.orderflow_scenario.report import report_is_safe
from src.orderflow_scenario.schema_validation import validate_analysis
from src.sources.broncx_discord import DiscordFeedConfig, DiscordFeedError, DiscordFeedPoller, load_bot_secret, message_to_post
from config.secrets import SecretValue

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
PRICE = Decimal("83365")
CHANNEL = "123456789012345678"
OWNER = "223456789012345678"
STRANGER = "323456789012345678"


def post(message_id: str, content: str, posted_at: datetime) -> BroncxPost:
    return BroncxPost(message_id=message_id, posted_at=posted_at, content=content, received_at=NOW)


def screenshot_posts() -> list[BroncxPost]:
    yesterday = datetime(2026, 9, 28, 19, 37, tzinfo=timezone.utc)
    return [
        post("1001", "Unless we flip poc for higher shorts are in on the rejection back to low and maybe leave a runner for break towards 80k", yesterday - timedelta(days=2)),
        post("1002", "Fc btc 15", yesterday),
        post("1003", "If taken take tp1 here tp2 at 82.6", yesterday + timedelta(minutes=1)),
        post("1004", "This might play out again", datetime(2026, 9, 29, 9, 4, tzinfo=timezone.utc)),
    ]


def candle(index: int, close: float, *, low: float | None = None, high: float | None = None) -> Candle:
    open_time = NOW - timedelta(minutes=15 * (60 - index))
    return Candle(
        symbol="BTCUSDT", timeframe="15m", open_time=open_time, close_time=open_time + timedelta(minutes=15),
        open=close, high=high if high is not None else close + 20, low=low if low is not None else close - 20,
        close=close, volume=100.0, trade_count=1000,
    )


# --- parsing -----------------------------------------------------------------------------------

def test_parses_the_real_short_idea_with_invalidation_and_target() -> None:
    guidance = parse_guidance("Unless we flip poc for higher shorts are in on the rejection back to low and maybe leave a runner for break towards 80k", PRICE)
    assert guidance.bias == "SHORT"
    assert guidance.invalidation == ("we flip poc for higher",)
    assert [(level.value, level.role) for level in guidance.levels] == [(Decimal("80000"), "TARGET")]
    assert "POC" in guidance.references
    assert guidance.parse_quality == "STRUCTURED"


def test_symbol_timeframe_and_shorthand_targets() -> None:
    header = parse_guidance("Fc btc 15", PRICE)
    assert (header.symbol, header.timeframe, header.levels) == ("BTC", "15m", ())
    targets = parse_guidance("If taken take tp1 here tp2 at 82.6", PRICE)
    assert [(level.value, level.role, level.scaled_from_shorthand) for level in targets.levels] == [(Decimal("82600.0"), "TARGET", True)]


def test_shorthand_without_reference_price_is_flagged_not_guessed() -> None:
    level = parse_guidance("tp2 at 82.6").levels[0]
    assert level.ambiguous and level.value == Decimal("82.6")


def test_percentages_sizes_and_far_numbers_are_not_levels() -> None:
    guidance = parse_guidance("50% off, 3 contracts, 20 % more, 1000x, 84,381.30 and invalid below 83365.", PRICE)
    assert [level.value for level in guidance.levels] == [Decimal("84381.30"), Decimal("83365")]
    assert guidance.invalidation == ("below 83365",)


def test_reaffirmation_and_unstructured_text() -> None:
    assert parse_guidance("This might play out again").reaffirms_previous
    assert parse_guidance("gm").parse_quality == "UNSTRUCTURED"


def test_reversed_wording_amounts_and_prices_are_not_misread() -> None:
    assert parse_guidance("short squeeze incoming", PRICE).bias == "NONE"
    assert parse_guidance("longs got liquidated, shorts are in", PRICE).bias == "SHORT"
    assert parse_guidance("squeeze the shorts, longs from here", PRICE).bias == "LONG"
    price_not_timeframe = parse_guidance("btc 83 is the level", PRICE)
    assert price_not_timeframe.timeframe is None and [level.value for level in price_not_timeframe.levels] == [Decimal("83000")]
    assert parse_guidance("btc 4h", PRICE).timeframe == "4h"
    assert [level.value for level in parse_guidance("took 1.5k profit, tp 84k", PRICE).levels] == [Decimal("84000")]


# --- storage -----------------------------------------------------------------------------------

def test_store_is_idempotent_and_survives_a_torn_line(tmp_path: Path) -> None:
    store = BroncxFeedStore(tmp_path)
    first, second = screenshot_posts()[:2]
    assert store.append(first) is True
    assert store.append(first) is False
    with store.posts_path.open("a", encoding="utf-8") as stream:
        stream.write('{"message_id": "torn')
    assert store.append(second) is True
    assert [item.message_id for item in store.load()] == ["1001", "1002"]
    # Both were received (forwarded) at NOW: before that TIM could not know them, whatever their post time.
    assert store.posts_until(NOW - timedelta(seconds=1)) == []
    assert [item.message_id for item in store.posts_until(NOW)] == ["1001", "1002"]


def test_state_tracks_last_message_id(tmp_path: Path) -> None:
    store = BroncxFeedStore(tmp_path)
    assert store.last_message_id() is None
    store.set_last_message_id("999")
    assert store.last_message_id() == "999"


# --- external context --------------------------------------------------------------------------

def test_screenshot_thread_renews_the_short_view_and_inherits_symbol() -> None:
    context = build_external_context(screenshot_posts(), observed_at=NOW, symbol="BTCUSDT", candles=[candle(59, 83365)], price_now=PRICE, scenarios=())
    entries = {item["message_id"]: item for item in context["entries"]}
    assert context["influences_decision"] is False
    # Three days old, but "This might play out again" renewed it this morning.
    assert entries["1001"]["status"] == "ACTIVE"
    assert entries["1001"]["renewed_at"] == "2026-09-29T09:04:00+00:00"
    assert entries["1004"]["renews"] == "1001"
    assert entries["1003"]["symbol"] == "BTC" and entries["1003"]["symbol_inherited"] is True
    assert entries["1001"]["alignment"] == "UNTESTED"
    assert entries["1001"]["invalidation_checks"][0]["status"] == "NOT_EVALUATED"


def test_posts_after_observation_time_are_never_used() -> None:
    posts = [post("1", "shorts are in, tp 80k", NOW + timedelta(minutes=5))]
    context = build_external_context(posts, observed_at=NOW, symbol="BTCUSDT", candles=[], price_now=PRICE, scenarios=())
    assert context["posts_excluded_future"] == 1 and context["entries"] == []


def test_posts_received_after_observation_time_are_not_used_in_replays() -> None:
    late = BroncxPost("1", NOW - timedelta(hours=1), "shorts are in", NOW + timedelta(hours=5))
    context = build_external_context([late], observed_at=NOW, symbol="BTCUSDT", candles=[], price_now=PRICE, scenarios=())
    assert context["posts_excluded_future"] == 1 and context["entries"] == []


def test_active_view_is_never_pushed_out_by_later_chatter() -> None:
    posts = [post("10", "shorts are in tp 80k", NOW - timedelta(hours=3))] + [post(str(20 + i), "gm", NOW - timedelta(hours=2) + timedelta(minutes=i)) for i in range(8)]
    posts += [post(str(40 + i), "old idea", NOW - timedelta(days=3, minutes=i)) for i in range(3)]
    context = build_external_context(posts, observed_at=NOW, symbol="BTCUSDT", candles=[], price_now=PRICE, scenarios=(), limit=5)
    ids = [item["message_id"] for item in context["entries"]]
    assert "10" in ids and all(item["status"] == "ACTIVE" for item in context["entries"])


def test_wick_before_the_post_inside_the_same_candle_is_not_a_touch() -> None:
    posted = NOW - timedelta(minutes=8)  # inside the 11:45-12:00 candle, whose low came before the post
    context = build_external_context([post("1", "btc short tp 82.6", posted)], observed_at=NOW, symbol="BTCUSDT", candles=[candle(59, 83365, low=82500)], price_now=PRICE, scenarios=())
    assert context["entries"][0]["level_checks"][0]["status"] == "NO_DATA_SINCE_POST"


def test_old_posts_are_stale_and_other_symbols_are_separated() -> None:
    posts = [post("1", "shorts are in, tp 80k", NOW - timedelta(hours=30)), post("2", "eth longs", NOW - timedelta(hours=1))]
    context = build_external_context(posts, observed_at=NOW, symbol="BTCUSDT", candles=[], price_now=PRICE, scenarios=())
    statuses = {item["message_id"]: item["status"] for item in context["entries"]}
    assert statuses == {"1": "STALE", "2": "OTHER_SYMBOL"}
    assert "level_checks" not in context["entries"][0]


def test_level_and_numeric_invalidation_checks_use_candles_after_the_post() -> None:
    posted = NOW - timedelta(minutes=15 * 10)
    posts = [post("1", "btc long, invalid below 83,000. tp 84k", posted)]
    candles = [candle(i, 83365) for i in range(40, 60)]
    candles[55 - 40] = candle(55, 83100, low=82950, high=84050)  # wick below, close above: not invalidated
    context = build_external_context(posts, observed_at=NOW, symbol="BTCUSDT", candles=candles, price_now=PRICE, scenarios=())
    entry = context["entries"][0]
    assert entry["invalidation_checks"][0] == {"text": "below 83,000", "level": "83000", "status": "NOT_TRIGGERED"}
    checks = {check["level"]: check for check in entry["level_checks"]}
    assert checks["84000"]["status"] == "TOUCHED" and checks["84000"]["role"] == "TARGET"
    assert checks["84000"]["distance_pct"] == "0.76"


# --- pipeline invariance -----------------------------------------------------------------------

def pipeline_inputs(**extra) -> PipelineInputs:
    candles = tuple(candle(i, 84000 - i * 12) for i in range(60))
    return PipelineInputs(
        market_context=MarketContext(symbol="BTCUSDT", venue="BINANCE", market_type="FUTURES", timeframe="15m", timestamp=NOW),
        candles=candles, price_now=Decimal(str(candles[-1].close)), price_timestamp=NOW,
        net_delta=Decimal("120"), aggressive_buy_volume=Decimal("400"), aggressive_sell_volume=Decimal("520"),
        total_volume=Decimal("920"), open_interest_with_price="RISING_WITH_PRICE_DOWN", source_name="TEST",
        observed_at=NOW, **extra,
    )


def test_broncx_guidance_never_changes_tim_decision_scores_or_scenarios() -> None:
    baseline = Pipeline().run(pipeline_inputs()).to_dict()
    guided = Pipeline().run(pipeline_inputs(external_posts=tuple(screenshot_posts()))).to_dict()
    for key in ("decision", "scenarios", "orderflow", "market_state", "data_quality"):
        assert guided[key] == baseline[key], key
    engines = {item["engine"]: item["result"] for item in guided["audit"]["engines"]}
    assert "external_context" not in {item["engine"] for item in baseline["audit"]["engines"]}
    assert engines["external_context"]["influences_decision"] is False
    assert validate_analysis(guided)[0] is True


def test_report_shows_broncx_as_external_guidance() -> None:
    analysis = Pipeline().run(pipeline_inputs(external_posts=tuple(screenshot_posts())))
    text = analysis.report_text
    assert "BRONCX-LEITFADEN (extern, zählt nicht als Bestätigung):" in text
    assert "Invalidierung laut Broncx: we flip poc for higher -> NOT_EVALUATED." in text
    assert "Von Broncx erneut bestätigt." in text
    assert report_is_safe(text)
    assert text.index("BRONCX-LEITFADEN") < text.index("ENTSCHEIDUNG:")


def test_cli_reads_the_feed_directory(tmp_path: Path, capsys, monkeypatch) -> None:
    from src.orderflow_scenario import cli

    store = BroncxFeedStore(tmp_path / "feed")
    for item in screenshot_posts():
        store.append(item)
    source = tmp_path / "input.json"
    source.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "_pipeline_inputs", lambda adapter, data: pipeline_inputs())
    assert cli.main(["--input", str(source), "--broncx-feed", str(store.root)]) == 0
    output = json.loads(capsys.readouterr().out)
    context = next(item["result"] for item in output["audit"]["engines"] if item["engine"] == "external_context")
    assert context["posts_known"] == 4 and context["max_age_hours"] == 24.0
    assert cli.main(["--input", str(source), "--broncx-feed", str(store.root), "--broncx-max-age-hours", "0"]) == 2
    assert cli.main(["--input", str(source), "--broncx-feed", str(tmp_path / "typo")]) == 2


# --- Discord poller ----------------------------------------------------------------------------

def forwarded(message_id: str, author: str, content: str, original_time: str, original_id: str) -> dict:
    return {
        "id": message_id, "timestamp": "2026-09-29T11:00:00+00:00", "content": "", "author": {"id": author},
        "message_reference": {"type": 1, "message_id": original_id, "channel_id": "9", "guild_id": "8"},
        "message_snapshots": [{"message": {"content": content, "timestamp": original_time, "attachments": [{"filename": "chart.png"}]}}],
    }


class FakeDiscord:
    def __init__(self, responses: list[tuple[int, object, dict]]) -> None:
        self.responses = responses
        self.urls: list[str] = []
        self.headers: list[dict[str, str]] = []

    def __call__(self, url: str, headers: dict[str, str]):
        self.urls.append(url)
        self.headers.append(headers)
        return self.responses.pop(0)


def poller(tmp_path: Path, fake: FakeDiscord) -> DiscordFeedPoller:
    return DiscordFeedPoller(SecretValue("bot-secret-value"), DiscordFeedConfig(CHANNEL, frozenset({OWNER})), BroncxFeedStore(tmp_path), http_get=fake, clock=lambda: NOW, sleep=lambda _: None)


def test_forward_keeps_original_text_time_and_id() -> None:
    item = message_to_post(forwarded("500000000000000001", OWNER, "This might play out again", "2026-09-29T09:04:00+00:00", "777"), NOW)
    assert item is not None
    assert (item.message_id, item.content, item.source, item.attachments) == ("777", "This might play out again", "discord_forward", ("chart.png",))
    assert item.posted_at == datetime(2026, 9, 29, 9, 4, tzinfo=timezone.utc)


def test_poller_accepts_only_the_owner_and_advances_the_cursor(tmp_path: Path) -> None:
    messages = [
        forwarded("500000000000000003", OWNER, "shorts are in", "2026-09-29T09:04:00+00:00", "777"),
        {"id": "500000000000000002", "timestamp": "2026-09-29T10:00:00+00:00", "content": "fake broncx: longs!", "author": {"id": STRANGER}},
        {"id": "500000000000000004", "timestamp": "2026-09-29T10:01:00+00:00", "content": "bot noise", "author": {"id": OWNER, "bot": True}},
        forwarded("500000000000000005", OWNER, "shorts are in", "2026-09-29T09:04:00+00:00", "777"),
    ]
    fake = FakeDiscord([(200, messages, {}), (200, [], {})])
    feed = poller(tmp_path, fake)
    result = feed.poll_once()
    assert (result.stored, result.duplicates, result.rejected_author, result.last_message_id) == (1, 1, 2, "500000000000000005")
    assert fake.urls[0].endswith(f"/channels/{CHANNEL}/messages?limit=50")
    assert fake.headers[0]["Authorization"] == "Bot bot-secret-value"
    feed.poll_once()
    assert fake.urls[1].endswith("messages?after=500000000000000005&limit=100")
    assert [item.content for item in BroncxFeedStore(tmp_path).load()] == ["shorts are in"]


def test_malformed_message_is_skipped_and_the_cursor_still_advances(tmp_path: Path) -> None:
    broken = {"id": "500000000000000007", "author": {"id": OWNER}, "content": "no timestamp"}
    fake = FakeDiscord([(200, [broken, {"id": "garbage"}], {})])
    result = poller(tmp_path, fake).poll_once()
    assert (result.stored, result.skipped_empty, result.last_message_id) == (0, 1, "500000000000000007")


def test_poller_retries_rate_limits_and_explains_access_errors(tmp_path: Path) -> None:
    fake = FakeDiscord([(429, {"retry_after": 0.1}, {}), (200, [], {})])
    assert poller(tmp_path, fake).poll_once().fetched == 0
    fake = FakeDiscord([(403, {"message": "Missing Access"}, {})])
    with pytest.raises(DiscordFeedError, match="Read Message History") as error:
        poller(tmp_path, fake).poll_once()
    assert "bot-secret-value" not in str(error.value)


def test_config_and_secret_file_are_validated(tmp_path: Path) -> None:
    with pytest.raises(DiscordFeedError):
        DiscordFeedConfig("not-an-id", frozenset({OWNER}))
    with pytest.raises(DiscordFeedError):
        DiscordFeedConfig(CHANNEL, frozenset())
    secret = tmp_path / "secret"
    secret.write_text("abc\n", encoding="utf-8")
    os.chmod(secret, 0o644)
    with pytest.raises(DiscordFeedError, match="chmod 600"):
        load_bot_secret(secret)
    os.chmod(secret, 0o600)
    assert load_bot_secret(secret).reveal() == "abc"


def test_setup_writes_private_files_and_never_prints_the_secret(tmp_path: Path, capsys) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("broncx_discord_bot", Path(__file__).resolve().parents[1] / "scripts/broncx_discord_bot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    answers = iter([CHANNEL, OWNER])
    config, secret = tmp_path / "cfg.json", tmp_path / "bot"
    code = module.main(["setup", "--config", str(config), "--secret-file", str(secret)], ask=lambda _: next(answers), ask_hidden=lambda _: "very-secret-bot-value")
    assert code == 0
    assert "very-secret-bot-value" not in capsys.readouterr().out
    for path in (config, secret):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert DiscordFeedConfig.load(config).forwarder_ids == frozenset({OWNER})
