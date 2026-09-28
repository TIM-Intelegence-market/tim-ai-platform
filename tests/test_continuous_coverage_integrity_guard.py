import hashlib
import json

from scripts.continuous_coverage_integrity_guard import guard


def _manifest(files):
    unsigned = {"schema_version": "1.0.0", "files": files}
    return {
        **unsigned,
        "manifest_hash": hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def test_guard_permanently_fails_status_on_integrity_mismatch(tmp_path, monkeypatch):
    component = tmp_path / "component.py"
    component.write_text("changed\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest({"component": {"path": "component.py", "sha256": "0" * 64}})))
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"state": "RUNNING"}))
    monkeypatch.setattr("scripts.verify_coverage_implementation.ROOT", tmp_path)

    assert guard(manifest, status)["status"] == "FAIL"
    assert json.loads(status.read_text())["state"] == "FAILED_PERMANENT"


def test_guard_does_not_mutate_an_existing_permanent_failure(tmp_path, monkeypatch):
    component = tmp_path / "component.py"
    component.write_text("changed\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest({"component": {"path": "component.py", "sha256": "0" * 64}})))
    status = tmp_path / "status.json"
    original = {"state": "FAILED_PERMANENT", "original_failure": "missing candle"}
    status.write_text(json.dumps(original))
    monkeypatch.setattr("scripts.verify_coverage_implementation.ROOT", tmp_path)

    assert guard(manifest, status)["status"] == "FAIL"
    assert json.loads(status.read_text()) == original
