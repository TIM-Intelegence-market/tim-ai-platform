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
        "superseded": [],
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

    # Only the newest version of each recipe counts; an ineligible newest version never
    # falls back to an older one that happens to pass the gates.
    newest = {}
    for gate in gates:
        current = newest.get(gate["remediation_id"])
        if current is None or _version_key(gate["version"]) > _version_key(current["version"]):
            newest[gate["remediation_id"]] = gate
    rows = {}
    for proposal in r.get("proposals") or []:
        recipe = _recipe(proposal)
        rows[(recipe["remediation_id"], recipe["version"])] = recipe
    proposed_ids = {rid for rid, _ in rows}
    superseded = sorted(
        f"{rid}@{gate['version']}"
        for rid, gate in newest.items()
        if gate.get("decision") != "PROPOSED" and rid in proposed_ids
    )
    if superseded:
        result["superseded"] = superseded
        return done(
            PlanOutcome.BLOCKED,
            "newest recipe version not eligible; no fallback to older version: "
            + ", ".join(superseded),
        )
    latest = {
        rid: rows[(rid, gate["version"])]
        for rid, gate in newest.items()
        if gate.get("decision") == "PROPOSED" and (rid, gate["version"]) in rows
    }
    if not latest:
        decisions = [g.get("decision") for g in newest.values()]
        if "REVIEW_REQUIRED" in decisions:
            return done(PlanOutcome.REVIEW_REQUIRED, "manual review required")
        if all(d == "OBSERVE_ONLY" for d in decisions):
            return done(PlanOutcome.OBSERVE_ONLY, "observation only")
        return done(PlanOutcome.BLOCKED, "no proposal passed the gates")

    result["candidates"] = sorted([rid, rec["version"]] for rid, rec in latest.items())
    if len(latest) > 1:
        return done(PlanOutcome.AMBIGUOUS, "multiple remediations match")

    recipe = next(iter(latest.values()))
    result["plan"] = copy.deepcopy({k: recipe[k] for k in PLAN_FIELDS if k in recipe})
    return done(PlanOutcome.RESOLVED, "single remediation resolved")
