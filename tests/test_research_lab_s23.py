"""S23: open interest at S20's breaks against the mechanics model; metrics archive parsing; freeze guard."""
from __future__ import annotations

import hashlib
import io
import math
import random
import zipfile
from datetime import date, datetime, timezone

import pytest

from src.research_lab.data.metrics import MetricsRef, OpenInterest, parse_metrics
from src.research_lab.data.store import ArchiveStore, HoldoutLocked
from src.research_lab.studies import s20, s23
from src.research_lab.studies.s20 import DOWN, HOUR, UP, Event
from src.research_lab.studies.s23 import HourlyOI, Row

HEADER = ("create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,"
          "sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n")
T0 = int(datetime(2021, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
FIVE = 5 * 60_000


def _snapshots(hours: int, value=lambda k: 100.0) -> list[OpenInterest]:
    return [OpenInterest(T0 + k * FIVE, value(k)) for k in range(hours * 12 + 1)]


def _event(hour: int, direction: str = UP) -> Event:
    return Event(500, T0 + hour * HOUR, direction, 1.0, 0, 1.0, "training")


# -- archive --------------------------------------------------------------------------------------------


def test_metrics_ref_points_at_the_daily_archive_and_respects_the_holdout():
    ref = MetricsRef(date(2020, 9, 1))
    assert ref.url == "https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2020-09-01.zip"
    assert ref.checksum_url.endswith(".zip.CHECKSUM") and not ref.touches_holdout
    assert MetricsRef(date(2025, 1, 1)).touches_holdout and not MetricsRef(date(2024, 12, 31)).touches_holdout
    with pytest.raises(ValueError):
        MetricsRef(date(2020, 8, 31))
    with pytest.raises(HoldoutLocked):
        ArchiveStore("unused", fetcher=lambda url: b"").fetch(MetricsRef(date(2025, 1, 1)))


def test_parse_metrics_collapses_the_repeated_rows_of_the_backfilled_files():
    rows = "2020-09-01 00:05:00,BTCUSDT,39081.0,1,1,1,1,1\n2020-09-01 00:00:00,BTCUSDT,39080.231,1,1,1,1,1\n"
    out = parse_metrics(HEADER + rows + rows)
    assert [o.contracts for o in out] == [39080.231, 39081.0]
    assert out[0].time == int(datetime(2020, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)
    with pytest.raises(ValueError):
        parse_metrics(HEADER + rows + "2020-09-01 00:00:00,BTCUSDT,1.0,1,1,1,1,1\n")


def test_store_verifies_and_loads_open_interest(tmp_path):
    ref = MetricsRef(date(2021, 12, 1))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("BTCUSDT-metrics-2021-12-01.csv", HEADER + "2021-12-01 00:00:00,BTCUSDT,59230.06,1,1,1,1,1\n"
                   "2021-11-30 23:55:00,BTCUSDT,1.0,1,1,1,1,1\n")
    payload = buf.getvalue()
    sidecar = f"{hashlib.sha256(payload).hexdigest()}  {ref.filename}".encode()
    store = ArchiveStore(tmp_path, fetcher=lambda url: sidecar if url.endswith(".CHECKSUM") else payload)
    store.fetch(ref)
    assert [o.contracts for o in store.load_open_interest([ref])] == [59230.06]  # rows outside the day dropped
    assert len(store.dataset_hash([ref])) == 64
    bad = ArchiveStore(tmp_path / "b", fetcher=lambda url: b"0" * 64 + f"  {ref.filename}".encode() if url.endswith(".CHECKSUM") else payload)
    with pytest.raises(ValueError):
        bad.fetch(ref)


# -- features -------------------------------------------------------------------------------------------


def test_hourly_value_is_the_last_snapshot_and_never_stale():
    oi = HourlyOI([OpenInterest(T0, 10.0), OpenInterest(T0 + FIVE, 11.0), OpenInterest(T0 + 6 * FIVE, 12.0)])
    assert oi.at(T0 + FIVE + 60_000) == 11.0
    assert oi.at(T0 + 3 * FIVE) == 11.0  # last snapshot 10 minutes old is allowed
    assert oi.at(T0 + 4 * FIVE) is None  # 15 minutes is not
    assert oi.at(T0 - 1) is None


def test_oi_features_window_break_and_level():
    hour = 400
    def value(k: int) -> float:
        h = k / 12
        if h <= hour - 10:
            return 100.0 + (k % 2)  # flat with a little noise, so the z-scores have a scale
        if h <= hour:
            return 100.0 * math.exp(0.01 * (h - (hour - 10)))  # +10 % log over the window
        return 100.0 * math.exp(0.1) * 1.05  # break hour: +5 %
    oi = HourlyOI(_snapshots(hour + 30, value))
    fenster, bruch_z, niveau_z = s23.oi_features(oi, _event(hour))
    assert fenster == pytest.approx(0.1, abs=1e-6)
    assert bruch_z > 10 and niveau_z > 1
    assert s23.oi_features(oi, _event(hour, DOWN)) == (fenster, bruch_z, niveau_z)  # unsigned by design


def test_oi_features_ignore_snapshots_after_the_break_close():
    hour = 400
    snaps = _snapshots(hour + 30, lambda k: 100.0 + (k % 3))
    before = s23.oi_features(HourlyOI(snaps), _event(hour))
    close = T0 + (hour + 1) * HOUR
    later = [OpenInterest(s.time, 999.0) if s.time > close else s for s in snaps]
    assert s23.oi_features(HourlyOI(later), _event(hour)) == before


def test_oi_features_need_the_values_and_the_history():
    hour = 400
    snaps = _snapshots(hour + 30, lambda k: 100.0 + (k % 3))
    close = T0 + (hour + 1) * HOUR
    assert s23.oi_features(HourlyOI([s for s in snaps if not close - 20 * 60_000 < s.time <= close]), _event(hour)) is None
    assert s23.oi_features(HourlyOI(snaps), _event(250)) is None  # fewer than 300 of the 336 earlier hours
    assert s23.START_MS == int(datetime(2020, 9, 15, tzinfo=timezone.utc).timestamp() * 1000)


# -- evaluation -----------------------------------------------------------------------------------------


def _rows(planted: bool, seed: int, *, mechanics_signal: float = 0.0, native_signal: bool = True) -> list[Row]:
    rng = random.Random(seed)
    rows = []
    t = s23.START_MS
    while (section := s20.section_of(t)) is not None:
        oi = tuple(rng.gauss(0, 1) for _ in s23.FEATURES)
        mech = abs(rng.gauss(0, 1))
        active = planted and (native_signal or t < s23.NATIVE_START_MS or section == "validierung")
        z = mechanics_signal * mech + (3.0 * oi[0] if active else 0.0)
        rows.append(Row(t, s20.week_of(t), section, int(rng.random() < 1 / (1 + math.exp(-z))), mech, oi))
        t += 40 * HOUR
    return rows


def test_planted_open_interest_passes():
    out = s23.evaluate(_rows(True, 1), boot_draws=199, shift_draws=39, version="1.0")
    assert out["urteil"] == "BESTANDEN (Kandidat)" and all(out["kriterien"].values())
    assert out["rel_gewinn"] > 0.1 and out["training_ab_2021_12"] >= s23.MIN_NATIVE_TRAINING


def test_distance_alone_does_not_pass():
    out = s23.evaluate(_rows(False, 2, mechanics_signal=2.0), boot_draws=199, shift_draws=3, version="1.0")
    assert out["urteil"].startswith("NICHT BESTANDEN") and not out["kriterien"]["gewinn"]


def test_signal_only_in_the_backfilled_years_fails_the_seam_check():
    out = s23.evaluate(_rows(True, 3, native_signal=False), boot_draws=199, shift_draws=3, version="1.0")
    assert out["kriterien"]["naht"] is False and out["urteil"].startswith("NICHT BESTANDEN")


def test_too_few_events_is_not_testable():
    rows = [Row(r.time, r.week, r.section, r.y, r.mechanics, None if i % 4 else r.oi) for i, r in enumerate(_rows(False, 4))]
    out = s23.evaluate(rows, boot_draws=99, shift_draws=3, version="1.0")
    assert out["urteil"] == "nicht testbar (Gate)" and "p" not in out


def test_count_is_results_blind():
    ev = [Event(i, s23.NATIVE_START_MS + (i - 2) * 50 * HOUR, UP, 1.0, 0, 1.0, "training") for i in range(5)]
    ev.append(Event(9, s23.START_MS - HOUR, UP, 1.0, 0, 1.0, "training"))
    out = s23.count(ev, {"entprellt": 2}, {e.time for e in ev[1:]})
    assert "flip" not in repr(out).lower()
    assert out["ereignisse"]["training"] == {"ab_start": 5, "mit_merkmalen": 4} and out["training_ab_2021_12"] == 3


def test_evaluate_refuses_while_draft():
    with pytest.raises(PermissionError):
        s23.evaluate(_rows(False, 5))
    assert s23.VERSION == "0.1" and s20.VERSION == "1.0"
