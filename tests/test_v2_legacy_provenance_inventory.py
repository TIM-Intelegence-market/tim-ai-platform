from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.v2_completion.legacy_provenance import FIELDS, inventory_legacy_jsonl


def source(tmp_path, raw):
    path = tmp_path / "legacy.jsonl"
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def complete():
    return {"artifact_hash": "a" * 64, "schema_version": "1.0.0", "generator_version": "1.0.0"}


def test_inventory_counts_all_legacy_deficiencies_and_bounds_examples_without_writes(tmp_path):
    raw = (json.dumps({"mode": "OBSERVE"}) + "\n").encode() * 1602
    path, digest = source(tmp_path, raw)
    result = inventory_legacy_jsonl(path, expected_sha256=digest, max_examples=2)
    assert result["source_binding"] == "MATCH" and result["read_complete"] is True
    assert result["records_seen"] == result["object_records"] == 1602
    assert result["documentation_complete_records"] == 0
    assert result["missing_field_counts"] == {field: 1602 for field in FIELDS}
    assert result["missing_field_combinations"] == [{"fields": list(FIELDS), "records": 1602}]
    assert len(result["issue_examples"]) == 2 and result["issues_not_shown"] == 1600
    assert result["documentation_status"] == "INCOMPLETE"
    assert result["classification_status"] == "PENDING_HUMAN_REVIEW"
    assert result["v2_approved"] is result["readiness_counted"] is False
    assert path.read_bytes() == raw
    assert list(tmp_path.iterdir()) == [path]


def test_present_but_empty_or_invalid_fields_are_not_counted_complete(tmp_path):
    rows = [complete(), {"artifact_hash": "not-a-hash", "generator_version": None, "schema_version": " "},
            {"artifact_hash": "b" * 64, "schema_version": "1.0.0"}]
    path, digest = source(tmp_path, ("\n".join(json.dumps(row) for row in rows) + "\n").encode())
    result = inventory_legacy_jsonl(path, expected_sha256=digest)
    assert result["documentation_complete_records"] == 1
    assert result["missing_field_counts"]["generator_version"] == 1
    assert result["invalid_field_counts"] == {field: 1 for field in FIELDS}
    assert result["documentation_status"] == "INCOMPLETE"


def test_malformed_non_object_duplicate_key_and_invalid_utf8_records_remain_visible(tmp_path):
    raw = b'\nnot JSON\n[]\n{"schema_version":"x","schema_version":"y"}\n\xff\n'
    path, digest = source(tmp_path, raw)
    result = inventory_legacy_jsonl(path, expected_sha256=digest)
    assert result["blank_lines"] == 1
    assert result["records_seen"] == result["malformed_records"] == 4
    assert result["object_records"] == 0
    assert [item["line"] for item in result["issue_examples"]] == [2, 3, 4, 5]
    assert result["documentation_status"] == "INCOMPLETE"
    assert path.read_bytes() == raw


def test_complete_documentation_does_not_verify_semantic_hash_or_approve_v2(tmp_path):
    path, digest = source(tmp_path, (json.dumps(complete()) + "\n").encode())
    result = inventory_legacy_jsonl(path, expected_sha256=digest)
    assert result["documentation_status"] == "COMPLETE" and result["source_binding"] == "MATCH"
    assert result["semantic_hash_verification"] == "NOT_PERFORMED"
    assert result["v2_approved"] is result["readiness_counted"] is False
    changed = inventory_legacy_jsonl(path, expected_sha256="0" * 64)
    assert changed["source_binding"] == "MISMATCH"
    assert changed["observed_source_sha256"] == digest


def test_empty_source_is_not_complete(tmp_path):
    path, digest = source(tmp_path, b"\n  \n")
    result = inventory_legacy_jsonl(path, expected_sha256=digest, max_examples=0)
    assert result["source_binding"] == "MATCH"
    assert result["documentation_status"] == "NO_RECORDS" and result["records_seen"] == 0


def test_absent_source_is_not_replaced_or_reported_as_an_empty_population(tmp_path):
    path = tmp_path / "missing.jsonl"
    result = inventory_legacy_jsonl(path, expected_sha256="a" * 64)
    assert result["source_binding"] == "UNAVAILABLE" and result["read_complete"] is False
    assert result["documentation_status"] == "UNAVAILABLE"
    assert result["observed_source_sha256"] is None
    assert result["source_error"] == "FileNotFoundError"
    assert list(tmp_path.iterdir()) == []


def test_read_error_cannot_bind_a_partial_inventory(tmp_path, monkeypatch):
    class BrokenStream:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def __iter__(self):
            yield b'{"schema_version":"1.0.0"}\n'
            raise OSError("private error detail")

    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: BrokenStream())
    result = inventory_legacy_jsonl(tmp_path / "partial.jsonl", expected_sha256="a" * 64)
    assert result["records_seen"] == 1
    assert result["read_complete"] is False and result["source_binding"] == "UNAVAILABLE"
    assert result["observed_source_sha256"] is None
    assert result["source_error"] == "OSError"
    assert "private error detail" not in json.dumps(result)


@pytest.mark.parametrize("digest,limit", [("bad", 50), ("A" * 64, 50), ("a" * 64, -1),
                                          ("a" * 64, 1001), ("a" * 64, True)])
def test_invalid_source_identity_or_example_limit_is_rejected(tmp_path, digest, limit):
    with pytest.raises(ValueError):
        inventory_legacy_jsonl(tmp_path / "unused", expected_sha256=digest, max_examples=limit)


def test_cli_is_read_only_and_rejects_unbound_or_incomplete_sources(tmp_path, capsys):
    from scripts.v2_legacy_provenance_inventory import main

    path, digest = source(tmp_path, (json.dumps(complete()) + "\n").encode())
    before = path.read_bytes()
    assert main(["--input", str(path), "--expected-sha256", digest]) == 0
    assert json.loads(capsys.readouterr().out)["v2_approved"] is False
    assert main(["--input", str(path), "--expected-sha256", "0" * 64]) == 2
    assert json.loads(capsys.readouterr().out)["source_binding"] == "MISMATCH"
    assert path.read_bytes() == before and list(tmp_path.iterdir()) == [path]


def test_cli_keeps_incomplete_bound_evidence_blocked(tmp_path, capsys):
    from scripts.v2_legacy_provenance_inventory import main

    path, digest = source(tmp_path, b'{}\n')
    assert main(["--input", str(path), "--expected-sha256", digest, "--max-examples", "0"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["source_binding"] == "MATCH" and result["documentation_status"] == "INCOMPLETE"
    assert result["issue_examples"] == [] and result["issues_not_shown"] == 1
    assert path.read_bytes() == b'{}\n'
