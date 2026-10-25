"""Evidence status of a setup from the hypothesis register: fail closed, provenance always present."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.research_lab.protocol import PROTOCOL_VERSION

from src.research_lab.stats.register import HypothesisRegister, RegisterError
from src.research_lab import setup_evidence as se


@pytest.mark.parametrize("scenario_type, timeframe", [
    ("BREAKOUT_ACCEPTANCE", "15m"),
    ("REJECTION_FAILED_BREAKOUT", "15m"),
    ("LIQUIDITY_SWEEP_REVERSAL", "1h"),
])
def test_no_explicit_mapping_never_inherits_t1_t3_failure(scenario_type, timeframe) -> None:
    verdict = se.evidence_status(scenario_type, timeframe)  # the real register of the repo
    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert verdict.variant_ids == () and verdict.variant_statuses == {}
    assert verdict.register_head_hash and verdict.register_events > 0
    assert verdict.reason == "NO_EXPLICIT_RULE_EQUIVALENCE" and verdict.execution_status == "RESEARCH_ONLY"
    assert verdict.mapping_version == se.EVIDENCE_MAPPING_VERSION and verdict.protocol_version == PROTOCOL_VERSION


def test_entry_model_alone_creates_no_mapping() -> None:
    verdict = se.evidence_status("REJECTION_FAILED_BREAKOUT", "15m", entry_model="FAILED_RETEST")
    assert verdict.status == "INSUFFICIENT_EVIDENCE" and verdict.variant_ids == ()


def test_shipped_equivalence_table_is_empty_by_design() -> None:
    assert se.RULE_EQUIVALENCES == {}
    # The repo register has no positive verdict at all; this test documents that fact.
    statuses = {v["status"] for v in HypothesisRegister(se.DEFAULT_REGISTER_PATH).variants().values()}
    assert "passed_holdout" not in statuses and "candidate" not in statuses


def _register(tmp_path: Path, **statuses: str) -> Path:
    path = tmp_path / "register.jsonl"
    register = HypothesisRegister(path)
    for variant, status in statuses.items():
        register.register(variant, "T2", {})
        if status == "passed_holdout":
            register.set_status(variant, "candidate")
        if status != "registered":
            register.set_status(variant, status)
    return path


@pytest.mark.parametrize("statuses, expected", [
    ({"v1": "failed_train"}, "NEGATIVE_EVIDENCE"),
    ({"v1": "failed_validation", "v2": "candidate"}, "NEGATIVE_EVIDENCE"),
    ({"v1": "candidate"}, "CANDIDATE_FROZEN"),
    ({"v1": "passed_holdout"}, "PASSED_HOLDOUT"),
    ({"v1": "passed_holdout", "v2": "failed_validation"}, "NEGATIVE_EVIDENCE"),
    ({"v1": "passed_holdout", "v2": "candidate"}, "INSUFFICIENT_EVIDENCE"),
    ({"v1": "registered"}, "INSUFFICIENT_EVIDENCE"),
])
def test_explicit_mapping_derives_status_from_register(tmp_path: Path, statuses, expected) -> None:
    path = _register(tmp_path, **statuses)
    table = {("REJECTION_FAILED_BREAKOUT", "15m"): tuple(statuses)}
    verdict = se.evidence_status("REJECTION_FAILED_BREAKOUT", "15m", path, equivalences=table)
    assert verdict.status == expected and verdict.variant_ids == tuple(statuses)
    assert verdict.variant_statuses == statuses and verdict.execution_status == "RESEARCH_ONLY"
    assert verdict.register_head_hash == HypothesisRegister(path).events()[-1]["hash"]
    # The mapping is keyed by type and timeframe; another timeframe inherits nothing.
    assert se.evidence_status("REJECTION_FAILED_BREAKOUT", "1h", path, equivalences=table).status == "INSUFFICIENT_EVIDENCE"


def test_mapping_to_an_unregistered_variant_is_an_error(tmp_path: Path) -> None:
    path = _register(tmp_path, v1="failed_train")
    with pytest.raises(RegisterError):
        se.evidence_status("X", "15m", path, equivalences={("X", "15m"): ("missing",)})


def test_broken_chain_gives_no_verdict_but_fail_closed_fields(tmp_path: Path) -> None:
    path = _register(tmp_path, v1="failed_train")
    lines = path.read_text().splitlines()
    path.write_text(lines[0].replace('"failed_train"', '"candidate"') + "\n" if '"failed_train"' in lines[0] else "\n".join(lines).replace('"failed_train"', '"candidate"') + "\n")
    with pytest.raises(RegisterError):
        se.evidence_status("X", "15m", path)
    fields = se.evidence_fields("X", "15m", path)
    assert fields["evidence_status"] == "INSUFFICIENT_EVIDENCE" and fields["execution_status"] == "RESEARCH_ONLY"
    assert fields["evidence_ref"]["reason"].startswith("REGISTER_UNREADABLE") and fields["evidence_ref"]["variant_ids"] == []


def test_missing_register_is_named(tmp_path: Path) -> None:
    verdict = se.evidence_status("X", "15m", tmp_path / "none.jsonl")
    assert verdict.status == "INSUFFICIENT_EVIDENCE" and verdict.reason == "REGISTER_MISSING" and verdict.register_events == 0


def test_verdict_with_positive_status_needs_variants() -> None:
    with pytest.raises(ValueError):
        se.EvidenceVerdict("PASSED_HOLDOUT", "X", "15m", (), {}, "h", "p", 1, "m", "1.1", "r")
    with pytest.raises(ValueError):
        se.EvidenceVerdict("APPROVED", "X", "15m", ("v",), {}, "h", "p", 1, "m", "1.1", "r")
