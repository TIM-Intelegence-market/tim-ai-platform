from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any


_REQUIRED_RESULT_KEYS = {"question", "summary", "claims", "conflicts", "limitations"}
_REQUIRED_CLAIM_KEYS = {"statement", "evidence_ids", "confidence"}


def validate_research_result(result: Any, known_evidence_ids: Iterable[str]) -> dict[str, Any]:
    """Validate a research result without raising exceptions."""
    errors: list[str] = []

    try:
        known_ids = set(known_evidence_ids)
    except Exception:
        known_ids = set()

    if not isinstance(result, dict):
        return {"ok": False, "errors": ["result must be a dict"]}

    missing = _REQUIRED_RESULT_KEYS - set(result)
    extra = set(result) - _REQUIRED_RESULT_KEYS
    for key in sorted(missing):
        errors.append(f"result: missing key {key}")
    for key in sorted(extra):
        errors.append(f"result: unexpected key {key}")

    question = result.get("question")
    if not isinstance(question, str) or not question:
        errors.append("question must be a non-empty str")

    if not isinstance(result.get("summary"), str):
        errors.append("summary must be a str")

    claims = result.get("claims")
    if not isinstance(claims, list):
        errors.append("claims must be a list")
    else:
        if len(claims) > 200:
            errors.append("claims must contain at most 200 items")
        for index, claim in enumerate(claims):
            _validate_claim(claim, index, known_ids, errors)

    for field in ("conflicts", "limitations"):
        value = result.get(field)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            errors.append(f"{field} must be a list of str")

    errors.sort()
    return {"ok": not errors, "errors": errors}


def _validate_claim(
    claim: Any, index: int, known_ids: set[Any], errors: list[str]
) -> None:
    prefix = f"claims[{index}]"
    if not isinstance(claim, dict):
        errors.append(f"{prefix}: must be a dict")
        return

    missing = _REQUIRED_CLAIM_KEYS - set(claim)
    extra = set(claim) - _REQUIRED_CLAIM_KEYS
    for key in sorted(missing):
        errors.append(f"{prefix}: missing key {key}")
    for key in sorted(extra):
        errors.append(f"{prefix}: unexpected key {key}")

    statement = claim.get("statement")
    if not isinstance(statement, str) or not statement:
        errors.append(f"{prefix}: statement must be a non-empty str")

    evidence_ids = claim.get("evidence_ids")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        errors.append(f"{prefix}: evidence_ids must be a non-empty list of unique str")
    else:
        if any(not isinstance(evidence_id, str) for evidence_id in evidence_ids):
            errors.append(f"{prefix}: evidence_ids must contain only str")
        if len(set(evidence_ids)) != len(evidence_ids):
            errors.append(f"{prefix}: evidence_ids must be unique")
        for evidence_id in evidence_ids:
            if isinstance(evidence_id, str) and evidence_id not in known_ids:
                errors.append(f"{prefix}: unknown evidence id {evidence_id}")

    confidence = claim.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        errors.append(f"{prefix}: confidence must be a finite number between 0 and 1")
