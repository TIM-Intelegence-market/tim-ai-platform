from src.research_evidence.result import validate_research_result


def valid_result():
    return {
        "question": "What happened?",
        "summary": "A concise answer.",
        "claims": [
            {
                "statement": "The answer is supported.",
                "evidence_ids": ["ev_1"],
                "confidence": 0.9,
            }
        ],
        "conflicts": [],
        "limitations": [],
    }


def test_accepts_valid_result():
    assert validate_research_result(valid_result(), ["ev_1"]) == {"ok": True, "errors": []}


def test_rejects_extra_and_missing_result_keys():
    result = valid_result()
    del result["summary"]
    result["extra"] = True

    errors = validate_research_result(result, ["ev_1"])["errors"]

    assert "result: missing key summary" in errors
    assert "result: unexpected key extra" in errors


def test_rejects_invalid_claim_fields():
    result = valid_result()
    result["claims"][0] = {
        "statement": "",
        "evidence_ids": [],
        "confidence": 2,
    }

    errors = validate_research_result(result, ["ev_1"])["errors"]

    assert "claims[0]: statement must be a non-empty str" in errors
    assert "claims[0]: evidence_ids must be a non-empty list of unique str" in errors
    assert "claims[0]: confidence must be a finite number between 0 and 1" in errors


def test_rejects_unknown_evidence_id():
    result = valid_result()
    result["claims"][0]["evidence_ids"] = ["ev_x"]

    assert "claims[0]: unknown evidence id ev_x" in validate_research_result(result, ["ev_1"])["errors"]


def test_rejects_duplicate_evidence_ids():
    result = valid_result()
    result["claims"][0]["evidence_ids"] = ["ev_1", "ev_1"]

    assert "claims[0]: evidence_ids must be unique" in validate_research_result(result, ["ev_1"])["errors"]


def test_rejects_nan_confidence():
    result = valid_result()
    result["claims"][0]["confidence"] = float("nan")

    assert not validate_research_result(result, ["ev_1"])["ok"]


def test_rejects_bool_confidence():
    result = valid_result()
    result["claims"][0]["confidence"] = True

    assert not validate_research_result(result, ["ev_1"])["ok"]


def test_rejects_more_than_200_claims():
    result = valid_result()
    result["claims"] = [result["claims"][0].copy() for _ in range(201)]

    assert "claims must contain at most 200 items" in validate_research_result(result, ["ev_1"])["errors"]
