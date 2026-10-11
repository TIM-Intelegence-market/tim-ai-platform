"""Local-first TIM worker primitives.

The local runtime owns normal execution. External providers are escalation-only and
must never become the authority for safety or final task state.
"""

from .runtime import (
    BlockerMailbox,
    LocalPrimaryWorker,
    LocalTask,
    RepairRecipe,
    RepairRecipeStore,
    SafetyDecision,
    SafetyGate,
)

__all__ = [
    "BlockerMailbox",
    "LocalPrimaryWorker",
    "LocalTask",
    "RepairRecipe",
    "RepairRecipeStore",
    "SafetyDecision",
    "SafetyGate",
]
