from datetime import datetime, timedelta, timezone

import buzz
import paper_bot
import report
import scanner
from common import SnapshotMarket, dt_to_ms, iso, read_rows

H = 3600 * 1000
M5 = 5 * 60 * 1000
NOW = datetime(2026, 10, 23, 12, 2, tzinfo=timezone.utc)
quiet = lambda *a, **k: None  # noqa: E731


def hour_klines(end_open: datetime, n: int, last_move: float, last_qv: float, base_qv: float = 1000.0):
    rows = []
    start = dt_to_ms(end_open) - (n - 1) * H
    for i in range(n):
        t = start + i * H
        o = 100.0
        c = 100.0 * (1 + last_move / 100) if i == n - 1 else 100.0
        qv = last_qv if i == n - 1 else base_qv
        rows.append([t, o, max(o, c), min(o, c), c, 1.0, t + H - 1, qv])
    return rows


def five_min(start: datetime, bars):
    t0 = dt_to_ms(start)
    return [[t0 + i * M5, o, h, l, c, 1.0, t0 + (i + 1) * M5 - 1, 1.0] for i, (o, h, l, c) in enumerate(bars)]


def market(extra=None):
    last_open = datetime(2026, 10, 23, 11, 0, tzinfo=timezone.utc)
    data = {
        "tickers": [
            {"symbol": "AAAUSDT", "quoteVolume": "5000"},
            {"symbol": "BBBUSDT", "quoteVolume": "4000"},
            {"symbol": "USDCUSDT", "quoteVolume": "9999"},
            {"symbol": "ETHDOWNUSDT", "quoteVolume": "9999"},
            {"symbol": "CCCBTC", "quoteVolume": "9999"},
            {"symbol": "JUPUSDT", "quoteVolume": "1"},
        ],
        "klines": {
            "AAAUSDT:1h": hour_klines(last_open, 170, last_move=4.0, last_qv=3000),  # Treffer
            "BBBUSDT:1h": hour_klines(last_open, 170, last_move=4.0, last_qv=1500),  # Volumen zu schwach
        },
        "prices": {"AAAUSDT": 104.0},
    }
    if extra:
        data["klines"].update(extra)
    return SnapshotMarket(data)


# --- Scanner ---

def test_universe_filters_stables_leveraged_and_non_usdt():
    assert scanner.select_universe(market().tickers_24h(), 10) == ["AAAUSDT", "BBBUSDT", "JUPUSDT"]


def test_scanner_flags_only_move_and_volume_and_dedups(tmp_path):
    flags = scanner.scan(market(), tmp_path, now=NOW, log=quiet)
    assert [f["symbol"] for f in flags] == ["AAAUSDT"]
    f = flags[0]
    assert f["direction"] == "up" and f["volume_multiple"] == 3.0
    assert f["candle_close_time"] == "2026-10-23T12:00:00+00:00"
    assert scanner.scan(market(), tmp_path, now=NOW + timedelta(minutes=5), log=quiet) == []
    assert len(read_rows(tmp_path / "scanner.csv")) == 1


def test_scanner_ignores_unclosed_candle():
    last_open = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)  # läuft noch
    kl = hour_klines(last_open, 170, last_move=10.0, last_qv=9000)
    assert scanner.evaluate("AAAUSDT", kl, NOW, 3.0, 2.0) is None


def test_scanner_move_must_exceed_threshold():
    last_open = datetime(2026, 10, 23, 11, 0, tzinfo=timezone.utc)
    kl = hour_klines(last_open, 170, last_move=3.0, last_qv=9000)
    assert scanner.evaluate("AAAUSDT", kl, NOW, 3.0, 2.0) is None


# --- Buzz ---

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>AAA rallies as traders pile in</title><pubDate>Fri, 23 Oct 2026 10:00:00 +0000</pubDate></item>
<item><title>Why $AAA is up today</title><pubDate>Fri, 23 Oct 2026 09:00:00 +0000</pubDate></item>
<item><title>AAA old news</title><pubDate>Mon, 19 Oct 2026 09:00:00 +0000</pubDate></item>
<item><title>AAAB is something else</title><pubDate>Fri, 23 Oct 2026 09:00:00 +0000</pubDate></item>
</channel></rss>"""


def test_parse_rss_and_count_mentions_last_24h_whole_word():
    items = buzz.parse_rss(RSS)
    assert len(items) == 4
    assert buzz.count_mentions("AAA", None, items, NOW) == 2


def test_parse_rss_broken_feed_is_empty():
    assert buzz.parse_rss(b"<rss><unclosed>") == []


def test_score_points_and_cap():
    trending = buzz.parse_trending({"coins": [{"item": {"symbol": "aaa", "name": "Triple A", "score": 0}}]})
    items = buzz.parse_rss(RSS)
    res = buzz.score_coin("AAA", trending, items, NOW)
    assert res["trending_points"] == 6 and res["headline_points"] == 2 and res["buzz_score"] == 8
    assert "Platz 1" in res["reason"]
    many = [{"title": "AAA", "published": NOW} for _ in range(9)]
    assert buzz.score_coin("AAA", trending, many, NOW)["buzz_score"] == 10
    assert buzz.score_coin("ZZZ", trending, items, NOW)["buzz_score"] == 0


def test_ambiguous_ticker_counts_only_by_name():
    items = [{"title": "Near the top? Bitcoin stalls", "published": NOW}]
    assert buzz.count_mentions("NEAR", None, items, NOW) == 0
    assert buzz.count_mentions("BTC", "Bitcoin", items, NOW) == 1


def run_pipeline(tmp_path, trending_rank=0, headlines=2):
    scanner.scan(market(), tmp_path, now=NOW, log=quiet)
    src = buzz.SnapshotBuzzSources({
        "trending": {"coins": [{"item": {"symbol": "AAA", "name": "Triple A", "score": trending_rank}}]}
        if trending_rank is not None else {"coins": []},
        "headlines": [{"title": "AAA pumps", "published": iso(NOW)} for _ in range(headlines)],
    })
    buzz.run(src, tmp_path, now=NOW, log=quiet)


# --- Papier-Bot ---

def test_buzz_7_opens_real_trade_with_one_percent_risk(tmp_path):
    run_pipeline(tmp_path)
    out = paper_bot.run(market(), tmp_path, now=NOW + timedelta(minutes=1), log=quiet)
    assert [d["decision"] for d in out["decisions"]] == ["real_open"]
    pos = out["state"]["open"][0]
    assert abs(pos["risk_amount"] - 10.0) < 1e-9
    loss_at_stop = pos["notional"] * (0.03 + 0.002 + 0.0005)
    assert abs(loss_at_stop - 10.0) < 1e-6
    assert pos["stop"] < pos["entry_price"] < pos["take_profit"]
    assert abs(pos["take_profit"] / pos["entry_price"] - 1.06) < 1e-9
    # zweiter Lauf: Signal schon verarbeitet
    out2 = paper_bot.run(market(), tmp_path, now=NOW + timedelta(minutes=2), log=quiet)
    assert out2["decisions"] == []


def test_low_buzz_goes_to_shadow_book_only(tmp_path):
    run_pipeline(tmp_path, trending_rank=None, headlines=1)
    out = paper_bot.run(market(), tmp_path, now=NOW + timedelta(minutes=1), log=quiet)
    assert out["decisions"][0]["decision"] == "shadow_open"
    assert out["state"]["open"] == [] and len(out["state"]["shadow_open"]) == 1
    assert out["state"]["cash"] == 1000.0


def test_stale_signal_is_skipped(tmp_path):
    run_pipeline(tmp_path)
    out = paper_bot.run(market(), tmp_path, now=NOW + timedelta(minutes=30), log=quiet)
    assert out["decisions"][0]["decision"] == "skip_stale"


def test_take_profit_closes_with_fees(tmp_path):
    run_pipeline(tmp_path)
    t_open = NOW + timedelta(minutes=1)
    paper_bot.run(market(), tmp_path, now=t_open, log=quiet)
    start = datetime(2026, 10, 23, 12, 5, tzinfo=timezone.utc)
    bars = five_min(start, [(104, 105, 103.5, 104.5), (104.5, 111, 104, 110)])
    out = paper_bot.run(market({"AAAUSDT:5m": bars}), tmp_path, now=start + timedelta(minutes=15), log=quiet)
    (row,) = out["closed"]
    assert row["exit_reason"] == "take_profit"
    assert float(row["fees"]) > 0 and float(row["net_pnl"]) < float(row["gross_pnl"])
    assert 1.7 < float(row["r_multiple"]) < 2.0
    assert abs(out["state"]["cash"] - (1000 + float(row["net_pnl"]))) < 1e-3


def test_candle_hitting_stop_and_target_counts_as_stop():
    pos = {"stop": 97.0, "take_profit": 106.0, "deadline": iso(NOW + timedelta(hours=24))}
    bars = five_min(NOW, [(100, 107, 96, 101)])
    assert paper_bot.find_exit(pos, bars)[1] == "stop"


def test_gap_below_stop_fills_at_open():
    pos = {"stop": 97.0, "take_profit": 106.0, "deadline": iso(NOW + timedelta(hours=24))}
    bars = five_min(NOW, [(95, 96, 94, 95.5)])
    assert paper_bot.find_exit(pos, bars)[:2] == (95, "stop_gap")


def test_time_exit_after_deadline():
    pos = {"stop": 97.0, "take_profit": 106.0, "deadline": iso(NOW + timedelta(minutes=10))}
    bars = five_min(NOW, [(100, 101, 99, 100), (100, 101, 99, 100.5)])
    assert paper_bot.find_exit(pos, bars)[:2] == (100.5, "time")


def test_daily_cap(tmp_path):
    cfg = paper_bot.Config(max_trades_per_day=0)
    run_pipeline(tmp_path)
    out = paper_bot.run(market(), tmp_path, now=NOW + timedelta(minutes=1), cfg=cfg, log=quiet)
    assert out["decisions"][0]["decision"] == "skip_daily_cap"


# --- Bericht ---

def test_report_is_strict_with_small_sample(tmp_path):
    test_take_profit_closes_with_fees(tmp_path)
    rep = report.build(tmp_path)
    assert rep["real"]["trades"] == 1
    assert rep["verdict"].startswith("NEIN")
    assert rep["buzz_helped"].startswith("Nicht beurteilbar")
    text = report.render(rep)
    assert "Trefferquote 100.0%" in text and "kein Echtgeld" in text


def test_report_empty(tmp_path):
    assert "Noch keine" in report.render(report.build(tmp_path))


def test_non_ascii_symbol_is_url_encoded(monkeypatch):
    import common

    seen = []
    monkeypatch.setattr(common, "http_get_json", lambda url, timeout=15.0: seen.append(url) or [])
    common.BinancePublic().klines("\u725b\u6765USDT", "1h", 5)
    assert seen[0].isascii() and "%E7%89%9B" in seen[0]
