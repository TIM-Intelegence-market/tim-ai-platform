from __future__ import annotations

from typing import Any,TypedDict

from langgraph.graph import END,START,StateGraph

from src.research.module_a.agent import LocalResearchAgent,ResearchResult


class ResearchGraphState(TypedDict,total=False):
    question:str;evidence:list[dict[str,Any]];validated:bool;result:ResearchResult;status:str


class DeterministicResearchGraph:
    """Real LangGraph workflow with deterministic TIM nodes only."""
    def __init__(self,agent:LocalResearchAgent|None=None)->None:self.agent=agent or LocalResearchAgent();self.graph=self._build()
    def _build(self):
        workflow=StateGraph(ResearchGraphState);workflow.add_node("validate",self._validate);workflow.add_node("analyze",self._analyze);workflow.add_node("finalize",self._finalize);workflow.add_edge(START,"validate");workflow.add_edge("validate","analyze");workflow.add_edge("analyze","finalize");workflow.add_edge("finalize",END);return workflow.compile()
    @staticmethod
    def _validate(state:ResearchGraphState)->dict[str,Any]:
        question=str(state.get("question","")).strip();evidence=state.get("evidence",[])
        if not question:raise ValueError("question is required")
        if not isinstance(evidence,list):raise ValueError("evidence must be a list")
        return {"question":question,"evidence":evidence,"validated":True}
    def _analyze(self,state:ResearchGraphState)->dict[str,Any]:return {"result":self.agent.analyze(state["question"],state["evidence"])}
    @staticmethod
    def _finalize(_:ResearchGraphState)->dict[str,Any]:return {"status":"COMPLETED"}
    def invoke(self,state:dict[str,Any])->ResearchResult:
        completed=self.graph.invoke(state);return completed["result"]
