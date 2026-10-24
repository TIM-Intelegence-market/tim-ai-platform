"""Evidence status of a pipeline setup, read from the hypothesis register.

The orderflow pipeline grades scenarios heuristically (rule quality). Whether a
setup family has an empirical edge is a different question, answered only by
the research protocol (train -> validation -> one holdout run) whose attempts
live in the append-only register docs/research_lab/REGISTER.jsonl.

This module is fail closed: a scenario type inherits a register verdict only
through an explicit, versioned rule equivalence in RULE_EQUIVALENCES. A name
that merely sounds alike (REJECTION_FAILED_BREAKOUT vs. T2-rejection) is not
an equivalence, because the pipeline scenarios are built from other rules than
the registered strategies. With no equivalence the status is
INSUFFICIENT_EVIDENCE. The entry model (LIMIT_RETEST, FAILED_RETEST, ...) never
creates a mapping. Execution stays RESEARCH_ONLY in every case; an execution
approval is a separate human step that this module does not model.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.research_lab.protocol import PROTOCOL_VERSION
from src.research_lab.stats.register import GENESIS, HypothesisRegister, RegisterError

DEFAULT_REGISTER_PATH = Path("docs/research_lab/REGISTER.jsonl")

# Version of the equivalence table below. Bump it with every change; the
# journal stores it next to each verdict.
EVIDENCE_MAPPING_VERSION = "setup-evidence-mapping/0"
# (scenario_type, timeframe) -> register variant ids whose rule is the same as
# the pipeline rule. Empty by design: no equivalence has been reviewed yet.
RULE_EQUIVALENCES: dict[tuple[str, str], tuple[str, ...]] = {}

INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
NEGATIVE_EVIDENCE = "NEGATIVE_EVIDENCE"
CANDIDATE_FROZEN = "CANDIDATE_FROZEN"
PASSED_HOLDOUT = "PASSED_HOLDOUT"
STATUSES = (INSUFFICIENT_EVIDENCE, NEGATIVE_EVIDENCE, CANDIDATE_FROZEN, PASSED_HOLDOUT)
RESEARCH_ONLY = "RESEARCH_ONLY"

NO_EXPLICIT_RULE_EQUIVALENCE = "NO_EXPLICIT_RULE_EQUIVALENCE"
REGISTER_MISSING = "REGISTER_MISSING"
REGISTER_UNREADABLE = "REGISTER_UNREADABLE"
FAILED = {"failed_train", "failed_validation", "failed_holdout"}


@dataclass(frozen=True, slots=True)
class EvidenceVerdict:
    status: str
    scenario_type: str
    timeframe: str
    variant_ids: tuple[str, ...]
    variant_statuses: dict[str, str]
    register_head_hash: str
    register_path: str
    register_events: int
    mapping_version: str
    protocol_version: str
    reason: str
    execution_status: str = RESEARCH_ONLY

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown evidence status {self.status}")
        if self.status != INSUFFICIENT_EVIDENCE and not self.variant_ids:
            raise ValueError(f"{self.status} needs at least one register variant")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["variant_ids"] = list(self.variant_ids)
        return data


def register_head(path: Path | str = DEFAULT_REGISTER_PATH) -> tuple[str, int]:
    """Head hash and event count of the register; raises RegisterError on a broken chain."""
    events = HypothesisRegister(path).events()
    return (events[-1]["hash"] if events else GENESIS), len(events)


def _status_from(statuses: dict[str, str]) -> tuple[str, str]:
    values = set(statuses.values())
    if values & FAILED:
        return NEGATIVE_EVIDENCE, "registered equivalent variant failed: " + ", ".join(sorted(v for v in statuses if statuses[v] in FAILED))
    if values == {"passed_holdout"}:
        return PASSED_HOLDOUT, "every equivalent variant passed the holdout (no execution approval implied)"
    if values == {"candidate"}:
        return CANDIDATE_FROZEN, "equivalent variants are frozen candidates; the holdout has not decided"
    return INSUFFICIENT_EVIDENCE, "equivalent variants without a final positive verdict: " + ", ".join(f"{k}={v}" for k, v in sorted(statuses.items()))


def evidence_status(
    scenario_type: str,
    timeframe: str,
    register_path: Path | str = DEFAULT_REGISTER_PATH,
    *,
    entry_model: str | None = None,
    equivalences: dict[tuple[str, str], tuple[str, ...]] | None = None,
) -> EvidenceVerdict:
    """Verdict for one scenario type and timeframe. `entry_model` is accepted
    only so that callers cannot forget that it does not influence the result."""
    del entry_model  # never part of the mapping key
    table = RULE_EQUIVALENCES if equivalences is None else equivalences
    path = Path(register_path)
    head, count = register_head(path)  # RegisterError on a broken chain: no verdict
    variant_ids = tuple(table.get((str(scenario_type), str(timeframe)), ()))
    common = {
        "scenario_type": str(scenario_type), "timeframe": str(timeframe), "register_head_hash": head,
        "register_path": str(path), "register_events": count, "mapping_version": EVIDENCE_MAPPING_VERSION,
        "protocol_version": PROTOCOL_VERSION,
    }
    if not path.exists():
        return EvidenceVerdict(status=INSUFFICIENT_EVIDENCE, variant_ids=(), variant_statuses={}, reason=REGISTER_MISSING, **common)
    if not variant_ids:
        return EvidenceVerdict(status=INSUFFICIENT_EVIDENCE, variant_ids=(), variant_statuses={}, reason=NO_EXPLICIT_RULE_EQUIVALENCE, **common)
    known = HypothesisRegister(path).variants()
    unknown = [v for v in variant_ids if v not in known]
    if unknown:
        raise RegisterError(f"equivalence table names unregistered variants: {unknown}")
    statuses = {v: known[v]["status"] for v in variant_ids}
    status, reason = _status_from(statuses)
    return EvidenceVerdict(status=status, variant_ids=variant_ids, variant_statuses=statuses, reason=reason, **common)


def evidence_fields(scenario_type: str, timeframe: str, register_path: Path | str = DEFAULT_REGISTER_PATH) -> dict[str, Any]:
    """Journal fields for a plan. A broken register gives no verdict; the plan
    is then recorded fail closed with the error named, never with a status
    that looks like a verdict."""
    try:
        verdict = evidence_status(scenario_type, timeframe, register_path)
    except RegisterError as error:
        return {
            "evidence_status": INSUFFICIENT_EVIDENCE,
            "evidence_ref": {
                "scenario_type": str(scenario_type), "timeframe": str(timeframe), "variant_ids": [],
                "register_path": str(register_path), "mapping_version": EVIDENCE_MAPPING_VERSION,
                "protocol_version": PROTOCOL_VERSION, "reason": f"{REGISTER_UNREADABLE}: {error}",
            },
            "execution_status": RESEARCH_ONLY,
        }
    ref = verdict.to_dict()
    ref.pop("status")
    ref.pop("execution_status")
    return {"evidence_status": verdict.status, "evidence_ref": ref, "execution_status": verdict.execution_status}
