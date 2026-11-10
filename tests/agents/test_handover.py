"""Übergabezettel TIM_HANDOVER_V1 (docs/MULTI_AGENTEN_SYSTEM.md, Paket P1)."""
import copy
import json

import pytest

from src.agents.handover import MAX_ATTEMPTS, SCHEMA, Gate, HandoverError, Role, main, parse, validate

VALID = {
    "schema": SCHEMA,
    "task_id": "github-issue-42",
    "issue_number": 42,
    "from_role": "ENGINEER",
    "to_role": "TESTER",
    "input": "Issue #42 mit Vertrag",
    "output": "Draft-PR mit Reparatur",
    "evidence": [{"kind": "link", "ref": "PR #43"}],
    "attempt": 1,
    "max_attempts": 3,
    "gate": "NONE",
}


def _slip(**changes):
    data = copy.deepcopy(VALID)
    data.update(changes)
    return data


def _body(data):
    return "Text davor\n\n```json TIM_HANDOVER_V1\n" + json.dumps(data) + "\n```\n\nText danach"


def test_valid_slip_round_trips_through_an_issue_body():
    slip = parse(_body(VALID), issue_number=42)
    assert (slip.from_role, slip.to_role, slip.gate) == (Role.ENGINEER, Role.TESTER, Gate.NONE)
    assert slip.to_dict() == VALID
    assert parse("Kopf\n\n" + slip.render()) == slip


@pytest.mark.parametrize("changes, message", [
    ({"schema": "TIM_HANDOVER_V2"}, "schema"),
    ({"task_id": "has space"}, "task_id"),
    ({"issue_number": 0}, "issue_number"),
    ({"issue_number": True}, "issue_number"),
    ({"from_role": "CEO"}, "from_role"),
    ({"to_role": "ENGINEER"}, "differ"),
    ({"input": " "}, "input"),
    ({"output": "x" * 2001}, "output"),
    ({"evidence": []}, "evidence"),
    ({"evidence": [{"kind": "feeling", "ref": "looks fine"}]}, "kind"),
    ({"evidence": [{"kind": "link", "ref": "PR #43", "note": "x"}]}, "exactly"),
    ({"evidence": [{"kind": "test", "ref": "pytest green"}]}, "must attach evidence of kind 'link'"),
    ({"attempt": 0}, "attempt"),
    ({"attempt": 1.0}, "attempt"),
    ({"max_attempts": MAX_ATTEMPTS + 1}, "max_attempts"),
    ({"attempt": 3, "max_attempts": 2}, "stop and report"),
    ({"gate": "APPROVED"}, "gate"),
])
def test_broken_rule_is_rejected(changes, message):
    with pytest.raises(HandoverError, match=message):
        validate(_slip(**changes))


def test_unknown_and_missing_fields_are_rejected():
    with pytest.raises(HandoverError, match="unknown \\['approved_by'\\]"):
        validate(_slip(approved_by="Uzi"))
    data = _slip()
    del data["gate"]
    with pytest.raises(HandoverError, match="missing \\['gate'\\]"):
        validate(data)
    with pytest.raises(HandoverError, match="JSON object"):
        validate([VALID])


def test_last_allowed_attempt_passes_and_extra_evidence_is_fine():
    slip = validate(_slip(attempt=MAX_ATTEMPTS, max_attempts=MAX_ATTEMPTS, gate="F2_MERGE",
                          evidence=[{"kind": "test", "ref": "pytest 7258 passed"},
                                    {"kind": "link", "ref": "PR #43"}]))
    assert slip.attempt == MAX_ATTEMPTS and slip.gate is Gate.F2_MERGE


def test_pm_needs_no_fixed_evidence_kind():
    assert validate(_slip(from_role="PM", to_role="ENGINEER",
                          evidence=[{"kind": "file", "ref": "docs/x.md"}])).from_role is Role.PM


@pytest.mark.parametrize("body, message", [
    (None, "found 0"),
    ("kein Zettel", "found 0"),
    (_body(VALID) + "\n" + _body(VALID), "found 2"),
    ("```json TIM_HANDOVER_V1\n{not json\n```", "invalid"),
    ("```json TIM_HANDOVER_V1\n{\"attempt\": NaN}\n```", "invalid"),
    ("```json TIM_HANDOVER_V1\n" + "x" * 12_001 + "\n```", "too large"),
])
def test_body_without_exactly_one_readable_slip_is_rejected(body, message):
    with pytest.raises(HandoverError, match=message):
        parse(body)


def test_slip_of_another_issue_is_rejected():
    with pytest.raises(HandoverError, match="another issue"):
        parse(_body(VALID), issue_number=7)


def test_cli_reports_valid_and_invalid(tmp_path, capsys):
    good, bad = tmp_path / "good.md", tmp_path / "bad.md"
    good.write_text(_body(VALID), encoding="utf-8")
    bad.write_text(_body(_slip(attempt=3, max_attempts=2)), encoding="utf-8")
    assert main([str(good)]) == 0
    assert "VALID: github-issue-42 ENGINEER -> TESTER, attempt 1/3, gate NONE" in capsys.readouterr().out
    assert main([str(bad)]) == 1
    assert "INVALID" in capsys.readouterr().out
    assert main([str(tmp_path / "missing.md")]) == 1
    assert main([]) == 2
