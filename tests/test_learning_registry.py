"""Learning loop L1: model register (hash chain, announce-before-test, holdout, budget, one evaluation, approval)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.research_lab.learning import __main__ as cli
from src.research_lab.learning import registry as reg
from src.research_lab.learning.registry import ELIGIBLE, NO_VERDICT, REJECTED, LearningError


class ModelRegister(reg.ModelRegister):
    """Test register whose clock stands at the date of the entry being written (the real-clock
    check itself is tested with reg.ModelRegister below)."""

    def _append(self, body):
        self.clock = lambda: reg._time(body["at"])
        return super()._append(body)

T0 = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)  # Monday
RULES = {"config_id": "s8-catboost-1", "horizon_minutes": 5, "min_window_days": 14, "min_minutes": 10_000,
         "min_effect": 0.002, "ci_level": 0.995, "per_week": 1, "per_quarter": 12,
         "prospective_start": T0.isoformat(), "metric": "log_loss", "approvers": ["Uzi"]}
GOOD = {"n_minutes": 18_000, "days": 14, "delta": 0.004, "ci_low": 0.001, "ci_high": 0.007, "ci_level": 0.995,
        "calibration_ok": True, "quality_ok": True}


def _register(tmp_path) -> ModelRegister:
    register = ModelRegister(tmp_path / "learn.jsonl")
    register.register_family("S8-L1", RULES, at=T0 - timedelta(days=1))
    register.register_baseline("S8-L1", "base-rate", model_hash="b" * 64, at=T0 - timedelta(days=1))
    return register


def _challenger(register: ModelRegister, model_id: str, *, at: datetime, **override):
    args = dict(at=at, trained_until=at - timedelta(minutes=10), window_start=at, window_end=at + timedelta(days=14),
                data_sources=[{"kind": "archive", "from": "2020-01-01T00:00:00Z", "to": "2024-12-31T23:59:00Z"},
                              {"kind": "live", "from": T0.isoformat(), "to": (at - timedelta(minutes=10)).isoformat()}],
                config_id="s8-catboost-1", code_commit="abc123", feature_version="1.1.0", label_version="1.0.0",
                data_hash="d" * 64, model_hash="m" * 64)
    args.update(override)
    return register.register_challenger("S8-L1", model_id, **args)


def test_full_cycle_promote_and_rollback(tmp_path) -> None:
    register = _register(tmp_path)
    at = T0 + timedelta(days=3)
    _challenger(register, "c1", at=at)
    assert register.record_evaluation("c1", GOOD, at=at + timedelta(days=14))["verdict"] == ELIGIBLE
    register.promote("c1", approved_by="Uzi", at=at + timedelta(days=14, hours=1))
    assert register.champion("S8-L1") == "c1"
    register.rollback("S8-L1", to_model_id="base-rate", reason="worse than base rate live", at=at + timedelta(days=20))
    assert register.champion("S8-L1") == "base-rate"


def test_edited_old_line_breaks_the_chain(tmp_path) -> None:
    register = _register(tmp_path)
    lines = register.path.read_text().splitlines()
    first = json.loads(lines[0])
    first["rules"]["min_effect"] = 0.0
    register.path.write_text("\n".join([json.dumps(first, sort_keys=True), *lines[1:]]) + "\n")
    with pytest.raises(LearningError, match="hash chain"):
        register.state()
    assert cli.main(["status", "--register", str(register.path)]) == 2


def test_deleted_line_breaks_the_chain(tmp_path) -> None:
    register = _register(tmp_path)
    _challenger(register, "c1", at=T0 + timedelta(days=1))
    lines = register.path.read_text().splitlines()
    register.path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    with pytest.raises(LearningError, match="hash chain"):
        register.events()


def test_rules_are_fixed_once(tmp_path) -> None:
    register = _register(tmp_path)
    with pytest.raises(LearningError, match="already exists"):
        register.register_family("S8-L1", {**RULES, "min_effect": 0.0001}, at=T0)
    with pytest.raises(LearningError, match="incomplete"):
        ModelRegister(tmp_path / "x.jsonl").register_family("F", {"config_id": "x"}, at=T0)


def test_window_must_start_after_announcement(tmp_path) -> None:
    register = _register(tmp_path)
    at = T0 + timedelta(days=3)
    with pytest.raises(LearningError, match="announce first"):
        _challenger(register, "c1", at=at, window_start=at - timedelta(hours=1))


def test_training_must_end_one_horizon_before_window(tmp_path) -> None:
    register = _register(tmp_path)
    at = T0 + timedelta(days=3)
    with pytest.raises(LearningError, match="one horizon"):
        _challenger(register, "c1", at=at, trained_until=at - timedelta(minutes=4))


def test_data_source_past_cutoff_is_refused(tmp_path) -> None:
    register = _register(tmp_path)
    at = T0 + timedelta(days=3)
    with pytest.raises(LearningError, match="past the training cut-off"):
        _challenger(register, "c1", at=at, data_sources=[{"kind": "live", "from": T0.isoformat(), "to": at.isoformat()}])


@pytest.mark.parametrize("source,message", [
    ({"kind": "archive", "from": "2024-06-01T00:00:00Z", "to": "2025-01-01T00:00:00Z"}, "locked holdout"),
    ({"kind": "archive", "from": "2025-03-01T00:00:00Z", "to": "2025-03-02T00:00:00Z"}, "locked holdout"),
    ({"kind": "live", "from": "2026-10-01T00:00:00Z", "to": "2026-11-03T00:00:00Z"}, "holdout gap"),
    ({"kind": "synthetic", "from": "2020-01-01T00:00:00Z", "to": "2020-01-02T00:00:00Z"}, "unknown data source"),
])
def test_holdout_and_closed_gap_are_never_training_data(tmp_path, source, message) -> None:
    register = _register(tmp_path)
    with pytest.raises(LearningError, match=message):
        _challenger(register, "c1", at=T0 + timedelta(days=3), data_sources=[source])


def test_other_config_is_a_new_study(tmp_path) -> None:
    register = _register(tmp_path)
    with pytest.raises(LearningError, match="new study"):
        _challenger(register, "c1", at=T0 + timedelta(days=3), config_id="s8-catboost-depth6")


def test_budget_counts_every_announced_challenger(tmp_path) -> None:
    register = _register(tmp_path)
    _challenger(register, "c1", at=T0 + timedelta(days=1))
    with pytest.raises(LearningError, match="weekly"):
        _challenger(register, "c2", at=T0 + timedelta(days=2))
    _challenger(register, "c2", at=T0 + timedelta(days=7))  # next ISO week
    assert register.record_evaluation("c1", {**GOOD, "delta": -0.01, "ci_low": -0.02}, at=T0 + timedelta(days=16))["verdict"] == REJECTED
    assert sorted(register.state()["models"]) == ["c1", "c2"]  # the rejected one stays counted


def test_quarter_budget(tmp_path) -> None:
    rules = {**RULES, "per_week": 5, "per_quarter": 2}
    register = ModelRegister(tmp_path / "q.jsonl")
    register.register_family("S8-L1", rules, at=T0 - timedelta(days=1))
    register.register_baseline("S8-L1", "base-rate", model_hash="b", at=T0)
    _challenger(register, "c1", at=T0 + timedelta(hours=1))
    _challenger(register, "c2", at=T0 + timedelta(hours=2))
    with pytest.raises(LearningError, match="quarterly"):
        _challenger(register, "c3", at=T0 + timedelta(hours=3))


def test_evaluation_only_once_and_only_after_window(tmp_path) -> None:
    register = _register(tmp_path)
    at = T0 + timedelta(days=3)
    _challenger(register, "c1", at=at)
    with pytest.raises(LearningError, match="before the end"):
        register.record_evaluation("c1", GOOD, at=at + timedelta(days=13))
    register.record_evaluation("c1", GOOD, at=at + timedelta(days=14))
    with pytest.raises(LearningError, match="used once"):
        register.record_evaluation("c1", GOOD, at=at + timedelta(days=15))


@pytest.mark.parametrize("change,verdict", [
    ({}, ELIGIBLE),
    ({"delta": 0.001}, REJECTED),             # below smallest effect
    ({"ci_low": 0.0}, REJECTED),              # interval touches zero
    ({"calibration_ok": False}, REJECTED),
    ({"n_minutes": 9_999}, NO_VERDICT),
    ({"days": 13}, NO_VERDICT),
    ({"quality_ok": False}, NO_VERDICT),
    ({"ci_level": 0.95}, NO_VERDICT),         # interval not corrected for the budget
])
def test_verdict_is_computed_from_registered_rules(change, verdict) -> None:
    assert ModelRegister.verdict(RULES, {**GOOD, **change})[0] == verdict


def test_promotion_needs_eligible_verdict_and_approver(tmp_path) -> None:
    register = _register(tmp_path)
    at = T0 + timedelta(days=3)
    _challenger(register, "c1", at=at)
    with pytest.raises(LearningError, match="ELIGIBLE"):
        register.promote("c1", approved_by="Uzi", at=at + timedelta(days=1))
    _challenger(register, "c2", at=at + timedelta(days=7))
    register.record_evaluation("c1", {**GOOD, "delta": 0.001}, at=at + timedelta(days=14))
    with pytest.raises(LearningError, match="ELIGIBLE"):
        register.promote("c1", approved_by="Uzi", at=at + timedelta(days=15))
    register.record_evaluation("c2", GOOD, at=at + timedelta(days=21))
    for name in (" ", "x", "Claude"):
        with pytest.raises(LearningError, match="approver"):
            register.promote("c2", approved_by=name, at=at + timedelta(days=22))
    register.promote("c2", approved_by="Uzi", at=at + timedelta(days=22))
    with pytest.raises(LearningError, match="already champion"):
        register.promote("c2", approved_by="Uzi", at=at + timedelta(days=23))


def test_stale_comparison_after_champion_change_is_refused(tmp_path) -> None:
    register = _register(tmp_path)
    at = T0 + timedelta(days=3)
    _challenger(register, "c1", at=at)
    _challenger(register, "c2", at=at + timedelta(days=7))
    register.record_evaluation("c1", GOOD, at=at + timedelta(days=14))
    register.promote("c1", approved_by="Uzi", at=at + timedelta(days=15))
    register.record_evaluation("c2", GOOD, at=at + timedelta(days=21))
    with pytest.raises(LearningError, match="stale"):
        register.promote("c2", approved_by="Uzi", at=at + timedelta(days=22))


def test_rollback_only_to_an_earlier_champion(tmp_path) -> None:
    register = _register(tmp_path)
    at = T0 + timedelta(days=3)
    _challenger(register, "c1", at=at)
    with pytest.raises(LearningError, match="never an earlier champion"):
        register.rollback("S8-L1", to_model_id="c1", reason="x", at=at)
    with pytest.raises(LearningError, match="never an earlier champion"):
        register.rollback("S8-L1", to_model_id="base-rate", reason="x", at=at)  # it is the current one


def test_challenger_needs_baseline_and_hashes(tmp_path) -> None:
    register = ModelRegister(tmp_path / "n.jsonl")
    register.register_family("S8-L1", RULES, at=T0 - timedelta(days=1))
    with pytest.raises(LearningError, match="baseline"):
        _challenger(register, "c1", at=T0 + timedelta(days=1))
    register.register_baseline("S8-L1", "base-rate", model_hash="b", at=T0)
    with pytest.raises(LearningError, match="model_hash"):
        _challenger(register, "c1", at=T0 + timedelta(days=1), model_hash="")
    with pytest.raises(LearningError, match="already exists"):
        _challenger(register, "base-rate", at=T0 + timedelta(days=1))


def test_time_without_zone_is_refused(tmp_path) -> None:
    with pytest.raises(LearningError, match="zone"):
        ModelRegister(tmp_path / "z.jsonl").register_family("F", {**RULES, "prospective_start": "2026-11-02T00:00:00"}, at=T0)


def test_status_cli_reads_without_writing(tmp_path, capsys) -> None:
    register = _register(tmp_path)
    before = register.path.read_bytes()
    assert cli.main(["status", "--register", str(register.path)]) == 0
    assert json.loads(capsys.readouterr().out)["families"]["S8-L1"]["champion"] == "base-rate"
    assert register.path.read_bytes() == before


def test_rollback_cannot_reactivate_a_demoted_model(tmp_path) -> None:
    register = _register(tmp_path)
    at = T0 + timedelta(days=3)
    _challenger(register, "c1", at=at)
    register.record_evaluation("c1", GOOD, at=at + timedelta(days=14))
    register.promote("c1", approved_by="Uzi", at=at + timedelta(days=14))
    register.rollback("S8-L1", to_model_id="base-rate", reason="live worse", at=at + timedelta(days=15))
    with pytest.raises(LearningError, match="never an earlier champion"):
        register.rollback("S8-L1", to_model_id="c1", reason="try again", at=at + timedelta(days=16))


def test_back_dated_entry_is_refused(tmp_path) -> None:
    register = _register(tmp_path)
    _challenger(register, "c1", at=T0 + timedelta(days=8))
    with pytest.raises(LearningError, match="backwards"):
        _challenger(register, "c2", at=T0 + timedelta(days=1))


def test_string_flags_are_refused(tmp_path) -> None:
    register = _register(tmp_path)
    at = T0 + timedelta(days=3)
    _challenger(register, "c1", at=at)
    with pytest.raises(LearningError, match="true or false"):
        register.record_evaluation("c1", {**GOOD, "quality_ok": "false"}, at=at + timedelta(days=14))


def test_entry_must_match_the_real_clock(tmp_path) -> None:
    now = T0 - timedelta(days=1)
    register = reg.ModelRegister(tmp_path / "c.jsonl", clock=lambda: now)
    register.register_family("S8-L1", RULES, at=now + timedelta(minutes=5))
    for wrong in (now - timedelta(days=4), now + timedelta(days=365)):
        with pytest.raises(LearningError, match="real clock"):
            register.register_baseline("S8-L1", "base-rate", model_hash="b", at=wrong)


@pytest.mark.parametrize("change", [
    {"delta": float("nan"), "ci_low": float("nan"), "days": float("nan"), "ci_level": float("nan")},
    {"delta": "1e9"}, {"ci_low": float("inf")}, {"n_minutes": float("inf")}, {"days": True},
])
def test_non_finite_or_non_numeric_metrics_are_refused(change) -> None:
    with pytest.raises(LearningError, match="finite number"):
        ModelRegister.verdict(RULES, {**GOOD, **change})


def test_interval_must_contain_the_estimate() -> None:
    with pytest.raises(LearningError, match="contain"):
        ModelRegister.verdict(RULES, {**GOOD, "ci_low": 1e9, "ci_high": -5})


@pytest.mark.parametrize("change", [{"min_effect": float("nan")}, {"ci_level": float("nan")}, {"min_effect": "0.1"},
                                    {"horizon_minutes": 5.9}, {"per_week": True}, {"approvers": []}, {"approvers": "Uzi"}])
def test_bad_rules_are_refused(tmp_path, change) -> None:
    with pytest.raises(LearningError):
        ModelRegister(tmp_path / "r.jsonl").register_family("F", {**RULES, **change}, at=T0 - timedelta(days=1))


def test_budget_counts_across_families_with_the_same_config(tmp_path) -> None:
    register = _register(tmp_path)
    register.register_family("S8-L1b", RULES, at=T0 - timedelta(days=1))
    register.register_baseline("S8-L1b", "base-rate-b", model_hash="b", at=T0 - timedelta(days=1))
    _challenger(register, "c1", at=T0 + timedelta(days=1))
    with pytest.raises(LearningError, match="weekly"):
        register.register_challenger("S8-L1b", "c2", at=T0 + timedelta(days=2), trained_until=T0 + timedelta(days=1),
                                     window_start=T0 + timedelta(days=2), window_end=T0 + timedelta(days=16),
                                     data_sources=[{"kind": "live", "from": T0.isoformat(), "to": (T0 + timedelta(days=1)).isoformat()}],
                                     config_id="s8-catboost-1", code_commit="a", feature_version="1", label_version="1",
                                     data_hash="d", model_hash="m")


def test_model_ids_are_unique_over_all_families(tmp_path) -> None:
    register = _register(tmp_path)
    register.register_family("F3", {**RULES, "config_id": "other"}, at=T0 - timedelta(days=1))
    with pytest.raises(LearningError, match="already exists"):
        register.register_baseline("F3", "base-rate", model_hash="b", at=T0 - timedelta(days=1))


def test_rollback_cannot_switch_back_and_forth(tmp_path) -> None:
    register = _register(tmp_path)
    at = T0 + timedelta(days=3)
    _challenger(register, "c1", at=at)
    _challenger(register, "c2", at=at + timedelta(days=7))
    register.record_evaluation("c1", GOOD, at=at + timedelta(days=14))
    register.promote("c1", approved_by="Uzi", at=at + timedelta(days=14))
    _challenger(register, "c3", at=at + timedelta(days=14))
    register.record_evaluation("c3", GOOD, at=at + timedelta(days=28))
    register.promote("c3", approved_by="Uzi", at=at + timedelta(days=28))
    register.rollback("S8-L1", to_model_id="c1", reason="live worse", at=at + timedelta(days=29))
    register.rollback("S8-L1", to_model_id="base-rate", reason="live worse", at=at + timedelta(days=30))
    with pytest.raises(LearningError, match="never an earlier champion"):
        register.rollback("S8-L1", to_model_id="c1", reason="again", at=at + timedelta(days=31))


def test_overdue_challengers_are_listed(tmp_path) -> None:
    register = _register(tmp_path)
    at = T0 + timedelta(days=3)
    _challenger(register, "c1", at=at)
    assert register.overdue(at + timedelta(days=13)) == []
    assert register.overdue(at + timedelta(days=14)) == ["c1"]


def test_reported_days_cannot_exceed_the_window(tmp_path) -> None:
    register = _register(tmp_path)
    at = T0 + timedelta(days=3)
    _challenger(register, "c1", at=at)
    with pytest.raises(LearningError, match="more days"):
        register.record_evaluation("c1", {**GOOD, "days": 30}, at=at + timedelta(days=14))


def test_broken_json_and_bad_source_raise_learning_error(tmp_path) -> None:
    register = _register(tmp_path)
    with pytest.raises(LearningError, match="kind, from and to"):
        _challenger(register, "c1", at=T0 + timedelta(days=3), data_sources=[{"kind": "live"}])
    with register.path.open("a") as handle:
        handle.write("{not json\n")
    with pytest.raises(LearningError, match="JSON"):
        register.events()
    assert cli.main(["status", "--register", str(register.path)]) == 2


def test_head_names_the_last_entry(tmp_path) -> None:
    register = _register(tmp_path)
    assert register.head() == register.events()[-1]["hash"]
