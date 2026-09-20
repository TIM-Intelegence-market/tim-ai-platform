"""AgentContextPack, RepairContextPack, ContextBudget (STEPS 13-14, 19).

Packs are bounded by construction: every list is truncated to its budget
and the serialized pack is hard-capped at MAX_CONTEXT_CHARS. Packs carry
source provenance and never include secret paths or full dumps."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from src.agent_infra import PREFLIGHT_VERSION


@dataclass(frozen=True, slots=True)
class ContextBudget:
    MAX_SYMBOLS: int = 10
    MAX_REFERENCES: int = 20
    MAX_TESTS: int = 10
    MAX_GRAPH_NEIGHBORS: int = 50
    MAX_GRAPH_DEPTH: int = 4
    MAX_NOTES: int = 5
    MAX_INCIDENTS: int = 5
    MAX_CONTEXT_CHARS: int = 24000

    def policy(self) -> str:
        return ("TIM_CONTEXT_BUDGET_V1: symbols<=10, references<=20, tests<=10, "
                "graph_neighbors<=50, graph_depth<=4, notes<=5, incidents<=5, "
                "serialized pack<=24000 chars")


DEFAULT_BUDGET = ContextBudget()


def _bounded(items: list[Any], limit: int) -> tuple[list[Any], bool]:
    return items[:limit], len(items) > limit


@dataclass(slots=True)
class AgentContextPack:
    request_summary: str
    mission: dict[str, Any] | None = None
    gates: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    symbols: list[dict[str, Any]] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    tests: list[dict[str, Any]] = field(default_factory=list)
    incidents: list[dict[str, Any]] = field(default_factory=list)
    impact: dict[str, Any] | None = None
    decisions: list[dict[str, Any]] = field(default_factory=list)
    docs: list[str] = field(default_factory=list)
    tool_status: dict[str, Any] = field(default_factory=dict)
    safety_constraints: list[str] = field(default_factory=list)
    source_provenance: dict[str, str] = field(default_factory=dict)
    truncated: dict[str, bool] = field(default_factory=dict)
    version: str = PREFLIGHT_VERSION
    _budget: ContextBudget = field(default_factory=ContextBudget, repr=False)

    def enforce_budget(self) -> None:
        budget = self._budget
        for name in ("symbols", "references", "tests", "gates", "blockers",
                     "incidents", "decisions", "docs"):
            limit = {"symbols": budget.MAX_SYMBOLS,
                     "references": budget.MAX_REFERENCES,
                     "tests": budget.MAX_TESTS,
                     "incidents": budget.MAX_INCIDENTS,
                     "decisions": budget.MAX_NOTES, "docs": budget.MAX_NOTES,
                     }.get(name, budget.MAX_GRAPH_NEIGHBORS)
            items, was_truncated = _bounded(getattr(self, name), limit)
            setattr(self, name, items)
            if was_truncated:
                self.truncated[name] = True

    def to_dict(self) -> dict[str, Any]:
        payload = {k: v for k, v in asdict(self).items() if k != "_budget"}
        return payload

    def serialize(self) -> str:
        text = json.dumps(self.to_dict(), default=str, sort_keys=True)
        limit = self._budget.MAX_CONTEXT_CHARS
        if len(text) > limit:
            # keep the pack usable: drop bulky optional sections first
            for optional in ("references", "docs", "incidents"):
                if len(text) <= limit:
                    break
                setattr(self, optional, [])
                self.truncated[optional] = True
                text = json.dumps(self.to_dict(), default=str, sort_keys=True)
            if len(text) > limit:
                raise ValueError(
                    f"context pack exceeds MAX_CONTEXT_CHARS even after "
                    f"truncation ({len(text)} > {limit})")
        return text


@dataclass(slots=True)
class RepairContextPack:
    """Foundation for Mission 09.2 (Bugfixer / Self-Healing). Data contract
    only — no repair automation lives here."""

    incident: dict[str, Any]
    fingerprint: str
    classification: str
    affected_graph_nodes: list[str] = field(default_factory=list)
    affected_symbols: list[dict[str, Any]] = field(default_factory=list)
    tests: list[dict[str, Any]] = field(default_factory=list)
    prior_repairs: list[dict[str, Any]] = field(default_factory=list)
    mission_gates: list[dict[str, Any]] = field(default_factory=list)
    safety_constraints: list[str] = field(default_factory=list)
    source_provenance: dict[str, str] = field(default_factory=dict)

    REQUIRED_FIELDS = ("incident", "fingerprint", "classification",
                       "affected_graph_nodes", "affected_symbols", "tests",
                       "prior_repairs", "mission_gates", "safety_constraints")

    def validate(self) -> list[str]:
        problems = []
        for name in self.REQUIRED_FIELDS:
            value = getattr(self, name)
            if value is None or value == "" or value == {}:
                problems.append(f"missing required field: {name}")
            # empty lists are legitimate (e.g. no prior repairs yet)
        return problems

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
