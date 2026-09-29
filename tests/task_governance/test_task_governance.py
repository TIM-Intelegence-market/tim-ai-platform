import multiprocessing as mp
import threading
import time

import pytest

from src.task_governance import (EnsureOutcome, MappingState, ReopenPolicy, TaskRegistry, TaskRequest,
                                 canonical_task_key, ensure_task, task_fingerprint)
from tests.task_governance.fakes import FakeGitHub


def req(**kw):
    base = dict(mission_id='M09', phase_id='P0', task_type='BASELINE_ARCHITECTURE_AUDIT', target='TIM',
                schema_version='v1', title='Baseline audit')
    base.update(kw)
    return TaskRequest(**base)


@pytest.fixture
def env(tmp_path):
    return str(tmp_path / 'reg.db'), FakeGitHub(str(tmp_path / 'gh.db'))


# ---- unit: identity ----
def test_key_and_fingerprint_are_deterministic():
    assert req().key == 'M09|P0|BASELINE_ARCHITECTURE_AUDIT|TIM|v1'
    assert req().fingerprint == task_fingerprint('M09|P0|BASELINE_ARCHITECTURE_AUDIT|TIM|v1')
    assert req().fingerprint == req().fingerprint


def test_title_and_body_do_not_change_identity():
    assert req(title='Totally different wording', body='x').fingerprint == req().fingerprint


def test_distinct_phase_target_type_version_give_distinct_identity():
    base = req().fingerprint
    for change in ({'phase_id': 'P1'}, {'target': 'SERVER'}, {'task_type': 'OTHER'}, {'schema_version': 'v2'},
                   {'mission_id': 'M10'}):
        assert req(**change).fingerprint != base


def test_case_of_identifier_parts_is_normalised_but_version_is_not():
    assert canonical_task_key('m09', 'p0', 'x', 'tim', 'v1') == 'M09|P0|X|TIM|v1'


@pytest.mark.parametrize('bad', ['', ' ', 'a|b', None, 'a b'])
def test_invalid_parts_are_rejected_not_normalised(bad):
    with pytest.raises(ValueError):
        canonical_task_key('M09', bad, 'T', 'TIM', 'v1')


# ---- retry / update-first ----
def test_first_call_creates_and_retry_returns_same_issue(env):
    reg_path, gh = env
    reg = TaskRegistry(reg_path)
    first = ensure_task(req(), reg, gh, claimant='w1')
    again = ensure_task(req(title='reworded'), reg, gh, claimant='w1')
    assert first.outcome is EnsureOutcome.CREATED and first.created
    assert again.outcome is EnsureOutcome.UPDATED and not again.created
    assert again.issue_number == first.issue_number and gh.count() == 1
    assert len(gh.ops('update')) == 1


def test_closed_issue_is_not_replaced_and_not_reopened_by_default(env):
    reg_path, gh = env
    reg = TaskRegistry(reg_path)
    n = ensure_task(req(), reg, gh, claimant='w').issue_number
    db = gh._db(); db.execute('UPDATE issues SET state=? WHERE number=?', ('closed', n)); db.close()
    r = ensure_task(req(), reg, gh, claimant='w', retry=True)   # policy NEVER wins over retry
    assert r.outcome is EnsureOutcome.UPDATED and r.issue_number == n
    assert gh.state(n) == 'closed' and gh.count() == 1 and gh.ops('reopen') == []


def test_closed_issue_reopens_only_with_explicit_policy_and_retry(env):
    reg_path, gh = env
    reg = TaskRegistry(reg_path)
    n = ensure_task(req(), reg, gh, claimant='w').issue_number
    db = gh._db(); db.execute('UPDATE issues SET state=? WHERE number=?', ('closed', n)); db.close()
    no_retry = ensure_task(req(), reg, gh, claimant='w', policy=ReopenPolicy.EXPLICIT)
    assert no_retry.outcome is EnsureOutcome.UPDATED and gh.state(n) == 'closed'
    r = ensure_task(req(), reg, gh, claimant='w', policy=ReopenPolicy.EXPLICIT, retry=True)
    assert r.outcome is EnsureOutcome.REOPENED and gh.state(n) == 'open' and gh.count() == 1


# ---- persistence / restart ----
def test_mapping_survives_process_restart(env):
    reg_path, gh = env
    first = ensure_task(req(), TaskRegistry(reg_path), gh, claimant='p1')
    fresh = TaskRegistry(reg_path)            # "new process"
    again = ensure_task(req(), fresh, gh, claimant='p2')
    assert again.issue_number == first.issue_number and not again.created and gh.count() == 1


def test_lost_local_state_recovers_mapping_from_github(env, tmp_path):
    reg_path, gh = env
    first = ensure_task(req(), TaskRegistry(reg_path), gh, claimant='p1')
    lost = TaskRegistry(str(tmp_path / 'brand-new.db'))
    again = ensure_task(req(), lost, gh, claimant='p2')
    assert again.outcome is EnsureOutcome.RECOVERED and not again.created
    assert again.issue_number == first.issue_number and gh.count() == 1
    assert lost.get(req().fingerprint).state is MappingState.MAPPED


def test_creator_crash_after_github_create_resumes_without_second_issue(env, tmp_path):
    reg_path, _ = env
    gh_path = str(tmp_path / 'gh2.db')
    crashing = FakeGitHub(gh_path, crash_after_create=True)
    with pytest.raises(RuntimeError):
        ensure_task(req(), TaskRegistry(reg_path), crashing, claimant='dead')
    assert crashing.count() == 1
    ok = FakeGitHub(gh_path)
    late = TaskRegistry(reg_path, clock=lambda: time.time() + 10_000)      # lease long expired
    r = ensure_task(req(), late, ok, claimant='alive', lease_seconds=300)
    assert r.outcome is EnsureOutcome.RECOVERED and not r.created and ok.count() == 1


def test_same_claimant_resumes_immediately_other_worker_waits_for_lease(env, tmp_path):
    reg_path, _ = env
    gh_path = str(tmp_path / 'gh3.db')
    with pytest.raises(RuntimeError):
        ensure_task(req(), TaskRegistry(reg_path), FakeGitHub(gh_path, crash_after_create=True), claimant='a')
    ok = FakeGitHub(gh_path)
    other = ensure_task(req(), TaskRegistry(reg_path), ok, claimant='b', lease_seconds=300)
    assert other.outcome is EnsureOutcome.PENDING and not other.created
    mine = ensure_task(req(), TaskRegistry(reg_path), ok, claimant='a')
    assert mine.outcome is EnsureOutcome.RECOVERED and ok.count() == 1


# ---- concurrency ----
def test_n_threads_racing_create_exactly_one_issue(tmp_path):
    reg_path = str(tmp_path / 'reg.db')
    gh = FakeGitHub(str(tmp_path / 'gh.db'), latency=0.05)     # big window between search and create
    TaskRegistry(reg_path).close()
    results, barrier = [], threading.Barrier(12)

    def worker(i):
        reg = TaskRegistry(reg_path)
        barrier.wait()
        results.append(ensure_task(req(), reg, gh, claimant=f't{i}'))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert gh.count() == 1
    assert sum(r.created for r in results) == 1
    assert {r.outcome for r in results} <= {EnsureOutcome.CREATED, EnsureOutcome.PENDING, EnsureOutcome.UPDATED}


def _proc(reg_path, gh_path, i, q):
    r = ensure_task(req(), TaskRegistry(reg_path), FakeGitHub(gh_path, latency=0.05), claimant=f'p{i}')
    q.put((r.created, r.outcome.value))


def test_n_processes_racing_create_exactly_one_issue(tmp_path):
    reg_path, gh_path = str(tmp_path / 'reg.db'), str(tmp_path / 'gh.db')
    gh = FakeGitHub(gh_path)
    TaskRegistry(reg_path).close()
    ctx = mp.get_context('spawn')
    q = ctx.Queue()
    procs = [ctx.Process(target=_proc, args=(reg_path, gh_path, i, q)) for i in range(8)]
    [p.start() for p in procs]; [p.join(60) for p in procs]
    outs = [q.get(timeout=5) for _ in procs]
    assert all(p.exitcode == 0 for p in procs)
    assert gh.count() == 1 and sum(c for c, _ in outs) == 1


def test_uniqueness_constraint_is_in_the_database(env):
    reg_path, gh = env
    reg = TaskRegistry(reg_path)
    ensure_task(req(), reg, gh, claimant='w')
    assert reg.count_mappings(req().key) == 1
    with pytest.raises(Exception):
        reg.db.execute('INSERT INTO task_mappings(fingerprint,canonical_key,state,created_at,updated_at) '
                       "VALUES('other',?, 'CLAIMED',0,0)", (req().key,))


# ---- GitHub-side duplicates ----
def test_regression_task_11_with_duplicates_22_to_65_creates_nothing(env):
    """#68 primary fixture: authoritative #11, historical duplicates #22..#65."""
    reg_path, gh = env
    fp = req().fingerprint
    gh.seed(11, fp)
    for n in range(22, 66):
        gh.seed(n, fp)
    reg = TaskRegistry(reg_path)
    r = ensure_task(req(), reg, gh, claimant='w', authoritative_hint=11)
    assert r.outcome is EnsureOutcome.RECOVERED and r.issue_number == 11 and not r.created
    assert gh.count() == 45
    assert reg.get(fp).duplicate_issues == tuple(range(22, 66))
    assert [n for n, _ in gh.ops('duplicate')] == list(range(22, 66))
    assert gh.state(11) == 'open'                       # authoritative issue never closed
    again = ensure_task(req(), reg, gh, claimant='w', authoritative_hint=11)
    assert again.outcome is EnsureOutcome.UPDATED and gh.count() == 45
    assert len(gh.ops('duplicate')) == 44               # already documented, not re-marked


def test_documented_duplicates_are_not_marked_twice(env):
    reg_path, gh = env
    fp = req().fingerprint
    gh.seed(11, fp); gh.seed(22, fp)
    gh.mark_duplicate(22, 11)
    ensure_task(req(), TaskRegistry(reg_path), gh, claimant='w', authoritative_hint=11)
    assert len(gh.ops('duplicate')) == 1


def test_ambiguous_duplicates_without_hint_block_and_escalate_without_creating(env):
    reg_path, gh = env
    fp = req().fingerprint
    gh.seed(5, fp); gh.seed(9, fp)
    reg = TaskRegistry(reg_path)
    r = ensure_task(req(), reg, gh, claimant='w')
    assert r.outcome is EnsureOutcome.BLOCKED and not r.created and gh.count() == 2
    assert reg.get(fp).state is MappingState.BLOCKED
    assert reg.incidents(fp)[0]['reason'] == 'AMBIGUOUS_DUPLICATES'
    retry = ensure_task(req(), reg, gh, claimant='w2')          # stays blocked, still no create
    assert retry.outcome is EnsureOutcome.BLOCKED and gh.count() == 2


def test_wrong_hint_not_among_matches_is_ambiguous(env):
    reg_path, gh = env
    fp = req().fingerprint
    gh.seed(5, fp); gh.seed(9, fp)
    r = ensure_task(req(), TaskRegistry(reg_path), gh, claimant='w', authoritative_hint=77)
    assert r.outcome is EnsureOutcome.BLOCKED and gh.count() == 2


def test_duplicate_appearing_after_create_is_escalated_not_closed(env, monkeypatch):
    reg_path, gh = env
    real_create = gh.create_issue

    def create_then_foreign_dup(request, fingerprint):
        issue = real_create(request, fingerprint)
        gh.seed(4242, fingerprint)          # somebody outside the claim created one too
        return issue

    monkeypatch.setattr(gh, 'create_issue', create_then_foreign_dup)
    reg = TaskRegistry(reg_path)
    r = ensure_task(req(), reg, gh, claimant='w')
    assert r.outcome is EnsureOutcome.BLOCKED and gh.count() == 2
    assert reg.incidents()[0]['reason'] == 'DUPLICATE_AFTER_CREATE'
    assert gh.state(r.issue_number) == 'open' and gh.state(4242) == 'open'


def test_gateway_protocol_has_no_close_operation():
    from src.task_governance import IssueGateway
    assert not [n for n in dir(IssueGateway) if 'close' in n.lower()]
