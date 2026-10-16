"""Resolve a single remediation plan for an event without executing anything."""

import copy
import enum

from src.bugfixer.processing import fingerprint
from src.bugfixer.remediation import dry_run
from src.bugfixer.safety import Policy


class PlanOutcome(enum.StrEnum):
    RESOLVED = "RESOLVED"
    NO_MATCH = "NO_MATCH"
    AMBIGUOUS = "AMBIGUOUS"
    BLOCKED = "BLOCKED"
    ESCALATE = "ESCALATE"
    OBSERVE_ONLY = "OBSERVE_ONLY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


PLAN_FIELDS = (
    "remediation_id",
    "version",
    "autonomy_level",
    "risk",
    "preconditions",
    "actions",
    "forbidden_actions",
    "rollback",
    "targeted_tests",
    "runtime_verification",
    "integrity_verification",
    "recurrence_check",
)


def _version_key(version):
    return tuple(int(x) for x in str(version).split("."))


def _recipe(proposal):
    inner = proposal.get("recipe")
    return inner if isinstance(inner, dict) else proposal


def resolve_plan(event, registry, policy=Policy(), *, satisfied_preconditions=None):
    r = dry_run(
        event, registry, policy, satisfied_preconditions=satisfied_preconditions
    )
    gates = r.get("gates", [])
    result = {
        "outcome": PlanOutcome.BLOCKED,
        "reason": "",
        "category": str(r["category"]),
        "fingerprint": fingerprint(event),
        "plan": None,
        "candidates": [],
        "gates": gates,
        "executed": False,
        "may_mark_fixed": False,
        "requires_verification_gates": True,
    }

    def done(outcome, reason):
        result["outcome"] = outcome
        result["reason"] = reason
        return result

    if r.get("legacy_registry"):
        return done(PlanOutcome.BLOCKED, "legacy registry cannot be resolved")
    if r.get("safe_stop"):
        return done(PlanOutcome.ESCALATE, "safe stop requested")
    if not gates:
        return done(PlanOutcome.NO_MATCH, "no remediation matches the event")

    proposals = r.get("proposals")
    if not proposals:
        decisions = [g.get("decision") for g in gates]
        if "REVIEW_REQUIRED" in decisions:
            return done(PlanOutcome.REVIEW_REQUIRED, "manual review required")
        if all(d == "OBSERVE_ONLY" for d in decisions):
            return done(PlanOutcome.OBSERVE_ONLY, "observation only")
        return done(PlanOutcome.BLOCKED, "no proposal passed the gates")

    latest = {}
    for proposal in proposals:
        recipe = _recipe(proposal)
        rid = recipe["remediation_id"]
        current = latest.get(rid)
        if current is None or _version_key(recipe["version"]) > _version_key(
            current["version"]
        ):
            latest[rid] = recipe

    result["candidates"] = sorted([rid, rec["version"]] for rid, rec in latest.items())
    if len(latest) > 1:
        return done(PlanOutcome.AMBIGUOUS, "multiple remediations match")

    recipe = next(iter(latest.values()))
    result["plan"] = copy.deepcopy({k: recipe[k] for k in PLAN_FIELDS if k in recipe})
    return done(PlanOutcome.RESOLVED, "single remediation resolved")
