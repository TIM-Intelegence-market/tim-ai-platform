"""Broncx chart images: download, local vision reading, and the stricter chart rules.

The geometry fixture is Broncx's chart of 2026-09-28 18:07 UTC (BTC 1h, MEXC):
a short position tool with entry 83,866.0, stop 84,358.7 and target 82,641.4.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from config.secrets import SecretValue
from src.knowledge.broncx_chart_vision import (
    ChartImageStore,
    OllamaVision,
    VisionError,
    guidance_for_post,
    parse_reading,
)
from src.knowledge.broncx_feed import BroncxFeedStore, BroncxPost
from src.models.market_data import Candle
from src.orderflow_scenario.external_context import active_view, build_external_context
from src.sources.broncx_discord import DiscordFeedConfig, DiscordFeedPoller, image_attachments

NOW = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)
POSTED = datetime(2026, 9, 28, 18, 8, tzinfo=timezone.utc)
PRICE = Decimal("83365")
CHANNEL = "123456789012345678"
OWNER = "223456789012345678"
CDN = "https://cdn.discordapp.com/attachments/1/2/image0.jpg?ex=abc"

SHORT_TOOL = {
    "symbol": "BTCUSDT",
    "timeframe": "1h",
    "position_tool": {"entry": 83866.0, "red_box_outer_edge": 84358.7, "green_box_outer_edge": 82641.4},
    "levels": [{"price": 82238.6, "label": "Prev rh"}],
    "text": "",
}


def reading(payload: dict | str, image: str = "images/1001/0-chart.png"):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return parse_reading(raw, image=image, model="test-vision", read_at=NOW)


def feed_with_chart(tmp_path: Path, content: str, payload: dict, message_id: str = "1001") -> BroncxFeedStore:
    store = BroncxFeedStore(tmp_path)
    store.append(BroncxPost(message_id=message_id, posted_at=POSTED, content=content, received_at=POSTED, attachments=("image0.jpg",)))
    images = ChartImageStore(tmp_path)
    path = images.save(message_id, 0, "image0.jpg", b"\x89PNG fake")
    images.append_reading(reading(payload, image=images.relative(path)))
    return store


def candle(minutes_after_post: int, close: float) -> Candle:
    open_time = POSTED + timedelta(minutes=minutes_after_post)
    return Candle(symbol="BTCUSDT", timeframe="15m", open_time=open_time, close_time=open_time + timedelta(minutes=15),
                  open=close, high=close + 20, low=close - 20, close=close, volume=100.0, trade_count=1000)


# --- reading the model answer ------------------------------------------------------------------

def test_short_position_tool_gives_short_with_entry_target_and_stop() -> None:
    result = reading(SHORT_TOOL)
    assert result.bias == "SHORT"
    assert (result.symbol, result.timeframe) == ("BTC", "1h")
    assert result.levels[:3] == (
        (Decimal("83866.0"), "entry: position tool"),
        (Decimal("82641.4"), "target: position tool"),
        (Decimal("84358.7"), "stop: position tool"),
    )
    assert result.invalidation == (("above", Decimal("84358.7")),)


def test_long_position_tool_is_computed_from_geometry() -> None:
    result = reading({"position_tool": {"entry": 83000, "red_box_outer_edge": 82500, "green_box_outer_edge": 84000}})
    assert result.bias == "LONG"
    assert result.invalidation == (("below", Decimal("82500")),)


def test_inconsistent_position_tool_gives_no_direction() -> None:
    # Both boxes on the same side of the entry: a misread, so no direction and no tool levels.
    result = reading({"position_tool": {"entry": 83000, "red_box_outer_edge": 84000, "green_box_outer_edge": 84500}})
    assert (result.bias, result.levels, result.invalidation) == ("NONE", (), ())


def test_model_opinion_fields_cannot_set_a_direction() -> None:
    assert reading({"bias": "SHORT", "arrow": "down", "levels": []}).bias == "NONE"


def test_malformed_answers_are_dropped_not_repaired() -> None:
    assert reading("I think it goes down").error == "model answer was not a JSON object"
    result = reading({"symbol": "SOLVUSDT", "timeframe": "7m", "levels": [{"price": -5}, {"price": True}, {"price": "abc"}, "x", {"price": "83,250.5"}]})
    assert (result.symbol, result.timeframe) == (None, None)
    assert result.levels == ((Decimal("83250.5"), ""),)


def test_json_wrapped_in_prose_is_still_read() -> None:
    assert reading("Here you go: " + json.dumps(SHORT_TOOL)).bias == "SHORT"


# --- merging into the guidance ------------------------------------------------------------------

def test_chart_agreeing_with_text_adds_estimated_levels(tmp_path: Path) -> None:
    store = feed_with_chart(tmp_path, "shorts are in on the rejection back to low towards 80k", SHORT_TOOL)
    guidance = guidance_for_post(store.load()[0], PRICE)
    assert guidance.bias == "SHORT" and guidance.timeframe == "1h"
    chart = [level for level in guidance.levels if level.source == "chart"]
    assert {(level.value, level.role) for level in chart} == {
        (Decimal("83866.0"), "ENTRY"), (Decimal("82641.4"), "TARGET"), (Decimal("84358.7"), "STOP"), (Decimal("82238.6"), "LEVEL")}
    assert "above 84358.7 (chart)" in guidance.invalidation
    assert guidance.chart_readings == 1
    assert "chart agrees with text bias SHORT" in guidance.notes


def test_chart_direction_against_text_is_ignored(tmp_path: Path) -> None:
    store = feed_with_chart(tmp_path, "longs are in", SHORT_TOOL)
    guidance = guidance_for_post(store.load()[0], PRICE)
    assert guidance.bias == "LONG"
    assert "chart bias SHORT ignored: text says LONG" in guidance.notes


def test_ignored_chart_direction_brings_no_invalidation(tmp_path: Path) -> None:
    # His text is long; a misread short tool must not make a rise above its "stop" kill the long view.
    store = feed_with_chart(tmp_path, "longs are in", SHORT_TOOL)
    assert guidance_for_post(store.load()[0], PRICE).invalidation == ()
    view = active_view(store.load(), observed_at=NOW, symbol="BTCUSDT", candles=[candle(15, 84500)], price_now=Decimal("84500"))
    assert (view.bias, view.reason) == ("LONG", "active")


def test_text_without_direction_takes_the_chart_direction(tmp_path: Path) -> None:
    # Broncx 2026-09-30 09:04 UTC: "Took this @here" plus a long position tool on BTC 15m.
    took_this = {"symbol": "BTCUSDT", "timeframe": "15m",
                 "position_tool": {"entry": 83092.7, "red_box_outer_edge": 82842.9, "green_box_outer_edge": 83991.7}}
    store = feed_with_chart(tmp_path, "Took this @here", took_this)
    guidance = guidance_for_post(store.load()[0], PRICE)
    assert guidance.bias == "LONG"
    assert "bias LONG read from chart (estimated); text states no direction" in guidance.notes
    assert guidance.invalidation == ("below 82842.9 (chart)",)
    view = active_view(store.load(), observed_at=NOW, symbol="BTCUSDT", candles=[candle(15, 83300)], price_now=PRICE)
    assert (view.bias, view.reason) == ("LONG", "active")


LONG_TOOL = {"position_tool": {"entry": 83092.7, "red_box_outer_edge": 82842.9, "green_box_outer_edge": 83991.7}}


def feed_with_text_then_chart(tmp_path: Path, first: str, second: str, payload: dict) -> BroncxFeedStore:
    store = BroncxFeedStore(tmp_path)
    store.append(BroncxPost(message_id="1000", posted_at=POSTED - timedelta(minutes=30), content=first, received_at=POSTED))
    store.append(BroncxPost(message_id="1001", posted_at=POSTED, content=second, received_at=POSTED, attachments=("image0.jpg",)))
    images = ChartImageStore(tmp_path)
    path = images.save("1001", 0, "image0.jpg", b"\x89PNG fake")
    images.append_reading(reading(payload, image=images.relative(path)))
    return store


def test_chart_follow_up_cannot_flip_his_written_direction(tmp_path: Path) -> None:
    store = feed_with_text_then_chart(tmp_path, "shorting here, invalid above 84500, level 83000", "Took this", LONG_TOOL)
    view = active_view(store.load(), observed_at=NOW, symbol="BTCUSDT", candles=[candle(15, 83300)], price_now=PRICE)
    assert (view.bias, view.source_message_id, view.levels) == ("SHORT", "1000", (Decimal("83000"),))


def test_chart_follow_up_cannot_revive_his_triggered_invalidation(tmp_path: Path) -> None:
    store = feed_with_text_then_chart(tmp_path, "shorting here, invalid above 83000", "tp1 here", SHORT_TOOL)
    view = active_view(store.load(), observed_at=NOW, symbol="BTCUSDT", candles=[candle(15, 83300)], price_now=PRICE)
    assert (view.bias, view.reason) == (None, "invalidated")


def test_chart_follow_up_keeps_his_written_levels(tmp_path: Path) -> None:
    store = feed_with_text_then_chart(tmp_path, "shorts at 83,000", "tp1 here", SHORT_TOOL)
    view = active_view(store.load(), observed_at=NOW, symbol="BTCUSDT", candles=[candle(15, 83300)], price_now=PRICE)
    assert (view.bias, view.source_message_id, view.levels) == ("SHORT", "1000", (Decimal("83000"),))
    follow_up = build_external_context(store.load(), observed_at=NOW, symbol="BTCUSDT", candles=[candle(15, 83300)], price_now=PRICE, scenarios=[])["entries"][0]
    assert "chart bias SHORT not used: follow-up to an active view" in follow_up["guidance"]["notes"]


def test_image_only_follow_up_cannot_flip_his_written_direction(tmp_path: Path) -> None:
    store = feed_with_text_then_chart(tmp_path, "shorting here, invalid above 84500", "", LONG_TOOL)
    view = active_view(store.load(), observed_at=NOW, symbol="BTCUSDT", candles=[candle(15, 83300)], price_now=PRICE)
    assert (view.bias, view.source_message_id) == ("SHORT", "1000")


def test_new_position_after_he_closed_the_old_one_counts(tmp_path: Path) -> None:
    store = BroncxFeedStore(tmp_path)
    store.append(BroncxPost(message_id="0999", posted_at=POSTED - timedelta(hours=2), content="shorting here", received_at=POSTED))
    store.append(BroncxPost(message_id="1000", posted_at=POSTED - timedelta(hours=1), content="closed my short", received_at=POSTED))
    store.append(BroncxPost(message_id="1001", posted_at=POSTED, content="Took this", received_at=POSTED, attachments=("image0.jpg",)))
    images = ChartImageStore(tmp_path)
    images.append_reading(reading(LONG_TOOL, image=images.relative(images.save("1001", 0, "image0.jpg", b"png"))))
    view = active_view(store.load(), observed_at=NOW, symbol="BTCUSDT", candles=[candle(15, 83300)], price_now=PRICE)
    assert (view.bias, view.source_message_id) == ("LONG", "1001")


@pytest.mark.parametrize("content", ["Stopped out", "TP1 hit, closed", "Closed this one", "If taken take tp1 here", "moved sl to be", "still valid",
                                     "took profits", "secured, out", "cut it", "trimmed some"])
def test_trade_management_text_does_not_take_the_chart_direction(tmp_path: Path, content: str) -> None:
    store = feed_with_chart(tmp_path, content, SHORT_TOOL)
    assert guidance_for_post(store.load()[0], PRICE).bias == "NONE"


@pytest.mark.parametrize("content", ["closed my short", "no shorts here", "shorts got squeezed"])
def test_text_that_withdraws_a_direction_keeps_none(tmp_path: Path, content: str) -> None:
    store = feed_with_chart(tmp_path, content, SHORT_TOOL)
    guidance = guidance_for_post(store.load()[0], PRICE)
    assert guidance.bias == "NONE"
    assert guidance.invalidation == ()


def test_image_only_post_takes_the_chart_direction(tmp_path: Path) -> None:
    store = feed_with_chart(tmp_path, "", SHORT_TOOL)
    guidance = guidance_for_post(store.load()[0], PRICE)
    assert guidance.bias == "SHORT" and guidance.symbol == "BTC"
    assert guidance.parse_quality == "STRUCTURED"
    assert "bias SHORT read from chart (estimated)" in guidance.notes


def test_chart_levels_far_from_price_or_without_price_are_dropped(tmp_path: Path) -> None:
    store = feed_with_chart(tmp_path, "", {"levels": [{"price": 42000, "label": ""}, {"price": 83100, "label": "POC"}]})
    guidance = guidance_for_post(store.load()[0], PRICE)
    assert [level.value for level in guidance.levels] == [Decimal("83100")]
    assert guidance_for_post(store.load()[0], None).levels == ()


def test_chart_levels_never_become_level_scenarios(tmp_path: Path) -> None:
    store = feed_with_chart(tmp_path, "", SHORT_TOOL)
    view = active_view(store.load(), observed_at=NOW, symbol="BTCUSDT", candles=[candle(15, 83400)], price_now=PRICE)
    assert (view.bias, view.levels, view.reason) == ("SHORT", (), "active")


def test_chart_stop_closed_through_invalidates_the_view(tmp_path: Path) -> None:
    store = feed_with_chart(tmp_path, "", SHORT_TOOL)
    view = active_view(store.load(), observed_at=NOW, symbol="BTCUSDT", candles=[candle(15, 84500)], price_now=Decimal("84500"))
    assert (view.bias, view.reason) == (None, "invalidated")


def test_audit_shows_chart_levels_with_their_source(tmp_path: Path) -> None:
    store = feed_with_chart(tmp_path, "", SHORT_TOOL)
    context = build_external_context(store.load(), observed_at=NOW, symbol="BTCUSDT", candles=[candle(15, 83400)], price_now=PRICE, scenarios=[])
    entry = context["entries"][0]
    assert entry["guidance"]["chart_readings"] == 1
    assert {level["source"] for level in entry["guidance"]["levels"]} == {"chart"}
    assert {check["level"] for check in entry["level_checks"]} >= {"82641.4", "84358.7"}
    assert {check["source"] for check in entry["level_checks"]} == {"chart"}


def test_report_marks_chart_levels_as_read_from_an_image(tmp_path: Path) -> None:
    from src.orderflow_scenario.report import _external_section

    store = feed_with_chart(tmp_path, "shorts are in 83,000", SHORT_TOOL)
    context = build_external_context(store.load(), observed_at=NOW, symbol="BTCUSDT", candles=[candle(15, 83400)], price_now=PRICE, scenarios=[])
    text = "\n".join(_external_section(context))
    assert "83000 LEVEL NOT_REACHED" in text or "83000 LEVEL TOUCHED" in text
    assert "82641.4 TARGET aus Bild, geschätzt" in text


# --- storage ---------------------------------------------------------------------------------------

def test_readings_are_attached_on_load_but_never_written_to_posts(tmp_path: Path) -> None:
    store = feed_with_chart(tmp_path, "", SHORT_TOOL)
    assert len(store.load()[0].chart_readings) == 1
    assert "chart_readings" not in json.loads(store.posts_path.read_text(encoding="utf-8").splitlines()[0])


def test_failed_readings_are_not_used(tmp_path: Path) -> None:
    store = feed_with_chart(tmp_path, "", "not json")
    assert store.load()[0].chart_readings == ()


class FakeVision:
    model = "fake"

    def __init__(self, answer: str | Exception) -> None:
        self.answer, self.calls = answer, 0

    def read(self, image: Path) -> str:
        self.calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_read_pending_reads_each_image_once(tmp_path: Path) -> None:
    store = BroncxFeedStore(tmp_path)
    store.append(BroncxPost(message_id="1001", posted_at=POSTED, content="", received_at=POSTED, attachments=("a.png",)))
    images = ChartImageStore(tmp_path)
    images.save("1001", 0, "a.png", b"png")
    vision = FakeVision(json.dumps(SHORT_TOOL))
    assert [item.bias for item in images.read_pending(store.load(), vision)] == ["SHORT"]
    assert images.read_pending(store.load(), vision) == []
    assert vision.calls == 1


def test_model_down_keeps_the_image_for_the_next_cycle(tmp_path: Path) -> None:
    store = BroncxFeedStore(tmp_path)
    store.append(BroncxPost(message_id="1001", posted_at=POSTED, content="", received_at=POSTED, attachments=("a.png",)))
    images = ChartImageStore(tmp_path)
    images.save("1001", 0, "a.png", b"png")
    with pytest.raises(VisionError):
        images.read_pending(store.load(), FakeVision(VisionError("down")))
    assert len(images.unread(store.load())) == 1


def test_image_file_names_cannot_escape_the_feed_directory(tmp_path: Path) -> None:
    path = ChartImageStore(tmp_path).save("../../etc", 0, "../../passwd.png", b"x")
    assert path.resolve().is_relative_to(tmp_path.resolve())


def test_ollama_request_is_local_json_with_the_image() -> None:
    sent = {}

    def post(url: str, payload: dict, timeout: float) -> dict:
        sent.update(url=url, payload=payload)
        return {"response": "{}"}

    vision = OllamaVision(model="qwen3.5:9b", url="http://127.0.0.1:11434", post=post)
    image = Path(__file__)
    assert vision.read(image) == "{}"
    assert sent["url"] == "http://127.0.0.1:11434/api/generate"
    assert sent["payload"]["format"] == "json" and sent["payload"]["options"] == {"temperature": 0}
    assert len(sent["payload"]["images"]) == 1


def test_empty_ollama_answer_is_an_error() -> None:
    with pytest.raises(VisionError):
        OllamaVision(post=lambda url, payload, timeout: {"error": "model not found"}).read(Path(__file__))


# --- download by the poller ------------------------------------------------------------------------

def forward(message_id: str, attachments: list[dict]) -> dict:
    return {
        "id": message_id, "timestamp": "2026-09-28T19:40:00+00:00", "content": "", "author": {"id": OWNER},
        "message_reference": {"type": 1, "message_id": "9" + message_id[1:]},
        "message_snapshots": [{"message": {"content": "", "timestamp": "2026-09-28T19:37:54+00:00", "attachments": attachments}}],
    }


def poller(tmp_path: Path, messages: list[dict], downloads: dict[str, bytes | Exception]):
    requests: list[tuple[str, dict]] = []

    def http_get(url: str, headers: dict) -> tuple[int, object, dict]:
        return 200, messages, {}

    def http_get_bytes(url: str, headers: dict, limit: int) -> bytes:
        requests.append((url, headers))
        result = downloads[url]
        if isinstance(result, Exception):
            raise result
        return result

    instance = DiscordFeedPoller(SecretValue("bot-secret-value"), DiscordFeedConfig(CHANNEL, frozenset({OWNER})), BroncxFeedStore(tmp_path),
                                 http_get=http_get, http_get_bytes=http_get_bytes, clock=lambda: NOW)
    return instance, requests


def test_poll_downloads_forwarded_chart_without_the_bot_secret(tmp_path: Path) -> None:
    message = forward("1554215667501105000", [{"filename": "chart.png", "url": CDN, "content_type": "image/png", "size": 1000}])
    instance, requests = poller(tmp_path, [message], {CDN: b"png-bytes"})
    result = instance.poll_once()
    assert (result.stored, result.images_saved, result.image_errors) == (1, 1, 0)
    assert [url for url, _ in requests] == [CDN]
    assert "Authorization" not in requests[0][1]
    saved = ChartImageStore(tmp_path).images_for("9554215667501105000")
    assert [path.read_bytes() for path in saved] == [b"png-bytes"]


def test_only_discord_cdn_images_within_the_size_limit_are_downloaded() -> None:
    message = forward("1554215667501105000", [
        {"filename": "a.png", "url": "https://evil.example/a.png", "content_type": "image/png"},
        {"filename": "b.png", "url": "http://cdn.discordapp.com/b.png", "content_type": "image/png"},
        {"filename": "c.pdf", "url": "https://cdn.discordapp.com/c.pdf", "content_type": "application/pdf"},
        {"filename": "d.png", "url": "https://cdn.discordapp.com/d.png", "size": 50 * 1024 * 1024},
        {"filename": "e.webp", "url": "https://media.discordapp.net/e.webp"},
    ])
    assert image_attachments(message)[1] == [("e.webp", "https://media.discordapp.net/e.webp")]


def test_failed_download_keeps_the_post(tmp_path: Path) -> None:
    message = forward("1554215667501105000", [{"filename": "chart.png", "url": CDN, "content_type": "image/png"}])
    instance, _ = poller(tmp_path, [message], {CDN: OSError("timeout")})
    result = instance.poll_once()
    assert (result.stored, result.images_saved, result.image_errors) == (1, 0, 1)


def test_backfill_fetches_images_of_already_stored_posts_once(tmp_path: Path) -> None:
    message = forward("1554215667501105000", [{"filename": "chart.png", "url": CDN, "content_type": "image/png"}])
    store = BroncxFeedStore(tmp_path)
    store.append(BroncxPost(message_id="9554215667501105000", posted_at=POSTED, content="", received_at=POSTED, attachments=("chart.png",)))
    instance, requests = poller(tmp_path, [message], {CDN: b"png"})
    assert instance.backfill_images() == (1, 0)
    assert instance.backfill_images() == (0, 0)
    assert len(requests) == 1


def test_a_failed_image_is_fetched_again_without_downloading_the_saved_one(tmp_path: Path) -> None:
    second = CDN.replace("image0", "image1")
    message = forward("1554215667501105000", [
        {"filename": "a.png", "url": CDN, "content_type": "image/png"},
        {"filename": "b.png", "url": second, "content_type": "image/png"},
    ])
    store = BroncxFeedStore(tmp_path)
    store.append(BroncxPost(message_id="9554215667501105000", posted_at=POSTED, content="", received_at=POSTED, attachments=("a.png", "b.png")))
    downloads: dict[str, bytes | Exception] = {CDN: b"a", second: OSError("timeout")}
    instance, requests = poller(tmp_path, [message], downloads)
    assert instance.backfill_images() == (1, 1)
    downloads[second] = b"b"
    assert instance.backfill_images() == (1, 0)
    assert [url for url, _ in requests] == [CDN, second, second]
    assert [path.read_bytes() for path in ChartImageStore(tmp_path).images_for("9554215667501105000")] == [b"a", b"b"]


@pytest.mark.parametrize(("raw", "expected"), [("1D", "1d"), ("D", "1d"), ("1d", "1d"), ("4h", "4h"), ("15m", "15m"), ("m", None), ("2D", None), ("1M", None)])
def test_chart_timeframes_include_the_daily_chart(raw: str, expected: str | None) -> None:
    assert reading({"timeframe": raw}).timeframe == expected
