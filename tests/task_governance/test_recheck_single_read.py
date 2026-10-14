from types import SimpleNamespace

import pytest

from src.task_governance import GitHubRestGateway, TaskRequest, fingerprint_marker
from src.task_governance.sync import _recheck_created_issue
from tests.task_governance.fake_rest import FakeRest

TOKEN = 'ghp_SUPERSECRETTOKEN'


def req(**kw):
    base = dict(mission_id='M09', phase_id='P0', task_type='SAMPLE_TASK', target='TIM', schema_version='v1',
                title='Sample', body='the body')
    base.update(kw)
    return TaskRequest(**base)


@pytest.fixture
def rest():
    return FakeRest()


@pytest.fixture
def gw(rest):
    return GitHubRestGateway('owner/repo', TOKEN, transport=rest)


def issue_reads(rest, number):
    return [c for c in rest.calls if c[0] == 'GET' and c[1].endswith(f'/issues/{number}')]


def test_get_issue_then_carries_marker_reads_the_issue_once(rest, gw):
    rest.seed(5, fingerprint_marker(req().fingerprint))
    assert gw.get_issue(5).number == 5
    assert gw.carries_marker(5, req().fingerprint) is True
    assert len(issue_reads(rest, 5)) == 1


def test_carries_marker_is_false_without_the_marker_from_the_remembered_body(rest, gw):
    rest.seed(5, 'no marker here')
    gw.get_issue(5)
    assert gw.carries_marker(5, req().fingerprint) is False
    assert len(issue_reads(rest, 5)) == 1


def test_remembered_body_is_consumed_and_later_calls_read_fresh(rest, gw):
    rest.seed(5, fingerprint_marker(req().fingerprint))
    gw.get_issue(5)
    assert gw.carries_marker(5, req().fingerprint) is True
    rest.issues[5]['body'] = 'marker removed'
    assert gw.carries_marker(5, req().fingerprint) is False
    assert len(issue_reads(rest, 5)) == 2


def test_remembered_body_of_another_number_is_not_used(rest, gw):
    rest.seed(5, 'no marker')
    rest.seed(6, fingerprint_marker(req().fingerprint))
    gw.get_issue(5)
    assert gw.carries_marker(6, req().fingerprint) is True
    assert len(issue_reads(rest, 6)) == 1


def test_carries_marker_without_get_issue_reads_the_issue(rest, gw):
    rest.seed(5, fingerprint_marker(req().fingerprint))
    assert gw.carries_marker(5, req().fingerprint) is True
    assert gw.carries_marker(404, req().fingerprint) is False
    assert len(issue_reads(rest, 5)) == 1


def test_recheck_of_a_created_issue_reads_it_only_once(rest, gw):
    rest.seed(5, fingerprint_marker(req().fingerprint))
    row = SimpleNamespace(block_candidates=(5,))
    verdict = _recheck_created_issue(None, gw, req(), row, None)
    assert verdict == 5
    assert len(issue_reads(rest, 5)) == 1
