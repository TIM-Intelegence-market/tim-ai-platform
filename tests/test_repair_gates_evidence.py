import hashlib
import json

from src.repair_gates.evidence_gates import REPORT_GATES, gates_from_refs


def write_report(tmp_path, name, status):
    path = tmp_path / f"{name}.json"
    data = json.dumps({"status": status}).encode()
    path.write_bytes(data)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def complete_refs(tmp_path):
    return {
        name: write_report(tmp_path, name, "FAIL_AS_EXPECTED" if name == "pre_repair_repro" else "PASS")
        for name in REPORT_GATES
    }


def test_all_valid_reports_pass(tmp_path):
    results = gates_from_refs(complete_refs(tmp_path))
    assert [result.status for result in results] == ["PASS"] * len(REPORT_GATES)
    assert [result.name for result in results] == list(REPORT_GATES)


def test_missing_reference_fails(tmp_path):
    refs = complete_refs(tmp_path)
    del refs["runtime"]
    result = gates_from_refs(refs)[2]
    assert result.status == "FAIL"
    assert result.reason == "missing evidence reference"


def test_unreadable_report_fails(tmp_path):
    refs = complete_refs(tmp_path)
    refs["runtime"]["path"] = str(tmp_path / "missing.json")
    result = gates_from_refs(refs)[2]
    assert result.status == "FAIL"
    assert result.evidence_refs == [refs["runtime"]["path"]]


def test_invalid_json_fails(tmp_path):
    refs = complete_refs(tmp_path)
    path = tmp_path / "bad.json"
    path.write_bytes(b"not json")
    refs["runtime"] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert gates_from_refs(refs)[2].status == "FAIL"


def test_hash_mismatch_fails(tmp_path):
    refs = complete_refs(tmp_path)
    refs["runtime"]["sha256"] = "0" * 64
    assert gates_from_refs(refs)[2].reason == "sha256 mismatch"


def test_pre_repair_requires_expected_failure(tmp_path):
    refs = complete_refs(tmp_path)
    refs["pre_repair_repro"] = write_report(tmp_path, "pre_repair_repro", "NOT_REPRODUCED")
    result = gates_from_refs(refs)[6]
    assert result.status == "FAIL"
    assert result.reason == "unexpected status: 'NOT_REPRODUCED'"


def test_missing_status_fails(tmp_path):
    refs = complete_refs(tmp_path)
    path = tmp_path / "missing-status.json"
    data = b"{}"
    path.write_bytes(data)
    refs["runtime"] = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}
    assert gates_from_refs(refs)[2].reason == "missing status"
