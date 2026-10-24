"""Read-only, source-bound inventory of legacy Module-A documentation fields."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any

FIELDS = ("artifact_hash", "generator_version", "schema_version")
SHA256 = re.compile(r"[0-9a-f]{64}")


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def inventory_legacy_jsonl(path: Path, *, expected_sha256: str, max_examples: int = 50) -> dict[str, Any]:
    """Inventory one explicitly selected source; never infer or repair metadata.

    The expected hash identifies independently frozen source bytes, not a semantic
    artifact hash. Complete fields do not establish provenance correctness.
    """
    if not isinstance(expected_sha256, str) or not SHA256.fullmatch(expected_sha256):
        raise ValueError("expected_sha256 must be a lowercase SHA-256 file hash")
    if isinstance(max_examples, bool) or not isinstance(max_examples, int) or not 0 <= max_examples <= 1000:
        raise ValueError("max_examples must be an integer from 0 through 1000")
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "kind": "LEGACY_MODULE_A_DOCUMENTATION_INVENTORY",
        "source_path": str(path),
        "expected_source_sha256": expected_sha256,
        "observed_source_sha256": None,
        "source_binding": "UNAVAILABLE",
        "size_bytes": 0,
        "records_seen": 0,
        "object_records": 0,
        "malformed_records": 0,
        "blank_lines": 0,
        "documentation_complete_records": 0,
        "missing_field_counts": {field: 0 for field in FIELDS},
        "invalid_field_counts": {field: 0 for field in FIELDS},
        "missing_field_combinations": [],
        "issue_examples": [],
        "issues_not_shown": 0,
        "documentation_status": "UNAVAILABLE",
        "semantic_hash_verification": "NOT_PERFORMED",
        "classification_status": "PENDING_HUMAN_REVIEW",
        "read_complete": False,
        "read_only": True,
        "readiness_counted": False,
        "v2_approved": False,
    }
    combinations: Counter[tuple[str, ...]] = Counter()
    digest = hashlib.sha256()
    issue_count = 0
    try:
        with path.open("rb") as stream:
            for number, raw in enumerate(stream, 1):
                digest.update(raw)
                result["size_bytes"] += len(raw)
                if not raw.strip():
                    result["blank_lines"] += 1
                    continue
                result["records_seen"] += 1
                missing, invalid = [], []
                try:
                    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
                    if not isinstance(value, dict):
                        raise ValueError("JSON object required")
                except (ValueError, UnicodeError):
                    result["malformed_records"] += 1
                    issue = {"line": number, "code": "MALFORMED_RECORD"}
                else:
                    result["object_records"] += 1
                    for field in FIELDS:
                        if field not in value:
                            missing.append(field)
                            result["missing_field_counts"][field] += 1
                        elif (not isinstance(value[field], str) or not value[field].strip()
                              or (field == "artifact_hash" and not SHA256.fullmatch(value[field]))):
                            invalid.append(field)
                            result["invalid_field_counts"][field] += 1
                    if missing:
                        combinations[tuple(missing)] += 1
                    if not missing and not invalid:
                        result["documentation_complete_records"] += 1
                        continue
                    issue = {"line": number, "code": "DOCUMENTATION_INCOMPLETE",
                             "missing_fields": missing, "invalid_fields": invalid}
                issue_count += 1
                if len(result["issue_examples"]) < max_examples:
                    result["issue_examples"].append(issue)
    except OSError as error:
        result["source_error"] = type(error).__name__
        # A partial read must never be presented as a complete inventory.
        result["documentation_status"] = "UNAVAILABLE"
        return result
    result["read_complete"] = True
    result["observed_source_sha256"] = digest.hexdigest()
    result["source_binding"] = "MATCH" if digest.hexdigest() == expected_sha256 else "MISMATCH"
    result["missing_field_combinations"] = [
        {"fields": list(fields), "records": count} for fields, count in sorted(combinations.items())
    ]
    result["issues_not_shown"] = issue_count - len(result["issue_examples"])
    result["documentation_status"] = (
        "NO_RECORDS" if not result["records_seen"] else "INCOMPLETE" if issue_count else "COMPLETE"
    )
    return result
