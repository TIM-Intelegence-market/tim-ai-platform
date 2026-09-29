"""Shared agent contract for TIM agents (Constitution Band 5, Master Prompt 09).

Agents communicate only through versioned tasks and immutable, hashed
messages. Every agent declares an AgentSpec before it may act.
"""

from .contract import (
    SCHEMA_VERSION,
    AgentSpec,
    Message,
    PolicyViolation,
    ReplayMismatch,
    RunRecord,
    TaskRecord,
    TaskStatus,
    canonical_json,
    content_hash,
    replay,
    run_task,
)

__all__ = [
    "SCHEMA_VERSION",
    "AgentSpec",
    "Message",
    "PolicyViolation",
    "ReplayMismatch",
    "RunRecord",
    "TaskRecord",
    "TaskStatus",
    "canonical_json",
    "content_hash",
    "replay",
    "run_task",
]
