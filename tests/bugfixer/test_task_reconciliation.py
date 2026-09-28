import sqlite3
from dataclasses import replace
import pytest
from src.bugfixer.store import IncidentStore
from src.bugfixer.tasks import Task, TaskState, validate_fix_evidence
from tests.bugfixer.test_foundation import event
from tests.bugfixer.repair_fixture import evidence


def test_v1_migration_preserves_incidents_cursor_and_is_idempotent(tmp_path):
    path=tmp_path/'observer.sqlite3';s=IncidentStore(path)
    with s.transaction():
        identity=s.record(event());s.save_checkpoint('source',{'offset':17})
    original=tuple(s.db.execute('SELECT * FROM incidents').fetchone())
    history=[tuple(r) for r in s.db.execute('SELECT * FROM history')];s.close()
    # Reconstruct v1 layout, solely in this synthetic test database.
    with sqlite3.connect(path) as db:
        for table in ['repair_tasks','task_history','incident_repair']:db.execute('DROP TABLE '+table)
        db.execute('PRAGMA user_version=1')
    for _ in range(2):
        s=IncidentStore(path)
        assert tuple(s.db.execute('SELECT * FROM incidents').fetchone())==original
        assert [tuple(r) for r in s.db.execute('SELECT * FROM history')]==history
        assert s.checkpoint('source')=={'offset':17}
        assert s.db.execute('SELECT count(*) FROM repair_tasks').fetchone()[0]==1
        assert s.task_for_incident(identity).state==TaskState.NEW
        s.close()


def test_dependencies_block_and_cycles_refused(tmp_path):
    s=IncidentStore(tmp_path/'observer.sqlite3')
    try:
        with s.transaction():
            a=Task();b=Task(dependencies=(a.id,));s.create_task(a);s.create_task(b)
            with pytest.raises(ValueError,match='cyclic'):s.plan_task(a.id,dependencies=(b.id,))
            s.transition_task(b.id,TaskState.PLANNED,reason='plan',next_action='wait')
            with pytest.raises(ValueError,match='dependencies'):
                s.transition_task(b.id,TaskState.READY,reason='ready',next_action='work')
    finally:s.close()


def test_stale_and_modified_evidence_never_satisfy_fixed(tmp_path):
    task=Task(git_sha='a'*40,attempt_count=1)
    proof=evidence(tmp_path,task)
    assert validate_fix_evidence(task,proof)==proof
    with pytest.raises(ValueError,match='stale'):
        validate_fix_evidence(replace(task,attempt_count=2),proof)
    from pathlib import Path
    Path(proof['repair']['after']['path']).write_text('tampered')
    with pytest.raises(ValueError,match='integrity'):
        validate_fix_evidence(task,proof)
