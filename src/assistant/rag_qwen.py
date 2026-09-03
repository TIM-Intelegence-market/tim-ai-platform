from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from src.llm.ollama_client import OllamaClient
from src.memory.market_memory import MarketMemory
from src.models.market_data import Observation
from src.research.case_engine import ResearchCaseEngine

@dataclass(frozen=True, slots=True)
class RAGContext:
    query: str
    similar: tuple
    cases: tuple
    memory_size: int
    provenance: str = "PUBLIC_MARKET_DATA_DETERMINISTIC + RAG_JACCARD"

@dataclass(frozen=True, slots=True)
class RAGAnswer:
    generated_at: str
    query: str
    answer: str
    citations: tuple
    context: RAGContext
    model: str
    via: str
    limitation: str = "RAG explanation only; no signal, no order, via OmniRoute/Ollama."

class RAGQwenAssistant:
    """RAG über Research Cases + Market Memory, Qwen via OmniRoute/Ollama, OBSERVE-only."""

    def __init__(self, memory: MarketMemory, cases: ResearchCaseEngine, ollama: OllamaClient, via: str = "ollama-local/qwen2.5:7b via OmniRoute"):
        self.memory = memory
        self.cases = cases
        self.ollama = ollama
        self.via = via

    def build_context(self, query: str, anchor: Observation | None = None) -> RAGContext:
        # Use anchor observation if provided, else build dummy for RAG search
        if anchor:
            similar = tuple(self.memory.similar(anchor, limit=5))
            # Find cases containing similar observations
            case_ids = {str(c.case_id) for c in self.cases.cases.values() if any(str(o.observation_id) in [str(s.observation.observation_id) for s in similar] for o in [anchor])}
            cases = tuple(self.cases.cases[c] for c in case_ids if c in self.cases.cases)
        else:
            similar = ()
            cases = tuple(list(self.cases.cases.values())[-3:])
        return RAGContext(query=query, similar=similar, cases=cases, memory_size=self.memory.size)

    async def ask(self, query: str, anchor: Observation | None = None) -> RAGAnswer:
        ctx = self.build_context(query, anchor)
        # Build prompt with citations, no trading terms
        similar_str = "\n".join(f"- {s.observation.kind.value} {s.observation.symbol} {s.observation.timeframe} sim={s.similarity} evidence={s.observation.evidence}" for s in ctx.similar) or "No similar observations (memory empty or no match)."
        cases_str = "\n".join(f"- case {c.case_id} {c.status} obs={len(c.observation_ids)} missing={c.missing_evidence}" for c in ctx.cases) or "No research cases."
        prompt = f"""You are TIM RAG assistant, OBSERVE-only. Answer in German, one paragraph, no buy/sell/order/signal.

Query: {query}

Similar observations (Jaccard, deterministic):
{similar_str}

Research cases (30m containers):
{cases_str}

Memory size: {ctx.memory_size}
Provenance: {ctx.provenance}

Rules: Cite observation_ids, mention conflicts if any, state limitation. Do not invent market facts.
Respond as JSON: {{"answer": "...", "citations": ["obs_id1", ...]}}"""

        try:
            result = await self.ollama.generate_json(prompt)
            answer = str(result.get("answer", ""))[:2000]
            citations = tuple(str(c) for c in result.get("citations", [])[:10])
        except Exception as e:
            answer = f"RAG Kontext bereit, LLM nicht verfügbar: {e}. Similar: {len(ctx.similar)}, Cases: {len(ctx.cases)}"
            citations = tuple(str(s.observation.observation_id) for s in ctx.similar[:3])
        return RAGAnswer(
            generated_at=datetime.now(timezone.utc).isoformat(),
            query=query,
            answer=answer,
            citations=citations,
            context=ctx,
            model=self.ollama.model,
            via=self.via,
        )
