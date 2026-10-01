import pytest

from src.task_engine.repository import SqliteTaskRepository
from src.task_engine.service import TaskEngine
from src.task_engine.model import TaskState
from src.task_governance import (EnsureOutcome, GitHubRestGateway, IdentityDrift, MappingState, TaskRegistry, issue_for_engine_task,
                                 request_from_engine_task,
                                 sync_engine_task_to_issue)
from tests.task_governance.fake_rest import FakeRest

REPO = 'uezeyiraydin-cell/tim-ai-platform'


@pytest.fixture
def world(tmp_path):
    repo = SqliteTaskRepository(tmp_path / 'engine.db')
    rest = FakeRest(REPO)
    yield (TaskEngine(repo), TaskRegistry(str(tmp_path / 'reg.db')), GitHubRestGateway(REPO, 'tok', transport=rest), rest, tmp_path)
    repo.close()


def make(engine, task_id='T-1', **kw):
    base = dict(type='SAMPLE_TASK', title='Sample', objective='Do the thing', source='M09',
                acceptance_criteria=['tests pass'], required_evidence=['ci log'], next_action='start')
    base.update(kw)
    return engine.create_task(task_id, **base)


def sync(engine, reg, gw, task_id='T-1', **kw):
    return sync_engine_task_to_issue(engine, task_id, reg, gw, mission_id='M09', phase_id='P0', claimant='w',
                                     trusted_authors=None, **kw)


def test_request_carries_identity_and_readable_body(world):
    engine, *_ = world
    request = request_from_engine_task(make(engine), mission_id='M09', phase_id='P0')
    assert request.key == 'M09|P0|SAMPLE_TASK|T-1|v1' and request.title == 'Sample'
    for text in ('Do the thing', 'tests pass', 'ci log', 'T-1'):
        assert text in request.body


def test_first_sync_creates_one_issue_and_only_reads_the_engine(world):
    engine, reg, gw, rest, _ = world
    make(engine)
    before = (engine.get_task('T-1'), engine.revision('T-1'))
    result = sync(engine, reg, gw)
    assert result.outcome is EnsureOutcome.CREATED and len(rest.issues) == 1
    assert (engine.get_task('T-1'), engine.revision('T-1')) == before and engine.checkpoints('T-1') == []
    mapping = issue_for_engine_task(reg, 'T-1')
    assert mapping.github_issue_number == result.issue_number and mapping.state is MappingState.MAPPED
    assert issue_for_engine_task(reg, 'nobody') is None


def test_opt_in_checkpoint_records_the_issue_once(world):
    engine, reg, gw, rest, _ = world
    make(engine)
    result = sync(engine, reg, gw, record_checkpoint=True)
    sync(engine, reg, gw, record_checkpoint=True)
    [checkpoint] = engine.checkpoints('T-1')
    assert checkpoint['metadata']['issue'] == result.issue_number and checkpoint['step_id'].startswith('github_issue:')
    assert engine.get_task('T-1').state is TaskState.NEW and engine.get_task('T-1').next_action == 'start'


def test_second_sync_updates_the_same_issue(world):
    engine, reg, gw, rest, _ = world
    make(engine)
    first, again = sync(engine, reg, gw), sync(engine, reg, gw)
    assert again.outcome is EnsureOutcome.UPDATED and again.issue_number == first.issue_number
    assert len(rest.issues) == 1 and engine.checkpoints('T-1') == []


def test_lost_registry_recovers_the_issue_instead_of_creating_another(world):
    engine, reg, gw, rest, tmp_path = world
    make(engine)
    first = sync(engine, reg, gw)
    lost = sync(engine, TaskRegistry(str(tmp_path / 'other.db')), gw)
    assert lost.outcome is EnsureOutcome.RECOVERED and lost.issue_number == first.issue_number and len(rest.issues) == 1


def test_distinct_tasks_get_distinct_issues(world):
    engine, reg, gw, rest, _ = world
    make(engine, 'T-1'), make(engine, 'T-2')
    assert sync(engine, reg, gw, 'T-1').issue_number != sync(engine, reg, gw, 'T-2').issue_number
    assert len(rest.issues) == 2


def test_blocked_sync_leaves_the_engine_task_untouched(world):
    engine, reg, gw, rest, _ = world
    make(engine)
    before = (engine.get_task('T-1'), engine.revision('T-1'), engine.checkpoints('T-1'))
    fp = request_from_engine_task(engine.get_task('T-1'), mission_id='M09', phase_id='P0').fingerprint
    from src.task_governance import fingerprint_marker
    rest.seed(5, fingerprint_marker(fp))
    rest.seed(6, fingerprint_marker(fp))                     # two candidates without a hint: ambiguous
    result = sync(engine, reg, gw)
    assert result.outcome is EnsureOutcome.BLOCKED and result.mapping.state is MappingState.BLOCKED
    assert (engine.get_task('T-1'), engine.revision('T-1'), engine.checkpoints('T-1')) == before


def test_github_outage_leaves_the_engine_task_untouched_and_creates_nothing(world):
    engine, reg, gw, rest, _ = world
    make(engine)
    rest.fail[('GET', r'/issues$')] = 503
    before = engine.revision('T-1')
    with pytest.raises(Exception):
        sync(engine, reg, gw)
    assert not rest.issues and engine.revision('T-1') == before and not engine.checkpoints('T-1')


def test_fixed_task_gets_an_issue_check_but_no_checkpoint(world):
    engine, reg, gw, rest, _ = world
    make(engine)
    now = engine.get_task('T-1').timestamps['updated_at']
    for state in (TaskState.PLANNED, TaskState.READY, TaskState.IN_PROGRESS, TaskState.VERIFYING, TaskState.FIXED):
        engine._repo.transition('T-1', state, at=now)          # repository level: the engine's own FIXED gate is #12's business
    assert sync(engine, reg, gw, record_checkpoint=True).outcome is EnsureOutcome.CREATED
    assert engine.checkpoints('T-1') == []


def test_missing_engine_task_raises_before_any_github_call(world):
    engine, reg, gw, rest, _ = world
    with pytest.raises(Exception):
        sync(engine, reg, gw, 'NOPE')
    assert rest.calls == []


def test_regression_legacy_audit_is_adopted_through_the_bridge_without_a_new_issue(world):
    engine, reg, gw, rest, _ = world
    make(engine, 'BASELINE', type='BASELINE_ARCHITECTURE_AUDIT')
    rest.seed(11, 'legacy audit issue')
    for number in range(22, 66):
        rest.seed(number, 'legacy duplicate')
    result = sync(engine, reg, gw, 'BASELINE', target='TIM')
    assert result.outcome is EnsureOutcome.RECOVERED and result.issue_number == 11
    assert not [c for c in rest.calls if c[0] == 'POST' and c[1].endswith('/issues')]      # nothing created
    assert len(rest.issues) == 45 and all(i['state'] == 'open' for i in rest.issues.values())
    assert sync(engine, reg, gw, 'BASELINE', target='TIM').issue_number == 11
    assert len(rest.issues) == 45


# ---- review round 1 of PR #130 ----
def test_task_ids_differing_only_in_case_get_distinct_identities_and_issues(world):
    engine, reg, gw, rest, _ = world
    make(engine, 'bug-a'), make(engine, 'BUG-A')
    first, second = sync(engine, reg, gw, 'bug-a'), sync(engine, reg, gw, 'BUG-A')
    assert first.issue_number != second.issue_number and len(rest.issues) == 2
    keys = {request_from_engine_task(engine.get_task(t), mission_id='M09', phase_id='P0').key for t in ('bug-a', 'BUG-A')}
    assert len(keys) == 2 and 'M09|P0|SAMPLE_TASK|BUG-A|v1' in keys


@pytest.mark.parametrize('task_id', ['bug a', 'bug|a', 'ünï', 'H-0123456789ABCDEF0123456789ABCDEF'])
def test_unusual_or_reserved_task_ids_still_get_a_valid_unique_identity(world, task_id):
    engine, reg, gw, rest, _ = world
    make(engine, task_id)
    key = request_from_engine_task(engine.get_task(task_id), mission_id='M09', phase_id='P0').key
    assert key.split('|')[3].startswith('H-') and key.split('|')[3] != task_id.upper()
    assert sync(engine, reg, gw, task_id).outcome is EnsureOutcome.CREATED


def test_changed_identity_for_the_same_task_is_refused_before_any_github_call(world):
    engine, reg, gw, rest, _ = world
    make(engine)
    sync(engine, reg, gw)
    calls = len(rest.calls)
    for changed in (dict(phase_id='P1'), dict(schema_version='v2'), dict(task_type='OTHER'), dict(target='ELSE')):
        args = dict(mission_id='M09', phase_id='P0', claimant='w', trusted_authors=None) | changed
        with pytest.raises(IdentityDrift):
            sync_engine_task_to_issue(engine, 'T-1', reg, gw, **args)
    assert len(rest.calls) == calls and len(rest.issues) == 1


# ---- review round 2 of PR #130: the binding must not depend on an engine checkpoint ----
def _force_state(engine, task_id, *states):
    now = engine.get_task(task_id).timestamps['updated_at']
    for state in states:
        engine._repo.transition(task_id, state, at=now)       # repository level: the engine's own gates are #12's business


def test_drift_is_caught_even_when_the_first_run_crashed_after_creating_and_wrote_no_checkpoint(world):
    engine, reg, gw, rest, _ = world
    make(engine)
    rest.lose_create_reply = True
    with pytest.raises(Exception):
        sync(engine, reg, gw)                                 # create landed, reply lost, reconcile cannot list
    assert len(rest.issues) == 1 and engine.checkpoints('T-1') == []
    rest.lose_create_reply = False
    rest.fail.clear()
    with pytest.raises(IdentityDrift):
        sync_engine_task_to_issue(engine, 'T-1', reg, gw, mission_id='M09', phase_id='P1', claimant='w', trusted_authors=None)
    assert len(rest.issues) == 1


def test_drift_is_caught_for_a_fixed_task_that_never_got_a_checkpoint(world):
    engine, reg, gw, rest, _ = world
    make(engine)
    _force_state(engine, 'T-1', TaskState.PLANNED, TaskState.READY, TaskState.IN_PROGRESS, TaskState.VERIFYING, TaskState.FIXED)
    assert sync(engine, reg, gw).outcome is EnsureOutcome.CREATED
    with pytest.raises(IdentityDrift):
        sync_engine_task_to_issue(engine, 'T-1', reg, gw, mission_id='M09', phase_id='P1', claimant='w', trusted_authors=None)
    assert len(rest.issues) == 1


def test_only_active_tasks_get_the_opt_in_checkpoint_and_a_blocked_task_keeps_its_revision(world):
    engine, reg, gw, rest, _ = world
    make(engine, 'T-1'), make(engine, 'T-2')
    engine.block('T-1', 'waiting')
    before = engine.revision('T-1')
    assert sync(engine, reg, gw, 'T-1', record_checkpoint=True).outcome is EnsureOutcome.CREATED
    assert engine.revision('T-1') == before and engine.checkpoints('T-1') == []
    assert sync(engine, reg, gw, 'T-2', record_checkpoint=True).outcome is EnsureOutcome.CREATED
    assert len(engine.checkpoints('T-2')) == 1


def test_a_task_blocked_while_github_is_called_gets_no_checkpoint_and_no_revision_bump(world):
    engine, reg, gw, rest, tmp_path = world
    make(engine)
    supervisor = TaskEngine(SqliteTaskRepository(tmp_path / 'engine.db'))       # a second writer on the same store
    real_create = gw.create_issue

    def create_and_block(*args, **kwargs):
        ref = real_create(*args, **kwargs)
        supervisor.block('T-1', 'stopped by a supervisor')
        return ref
    gw.create_issue = create_and_block
    assert sync(engine, reg, gw, record_checkpoint=True).outcome is EnsureOutcome.CREATED
    after_block = engine.revision('T-1')
    assert engine.get_task('T-1').state is TaskState.BLOCKED and engine.checkpoints('T-1') == []
    assert engine.revision('T-1') == after_block


def test_a_blank_next_action_does_not_break_the_opt_in_checkpoint(world):
    engine, reg, gw, rest, _ = world
    make(engine, next_action='   ')
    assert sync(engine, reg, gw, record_checkpoint=True).outcome is EnsureOutcome.CREATED
    assert engine.checkpoints('T-1')[0]['next_action'] == 'continue task'
    assert sync(engine, reg, gw, record_checkpoint=True).outcome is EnsureOutcome.UPDATED


def test_binding_is_durable_across_registry_reopen_and_an_operator_can_rebind(world):
    engine, reg, gw, rest, tmp_path = world
    make(engine)
    first = sync(engine, reg, gw, record_checkpoint=True)               # leaves an engine checkpoint behind
    reopened = TaskRegistry(str(tmp_path / 'reg.db'))
    with pytest.raises(IdentityDrift):
        sync_engine_task_to_issue(engine, 'T-1', reopened, gw, mission_id='M09', phase_id='P1', claimant='w', trusted_authors=None)
    request = request_from_engine_task(engine.get_task('T-1'), mission_id='M09', phase_id='P1')
    with pytest.raises(ValueError):
        reopened.rebind_engine_task('T-1', request.fingerprint, request.key, ' ')
    reopened.rebind_engine_task('T-1', request.fingerprint, request.key, 'operator moved the task to P1')
    moved = sync_engine_task_to_issue(engine, 'T-1', reopened, gw, mission_id='M09', phase_id='P1', claimant='w', trusted_authors=None)
    assert moved.outcome is EnsureOutcome.CREATED and moved.issue_number != first.issue_number     # no raw SQL needed
    assert issue_for_engine_task(reopened, 'T-1').github_issue_number == moved.issue_number
    assert [i for i in reopened.incidents() if i['reason'] == 'ENGINE_REBOUND']


def test_concurrent_bindings_of_different_identities_all_see_the_first_one(world):
    import threading
    _, reg, *_ = world
    seen = []

    def run(i):
        seen.append(reg.bind_engine_task('T-1', f'fp{i}', f'KEY{i}'))

    threads = [threading.Thread(target=run, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(seen) == 8 and len(set(seen)) == 1


# ---- review round 4 of PR #130 ----
def test_two_engine_tasks_cannot_share_one_identity(world):
    engine, reg, gw, rest, _ = world
    make(engine, 'T-1'), make(engine, 'T-2')
    sync(engine, reg, gw, 'T-1', target='SHARED')
    with pytest.raises(IdentityDrift, match='already bound'):
        sync(engine, reg, gw, 'T-2', target='SHARED')
    other = request_from_engine_task(engine.get_task('T-2'), mission_id='M09', phase_id='P0', target='SHARED')
    with pytest.raises(Exception, match='already bound'):
        reg.rebind_engine_task('T-2', other.fingerprint, other.key, 'try to share')
    assert len(rest.issues) == 1


# ---- review round 6 of PR #130: registry files written by earlier intermediate states ----
def test_a_registry_file_with_two_tasks_on_one_identity_is_reported_once_and_answers_nothing(world):
    import sqlite3
    from src.task_governance import EngineBindingConflict
    _, reg, _, _, tmp_path = world
    reg.bind_engine_task('T-1', 'f' * 64, 'KEY')
    raw = sqlite3.connect(str(tmp_path / 'reg.db'))                    # what an earlier release could have written
    raw.execute("INSERT INTO engine_bindings(task_id,fingerprint,canonical_key,created_at) VALUES('T-2',?,?,0)", ('f' * 64, 'KEY'))
    raw.commit(), raw.close()
    for _ in range(2):                                                 # reopening must not repeat the incident
        reopened = TaskRegistry(str(tmp_path / 'reg.db'))
    found = [i for i in reopened.incidents() if i['reason'] == 'ENGINE_BINDING_DUPLICATE']
    assert len(found) == 1 and 'T-1' in found[0]['detail'] and 'T-2' in found[0]['detail']
    for task in ('T-1', 'T-2'):
        with pytest.raises(EngineBindingConflict, match='rebind_engine_task'):
            issue_for_engine_task(reopened, task)
    clean = TaskRegistry(str(tmp_path / 'clean.db'))
    assert not [i for i in clean.incidents() if i['reason'] == 'ENGINE_BINDING_DUPLICATE']
