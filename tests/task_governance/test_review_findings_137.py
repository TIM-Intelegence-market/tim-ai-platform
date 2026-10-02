"""Regression tests for the Codex final review of PR #137 (findings 1-5 and the lease takeover of a shared registry)."""
import json

import pytest

from src.task_governance import (EnsureOutcome, GitHubError, GitHubRestGateway, MappingState, TaskRegistry, TaskRequest,
                                 ensure_task, fingerprint_marker)
from src.task_governance import live_check
from src.task_governance.live_check import TOKEN_VARIABLE
from tests.task_governance.fake_rest import FakeRest

TOKEN = 'ghp_SUPERSECRETTOKEN'


def req(**kw):
    base = dict(mission_id='M09', phase_id='P0', task_type='SAMPLE_TASK', target='TIM', schema_version='v1',
                title='Sample', body='the body')
    base.update(kw)
    return TaskRequest(**base)


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def creates(rest):
    return len([c for c in rest.calls if c[0] == 'POST' and c[1].endswith('/issues')])


def blind_setup(rest):
    """#1-#5 listed, #6-#8 deleted (410): a lookup with no memory stops at #8 and cannot see #9."""
    rest.next_number, rest.lag_listing = 0, True
    for number in range(1, 6):
        rest.seed(number)
    for number in (6, 7, 8):
        rest.fail[('GET', rf'/issues/{number}$')] = 410
    rest.next_number = 8


def failing_check_after_create(gw):
    real, calls = gw.find_issues, []

    def flaky(fingerprint, key):
        calls.append(1)
        if len(calls) == 2:                        # the lookup before the create works, the check after it does not
            raise GitHubError('GET /repos/owner/repo/issues: HTTP 429')
        return real(fingerprint, key)
    gw.find_issues = flaky


# -- finding 1: a good answer from the listing must reset a pending "missing" answer ------------------------------

def test_a_listing_that_shows_the_issue_resets_its_first_missing_answer():
    rest, clock = FakeRest(), Clock()
    gw = GitHubRestGateway(rest.repo, TOKEN, transport=rest, clock=clock)
    request = req()
    for n in range(1, 101):
        rest.seed(n, fingerprint_marker(request.fingerprint) if n == 40 else '')
    rest.next_number = 100
    rest.unlisted = {40}
    rest.fail[('GET', r'/issues/40$')] = 404       # first wrong answer
    gw.find_issues(request.fingerprint, request.key)
    clock.now += 60
    rest.unlisted.clear()
    del rest.fail[('GET', r'/issues/40$')]
    assert [i.number for i in gw.find_issues(request.fingerprint, request.key)] == [40]     # good answer in between
    clock.now += 61
    rest.unlisted = {40}
    rest.fail[('GET', r'/issues/40$')] = 404       # a second wrong answer, 121 s after the first: must not be "confirmed"
    gw.find_issues(request.fingerprint, request.key)
    del rest.fail[('GET', r'/issues/40$')]
    result = ensure_task(request, TaskRegistry(':memory:'), gw, claimant='w', trusted_authors=['owner'])
    assert result.outcome is EnsureOutcome.RECOVERED and result.issue_number == 40
    assert creates(rest) == 0


# -- finding 2: the re-check with a fresh gateway must search up to the created issue -----------------------------

def test_the_re_check_in_a_new_process_still_sees_a_hidden_duplicate_below_the_created_issue(tmp_path):
    rest = FakeRest()
    blind_setup(rest)
    rest.seed(9, fingerprint_marker(req().fingerprint))       # an older issue of this task, hidden by the lag
    rest.unlisted = {9}
    rest.next_number = 9
    reg = TaskRegistry(str(tmp_path / 'a.db'))
    gw = GitHubRestGateway(rest.repo, TOKEN, transport=rest)
    failing_check_after_create(gw)
    first = ensure_task(req(), reg, gw, claimant='w', trusted_authors=None)
    assert first.outcome is EnsureOutcome.BLOCKED and first.issue_number == 10
    fresh = GitHubRestGateway(rest.repo, TOKEN, transport=rest)       # new process: no memory of #10
    again = ensure_task(req(), reg, fresh, claimant='w', trusted_authors=None)
    assert again.outcome is EnsureOutcome.BLOCKED and again.mapping.block_candidates == (9, 10)
    assert again.mapping.state is MappingState.BLOCKED
    assert rest.comments.get(9, []) == [] and creates(rest) == 1


# -- finding 3: a stale re-check must not lift a newer block --------------------------------------------------------

def test_a_stale_re_check_cannot_lift_a_newer_duplicate_block(tmp_path):
    rest = FakeRest()
    blind_setup(rest)
    path = str(tmp_path / 'a.db')
    reg_a, reg_b = TaskRegistry(path), TaskRegistry(path)
    gw = GitHubRestGateway(rest.repo, TOKEN, transport=rest)
    failing_check_after_create(gw)
    first = ensure_task(req(), reg_a, gw, claimant='a', trusted_authors=None)
    assert first.mapping.block_reason == 'POST_CREATE_CHECK_FAILED' and first.issue_number == 9
    inner = GitHubRestGateway(rest.repo, TOKEN, transport=rest)
    other = []

    class PausesAfterTheReCheck:
        """Worker A: after its re-check read everything, worker B runs completely before A writes."""
        def __getattr__(self, name):
            return getattr(inner, name)

        def carries_marker(self, number, fingerprint):
            answer = inner.carries_marker(number, fingerprint)
            if not other:
                rest.seed(10, fingerprint_marker(fingerprint))       # another marker issue becomes visible
                rest.next_number = 10
                other.append(ensure_task(req(), reg_b, GitHubRestGateway(rest.repo, TOKEN, transport=rest), claimant='b',
                                         trusted_authors=None))
            return answer
    result_a = ensure_task(req(), reg_a, PausesAfterTheReCheck(), claimant='a', trusted_authors=None)
    assert other[0].outcome is EnsureOutcome.BLOCKED and other[0].mapping.block_candidates == (9, 10)
    row = reg_a.get(req().fingerprint)
    assert row.state is MappingState.BLOCKED and row.block_reason == 'DUPLICATE_AFTER_CREATE' and row.block_candidates == (9, 10)
    assert result_a.outcome is EnsureOutcome.BLOCKED
    assert rest.comments.get(10, []) == [] and creates(rest) == 1      # nobody chose #9 over #10 for the operator


# -- finding 4: the candidate of a failed post-create check belongs to one repository ------------------------------

@pytest.mark.parametrize('b_has_marker_issue', [True, False])
def test_a_block_about_a_created_issue_is_not_rechecked_through_another_repository(tmp_path, b_has_marker_issue):
    rest_a, rest_b = FakeRest('owner/a'), FakeRest('owner/b')
    reg = TaskRegistry(str(tmp_path / 'a.db'))
    gw_a = GitHubRestGateway('owner/a', TOKEN, transport=rest_a)
    failing_check_after_create(gw_a)
    first = ensure_task(req(), reg, gw_a, claimant='w', trusted_authors=None)
    assert first.mapping.block_reason == 'POST_CREATE_CHECK_FAILED' and first.issue_number == 1
    if b_has_marker_issue:
        rest_b.seed(1, fingerprint_marker(req().fingerprint))
    again = ensure_task(req(), reg, GitHubRestGateway('owner/b', TOKEN, transport=rest_b), claimant='w', trusted_authors=None)
    assert again.outcome is EnsureOutcome.BLOCKED and again.detail == 'REPOSITORY_MISMATCH'
    row = reg.get(req().fingerprint)
    assert row.block_reason == 'POST_CREATE_CHECK_FAILED' and row.block_candidates == (1,)       # untouched
    assert rest_b.writes() == []
    back = ensure_task(req(), reg, GitHubRestGateway('owner/a', TOKEN, transport=rest_a), claimant='w', trusted_authors=None)
    assert back.mapping.state is MappingState.MAPPED and back.issue_number == 1 and back.mapping.github_repository == 'owner/a'


# -- finding 5: the live check's lost-registry step must also lose the gateway's memory ------------------------------

def test_the_live_check_lost_registry_step_uses_a_gateway_without_memory(capsys):
    rest = FakeRest('owner/throwaway')
    blind_setup(rest)                              # the live run's issue lands at #9, behind three missing numbers
    code = live_check.main(['--repo', rest.repo, '--mode', 'roundtrip', '--confirm-write', rest.repo],
                           environ={TOKEN_VARIABLE: TOKEN}, transport=rest)
    report = json.loads(capsys.readouterr().out)
    names = {c['name']: c for c in report['checks']}
    # a process without memory creates a second issue here (the documented lost-registry limit): the check must say so
    assert code == 1 and not names['lost_registry_adopts_instead_of_creating']['ok']


# -- lease takeover within ONE shared registry: the second worker must never create blindly -------------------------

def _crashing_after_create(gw):
    real = gw.create_issue

    def create_then_die(request, fingerprint, *, timeout):
        real(request, fingerprint, timeout=timeout)
        raise SystemExit('worker died after the create, before anything was persisted')
    gw.create_issue = create_then_die


def test_a_worker_taking_over_an_expired_claim_after_a_create_attempt_never_creates_again(tmp_path):
    rest = FakeRest()
    blind_setup(rest)
    clock = Clock()
    path = str(tmp_path / 'shared.db')
    gw_a = GitHubRestGateway(rest.repo, TOKEN, transport=rest)
    _crashing_after_create(gw_a)
    with pytest.raises(SystemExit):
        ensure_task(req(), TaskRegistry(path, clock=clock), gw_a, claimant='a', trusted_authors=None)
    assert creates(rest) == 1 and 9 in rest.issues
    clock.now += 10_000                            # A's lease expired
    reg_b = TaskRegistry(path, clock=clock)
    b = ensure_task(req(), reg_b, GitHubRestGateway(rest.repo, TOKEN, transport=rest), claimant='b', trusted_authors=None)
    assert creates(rest) == 1                      # B is blind to #9 but must not create #10
    assert b.outcome is EnsureOutcome.BLOCKED and b.detail == 'CREATE_UNCERTAIN'
    again = ensure_task(req(), reg_b, GitHubRestGateway(rest.repo, TOKEN, transport=rest), claimant='b', trusted_authors=None)
    assert again.outcome is EnsureOutcome.BLOCKED and creates(rest) == 1      # still blind: stays blocked, still no create
    rest.release_listing()                         # the listing caught up: the issue is adopted, nothing created
    healed = ensure_task(req(), reg_b, GitHubRestGateway(rest.repo, TOKEN, transport=rest), claimant='b', trusted_authors=None)
    assert healed.outcome is EnsureOutcome.RECOVERED and healed.issue_number == 9 and creates(rest) == 1


def test_a_create_that_certainly_was_not_sent_does_not_leave_the_task_uncertain(tmp_path):
    from src.task_governance import CreateNotSent
    rest = FakeRest()
    gw = GitHubRestGateway(rest.repo, TOKEN, transport=rest)
    real = gw.create_issue
    calls = []

    def refused_once(request, fingerprint, *, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise CreateNotSent('connection refused')
        return real(request, fingerprint, timeout=timeout)
    gw.create_issue = refused_once
    reg = TaskRegistry(str(tmp_path / 'a.db'))
    with pytest.raises(CreateNotSent):
        ensure_task(req(), reg, gw, claimant='w', trusted_authors=None)
    result = ensure_task(req(), reg, gw, claimant='w', trusted_authors=None)
    assert result.outcome is EnsureOutcome.CREATED and creates(rest) == 1


def test_an_open_claim_from_a_release_three_registry_counts_as_a_possible_create(tmp_path):
    import sqlite3
    path = str(tmp_path / 'v3.db')
    TaskRegistry(path).close()
    db = sqlite3.connect(path)                     # turn the fresh file back into a release-3 file with an open claim
    db.execute('ALTER TABLE task_mappings DROP COLUMN create_intent')
    db.execute('PRAGMA user_version=3')
    db.execute("INSERT INTO task_mappings(fingerprint,canonical_key,state,claimant,claimed_at,claim_token,created_at,updated_at)"
               " VALUES(?,?,'CLAIMED','old',0,1,0,0)", (req().fingerprint, req().key))
    db.execute("INSERT INTO task_mappings(fingerprint,canonical_key,state,claimant,claimed_at,claim_token,created_at,updated_at)"
               " VALUES(?,?,'RELEASED','old',0,1,0,0)", (req(target='OTHER').fingerprint, req(target='OTHER').key))
    db.commit()
    db.close()
    reg = TaskRegistry(path)
    assert reg.get(req().fingerprint).create_intent is True                       # its worker may have been creating
    assert reg.get(req(target='OTHER').fingerprint).create_intent is False
    assert reg.db.execute('PRAGMA user_version').fetchone()[0] == 4
    rest = FakeRest()
    result = ensure_task(req(), reg, GitHubRestGateway(rest.repo, TOKEN, transport=rest), claimant='new', trusted_authors=None)
    assert result.detail == 'CREATE_UNCERTAIN' and creates(rest) == 0


def test_an_operator_can_clear_an_uncertain_create_after_checking_github(tmp_path):
    rest = FakeRest()
    clock = Clock()
    path = str(tmp_path / 'shared.db')
    gw_a = GitHubRestGateway(rest.repo, TOKEN, transport=rest)

    def dies_before_sending(request, fingerprint, *, timeout):
        raise SystemExit('worker died before the request left')
    gw_a.create_issue = dies_before_sending
    with pytest.raises(SystemExit):
        ensure_task(req(), TaskRegistry(path, clock=clock), gw_a, claimant='a', trusted_authors=None)
    clock.now += 10_000
    reg = TaskRegistry(path, clock=clock)
    gw = GitHubRestGateway(rest.repo, TOKEN, transport=rest)
    assert ensure_task(req(), reg, gw, claimant='b', trusted_authors=None).detail == 'CREATE_UNCERTAIN'
    with pytest.raises(ValueError):
        reg.confirm_not_created(req().fingerprint, '')        # a note is required
    assert reg.confirm_not_created(req().fingerprint, 'operator: no issue with the marker exists') is True
    result = ensure_task(req(), reg, gw, claimant='b', trusted_authors=None)
    assert result.outcome is EnsureOutcome.CREATED and creates(rest) == 1
    assert 'CREATE_INTENT_CLEARED' in [i['reason'] for i in reg.incidents(req().fingerprint)]
