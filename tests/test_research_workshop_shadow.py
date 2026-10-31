"""F7 shadow operation: own journal that never counts, window used once, random strategies almost never pass."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from src.research_lab.learning.registry import ELIGIBLE, LearningError, ModelRegister
from src.research_lab.workshop import shadow
from src.research_lab.workshop.shadow import ShadowError, ShadowJournal

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
HORIZON = 1440


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.now = moment

    def __call__(self) -> datetime:
        return self.now


def _setup(tmp_path: Path):
    clock = Clock(T0)
    register = ModelRegister(tmp_path / "register.jsonl", clock=clock)
    entry = shadow.start(register, "S12", model_id="S12-v1", variant_hash="abc123", code_commit="c0ffee",
                         study_version="S12/1.0", cost_rule="kosten/1", min_trades=30, min_effect=0.05,
                         horizon_minutes=HORIZON, at=T0)
    journal = ShadowJournal("S12", "S12-v1", folder=tmp_path / "shadow", clock=clock)
    return clock, register, journal, entry


def _trade(clock, register, journal, n: int, net_r: float, **extra) -> None:
    decided = clock.now
    journal.record_plan(register, f"p{n:03d}", decided_at=decided, direction="LONG", entry=100.0, stop=99.0,
                        targets=[102.0], inputs_hash="h")
    clock.now = decided + timedelta(hours=2)
    journal.record_outcome(f"p{n:03d}", closed_at=clock.now, net_r=net_r, gross_r=net_r + 0.1, cost_r=0.1,
                           exit_reason="TP1", **extra)
    clock.now = decided + timedelta(hours=20)


def test_start_registers_family_baseline_and_window(tmp_path: Path) -> None:
    _, register, _, entry = _setup(tmp_path)
    state = register.state()
    family = state["families"]["S12-schatten"]
    assert family["champion"] == shadow.BASELINE and family["rules"]["approvers"] == ["Uzi"]
    assert family["rules"]["min_window_days"] == 30 and family["rules"]["ci_level"] == 0.995
    assert entry["window_start"] == "2026-11-02T12:00:00Z" and entry["window_end"] == "2026-12-02T12:00:00Z"
    with pytest.raises(LearningError):  # one family per study, rules never change
        shadow.start(register, "S12", model_id="S12-v2", variant_hash="abc123", code_commit="c", study_version="v",
                     cost_rule="k", min_trades=30, min_effect=0.05, horizon_minutes=HORIZON, at=T0)


def test_plans_only_inside_the_window_and_in_real_time(tmp_path: Path) -> None:
    clock, register, journal, _ = _setup(tmp_path)
    with pytest.raises(ShadowError, match="außerhalb"):
        journal.record_plan(register, "early", decided_at=T0, direction="LONG", entry=1, stop=0.9, targets=[1.2],
                            inputs_hash="h")
    clock.now = T0 + timedelta(days=2)
    with pytest.raises(ShadowError, match="Entscheidungszeit"):
        journal.record_plan(register, "late", decided_at=clock.now - timedelta(hours=1), direction="LONG", entry=1,
                            stop=0.9, targets=[1.2], inputs_hash="h")
    _trade(clock, register, journal, 1, 0.5)
    with pytest.raises(ShadowError, match="schon ein Ergebnis"):
        journal.record_outcome("p001", closed_at=clock.now, net_r=9.0, gross_r=9.0, cost_r=0.0, exit_reason="x")
    with pytest.raises(ShadowError, match="endliche"):
        journal.record_plan(register, "nan", decided_at=clock.now, direction="LONG", entry=float("nan"), stop=1,
                            targets=[], inputs_hash="h")


def test_shadow_never_counts_and_chain_detects_edits(tmp_path: Path) -> None:
    clock, register, journal, _ = _setup(tmp_path)
    clock.now = T0 + timedelta(days=2)
    _trade(clock, register, journal, 1, 0.5)
    events = journal.events()
    assert all(e["counts_in_net_r"] is False and e["journal"] == "schatten:S12" for e in events)
    assert journal.path.parent.name == "shadow" and "plan_journal" not in journal.path.name
    lines = journal.path.read_text().splitlines()
    edited = json.loads(lines[1])
    edited["net_r"] = 5.0
    journal.path.write_text("\n".join([lines[0], json.dumps(edited)]) + "\n")
    with pytest.raises(ShadowError, match="Hash-Kette"):
        journal.events()


def test_window_is_evaluated_once_and_promotion_needs_uzi(tmp_path: Path) -> None:
    clock, register, journal, _ = _setup(tmp_path)
    clock.now = T0 + timedelta(days=1, minutes=1)
    for n in range(35):
        _trade(clock, register, journal, n, 0.4 + 0.02 * (n % 5))
    with pytest.raises(LearningError, match="before the end"):
        shadow.evaluate(register, journal, at=clock.now)  # about 30 days in, window still open
    clock.now = T0 + timedelta(days=31, hours=1)
    entry = shadow.evaluate(register, journal, at=clock.now)
    assert entry["verdict"] == ELIGIBLE and entry["metrics"]["n_minutes"] == 35
    assert entry["metrics"]["register_head"]
    with pytest.raises(LearningError, match="already evaluated"):
        shadow.evaluate(register, journal, at=clock.now)
    with pytest.raises(ShadowError, match="bewertet"):
        journal.record_plan(register, "after", decided_at=clock.now, direction="LONG", entry=1, stop=0.9,
                            targets=[], inputs_hash="h")
    with pytest.raises(LearningError, match="approver"):
        register.promote("S12-v1", approved_by="tim", at=clock.now)
    register.promote("S12-v1", approved_by="Uzi", at=clock.now, note="Uzi im Thread")
    assert register.champion("S12-schatten") == "S12-v1"
    assert shadow.status(register, tmp_path / "shadow")[0]["closed"] == 35


def test_open_plans_or_gaps_give_no_verdict(tmp_path: Path) -> None:
    clock, register, journal, _ = _setup(tmp_path)
    clock.now = T0 + timedelta(days=1, minutes=1)
    for n in range(32):
        _trade(clock, register, journal, n, 0.5, data_gap=n < 5)
    clock.now = T0 + timedelta(days=31, hours=1)
    entry = shadow.evaluate(register, journal, at=clock.now)
    assert entry["verdict"] == "NO_VERDICT"


def test_random_strategy_is_promoted_in_under_5_percent() -> None:
    rules = {"min_minutes": 30, "min_window_days": 30, "ci_level": 0.995, "min_effect": 0.05}
    rng = np.random.default_rng(31)
    passed = 0
    for sim in range(1000):
        values = rng.choice([-1.1, 0.9], size=60)  # coin flip with costs: true mean -0.1 R
        low, high = shadow.bootstrap_interval(values, draws=500, seed=sim)
        delta = float(values.mean())
        metrics = {"n_minutes": 60, "days": 30, "delta": delta, "ci_low": min(low, delta), "ci_high": max(high, delta),
                   "ci_level": 0.995, "calibration_ok": True, "quality_ok": True}
        passed += ModelRegister.verdict(rules, metrics)[0] == ELIGIBLE
    assert passed / 1000 < 0.05, passed
    fair = 0
    for sim in range(1000):
        values = rng.normal(0.0, 1.0, size=60)  # no edge at all
        low, high = shadow.bootstrap_interval(values, draws=500, seed=sim)
        delta = float(values.mean())
        metrics = {"n_minutes": 60, "days": 30, "delta": delta, "ci_low": min(low, delta), "ci_high": max(high, delta),
                   "ci_level": 0.995, "calibration_ok": True, "quality_ok": True}
        fair += ModelRegister.verdict(rules, metrics)[0] == ELIGIBLE
    assert fair / 1000 < 0.05, fair


def test_cli_start_and_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    from src.research_lab.workshop.__main__ import main
    monkeypatch.chdir(tmp_path)
    args = ["shadow-start", "--study", "S12", "--model-id", "S12-v1", "--variant-hash", "h", "--code-commit", "c",
            "--study-version", "S12/1.0", "--cost-rule", "kosten/1", "--min-trades", "30", "--min-effect", "0.05"]
    assert main(args) == 0
    assert main(args) == 2  # the same study cannot start twice
    assert main(["shadow-status"]) == 0
    out = capsys.readouterr().out
    assert '"model_id": "S12-v1"' in out and (tmp_path / "data/research/shadow/register.jsonl").exists()


def test_weekly_round_evaluates_ended_shadows(tmp_path: Path) -> None:
    from src.research_lab.workshop.schedule import Workshop
    now = datetime.now(timezone.utc).replace(microsecond=0)
    clock = Clock(now)
    register = ModelRegister(tmp_path / shadow.REGISTER_PATH, clock=clock)
    shadow.start(register, "S12", model_id="S12-v1", variant_hash="h", code_commit="c", study_version="v",
                 cost_rule="k", min_trades=30, min_effect=0.05, horizon_minutes=60, at=now)
    workshop = Workshop(tmp_path, ps=lambda: "")
    assert workshop.evaluate_shadows(now + timedelta(days=5)) == []  # window still open
    # window over: the real clock is still "now", so the register refuses the early evaluation; the round
    # reports it instead of failing the whole week
    result = workshop.evaluate_shadows(now + timedelta(days=31))
    assert result[0]["model_id"] == "S12-v1" and "before the end" in result[0]["error"]
