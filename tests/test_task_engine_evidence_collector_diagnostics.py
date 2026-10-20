import sys

import pytest

from src.task_engine import evidence_collector
from src.task_engine.evidence_collector import EvidenceCollector, ReproductionFailed


def _collector(tmp_path):
    workspace = tmp_path / 'workspace'
    out = tmp_path / 'out'
    workspace.mkdir()
    out.mkdir()
    collector = object.__new__(EvidenceCollector)
    collector.python = sys.executable
    collector.workspace = workspace
    collector.out = out
    collector.timeout = 120
    return collector, workspace


def test_failing_test_tails_are_redacted(tmp_path):
    collector, workspace = _collector(tmp_path)
    (workspace / 'test_secret.py').write_text(
        "def test_secret():\n    print('password=hunter2')\n    assert False\n")
    result = collector.pytest(['test_secret.py'], 'diag')
    assert result['counts']['failure'] == 1
    assert 'failed' in result['stdout_tail']
    assert 'hunter2' not in result['stdout_tail']
    assert 'hunter2' not in result['stderr_tail']


def test_passing_test_has_string_tails(tmp_path):
    collector, workspace = _collector(tmp_path)
    (workspace / 'test_ok.py').write_text('def test_ok():\n    assert True\n')
    result = collector.pytest(['test_ok.py'], 'diag_ok')
    assert result['exit_status'] == 0
    assert isinstance(result['stdout_tail'], str)
    assert isinstance(result['stderr_tail'], str)


def test_missing_junit_report_raises_reproduction_failed_with_exit_status(tmp_path, monkeypatch):
    collector, workspace = _collector(tmp_path)
    (workspace / 'test_ok.py').write_text('def test_ok():\n    assert True\n')

    def missing(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(evidence_collector, 'junit_summary', missing)
    with pytest.raises(ReproductionFailed) as info:
        collector.pytest(['test_ok.py'], 'diag_missing')
    message = str(info.value)
    assert 'diag_missing' in message
    assert 'exit status 0' in message
