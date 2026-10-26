"""#16: the shipped registry is checked against its version history and provenance on every CI run."""
import copy
import json
from pathlib import Path

import pytest

from src.bugfixer.remediation import load_registry
from src.repair_registry.provenance import (check_history, check_provenance, load_history, load_provenance)
from src.repair_registry.versioning import RegistryUpgradeError, recipe_digest

REGISTRY = Path(__file__).resolve().parents[1] / 'schemas' / 'bugfixer' / 'remediations.v2.json'


@pytest.fixture
def entries():
    return [dict(e) for e in load_registry(REGISTRY)]


def test_shipped_registry_matches_its_history(entries):
    report = check_history(entries, load_history())
    assert report['checked'] == sorted(f"{e['remediation_id']}@{e['version']}" for e in entries)


def test_shipped_registry_has_complete_provenance(entries):
    statuses = check_provenance(entries, load_provenance())
    assert set(statuses) == {f"{e['remediation_id']}@{e['version']}" for e in entries}


def test_a_changed_recipe_without_version_bump_fails(entries):
    changed = copy.deepcopy(entries)
    changed[0]['confidence'] = 0.99
    with pytest.raises(RegistryUpgradeError, match='without version bump'):
        check_history(changed, load_history())


def test_a_new_version_must_be_recorded_and_higher(entries):
    bumped = copy.deepcopy(entries)
    bumped[0]['version'] = '2.1.0'
    with pytest.raises(RegistryUpgradeError, match='not recorded'):
        check_history(bumped, load_history())
    history = dict(load_history())
    history[f"{bumped[0]['remediation_id']}@2.1.0"] = recipe_digest(bumped[0])
    assert check_history(bumped, history)['retired'] == [f"{entries[0]['remediation_id']}@2.0.0"]
    lower = dict(history)
    lower[f"{bumped[0]['remediation_id']}@1.9.0"] = 'f' * 64
    with pytest.raises(RegistryUpgradeError, match='must be higher'):
        check_history(bumped, lower)


def test_provenance_must_name_the_same_digest_and_cite_evidence(entries):
    provenance = copy.deepcopy(load_provenance())
    label = f"{entries[0]['remediation_id']}@{entries[0]['version']}"
    provenance[label]['digest'] = '0' * 64
    with pytest.raises(ValueError, match='another digest'):
        check_provenance(entries, provenance)
    provenance = copy.deepcopy(load_provenance())
    provenance[label]['evidence_status'] = 'REPRODUCED'
    provenance[label]['evidence_refs'] = []
    with pytest.raises(ValueError, match='without a reference'):
        check_provenance(entries, provenance)
    provenance = copy.deepcopy(load_provenance())
    del provenance[label]
    with pytest.raises(ValueError, match='no complete provenance'):
        check_provenance(entries, provenance)


def test_evidence_references_point_at_existing_files():
    root = Path(__file__).resolve().parents[1]
    for row in load_provenance().values():
        for ref in row['evidence_refs']:
            assert (root / ref.split('#', 1)[0]).is_file(), ref


def test_side_files_are_plain_json(tmp_path):
    from src.repair_registry import provenance as module
    for path in (module.HISTORY_PATH, module.PROVENANCE_PATH):
        assert json.loads(path.read_text())['schema_version'] == 1
    bad = tmp_path / 'h.json'
    bad.write_text(json.dumps({'schema_version': 2, 'recipes': {}}))
    with pytest.raises(ValueError):
        load_history(bad)
