"""Review regressions for S8, with synthetic archives and no outcome research."""

import math
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.research_lab.orderflow_ml import __main__ as cli
from src.research_lab.orderflow_ml.export import ExportConfig, replay, run_export
from src.research_lab.orderflow_ml.features import BarSeries
from src.research_lab.orderflow_ml.labels import LabelConfig, label_at
from src.research_lab.orderflow_ml.store import MinuteBarStore
from tests.test_research_lab_s8_export import filled_store


DAY = date(2020, 2, 2)


@pytest.mark.parametrize("quality", ["id_gaps", "time_regressions"])
def test_bad_source_day_cannot_silently_become_training_rows(tmp_path, quality):
    store = filled_store(tmp_path, [DAY])
    entry = store.manifest()[DAY.isoformat()]
    entry["quality"][quality] = 1
    store.record(DAY, entry)
    with pytest.raises(ValueError, match="quality"):
        run_export(store, ExportConfig(DAY, DAY), tmp_path / "out")
    assert not list((tmp_path / "out").rglob("split_manifest.json"))


def test_incompatible_bar_version_is_not_accepted_as_current_data(tmp_path):
    store = filled_store(tmp_path, [DAY])
    entry = store.manifest()[DAY.isoformat()]
    entry["bar_version"] = "0.0.0"
    store.record(DAY, entry)
    with pytest.raises(ValueError, match="version"):
        store.load(DAY)


def test_dataset_hash_binds_quality_and_source_semantics(tmp_path):
    store = filled_store(tmp_path, [DAY])
    before = store.dataset_hash([DAY])
    entry = store.manifest()[DAY.isoformat()]
    entry["quality"]["id_gaps"] = 1
    store.record(DAY, entry)
    assert store.dataset_hash([DAY]) != before


@pytest.mark.parametrize("field", ["threshold_k", "cost_floor"])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_label_parameters_are_not_valid_neutral_generators(field, value):
    with pytest.raises(ValueError, match="configuration"):
        LabelConfig(**{field: value})


@pytest.mark.parametrize("kwargs", [{"horizon_min": 1.5}, {"horizon_min": True}, {"stale_limit_ms": 0.5}])
def test_label_time_intervals_require_integer_units(kwargs):
    with pytest.raises(ValueError, match="configuration"):
        LabelConfig(**kwargs)


def test_nonfinite_input_volatility_does_not_produce_a_neutral_label(tmp_path):
    store = filled_store(tmp_path, [DAY])
    result = label_at(BarSeries(store.load(DAY)), 700, math.nan, LabelConfig())
    assert result.status == "no_volatility" and result.label is None


def test_sealed_export_is_never_overwritten_on_repeat(tmp_path):
    store = filled_store(tmp_path, [DAY])
    cfg = ExportConfig(DAY, DAY)
    run_export(store, cfg, tmp_path / "out")
    path = tmp_path / "out" / cfg.export_id() / "split_manifest.json"
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        run_export(store, cfg, tmp_path / "out", code_version="different-code")
    assert path.read_bytes() == before


def test_export_rejects_a_symbol_that_does_not_match_its_source(tmp_path):
    store = MinuteBarStore(tmp_path / "empty-btc-store")
    with pytest.raises(ValueError, match="symbol"):
        run_export(store, ExportConfig(DAY, DAY, symbol="ETHUSDT"), tmp_path / "out")


def test_replay_does_not_expose_a_target_price_purged_at_the_split(tmp_path):
    days = [date(2022, 12, 31), date(2023, 1, 1)]
    store = filled_store(tmp_path, days)
    decision = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    result = replay(store, decision, ExportConfig(days[0], days[-1]))
    assert result["label"]["status"] == "purged_section_end"
    assert result["target_bar"] is None


def test_replay_requires_an_explicit_timezone_instead_of_using_the_host_zone(tmp_path):
    with pytest.raises(ValueError, match="timezone"):
        cli.main(["--root", str(tmp_path), "replay", "--decision", "2020-02-02T12:00:00"])


def test_cli_records_the_source_checkout_version_when_called_from_elsewhere(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    expected = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    monkeypatch.chdir(tmp_path)
    assert cli._code_version() == expected
