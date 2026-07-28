from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import ARTIFACT_ROOT
from .reporting import load_snapshot
from .storage import ManagerStore


def _matching_contradictions(question: str, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    lowered = question.casefold()
    normalized = lowered.replace("_", " ")
    contradictions = snapshot.get("contradictions", [])
    if any(term in lowered for term in ("contradiction", "conflict", "widerspruch", "widersprü")):
        return contradictions
    return [
        item
        for item in contradictions
        if item["subject"].replace("_", " ") in normalized
        or item["predicate"].replace("_", " ") in normalized
    ]


def answer(question: str, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    data = snapshot or load_snapshot()
    lowered = question.casefold()
    matching_contradictions = _matching_contradictions(question, data)
    if matching_contradictions:
        evidence = sorted(
            {
                reference
                for contradiction in matching_contradictions
                for claim in contradiction["claims"]
                for reference in claim["evidence_refs"]
            }
        )
        summary = "; ".join(
            f"{item['subject']}.{item['predicate']}: "
            + " vs ".join(str(claim["value"]) for claim in item["claims"])
            + f" ({item['resolution_status']})"
            for item in matching_contradictions
        )
        return {
            "answer": f"Contradiction(s) documented: {summary}.",
            "status": (
                "unresolved"
                if any(item["resolution_status"] == "unresolved" for item in matching_contradictions)
                else "provisionally_resolved"
            ),
            "data_state": data["generated_at_utc"],
            "verified_facts": [],
            "interpretation": [],
            "risks": [],
            "contradictions": matching_contradictions,
            "missing_information": [],
            "evidence": evidence,
            "snapshot": data["snapshot_id"],
        }
    module = next((item for item in data["module_states"] if item["module_id"].replace("_", " ") in lowered or item["name"].casefold() in lowered), None)
    if module:
        module_contradictions = [
            item
            for item in data.get("contradictions", [])
            if module["module_id"] in item["subject"]
        ]
        return {
            "answer": f"{module['name']} is {module['status']}.",
            "status": module["status"],
            "data_state": data["generated_at_utc"],
            "verified_facts": [f"{criterion} is evidenced" for criterion in module["verified_criteria"]],
            "interpretation": [],
            "risks": module["risks"],
            "contradictions": module_contradictions,
            "missing_information": [f"No evidence for {criterion}" for criterion in module["failed_criteria"]],
            "evidence": module["evidence_refs"],
            "snapshot": data["snapshot_id"],
        }
    return {
        "answer": "This information is not supported by the current canonical snapshot.",
        "status": "unknown",
        "data_state": data["generated_at_utc"],
        "verified_facts": [],
        "interpretation": [],
        "risks": [],
        "contradictions": [],
        "missing_information": ["No matching evidenced module or deterministic claim was found."],
        "evidence": [],
        "snapshot": data["snapshot_id"],
    }


def search(query: str, limit: int = 20) -> list[dict[str, Any]]:
    store = ManagerStore(ARTIFACT_ROOT / "indexes" / "tim_manager.sqlite3")
    try:
        return store.search(query, limit)
    finally:
        store.close()
