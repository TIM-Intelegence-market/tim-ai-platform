import hashlib
import json

from scripts.verify_coverage_implementation import verify


def _manifest(files):
    unsigned = {"schema_version": "1.0.0", "files": files}
    return {
        **unsigned,
        "manifest_hash": hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def test_verify_accepts_matching_component(tmp_path, monkeypatch):
    component = tmp_path / "component.py"
    component.write_text("pass\n")
    expected = hashlib.sha256(component.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest({"component": {"path": "component.py", "sha256": expected}})))
    monkeypatch.setattr("scripts.verify_coverage_implementation.ROOT", tmp_path)

    assert verify(manifest)["status"] == "PASS"


def test_verify_rejects_changed_component(tmp_path, monkeypatch):
    component = tmp_path / "component.py"
    component.write_text("changed\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest({"component": {"path": "component.py", "sha256": "0" * 64}})))
    monkeypatch.setattr("scripts.verify_coverage_implementation.ROOT", tmp_path)

    assert verify(manifest)["status"] == "FAIL"
