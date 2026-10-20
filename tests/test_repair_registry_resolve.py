import copy
from pathlib import Path

from src.bugfixer.remediation import RegistryEntries, load_registry
from src.repair_registry.resolve import PlanOutcome, resolve_plan

try:
    from src.bugfixer.models import Event
except ImportError:  # pragma: no cover
    try:
        from src.bugfixer.processing import Event
    except ImportError:
        from src.bugfixer.remediation import Event

ROOT = Path(__file__).resolve().parents[1]
RECIPE = copy.deepcopy(
    load_registry(ROOT / "schemas/bugfixer/remediations.v2.json")[0]
)
EVENT = Event(
    "2026-09-09T00:00:00+00:00", "collector", "TimeoutError", "network timeout"
)
ATTEST = dict.fromkeys(RECIPE["preconditions"], True)


def _resolve(registry, event=EVENT, attest=ATTEST):
    return resolve_plan(event, registry, satisfied_preconditions=attest)


def test_attested_recipe_resolves():
    res = _resolve([copy.deepcopy(RECIPE)])
    assert res["outcome"] == PlanOutcome.RESOLVED
    assert res["plan"]["remediation_id"] == "NETWORK_TIMEOUT"
    assert res["plan"]["rollback"] == RECIPE["rollback"]
    assert res["executed"] is False
    assert res["may_mark_fixed"] is False


def test_highest_version_wins():
    old = copy.deepcopy(RECIPE)
    old["version"] = "1.0.0"
    res = _resolve([old, copy.deepcopy(RECIPE)])
    assert res["outcome"] == PlanOutcome.RESOLVED
    assert res["plan"]["version"] == "2.0.0"


def test_two_remediation_ids_are_ambiguous():
    alt = copy.deepcopy(RECIPE)
    alt["remediation_id"] = "NETWORK_TIMEOUT_ALT"
    res = _resolve([copy.deepcopy(RECIPE), alt])
    assert res["outcome"] == PlanOutcome.AMBIGUOUS
    assert res["plan"] is None
    assert res["candidates"] == [
        ["NETWORK_TIMEOUT", "2.0.0"],
        ["NETWORK_TIMEOUT_ALT", "2.0.0"],
    ]


def test_non_matching_rule_is_no_match():
    other = copy.deepcopy(RECIPE)
    other["matching_rules"]["exception"] = "OtherError"
    assert _resolve([other])["outcome"] == PlanOutcome.NO_MATCH


def test_missing_attestation_is_blocked():
    res = _resolve([copy.deepcopy(RECIPE)], attest=None)
    assert res["outcome"] == PlanOutcome.BLOCKED


def test_invariant_violation_escalates():
    event = Event("2026-09-09T00:00:00+00:00", "collector", "", "invariant violation")
    assert _resolve([copy.deepcopy(RECIPE)], event)["outcome"] == PlanOutcome.ESCALATE


def test_high_risk_patch_requires_review():
    recipe = copy.deepcopy(RECIPE)
    recipe["autonomy_level"] = "A3"
    recipe["risk"] = "HIGH"
    recipe["actions"] = ["isolated_code_patch"]
    assert _resolve([recipe])["outcome"] == PlanOutcome.REVIEW_REQUIRED


def test_observe_recipe_is_observe_only():
    recipe = copy.deepcopy(RECIPE)
    recipe["autonomy_level"] = "A0"
    recipe["actions"] = ["observe"]
    assert _resolve([recipe])["outcome"] == PlanOutcome.OBSERVE_ONLY


def test_legacy_registry_is_blocked():
    assert resolve_plan(EVENT, [])["outcome"] == PlanOutcome.BLOCKED


def test_empty_v2_registry_is_no_match():
    res = resolve_plan(EVENT, RegistryEntries([], 2))
    assert res["outcome"] == PlanOutcome.NO_MATCH


def test_later_timestamp_gives_same_result():
    later = Event(
        "2027-01-01T00:00:00+00:00", "collector", "TimeoutError", "network timeout"
    )
    first = _resolve([copy.deepcopy(RECIPE)])
    second = _resolve([copy.deepcopy(RECIPE)], later)
    assert second == first
