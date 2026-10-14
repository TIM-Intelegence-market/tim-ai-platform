import json

import pytest

from src.task_governance import live_check
from src.task_governance.live_check import PRODUCTION_REPOSITORY, TOKEN_VARIABLE, main
from tests.task_governance.fake_rest import FakeRest

REPO = 'owner/throwaway'
TOKEN = 'ghp_SECRETSECRETSECRET'


def run(rest, *args, token=TOKEN):
    environ = {TOKEN_VARIABLE: token} if token else {}
    return main(['--repo', rest.repo, *args], environ=environ, transport=rest)


def test_readonly_mode_sends_only_gets_and_passes_against_a_healthy_repository(capsys):
    rest = FakeRest(REPO)
    rest.seed(7, 'plain human issue')
    assert run(rest, '--probe-issue', '7') == 0
    report = json.loads(capsys.readouterr().out)
    assert report['ok'] and [c['name'] for c in report['checks']] == [
        'repository_visible', 'token_user', 'listing_is_complete', 'missing_issue_is_a_confirmed_404', 'probe_issue_readable']
    assert rest.writes() == []


def test_a_failing_check_is_reported_and_does_not_hide_the_others(capsys):
    rest = FakeRest(REPO)
    rest.fail[('GET', r'/issues$')] = 403
    assert run(rest) == 1
    report = json.loads(capsys.readouterr().out)
    by_name = {c['name']: c for c in report['checks']}
    assert not report['ok'] and not by_name['listing_is_complete']['ok'] and 'SECRET-DETAIL' not in json.dumps(report)
    assert by_name['repository_visible']['ok'] and by_name['missing_issue_is_a_confirmed_404']['ok']


def test_an_invisible_repository_fails_loudly(capsys):
    rest = FakeRest(REPO)
    rest.repo_visible = False
    assert run(rest) == 1
    assert not json.loads(capsys.readouterr().out)['ok']


def test_roundtrip_creates_one_issue_updates_it_and_adopts_it_after_a_lost_registry(capsys):
    rest = FakeRest(REPO)
    assert run(rest, '--mode', 'roundtrip', '--confirm-write', REPO) == 0
    report = json.loads(capsys.readouterr().out)
    names = {c['name']: c for c in report['checks']}
    assert report['ok'] and len(rest.issues) == 1
    assert [c for c in rest.writes() if c[0] == 'POST' and c[1].endswith('/issues')] != [] and \
        len([c for c in rest.writes() if c[0] == 'POST' and c[1].endswith('/issues')]) == 1
    assert names['lost_registry_adopts_instead_of_creating']['ok'] and names['exactly_one_issue_carries_the_marker']['ok']
    assert names['create_claim_released']['ok'] and rest.labels == {}       # the create claim (#68) was taken and dropped
    assert [c[0] for c in rest.writes() if '/labels' in c[1]] == ['POST', 'DELETE']
    assert 'close it by hand' in names['cleanup']['detail']


def test_roundtrip_fails_when_the_lost_registry_would_create_a_second_issue(capsys, monkeypatch):
    rest = FakeRest(REPO)
    original = live_check.sync_engine_task_to_issue
    calls = []

    def lying_sync(*a, **k):
        result = original(*a, **k)
        calls.append(result)
        if len(calls) == 3:                                         # pretend the third run created a new issue
            from dataclasses import replace
            return replace(result, outcome=live_check.EnsureOutcome.CREATED, issue_number=result.issue_number + 1)
        return result

    monkeypatch.setattr(live_check, 'sync_engine_task_to_issue', lying_sync)
    assert run(rest, '--mode', 'roundtrip', '--confirm-write', REPO) == 1
    assert not json.loads(capsys.readouterr().out)['ok']


@pytest.mark.parametrize('args', [
    ['--mode', 'roundtrip'],                                                        # no confirmation
    ['--mode', 'roundtrip', '--confirm-write', 'other/repo'],                       # confirmation for another repository
])
def test_roundtrip_refuses_without_a_matching_confirmation_and_writes_nothing(args):
    rest = FakeRest(REPO)
    assert run(rest, *args) == 2 and rest.calls == []


@pytest.mark.parametrize('repository', [PRODUCTION_REPOSITORY, 'uezeyiraydin-cell/tim-ai-platform'])
def test_the_production_repository_needs_its_own_flag_and_the_token_is_required(capsys, repository):
    prod = FakeRest(repository)
    assert run(prod, '--mode', 'roundtrip', '--confirm-write', repository) == 2 and prod.calls == []
    assert run(FakeRest(REPO), token=None) == 2
    # The flag lifts only the live_check refusal; create authority still refuses both production aliases.
    assert run(prod, '--mode', 'roundtrip', '--confirm-write', repository, '--allow-production-repo') == 1
    assert prod.issues == {}


def test_the_token_never_appears_in_any_output(capsys):
    rest = FakeRest(REPO)
    run(rest, '--mode', 'roundtrip', '--confirm-write', REPO)
    run(rest)
    run(rest, token=None)
    out = capsys.readouterr()
    assert TOKEN not in out.out and TOKEN not in out.err
