import json

import pytest

from src.repair_diagnosis.manual import (
    REQUEST_KIND,
    export_request,
    import_response,
    main,
    request_hash,
)
from src.repair_diagnosis.package import build_request


@pytest.fixture
def incident():
    return {
        "incident_id": "inc-1",
        "category": "network",
        "component": "collector",
        "fingerprint": "a" * 64,
        "normalized_error": "TimeoutError: " + "pass" + "word=" + "hun" + "ter2",
        "stack": "line 1",
        "reproduction": None,
        "code_paths": [],
        "tests": [],
    }


def test_export_writes_integrity_metadata_without_secret(tmp_path, incident):
    output = tmp_path / "request.json"
    request = build_request(incident)

    export_request(request, output)

    document = json.loads(output.read_text())
    assert document["kind"] == REQUEST_KIND
    assert document["request_sha256"] == request_hash(request)
    assert "hunter2" not in output.read_text()


def test_export_existing_path_raises_value_error(tmp_path, incident):
    output = tmp_path / "request.json"
    output.write_text("existing")

    with pytest.raises(ValueError):
        export_request(build_request(incident), output)


def test_import_valid_answer_is_manual_proposal(tmp_path, incident):
    request_path = tmp_path / "request.json"
    response_path = tmp_path / "response.json"
    request = build_request(incident)
    export_request(request, request_path)
    response_path.write_text(
        json.dumps(
            {
                "incident_id": "inc-1",
                "hypothesis": "temporary network timeout",
                "proposed_actions": ["retry collection"],
                "confidence": 0.8,
            }
        )
    )

    result = import_response(request_path, response_path)

    assert result["status"] == "VALID"
    assert result["provider"] == "manual"
    assert result["can_mark_fixed"] is False


def test_import_rejects_edited_request(tmp_path, incident):
    request_path = tmp_path / "request.json"
    response_path = tmp_path / "response.json"
    export_request(build_request(incident), request_path)
    document = json.loads(request_path.read_text())
    document["request"]["incident_id"] = "edited"
    request_path.write_text(json.dumps(document))
    response_path.write_text("{}")

    with pytest.raises(ValueError):
        import_response(request_path, response_path)


def test_import_rejects_oversized_answer(tmp_path, incident):
    request_path = tmp_path / "request.json"
    response_path = tmp_path / "response.json"
    export_request(build_request(incident), request_path)
    response_path.write_bytes(b"x" * 65537)

    result = import_response(request_path, response_path)

    assert result["status"] == "INVALID"
    assert result["reasons"] == ["response_too_large"]


def test_main_import_returns_status_code(tmp_path, incident):
    request_path = tmp_path / "request.json"
    valid_path = tmp_path / "valid.json"
    malformed_path = tmp_path / "malformed.json"
    export_request(build_request(incident), request_path)
    valid_path.write_text(
        json.dumps(
            {
                "incident_id": "inc-1",
                "hypothesis": "timeout",
                "proposed_actions": [],
                "confidence": 0.5,
            }
        )
    )
    malformed_path.write_text("not json")

    assert main(["import", "--request", str(request_path), "--response", str(valid_path)]) == 0
    assert main(["import", "--request", str(request_path), "--response", str(malformed_path)]) == 2


def test_main_export_and_missing_incident(tmp_path, incident):
    incident_path = tmp_path / "incident.json"
    output_path = tmp_path / "request.json"
    incident_path.write_text(json.dumps(incident))

    assert main(["export", "--incident", str(incident_path), "--out", str(output_path)]) == 0
    assert main(
        [
            "export",
            "--incident",
            str(tmp_path / "missing.json"),
            "--out",
            str(tmp_path / "missing-output.json"),
        ]
    ) == 1
