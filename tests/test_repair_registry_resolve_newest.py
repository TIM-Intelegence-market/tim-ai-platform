import copy
from pathlib import Path

from src.bugfixer.processing import Event
from src.bugfixer.remediation import load_registry
from src.repair_registry.resolve import PlanOutcome, resolve_plan

ROOT = Path(__file__).resolve().parents[1]
RECIPE = copy.deepcopy(load_registry(ROOT / "schemas/bugfixer/remediations.v2.json")[0])
EVENT = Event("2026-09-09T00:00:00+00:00", "collector", "TimeoutError", "network timeout")
ATTEST = dict.fromkeys(RECIPE["preconditions"], True)


def _variant(**changes):
    recipe = copy.deepcopy(RECIPE)
    recipe.update(changes)
    return recipe


OLD = _variant(version="1.0.0")
NEW = _variant(version="2.1.0", confidence=0.5)
ALT = _variant(remediation_id="NETWORK_TIMEOUT_ALT")


def _resolve(registry):
    result = resolve_plan(EVENT, copy.deepcopy(registry), satisfied_preconditions=ATTEST)
    assert result["executed"] is False and result["may_mark_fixed"] is False
    return result


def _assert_no_fallback(result):
    assert result["outcome"] == PlanOutcome.BLOCKED
    assert result["plan"] is None and result["candidates"] == []
    assert result["superseded"] == ["NETWORK_TIMEOUT@2.1.0"]
    assert "no fallback" in result["reason"]


def test_blocked_newest_version_never_falls_back_to_older():
    _assert_no_fallback(_resolve([OLD, NEW]))


def test_order_of_registry_does_not_matter():
    _assert_no_fallback(_resolve([NEW, OLD]))


def test_other_eligible_recipe_does_not_hide_the_block():
    result = _resolve([OLD, NEW, ALT])
    assert result["outcome"] == PlanOutcome.BLOCKED and result["plan"] is None


def test_blocked_newest_alone_is_blocked_without_superseded():
    result = _resolve([NEW])
    assert result["outcome"] == PlanOutcome.BLOCKED and result["superseded"] == []


def test_eligible_newest_version_still_resolves():
    result = _resolve([OLD, RECIPE])
    assert result["outcome"] == PlanOutcome.RESOLVED
    assert result["plan"]["version"] == "2.0.0" and result["superseded"] == []


def test_newer_review_only_version_blocks_older_proposal():
    newer = _variant(version="2.1.0", autonomy_level="A3", risk="HIGH", actions=["isolated_code_patch"])
    result = _resolve([OLD, newer])
    assert result["outcome"] == PlanOutcome.BLOCKED and result["outcome"] != PlanOutcome.RESOLVED
    assert result["superseded"] == ["NETWORK_TIMEOUT@2.1.0"]


def test_newer_observe_only_version_blocks_older_proposal():
    newer = _variant(version="2.1.0", autonomy_level="A0")
    result = _resolve([OLD, newer])
    assert result["outcome"] == PlanOutcome.BLOCKED and result["plan"] is None
    assert result["superseded"] == ["NETWORK_TIMEOUT@2.1.0"]
