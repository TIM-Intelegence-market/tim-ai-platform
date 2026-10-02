"""STEP 30: indexer behavior — code/AST, database schema, Obsidian vault,
agents, GitHub payload, runtime services, incremental refresh, deletions."""
from __future__ import annotations

import json
from pathlib import Path

from src.graph_mcp.indexer.agents import AgentIndexer
from src.graph_mcp.indexer.code import CodeIndexer
from src.graph_mcp.indexer.database import DatabaseIndexer
from src.graph_mcp.indexer.github import GithubIndexer
from src.graph_mcp.indexer.obsidian import (ObsidianIndexer, parse_code_field,
                                            parse_frontmatter)
from src.graph_mcp.indexer.runtime import RuntimeIndexer


def test_code_indexer_extracts_symbols_and_relations(code_tree: Path):
    result = CodeIndexer(code_tree).index()
    ids = {node["id"] for node in result.nodes}
    types = {node["type"] for node in result.nodes}
    assert {"File", "Module", "Class", "Method", "Function", "Test"} <= types
    assert "class:src/demo/core.py:Engine" in ids
    assert "method:src/demo/core.py:Engine.run" in ids
    assert "method:src/demo/core.py:Engine.prepare" in ids
    assert "function:src/demo/core.py:helper" in ids
    assert "test:tests/test_core.py:test_helper_returns_engine" in ids
    relations = {(e["from"], e["to"], e["type"]) for e in result.edges}
    assert any(e[2] == "IMPORTS" for e in relations)
    assert any(e[2] == "TESTS" and e[0].startswith("test:") for e in relations)
    tests_edge = next(e for e in result.edges if e["type"] == "TESTS")
    assert tests_edge["metadata"]["confidence"] < 1.0  # resolution labeled
    calls = [e for e in result.edges if e["type"] == "CALLS"]
    assert all(e["metadata"]["confidence"] < 1.0 and e["evidence"] for e in calls)


def test_code_indexer_deterministic(code_tree: Path):
    first = CodeIndexer(code_tree).index()
    second = CodeIndexer(code_tree).index()
    key = lambda r: (tuple(sorted(n["id"] for n in r.nodes)),
                     tuple(sorted((e["from"], e["to"], e["type"]) for e in r.edges)))
    assert key(first) == key(second)


def test_calls_resolve_to_real_method_ids(code_tree: Path):
    """R12 regression: same-file calls to methods must target
    method:<file>:Class.name ids — the old resolver emitted phantom
    function:<file>:name targets (86 dangling edges in the real graph)."""
    result = CodeIndexer(code_tree).index()
    ids = {node["id"] for node in result.nodes}
    calls = [e for e in result.edges if e["type"] == "CALLS"]
    assert all(e["to"] in ids for e in calls)  # no dangling CALLS targets
    assert any(e["to"] == "method:src/demo/core.py:Engine.prepare" for e in calls)


def test_no_phantom_init_service(code_tree: Path):
    """R12 regression: src/__init__.py is a package marker, not a service."""
    (code_tree / "src" / "other").mkdir(exist_ok=True)
    (code_tree / "src" / "other" / "__init__.py").write_text("")
    result = RuntimeIndexer(code_tree).index()
    assert "service:__init__.py" not in {node["id"] for node in result.nodes}


def test_database_indexer_parses_schema(tmp_path: Path):
    schema_dir = tmp_path / "src" / "database"
    schema_dir.mkdir(parents=True)
    (schema_dir / "schema.sql").write_text(
        "CREATE TABLE IF NOT EXISTS candles (\n"
        "    symbol TEXT NOT NULL,\n"
        "    open_time TIMESTAMPTZ NOT NULL,\n"
        "    volume DOUBLE PRECISION NOT NULL,\n"
        "    PRIMARY KEY (symbol, open_time)\n"
        ");\n"
        "CREATE TABLE IF NOT EXISTS observations (\n"
        "    candle_symbol TEXT REFERENCES candles,\n"
        "    PRIMARY KEY (candle_symbol)\n"
        ");\n")
    (tmp_path / "src" / "repo_layer.py").write_text(
        "rows = conn.fetch('SELECT symbol FROM candles WHERE open_time > $1')\n"
        "await conn.execute('INSERT INTO observations VALUES ($1)')\n")
    indexer = DatabaseIndexer(tmp_path)
    tables = indexer.tables()
    assert set(tables) == {"candles", "observations"}
    assert tables["candles"]["columns"][0]["name"] == "symbol"
    assert tables["observations"]["references"] == ["candles"]
    result = indexer.index()
    ids = {node["id"] for node in result.nodes}
    assert "table:tim:candles" in ids and "column:tim:candles:symbol" in ids
    relations = {(e["from"], e["to"], e["type"]) for e in result.edges}
    assert any(r[2] == "REFERENCES" for r in relations)
    reads = [e for e in result.edges if e["type"] == "READS"]
    writes = [e for e in result.edges if e["type"] == "WRITES"]
    assert reads and all(e["evidence"] for e in reads)
    assert writes and writes[0]["evidence"][0].endswith(":L2")


def test_obsidian_indexer_types_links_and_privacy(vault_tree: Path):
    result = ObsidianIndexer(vault_tree).index()
    types = {node["type"] for node in result.nodes}
    assert {"ObsidianNote", "Mission", "Gate", "Incident"} <= types
    mission = next(n for n in result.nodes if n["type"] == "Mission")
    assert mission["metadata"]["status"] == "active"
    references = [e for e in result.edges if e["type"] == "REFERENCES"]
    assert references and all(e["evidence"] for e in references)
    documented = [e for e in result.edges if e["type"] == "DOCUMENTED_BY"]
    assert documented
    # bodies are never indexed: metadata carries frontmatter only
    for node in result.nodes:
        assert "See" not in json.dumps(node["metadata"])


def test_obsidian_indexer_skips_template_folders(vault_tree: Path):
    for folder in ("99 Vorlagen", "Templates"):
        template = vault_tree / "TIM" / folder / "Template Mission.md"
        template.parent.mkdir()
        template.write_text("---\ntype: mission\nstatus: planned\n---\n# {{title}}\n")
    result = ObsidianIndexer(vault_tree).index()
    assert [n["name"] for n in result.nodes if n["type"] == "Mission"] == ["Demo Mission"]
    assert result.metrics["NOTES"] == 3


def test_parse_frontmatter():
    fields = parse_frontmatter("---\ntype: mission\nstatus: pass\n---\nbody\n")
    assert fields == {"type": "mission", "status": "pass"}
    assert parse_frontmatter("no frontmatter") == {}


def test_agents_indexer_uses_tool_only_with_evidence(tmp_path: Path):
    empty = AgentIndexer(tmp_path / "missing").index()
    assert not [e for e in empty.edges if e["type"] == "USES_TOOL"]
    ki = tmp_path / "KI TOOLS"
    (ki / "caveman").mkdir(parents=True)
    result = AgentIndexer(ki).index()
    uses = [e for e in result.edges if e["type"] == "USES_TOOL"]
    assert uses and uses[0]["from"] == "agent:opencode"
    assert uses[0]["evidence"] == ["KI TOOLS/README.md"]
    agents = {n["id"]: n for n in result.nodes if n["type"] == "Agent"}
    assert agents["agent:chatgpt"]["metadata"]["availability"] == "unknown"


def test_github_payload_adapter():
    payload = {"issues": [{"number": 12, "title": "gates", "state": "open",
                           "parent": 11, "blocked_by": [13]}],
               "commits": [{"sha": "abcdef1234567890", "message": "fix",
                            "implements": [12]}],
               "pull_requests": [{"number": 7, "state": "open", "implements": [12]}]}
    result = GithubIndexer().index_payload(payload)
    ids = {node["id"] for node in result.nodes}
    assert "github:issue:12" in ids
    relations = {(e["from"], e["to"], e["type"]) for e in result.edges}
    assert ("github:issue:11", "github:issue:12", "PARENT_OF") in relations
    assert ("github:issue:13", "github:issue:12", "BLOCKS") in relations
    assert any(r[2] == "IMPLEMENTS" for r in relations)


def test_runtime_indexer_services_from_imports(code_tree: Path):
    result = RuntimeIndexer(code_tree).index()
    services = {node["name"] for node in result.nodes if node["type"] == "Service"}
    assert "src.demo" in services
    assert all(node["metadata"]["discovery"] == "code_imports"
               for node in result.nodes if node["type"] == "Service")
    # no main.py in the fixture -> nothing claims main.py wiring
    assert all(node["metadata"]["wired_via"] == "internal"
               for node in result.nodes if node["type"] == "Service")


def test_obsidian_typed_links_become_typed_edges(vault_tree: Path):
    result = ObsidianIndexer(vault_tree).index()
    typed = {(e["from"], e["to"], e["type"]) for e in result.edges
             if e["metadata"].get("resolution_method") == "wikilink_typed"}
    mission = "mission:TIM/30%20Missions/Demo%20Mission.md"
    gate = "gate:TIM/00%20HOME/Demo%20Gate.md"
    incident = "incident:TIM/20%20Incidents/Demo%20Incident.md"
    assert (mission, gate, "REQUIRES") in typed
    assert (mission, incident, "REFERENCES") in typed
    assert (incident, mission, "REFERENCES") in typed
    assert len(typed) == 3  # no duplicates, no self links


def test_obsidian_code_field_links_only_existing_paths(vault_tree: Path, code_tree: Path):
    system = vault_tree / "TIM" / "40 Systeme" / "Demo Engine.md"
    system.parent.mkdir()
    system.write_text("---\ntype: system\nstatus: active\ncode:\n"
                      "  - src/demo/core.py\n  - src/demo\n  - service:demo\n"
                      "  - src/missing.py\n  - ../outside.py\n  - service:../tests\n---\n# Demo Engine\n")
    result = ObsidianIndexer(vault_tree, repo_root=code_tree).index()
    note = "note:TIM/40%20Systeme/Demo%20Engine.md"
    code_edges = {(e["from"], e["to"]) for e in result.edges
                  if e["metadata"].get("resolution_method") == "frontmatter_code"}
    assert code_edges == {("file:src/demo/core.py", note), ("service:demo", note)}
    assert result.metrics["CODE_LINKS"] == 2  # directory and service: same node
    assert result.metrics["CODE_LINKS_UNRESOLVED"] == 3
    # without a repository root nothing is linked, nothing is guessed
    assert ObsidianIndexer(vault_tree).index().metrics["CODE_LINKS"] == 0


def test_parse_code_field_formats():
    assert parse_code_field("---\ncode: [src/a.py, 'src/b']\n---\n") == ["src/a.py", "src/b"]
    assert parse_code_field("---\ncode: src/a.py\n---\n") == ["src/a.py"]
    assert parse_code_field("---\ncode:\n  - src/a.py\ntype: x\n---\n") == ["src/a.py"]
    assert parse_code_field("---\ntype: x\n---\ncode: src/a.py\n") == []
