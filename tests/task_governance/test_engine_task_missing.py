import pytest

from src.task_engine.repository import SqliteTaskRepository
from src.task_engine.service import TaskEngine
from src.task_governance import EngineTaskMissing, GitHubRestGateway, IdentityDrift, TaskRegistry, sync_engine_task_to_issue
from tests.task_governance.fake_rest import FakeRest

REPO = 'uezeyiraydin-cell/tim-ai-platform'


def test_missing_engine_task_raises_engine_task_missing_without_side_effects(tmp_path):
    repo = SqliteTaskRepository(tmp_path / 'engine.db')
    try:
        engine = TaskEngine(repo)
        registry = TaskRegistry(str(tmp_path / 'reg.db'))
        rest = FakeRest(REPO)
        gateway = GitHubRestGateway(REPO, 'tok', transport=rest)
        with pytest.raises(EngineTaskMissing) as info:
            sync_engine_task_to_issue(engine, 'T-404', registry, gateway, mission_id='M09', phase_id='P0',
                                      claimant='w', trusted_authors=None)
        assert isinstance(info.value, IdentityDrift)
        assert 'T-404' in str(info.value) and 'no binding' in str(info.value)
        assert rest.calls == []
        assert registry.engine_binding('T-404') is None
    finally:
        repo.close()
