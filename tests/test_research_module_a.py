from pathlib import Path

from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph

from src.research.config import ResearchConfig
from src.research.module_a.agent import LocalResearchAgent
from src.research.module_a.graph import DeterministicResearchGraph


def test_module_a_dependencies_and_deterministic_core(tmp_path:Path)->None:
    assert ChatOllama is not None and StateGraph is not None
    agent=LocalResearchAgent(ResearchConfig(cache_path=tmp_path/"cache.jsonl",report_root=tmp_path/"reports"))
    evidence=[{"summary":"documented rejection","source":"TIM","provenance":"PUBLIC_MARKET_DATA_DETERMINISTIC"}];result=agent.analyze("review",evidence)
    assert result.module=="A" and result.patterns==["rejection"]
    graph_result=DeterministicResearchGraph(agent).invoke({"question":"review","evidence":evidence})
    assert graph_result.input_hash==result.input_hash
