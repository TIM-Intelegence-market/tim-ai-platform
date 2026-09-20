"""Shared fixtures for graph MCP tests — everything runs against temporary
trees and a temporary SQLite store. No TIM production surface is touched."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from src.graph_mcp.service import GraphService  # noqa: E402
from src.graph_mcp.store import GraphStore  # noqa: E402


@pytest.fixture
def code_tree(tmp_path: Path) -> Path:
    (tmp_path / "src" / "demo").mkdir(parents=True)
    (tmp_path / "src" / "demo" / "__init__.py").write_text("")
    (tmp_path / "src" / "demo" / "core.py").write_text(
        "from src.demo import helper\n"
        "\n"
        "\n"
        "class Engine:\n"
        "    def run(self):\n"
        "        return self.prepare()\n"
        "\n"
        "    def prepare(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "def helper():\n"
        "    return Engine()\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text(
        "from src.demo.core import helper\n"
        "\n"
        "\n"
        "def test_helper_returns_engine():\n"
        "    assert helper() is not None\n"
    )
    return tmp_path


@pytest.fixture
def vault_tree(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    content = vault / "TIM"
    content.mkdir(parents=True)
    (content / "30 Missions").mkdir()
    (content / "30 Missions" / "Demo Mission.md").write_text(
        "---\ntype: mission\nstatus: active\n---\n"
        "# Demo Mission\nSee [[Demo Gate]] and [[Demo Incident]].\n"
    )
    (content / "00 HOME").mkdir()
    (content / "00 HOME" / "Demo Gate.md").write_text(
        "---\ntype: gate\nstatus: pass\n---\n# Demo Gate\nDepends on data.\n"
    )
    (content / "20 Incidents").mkdir()
    (content / "20 Incidents" / "Demo Incident.md").write_text(
        "---\ntype: incident\nstatus: resolved\n---\n"
        "# Demo Incident\nDocumented in [[Demo Mission]].\n"
    )
    return vault


@pytest.fixture
def service(code_tree: Path, vault_tree: Path, tmp_path: Path) -> GraphService:
    store = GraphStore(tmp_path / "graph.sqlite")
    service = GraphService(store, code_tree, vault=vault_tree,
                           ki_tools=code_tree / "KI TOOLS")
    (code_tree / "KI TOOLS").mkdir(exist_ok=True)
    (code_tree / "KI TOOLS" / "caveman").mkdir(exist_ok=True)
    service.refresh_code()
    service.refresh_docs()
    service.refresh_runtime_readonly()
    return service
