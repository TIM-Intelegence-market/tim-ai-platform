"""#68, the authority handover race: a creator that passed its checks, stood still while the designation moved to another
registry, and then went on, must not make a second issue. Three things close it: the designation is asked again right
before the request, that answer and the lookup must be younger than `CREATE_FRESHNESS_SECONDS`, and every create happens
under a repository-wide create claim (a label GitHub creates at most once per name) that is dropped only after the created
issue is recorded. No sleeps: every pause is an event, and one case is a real SIGSTOP of a separate process."""
import multiprocessing as mp
import os
import signal
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from src.task_governance import EnsureOutcome, GitHubError, IssueCreateAuthority, MappingState, TaskRegistry, ensure_task
from src.task_governance import sync
from src.task_governance.create_authority import authority_body
from src.task_governance.github_gateway import claim_label
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
    assert incidents(b)[0][0] == 'GLOBAL_CLAIM_HELD' and f'registry={a.registry_id}' in incidents(b)[0][1]
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


def test_a_claim_of_this_registry_on_this_host_under_an_older_token_is_replaced(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    host = sync._hostname()[:sync.HOLDER_HOST_CHARS]
    hold(rest, f'registry={reg.registry_id} token=0 host={host} at=2026-10-13T21:00Z')   # left by a run that ended without a request
    result = ensure(reg, gateway(rest))
    assert result.outcome is EnsureOutcome.CREATED and rest.labels == {}
    assert [r for r, _ in incidents(reg)] == ['STALE_CLAIM_REPLACED']


@pytest.mark.parametrize('token', ['9', 'x'], ids=['newer', 'unreadable'])
def test_a_claim_of_this_registry_with_a_token_that_is_not_lower_is_not_touched(tmp_path, token):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    host = sync._hostname()[:sync.HOLDER_HOST_CHARS]
    hold(rest, f'registry={reg.registry_id} token={token} host={host}')   # a registry file restored from a backup, or garbage
    result = ensure(reg, gateway(rest))
    assert result.outcome is EnsureOutcome.PENDING and result.detail == 'GLOBAL_CLAIM_HELD'
    assert issue_posts(rest) == [] and LABEL in rest.labels and reg.get(FP).claim_token < 9


def test_a_claim_of_this_registry_on_another_host_is_not_touched(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    hold(rest, f'registry={reg.registry_id} token=1 host=another-host at=2026-10-13T21:00Z')   # a copied registry file
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
    monkeypatch.setattr(sync, '_hostname', lambda: 'a-very-long-host-name-that-goes-on-and-on.example.org')
    text = sync._claim_holder(reg, 10 ** 9)
    assert len(text) <= 100 and sync._claim_fields(text)['registry'] == reg.registry_id
    assert sync._claim_fields(text)['host'] == 'a-very-long-host'
    assert ' at=' not in text                                    # the time is the first thing dropped to fit
    assert ' at=' in sync._claim_holder(reg, 7)


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
