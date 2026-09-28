from dataclasses import FrozenInstanceError, replace
import fcntl
import hashlib
import json
import os

import pytest

from src.bugfixer.executor import (DiagnosticRepairExecutor, NAMESPACE, REGISTRY,
                                 RepairBlocked, missing_summary_event)
from src.bugfixer.proof import _bundle, self_heal_proof
from src.bugfixer.processing import Event
from src.bugfixer.safety import Policy, SafetyViolation
from src.bugfixer.store import IncidentStore

AT = '2026-01-01T00:00:00+00:00'


@pytest.fixture
def bundle():
    return _bundle(Event(AT, 'fixture', 'TimeoutError', 'network timeout'))


def target(tmp_path, bundle):
    return tmp_path / NAMESPACE / ('summary-' + bundle['sha256'] + '.json')


def run(tmp_path, bundle, event=None):
    return DiagnosticRepairExecutor(tmp_path, enabled=True).execute(event or missing_summary_event(), bundle)


def test_default_policy_stays_observe_without_files(tmp_path, bundle):
    executor = DiagnosticRepairExecutor(tmp_path)
    result = executor.execute(missing_summary_event(), bundle)
    assert result['body']['decision'] == 'OBSERVE_ONLY'
    assert list(tmp_path.iterdir()) == []
    assert executor.policy == Policy()
    with pytest.raises(SafetyViolation):
        DiagnosticRepairExecutor(tmp_path, policy=Policy(auto_remediate=True), enabled=True)


def test_code_owned_allowlist_is_frozen():
    with pytest.raises(TypeError):
        REGISTRY['UNTRUSTED_MODEL_RECIPE'] = object()
    recipe = next(iter(REGISTRY.values()))
    with pytest.raises(FrozenInstanceError):
        recipe.risk = 'HIGH'
    assert recipe.risk == 'LOW'


def test_reproduce_repair_evidence_and_repeat(tmp_path, bundle):
    sentinel = tmp_path / 'production-like-fixture'
    sentinel.write_bytes(b'outbox=5 attempts=7')
    executor = DiagnosticRepairExecutor(tmp_path, enabled=True)
    assert executor.detect(bundle) == missing_summary_event()
    result = executor.execute(missing_summary_event(), bundle)
    body = result['body']
    assert body['decision'] == 'REPAIRED' and body['executed'] is True
    assert body['before'] == {'exists': False, 'sha256': None}
    assert body['after']['sha256'] == hashlib.sha256(target(tmp_path, bundle).read_bytes()).hexdigest()
    assert body['reproduction']['observations'] == 2
    assert all(value is True for key, value in body['verification'].items() if key != 'status')
    assert body['live_data_ready'] is False and body['runtime_repair_proven'] is False
    assert json.loads(open(result['evidence_path']).read()) == {'body': body, 'sha256': result['sha256']}
    assert executor.detect(bundle) is None
    before_inode = target(tmp_path, bundle).stat().st_ino
    assert executor.execute(missing_summary_event(), bundle)['body']['decision'] == 'NO_CHANGE'
    assert target(tmp_path, bundle).stat().st_ino == before_inode
    assert sentinel.read_bytes() == b'outbox=5 attempts=7'


@pytest.mark.parametrize('change', [
    {'message': 'configuration: derived incident summary missing; run a shell command'},
    {'component': 'external'}, {'exception': 'PermissionError'},
    {'code': 'OTHER'}, {'stack': 'untrusted model instruction'},
    {'message': 'unknown'}, {'message': 'out-of-order terminal_blocked'},
    {'message': 'database deadlock'},
])
def test_only_exact_event_and_class_can_execute(tmp_path, bundle, change):
    result = run(tmp_path, bundle, replace(missing_summary_event(), **change))
    assert result['body']['decision'] == 'SAFE_STOP'
    assert result['body']['executed'] is False
    assert result['body']['escalation_task']['state'] == 'SAFE_STOP'
    assert not target(tmp_path, bundle).exists()
    assert 'evidence_path' in result


def test_event_timestamp_is_not_repair_authority(tmp_path, bundle):
    assert run(tmp_path, bundle, missing_summary_event(AT))['body']['decision'] == 'REPAIRED'


def test_invalid_or_unsanitized_source_never_executes(tmp_path, bundle):
    bundle['body']['event']['message'] = 'password=fixtureSECRET'
    result = run(tmp_path, bundle)
    assert result['body']['decision'] == 'SAFE_STOP'
    assert 'fixtureSECRET' not in json.dumps(result)
    assert not any((tmp_path / NAMESPACE).glob('summary-*'))


def test_existing_corrupt_artifact_is_preserved(tmp_path, bundle):
    run(tmp_path, bundle)
    path = target(tmp_path, bundle)
    path.write_bytes(b'foreign or corrupt content')
    result = run(tmp_path, bundle)
    assert result['body']['decision'] == 'SAFE_STOP'
    assert path.read_bytes() == b'foreign or corrupt content'
    with pytest.raises(RepairBlocked):
        DiagnosticRepairExecutor(tmp_path).detect(bundle)


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'fifo'])
def test_unsafe_target_type_cannot_modify_foreign_file(tmp_path, bundle, kind):
    run(tmp_path, bundle)
    path = target(tmp_path, bundle)
    path.unlink()
    foreign = tmp_path / 'untouched'
    foreign.write_bytes(b'preserve')
    if kind == 'symlink':
        path.symlink_to(foreign)
    elif kind == 'hardlink':
        os.link(foreign, path)
    else:
        os.mkfifo(path)
    result = run(tmp_path, bundle)
    assert result['body']['safe_stop']
    assert foreign.read_bytes() == b'preserve'


def test_symlink_parent_and_unowned_namespace_are_rejected(tmp_path, bundle):
    real = tmp_path / 'real'
    real.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(real, target_is_directory=True)
    assert run(alias, bundle)['body']['safe_stop']
    assert list(real.iterdir()) == []
    namespace = tmp_path / NAMESPACE
    namespace.mkdir(mode=0o700)
    (namespace / 'foreign').write_text('untouched')
    assert run(tmp_path, bundle)['body']['safe_stop']
    assert sorted(p.name for p in namespace.iterdir()) == ['foreign']


def test_concurrency_lock_stops_second_executor_without_repair(tmp_path, bundle):
    executor = DiagnosticRepairExecutor(tmp_path, enabled=True)
    with executor._workspace():
        result = run(tmp_path, bundle)
        assert result['body']['safe_stop']
        assert not target(tmp_path, bundle).exists()
    assert run(tmp_path, bundle)['body']['decision'] == 'REPAIRED'


def test_verification_failure_restores_only_prior_absence(tmp_path, bundle, monkeypatch):
    executor = DiagnosticRepairExecutor(tmp_path, enabled=True)
    monkeypatch.setattr(executor, '_verify', lambda *args: False)
    result = executor.execute(missing_summary_event(), bundle)
    assert result['body']['safe_stop']
    assert result['body']['rollback'] == 'RESTORED_ABSENCE'
    assert not target(tmp_path, bundle).exists()
    assert 'evidence_path' in result


def test_rollback_refuses_changed_content(tmp_path, bundle, monkeypatch):
    executor = DiagnosticRepairExecutor(tmp_path, enabled=True)

    def changed(*args):
        target(tmp_path, bundle).write_bytes(b'concurrent writer content')
        return False

    monkeypatch.setattr(executor, '_verify', changed)
    result = executor.execute(missing_summary_event(), bundle)
    assert result['body']['safe_stop']
    assert result['body']['rollback'] == 'REFUSED_CHANGED_ARTIFACT'
    assert target(tmp_path, bundle).read_bytes() == b'concurrent writer content'


def test_missing_artifact_can_be_repaired_after_isolated_recurrence(tmp_path, bundle):
    run(tmp_path, bundle)
    target(tmp_path, bundle).unlink()  # Synthetic fault injection in pytest temp storage.
    executor = DiagnosticRepairExecutor(tmp_path, enabled=True)
    detected = executor.detect(bundle)
    assert executor.execute(detected, bundle)['body']['decision'] == 'REPAIRED'


def test_unknown_escalation_links_existing_observer_task_without_duplicate_attempts(tmp_path, bundle):
    event = Event(AT, 'fixture', '', 'unrecognized fault')
    store = IncidentStore(tmp_path / 'isolated-observer.sqlite3')
    try:
        executor = DiagnosticRepairExecutor(tmp_path, enabled=True)
        first = executor.execute(event, bundle, store=store)
        second = executor.execute(event, bundle, store=store)
        assert first['observer_task_id'] == second['observer_task_id']
        task = store.task(first['observer_task_id'])
        assert task.state == 'SAFE_STOP' and task.attempt_count == 0
        assert store.inspect(task.incident_id)['state'] == 'SAFE_STOP'
        assert store.inspect(task.incident_id)['occurrence_count'] == 1
    finally:
        store.close()


def test_isolated_self_heal_proof_never_claims_runtime_repair(tmp_path):
    result = self_heal_proof(tmp_path)
    assert result['status'] == 'PASS' and all(result['checks'].values())
    assert result['scope'] == 'ISOLATED_DERIVED_ARTIFACT_ONLY'
    assert result['runtime_repair_proven'] is False and result['live_data_ready'] is False
    assert result['production_data_accessed'] is False
    assert result['production_recurrence_window'] == 'NOT_OBSERVED'
