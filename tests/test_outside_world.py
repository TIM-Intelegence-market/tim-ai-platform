"""Headlines (RSS allowlist) and hourly stock bars for move_context (P3); no network in tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.dashboard import outside_world as W

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Bitcoin <b>slides</b> as Nvidia&#9; falls</title><link>https://example.com/a</link><pubDate>Fri, 13 Nov 2026 13:10:00 GMT</pubDate></item>
<item><title>No date</title></item>
<item><title>Bad link</title><link>javascript:alert(1)</link><pubDate>Fri, 13 Nov 2026 13:20:00 +0000</pubDate></item>
</channel></rss>"""
ATOM = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Fed holds</title><link href="https://example.com/f"/>
<updated>2026-11-13T12:00:00Z</updated></entry></feed>"""


def test_rss_and_atom_are_parsed_and_cleaned():
    items = W.parse_feed(RSS, "CoinDesk")
    assert [i["title"] for i in items] == ["Bitcoin slides as Nvidia falls", "Bad link"]
    assert items[0]["link"] == "https://example.com/a" and items[1]["link"] == ""
    assert items[0]["time"] == "2026-11-13T13:10:00+00:00"
    atom = W.parse_feed(ATOM, "X")
    assert atom[0]["title"] == "Fed holds" and atom[0]["link"] == "https://example.com/f"


def test_entities_and_doctype_are_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>'
    with pytest.raises(ValueError):
        W.parse_feed(bomb, "X")


def test_one_broken_feed_is_skipped_and_none_answering_raises():
    def fetch(url: str) -> bytes:
        if "coindesk" in url:
            return RSS
        raise OSError("down")
    assert len(W.fetch_headlines(fetch)) == 2
    with pytest.raises(ValueError):
        W.fetch_headlines(lambda url: (_ for _ in ()).throw(OSError("down")))


def test_log_appends_only_new_items(tmp_path):
    path = tmp_path / "h.jsonl"
    items = W.parse_feed(RSS, "CoinDesk")
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)  # fixed: the feed items are from 13.11.2026 (the window is 10 days)
    assert W.append_log(items, path, now=now) == 2
    assert W.append_log(items, path, now=now) == 0
    assert len(W.read_log(path, now=now)) == 2
    assert W.read_log(path, days=0, now=now) == []


def test_headlines_between_dedupes_titles():
    t = datetime(2026, 11, 13, 13, 0, tzinfo=timezone.utc)
    items = [{"id": "1", "feed": "a", "title": "Same", "time": t.isoformat()}, {"id": "2", "feed": "b", "title": "same", "time": t.isoformat()}]
    assert len(W.headlines_between(items, t - timedelta(hours=1), t)) == 1


def test_yahoo_chart_parse_and_window():
    t0 = int(datetime(2026, 11, 13, 14, 30, tzinfo=timezone.utc).timestamp())
    payload = {"chart": {"result": [{"timestamp": [t0, t0 + 3600, t0 + 7200],
                                     "indicators": {"quote": [{"open": [100.0, None, 99.0], "close": [99.0, 98.0, 97.0]}]}}]}}
    bars = W.parse_chart(payload, "^NDX")
    assert bars == [[t0, 100.0, 99.0], [t0 + 7200, 99.0, 97.0]]
    start = datetime.fromtimestamp(t0, timezone.utc)
    move = W.stock_move(bars, start, start + timedelta(hours=1))
    assert move["change_pct"] == -1.0 and move["bars"] == 1
    assert W.stock_move(bars, start, start + timedelta(minutes=59)) is None


def test_fetch_stocks_keeps_answering_symbols():
    t0 = 1_700_000_000
    good = json.dumps({"chart": {"result": [{"timestamp": [t0, t0 + 3600], "indicators": {"quote": [{"open": [1.0, 1.0], "close": [1.0, 1.1]}]}}]}}).encode()

    def fetch(url: str) -> bytes:
        if "NVDA" in url:
            raise OSError("down")
        return good
    snap = W.fetch_stocks(fetch)
    assert set(snap["series"]) == {"^NDX", "^GSPC"}


def test_cache_refresh_writes_log_and_keeps_last_value(tmp_path):
    calls = {"n": 0}

    def headlines():
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("down")
        return W.parse_feed(RSS, "CoinDesk")
    cache = W.Cache(headlines=headlines, stocks=lambda: {"series": {}}, log_path=tmp_path / "h.jsonl", ttl=0, fail_pause=0)
    cache.refresh()
    cache.refresh()
    assert len(cache.snapshot(background=False)["headlines"] or []) == 2
    assert len((tmp_path / "h.jsonl").read_text().splitlines()) == 2


def test_sources_are_empty_in_tests(monkeypatch):
    monkeypatch.setenv("TIM_RUNTIME_ENV", "test")
    assert W.sources() == {}


def test_utf16_doctype_is_refused_too():
    raw = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE r [<!ENTITY a "x">]><rss><channel/></rss>'.encode("utf-16")
    with pytest.raises(ValueError):
        W.parse_feed(raw, "X")
    late = b"<?xml version='1.0'?><!--" + b"x" * 5000 + b"--><!DOCTYPE rss><rss><channel/></rss>"
    with pytest.raises(ValueError):
        W.parse_feed(late, "X")


def test_broken_log_never_raises(tmp_path):
    path = tmp_path / "h.jsonl"
    good = {"id": "1", "feed": "a", "title": "ok", "time": "2026-11-13T13:00:00+00:00"}
    naive = {"id": "2", "feed": "a", "title": "naive", "time": "2026-11-13T13:00:00"}
    path.write_bytes(json.dumps(good).encode() + b"\n" + json.dumps(naive).encode() + b"\n\xff\xfe broken\n[1, 2]\n")
    rows = W.read_log(path, now=datetime(2026, 11, 14, tzinfo=timezone.utc))
    assert [r["id"] for r in rows] == ["1"]
    assert W.append_log([{**good, "id": "3"}], path) == 1


def test_refresh_after_a_crash_still_runs(tmp_path, monkeypatch):
    calls = {"n": 0}

    def headlines():
        calls["n"] += 1
        return W.parse_feed(RSS, "CoinDesk")
    monkeypatch.setattr(W, "append_log", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    cache = W.Cache(headlines=headlines, stocks=lambda: {"series": {}}, log_path=tmp_path / "h.jsonl", ttl=0, fail_pause=0)
    cache.snapshot(background=False)
    cache.snapshot(background=False)
    assert calls["n"] == 2
