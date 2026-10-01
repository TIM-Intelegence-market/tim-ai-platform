import json
from pathlib import Path

import pytest

from src.obsidian_vault.schema import SCHEMA_PATH, load_schema, vault_path


def test_repo_schema_loads_and_is_consistent():
    schema = load_schema()
    assert schema.statuses == ("planned", "active", "blocked", "done", "archived")
    assert schema.inbox == "00 Inbox"
    assert schema.template_folders == ("99 Vorlagen",)
    prefixes = [rule.prefix for rule in schema.folders.values()]
    assert len(prefixes) == len(set(prefixes))


def test_duplicate_prefix_is_rejected(tmp_path: Path):
    raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    raw["folders"]["40 Architektur"] = {"types": ["architecture"]}
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate folder prefixes"):
        load_schema(path)


def test_unknown_folder_type_is_rejected(tmp_path: Path):
    raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    raw["folders"]["40 Systeme"] = {"types": ["service"]}
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown types"):
        load_schema(path)


def test_vault_path_resolution_order(monkeypatch):
    monkeypatch.delenv("TIM_OBSIDIAN_VAULT", raising=False)
    monkeypatch.delenv("TIM_GRAPH_MCP_VAULT", raising=False)
    assert vault_path() is None
    monkeypatch.setenv("TIM_GRAPH_MCP_VAULT", "/legacy")
    assert vault_path() == Path("/legacy")
    monkeypatch.setenv("TIM_OBSIDIAN_VAULT", "/main")
    assert vault_path() == Path("/main")
    assert vault_path("/explicit") == Path("/explicit")
