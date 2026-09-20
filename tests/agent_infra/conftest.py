"""Shared fixtures: fake Serena + seeded graph store for preflight tests."""
from __future__ import annotations

import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from src.graph_mcp.schema import Edge, EdgeType, Node, NodeType, stable_id, utc_now  # noqa: E402
from src.graph_mcp.service import GraphService  # noqa: E402
from src.graph_mcp.store import GraphStore  # noqa: E402

from _fakes import FakeSerena, fake_serena_factory  # noqa: E402,F401


def seed_graph(store: GraphStore) -> None:
    observed = utc_now()
    mission_id = stable_id("mission", "TIM/30 Missions/Demo Mission.md")
    gate_id = stable_id("gate", "TIM/50 Data & QA/Demo Gate.md")
    note_id = stable_id("note", "TIM/30 Missions/Demo Mission.md")
    decision_id = stable_id("decision", "TIM/70 Decisions/Decision Log.md")
    class_id = stable_id("class", "src/data_ingestion/aggregator.py",
                         "CandleAggregator")
    module_id = stable_id("module", "src.data_ingestion.aggregator")
    nodes = [
        Node(mission_id, NodeType.MISSION, "Demo Mission", "obsidian",
             "TIM/30 Missions/Demo Mission.md",
             {"status": "active"}).record(observed),
        Node(gate_id, NodeType.GATE, "Demo Gate", "obsidian",
             "TIM/50 Data & QA/Demo Gate.md", {"status": "pass"}).record(observed),
        Node(note_id, NodeType.OBSIDIAN_NOTE, "Demo Mission", "obsidian",
             "TIM/30 Missions/Demo Mission.md", {}).record(observed),
        Node(decision_id, NodeType.DECISION, "Decision Log", "obsidian",
             "TIM/70 Decisions/Decision Log.md", {}).record(observed),
        Node(class_id, NodeType.CLASS, "CandleAggregator", "code",
             "src/data_ingestion/aggregator.py", {}).record(observed),
        Node(module_id, NodeType.MODULE, "src.data_ingestion.aggregator",
             "code", "src/data_ingestion/aggregator.py", {}).record(observed),
    ]
    edges = [
        Edge(mission_id, gate_id, EdgeType.DEPENDS_ON).record(),
        Edge(mission_id, note_id, EdgeType.DOCUMENTED_BY).record(),
        Edge(decision_id, note_id, EdgeType.DOCUMENTED_BY).record(),
        Edge(module_id, class_id, EdgeType.DEFINES).record(),
    ]
    store.apply(nodes, edges, source_prefix="obsidian")
    store.apply(nodes[4:], [edges[-1]], source_prefix="code")


@pytest.fixture
def graph_service(tmp_path: Path) -> GraphService:
    store = GraphStore(tmp_path / "graph.sqlite")
    seed_graph(store)
    return GraphService(store, tmp_path)


@pytest.fixture
def fake_serena() -> FakeSerena:
    return FakeSerena()
