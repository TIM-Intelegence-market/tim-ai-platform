"""#68, the authority handover race: a creator that passed its checks, stood still while the designation moved to another
registry, and then went on, must not make a second issue. Three things close it: the designation is asked again right
before the request, that answer and the lookup must be younger than `CREATE_FRESHNESS_SECONDS`, and every create happens
under a repository-wide create claim (a label GitHub creates at most once per name) that is dropped only after the created
issue is recorded. No sleeps: every pause is an event, and one case is a real SIGSTOP of a separate process."""
import hashlib
import multiprocessing as mp
import os
import shutil
import signal
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from src.task_governance import (CreateNotSent, EnsureOutcome, GitHubError, IssueCreateAuthority, IssueRef, MappingState,
                                 TaskRegistry, ensure_task, fingerprint_marker)
from src.task_governance import sync
from src.task_governance.create_authority import authority_body
from src.task_governance.github_gateway import _NotSent, claim_label
from tests.task_governance.fake_rest import FakeRest
from tests.task_governance.fakes import FakeGitHub
from tests.task_governance.test_create_authority import AUTH_ISSUE, OWNER, REPO, designate, ensure, gateway, registry, req, task_issues

pytestmark = pytest.mark.real_create_authority

FP = req().fingerprint
LABEL = claim_label(FP)


def redesignate(rest, reg):
    """The one-step handover the review found racy: the marker of the designation now names `reg`."""
    rest.issues[AUTH_ISSUE]['body'] = authority_body(reg.registry_id, REPO)


def issue_posts(rest):
    return [c for c in rest.calls if c[0] == 'POST' and c[1].endswith('/issues')]


def pause_at(gw, method, *, call=1, before=False):
    """Make the gateway's `method` signal `reached` and wait for `go` on its `call`-th invocation, after the real call
    (the check passed, then the process stands still) or, with `before`, right before it."""
    reached, go, real, calls = threading.Event(), threading.Event(), getattr(gw, method), []

    def pause():
        reached.set()
        assert go.wait(timeout=10), 'the test never let the paused creator go on'

    def paused(*args, **kwargs):
        calls.append(1)
        if before and len(calls) == call:
            pause()
        result = real(*args, **kwargs)
        if not before and len(calls) == call:
            pause()
        return result

    setattr(gw, method, paused)
    return reached, go


def run_in_thread(fn):
    box = {}

    def target():
        try:
            box['result'] = fn()
        except BaseException as exc:           # pragma: no cover - surfaces in the assertion below
            box['error'] = exc

    thread = threading.Thread(target=target)
    thread.start()
    return thread, box


def finished(thread, box):
    thread.join(20)
    assert not thread.is_alive() and 'error' not in box, box.get('error')
    return box['result']


def incidents(reg, fp=FP):
    return [(i['reason'], i['detail']) for i in reg.incidents(fp)]


def holder(reg, token=0, *, host=None, run=None, ended=False):
    """A claim text of this registry, by default of this host and of a fresh run; `ended=True` records that run as ended
    without a request, which is the one condition under which a run of this registry replaces the label."""
    run = run or sync._new_run()
    if ended:
        reg.note_claim_ended(FP, run)
    return f'registry={reg.registry_id[:16]} token={token} host={host or sync._host_id()} run={run} at=2026-10-13T21:00Z'


def backup_of(reg, dest):
    """A copy of the registry file as a backup would take it (WAL checkpointed first)."""
    reg.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    shutil.copyfile(reg.path, dest)
    return TaskRegistry(dest)


# -- the handover while the old creator stands still ---------------------------------------------------------------------

def test_a_creator_paused_before_its_claim_adopts_the_issue_the_new_creator_made(tmp_path):
    rest = FakeRest()
    a, b = registry(tmp_path, 'a.db'), registry(tmp_path, 'b.db')
    designate(rest, a)
    gw_a, gw_b = gateway(rest), gateway(rest)
    reached, go = pause_at(gw_a, 'authorize_create')           # A passed its first check and stands still
    thread, box = run_in_thread(lambda: ensure(a, gw_a, claimant='a'))
    assert reached.wait(5)
    redesignate(rest, b)
    created = ensure(b, gw_b, claimant='b')
    assert created.outcome is EnsureOutcome.CREATED
    go.set()
    resumed = finished(thread, box)
    assert resumed.outcome is EnsureOutcome.RECOVERED and resumed.issue_number == created.issue_number
    assert len(task_issues(rest)) == 1 and len(issue_posts(rest)) == 1 and rest.labels == {}


def test_a_creator_paused_under_its_claim_is_refused_by_the_second_check_and_the_new_creator_waits(tmp_path):
    rest = FakeRest()
    a, b = registry(tmp_path, 'a.db'), registry(tmp_path, 'b.db')
    designate(rest, a)
    gw_a, gw_b = gateway(rest), gateway(rest)
    reached, go = pause_at(gw_a, 'authorize_create', call=2, before=True)   # A holds the create claim, has not asked again yet
    thread, box = run_in_thread(lambda: ensure(a, gw_a, claimant='a'))
    assert reached.wait(5)
    assert LABEL in rest.labels
    redesignate(rest, b)
    waiting = ensure(b, gw_b, claimant='b')
    assert waiting.outcome is EnsureOutcome.PENDING and waiting.detail == 'GLOBAL_CLAIM_HELD'
    row = b.get(FP)
    assert row.state is MappingState.RELEASED and not row.create_intent
    assert incidents(b)[0][0] == 'GLOBAL_CLAIM_HELD' and f'registry={a.registry_id[:16]} ' in incidents(b)[0][1]
    go.set()
    refused = finished(thread, box)
    assert refused.outcome is EnsureOutcome.BLOCKED and refused.detail == 'CREATE_NOT_AUTHORIZED'
    assert issue_posts(rest) == [] and rest.labels == {}
    row = a.get(FP)
    assert row.state is MappingState.RELEASED and not row.create_intent
    created = ensure(b, gw_b, claimant='b')
    assert created.outcome is EnsureOutcome.CREATED and len(task_issues(rest)) == 1


def test_a_creator_paused_right_before_its_request_creates_once_and_the_new_creator_adopts(tmp_path):
    """The window no check can close: A passed everything and stands still with the request not sent yet."""
    rest = FakeRest()
    a, b = registry(tmp_path, 'a.db'), registry(tmp_path, 'b.db')
    designate(rest, a)
    gw_a, gw_b = gateway(rest), gateway(rest)
    reached, go = pause_at(gw_a, 'create_issue', before=True)
    thread, box = run_in_thread(lambda: ensure(a, gw_a, claimant='a'))
    assert reached.wait(5)
    redesignate(rest, b)
    for _ in range(3):                                           # a scheduler keeps asking: it waits, it never creates
        waiting = ensure(b, gw_b, claimant='b')
        assert waiting.outcome is EnsureOutcome.PENDING and waiting.detail == 'GLOBAL_CLAIM_HELD'
    assert [r for r, _ in incidents(b)] == ['GLOBAL_CLAIM_HELD']
    go.set()
    created = finished(thread, box)
    assert created.outcome is EnsureOutcome.CREATED
    adopted = ensure(b, gw_b, claimant='b')
    assert adopted.outcome is EnsureOutcome.RECOVERED and adopted.issue_number == created.issue_number
    assert len(task_issues(rest)) == 1 and len(issue_posts(rest)) == 1 and rest.labels == {}


def test_the_documented_handover_close_wait_redesignate_never_makes_two_issues(tmp_path):
    rest = FakeRest()
    a, b = registry(tmp_path, 'a.db'), registry(tmp_path, 'b.db')
    designate(rest, a)
    gw_a, gw_b = gateway(rest), gateway(rest, create_authority=IssueCreateAuthority(AUTH_ISSUE + 1))
    reached, go = pause_at(gw_a, 'authorize_create', call=2, before=True)
    thread, box = run_in_thread(lambda: ensure(a, gw_a, claimant='a'))
    assert reached.wait(5)
    rest.issues[AUTH_ISSUE]['state'] = 'closed'                  # step 1: close the old designation
    go.set()                                                     # step 2: the old creator finishes (here: at once)
    refused = finished(thread, box)
    assert refused.detail == 'CREATE_NOT_AUTHORIZED' and issue_posts(rest) == []
    designate(rest, b, number=AUTH_ISSUE + 1)                    # step 3: a new designation for the new creator
    assert ensure(b, gw_b, claimant='b').outcome is EnsureOutcome.CREATED
    assert ensure(a, gw_a, claimant='a').outcome is EnsureOutcome.RECOVERED
    assert len([n for n in task_issues(rest) if n != AUTH_ISSUE + 1]) == 1 and rest.labels == {}


# -- the freshness bound -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize('later', [(100.0, 0.0), (0.0, 100.0)], ids=['monotonic', 'wall'])
def test_a_lookup_older_than_the_bound_on_either_clock_does_not_create(tmp_path, monkeypatch, later):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    clocks = iter([(0.0, 0.0), later])
    monkeypatch.setattr(sync, '_now', lambda: next(clocks, later))
    result = ensure(reg, gateway(rest))
    assert result.outcome is EnsureOutcome.BLOCKED and result.detail == 'CREATE_NOT_AUTHORIZED'
    assert issue_posts(rest) == [] and rest.labels == {}
    row = reg.get(FP)
    assert row.state is MappingState.RELEASED and not row.create_intent
    [(reason, detail)] = incidents(reg)
    assert reason == 'CREATE_NOT_AUTHORIZED' and '100s old' in detail and f'{sync.CREATE_FRESHNESS_SECONDS:g}s' in detail
    monkeypatch.undo()
    assert ensure(reg, gateway(rest)).outcome is EnsureOutcome.CREATED


def test_the_bound_itself_is_fresh_enough(tmp_path, monkeypatch):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    edge = (sync.CREATE_FRESHNESS_SECONDS, sync.CREATE_FRESHNESS_SECONDS)
    clocks = iter([(0.0, 0.0), edge])
    monkeypatch.setattr(sync, '_now', lambda: next(clocks, edge))
    assert ensure(reg, gateway(rest)).outcome is EnsureOutcome.CREATED
    assert sync.CREATE_FRESHNESS_SECONDS == 80.0


# -- the create claim --------------------------------------------------------------------------------------------------

def hold(rest, holder):
    rest.labels[LABEL] = {'name': LABEL, 'color': 'ededed', 'description': holder}


def test_a_claim_held_elsewhere_makes_the_task_pending_until_it_is_released(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    hold(rest, 'registry=' + 'f' * 32 + ' token=1 host=elsewhere at=2026-10-13T22:00Z')
    for _ in range(3):
        result = ensure(reg, gateway(rest))
        assert result.outcome is EnsureOutcome.PENDING and result.detail == 'GLOBAL_CLAIM_HELD'
    assert issue_posts(rest) == [] and [r for r, _ in incidents(reg)] == ['GLOBAL_CLAIM_HELD']
    row = reg.get(FP)
    assert row.state is MappingState.RELEASED and not row.create_intent
    del rest.labels[LABEL]                                       # the holder finished, or an operator who knows it stopped
    assert ensure(reg, gateway(rest)).outcome is EnsureOutcome.CREATED and rest.labels == {}


def test_a_claim_of_a_run_this_registry_recorded_as_ended_is_replaced(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    hold(rest, holder(reg, ended=True))                          # left by a run that ended without a request; its delete was lost
    result = ensure(reg, gateway(rest))
    assert result.outcome is EnsureOutcome.CREATED and rest.labels == {}
    assert [r for r, _ in incidents(reg)] == ['STALE_CLAIM_REPLACED']


@pytest.mark.parametrize('text', ['lower token, unknown run', 'no run', 'garbage run', 'huge token'])
def test_a_claim_of_a_run_this_registry_never_saw_end_is_not_touched(tmp_path, text):
    """Not the token decides, only the recorded end of the run: a restored backup reaches any token by retrying."""
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    hold(rest, {'lower token, unknown run': holder(reg, 0),
                'no run': f'registry={reg.registry_id[:16]} token=0 host={sync._host_id()}',
                'garbage run': holder(reg, 0, run='²'),
                'huge token': holder(reg, '1' * 19, ended=True)}[text])
    result = ensure(reg, gateway(rest))                           # never an exception, never a create
    expected = EnsureOutcome.PENDING if text != 'huge token' else EnsureOutcome.CREATED   # the token is informational only
    assert result.outcome is expected
    if expected is EnsureOutcome.PENDING:
        assert result.detail == 'GLOBAL_CLAIM_HELD' and issue_posts(rest) == [] and LABEL in rest.labels


def test_our_registry_host_and_token_with_another_run_count_as_held(tmp_path):
    """The run id is the identity: a twin that shares the registry file and token is another run."""
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    hold(rest, sync._claim_holder(reg, 1, sync._new_run()))
    result = ensure(reg, gateway(rest))
    assert result.outcome is EnsureOutcome.PENDING and result.detail == 'GLOBAL_CLAIM_HELD' and issue_posts(rest) == []


def test_a_claim_request_whose_answer_was_lost_is_recognised_as_ours_by_the_run(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    gw = gateway(rest)
    real = gw.claim_create

    def lost(fingerprint, text):
        real(fingerprint, text)                                   # the label exists, the answer never arrives
        raise GitHubError('POST /repos/owner/repo/labels: timed out')

    gw.claim_create = lost
    result = ensure(reg, gw)
    assert result.outcome is EnsureOutcome.CREATED and rest.labels == {} and len(issue_posts(rest)) == 1
    assert incidents(reg) == []


def test_two_hosts_whose_names_share_a_prefix_are_different_hosts(tmp_path, monkeypatch):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    monkeypatch.setattr(sync, '_hostname', lambda: 'tim-checkup-prod-02')
    twin = sync._host_id()
    monkeypatch.setattr(sync, '_hostname', lambda: 'tim-checkup-prod-01')
    assert twin != sync._host_id() and twin.startswith('tim-checku-') and len(twin) == 17
    hold(rest, holder(reg, host=twin, ended=True))               # an unrotated copy of our registry on the twin
    result = ensure(reg, gateway(rest))
    assert result.outcome is EnsureOutcome.PENDING and result.detail == 'GLOBAL_CLAIM_HELD' and issue_posts(rest) == []


def test_a_claim_of_this_registry_on_another_host_is_not_touched(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    hold(rest, holder(reg, 1, host='another-ho-abcdef', ended=True))   # a copied registry file
    result = ensure(reg, gateway(rest))
    assert result.outcome is EnsureOutcome.PENDING and result.detail == 'GLOBAL_CLAIM_HELD'
    assert issue_posts(rest) == [] and LABEL in rest.labels


def test_the_claim_is_dropped_after_the_create_and_kept_while_the_outcome_is_uncertain(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    gw = gateway(rest)
    rest.fail[('POST', r'/issues$')] = TimeoutError('no answer')
    with pytest.raises(GitHubError):
        ensure(reg, gw)
    row = reg.get(FP)
    assert row.state is MappingState.CLAIMED and row.create_intent and LABEL in rest.labels   # nobody creates behind it
    assert 'CREATE_UNCERTAIN' in [r for r, _ in incidents(reg)]
    del rest.fail[('POST', r'/issues$')]
    assert ensure(reg, gw).detail == 'claim held by w' and LABEL in rest.labels
    other = registry(tmp_path, 'other.db')
    redesignate(rest, other)                                     # even a newly designated registry waits
    assert ensure(other, gateway(rest), claimant='x').detail == 'GLOBAL_CLAIM_HELD'
    assert len(issue_posts(rest)) == 1 and task_issues(rest) == []        # the one request that got no answer


def test_a_failed_claim_release_is_an_incident_and_the_created_issue_is_still_adopted(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    rest.fail[('DELETE', r'/labels/')] = 503
    result = ensure(reg, gateway(rest))
    assert result.outcome is EnsureOutcome.CREATED and LABEL in rest.labels
    assert [r for r, _ in incidents(reg)] == ['CLAIM_RELEASE_FAILED']
    lost = ensure(registry(tmp_path, 'lost.db'), gateway(rest), claimant='x')
    assert lost.outcome is EnsureOutcome.RECOVERED and lost.issue_number == result.issue_number   # found before any claim
    assert len(task_issues(rest)) == 1


def test_an_invalid_claim_request_is_an_error_and_never_counts_as_held(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    rest.fail[('POST', r'/labels$')] = 422                       # 422 without a label behind it
    with pytest.raises(GitHubError, match='HTTP 422 but the label does not exist'):
        ensure(reg, gateway(rest))
    row = reg.get(FP)
    assert row.state is MappingState.RELEASED and not row.create_intent and issue_posts(rest) == []


def test_a_gateway_without_the_claim_never_creates(tmp_path):
    class NoClaim(FakeGitHub):
        claim_create = None

    fake = NoClaim(str(tmp_path / 'gh.db'))
    reg = registry(tmp_path)
    result = ensure_task(req(), reg, fake, claimant='w', trusted_authors=None)
    assert result.outcome is EnsureOutcome.BLOCKED and result.detail == 'CREATE_NOT_AUTHORIZED'
    assert fake.count() == 0
    row = reg.get(FP)
    assert row.state is MappingState.RELEASED and not row.create_intent


def test_the_claim_label_and_its_text_fit_github(tmp_path, monkeypatch):
    assert LABEL.startswith('tim-claim-') and len(LABEL) == 42 <= 50
    reg = registry(tmp_path)
    name = 'a-very-long-host-name-that-goes-on-and-on.example.org'
    monkeypatch.setattr(sync, '_hostname', lambda: name)
    run = sync._new_run()
    text = sync._claim_holder(reg, 10 ** 9, run)
    assert len(text) <= 100 and sync._claim_fields(text)['registry'] == reg.registry_id[:16]
    assert sync._claim_fields(text)['host'] == 'a-very-lon-' + hashlib.sha256(name.encode()).hexdigest()[:6]
    assert sync._holder_run(text) == run and len(run) == 12
    assert ' at=' not in text                                    # the time is the first thing dropped to fit
    assert ' at=' in sync._claim_holder(reg, 10 ** 7 - 1, run)   # seven digits of token still fit with the time


def test_a_lookup_failure_under_the_claim_releases_it_and_creates_nothing(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    gw = gateway(rest)
    real, calls = gw.find_issues, []

    def flaky(fingerprint, key):
        calls.append(1)
        if len(calls) == 2:                                      # the lookup under the claim fails
            raise GitHubError('GET /repos/owner/repo/issues: HTTP 502')
        return real(fingerprint, key)

    gw.find_issues = flaky
    with pytest.raises(GitHubError):
        ensure(reg, gw)
    row = reg.get(FP)
    assert row.state is MappingState.RELEASED and not row.create_intent and rest.labels == {} and issue_posts(rest) == []
    assert ensure(reg, gw).outcome is EnsureOutcome.CREATED


def test_a_slow_lookup_under_the_claim_does_not_count_against_the_bound(tmp_path, monkeypatch):
    """Under the claim nobody else creates, so the lookup cannot go stale; only the authority answer must be fresh."""
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    gw = gateway(rest)
    clock, real, calls = [0.0], gw.find_issues, []

    def slow(fingerprint, key):
        calls.append(1)
        if len(calls) == 2:                                      # the lookup under the claim takes long (many direct reads)
            clock[0] += 10 * sync.CREATE_FRESHNESS_SECONDS
        return real(fingerprint, key)

    gw.find_issues = slow
    monkeypatch.setattr(sync, '_now', lambda: (clock[0], clock[0]))
    assert ensure(reg, gw).outcome is EnsureOutcome.CREATED


def test_an_unknown_issue_kind_under_the_claim_leaves_no_create_intent(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    gw = gateway(rest)
    real, calls = gw.find_issues, []

    def unknown_under_claim(fingerprint, key):
        calls.append(1)
        if len(calls) == 2:
            return [IssueRef(77, 'open', author=OWNER, is_pull_request=None)]     # the gateway did not say issue or PR
        return real(fingerprint, key)

    gw.find_issues = unknown_under_claim
    result = ensure(reg, gw)
    assert result.outcome is EnsureOutcome.BLOCKED and result.detail == 'UNKNOWN_ISSUE_KIND'
    row = reg.get(FP)
    assert row.state is MappingState.BLOCKED and not row.create_intent and rest.labels == {} and issue_posts(rest) == []
    gw.find_issues = real                                        # the kind is reported on the next run: it creates, no CREATE_UNCERTAIN
    again = ensure(reg, gw)
    assert again.outcome is EnsureOutcome.CREATED and 'CREATE_UNCERTAIN' not in [r for r, _ in incidents(reg)]


# -- the same registry: a paused run is never taken over --------------------------------------------------------------

def test_a_paused_run_of_the_same_registry_is_not_taken_over_after_its_lease(tmp_path):
    rest = FakeRest()
    clock = [1000.0]
    reg1 = TaskRegistry(str(tmp_path / 'a.db'), clock=lambda: clock[0])
    reg2 = TaskRegistry(str(tmp_path / 'a.db'), clock=lambda: clock[0])
    designate(rest, reg1)
    gw1, gw2 = gateway(rest), gateway(rest)
    reached, go = pause_at(gw1, 'create_issue', before=True)
    thread, box = run_in_thread(lambda: ensure(reg1, gw1, claimant='run-1'))
    assert reached.wait(5)
    clock[0] += 400                                              # the lease (300 s) ran out while run 1 stands still
    second = ensure(reg2, gw2, claimant='run-2')
    assert second.outcome is EnsureOutcome.BLOCKED and second.detail == 'CREATE_UNCERTAIN'   # not GLOBAL_CLAIM_HELD, not a take-over
    assert LABEL in rest.labels and issue_posts(rest) == []
    go.set()
    first = finished(thread, box)
    assert first.detail == 'CLAIM_LOST_AFTER_CREATE' and first.created
    assert len(task_issues(rest)) == 1 and rest.labels == {}


# -- the race review of 2026-10-14: C1 (late delete), C2 (restored backup), C5 (label leak) -----------------------------

def test_a_run_that_gives_up_cannot_delete_the_label_of_a_sibling_run(tmp_path):
    """C1: run 1 of a registry file gives up under its claim (its create never left) and stands still right before its
    DELETE; run 2 of the same file must not get the claim meanwhile (run 1 still holds the row), so run 1's late DELETE
    hits only its own label; after the handover the new creator creates the one issue."""
    rest = FakeRest()
    reg1, reg2, other = registry(tmp_path, 'shared.db'), registry(tmp_path, 'shared.db'), registry(tmp_path, 'b.db')
    designate(rest, reg1)
    gw1, gw2 = gateway(rest), gateway(rest)
    rest.fail[('POST', r'/issues$')] = _NotSent()
    reached, go = pause_at(gw1, 'release_create_claim', before=True)
    thread, box = run_in_thread(lambda: ensure(reg1, gw1, claimant='run-1'))
    assert reached.wait(5)
    del rest.fail[('POST', r'/issues$')]
    row = reg1.get(FP)
    assert row.state is MappingState.CLAIMED and row.create_intent and LABEL in rest.labels   # the row is kept until the delete
    second = ensure(reg2, gw2, claimant='run-2')
    assert second.outcome is EnsureOutcome.PENDING and second.detail == 'claim held by run-1'
    assert 'STALE_CLAIM_REPLACED' not in [r for r, _ in incidents(reg2)] and LABEL in rest.labels
    go.set()
    thread.join(20)
    assert isinstance(box.get('error'), CreateNotSent)          # run 1 ends as it would have: nothing was sent
    row = reg1.get(FP)
    assert row.state is MappingState.RELEASED and not row.create_intent and rest.labels == {}
    assert reg1.claim_ended(FP, row.create_run)
    redesignate(rest, other)
    created = ensure(other, gateway(rest), claimant='b')
    assert created.outcome is EnsureOutcome.CREATED
    assert ensure(reg2, gw2, claimant='run-2').outcome is EnsureOutcome.RECOVERED
    assert len(task_issues(rest)) == 1 and len(issue_posts(rest)) == 2 and rest.labels == {}   # the first request never left


def test_a_registry_restored_from_a_backup_never_replaces_the_claim_of_the_live_original(tmp_path):
    """C2: the restored file shares id and host with the original and reaches every token by retrying; the run id of the
    original's live holder is not in its `claim_ends`, so it waits however often it runs."""
    rest = FakeRest()
    reg = registry(tmp_path, 'a.db')
    designate(rest, reg)
    rest.issues[AUTH_ISSUE]['state'] = 'closed'                  # two refused runs: tokens 1 and 2, then a backup
    assert ensure(reg, gateway(rest)).detail == 'CREATE_NOT_AUTHORIZED'
    restored = backup_of(reg, str(tmp_path / 'a.restored.db'))
    assert ensure(reg, gateway(rest)).detail == 'CREATE_NOT_AUTHORIZED'
    rest.issues[AUTH_ISSUE]['state'] = 'open'
    gw = gateway(rest)
    reached, go = pause_at(gw, 'create_issue', before=True)       # the original holds the claim and stands still
    thread, box = run_in_thread(lambda: ensure(reg, gw, claimant='original'))
    assert reached.wait(5)
    assert restored.registry_id == reg.registry_id
    for _ in range(6):                                           # the scheduler retries; the token passes the holder's
        waiting = ensure(restored, gateway(rest), claimant='restored')
        assert waiting.outcome is EnsureOutcome.PENDING and waiting.detail == 'GLOBAL_CLAIM_HELD'
    assert restored.get(FP).claim_token > reg.get(FP).claim_token and issue_posts(rest) == []
    assert 'STALE_CLAIM_REPLACED' not in [r for r, _ in incidents(restored)]
    go.set()
    assert finished(thread, box).outcome is EnsureOutcome.CREATED
    assert ensure(restored, gateway(rest), claimant='restored').outcome is EnsureOutcome.RECOVERED
    assert len(task_issues(rest)) == 1 and rest.labels == {}


def test_an_uncertain_create_resolved_by_the_first_lookup_drops_the_label(tmp_path):
    """C5: the label kept for an uncertain create goes once the issue is visible and adopted."""
    rest = FakeRest()
    clock = [1000.0]
    reg = TaskRegistry(str(tmp_path / 'a.db'), clock=lambda: clock[0])
    designate(rest, reg)
    gw = gateway(rest)
    rest.lose_create_reply = True
    with pytest.raises(GitHubError):
        ensure(reg, gw)
    rest.lose_create_reply = False
    del rest.fail[('GET', r'/issues$')]
    row = reg.get(FP)
    assert row.state is MappingState.CLAIMED and row.create_intent and LABEL in rest.labels
    clock[0] += 400                                              # the lease is over, the issue is visible now
    result = ensure(reg, gw)
    assert result.outcome is EnsureOutcome.RECOVERED and reg.get(FP).state is MappingState.MAPPED
    assert rest.labels == {} and len(task_issues(rest)) == 1


def test_a_run_that_noted_its_end_but_lost_its_row_release_leaves_no_uncertain_create(tmp_path):
    """A crash between the note and the row release heals at the next takeover: the recorded run ended without a request."""
    rest = FakeRest()
    clock = [1000.0]
    reg = TaskRegistry(str(tmp_path / 'a.db'), clock=lambda: clock[0])
    designate(rest, reg)
    won, mapping = reg.claim(FP, req().key, 'crashed', 300.0)
    run = sync._new_run()
    assert won and reg.begin_create(FP, mapping.claim_token, REPO, run)
    reg.note_claim_ended(FP, run)                                # its label is gone (or replaceable), then it died
    clock[0] += 400
    result = ensure(reg, gateway(rest))
    assert result.outcome is EnsureOutcome.CREATED
    assert [r for r, _ in incidents(reg)] == ['STALE_INTENT_CLEARED'] and len(task_issues(rest)) == 1


def test_the_operator_confirmation_lets_the_next_run_replace_the_dead_holders_label(tmp_path):
    rest = FakeRest()
    clock = [1000.0]
    reg = TaskRegistry(str(tmp_path / 'a.db'), clock=lambda: clock[0])
    designate(rest, reg)
    gw = gateway(rest)
    rest.fail[('POST', r'/issues$')] = TimeoutError('no answer')   # nothing created, nobody can know
    with pytest.raises(GitHubError):
        ensure(reg, gw)
    del rest.fail[('POST', r'/issues$')]
    clock[0] += 400
    assert ensure(reg, gw).detail == 'CREATE_UNCERTAIN' and LABEL in rest.labels
    assert not reg.confirm_not_created(FP, 'checked GitHub, worker stopped')   # not before the quiet hour
    clock[0] += 3600
    assert reg.confirm_not_created(FP, 'checked GitHub, worker stopped')
    result = ensure(reg, gw)
    assert result.outcome is EnsureOutcome.CREATED and rest.labels == {} and len(task_issues(rest)) == 1
    assert 'STALE_CLAIM_REPLACED' in [r for r, _ in incidents(reg)]


def test_a_label_another_run_holds_by_now_is_never_deleted_by_name(tmp_path):
    """Defence in depth under the rule above: a release reads the label first and leaves another holder's label alone."""
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    gw = gateway(rest)
    real = gw.create_issue

    def swapped(request, fingerprint, *, timeout):               # while we create, someone replaced our label by hand
        issue = real(request, fingerprint, timeout=timeout)
        hold(rest, holder(registry(tmp_path, 'other.db'), 1))
        return issue

    gw.create_issue = swapped
    result = ensure(reg, gw)
    assert result.outcome is EnsureOutcome.CREATED and LABEL in rest.labels
    assert [r for r, _ in incidents(reg)] == ['CLAIM_NOT_OURS']


# -- the second race review of 2026-10-14: two replacers (A1), a healed takeover (A6), an unknown kind (A7) -------------

def test_two_replacers_of_one_dead_runs_label_make_one_issue(tmp_path):
    """A1: the original and a backup restored on the same host both know the dead run; the slower replacer must not
    delete the faster replacer's live label by name."""
    rest = FakeRest()
    reg = registry(tmp_path, 'a.db')
    designate(rest, reg)
    gw = gateway(rest)
    rest.fail[('POST', r'/issues$')] = _NotSent()                # a run gives up under its claim ...
    rest.fail[('DELETE', r'/labels/')] = 503                     # ... and its drop fails: the dead run's label stands
    with pytest.raises(CreateNotSent):
        ensure(reg, gw)
    rest.fail.clear()
    dead = reg.get(FP).create_run
    assert reg.claim_ended(FP, dead) and sync._holder_run(rest.labels[LABEL]['description']) == dead
    restored = backup_of(reg, str(tmp_path / 'a.restored.db'))
    gw_o, gw_r = gateway(rest), gateway(rest)
    reached, go = pause_at(gw_o, 'create_claim_holder', before=True)   # the original: 422, dead run, about to re-read
    thread, box = run_in_thread(lambda: ensure(reg, gw_o, claimant='original'))
    assert reached.wait(5)
    r_reached, r_go = pause_at(gw_r, 'create_issue', before=True)      # the restored copy replaces the label and creates
    r_thread, r_box = run_in_thread(lambda: ensure(restored, gw_r, claimant='restored'))
    assert r_reached.wait(5)
    assert 'STALE_CLAIM_REPLACED' in [r for r, _ in incidents(restored)]
    go.set()
    original = finished(thread, box)
    assert original.outcome is EnsureOutcome.PENDING and original.detail == 'GLOBAL_CLAIM_HELD'
    assert [r for r, _ in incidents(reg)][-2:] == ['CLAIM_NOT_OURS', 'GLOBAL_CLAIM_HELD'] and LABEL in rest.labels
    r_go.set()
    assert finished(r_thread, r_box).outcome is EnsureOutcome.CREATED
    assert ensure(reg, gw_o, claimant='original').outcome is EnsureOutcome.RECOVERED
    assert len(task_issues(rest)) == 1 and rest.labels == {}


def test_a_label_taken_away_right_before_the_request_stops_the_create(tmp_path):
    """The victim side of a raced replacement (or a hand deletion): one read before the request, no request when the
    label does not name this run any more."""
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    gw = gateway(rest)
    reached, go = pause_at(gw, 'create_claim_holder', before=True)     # the look right before the request
    thread, box = run_in_thread(lambda: ensure(reg, gw, claimant='victim'))
    assert reached.wait(5)
    ours = reg.get(FP).create_run
    hold(rest, holder(registry(tmp_path, 'other.db'), 1))              # replaced meanwhile
    go.set()
    result = finished(thread, box)
    assert result.outcome is EnsureOutcome.PENDING and result.detail == 'CLAIM_LOST_BEFORE_CREATE'
    assert issue_posts(rest) == [] and LABEL in rest.labels              # the other holder's label is left alone
    row = reg.get(FP)
    assert row.state is MappingState.RELEASED and not row.create_intent and reg.claim_ended(FP, ours)
    assert [r for r, _ in incidents(reg)] == ['CLAIM_LOST_BEFORE_CREATE']


def test_a_healed_takeover_that_adopts_drops_the_dead_runs_label(tmp_path):
    """A6: run 1 finds the issue under its claim, fails while adopting and while dropping its label, notes its end and
    dies; the takeover clears the stale intent, adopts, and the label goes with it."""
    rest = FakeRest()
    clock = [1000.0]
    reg1 = TaskRegistry(str(tmp_path / 'a.db'), clock=lambda: clock[0])
    reg2 = TaskRegistry(str(tmp_path / 'a.db'), clock=lambda: clock[0])
    designate(rest, reg1)
    gw = gateway(rest)
    reached, go = pause_at(gw, 'claim_create')
    thread, box = run_in_thread(lambda: ensure(reg1, gw, claimant='run-1'))
    assert reached.wait(5)
    rest.seed(50, body=fingerprint_marker(FP))                      # visible to the lookup under the claim only
    rest.fail[('PATCH', r'/issues/50$')] = 503
    rest.fail[('DELETE', r'/labels/')] = 503
    go.set()
    thread.join(20)
    assert isinstance(box.get('error'), GitHubError)
    row = reg1.get(FP)
    assert row.state is MappingState.CLAIMED and row.create_intent and reg1.claim_ended(FP, row.create_run)
    assert LABEL in rest.labels
    rest.fail.clear()
    clock[0] += 400
    result = ensure(reg2, gateway(rest), claimant='run-2')
    assert result.outcome is EnsureOutcome.RECOVERED and result.issue_number == 50
    assert [r for r, _ in incidents(reg2)] == ['CLAIM_RELEASE_FAILED', 'STALE_INTENT_CLEARED'] and rest.labels == {}


def test_an_unknown_kind_after_an_uncertain_create_keeps_the_label_with_the_intent(tmp_path):
    """A7: the request may have reached GitHub and the reconcile lookup cannot tell issue from PR: the intent stays, so
    the label stays; the re-validation drops it with the adoption."""
    rest = FakeRest()
    clock = [1000.0]
    reg = TaskRegistry(str(tmp_path / 'a.db'), clock=lambda: clock[0])
    designate(rest, reg)
    gw = gateway(rest)
    rest.fail[('POST', r'/issues$')] = TimeoutError('no answer')
    real, calls = gw.find_issues, []

    def unknown_after_create(fingerprint, key):
        calls.append(1)
        if len(calls) == 3:                                          # the reconcile lookup
            return [IssueRef(77, 'open', author=OWNER, is_pull_request=None)]
        return real(fingerprint, key)

    gw.find_issues = unknown_after_create
    result = ensure(reg, gw)
    assert result.outcome is EnsureOutcome.BLOCKED and result.detail == 'UNKNOWN_ISSUE_KIND'
    row = reg.get(FP)
    assert row.create_intent and LABEL in rest.labels
    other = registry(tmp_path, 'other.db')
    redesignate(rest, other)
    assert ensure(other, gateway(rest), claimant='x').detail == 'GLOBAL_CLAIM_HELD'   # nobody creates behind it
    del rest.fail[('POST', r'/issues$')]
    gw.find_issues = real
    rest.seed(77, body=fingerprint_marker(FP))                       # the kind is reported now: an issue, adopted
    clock[0] += 400
    again = ensure(reg, gw)
    assert again.outcome is EnsureOutcome.RECOVERED and again.issue_number == 77 and rest.labels == {}


# -- a real SIGSTOP of a separate process -----------------------------------------------------------------------------

class Designated(FakeGitHub):
    """FakeGitHub whose designation is a file, so a parent and a child process share it."""

    def __init__(self, path, control):
        super().__init__(path)
        self.control = Path(control)

    def authorize_create(self, registry_id, trusted_authors):
        from src.task_governance import CreateNotAuthorized
        if (self.control / 'designated').read_text().strip() != registry_id:
            raise CreateNotAuthorized('not designated')

    def create_issue(self, request, fingerprint, *, timeout):
        (self.control / 'at-post').write_text(str(os.getpid()))  # the parent stops us here, with SIGSTOP
        deadline = time.monotonic() + 30
        while not (self.control / 'go').exists():
            if time.monotonic() > deadline:
                raise RuntimeError('never let go')
            time.sleep(0.01)
        return super().create_issue(request, fingerprint, timeout=timeout)


def _old_creator(reg_path, gh_path, control):
    result = ensure_task(req(), TaskRegistry(reg_path), Designated(gh_path, control), claimant='old', trusted_authors=None)
    (Path(control) / 'old-result').write_text(f'{result.outcome.value} {result.issue_number}')


def _wait_for(path, timeout=20):
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert time.monotonic() < deadline, f'{path.name} never appeared'
        time.sleep(0.01)


def test_a_creator_stopped_by_sigstop_before_its_request_cannot_be_doubled(tmp_path):
    control, gh_path = tmp_path / 'control', str(tmp_path / 'gh.db')
    control.mkdir()
    old, new = TaskRegistry(str(tmp_path / 'old.db')), TaskRegistry(str(tmp_path / 'new.db'))
    (control / 'designated').write_text(old.registry_id)
    old.close()
    gh = Designated(gh_path, control)
    ctx = mp.get_context('spawn')
    child = ctx.Process(target=_old_creator, args=(str(tmp_path / 'old.db'), gh_path, str(control)))
    child.start()
    try:
        _wait_for(control / 'at-post')
        os.kill(child.pid, signal.SIGSTOP)                       # frozen with every check passed and the request not sent
        (control / 'designated').write_text(new.registry_id)     # the handover happens while it is frozen
        (control / 'go').write_text('')                          # it will send the moment it runs again
        waiting = ensure_task(req(), new, gh, claimant='new', trusted_authors=None)
        assert waiting.outcome is EnsureOutcome.PENDING and waiting.detail == 'GLOBAL_CLAIM_HELD'
        assert gh.count() == 0
        os.kill(child.pid, signal.SIGCONT)
        child.join(30)
        assert child.exitcode == 0
    finally:
        if child.is_alive():                                     # pragma: no cover
            os.kill(child.pid, signal.SIGCONT)
            child.kill()
    assert (control / 'old-result').read_text().startswith('CREATED')
    adopted = ensure_task(req(), new, gh, claimant='new', trusted_authors=None)
    assert adopted.outcome is EnsureOutcome.RECOVERED and gh.count() == 1 and gh.claims() == {}
    assert sqlite3.connect(gh_path).execute("SELECT COUNT(*) FROM log WHERE op='create'").fetchone()[0] == 1
