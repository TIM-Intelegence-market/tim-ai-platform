from copy import deepcopy
from pathlib import Path

import pytest

from src.bugfixer.remediation import load_registry
from src.repair_registry.versioning import (
    RegistryUpgradeError,
    check_registry_upgrade,
    latest_versions,
    recipe_digest,
)

REGISTRY = Path(__file__).resolve().parents[1] / "schemas/bugfixer/remediations.v2.json"


def _recipe():
    return deepcopy(load_registry(REGISTRY)[0])


def test_same_list_is_unchanged():
    result = check_registry_upgrade([_recipe()], [_recipe()])
    assert result["added"] == []
    assert result["removed"] == []
    assert result["unchanged"] == ["NETWORK_TIMEOUT@2.0.0"]
    assert result["requires_review"] is False


def test_recipe_digest_is_stable_across_key_order():
    row = _recipe()
    reversed_row = {k: row[k] for k in reversed(list(row))}
    assert recipe_digest(row) == recipe_digest(reversed_row)


def test_recipe_digest_changes_with_confidence():
    row = _recipe()
    changed = deepcopy(row)
    changed["confidence"] = 0.5 if row["confidence"] != 0.5 else 0.6
    assert recipe_digest(row) != recipe_digest(changed)


def test_changed_recipe_without_version_bump_raises():
    old = _recipe()
    new = deepcopy(old)
    new["confidence"] = 0.5 if old["confidence"] != 0.5 else 0.6
    with pytest.raises(RegistryUpgradeError, match="without version bump"):
        check_registry_upgrade([old], [new])


def test_added_higher_version_is_reported():
    old = _recipe()
    newer = deepcopy(old)
    newer["version"] = "2.1.0"
    result = check_registry_upgrade([old], [old, newer])
    assert result["added"] == ["NETWORK_TIMEOUT@2.1.0"]
    assert result["removed"] == []


def test_added_lower_version_raises():
    old = _recipe()
    lower = deepcopy(old)
    lower["version"] = "1.5.0"
    with pytest.raises(RegistryUpgradeError, match="new version must be higher"):
        check_registry_upgrade([old], [old, lower])


def test_brand_new_remediation_id_is_accepted():
    old = _recipe()
    fresh = deepcopy(old)
    fresh["remediation_id"] = "NEW_RECIPE"
    fresh["version"] = "1.0.0"
    result = check_registry_upgrade([old], [old, fresh])
    assert result["added"] == ["NEW_RECIPE@1.0.0"]


def test_removed_recipe_requires_review():
    old = _recipe()
    other = deepcopy(old)
    other["remediation_id"] = "NEW_RECIPE"
    other["version"] = "1.0.0"
    result = check_registry_upgrade([old, other], [old])
    assert result["removed"] == ["NEW_RECIPE@1.0.0"]
    assert result["requires_review"] is True


def test_invalid_entry_raises_value_error():
    old = _recipe()
    bad = deepcopy(old)
    del bad["rollback"]
    with pytest.raises(ValueError):
        check_registry_upgrade([old], [bad])


def test_latest_versions_compares_numerically():
    entries = [
        {"remediation_id": "NETWORK_TIMEOUT", "version": "2.0.0"},
        {"remediation_id": "NETWORK_TIMEOUT", "version": "2.1.0"},
    ]
    assert latest_versions(entries) == {"NETWORK_TIMEOUT": "2.1.0"}
    numeric = [
        {"remediation_id": "X", "version": "2.9.0"},
        {"remediation_id": "X", "version": "2.10.0"},
    ]
    assert latest_versions(numeric) == {"X": "2.10.0"}
