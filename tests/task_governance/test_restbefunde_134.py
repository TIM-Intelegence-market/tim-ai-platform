"""Reproductions for the remaining findings of #134 (reviews of PR #123/#130).

Each test either pins a fix or pins the accepted behaviour documented in
docs/mission-09-task-governance.md, section "Restbefunde #134".
"""
import sqlite3

import pytest

from src.task_governance import EngineBindingConflict, EnsureOutcome, MappingState, TaskRegistry, TaskRequest
from src.task_governance import ensure_task as _ensure_task
from tests.task_governance.fakes import FakeGitHub


def ensure_task(*args, trusted_authors=None, **kwargs):
    return _ensure_task(*args, trusted_authors=trusted_authors, **kwargs)


def req(**kw):
    base = dict(mission_id='M09', phase_id='P0', task_type='SAMPLE_TASK', target='TIM', schema_version='v1',
                title='Sample')
    base.update(kw)
    return TaskRequest(**base)


@pytest.fixture
def env(tmp_path):
    return str(tmp_path / 'reg.db'), FakeGitHub(str(tmp_path / 'gh.db'))


def reasons(reg, fp):
    return [i['reason'] for i in reg.incidents(fp)]


# ---- G3: audit trail for duplicates (fixed) ----
def test_adopting_with_legacy_duplicates_leaves_an_audit_incident(env):
    reg_path, gh = env
    task = req()
    gh.seed(11, task.fingerprint, marker=False)
    gh.seed(22, task.fingerprint, marker=False)
    reg = TaskRegistry(reg_path)
    r = ensure_task(task, reg, gh, claimant='w', authoritative_hint=11, legacy_issues=[22])
    assert r.outcome is EnsureOutcome.RECOVERED and r.mapping.duplicate_issues == (22,)
    found = [i for i in reg.incidents(task.fingerprint) if i['reason'] == 'DUPLICATES_RECORDED']
    assert len(found) == 1 and '#11' in found[0]['detail'] and '22' in found[0]['detail']


def test_adopting_without_duplicates_records_no_duplicate_incident(env):
    reg_path, gh = env
    gh.seed(11, req().fingerprint)
    reg = TaskRegistry(reg_path)
    assert ensure_task(req(), reg, gh, claimant='w').outcome is EnsureOutcome.RECOVERED
    assert 'DUPLICATES_RECORDED' not in reasons(reg, req().fingerprint)


def test_add_duplicates_records_only_new_numbers_once(tmp_path):
    reg = TaskRegistry(str(tmp_path / 'reg.db'))
    won, m = reg.claim('fp', 'K|A|B|C|v1', 'w', 300)
    assert won
    reg.map_issue('fp', m.claim_token, 'o/r', 5)
    assert reg.add_duplicates('fp', [7]).duplicate_issues == (7,)
    assert reg.add_duplicates('fp', [7]).duplicate_issues == (7,)        # nothing new: no second incident
    assert reg.add_duplicates('fp', [7, 8]).duplicate_issues == (7, 8)
    details = [i['detail'] for i in reg.incidents('fp') if i['reason'] == 'DUPLICATES_RECORDED']
    assert details == ['#5 authoritative; duplicates added [7]', '#5 authoritative; duplicates added [8]']


# ---- G1: legacy numbers of a rejected hint (accepted: replaced, not merged) ----
def test_legacy_numbers_of_a_rejected_hint_are_replaced_not_merged(env):
    """The legacy list belongs to the hint that was rejected. Merging it into a new hint would mark issues as
    duplicates of an issue the operator never named for them; the operator passes them again if they still apply."""
    reg_path, gh = env
    task = req(mission_id='M10')
    gh.seed(12, task.fingerprint, marker=False)
    reg = TaskRegistry(reg_path)
    r = ensure_task(task, reg, gh, claimant='w', authoritative_hint=99, legacy_issues=[30])
    assert r.outcome is EnsureOutcome.BLOCKED and r.mapping.block_reason == 'HINT_NOT_FOUND'
    assert reg.get(task.fingerprint).hint_legacy == (30,)
    assert reg.unblock(task.fingerprint, 'operator', hint=12, legacy=[13])
    assert reg.get(task.fingerprint).hint_legacy == (13,)
    r = ensure_task(task, reg, gh, claimant='w')
    assert r.outcome is EnsureOutcome.RECOVERED and r.issue_number == 12
    assert not gh.is_documented_duplicate(30, 12)


# ---- C1 (fixed in #185): a plain unblock never lifts HINT_CONFLICT ----
def test_plain_unblock_never_lifts_hint_conflict(tmp_path):
    reg = TaskRegistry(str(tmp_path / 'reg.db'))
    won, m = reg.claim('fp', 'K|A|B|C|v1', 'w', 300, hint=11)
    assert won
    reg.block('fp', 'HINT_CONFLICT', 'authoritative_hint=12', token=m.claim_token, candidates=(12,))
    with pytest.raises(ValueError):
        reg.unblock('fp', 'operator')
    assert reg.get('fp').state is MappingState.BLOCKED


# ---- engine_bindings without a UNIQUE index (accepted: enforced in one transaction, detected on open) ----
def test_second_binding_of_one_identity_is_refused(tmp_path):
    reg = TaskRegistry(str(tmp_path / 'reg.db'))
    assert reg.bind_engine_task('t1', 'fp', 'K|A|B|C|v1') == 'fp'
    with pytest.raises(EngineBindingConflict, match='rebind_engine_task'):
        reg.bind_engine_task('t2', 'fp', 'K|A|B|C|v1')


def test_duplicate_bindings_from_an_old_file_are_reported_once_and_block_the_lookup(tmp_path):
    path = str(tmp_path / 'reg.db')
    TaskRegistry(path).close()
    db = sqlite3.connect(path)
    db.execute("INSERT INTO engine_bindings VALUES ('t1','fp','K|A|B|C|v1',0), ('t2','fp','K|A|B|C|v1',0)")
    db.commit()
    db.close()
    reg = TaskRegistry(path)
    reg.close()
    reg = TaskRegistry(path)
    found = [i['detail'] for i in reg.incidents('fp') if i['reason'] == 'ENGINE_BINDING_DUPLICATE']
    assert len(found) == 1 and 't1, t2' in found[0]
    with pytest.raises(EngineBindingConflict):
        reg.engine_binding('t1')
    rows = sqlite3.connect(path).execute("SELECT COUNT(*) FROM engine_bindings WHERE fingerprint='fp'").fetchone()
    assert rows == (2,)     # nothing deleted: the operator decides with rebind_engine_task

