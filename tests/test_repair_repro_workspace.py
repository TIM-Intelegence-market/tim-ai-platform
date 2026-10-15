import hashlib
import json

import pytest

from src.repair_repro.workspace import isolated_workspace, replay_twice


def _name(value):
    return getattr(value, "name", None) or str(value)


def test_workspace_removed_after_normal_exit():
    with isolated_workspace() as path:
        assert path.is_dir()
        (path / "f.txt").write_text("x")
    assert not path.exists()


def test_workspace_removed_after_exception():
    seen = []
    with pytest.raises(RuntimeError):
        with isolated_workspace() as path:
            seen.append(path)
            raise RuntimeError("boom")
    assert not seen[0].exists()


def test_workspace_uses_prefix():
    with isolated_workspace("abc-") as path:
        assert path.name.startswith("abc-")


@pytest.mark.parametrize("prefix", ["", None, 5, "a/b", "a\\b", "..x", "a..b"])
def test_rejects_bad_prefix(prefix):
    with pytest.raises(ValueError):
        with isolated_workspace(prefix):
            pass


def test_reproduced_when_both_runs_true():
    result = replay_twice("c1", lambda ws, p: True, {"a": 1})
    assert _name(result.status) == "REPRODUCED"
    assert len(result.evidence_refs) == 1
    assert result.evidence_refs[0].startswith("sha256:")


def test_not_reproduced_when_both_runs_false():
    result = replay_twice("c1", lambda ws, p: False, {})
    assert _name(result.status) == "NOT_REPRODUCED"


def test_non_deterministic_is_insufficient():
    calls = []

    def fn(ws, p):
        calls.append(1)
        return len(calls) == 1

    result = replay_twice("c1", fn, {})
    assert _name(result.status) == "INSUFFICIENT_EVIDENCE"
    assert result.reason == "non-deterministic reproduction"


def test_non_boolean_is_insufficient():
    result = replay_twice("c1", lambda ws, p: 1, {})
    assert _name(result.status) == "INSUFFICIENT_EVIDENCE"
    assert result.reason == "reproduction returned a non-boolean"


def test_exception_is_insufficient_with_class_name():
    def fn(ws, p):
        raise KeyError("k")

    result = replay_twice("c1", fn, {})
    assert _name(result.status) == "INSUFFICIENT_EVIDENCE"
    assert result.reason == "reproduction raised: KeyError"


def test_runs_use_distinct_workspaces_removed_afterwards():
    paths = []

    def fn(ws, p):
        assert ws.is_dir()
        paths.append(ws)
        return True

    replay_twice("c1", fn, {})
    assert len(paths) == 2
    assert paths[0] != paths[1]
    assert not paths[0].exists()
    assert not paths[1].exists()


def test_fn_cannot_mutate_callers_payload():
    payload = {"items": [1, 2]}

    def fn(ws, p):
        p["items"].append(3)
        p["new"] = True
        return True

    replay_twice("c1", fn, payload)
    assert payload == {"items": [1, 2]}


def test_evidence_ref_is_stable_and_matches_spec():
    payload = {"b": 2, "a": 1}
    first = replay_twice("c1", lambda ws, p: True, payload)
    second = replay_twice("c1", lambda ws, p: True, payload)
    blob = json.dumps(
        {"case_id": "c1", "payload": payload, "result": True},
        sort_keys=True,
        default=str,
    )
    expected = "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
    assert first.evidence_refs == second.evidence_refs == (expected,)
