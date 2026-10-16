import json

import pytest

from src.repair_diagnosis.manual import export_request, import_and_save, main
from src.repair_diagnosis.package import build_request
from src.repair_diagnosis.store import list_diagnoses

RECORDED_AT = "2026-09-09T00:00:00+00:00"
SECRET = "pass" + "word=" + "hunter2x"


@pytest.fixture
def request_path(tmp_path):
    request = build_request(
        {
            "incident_id": "inc-1",
            "category": "network",
            "component": "collector",
            "fingerprint": "a" * 64,
            "normalized_error": "TimeoutError: x",
        }
    )
    path = tmp_path / "req.json"
    export_request(request, path)
    return path


def write_response(tmp_path, hypothesis="retry", raw=None):
    path = tmp_path / "resp.json"
    if raw is None:
        raw = json.dumps(
            {
                "incident_id": "inc-1",
                "hypothesis": hypothesis,
                "proposed_actions": ["inspect timeout"],
                "confidence": 0.5,
            }
        )
    path.write_text(raw, encoding="utf-8")
    return path


def test_valid_response_is_saved_as_proposal(tmp_path, request_path):
    directory = tmp_path / "d"
    result = import_and_save(
        request_path, write_response(tmp_path), directory, recorded_at=RECORDED_AT
    )
    assert result["status"] == "VALID"
    assert result["can_mark_fixed"] is False
    saved = list_diagnoses(directory, "inc-1")
    assert len(saved) == 1
    assert saved[0]["outcome"] == "PROPOSAL"
    assert saved[0]["provider"] == "manual"
    assert saved[0]["provider_model"] == "manual"
    assert saved[0]["hypothesis"] == "retry"
    assert saved[0]["can_mark_fixed"] is False
    assert result["path"].endswith(".json")


def test_invalid_json_is_saved_as_invalid_response(tmp_path, request_path):
    directory = tmp_path / "d"
    result = import_and_save(
        request_path, write_response(tmp_path, raw="{bad"), directory, recorded_at=RECORDED_AT
    )
    assert result["status"] == "INVALID"
    saved = list_diagnoses(directory, "inc-1")
    assert [item["outcome"] for item in saved] == ["INVALID_RESPONSE"]
    assert saved[0]["hypothesis"] is None
    assert saved[0]["attempts"] == [{"provider": "manual", "status": "INVALID"}]


def test_secret_is_not_saved(tmp_path, request_path):
    directory = tmp_path / "d"
    result = import_and_save(
        request_path,
        write_response(tmp_path, hypothesis="leak " + SECRET),
        directory,
        recorded_at=RECORDED_AT,
    )
    assert result["status"] == "VALID"
    files = list(directory.glob("*.json"))
    assert len(files) == 1
    assert b"hunter2x" not in files[0].read_bytes()


def test_tampered_request_saves_nothing(tmp_path, request_path):
    document = json.loads(request_path.read_text())
    document["request"]["component"] = "other"
    request_path.write_text(json.dumps(document))
    directory = tmp_path / "d"
    with pytest.raises(ValueError):
        import_and_save(request_path, write_response(tmp_path), directory, recorded_at=RECORDED_AT)
    assert not list(directory.glob("*.json"))


def test_cli_with_store_saves_one_file(tmp_path, request_path, capsys):
    directory = tmp_path / "d"
    code = main(
        [
            "import",
            "--request",
            str(request_path),
            "--response",
            str(write_response(tmp_path)),
            "--store",
            str(directory),
        ]
    )
    assert code == 0
    assert len(list(directory.glob("*.json"))) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "VALID"


def test_cli_with_store_invalid_exit_code(tmp_path, request_path):
    directory = tmp_path / "d"
    code = main(
        [
            "import",
            "--request",
            str(request_path),
            "--response",
            str(write_response(tmp_path, raw="{bad")),
            "--store",
            str(directory),
        ]
    )
    assert code == 2
    assert len(list(directory.glob("*.json"))) == 1


def test_cli_without_store_saves_nothing(tmp_path, request_path):
    before = sorted(p.name for p in tmp_path.rglob("*"))
    code = main(
        ["import", "--request", str(request_path), "--response", str(write_response(tmp_path))]
    )
    assert code == 0
    after = sorted(p.name for p in tmp_path.rglob("*"))
    assert after == sorted(set(before) | {"resp.json"})
