"""Study S2 tooling: exact equality with the live rules, outcome-blind counting, day store, power gate."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import random
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.models.market_data import Trade
from src.orderflow.metrics import OrderflowMetricsEngine
from src.orderflow.observations import OrderflowObservationEngine
from src.research_lab.data.aggtrades import AggTradeDayStore, HoldoutLocked, days_between, fast_available, reduce_day, reduce_day_fast
from src.research_lab.data.store import HoldoutLocked as StoreHoldoutLocked
from src.research_lab.studies import s2_orderflow as s2
from src.research_lab.studies import s2_power
from src.v2_readiness.backfill import BinanceArchiveRef

DAY = datetime(2020, 1, 6, tzinfo=timezone.utc)  # Monday, 2020-W02, first complete training week
DAY_MS = int(DAY.timestamp() * 1000)
FIELDS = ("trade_count", "buy_count", "sell_count", "aggressive_buy_volume", "aggressive_sell_volume", "total_volume", "net_delta",
          "cumulative_delta", "average_trade_size", "largest_trade", "trades_per_second", "volume_per_second", "buy_sell_ratio")


def synthetic_day(seed: int, day_ms: int = DAY_MS, *, density: tuple[int, ...] = (0, 0, 1, 2, 5, 30)) -> tuple[list[list[str]], list[Trade]]:
    rng = random.Random(seed)
    rows: list[list[str]] = []
    trades: list[Trade] = []
    trade_id = seed * 10_000_000
    stamp = day_ms
    for minute in range(s2.MINUTES_PER_DAY):
        for _ in range(rng.choice(density)):
            trade_id += 1
            stamp = max(stamp, day_ms + minute * 60_000) + rng.randint(0, 3_000)
            stamp = min(stamp, day_ms + minute * 60_000 + 59_999)
            qty = f"{rng.randint(1, 500_000) / 1e5:.5f}" if rng.random() < 0.9 else f"{rng.randint(1, 10**8) / 1e8:.8f}"
            price = f"{7000 + rng.randint(-5000, 5000) / 100:.2f}"
            maker = rng.random() < 0.5
            rows.append([str(trade_id), price, qty, "1", "1", str(stamp), "True" if maker else "False", "True"])
            trades.append(Trade("BTCUSDT", float(price), float(qty), datetime.fromtimestamp(stamp / 1000, tz=timezone.utc), trade_id, maker))
    return rows, trades


def csv_text(rows: list[list[str]], header: bool = False) -> str:
    lines = ["agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker,is_best_match"] if header else []
    lines += [",".join(row) for row in rows]
    return "\n".join(lines) + "\n"


def zipped(name: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(name, text)
    return buffer.getvalue()


class FakeArchive:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.calls: list[str] = []

    def add(self, day: date, rows: list[list[str]], *, corrupt: bool = False, header: bool = False) -> None:
        ref = BinanceArchiveRef(day)
        payload = zipped(ref.filename.replace(".zip", ".csv"), csv_text(rows, header))
        digest = "0" * 64 if corrupt else hashlib.sha256(payload).hexdigest()
        self.files[ref.url] = payload
        self.files[ref.checksum_url] = f"{digest}  {ref.filename}\n".encode()

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        return self.files[url]


# -- exact equality with the live engine --------------------------------------------------------------

@pytest.mark.parametrize("seed", [1, 2, 3])
def test_aggregates_reproduce_live_metrics_and_observations_exactly(seed: int) -> None:
    rows, trades = synthetic_day(seed)
    aggregates = s2.aggregate_rows(rows, DAY_MS)
    live = OrderflowMetricsEngine().series(trades, DAY, DAY + timedelta(days=1), 60, symbol="BTCUSDT")
    assert len(aggregates) == len(live) == s2.MINUTES_PER_DAY
    cvd = Decimal(0)
    for item, metric in zip(aggregates, live, strict=True):
        mine = s2.metric_from_aggregate(item, opening_cvd=cvd)
        cvd = mine.cumulative_delta
        for name in FIELDS:
            assert getattr(mine, name) == getattr(metric, name), (name, item.window_start)
    engine = OrderflowObservationEngine()
    expected = [frozenset(obs.kind for obs in engine.evaluate(live[i - 1], live[i])) for i in range(1, len(live))]
    observed = list(s2.observe(aggregates))
    assert observed[0][1] is None  # no previous window
    assert [kinds for _, kinds in observed[1:]] == expected
    assert sum(len(kinds) for kinds in expected) > 0


def test_quantity_parsing_is_exact_and_strict() -> None:
    assert s2.quantity_to_sats("0.00000001") == 1
    assert s2.quantity_to_sats("12.5") == 1_250_000_000
    assert s2.quantity_to_sats("0.10000000") == 10_000_000
    with pytest.raises(ValueError):
        s2.quantity_to_sats("0.000000001")
    with pytest.raises(ValueError):
        s2.quantity_to_sats("-1")
    assert s2.parse_is_buyer_maker("True") is True and s2.parse_is_buyer_maker("false") is False
    with pytest.raises(ValueError):
        s2.parse_is_buyer_maker("maybe")
    with pytest.raises(ValueError, match="outside"):
        s2.aggregate_rows([["1", "1", "1", "1", "1", str(DAY_MS - 1), "True", "True"]], DAY_MS)


def test_rules_read_no_price_and_the_report_carries_none() -> None:
    rows, _ = synthetic_day(4)
    for row in rows:
        row[1] = "PRICE_NOT_READ"  # a non-numeric price must not matter to the count run
    aggregates = s2.aggregate_rows(rows, DAY_MS)
    weeks = s2.count_weeks([(DAY.date(), aggregates)])
    report = s2.build_count_report(weeks, commit="abc", dataset_hash="d" * 64, days=1, missing_days=[])
    dump = json.dumps(report).lower()
    assert "price" not in dump.replace("prices_read", "") and report["prices_read"] is False and report["outcome_blind"] is True
    assert "hit" not in dump


# -- counting rules -----------------------------------------------------------------------------------

def test_greedy_dedup_is_anchored_on_the_kept_case() -> None:
    minute = 60_000
    times = [0, 10 * minute, 29 * minute + 59_999, 30 * minute, 45 * minute, 60 * minute]
    assert s2.greedy_dedup(times) == [0, 30 * minute, 60 * minute]
    with pytest.raises(ValueError):
        s2.greedy_dedup([minute, 0])


def test_iso_weeks_and_section_assignment() -> None:
    assert s2.section_of_week(2020, 1) is None  # 2019-12-30 .. 2020-01-05 straddles the training start
    assert s2.section_of_week(2020, 2) == "train"
    assert s2.section_of_week(2022, 52) is None  # ends on 2023-01-01
    assert s2.section_of_week(2023, 1) == "validation"
    assert s2.section_of_week(2024, 52) == "validation"
    assert s2.section_of_week(2025, 1) is None  # reaches into the holdout
    assert len(s2.calendar_weeks("train")) == 155 and len(s2.calendar_weeks("validation")) == 104
    assert s2.iso_week_of(DAY_MS) == (2020, 2) and s2.week_id(2020, 2) == "2020-W02"


def test_weekly_counts_controls_gaps_and_completeness() -> None:
    days = []
    for offset in range(8):  # 2020-01-06 .. 2020-01-13: one full week plus the next Monday
        day = DAY + timedelta(days=offset)
        rows, _ = synthetic_day(10 + offset, int(day.timestamp() * 1000))
        days.append((day.date(), s2.aggregate_rows(rows, int(day.timestamp() * 1000))))
    del days[5]  # Saturday missing: week incomplete, Sunday's first window has no previous
    weeks = s2.count_weeks(days)
    week = weeks[(2020, 2)]
    assert week.days_present == 6 and not week.complete and week.section == "train"
    assert week.non_evaluable_windows == 2  # first window of the stream and first window after the gap
    # windows are dated by their end: Sunday's last window ends on Monday 00:00 and belongs to the next week
    assert week.evaluable_windows == 6 * s2.MINUTES_PER_DAY - 2 - 1
    for kind in s2.ALL_KINDS:
        assert week.controls(kind) == week.evaluable_windows - week.raw[kind]
        assert week.kept[kind] <= week.raw[kind]
    assert weeks[(2020, 3)].days_present == 1
    summary = s2.section_summary(weeks, "train")
    assert summary["complete_weeks"] == 0 and "2020-W02" in summary["incomplete_weeks"]
    assert s2.weekly_series(weeks, "train", "STRONG_BUYER_ACTIVITY")[0] == (0, 0)


def test_complete_week_enters_the_section_series() -> None:
    days = []
    for offset in range(7):
        day = DAY + timedelta(days=offset)
        rows, _ = synthetic_day(20 + offset, int(day.timestamp() * 1000))
        days.append((day.date(), s2.aggregate_rows(rows, int(day.timestamp() * 1000))))
    weeks = s2.count_weeks(days)
    week = weeks[(2020, 2)]
    assert week.complete
    kind = "RISING_CVD_ACTIVITY"
    assert week.kept[kind] >= 1
    assert s2.weekly_series(weeks, "train", kind)[0] == (week.kept[kind], week.controls(kind))
    report = s2.build_count_report(weeks, commit="c", dataset_hash="d" * 64, days=7, missing_days=[])
    text = s2.render_count_markdown(report)
    assert "keine Preise" in text and report["sections"]["train"]["kinds"][kind]["usable_weeks"] == 1
    assert report["sections"]["train"]["kinds"][kind]["minimum_met"] is False  # one week is below 26


def test_holdout_days_are_refused_by_the_count() -> None:
    holdout = datetime(2025, 1, 6, tzinfo=timezone.utc)
    rows, _ = synthetic_day(30, int(holdout.timestamp() * 1000))
    with pytest.raises(PermissionError):
        list(s2.count_weeks([(holdout.date(), s2.aggregate_rows(rows, int(holdout.timestamp() * 1000)))]))


# -- day store ----------------------------------------------------------------------------------------

def test_store_fetches_verifies_reduces_and_reloads(tmp_path) -> None:
    rows, _ = synthetic_day(40)
    fake = FakeArchive()
    fake.add(DAY.date(), rows, header=True)
    store = AggTradeDayStore(tmp_path, fake)
    entry = store.fetch(DAY.date(), fast=False)
    assert entry["rows"] == len(rows) and entry["reduction"] == "reference"
    assert store.agg_path(DAY.date()).exists() and store.px_path(DAY.date()).exists() and not store.raw_path(DAY.date()).exists()
    assert "price" not in store.agg_path(DAY.date()).read_text().splitlines()[0]
    loaded = store.load_aggregates(DAY.date())
    assert loaded == s2.aggregate_rows(rows, DAY_MS)
    store.fetch(DAY.date())  # cached: no new download
    assert len(fake.calls) == 2
    assert store.present_days() == [DAY.date()]
    assert store.dataset_hash([DAY.date()]) == store.dataset_hash([DAY.date()])
    store.agg_path(DAY.date()).write_text("tampered")
    with pytest.raises(ValueError, match="changed on disk"):
        store.load_aggregates(DAY.date())


def test_store_refuses_bad_checksum_and_holdout(tmp_path) -> None:
    rows, _ = synthetic_day(41)
    fake = FakeArchive()
    fake.add(DAY.date(), rows, corrupt=True)
    store = AggTradeDayStore(tmp_path, fake)
    with pytest.raises(ValueError, match="checksum mismatch"):
        store.fetch(DAY.date(), fast=False)
    assert not store.agg_path(DAY.date()).exists()
    with pytest.raises(StoreHoldoutLocked):
        store.fetch(date(2025, 1, 1))
    with pytest.raises(HoldoutLocked):
        store.load_aggregates(date(2026, 6, 1))
    assert all("2025" not in url for url in fake.calls)
    assert days_between(date(2024, 12, 30), date(2025, 1, 1)) == [date(2024, 12, 30), date(2024, 12, 31), date(2025, 1, 1)]


def test_fast_reduction_matches_the_reference() -> None:
    if not fast_available():
        pytest.skip("numpy/pandas not installed")
    rows, _ = synthetic_day(42)
    payload = zipped("x.csv", csv_text(rows, header=True))
    assert reduce_day_fast(payload, DAY.date()) == reduce_day(payload, DAY.date())
    empty = zipped("x.csv", "")
    aggregates, prices, count = reduce_day_fast(empty, DAY.date())
    assert count == 0 and all(item.trade_count == 0 for item in aggregates) and prices == [None] * s2.MINUTES_PER_DAY


def test_fetch_with_verify_compares_both_paths(tmp_path) -> None:
    if not fast_available():
        pytest.skip("numpy/pandas not installed")
    rows, _ = synthetic_day(43)
    fake = FakeArchive()
    fake.add(DAY.date(), rows)
    entry = AggTradeDayStore(tmp_path, fake).fetch(DAY.date(), verify=True)
    assert entry["reduction"] == "fast" and entry["verified_both"] is True


# -- power gate ---------------------------------------------------------------------------------------

def test_block_plan_and_standardized_delta() -> None:
    assert s2_power.block_plan(155) == (39, 3) and s2_power.block_plan(104) == (26, 4) and s2_power.block_plan(8) == (2, 4)
    with pytest.raises(ValueError):
        s2_power.block_plan(3)
    delta = s2_power.standardized_delta([10, 0, 20], [8, 0, 10], [100, 50, 100], [50, 10, 50])
    assert delta == pytest.approx(((8 - 10 * 0.5) + (10 - 20 * 0.5)) / 30)
    assert s2_power.standardized_delta([0], [0], [10], [5]) is None
    assert len(s2_power.scenarios()) == 9 and s2_power.ALPHA_SECTION == pytest.approx(0.05 / 18)


def test_power_simulation_is_deterministic_and_sane() -> None:
    pytest.importorskip("numpy")
    weeks = 30
    strong = [(400, 8_000)] * weeks
    a = s2_power.simulate_power(strong, s2_power.Scenario(0.5, 0.0), replications=24, b=999)
    b = s2_power.simulate_power(strong, s2_power.Scenario(0.5, 0.0), replications=24, b=999)
    assert a == b and a.power >= 0.9 and a.joint_rate <= a.power
    null = s2_power.simulate_power(strong, s2_power.Scenario(0.5, 0.0, true_delta=0.0), replications=60, b=999)
    assert null.power <= 0.1
    sparse = [(2, 500)] * 20 + [(0, 0)] * 10
    weak = s2_power.simulate_power(sparse, s2_power.Scenario(0.5, 0.10), replications=24, b=999)
    assert weak.power < a.power
    assert s2_power.simulate_power([(0, 0)] * weeks, s2_power.Scenario(0.5, 0.0), replications=5, b=99).evaluable == 0


def test_power_report_and_markdown() -> None:
    pytest.importorskip("numpy")
    count_report = {"commit": "c" * 40, "dataset_hash": "d" * 64, "sections": {"train": {"kinds": {k: {"directional": k in s2.DIRECTIONAL} for k in s2.ALL_KINDS}}}}
    kind = "STRONG_BUYER_ACTIVITY"
    results = {section: {kind: [s2_power.simulate_power([(400, 8_000)] * 30, scenario, replications=4, b=199) for scenario in s2_power.scenarios()[:2]]}
               for section in ("train", "validation")}
    report = s2_power.build_power_report(results, count_report=count_report, commit="e" * 40, replications=4, b=199, seed=1, created="now")
    assert report["sections"]["train"][kind]["min_power"] is not None and report["outcome_blind"] is True
    text = s2_power.render_power_markdown(report)
    assert "Gate" in text and kind in text


def test_script_loads_and_rebuilds_weekly_series_from_a_report() -> None:
    spec = importlib.util.spec_from_file_location("s2_script", Path("scripts/research_lab_s2.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.DEFAULT_LAST < date(2025, 1, 1) and module.DEFAULT_FIRST.isoweekday() == 1
    days = []
    for offset in range(7):
        day = DAY + timedelta(days=offset)
        rows, _ = synthetic_day(50 + offset, int(day.timestamp() * 1000))
        days.append((day.date(), s2.aggregate_rows(rows, int(day.timestamp() * 1000))))
    weeks = s2.count_weeks(days)
    report = s2.build_count_report(weeks, commit="c", dataset_hash="d" * 64, days=7, missing_days=[])
    by_key = {tuple(int(part) for part in row["week"].split("-W")): row for row in report["weeks"]}
    kind = "FALLING_CVD_ACTIVITY"
    assert module._series_from_report(by_key, "train", kind) == s2.weekly_series(weeks, "train", kind)


def test_fetch_with_workers_records_every_day_once_and_resumes(tmp_path) -> None:
    import importlib.util

    from src.research_lab.data.aggtrades import DirectoryFetcher

    spec = importlib.util.spec_from_file_location("s2_script_workers", Path("scripts/research_lab_s2.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    archive_dir = tmp_path / "archives"
    archive_dir.mkdir()
    days = [DAY.date() + timedelta(days=i) for i in range(5)]
    for i, day in enumerate(days):
        rows, _ = synthetic_day(60 + i, int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000))
        ref = BinanceArchiveRef(day)
        payload = zipped(ref.filename.replace(".zip", ".csv"), csv_text(rows))
        (archive_dir / ref.filename).write_bytes(payload)
        (archive_dir / (ref.filename + ".CHECKSUM")).write_text(f"{hashlib.sha256(payload).hexdigest()}  {ref.filename}\n")
    store = AggTradeDayStore(tmp_path / "store", DirectoryFetcher(archive_dir))
    store.fetch(days[0], fast=False)  # already reduced: must be skipped
    (archive_dir / BinanceArchiveRef(days[0]).filename).unlink()  # a re-download would now fail
    assert module.fetch(store, days[0], days[-1], verify_days=1, keep_raw=False, workers=2) == 0
    assert store.present_days() == days
    assert store.cached(days[0]) is not None and store.cached(days[0] + timedelta(days=30)) is None
    assert store.manifest()[days[1].isoformat()]["rows"] > 0
    # a day without archive is reported, the others still land
    assert module.fetch(store, days[0], days[-1] + timedelta(days=1), verify_days=0, keep_raw=False, workers=2) == 1
    assert store.present_days() == days


def test_power_with_workers_matches_the_sequential_run(tmp_path) -> None:
    pytest.importorskip("numpy")
    spec = importlib.util.spec_from_file_location("s2_script_power_workers", Path("scripts/research_lab_s2.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    days = []
    for offset in range(14):
        day = DAY + timedelta(days=offset)
        rows, _ = synthetic_day(70 + offset, int(day.timestamp() * 1000))
        days.append((day.date(), s2.aggregate_rows(rows, int(day.timestamp() * 1000))))
    report = s2.build_count_report(s2.count_weeks(days), commit="c" * 40, dataset_hash="d" * 64, days=14, missing_days=[])
    count_file = tmp_path / "s2_count_test.json"
    count_file.write_text(json.dumps(report))
    kinds = ["STRONG_BUYER_ACTIVITY", "FALLING_CVD_ACTIVITY"]
    outs = {}
    for label, workers in (("one", 1), ("two", 2)):
        out_dir = tmp_path / label
        assert module.power(count_file, out_dir, replications=4, b=199, seed=7, kinds=kinds, workers=workers) == 0
        written = list(out_dir.glob("s2_power_*.json"))
        assert len(written) == 1
        outs[label] = json.loads(written[0].read_text())
    assert outs["one"]["sections"] == outs["two"]["sections"]
    assert outs["one"]["gate"] == outs["two"]["gate"] and outs["two"]["registered_parameters"] is False
    for section in ("train", "validation"):
        assert set(outs["two"]["sections"][section]) == set(kinds)
