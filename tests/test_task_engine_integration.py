"""Issue #12 P1.9: Phase 1 integration proof across real process boundaries.

1 create parent maintenance task    6 resume from next_action
2 create dependent BUGFIX child     7 analysis-only FIXED -> rejected
3 persist                           8 attach valid repair/verification evidence
4 valid lifecycle                   9 VERIFYING -> FIXED (child, then parent)
5 restart / session loss            10 reload and verify exact durable state

Evidence here is the synthetic unit-test fixture; the real repair is P1.10.
"""
import json
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from src.task_engine import TaskState
from src.task_engine.fix_first import FixFirstRejected
from src.task_engine.gating import GateRejected
from src.task_engine.repository import SqliteTaskRepository
from src.task_engine.service import TaskEngine
from tests.bugfixer.repair_fixture import evidence as synthetic_evidence

S = TaskState
ROOT = Path(__file__).resolve().parents[1]
SHA = '9' * 40

SESSION = textwrap.dedent('''
    import json, os, sys
    from pathlib import Path
    from src.task_engine import TaskState as S
    from src.task_engine.repository import SqliteTaskRepository
    from src.task_engine.service import TaskEngine
    db, effects, mode, start = sys.argv[1], Path(sys.argv[2]), sys.argv[3], int(sys.argv[4])
    ticks = iter(range(start, start + 50))
    engine = TaskEngine(SqliteTaskRepository(db), clock=lambda: f'2026-09-29T12:{next(ticks):02d}:00+00:00')
    STEPS = [('reproduce', 'reproduce defect in isolation'), ('repair', 'apply repair'),
             ('verify', 'run targeted and regression tests')]
    if mode == 'first':
        # 1-3: parent maintenance task + dependent BUGFIX child, persisted
        engine.create_task('maint-1', type='MAINTENANCE', title='Evidence gate maintenance',
                           required_evidence=['children_summary'], source='issue:12')
        engine.create_task('bug-1', type='BUGFIX', parent_task_id='maint-1', source='incident:demo',
                           title='Gate accepts bad hash', git_sha=sys.argv[5], next_action=STEPS[0][1])
        # 4: valid lifecycle
        for target in (S.PLANNED, S.READY):
            engine.transition_task('maint-1', target)
        for target in (S.PLANNED, S.READY, S.IN_PROGRESS):
            engine.transition_task('bug-1', target)
        task_id = 'bug-1'
    else:
        # 6: resume purely from durable handoff
        handoff = engine.handoff()
        print(json.dumps(handoff, sort_keys=True))
        task_id = handoff['current']['task_id']
    done = set(engine.snapshot(task_id)['completed_steps'])
    for index, (step_id, _) in enumerate(STEPS):
        if step_id in done:
            continue
        if mode == 'first' and step_id == 'verify':
            os._exit(9)  # 5: session lost mid-work, no cleanup
        with effects.open('a') as handle:
            handle.write(step_id + '\\n')
        following = STEPS[index + 1][1] if index + 1 < len(STEPS) else 'move to VERIFYING'
        engine.checkpoint(task_id, step_id, next_action=following, metadata={'verification': step_id.upper()})
    engine.transition_task(task_id, S.VERIFYING)
''')


def session(db, effects, mode, start, *extra, check=True):
    return subprocess.run([sys.executable, '-c', SESSION, str(db), str(effects), mode, str(start), *extra],
                          cwd=ROOT, timeout=60, capture_output=True, text=True, check=check)


def test_phase_1_integration_proof(tmp_path):
    db, effects = tmp_path / 'engine' / 'tasks.sqlite3', tmp_path / 'effects.log'

    # 1-5: first session creates, persists, progresses, then dies mid-step
    first = session(db, effects, 'first', 0, SHA, check=False)
    assert first.returncode == 9, first.stderr
    assert effects.read_text().split() == ['reproduce', 'repair']

    # 6: a new process resumes from next_action without repeating work
    second = session(db, effects, 'resume', 20)
    handoff = json.loads(second.stdout)
    assert handoff['current']['task_id'] == 'bug-1'
    assert handoff['current']['next_action'] == 'run targeted and regression tests'
    assert handoff['current']['completed_steps'] == ['reproduce', 'repair']
    assert handoff['current']['attempt_count'] == 1
    assert effects.read_text().split() == ['reproduce', 'repair', 'verify']

    ticks = iter(range(40, 90))
    with SqliteTaskRepository(db) as repo:
        engine = TaskEngine(repo, clock=lambda: f'2026-09-29T12:{next(ticks):02d}:00+00:00')
        bug = engine.get_task('bug-1')
        assert bug.state is S.VERIFYING and bug.next_action == 'move to VERIFYING'

        # parent cannot close over the unfinished child
        engine.transition_task('maint-1', S.IN_PROGRESS)
        engine.transition_task('maint-1', S.VERIFYING)
        with pytest.raises(GateRejected):
            engine.transition_task('maint-1', S.FIXED)

        # 7: analysis-only closure is rejected and changes nothing
        engine.attach_evidence_ref('bug-1', 'root_cause', 'Gate compares hashes only when present')
        engine.attach_evidence_ref('bug-1', 'analysis', 'Reviewed code; confident this is fixed')
        with pytest.raises(FixFirstRejected):
            engine.transition_task('bug-1', S.FIXED)
        assert engine.get_task('bug-1').state is S.VERIFYING

        # 8: attach content-bound repair + verification evidence
        refs = synthetic_evidence(tmp_path, SimpleNamespace(id='bug-1', attempt_count=bug.attempt_count, git_sha=SHA))
        for name, reference in refs.items():
            engine.attach_evidence_ref('bug-1', name, reference)

        # 9: VERIFYING -> FIXED for the child, then the parent
        assert engine.transition_task('bug-1', S.FIXED).state is S.FIXED
        engine.attach_evidence_ref('maint-1', 'children_summary', 'bug-1 FIXED with verified repair')
        assert engine.transition_task('maint-1', S.FIXED).state is S.FIXED

        expected = {task_id: (engine.get_task(task_id).to_dict(), engine.history(task_id),
                              engine.checkpoints(task_id), engine.evidence(task_id), engine.revision(task_id))
                    for task_id in ('maint-1', 'bug-1')}
        assert engine.resumable_work() == []

    # 10: reload in a fresh connection shows exactly the same durable state
    with SqliteTaskRepository(db) as repo:
        engine = TaskEngine(repo)
        for task_id, state in expected.items():
            assert (engine.get_task(task_id).to_dict(), engine.history(task_id), engine.checkpoints(task_id),
                    engine.evidence(task_id), engine.revision(task_id)) == state
        bug = engine.get_task('bug-1')
        assert bug.state is S.FIXED and bug.attempt_count == 1 and bug.git_sha == SHA
        assert [(h['from_state'], h['to_state']) for h in engine.history('bug-1')] == [
            ('NEW', 'PLANNED'), ('PLANNED', 'READY'), ('READY', 'IN_PROGRESS'),
            ('IN_PROGRESS', 'VERIFYING'), ('VERIFYING', 'FIXED')]
        assert [c['step_id'] for c in engine.checkpoints('bug-1')] == ['reproduce', 'repair', 'verify']
        assert engine.tasks(source='incident:demo') == [bug]
        assert engine.handoff()['current'] is None
