"""PR gate: worker PRs may not touch src/tim_incident/, the reporter's protection logic (design E8)."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.pr_gate import Entry, evaluate, load_policy

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / ".github" / "pr-gate-policy.json"


def test_policy_lists_tim_incident_as_denied() -> None:
    policy = load_policy(POLICY_PATH)
    assert "src/tim_incident/" in policy["deny_prefixes"]
    assert "src/" in policy["allow_prefixes"]  # the deny entry is what keeps it out, not a missing allow


@pytest.mark.parametrize(
    ("status", "old_mode", "new_mode", "path"),
    [
        ("M", "100644", "100644", "src/tim_incident/checkup.py"),
        ("M", "100644", "100644", "src/tim_incident/redaction.py"),
        ("A", "000000", "100644", "src/tim_incident/helper.py"),
        ("D", "100644", "000000", "src/tim_incident/policy.py"),
        ("M", "100644", "100644", "SRC/Tim_Incident/github.py"),
    ],
)
def test_pr_gate_denies_tim_incident(status: str, old_mode: str, new_mode: str, path: str) -> None:
    violations = evaluate([Entry(old_mode, new_mode, status, path)], load_policy(POLICY_PATH))
    assert any("protected path" in violation for violation in violations), violations


def test_pr_gate_rejects_a_mixed_diff_that_touches_the_checkup() -> None:
    entries = [Entry("100644", "100644", "M", "src/agents/review.py"),
               Entry("100644", "100644", "M", "src/tim_incident/checkup.py")]
    violations = evaluate(entries, load_policy(POLICY_PATH))
    assert violations == ["src/tim_incident/checkup.py: protected path"]


def test_neighbouring_source_paths_stay_allowed() -> None:
    policy = load_policy(POLICY_PATH)
    assert evaluate([Entry("100644", "100644", "M", "src/agents/review.py")], policy) == []
    assert evaluate([Entry("000000", "100644", "A", "src/tim_incident_notes.py")], policy) == []


def test_src_package_init_is_denied() -> None:
    # src/__init__.py runs on every import inside the key-holding checkup process
    policy = load_policy(POLICY_PATH)
    violations = evaluate([Entry("100644", "100644", "M", "src/__init__.py")], policy)
    assert violations == ["src/__init__.py: protected path"]
    assert evaluate([Entry("100644", "100644", "M", "src/agents/__init__.py")], policy) == []
