"""XMR-BTC coupling (Bauplan XMR, Paket 1): statistics on known series, verified archives, holdout refused."""
from __future__ import annotations

import hashlib
import io
import math
import random
import zipfile

import pytest

from src.research_lab import xmr_btc_coupling as xc

HOUR = xc.INTERVAL_MS["1h"]
DAY = xc.INTERVAL_MS["1d"]
T0 = xc.month_start_ms(2021, 1)


def _prices(returns: list[float], start: float = 100.0) -> list[float]:
    out = [start]
    for r in returns:
        out.append(out[-1] * math.exp(r))
    return out


def _series(prices: list[float], step: int, t0: int = T0) -> dict[int, float]:
    return {t0 + i * step: p for i, p in enumerate(prices)}


def test_exact_follower_has_corr_one_and_its_beta() -> None:
    rng = random.Random(1)
    btc_r = [rng.gauss(0, 0.01) for _ in range(500)]
    btc = _series(_prices(btc_r), HOUR)
    xmr = _series(_prices([1.5 * r for r in btc_r]), HOUR)
    pairs = xc.aligned_returns(btc, xmr, HOUR)
    result = xc.coupling(pairs, HOUR)
    assert result["n"] == 500
    assert result["corr"] == pytest.approx(1.0)
    assert result["beta"] == pytest.approx(1.5)
    assert result["own_share"] == pytest.approx(0.0, abs=1e-9)


def test_independent_series_have_little_correlation() -> None:
    rng = random.Random(2)
    btc = _series(_prices([rng.gauss(0, 0.01) for _ in range(3000)]), HOUR)
    xmr = _series(_prices([rng.gauss(0, 0.01) for _ in range(3000)]), HOUR)
    result = xc.coupling(xc.aligned_returns(btc, xmr, HOUR), HOUR)
    assert abs(result["corr"]) < 0.06
    assert result["own_share"] > 0.99


def test_lead_lag_finds_btc_moving_first() -> None:
    rng = random.Random(3)
    btc_r = [rng.gauss(0, 0.01) for _ in range(2000)]
    xmr_r = [0.0, 0.0] + btc_r[:-2]  # XMR repeats BTC two hours later
    pairs = xc.aligned_returns(_series(_prices(btc_r), HOUR), _series(_prices(xmr_r), HOUR), HOUR)
    ll = xc.lead_lag(pairs, HOUR)
    assert max(ll, key=lambda k: ll[k] or -1) == 2
    assert ll[2] == pytest.approx(1.0, abs=1e-6)
    assert abs(ll[0]) < 0.1


def test_gaps_drop_out_instead_of_spanning_two_candles() -> None:
    btc = _series([100, 101, 102, 103, 104], HOUR)
    xmr = _series([10, 11, 12, 13, 14], HOUR)
    del xmr[T0 + 2 * HOUR]
    pairs = xc.aligned_returns(btc, xmr, HOUR)
    # returns at 1h (from 0h) and 4h (from 3h) only: 2h has no XMR, 3h has no XMR before it
    assert pairs.times == [T0 + HOUR, T0 + 4 * HOUR]


def test_crash_correlation_uses_the_worst_btc_candles() -> None:
    rng = random.Random(4)
    btc_r = [rng.gauss(0, 0.01) for _ in range(1000)]
    cut = sorted(btc_r)[99]
    # XMR follows BTC only in crashes, otherwise noise
    xmr_r = [r if r <= cut else rng.gauss(0, 0.01) for r in btc_r]
    result = xc.coupling(xc.aligned_returns(_series(_prices(btc_r), HOUR), _series(_prices(xmr_r), HOUR), HOUR), HOUR)
    assert result["corr_crash"] == pytest.approx(1.0)
    assert abs(result["corr_rest"]) < 0.1


def test_by_year_and_rolling_spread() -> None:
    rng = random.Random(5)
    n = 800
    btc_r = [rng.gauss(0, 0.02) for _ in range(n)]
    # first half tightly coupled, second half loose
    xmr_r = [r + rng.gauss(0, 0.002) if i < n // 2 else rng.gauss(0, 0.02) for i, r in enumerate(btc_r)]
    pairs = xc.aligned_returns(_series(_prices(btc_r), DAY), _series(_prices(xmr_r), DAY), DAY)
    years = xc.by_year(pairs)
    assert list(years) == ["2021", "2022", "2023"]
    assert years["2021"]["corr"] > 0.9 and years["2023"]["corr"] < 0.3
    rolling = xc.rolling_corr(pairs, 30 * DAY)
    assert rolling["windows"] > 700 and rolling["max"] > 0.95 and rolling["min"] < 0.5


def test_holdout_months_are_refused() -> None:
    with pytest.raises(xc.HoldoutRefused):
        xc.archive_url("XMRUSDT", "1h", 2025, 1)
    assert xc.archive_url("XMRUSDT", "1h", 2024, 12).endswith("/XMRUSDT/1h/XMRUSDT-1h-2024-12.zip")
    assert xc.months()[-1] == (2024, 12)
    with pytest.raises(ValueError):
        xc.archive_url("ETHUSDT", "1h", 2021, 1)


def _archive(symbol: str, interval: str, year: int, month: int, closes: list[float]) -> bytes:
    step = xc.INTERVAL_MS[interval]
    start = xc.month_start_ms(year, month)
    rows = "\n".join(f"{start + i * step},{c},{c},{c},{c},10,{start + (i + 1) * step - 1},0,1,5,0,0" for i, c in enumerate(closes))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(f"{symbol}-{interval}-{year:04d}-{month:02d}.csv", "open_time,o,h,l,c,v,close_time,qv,count,tbv,tbqv,ignore\n" + rows)
    return buffer.getvalue()


def _fake_binance(archives: dict[str, bytes], calls: list[str]):
    def fetch(url: str) -> bytes:
        calls.append(url)
        if url.endswith(".CHECKSUM"):
            name = url.rsplit("/", 1)[-1].removesuffix(".CHECKSUM")
            if name not in archives:
                raise xc.MissingArchive(url)
            return f"{hashlib.sha256(archives[name]).hexdigest()}  {name}\n".encode()
        name = url.rsplit("/", 1)[-1]
        if name not in archives:
            raise xc.MissingArchive(url)
        return archives[name]
    return fetch


def test_load_month_verifies_checksum_and_caches(tmp_path) -> None:
    payload = _archive("XMRUSDT", "1d", 2021, 1, [100.0, 101.0, 102.0])
    calls: list[str] = []
    fetch = _fake_binance({"XMRUSDT-1d-2021-01.zip": payload}, calls)
    closes = xc.load_month("XMRUSDT", "1d", 2021, 1, tmp_path, fetch)
    assert list(closes.values()) == [100.0, 101.0, 102.0]
    assert len(calls) == 2  # archive + checksum
    xc.load_month("XMRUSDT", "1d", 2021, 1, tmp_path, fetch)
    assert len(calls) == 2  # second read from the verified cache

    def tampered(url: str) -> bytes:
        if url.endswith(".CHECKSUM"):
            return f"{'0' * 64}  XMRUSDT-1d-2021-02.zip\n".encode()
        return _archive("XMRUSDT", "1d", 2021, 2, [1.0])

    with pytest.raises(ValueError, match="checksum mismatch"):
        xc.load_month("XMRUSDT", "1d", 2021, 2, None, tampered)


def test_run_end_to_end_with_kraken_cross_check() -> None:
    rng = random.Random(6)
    archives: dict[str, bytes] = {}
    span = [(2021, 1), (2021, 2)]
    btc_daily, xmr_daily = [], []
    for symbol in xc.SYMBOLS:
        for interval in xc.INTERVALS:
            for year, month in span:
                step = xc.INTERVAL_MS[interval]
                days_in = (xc.month_start_ms(2021, month + 1) - xc.month_start_ms(year, month)) // step
                btc_r = [rng.gauss(0, 0.01) for _ in range(days_in - 1)]
                prices = _prices(btc_r, 30_000.0 if symbol == "BTCUSDT" else 200.0)
                archives[f"{symbol}-{interval}-{year:04d}-{month:02d}.zip"] = _archive(symbol, interval, year, month, prices)
    calls: list[str] = []
    fetch = _fake_binance(archives, calls)
    # Kraken XMR/XBT = Binance ratio on 1d, 0.2 % apart
    btc = {}
    xmr = {}
    for year, month in span:
        btc.update(xc.load_month("BTCUSDT", "1d", year, month, None, fetch))
        xmr.update(xc.load_month("XMRUSDT", "1d", year, month, None, fetch))
    kraken = "\n".join(f"{t // 1000},0,0,0,{xmr[t] / btc[t] * 1.002},1,1" for t in sorted(btc))
    report = xc.run(None, fetch, kraken_text=kraken, span=span)
    assert set(report["intervals"]) == {"15m", "1h", "1d"}
    assert report["intervals"]["1h"]["n"] > 1000
    check = report["kraken_xmr_btc"]
    assert check["days"] == len(btc) and check["median_gap"] == pytest.approx(1 - 1 / 1.002)
    assert check["return_corr"] == pytest.approx(1.0)
    text = xc.markdown(report)
    assert "Gegenprobe Kraken" in text and "Wer bewegt sich zuerst" in text
    assert not any("2025" in url for url in calls)


def test_missing_months_are_listed_not_fatal() -> None:
    fetch = _fake_binance({}, [])
    closes, missing = xc.load_closes("XMRUSDT", "1d", None, fetch, [(2020, 3)])
    assert closes == {} and missing == ["2020-03"]


def test_kraken_rows_from_the_holdout_are_ignored() -> None:
    text = f"{(xc.HOLDOUT_START_MS - DAY) // 1000},1,1,1,0.004,1,1\n{xc.HOLDOUT_START_MS // 1000},1,1,1,0.005,1,1\n"
    assert list(xc.parse_kraken_ohlcvt(text).values()) == [0.004]
