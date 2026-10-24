"""An approval flag must not manufacture review evidence for an empty sample."""
import pytest

from src.v2_completion.independent_cases import (
    build_review_workbook,
    validate_review_workbook,
)


@pytest.mark.parametrize("workbook", [
    {"approval": True},
    {"selected_cases": [], "approval": True},
    {"selected_cases": [], "selected_count": 24, "human_decisions_recorded": 24, "approval": True},
])
def test_approval_without_case_evidence_cannot_pass(workbook):
    result = validate_review_workbook(workbook)
    assert result["status"] == "PENDING_OR_FAIL"
    assert result["complete_human_decisions"] == 0


def test_generated_empty_workbook_cannot_be_approved_by_flipping_a_flag():
    workbook = build_review_workbook({"selected_cases": []})
    workbook["approval"] = True
    result = validate_review_workbook(workbook)
    assert result["status"] == "PENDING_OR_FAIL"
    assert result["selected_count"] == 0
