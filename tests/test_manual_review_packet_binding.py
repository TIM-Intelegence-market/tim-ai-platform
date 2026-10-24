"""T04 extension: completeness, approval and authorization are separate; attestations bind to content."""
from __future__ import annotations

import copy

import pytest

from src.v2_completion.independent_cases import (
    build_review_workbook,
    review_content_hash,
    validate_review_packet,
    validate_review_workbook,
)

SAMPLE = {
    "sample_hash": "s" * 64,
    "manifest_hash": "m" * 64,
    "selected_cases": [
        {
            "selection_rank": rank,
            "observation_id": f"obs-{rank}",
            "case_id": f"case-{rank}",
            "source_window_signature": f"window-{rank}",
            "observed_at_utc": "2026-08-01T00:00:00Z",
            "validated_through_utc": "2026-08-01T00:30:00Z",
            "observation_kind": "RISING_CVD_ACTIVITY",
            "outcome": "PRICE_INCREASED",
            "input_hash": f"{rank}" * 64,
            "validation_hash": f"{rank + 5}" * 64,
        }
        for rank in (1, 2)
    ],
}


def full_review(reviewer: str = "reviewer-a", decision: str = "ACCEPT", **overrides):
    review = {
        "reviewer_id": reviewer,
        "reviewed_at_utc": "2026-10-22T07:00:00Z",
        "data_quality": "good",
        "observation_correct": True,
        "label_correct": True,
        "future_information_absent": True,
        "narrative_adjustment_absent": True,
        "confidence_0_to_1": 0.9,
        "decision": decision,
        "exclusion_reason": None,
        "rationale": "checked against replay",
        "inter_rater_conflict": False,
        "conflict_resolution": None,
    }
    review.update(overrides)
    return review


def signed_workbook(decisions=("ACCEPT", "ACCEPT")):
    workbook = build_review_workbook(SAMPLE)
    for item, decision in zip(workbook["selected_cases"], decisions):
        item["review"] = full_review(decision=decision)
    workbook["approval"] = True
    content = review_content_hash(workbook)
    workbook["reviewer_signature"] = {
        "signer_id": "reviewer-a", "role": "reviewer",
        "signed_at_utc": "2026-10-22T07:05:00Z", "bound_content_hash": content,
    }
    workbook["release_authority_signature"] = {
        "signer_id": "authority-b", "role": "release_authority",
        "signed_at_utc": "2026-10-22T07:10:00Z", "bound_content_hash": content,
    }
    return workbook


def test_fully_reviewed_signed_and_source_bound_packet_is_authorized():
    result = validate_review_packet(signed_workbook(), SAMPLE)
    assert result["completeness"] == "PASS" and result["approval"] is True
    assert result["authorization"] == "AUTHORIZED" and result["authorization_problems"] == []
    assert result["source_binding"] == "BOUND" and result["verdict"] == "REVIEW_AUTHORIZED"
    assert result["decisions"] == {"ACCEPT": 2, "REJECT": 0, "EXCLUDE": 0}
    # the legacy completeness check agrees
    assert validate_review_workbook(signed_workbook())["status"] == "PASS"


def test_the_three_findings_are_independent():
    workbook = signed_workbook()
    # approval flag off: complete and signed, but not approved
    unapproved = copy.deepcopy(workbook)
    unapproved["approval"] = False
    r = validate_review_packet(unapproved, SAMPLE)
    assert r["completeness"] == "PASS" and r["authorization"] == "AUTHORIZED"
    assert r["approval"] is False and r["verdict"] == "NOT_AUTHORIZED"
    # approval as string "true" is not approval
    stringy = copy.deepcopy(workbook)
    stringy["approval"] = "true"
    r = validate_review_packet(stringy, SAMPLE)
    assert r["approval"] is False and r["approval_flag_type_ok"] is False
    # approved and signed, but one decision missing: completeness fails, authorization is still judged on its own
    incomplete = copy.deepcopy(workbook)
    incomplete["selected_cases"][1]["review"] = {k: None for k in incomplete["selected_cases"][1]["review"]}
    content = review_content_hash(incomplete)
    for field in ("reviewer_signature", "release_authority_signature"):
        incomplete[field]["bound_content_hash"] = content
    r = validate_review_packet(incomplete, SAMPLE)
    assert r["completeness"] == "PENDING_OR_FAIL" and r["empty_reviews"] == 1
    assert r["authorization"] == "AUTHORIZED" and r["verdict"] == "NOT_AUTHORIZED"


def test_changing_a_decision_after_signing_breaks_the_binding():
    workbook = signed_workbook()
    workbook["selected_cases"][0]["review"]["decision"] = "REJECT"
    workbook["selected_cases"][0]["review"]["label_correct"] = False
    r = validate_review_packet(workbook, SAMPLE)
    assert r["completeness"] == "PASS"  # the row itself is a valid REJECT
    assert r["authorization"] == "NOT_AUTHORIZED"
    assert any("bound_content_hash" in p for p in r["authorization_problems"])
    assert r["verdict"] == "NOT_AUTHORIZED"


def test_approval_flag_and_legacy_hash_are_not_part_of_the_signed_content():
    workbook = signed_workbook()
    before = review_content_hash(workbook)
    workbook["approval"] = False
    workbook["workbook_hash"] = "x" * 64
    workbook["reviewer_signature"]["signed_at_utc"] = "2026-10-22T09:00:00Z"
    assert review_content_hash(workbook) == before
    workbook["selected_cases"][1]["review"]["rationale"] = "edited"
    assert review_content_hash(workbook) != before


@pytest.mark.parametrize("mutate, expected", [
    (lambda w: w.pop("release_authority_signature"), "release_authority_signature missing"),
    (lambda w: w.__setitem__("release_authority_signature", "authority-b"), "must be an object"),
    (lambda w: w["release_authority_signature"].__setitem__("signer_id", "reviewer-a"), "must not be the reviewer signer"),
    (lambda w: w["release_authority_signature"].__setitem__("role", "reviewer"), "role must be"),
    (lambda w: w["reviewer_signature"].__setitem__("signed_at_utc", "2026-10-22 07:05"), "signed_at_utc"),
    (lambda w: w["reviewer_signature"].__setitem__("bound_content_hash", "0" * 64), "does not match"),
])
def test_signature_defects_block_authorization(mutate, expected):
    workbook = signed_workbook()
    mutate(workbook)
    r = validate_review_packet(workbook, SAMPLE)
    assert r["authorization"] == "NOT_AUTHORIZED" and r["verdict"] == "NOT_AUTHORIZED"
    assert any(expected in p for p in r["authorization_problems"]), r["authorization_problems"]


def test_release_authority_may_not_have_reviewed_cases():
    workbook = signed_workbook()
    workbook["selected_cases"][1]["review"]["reviewer_id"] = "authority-b"
    content = review_content_hash(workbook)
    for field in ("reviewer_signature", "release_authority_signature"):
        workbook[field]["bound_content_hash"] = content
    r = validate_review_packet(workbook, SAMPLE)
    assert "must not have reviewed cases" in " ".join(r["authorization_problems"])
    assert sorted(r["reviewers"]) == ["authority-b", "reviewer-a"]


def test_negative_decisions_are_valid_outcomes_and_counted():
    workbook = signed_workbook(decisions=("ACCEPT", "REJECT"))
    workbook["selected_cases"][1]["review"]["observation_correct"] = False
    content = review_content_hash(workbook)
    for field in ("reviewer_signature", "release_authority_signature"):
        workbook[field]["bound_content_hash"] = content
    r = validate_review_packet(workbook, SAMPLE)
    assert r["completeness"] == "PASS" and r["decisions"]["REJECT"] == 1
    assert r["verdict"] == "REVIEW_AUTHORIZED"  # an authorized packet may contain rejections


@pytest.mark.parametrize("overrides, expected", [
    ({"decision": "MATCH"}, "decision must be one of"),
    ({"decision": "accept"}, "decision must be one of"),
    ({"decision": "ACCEPT", "label_correct": False}, "ACCEPT contradicts"),
    ({"decision": "REJECT"}, "REJECT without any false"),
    ({"decision": "EXCLUDE"}, "EXCLUDE requires exclusion_reason"),
    ({"observation_correct": "yes"}, "must be true or false"),
    ({"observation_correct": 1}, "must be true or false"),
    ({"inter_rater_conflict": "no"}, "must be true or false"),
    ({"inter_rater_conflict": True}, "requires conflict_resolution"),
    ({"confidence_0_to_1": 1.5}, "between 0 and 1"),
    ({"confidence_0_to_1": True}, "between 0 and 1"),
    ({"confidence_0_to_1": "0.9"}, "between 0 and 1"),
    ({"reviewed_at_utc": "now"}, "reviewed_at_utc"),
    ({"reviewed_at_utc": "2026-10-22T07:00:00"}, "reviewed_at_utc"),
    ({"reviewer_id": 7}, "reviewer_id must be a string"),
    ({"rationale": ""}, "missing: rationale"),
])
def test_wrong_types_and_contradictions_make_a_row_invalid(overrides, expected):
    workbook = build_review_workbook(SAMPLE)
    workbook["selected_cases"][0]["review"] = full_review(**overrides)
    workbook["selected_cases"][1]["review"] = full_review()
    r = validate_review_packet(workbook)
    assert r["completeness"] == "PENDING_OR_FAIL" and r["complete_human_decisions"] == 1
    assert len(r["invalid_reviews"]) == 1 and r["invalid_reviews"][0]["observation_id"] == "obs-1"
    assert any(expected in p for p in r["invalid_reviews"][0]["problems"]), r["invalid_reviews"][0]["problems"]


def test_source_binding_detects_swapped_rows_and_foreign_sample():
    workbook = signed_workbook()
    tampered = copy.deepcopy(workbook)
    tampered["selected_cases"][0]["persisted_outcome"] = "PRICE_DECREASED"
    r = validate_review_packet(tampered, SAMPLE)
    assert r["source_binding"] == "MISMATCH" and "differs from sample row" in " ".join(r["source_binding_problems"])
    assert r["verdict"] == "NOT_AUTHORIZED"
    foreign = dict(SAMPLE, sample_hash="f" * 64)
    r = validate_review_packet(workbook, foreign)
    assert r["source_binding"] == "MISMATCH" and "source_sample_hash differs" in " ".join(r["source_binding_problems"])
    extra = copy.deepcopy(workbook)
    extra["selected_cases"].append(dict(extra["selected_cases"][0], observation_id="obs-99"))
    r = validate_review_packet(extra, SAMPLE)
    assert r["source_binding"] == "MISMATCH" and any("obs-99 not in sample" in p for p in r["source_binding_problems"])
    # without a sample the binding is reported as not checked, never as bound
    assert validate_review_packet(workbook)["source_binding"] == "NOT_CHECKED"


def test_empty_or_malformed_workbooks_never_authorize():
    for workbook in ({}, {"approval": True}, {"selected_cases": "not-a-list", "approval": True},
                     {"selected_cases": [{"observation_id": "x", "review": "nope"}], "approval": True}):
        r = validate_review_packet(workbook)
        assert r["completeness"] == "PENDING_OR_FAIL" and r["verdict"] == "NOT_AUTHORIZED"
        assert r["authorization"] == "NOT_AUTHORIZED"


def test_shipped_blank_workbook_stays_pending_and_unauthorized():
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "artifacts/v2_completion/manual_review_workbook.json"
    workbook = json.loads(path.read_text(encoding="utf-8"))
    r = validate_review_packet(workbook)
    assert r["selected_count"] == 24 and r["empty_reviews"] == 24 and r["complete_human_decisions"] == 0
    assert r["completeness"] == "PENDING_OR_FAIL" and r["authorization"] == "NOT_AUTHORIZED"
    assert r["verdict"] == "NOT_AUTHORIZED"
