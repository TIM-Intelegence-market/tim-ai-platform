import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.bugfixer.remediation import load_registry
from src.repair_registry.versioning import (
    RegistryUpgradeError,
    load_checked_upgrade,
    main,
)

REGISTRY = Path(__file__).resolve().parents[1] / "schemas/bugfixer/remediations.v2.json"


def _entries():
    return [deepcopy(e) for e in load_registry(REGISTRY)]


def _write(path, entries, schema_version=2):
    path.write_text(json.dumps({"schema_version": schema_version, "entries": entries}))
    return path


def _snapshot(directory):
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


def _run(capsys, old, new):
    code = main(["--old", str(old), "--new", str(new)])
    return code, json.loads(capsys.readouterr().out)


def test_committed_file_against_itself_is_ok(capsys):
    result = load_checked_upgrade(REGISTRY, REGISTRY)
    ids = {e["remediation_id"] for e in _entries()}
    assert len(ids) == 2
    assert result["report"]["unchanged"] == sorted(
        f"{e['remediation_id']}@{e['version']}" for e in _entries()
    )
    assert result["report"]["requires_review"] is False
    assert result["entries"] == _entries()
    code, out = _run(capsys, REGISTRY, REGISTRY)
    assert code == 0
    assert out["status"] == "OK"


def test_added_higher_version_exits_zero(tmp_path, capsys):
    old = _write(tmp_path / "old.json", _entries())
    extra = deepcopy(next(e for e in _entries() if e["remediation_id"] == "NETWORK_TIMEOUT"))
    extra["version"] = "2.1.0"
    new = _write(tmp_path / "new.json", _entries() + [extra])
    before = _snapshot(tmp_path)
    assert load_checked_upgrade(old, new)["report"]["added"] == ["NETWORK_TIMEOUT@2.1.0"]
    code, out = _run(capsys, old, new)
    assert code == 0
    assert out["status"] == "OK"
    assert out["added"] == ["NETWORK_TIMEOUT@2.1.0"]
    assert _snapshot(tmp_path) == before


def test_changed_recipe_without_bump_is_rejected(tmp_path, capsys):
    old = _write(tmp_path / "old.json", _entries())
    changed = _entries()
    changed[0]["confidence"] = 0.5 if changed[0]["confidence"] != 0.5 else 0.6
    new = _write(tmp_path / "new.json", changed)
    before = _snapshot(tmp_path)
    with pytest.raises(RegistryUpgradeError):
        load_checked_upgrade(old, new)
    code, out = _run(capsys, old, new)
    assert code == 2
    assert out["status"] == "REJECTED"
    assert _snapshot(tmp_path) == before


def test_removed_entry_requires_review(tmp_path, capsys):
    old = _write(tmp_path / "old.json", _entries())
    new = _write(tmp_path / "new.json", _entries()[:1])
    before = _snapshot(tmp_path)
    code, out = _run(capsys, old, new)
    assert code == 3
    assert out["status"] == "REVIEW_REQUIRED"
    assert out["requires_review"] is True
    assert len(out["removed"]) == 1
    assert _snapshot(tmp_path) == before


def test_schema_version_one_is_rejected(tmp_path, capsys):
    old = _write(tmp_path / "old.json", [], schema_version=1)
    new = _write(tmp_path / "new.json", _entries())
    before = _snapshot(tmp_path)
    with pytest.raises(ValueError, match="schema_version 2"):
        load_checked_upgrade(old, new)
    code, out = _run(capsys, old, new)
    assert code == 2
    assert out["status"] == "REJECTED"
    assert _snapshot(tmp_path) == before


def test_missing_file_is_rejected_without_leaking_path(tmp_path, capsys):
    old = _write(tmp_path / "old.json", _entries())
    missing = tmp_path / "does-not-exist.json"
    before = _snapshot(tmp_path)
    code = main(["--old", str(old), "--new", str(missing)])
    raw = capsys.readouterr().out
    assert code == 2
    assert json.loads(raw)["status"] == "REJECTED"
    assert str(missing) not in raw
    assert str(tmp_path) not in raw
    assert _snapshot(tmp_path) == before
