"""Setup draft for the community channel: text only, derived from one analysis, never posted by TIM."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from src.orderflow_scenario.domain import DecisionStatus
from src.orderflow_scenario.engines.pipeline import Pipeline
from src.orderflow_scenario.setup_draft import DISCLAIMER, MAX_DRAFT_CHARS, build_setup_draft

from tests.test_goathub_discord_feed import pipeline_inputs


def test_no_trade_draft_says_so_and_carries_the_disclaimer() -> None:
    analysis = Pipeline().run(pipeline_inputs())
    assert analysis.decision.status == DecisionStatus.NO_TRADE
    draft = build_setup_draft(analysis)
    assert "Kein Setup (NO TRADE)" in draft and "BTCUSDT 15m" in draft
    assert draft.rstrip().endswith(f"_{DISCLAIMER}_")
    assert "Chance/Risiko" not in draft and "Stop " not in draft


def test_draft_never_shows_scores_or_exceeds_the_discord_limit() -> None:
    analysis = Pipeline().run(pipeline_inputs())
    draft = build_setup_draft(analysis)
    assert len(draft) <= MAX_DRAFT_CHARS
    assert "score" not in draft.lower()


def test_long_text_is_cut_but_the_disclaimer_survives() -> None:
    analysis = Pipeline().run(pipeline_inputs())
    long_reasons = tuple(f"REASON_{i}_" + "X" * 80 for i in range(60))
    noisy = replace(analysis, decision=replace(analysis.decision, reason_codes=long_reasons))
    draft = build_setup_draft(noisy)
    assert len(draft) <= MAX_DRAFT_CHARS
    assert draft.rstrip().endswith(f"_{DISCLAIMER}_") and "…" in draft


def test_sensitive_words_are_not_copied_into_the_draft() -> None:
    analysis = Pipeline().run(pipeline_inputs())
    decision = replace(analysis.decision, missing_confirmations=("api secret leaked in note",))
    draft = build_setup_draft(replace(analysis, decision=decision))
    assert "secret" not in draft.lower() and "(Text siehe Audit)" in draft


def test_cli_writes_the_draft_to_a_file(tmp_path: Path, capsys, monkeypatch) -> None:
    from src.orderflow_scenario import cli

    source = tmp_path / "input.json"
    source.write_text("{}", encoding="utf-8")
    target = tmp_path / "draft.md"
    monkeypatch.setattr(cli, "_pipeline_inputs", lambda adapter, data: pipeline_inputs())
    assert cli.main(["--input", str(source), "--setup-draft", str(target)]) == 0
    json.loads(capsys.readouterr().out)  # stdout stays the analysis JSON
    assert "TIM · Setup-Entwurf" in target.read_text(encoding="utf-8")


def test_trade_plan_draft_shows_levels_invalidation_and_evidence_gaps() -> None:
    from tests.test_orderflow_pipeline_trade_plan import confirmed_run

    _, analysis = confirmed_run()
    plan = analysis.decision.trade_plan
    assert plan is not None
    draft = build_setup_draft(analysis)
    assert f"**Setup:** {plan.direction.value} BTCUSDT" in draft and "Kein Setup" not in draft
    assert f"Stop {format(plan.stop_loss, 'f')}" in draft
    assert format(plan.target_1, "f") in draft and "Ungültig, wenn:" in draft
    assert "Chance/Risiko" in draft and draft.rstrip().endswith(f"_{DISCLAIMER}_")
    assert len(draft) <= MAX_DRAFT_CHARS


def test_cli_reports_an_unwritable_draft_path_without_traceback(tmp_path: Path, capsys, monkeypatch) -> None:
    from src.orderflow_scenario import cli

    source = tmp_path / "input.json"
    source.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "_pipeline_inputs", lambda adapter, data: pipeline_inputs())
    assert cli.main(["--input", str(source), "--setup-draft", str(tmp_path / "missing" / "draft.md")]) == 2
    assert "--setup-draft could not be written" in capsys.readouterr().err


def test_mentions_in_the_draft_cannot_ping() -> None:
    analysis = Pipeline().run(pipeline_inputs())
    noisy = replace(analysis, decision=replace(analysis.decision, reason_codes=("@everyone", "<@123456789012345678>", "@here")))
    draft = build_setup_draft(noisy)
    assert "@everyone" not in draft and "@here" not in draft and "<@1" not in draft
    assert "@\u200beveryone" in draft
