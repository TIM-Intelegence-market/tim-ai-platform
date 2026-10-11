import json
from pathlib import Path

from src.local_first.documentation_context import documentation_for
from scripts.run_local_qwen_developer import _prompt
from src.local_first.runtime import LocalPrimaryWorker, LocalTask, RepairRecipeStore


def test_retrieves_relevant_local_docs_without_leaking_sensitive_files(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "state_machine.md").write_text(
        "# State machine\nA blocked task remains BLOCKED until tests pass.\n"
        "password=do-not-show\n", encoding="utf-8")
    (docs / "unrelated.md").write_text("# Weather\nSunny.\n", encoding="utf-8")
    (docs / "secret_notes.md").write_text("State machine private instructions.\n", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("State machine outside.\n", encoding="utf-8")
    (docs / "linked.md").symlink_to(outside)

    result = documentation_for(tmp_path, {"objective": "Repair state machine"})
    assert result and result[0]["path"] == "docs/state_machine.md"
    assert "BLOCKED" in result[0]["excerpt"]
    assert "do-not-show" not in json.dumps(result)
    assert "secret_notes" not in json.dumps(result)
    assert "outside" not in json.dumps(result)


def test_developer_prompt_includes_bounded_docs_without_expanding_patch_paths(tmp_path: Path, monkeypatch) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "state_machine.md").write_text("State machine must verify transitions.\n", encoding="utf-8")
    monkeypatch.setattr("scripts.run_local_qwen_developer.__file__", str(tmp_path / "scripts" / "run_local_qwen_developer.py"))
    prompt = json.loads(_prompt(
        {"objective": "Repair state machine", "allowed_paths": ["src/state.py"]},
        {"allowed_paths": ["src/state.py"], "required_outputs": [], "tests": [], "context": []},
    ))
    assert prompt["local_documentation"][0]["path"] == "docs/state_machine.md"
    assert prompt["allowed_paths_exact"] == ["src/state.py"]


def test_operational_qwen_prompt_uses_local_docs(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "health.md").write_text("Health check must verify the local result.\n", encoding="utf-8")
    worker = LocalPrimaryWorker(tmp_path, tmp_path / "state", None, RepairRecipeStore(tmp_path / "recipes"))
    prompt = json.loads(worker._prompt(LocalTask("health-1", "Repair health check", "Verify health")))
    assert prompt["local_documentation"][0]["path"] == "docs/health.md"
