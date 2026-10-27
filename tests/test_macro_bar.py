"""Macro bar on the prep page: gold, dollar, Nasdaq, 10y yield, BTC dominance (display only)."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone

from src.dashboard import macro_bar
from src.dashboard.helpers import _safe
from src.dashboard.macro_bar import (MacroCache, build_macro_bar, correlation, describe, load_dominance, macro_rows_html,
                                     parse_dominance, parse_fred, parse_klines, record_dominance, relation_text)
from src.dashboard.pages.prep import _prep_page

NOW = datetime(2026, 10, 27, 16, 0, tzinfo=timezone.utc)
KEY = lambda: "k" * 32  # noqa: E731 - test key, never a real one
DAYS = [NOW.date() - timedelta(days=60 - i) for i in range(60)]


def _btc(i: int) -> float:
    return 100_000 * (1 + 0.03 * math.sin(i / 3) + 0.001 * i)


def _klines(symbol: str) -> bytes:
    rows = []
    for i, day in enumerate(DAYS + [NOW.date()]):
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        close = _btc(i) if symbol == "BTCUSDT" else 4000 * (1 + 0.01 * math.sin(i / 3 + 0.2))
        rows.append([int(start.timestamp() * 1000), "0", "0", "0", str(close), "0", int((start + timedelta(days=1)).timestamp() * 1000) - 1])
    return json.dumps(rows).encode()


def _fred(series: str) -> bytes:
    rows = []
    for i, day in enumerate(DAYS):
        if day.weekday() >= 5:
            continue
        value = {"DGS10": 4.5 + 0.01 * i, "NASDAQCOM": 25_000 * (1 + 0.02 * math.sin(i / 3)), "DTWEXBGS": 120 - 0.01 * _btc(i) / 1000}[series]
        rows.append({"date": day.isoformat(), "value": "." if i == 10 else str(value)})
    return json.dumps({"observations": rows}).encode()


def fake_fetch(url: str) -> bytes:
    if "binance" in url:
        return _klines("BTCUSDT" if "BTCUSDT" in url else "PAXGUSDT")
    if "stlouisfed" in url:
        assert "api_key=" + "k" * 32 in url and "file_type=json" in url
        return _fred(url.split("series_id=")[1].split("&")[0])
    if "coingecko" in url:
        return json.dumps({"data": {"market_cap_percentage": {"btc": 58.4321, "eth": 12.1}}}).encode()
    raise AssertionError(url)


def test_parsers_skip_missing_values_and_the_running_day() -> None:
    raw = json.dumps({"observations": [{"date": "2026-10-22", "value": "4.96"}, {"date": "2026-10-23", "value": "."}, {"date": "2026-10-24", "value": "5.00"}]})
    assert parse_fred(raw.encode()) == [(date(2026, 10, 22), 4.96), (date(2026, 10, 24), 5.0)]
    klines = parse_klines(_klines("BTCUSDT"), NOW)
    assert klines[-1][0] == DAYS[-1]  # today's open candle is left out
    assert parse_dominance(b'{"data":{"market_cap_percentage":{"btc":57.9}}}') == 57.9
    assert parse_dominance(b'{"data":{}}') is None and parse_dominance(b'{"data":{"market_cap_percentage":{"btc":130}}}') is None


def test_correlation_needs_overlap_and_detects_direction() -> None:
    a = {DAYS[i]: math.sin(i) for i in range(40)}
    assert correlation(a, a)[0] == 1.0 or abs(correlation(a, a)[0] - 1) < 1e-9
    assert correlation(a, {d: -v for d, v in a.items()})[0] < -0.99
    assert correlation(a, {DAYS[i]: 1.0 for i in range(5)}) == (None, 5)
    assert relation_text(0.6) == "läuft meist mit BTC" and relation_text(-0.5) == "läuft meist gegen BTC" and relation_text(0.1) == "kaum Zusammenhang"


def test_describe_yield_change_in_basis_points() -> None:
    series = [(DAYS[i], 4.0 + 0.1 * i) for i in range(25)]
    row = describe(series, "bp", None)
    assert row["change_unit"] == "bp" and abs(row["change"] - 50) < 1e-9 and row["above_mean"] is True


def test_build_macro_bar_rows_and_dominance_history(tmp_path) -> None:
    path = tmp_path / "macro" / "btc_dominance.jsonl"
    bar = build_macro_bar(fake_fetch, NOW, path, key=KEY)
    keys = [r["key"] for r in bar["rows"]]
    assert keys == ["btc", "gold", "dollar", "nasdaq", "us10y", "btc_dominance"]
    rows = {r["key"]: r for r in bar["rows"]}
    assert all(rows[k]["status"] == "OK" for k in keys[:-1])
    assert rows["dollar"]["corr_btc"] is not None and rows["dollar"]["corr_btc"] < -0.4  # built as the mirror of BTC
    assert rows["us10y"]["change_unit"] == "bp"
    assert rows["btc_dominance"]["last"] == 58.4321 and rows["btc_dominance"]["days_stored"] == 1
    # same UTC day: no second entry; next day: one more
    build_macro_bar(fake_fetch, NOW + timedelta(hours=3), path, key=KEY)
    build_macro_bar(fake_fetch, NOW + timedelta(days=1), path, key=KEY)
    assert [h["date"] for h in load_dominance(path)] == ["2026-10-27", "2026-10-28"]
    assert bar["read_only"] is True and not bar["notes"]


def test_failed_source_becomes_a_note_not_an_error(tmp_path) -> None:
    def broken(url: str) -> bytes:
        if "stlouisfed" in url and "NASDAQCOM" in url:
            raise OSError("blocked")
        return fake_fetch(url)

    bar = build_macro_bar(broken, NOW, tmp_path / "dom.jsonl", key=KEY)
    rows = {r["key"]: r for r in bar["rows"]}
    assert rows["nasdaq"]["status"] == "UNAVAILABLE" and rows["gold"]["status"] == "OK"
    assert any("NASDAQCOM" in n for n in bar["notes"])
    html = macro_rows_html(bar, _safe)
    assert "keine Daten" in html and "Gold (PAXG)" in html


def test_record_dominance_ignores_broken_lines(tmp_path) -> None:
    path = tmp_path / "d.jsonl"
    path.write_text('{"date":"2026-10-25","btc_dominance":58.0}\nnot json\n', encoding="utf-8")
    history = record_dominance(path, 58.5, NOW)
    assert [h["date"] for h in history] == ["2026-10-25", "2026-10-27"]


def test_cache_builds_once_and_pauses_after_failure(monkeypatch) -> None:
    calls = []
    cache = MacroCache(lambda: calls.append(1) or {"rows": [{"status": "OK"}], "notes": []})
    assert cache.snapshot(background=False)["rows"] and cache.snapshot(background=False) and len(calls) == 1
    bad = MacroCache(lambda: (_ for _ in ()).throw(OSError("down")))
    assert bad.snapshot(background=False) is None and bad.snapshot(background=False) is None


def test_prep_page_shows_macro_section_or_loading_line(tmp_path) -> None:
    bar = build_macro_bar(fake_fetch, NOW, tmp_path / "dom.jsonl", key=KEY)
    html = _prep_page({}, {"notes": ["Keine Daten."]}, macro=bar)
    assert "Makro: Gold, Dollar, Aktien, Zinsen, BTC-Dominanz" in html and "BTC-Dominanz" in html
    assert "werden geladen" in _prep_page({}, {"notes": []}, macro=None)
    assert "Makro" not in _prep_page({}, {"notes": []})
    assert macro_bar.DOMINANCE_PATH.as_posix() == "data/macro/btc_dominance.jsonl"


def test_without_fred_key_market_rows_stay_empty_and_key_never_leaks(tmp_path) -> None:
    bar = build_macro_bar(fake_fetch, NOW, tmp_path / "dom.jsonl", key=lambda: None)
    rows = {r["key"]: r for r in bar["rows"]}
    assert rows["dollar"]["status"] == rows["nasdaq"]["status"] == rows["us10y"]["status"] == "UNAVAILABLE"
    assert rows["gold"]["status"] == "OK" and rows["btc_dominance"]["status"] == "OK"
    assert rows["btc_dominance"]["relation"] == "Verlauf baut sich ab heute auf"
    assert any("FRED-Key fehlt" in n for n in bar["notes"])
    with_key = build_macro_bar(fake_fetch, NOW, tmp_path / "dom2.jsonl", key=KEY)
    assert "k" * 32 not in json.dumps(with_key, default=str)
