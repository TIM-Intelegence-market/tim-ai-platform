"""Study S8 (draft): trade-only bars, features, labels, export, replay and guards."""
from __future__ import annotations

import hashlib
import io
import json
import random
import zipfile
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.research_lab.data.aggtrades import AggTradeDayStore
from src.research_lab.data.store import HoldoutLocked
from src.research_lab.orderflow_ml import __main__ as cli
from src.research_lab.orderflow_ml.bars import (MINUTE_MS, MinuteBar, TradeTick, decimal_to_e8, nice_width_e8, reduce_trades,
                                                reduce_trades_with_profile, ticks_from_rows)
from src.research_lab.orderflow_ml.profile import tpo_histogram, value_area, volume_histogram
from src.research_lab.orderflow_ml.export import FEATURE_HEADER, ExportConfig, crosscheck_s2, replay, run_export
from src.research_lab.orderflow_ml.features import FEATURE_NAMES, WARMUP_BARS, BarSeries, features_at
from src.research_lab.orderflow_ml.labels import LabelConfig, label_at
from src.research_lab.orderflow_ml.store import MinuteBarStore, day_start_ms
from src.v2_readiness.backfill import BinanceArchiveRef


def synthetic_rows(day: date, seed: int, *, gap: tuple[int, int] | None = None, first_id: int | None = None) -> list[list[str]]:
    rng = random.Random(seed)
    start = day_start_ms(day)
    rows: list[list[str]] = []
    trade_id = first_id if first_id is not None else seed * 10_000_000
    price = 30_000.0 + seed
    for minute in range(1440):
        if gap and gap[0] <= minute < gap[1]:
            continue
        stamps = sorted(rng.randint(0, 59_999) for _ in range(rng.randint(1, 4)))
        for offset in stamps:
            trade_id += 1
            price = max(1000.0, price * (1 + rng.gauss(0, 0.0004)))
            qty = f"{rng.randint(1, 300_000) / 1e5:.5f}"
            rows.append([str(trade_id), f"{price:.2f}", qty, "1", "1", str(start + minute * MINUTE_MS + offset),
                         "True" if rng.random() < 0.5 else "False", "True"])
    return rows


def zipped(name: str, rows: list[list[str]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(name, "\n".join(",".join(r) for r in rows) + "\n")
    return buffer.getvalue()


class FakeArchive:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.calls: list[str] = []

    def add(self, day: date, rows: list[list[str]], *, corrupt: bool = False) -> None:
        ref = BinanceArchiveRef(day)
        payload = zipped(ref.filename.replace(".zip", ".csv"), rows)
        digest = "0" * 64 if corrupt else hashlib.sha256(payload).hexdigest()
        self.files[ref.url] = payload
        self.files[ref.checksum_url] = f"{digest}  {ref.filename}\n".encode()

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        return self.files[url]


def filled_store(tmp_path: Path, days: list[date], **gaps) -> MinuteBarStore:
    fake = FakeArchive()
    for n, day in enumerate(days):
        fake.add(day, synthetic_rows(day, n + 1, gap=gaps.get(day.isoformat())))
    store = MinuteBarStore(tmp_path / "s8", fake)
    for day in days:
        store.fetch(day)
    return store


# -- bars -------------------------------------------------------------------------------------------------
def test_decimal_to_e8_is_exact_and_strict() -> None:
    assert decimal_to_e8("30000.12") == 3_000_012_000_000
    assert decimal_to_e8("0.00000001") == 1
    assert decimal_to_e8("1.10000000") == 110_000_000
    for bad in ("-1", "0.000000001", "abc", ""):
        with pytest.raises(ValueError):
            decimal_to_e8(bad)


def test_reduction_detects_duplicates_gaps_regressions_and_wrong_day() -> None:
    start = day_start_ms(date(2020, 3, 1))
    t = [TradeTick(10, 100 * 10**8, 10**8, start + 5, False), TradeTick(10, 100 * 10**8, 10**8, start + 5, False),
         TradeTick(13, 101 * 10**8, 2 * 10**8, start + 4, True), TradeTick(14, 99 * 10**8, 5 * 10**7, start + 70_000, False)]
    bars, q = reduce_trades(t, start)
    assert (q.rows, q.duplicate_rows, q.id_gaps, q.time_regressions, q.empty_minutes) == (4, 1, 2, 1, 1438)
    first = bars[0]
    assert (first.trade_count, first.buy_count, first.buy_sats, first.sell_sats, first.large_count) == (2, 1, 10**8, 2 * 10**8, 2)
    assert (first.last_price_e8, first.high_price_e8, first.low_price_e8) == (101 * 10**8, 101 * 10**8, 100 * 10**8)
    assert first.buy_quote_e8 == 100 * 10**8 and first.sell_quote_e8 == 202 * 10**8
    with pytest.raises(ValueError, match="different content"):
        reduce_trades([t[0], t[0]._replace(qty_sats=7)], start)
    with pytest.raises(ValueError, match="ascending"):
        reduce_trades([t[2], t[0]], start)
    with pytest.raises(ValueError, match="outside the UTC day"):
        reduce_trades([t[0]._replace(time_ms=start - 1)], start)


def test_bars_match_s2_count_files_and_s2_prices_stay_unopened(tmp_path: Path) -> None:
    day = date(2020, 1, 6)
    rows = synthetic_rows(day, 3)
    fake = FakeArchive()
    fake.add(day, rows)
    s2 = AggTradeDayStore(tmp_path / "s2", fake)
    s2.fetch(day)
    ours = MinuteBarStore(tmp_path / "s8", fake)
    ours.fetch(day)
    px = s2.px_path(day)
    px.unlink()  # any attempt to read S2 prices would now fail
    assert crosscheck_s2(ours, s2, [day]) == {"days_checked": 1, "days_mismatched": []}


# -- store -------------------------------------------------------------------------------------------------
def test_store_refuses_holdout_before_fetching_and_bad_checksums(tmp_path: Path) -> None:
    fake = FakeArchive()
    store = MinuteBarStore(tmp_path, fake)
    with pytest.raises(HoldoutLocked):
        store.fetch(date(2025, 1, 1))
    assert fake.calls == []
    fake.add(date(2020, 2, 2), synthetic_rows(date(2020, 2, 2), 1), corrupt=True)
    with pytest.raises(ValueError, match="checksum"):
        store.fetch(date(2020, 2, 2))
    with pytest.raises(ValueError):
        ExportConfig(date(2024, 1, 1), date(2025, 1, 1))


def test_store_detects_changed_bar_file(tmp_path: Path) -> None:
    store = filled_store(tmp_path, [date(2020, 2, 2)])
    path = store.bar_path(date(2020, 2, 2))
    path.write_text(path.read_text().replace("\n1580601", "\n1580602", 1))
    with pytest.raises(ValueError, match="changed on disk"):
        store.load(date(2020, 2, 2))


# -- features: no look-ahead ---------------------------------------------------------------------------------
def _series(tmp_path: Path) -> BarSeries:
    days = [date(2020, 2, 2), date(2020, 2, 3)]
    store = filled_store(tmp_path, days)
    return BarSeries(store.load(days[0]) + store.load(days[1]), {day_start_ms(d): store.load_profile(d) for d in days})


def test_future_bars_never_change_a_feature(tmp_path: Path) -> None:
    full = _series(tmp_path)
    full_profiles = full.profiles
    rng = random.Random(7)
    for i in [0, 59, WARMUP_BARS - 1, 600, 1439, 1440, 2000]:
        cut = full.start[i]
        profiles = {d: p for d, p in full_profiles.items()}
        future_profiles = {d: replace(p, entries=tuple(e if d + e[0] * MINUTE_MS <= cut else (e[0], e[1] + 7, e[2] * 3, 1) for e in p.entries))
                           for d, p in profiles.items()}
        truncated = BarSeries(full.bars[: i + 1], profiles)
        tampered = full.bars[: i + 1] + [MinuteBar.empty(b.window_start_ms) if rng.random() < 0.5 else b for b in full.bars[i + 1:]]
        assert features_at(truncated, i) == features_at(full, i) == features_at(BarSeries(tampered, future_profiles), i)


def test_features_are_complete_after_warmup_and_flag_warmup(tmp_path: Path) -> None:
    s = _series(tmp_path)
    assert not features_at(s, WARMUP_BARS - 2).warm
    row = features_at(s, 1500)
    assert row.warm and len(row.values) == len(FEATURE_NAMES)
    # Sequence correlation requires at least three events in the current minute.
    assert row.complete == (s.bars[1500].trade_count >= 3)
    complete = next(features_at(s, i) for i in range(1440, 2000) if s.bars[i].trade_count >= 3)
    assert complete.complete
    assert row.values[FEATURE_NAMES.index("hour_utc")] == datetime.fromtimestamp(row.decision_ms / 1000, tz=timezone.utc).hour


def test_previous_hour_uses_closed_clock_hour_only(tmp_path: Path) -> None:
    s = _series(tmp_path)
    i = 1440 + 10 * 60 + 29  # decision 10:30 -> hour 09:00-10:00
    j_last = 1440 + 9 * 60 + 59
    hi = max(s.high[j_last - 59: j_last + 1])
    row = features_at(s, i)
    import math
    assert row.values[FEATURE_NAMES.index("prev_hour_dist_high")] == math.log(s.px[i] / hi)


# -- labels -------------------------------------------------------------------------------------------------
def test_missing_target_is_never_neutral(tmp_path: Path) -> None:
    day = date(2020, 2, 2)
    store = filled_store(tmp_path, [day], **{day.isoformat(): (600, 620)})
    s = BarSeries(store.load(day))
    cfg = LabelConfig()
    vol = 0.001
    assert label_at(s, 598, vol, cfg).status == "stale_target"  # target minute 603 lies in the gap
    assert label_at(s, 610, vol, cfg).status == "stale_start"
    assert label_at(s, 1439, vol, cfg).status == "beyond_data"
    ok = label_at(s, 700, vol, cfg)
    assert ok.status == "ok" and ok.label in {"up", "down", "neutral"} and ok.threshold >= cfg.cost_floor
    assert label_at(s, 700, None, cfg).status == "no_volatility"


# -- export -------------------------------------------------------------------------------------------------
DAYS = [date(2022, 12, 30), date(2022, 12, 31), date(2023, 1, 1)]


def test_export_is_deterministic_purges_boundaries_and_replays(tmp_path: Path) -> None:
    store = filled_store(tmp_path, DAYS)
    cfg = ExportConfig(DAYS[0], DAYS[-1])
    a = run_export(store, cfg, tmp_path / "a", code_version="x")
    b = run_export(store, cfg, tmp_path / "b", code_version="x")
    assert (a["features_hash"], a["labels_hash"]) == (b["features_hash"], b["labels_hash"])
    train, val = a["sections"]["train"], a["sections"]["validation"]
    assert train["days"] == 2 and val["days"] == 1
    assert train["label_status"]["purged_section_end"] == 5  # all five targets purged, even with incomplete sequence features
    assert "warmup" not in val["exclusions"]  # 2023-01-01 looks back into 2022-12-31 (past data)
    assert train["exclusions"]["warmup"] == WARMUP_BARS - 1  # only the first day of the run has no history
    assert val["label_status"]["beyond_data"] == 5
    export_dir = tmp_path / "a" / cfg.export_id()
    header = (export_dir / "features" / "BTCUSDT-2022-12-31.csv").read_text().splitlines()[0].split(",")
    assert header == FEATURE_HEADER
    report = (export_dir / "quality_report.md").read_text()
    assert "neutral" not in report and "up" not in report.split("Ergebnisblind")[1].split("|")[0]
    for stamp in ("2022-12-31T12:00:00Z", "2023-01-01T00:00:00Z", "2023-01-01T08:31:00Z"):
        decision = int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() * 1000)
        result = replay(store, decision, cfg, export_dir)
        assert result["matches_export"], stamp
    edge = replay(store, int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000), cfg)
    assert edge["section"] == "train" and edge["label"]["status"] == "purged_section_end"


def test_export_reports_missing_days_and_restarts_warmup(tmp_path: Path) -> None:
    store = filled_store(tmp_path, [date(2021, 5, 1), date(2021, 5, 3)])
    split = run_export(store, ExportConfig(date(2021, 5, 1), date(2021, 5, 3)), tmp_path / "out")
    assert split["missing_days"] == ["2021-05-02"]
    assert split["sections"]["train"]["exclusions"]["warmup"] == 2 * (WARMUP_BARS - 1)


def test_cli_fetch_export_replay_from_local_archives(tmp_path: Path, capsys) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    fake = FakeArchive()
    days = [date(2020, 4, 1), date(2020, 4, 2)]
    for n, day in enumerate(days):
        fake.add(day, synthetic_rows(day, n + 5))
    for url, payload in fake.files.items():
        (raw / url.rsplit("/", 1)[1]).write_bytes(payload)
    root = str(tmp_path / "lab")
    assert cli.main(["--root", root, "fetch", "--from", "2020-04-01", "--to", "2020-04-02", "--raw-dir", str(raw)]) == 0
    assert cli.main(["--root", root, "export", "--from", "2020-04-01", "--to", "2020-04-02"]) == 0
    out = json.loads(capsys.readouterr().out.split("\n", 2)[-1])
    export_dir = Path(root) / "exports" / out["export_id"]
    assert cli.main(["--root", root, "replay", "--decision", "2020-04-02T06:00:00Z", "--export-dir", str(export_dir),
                     "--from", "2020-04-01", "--to", "2020-04-02"]) == 0
    assert json.loads(capsys.readouterr().out)["matches_export"] is True


def test_config_hash_changes_with_any_label_parameter() -> None:
    base = ExportConfig()
    other = ExportConfig(label=LabelConfig(threshold_k=0.6))
    assert base.config_hash() != other.config_hash() and base.export_id() != other.export_id()
    assert ExportConfig().config_hash() == base.config_hash()


def test_data_dictionary_in_preregistration_lists_every_feature() -> None:
    text = (Path(__file__).resolve().parents[1] / "docs/research_lab/studien/S8_ORDERFLOW_PROGNOSE_PRAEREGISTRIERUNG.md").read_text()
    missing = [name for name in FEATURE_NAMES if f"| `{name}` |" not in text]
    assert missing == []


# -- Volume Profile and TPO (feature version 1.1.0) -----------------------------------------------------------
def test_nice_width_is_about_ten_basis_points() -> None:
    assert nice_width_e8(30_000 * 10**8) == 20 * 10**8  # 30 USD target -> 20
    assert nice_width_e8(9_000 * 10**8) == 5 * 10**8
    assert nice_width_e8(69_000 * 10**8) == 50 * 10**8
    assert nice_width_e8(1 * 10**8) == 10**6  # floor 0.01 USDT


def test_value_area_rules_by_hand() -> None:
    assert value_area({}) is None
    # POC 12 (40); neighbours 13:30 vs 11:10 -> 13; 70 of 100 reached
    assert value_area({10: 5, 11: 10, 12: 40, 13: 30, 14: 5, 15: 10}) == (12, 12, 13)
    # POC 12 (40); 13:20 vs 11:25 -> 11 (65); 13:20 vs 10:5 -> 13 (85 of 100)
    assert value_area({10: 5, 11: 25, 12: 40, 13: 20, 14: 10}) == (12, 11, 13)
    assert value_area({1: 10, 2: 10}) == (1, 1, 2)  # POC tie -> lower bin
    assert value_area({1: 5, 2: 10, 3: 5}) == (2, 2, 3)  # expansion tie -> upper bin
    assert value_area({1: 10, 4: 1}) == (1, 1, 1)  # one bin already holds 70 %


def test_tpo_histogram_marks_each_bin_once_per_period() -> None:
    start = day_start_ms(date(2020, 1, 1))
    w = 10 * 10**8

    def bar(minute: int, lo: int, hi: int) -> MinuteBar:
        return MinuteBar(start + minute * MINUTE_MS, 1, 1, 1, 0, 1, 0, 0, 0, lo * 10**8, hi * 10**8, hi * 10**8, lo * 10**8,
                         start + minute * MINUTE_MS + 1)

    bars = [MinuteBar.empty(start + m * MINUTE_MS) for m in range(60)]
    bars[0], bars[5] = bar(0, 100, 105), bar(5, 112, 119)  # period 1: bins 10..11
    bars[40] = bar(40, 111, 111)  # period 2: bin 11
    assert tpo_histogram(bars, w) == {10: 1, 11: 2}


def test_profile_volume_matches_bars_and_developing_profile_is_causal(tmp_path: Path) -> None:
    s = _series(tmp_path)
    day1 = s.start[1440]
    profile = s.profiles[day1]
    per_minute: dict[int, int] = {}
    for minute, _, buy, sell in profile.entries:
        per_minute[minute] = per_minute.get(minute, 0) + buy + sell
    assert all(per_minute.get(m, 0) == s.volume[1440 + m] for m in range(1440))
    for m in (0, 37, 900, 1439):
        va = value_area(volume_histogram(profile.entries, m))
        w = profile.width_e8
        assert s.vp_dev[1440 + m] == (va[0] * w + w // 2, va[1] * w, (va[2] + 1) * w)
    row = features_at(s, 1440 + 700)
    names = ("vp_prev_poc_dist", "vp_prev_va_pos", "vp_dev_poc_dist", "tpo_prev_poc_dist", "tpo_prev_va_pos")
    assert all(row.values[FEATURE_NAMES.index(n)] is not None for n in names)
    assert all(features_at(s, i).values[FEATURE_NAMES.index("vp_prev_poc_dist")] is None for i in (0, 1439))  # day 1 has no previous day


def test_reduction_profile_uses_first_trade_width() -> None:
    start = day_start_ms(date(2020, 3, 1))
    ticks = [TradeTick(1, 30_000 * 10**8, 10**8, start + 5, False), TradeTick(2, 30_045 * 10**8, 2 * 10**8, start + 61_000, True)]
    _, _, profile = reduce_trades_with_profile(ticks, start)
    assert profile.width_e8 == 20 * 10**8
    assert profile.entries == ((0, 1500, 10**8, 0), (1, 1502, 0, 2 * 10**8))
