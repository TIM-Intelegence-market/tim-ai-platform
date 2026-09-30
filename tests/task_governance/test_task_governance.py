import multiprocessing as mp
import threading
import time

import pytest

from src.task_governance import (EnsureOutcome, MappingState, ReopenPolicy, TaskRegistry, TaskRequest,
                                 canonical_task_key, task_fingerprint)
from src.task_governance import ensure_task as _ensure_task
from tests.task_governance.fakes import FakeGitHub


def ensure_task(*args, trusted_authors=None, **kwargs):
    """Tests trust every author unless a test says otherwise; production callers must decide."""
    return _ensure_task(*args, trusted_authors=trusted_authors, **kwargs)


def req(**kw):
    base = dict(mission_id='M09', phase_id='P0', task_type='SAMPLE_TASK', target='TIM',
                schema_version='v1', title='Sample')
    base.update(kw)
    return TaskRequest(**base)


LEGACY_REPO = 'uezeyiraydin-cell/tim-ai-platform'


def legacy_req():
    return req(task_type='BASELINE_ARCHITECTURE_AUDIT')


@pytest.fixture
def env(tmp_path):
    return str(tmp_path / 'reg.db'), FakeGitHub(str(tmp_path / 'gh.db'))


# ---- unit: identity ----
def test_key_and_fingerprint_are_deterministic():
    assert legacy_req().key == 'M09|P0|BASELINE_ARCHITECTURE_AUDIT|TIM|v1'
    assert legacy_req().fingerprint == task_fingerprint('M09|P0|BASELINE_ARCHITECTURE_AUDIT|TIM|v1')
    assert req().fingerprint == req().fingerprint


def test_title_and_body_do_not_change_identity():
    assert req(title='Totally different wording', body='x').fingerprint == req().fingerprint


def test_distinct_phase_target_type_version_give_distinct_identity():
    base = req().fingerprint
    for change in ({'phase_id': 'P1'}, {'target': 'SERVER'}, {'task_type': 'OTHER'}, {'schema_version': 'v2'},
                   {'mission_id': 'M10'}):
        assert req(**change).fingerprint != base


def test_case_of_identifier_parts_is_normalised():
    assert canonical_task_key('m09', 'p0', 'x', 'tim', 'V1') == 'M09|P0|X|TIM|v1'


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


def test_timeout_after_github_created_the_issue_adopts_it_immediately(env, tmp_path):
    reg_path, _ = env
    gh = FakeGitHub(str(tmp_path / 'gh2.db'), crash_after_create=True)
    reg = TaskRegistry(reg_path)
    r = ensure_task(req(), reg, gh, claimant='w')
    assert r.outcome is EnsureOutcome.CREATED and r.created and gh.count() == 1
    assert 'CREATE_UNCERTAIN' in [i['reason'] for i in reg.incidents(req().fingerprint)]
    again = ensure_task(req(), reg, FakeGitHub(gh.path), claimant='w2')
    assert again.outcome is EnsureOutcome.UPDATED and again.issue_number == r.issue_number and gh.count() == 1


def test_creator_dies_with_github_unreachable_recovers_after_lease(env, tmp_path):
    reg_path, _ = env
    gh_path = str(tmp_path / 'gh2.db')
    dead = FakeGitHub(gh_path, crash_after_create=True, blackout_after_crash=True)
    with pytest.raises(TimeoutError):
        ensure_task(req(), TaskRegistry(reg_path), dead, claimant='dead')
    assert dead.count() == 1
    ok = FakeGitHub(gh_path)
    late = TaskRegistry(reg_path, clock=lambda: time.time() + 10_000)      # lease long expired
    r = ensure_task(req(), late, ok, claimant='alive', lease_seconds=300)
    assert r.outcome is EnsureOutcome.RECOVERED and not r.created and ok.count() == 1


def test_nobody_resumes_by_name_only_after_lease_expiry(env, tmp_path):
    reg_path, _ = env
    gh_path = str(tmp_path / 'gh3.db')
    with pytest.raises(TimeoutError):
        ensure_task(req(), TaskRegistry(reg_path), FakeGitHub(gh_path, crash_after_create=True, blackout_after_crash=True),
                    claimant='a')
    ok = FakeGitHub(gh_path)
    for name in ('b', 'a'):        # even the same name must wait: names are not identities
        r = ensure_task(req(), TaskRegistry(reg_path), ok, claimant=name, lease_seconds=300)
        assert r.outcome is EnsureOutcome.PENDING and not r.created
    late = TaskRegistry(reg_path, clock=lambda: time.time() + 10_000)
    r = ensure_task(req(), late, ok, claimant='a', lease_seconds=300)
    assert r.outcome is EnsureOutcome.RECOVERED and ok.count() == 1


def test_workers_sharing_one_claimant_name_still_create_one_issue(tmp_path):
    reg_path = str(tmp_path / 'reg.db')
    gh = FakeGitHub(str(tmp_path / 'gh.db'), latency=0.05)
    TaskRegistry(reg_path).close()
    results, barrier = [], threading.Barrier(6)

    def worker():
        reg = TaskRegistry(reg_path)
        barrier.wait()
        results.append(ensure_task(req(), reg, gh, claimant='tim-worker'))

    ts = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert gh.count() == 1 and sum(r.created for r in results) == 1


def test_lease_expiry_during_slow_create_does_not_produce_second_issue(env, monkeypatch):
    """A is slow between claim and create; B's lease takeover must stop A before it creates."""
    reg_path, gh = env
    reg_a = TaskRegistry(reg_path)
    real_find = gh.find_issues
    state = {'first': True}

    def slow_find(fp, key):
        out = real_find(fp, key)
        if state['first']:                       # A is inside its pre-create check ...
            state['first'] = False
            late = TaskRegistry(reg_path, clock=lambda: time.time() + 10_000)
            b = ensure_task(req(), late, gh, claimant='B', lease_seconds=300)   # ... B takes over and creates
            state['b'] = b
        return out

    monkeypatch.setattr(gh, 'find_issues', slow_find)
    a = ensure_task(req(), reg_a, gh, claimant='A')
    assert state['b'].outcome is EnsureOutcome.CREATED
    assert a.outcome is EnsureOutcome.PENDING and not a.created      # A's renew fails, A never creates
    assert gh.count() == 1


def test_claim_lost_after_create_is_reported_as_blocked_not_created(env, monkeypatch):
    reg_path, gh = env
    reg = TaskRegistry(reg_path)
    real_create = gh.create_issue

    def create_then_lose_claim(request, fingerprint, **kw):
        issue = real_create(request, fingerprint, **kw)
        TaskRegistry(reg_path, clock=lambda: time.time() + 10_000).claim(
            fingerprint, request.key, 'thief', 300)       # takeover after A's renew
        return issue

    monkeypatch.setattr(gh, 'create_issue', create_then_lose_claim)
    r = ensure_task(req(), reg, gh, claimant='A')
    assert r.outcome is EnsureOutcome.BLOCKED and r.created
    assert reg.incidents()[0]['reason'] == 'CLAIM_LOST_AFTER_CREATE'


def test_failure_before_create_releases_the_claim(env, monkeypatch):
    reg_path, gh = env
    reg = TaskRegistry(reg_path)
    monkeypatch.setattr(gh, 'find_issues', lambda *a: (_ for _ in ()).throw(ConnectionError('github down')))
    with pytest.raises(ConnectionError):
        ensure_task(req(), reg, gh, claimant='A')
    assert reg.get(req().fingerprint).state is MappingState.RELEASED
    monkeypatch.undo()
    assert ensure_task(req(), reg, gh, claimant='B').outcome is EnsureOutcome.CREATED


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
def test_regression_legacy_issues_without_marker_creates_nothing(env):
    """The real #11 and #22..#65 predate the marker: the hint must still be adopted."""
    reg_path, gh = env
    fp = req().fingerprint
    gh.seed(11, fp, marker=False)
    for n in range(22, 66):
        gh.seed(n, fp, marker=False)
    reg = TaskRegistry(reg_path)
    r = ensure_task(req(), reg, gh, claimant='w', authoritative_hint=11, legacy_issues=range(22, 66))
    assert r.outcome is EnsureOutcome.RECOVERED and r.issue_number == 11 and not r.created
    assert gh.count() == 45 and reg.get(fp).duplicate_issues == tuple(range(22, 66))
    assert len(gh.ops('duplicate')) == 44 and gh.state(11) == 'open'
    assert [i.number for i in gh.find_issues(fp, req().key)] == [11]     # marker back-filled on #11 only
    again = ensure_task(req(), reg, gh, claimant='w', authoritative_hint=11)
    assert again.outcome is EnsureOutcome.UPDATED and gh.count() == 45


def test_blocked_ambiguity_resolves_when_a_valid_hint_is_supplied_later(env):
    reg_path, gh = env
    fp = req().fingerprint
    gh.seed(5, fp); gh.seed(9, fp)
    reg = TaskRegistry(reg_path)
    assert ensure_task(req(), reg, gh, claimant='w').outcome is EnsureOutcome.BLOCKED
    r = ensure_task(req(), reg, gh, claimant='w', authoritative_hint=5)
    assert r.outcome is EnsureOutcome.RECOVERED and r.issue_number == 5 and gh.count() == 2
    assert [i['reason'] for i in reg.incidents(fp)] == ['AMBIGUOUS_DUPLICATES', 'UNBLOCKED']


def test_marker_copied_by_untrusted_author_cannot_hijack_or_block(env):
    reg_path, gh = env
    fp = req().fingerprint
    gh.seed(5, fp, author='stranger')
    reg = TaskRegistry(reg_path)
    r = ensure_task(req(), reg, gh, claimant='w', trusted_authors={'owner'})
    assert r.outcome is EnsureOutcome.CREATED and r.issue_number != 5
    reg2 = TaskRegistry(reg_path + '2')
    gh.seed(6, fp, author='stranger')
    assert ensure_task(req(), reg2, gh, claimant='w', trusted_authors={'owner'}).outcome is EnsureOutcome.RECOVERED


def test_schema_version_case_does_not_create_a_second_identity():
    assert req(schema_version='V1').fingerprint == req(schema_version='v1').fingerprint



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

    def create_then_foreign_dup(request, fingerprint, **kw):
        issue = real_create(request, fingerprint, **kw)
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


# ---- second review round ----
def test_invalid_hint_blocks_and_never_creates(env):
    reg_path, gh = env
    fp = req().fingerprint
    for n in (11, 22, 23):
        gh.seed(n, fp, marker=False)
    reg = TaskRegistry(reg_path)
    r = ensure_task(req(), reg, gh, claimant='w', authoritative_hint=7777)
    assert r.outcome is EnsureOutcome.BLOCKED and not r.created and gh.count() == 3
    assert reg.incidents(fp)[0]['reason'] == 'HINT_NOT_FOUND'
    fixed = ensure_task(req(), reg, gh, claimant='w', authoritative_hint=11, legacy_issues=[22, 23])
    assert fixed.outcome is EnsureOutcome.RECOVERED and fixed.issue_number == 11 and gh.count() == 3


def test_legacy_issues_without_hint_are_rejected(env):
    reg_path, gh = env
    with pytest.raises(ValueError):
        ensure_task(req(), TaskRegistry(reg_path), gh, claimant='w', legacy_issues=[22])


def test_lease_shorter_than_gateway_create_time_is_rejected(env):
    reg_path, gh = env
    with pytest.raises(ValueError):
        ensure_task(req(), TaskRegistry(reg_path), gh, claimant='w', lease_seconds=10)   # 4 x 5s = 20s needed
    assert gh.count() == 0


def test_trusted_authors_decision_is_mandatory(env):
    reg_path, gh = env
    with pytest.raises(TypeError):
        _ensure_task(req(), TaskRegistry(reg_path), gh, claimant='w')


def test_stale_worker_cannot_overwrite_the_winners_mapping(env, monkeypatch):
    reg_path, gh = env
    reg_a = TaskRegistry(reg_path)
    real_create = gh.create_issue

    def slow_create(request, fingerprint, **kw):
        issue = real_create(request, fingerprint, **kw)          # A creates ...
        late = TaskRegistry(reg_path, clock=lambda: time.time() + 10_000)
        won, m = late.claim(fingerprint, request.key, 'B', 300)   # ... but B took over meanwhile
        assert won
        gh_b = FakeGitHub(gh.path)
        late.map_issue(fingerprint, m.claim_token, gh_b.repository, 4711)   # and B mapped its own issue
        return issue

    monkeypatch.setattr(gh, 'create_issue', slow_create)
    r = ensure_task(req(), reg_a, gh, claimant='A')
    m = reg_a.get(req().fingerprint)
    assert r.outcome is EnsureOutcome.BLOCKED and r.created
    assert m.state is MappingState.MAPPED and m.github_issue_number == 4711      # winner untouched
    assert r.issue_number in m.duplicate_issues                                  # A's issue recorded as duplicate


def test_duplicate_after_create_unblocks_with_a_valid_hint(env, monkeypatch):
    reg_path, gh = env
    real_create = gh.create_issue

    def create_then_foreign_dup(request, fingerprint, **kw):
        issue = real_create(request, fingerprint, **kw)
        gh.seed(4242, fingerprint)
        return issue

    monkeypatch.setattr(gh, 'create_issue', create_then_foreign_dup)
    reg = TaskRegistry(reg_path)
    first = ensure_task(req(), reg, gh, claimant='w')
    assert first.outcome is EnsureOutcome.BLOCKED
    monkeypatch.undo()
    r = ensure_task(req(), reg, gh, claimant='w', authoritative_hint=first.issue_number)
    assert r.outcome is EnsureOutcome.RECOVERED and r.issue_number == first.issue_number and gh.count() == 2


def test_crash_while_documenting_duplicates_resumes_and_finishes_them(env, monkeypatch):
    reg_path, gh = env
    fp = req().fingerprint
    gh.seed(11, fp, marker=False)
    for n in (22, 23, 24):
        gh.seed(n, fp, marker=False)
    reg = TaskRegistry(reg_path)
    real_mark = gh.mark_duplicate
    calls = []

    def flaky(number, authoritative):
        calls.append(number)
        if len(calls) == 2:
            raise ConnectionError('github hiccup')
        real_mark(number, authoritative)

    monkeypatch.setattr(gh, 'mark_duplicate', flaky)
    with pytest.raises(ConnectionError):
        ensure_task(req(), reg, gh, claimant='w', authoritative_hint=11, legacy_issues=[22, 23, 24])
    assert reg.get(fp).state is MappingState.CLAIMED          # not mapped yet: nothing is skipped on retry
    monkeypatch.setattr(gh, 'mark_duplicate', real_mark)
    late = TaskRegistry(reg_path, clock=lambda: time.time() + 10_000)
    r = ensure_task(req(), late, gh, claimant='w2', authoritative_hint=11, legacy_issues=[22, 23, 24])
    assert r.outcome is EnsureOutcome.RECOVERED
    assert sorted(n for n, _ in gh.ops('duplicate')) == [22, 23, 24]


# ---- third review round ----
def test_legacy_task_without_hint_uses_built_in_authority_and_creates_nothing(env):
    reg_path, gh = env
    gh.repository = LEGACY_REPO
    fp = legacy_req().fingerprint
    gh.seed(11, fp, marker=False)
    for n in range(22, 66):
        gh.seed(n, fp, marker=False)
    reg = TaskRegistry(reg_path)
    r = ensure_task(legacy_req(), reg, gh, claimant='w')          # caller forgot the hint
    assert r.outcome is EnsureOutcome.RECOVERED and r.issue_number == 11 and not r.created
    assert gh.count() == 45 and len(gh.ops('duplicate')) == 44 and gh.state(11) == 'open'
    lost = ensure_task(legacy_req(), TaskRegistry(reg_path + '.new'), gh, claimant='w')   # registry lost too
    assert lost.issue_number == 11 and gh.count() == 45


def test_fencing_tokens_never_restart_after_release_or_unblock(env, monkeypatch):
    reg_path, gh = env
    reg = TaskRegistry(reg_path)
    fp, key = req().fingerprint, req().key
    won, m1 = reg.claim(fp, key, 'A', 300)
    reg.release(fp, m1.claim_token)
    won2, m2 = reg.claim(fp, key, 'C', 300)
    assert won and won2 and m2.claim_token > m1.claim_token
    assert not reg.renew(fp, m1.claim_token)                        # stale A can no longer renew
    assert reg.map_issue(fp, m1.claim_token, 'owner/repo', 5) is None
    reg.block(fp, 'AMBIGUOUS_DUPLICATES', 'matches=[1, 2]', token=m2.claim_token)
    assert reg.unblock(fp, 'test') and not reg.unblock(fp, 'again')
    _, m3 = reg.claim(fp, key, 'D', 300)
    assert m3.claim_token > m2.claim_token


def test_hint_pointing_at_a_pull_request_or_untrusted_author_is_rejected(env):
    reg_path, gh = env
    fp = req().fingerprint
    gh.seed(77, fp, marker=False, pr=True)
    gh.seed(78, fp, marker=False, author='stranger')
    reg = TaskRegistry(reg_path)
    pr = ensure_task(req(), reg, gh, claimant='w', authoritative_hint=77)
    assert pr.outcome is EnsureOutcome.BLOCKED and reg.incidents(fp)[0]['reason'] == 'HINT_INVALID'
    other = ensure_task(req(), TaskRegistry(reg_path + '2'), gh, claimant='w', authoritative_hint=78,
                        trusted_authors={'owner'})
    assert other.outcome is EnsureOutcome.BLOCKED and gh.count() == 2
    body = gh._db().execute('SELECT body FROM issues WHERE number IN (77,78)').fetchall()
    assert all('TIM_TASK_FINGERPRINT' not in b[0] for b in body)     # nothing was written into the wrong issue


def test_stale_workers_issue_is_recorded_as_duplicate_even_when_winner_is_visible(env, monkeypatch):
    reg_path, gh = env
    reg_a = TaskRegistry(reg_path)
    real_create = gh.create_issue

    def create_after_takeover(request, fingerprint, **kw):
        issue = real_create(request, fingerprint, **kw)               # A's own issue
        late = TaskRegistry(reg_path, clock=lambda: time.time() + 10_000)
        won, m = late.claim(fingerprint, request.key, 'B', 300)
        gh.seed(4711, fingerprint)                                     # B's issue exists on GitHub
        late.map_issue(fingerprint, m.claim_token, gh.repository, 4711)
        return issue

    monkeypatch.setattr(gh, 'create_issue', create_after_takeover)
    r = ensure_task(req(), reg_a, gh, claimant='A')
    m = reg_a.get(req().fingerprint)
    assert r.outcome is EnsureOutcome.BLOCKED and r.created
    assert m.state is MappingState.MAPPED and m.github_issue_number == 4711
    assert r.issue_number in m.duplicate_issues and 4711 not in m.duplicate_issues


def test_gateway_must_declare_create_bound(env):
    reg_path, gh = env
    gh.max_create_seconds = None
    with pytest.raises(ValueError):
        ensure_task(req(), TaskRegistry(reg_path), gh, claimant='w')
    assert gh.count() == 0


def test_create_slower_than_declared_bound_is_recorded(env, monkeypatch):
    reg_path, gh = env
    gh.max_create_seconds = 0.05
    real_create = gh.create_issue

    def slow(request, fingerprint, **kw):
        time.sleep(0.2)
        return real_create(request, fingerprint, **kw)

    monkeypatch.setattr(gh, 'create_issue', slow)
    reg = TaskRegistry(reg_path)
    r = ensure_task(req(), reg, gh, claimant='w', lease_seconds=1)
    assert r.outcome is EnsureOutcome.CREATED
    assert [i['reason'] for i in reg.incidents(req().fingerprint)] == ['SLOW_CREATE']


def test_always_passed_hint_does_not_wave_away_unrelated_blocks(env):
    reg_path, gh = env
    fp = req().fingerprint
    gh.seed(5, fp); gh.seed(9, fp)
    reg = TaskRegistry(reg_path)
    assert ensure_task(req(), reg, gh, claimant='w').outcome is EnsureOutcome.BLOCKED       # ambiguous 5 vs 9
    unrelated = ensure_task(req(), reg, gh, claimant='w', authoritative_hint=11)              # 11 is not a candidate
    assert unrelated.outcome is EnsureOutcome.BLOCKED and reg.get(fp).state is MappingState.BLOCKED
    assert gh.count() == 2


# ---- fourth review round ----
def test_explicit_correct_hint_still_documents_the_built_in_legacy_duplicates(env):
    reg_path, gh = env
    gh.repository = LEGACY_REPO
    fp = legacy_req().fingerprint
    gh.seed(11, fp, marker=False)
    for n in range(22, 66):
        gh.seed(n, fp, marker=False)
    r = ensure_task(legacy_req(), TaskRegistry(reg_path), gh, claimant='w', authoritative_hint=11)
    assert r.outcome is EnsureOutcome.RECOVERED and len(gh.ops('duplicate')) == 44


def test_legacy_table_does_not_apply_to_another_repository(env):
    reg_path, gh = env                      # repository 'owner/repo': #11 and #22.. there are strangers' issues
    fp = legacy_req().fingerprint
    gh.seed(11, fp, marker=False)
    for n in range(22, 66):
        gh.seed(n, fp, marker=False)
    r = ensure_task(legacy_req(), TaskRegistry(reg_path), gh, claimant='w')
    assert r.outcome is EnsureOutcome.CREATED and gh.ops('duplicate') == []      # nothing written into foreign issues
    assert all(b[0] == 'legacy' for b in gh._db().execute('SELECT body FROM issues WHERE number<=65').fetchall())


def test_public_block_never_downgrades_a_mapped_task(env):
    reg_path, gh = env
    reg = TaskRegistry(reg_path)
    first = ensure_task(req(), reg, gh, claimant='w')
    after = reg.block(req().fingerprint, 'OPERATOR_TEST', 'x')
    assert after.state is MappingState.MAPPED and after.github_issue_number == first.issue_number
    assert reg.incidents(req().fingerprint)[-1]['reason'] == 'OPERATOR_TEST'


def test_hint_decision_uses_structured_candidates_not_incident_text(env):
    reg_path, gh = env
    fp = req().fingerprint
    gh.seed(5, fp); gh.seed(9, fp)
    reg = TaskRegistry(reg_path)
    assert ensure_task(req(), reg, gh, claimant='w').outcome is EnsureOutcome.BLOCKED
    assert reg.get(fp).block_candidates == (5, 9)
    reg.record_incident(fp, 'AMBIGUOUS_DUPLICATES', 'matches=[11, 12]')      # a stale worker's noise changes nothing
    assert ensure_task(req(), reg, gh, claimant='w', authoritative_hint=11).outcome is EnsureOutcome.BLOCKED
    assert ensure_task(req(), reg, gh, claimant='w', authoritative_hint=9).outcome is EnsureOutcome.RECOVERED


def test_create_failure_with_two_visible_issues_blocks(env, monkeypatch):
    reg_path, gh = env
    real_create = gh.create_issue

    def create_then_fail_with_foreign_dup(request, fingerprint, **kw):
        real_create(request, fingerprint, **kw)
        gh.seed(4242, fingerprint)
        raise TimeoutError('timeout')

    monkeypatch.setattr(gh, 'create_issue', create_then_fail_with_foreign_dup)
    reg = TaskRegistry(reg_path)
    r = ensure_task(req(), reg, gh, claimant='w')
    assert r.outcome is EnsureOutcome.BLOCKED and gh.count() == 2


# ---- fifth review round ----
def test_pull_request_carrying_the_marker_is_never_adopted(env):
    reg_path, gh = env
    gh.seed(31, req().fingerprint, pr=True)
    r = ensure_task(req(), TaskRegistry(reg_path), gh, claimant='w')
    assert r.outcome is EnsureOutcome.CREATED and r.issue_number != 31 and gh.count() == 2


def test_pull_request_with_marker_after_failed_create_is_not_taken_for_the_issue(env, monkeypatch):
    reg_path, gh = env
    gh.seed(31, req().fingerprint, pr=True)

    def failing(request, fingerprint, **kw):
        raise TimeoutError('timeout')

    monkeypatch.setattr(gh, 'create_issue', failing)
    with pytest.raises(TimeoutError):
        ensure_task(req(), TaskRegistry(reg_path), gh, claimant='w')      # nothing real found: claim stays held


@pytest.mark.parametrize('spelling', ['Uezeyiraydin-Cell/TIM-AI-Platform', ' uezeyiraydin-cell/tim-ai-platform '])
def test_repository_binding_ignores_case_and_whitespace(env, spelling):
    reg_path, gh = env
    gh.repository = spelling
    fp = legacy_req().fingerprint
    gh.seed(11, fp, marker=False)
    r = ensure_task(legacy_req(), TaskRegistry(reg_path), gh, claimant='w')
    assert r.outcome is EnsureOutcome.RECOVERED and r.issue_number == 11 and gh.count() == 1


def test_registry_file_from_an_earlier_release_is_migrated(tmp_path):
    import sqlite3
    path = str(tmp_path / 'old.db')
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE task_mappings (fingerprint TEXT PRIMARY KEY, canonical_key TEXT NOT NULL UNIQUE,
        state TEXT NOT NULL, claimant TEXT, claimed_at REAL, github_repository TEXT, github_issue_number INTEGER,
        duplicate_issues TEXT NOT NULL DEFAULT '[]', block_reason TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL, updated_at REAL NOT NULL);
        CREATE TABLE governance_incidents (id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL,
        reason TEXT NOT NULL, detail TEXT NOT NULL, created_at REAL NOT NULL);''')
    fp = req().fingerprint
    db.execute("INSERT INTO task_mappings(fingerprint,canonical_key,state,github_repository,github_issue_number,created_at,updated_at)"
               " VALUES(?,?,?,?,?,0,0)", (fp, req().key, 'MAPPED', 'owner/repo', 5))
    db.commit(); db.close()
    reg = TaskRegistry(path)
    m = reg.get(fp)
    assert m.github_issue_number == 5 and m.claim_token == 0 and m.block_candidates == ()
    gh = FakeGitHub(str(tmp_path / 'gh.db'))
    gh.seed(5, fp)
    assert ensure_task(req(), reg, gh, claimant='w').outcome is EnsureOutcome.UPDATED


def test_create_not_sent_releases_the_claim_at_once(env, monkeypatch):
    from src.task_governance import CreateNotSent
    reg_path, gh = env
    reg = TaskRegistry(reg_path)

    def refused(request, fingerprint, **kw):
        raise CreateNotSent('no network')

    monkeypatch.setattr(gh, 'create_issue', refused)
    with pytest.raises(CreateNotSent):
        ensure_task(req(), reg, gh, claimant='A')
    assert reg.get(req().fingerprint).state is MappingState.RELEASED
    monkeypatch.undo()
    assert ensure_task(req(), reg, gh, claimant='B').outcome is EnsureOutcome.CREATED


def test_unblock_and_map_clear_block_candidates(env):
    reg_path, gh = env
    fp = req().fingerprint
    gh.seed(5, fp); gh.seed(9, fp)
    reg = TaskRegistry(reg_path)
    ensure_task(req(), reg, gh, claimant='w')
    ensure_task(req(), reg, gh, claimant='w', authoritative_hint=9)
    assert reg.get(fp).block_candidates == () and reg.get(fp).state is MappingState.MAPPED
