"""Recipe provenance and shipped-version history for the remediation registry (#16).

The registry schema stays unchanged. Two side files bind every shipped recipe (ID@version) to its digest:

- `registry_history.v1.json`: every ID@version ever shipped with its digest. A recipe may not change without a
  version bump, and a new version must be higher than every shipped one (checked with the rules of
  `versioning.check_registry_upgrade`). A new version is appended here in the same reviewed change.
- `provenance.v1.json`: where each shipped recipe came from and how strong its evidence is.

Both are checked by tests on every CI run, so the upgrade check is no longer a CLI that nobody calls.
"""
import json
from pathlib import Path

from src.repair_registry.versioning import RegistryUpgradeError, _key, recipe_digest

HERE = Path(__file__).resolve().parent
HISTORY_PATH = HERE / 'registry_history.v1.json'
PROVENANCE_PATH = HERE / 'provenance.v1.json'
EVIDENCE_STATUSES = {'REPRODUCED', 'CANDIDATE_EVIDENCE', 'UNVERIFIED_ORIGIN'}
_PROVENANCE_FIELDS = {'digest', 'origin_commit', 'introduced', 'changed_by', 'evidence_status', 'evidence_refs', 'note'}


def _label(entry: dict) -> str:
    return f"{entry['remediation_id']}@{entry['version']}"


def _load(path: Path, key: str) -> dict:
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict) or payload.get('schema_version') != 1 or not isinstance(payload.get(key), dict):
        raise ValueError(f'unsupported {Path(path).name}')
    return payload[key]


def check_history(entries: list, history: dict) -> dict:
    """Every current recipe must be in the history with the same digest; nothing changes without a bump."""
    for entry in entries:
        label = _label(entry)
        if label not in history:
            raise RegistryUpgradeError(f'{label} is not recorded in the registry history')
        if history[label] != recipe_digest(entry):
            raise RegistryUpgradeError(f'{label} changed without version bump')
    last: dict = {}
    for label in history:       # file order is shipping order: each new version is appended and must be higher
        rid, version = label.rsplit('@', 1)
        if rid in last and _key(version) <= _key(last[rid]):
            raise RegistryUpgradeError(f'{label}: new version must be higher than {last[rid]}')
        last[rid] = version
    current = {_label(e) for e in entries}
    retired = sorted(set(history) - current)
    return {'checked': sorted(current), 'retired': retired}


def check_provenance(entries: list, provenance: dict) -> dict:
    """Every current recipe needs a provenance record that names the same digest."""
    statuses = {}
    for entry in entries:
        label = _label(entry)
        row = provenance.get(label)
        if not isinstance(row, dict) or set(row) != _PROVENANCE_FIELDS:
            raise ValueError(f'{label} has no complete provenance record')
        if row['digest'] != recipe_digest(entry):
            raise ValueError(f'{label} provenance names another digest')
        if row['evidence_status'] not in EVIDENCE_STATUSES:
            raise ValueError(f'{label} has an unknown evidence status')
        if not isinstance(row['evidence_refs'], list) or not isinstance(row['changed_by'], list):
            raise ValueError(f'{label} provenance lists are malformed')
        if row['evidence_status'] != 'UNVERIFIED_ORIGIN' and not row['evidence_refs']:
            raise ValueError(f'{label} claims evidence without a reference')
        statuses[label] = row['evidence_status']
    return statuses


def load_history(path: Path = HISTORY_PATH) -> dict:
    return _load(path, 'recipes')


def load_provenance(path: Path = PROVENANCE_PATH) -> dict:
    return _load(path, 'recipes')
