"""Agent profiles (STEPS 17, 21-24): OpenCode, GLM, Qwen.

Profiles bound preferred/allowed/fallback tools, write authority and
forbidden actions. The Tool Router never grants write authority — these
profiles are the reference for what a worker MAY do, not what routing
implies."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AgentProfile:
    name: str
    role: str
    preferred_tools: tuple[str, ...]
    fallback_tools: tuple[str, ...]
    write_authority: str
    forbidden_actions: tuple[str, ...] = field(default_factory=tuple)


COMMON_FORBIDDEN = (
    "production_db_writes", "production_ddl", "tim_runtime_restart",
    "queue_or_outbox_mutation", "attempt_reset", "trading_actions",
    "order_creation", "secret_exposure", "unrelated_git_staging",
    "git_merge_or_push_without_authorization",
)

OPENCODE = AgentProfile(
    name="OpenCode",
    role="primary implementation worker",
    preferred_tools=("Serena", "TIMGraphMCP", "pytest"),
    fallback_tools=("NativeSearch",),
    write_authority="isolated worker worktree only (e.g. "
                    "worktrees/agent-infrastructure-v1); never the "
                    "productive checkout",
    forbidden_actions=COMMON_FORBIDDEN,
)

GLM = AgentProfile(
    name="GLM",
    role="terminal investigation, bounded engineering, heavy local analysis",
    preferred_tools=("Serena", "TIMGraphMCP", "Graphify"),
    fallback_tools=("NativeSearch", "pytest"),
    write_authority="isolated worktree only unless separately authorized",
    forbidden_actions=COMMON_FORBIDDEN,
)

QWEN = AgentProfile(
    name="Qwen",
    role="diagnosis, challenge, independent review (read-only)",
    preferred_tools=("AgentContextPack",),
    fallback_tools=(),
    write_authority="none — read-only reviewer; receives bounded "
                    "AgentContextPack, never a repository dump",
    forbidden_actions=(*COMMON_FORBIDDEN, "blind_full_repository_parsing",
                       "silent_model_substitution"),
)

PROFILES = {profile.name: profile for profile in (OPENCODE, GLM, QWEN)}
