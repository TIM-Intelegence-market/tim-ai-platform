import pytest

from src.task_engine.repository import SqliteTaskRepository
from src.task_engine.service import TaskEngine
from src.task_engine.model import TaskState
from src.task_governance import (EnsureOutcome, GitHubRestGateway, MappingState, TaskRegistry, request_from_engine_task,
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


def test_first_sync_creates_one_issue_and_checkpoints_it(world):
    engine, reg, gw, rest, _ = world
    make(engine)
    result = sync(engine, reg, gw)
    assert result.outcome is EnsureOutcome.CREATED and len(rest.issues) == 1
    [checkpoint] = engine.checkpoints('T-1')
    assert checkpoint['metadata']['issue'] == result.issue_number and checkpoint['step_id'].startswith('github_issue:')
    assert engine.get_task('T-1').state is TaskState.NEW and engine.get_task('T-1').next_action == 'start'


def test_second_sync_updates_the_same_issue_and_adds_no_checkpoint(world):
    engine, reg, gw, rest, _ = world
    make(engine)
    first, again = sync(engine, reg, gw), sync(engine, reg, gw)
    assert again.outcome is EnsureOutcome.UPDATED and again.issue_number == first.issue_number
    assert len(rest.issues) == 1 and len(engine.checkpoints('T-1')) == 1


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
    assert sync(engine, reg, gw).outcome is EnsureOutcome.CREATED
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
