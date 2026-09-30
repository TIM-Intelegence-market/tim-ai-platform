import pytest

from src.task_governance import (CreateNotSent, EnsureOutcome, GitHubError, GitHubRestGateway, MappingState, TaskRegistry,
                                 TaskRequest, ensure_task, fingerprint_marker)
from src.task_governance.github_gateway import BODY_BEGIN, BODY_END, PAGE_SIZE, _NotSent
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


def test_find_issues_matches_marker_and_reports_pull_requests(rest, gw):
    fp = req().fingerprint
    rest.seed(5, fingerprint_marker(fp))
    rest.seed(6, 'unrelated')
    rest.seed(7, 'x ' + fingerprint_marker(fp), pr=True, login='stranger')
    found = gw.find_issues(fp, req().key)
    assert [(i.number, i.is_pull_request, i.author) for i in found] == [(5, False, 'owner'), (7, True, 'stranger')]


def test_find_issues_paginates_and_refuses_to_guess_beyond_the_cap(rest):
    fp = req().fingerprint
    for n in range(1, PAGE_SIZE * 2 + 2):
        rest.seed(n, fingerprint_marker(fp) if n == PAGE_SIZE * 2 + 1 else '')
    assert [i.number for i in GitHubRestGateway('owner/repo', TOKEN, transport=rest).find_issues(fp, '')] == [PAGE_SIZE * 2 + 1]
    with pytest.raises(GitHubError):
        GitHubRestGateway('owner/repo', TOKEN, transport=rest, max_pages=2).find_issues(fp, '')


def test_get_issue_none_only_for_confirmed_404(rest, gw):
    rest.seed(9)
    assert gw.get_issue(9).number == 9
    assert gw.get_issue(10) is None
    for status in (403, 429, 500, 502):
        rest.fail[('GET', r'/issues/9$')] = status
        with pytest.raises(GitHubError):
            gw.get_issue(9)


def test_errors_never_carry_token_or_response_body(rest, gw):
    rest.fail[('GET', r'/issues$')] = 403
    with pytest.raises(GitHubError) as exc:
        gw.find_issues('x', 'y')
    assert TOKEN not in str(exc.value) and 'SECRET-DETAIL' not in str(exc.value) and TOKEN not in repr(gw)


def test_bad_json_and_missing_number_raise(rest, gw):
    bad = GitHubRestGateway('owner/repo', TOKEN, transport=lambda *a: (200, b'<html>'))
    with pytest.raises(GitHubError):
        bad.get_issue(1)
    odd = GitHubRestGateway('owner/repo', TOKEN, transport=lambda *a: (201, b'{}'))
    with pytest.raises(GitHubError):
        odd.create_issue(req(), req().fingerprint, timeout=5)


def test_create_puts_marker_body_and_timeout_on_the_request(rest, gw):
    ref = gw.create_issue(req(), req().fingerprint, timeout=7.5)
    body = rest.issues[ref.number]['body']
    assert fingerprint_marker(req().fingerprint) in body and BODY_BEGIN in body and 'the body' in body
    assert rest.calls[-1] == ('POST', '/repos/owner/repo/issues', 7.5)


def test_connection_refused_is_create_not_sent_but_timeouts_are_not(rest, gw):
    rest.fail[('POST', r'/issues$')] = _NotSent()
    with pytest.raises(CreateNotSent):
        gw.create_issue(req(), req().fingerprint, timeout=5)
    rest.fail[('POST', r'/issues$')] = TimeoutError('slow')
    with pytest.raises(TimeoutError):
        gw.create_issue(req(), req().fingerprint, timeout=5)


def test_update_replaces_only_the_managed_section_and_is_idempotent(rest, gw):
    ref = gw.create_issue(req(), req().fingerprint, timeout=5)
    rest.issues[ref.number]['body'] = rest.issues[ref.number]['body'].replace(
        BODY_END, BODY_END + '\n\nHUMAN NOTE') 
    newer = req(body='changed body')
    gw.update_issue(ref.number, newer, 'reason a')
    body = rest.issues[ref.number]['body']
    assert 'changed body' in body and 'the body' not in body and 'HUMAN NOTE' in body
    before = len(rest.writes())
    gw.update_issue(ref.number, newer, 'reason a')
    assert len(rest.writes()) == before                       # no second PATCH, no second comment
    gw.update_issue(ref.number, newer, 'reason b')
    assert len(rest.writes()) == before + 1 and len(rest.comments[ref.number]) == 2


def test_update_backfills_marker_on_legacy_issue_and_keeps_human_text(rest, gw):
    rest.seed(11, 'human written legacy text')
    gw.update_issue(11, req(), 'adopted')
    body = rest.issues[11]['body']
    assert body.startswith('human written legacy text') and fingerprint_marker(req().fingerprint) in body


def test_update_of_missing_issue_raises(gw):
    with pytest.raises(GitHubError):
        gw.update_issue(404, req(), 'x')


def test_duplicate_documentation_is_a_single_comment_and_never_closes(rest, gw):
    rest.seed(22)
    assert not gw.is_documented_duplicate(22, 11)
    gw.mark_duplicate(22, 11)
    gw.mark_duplicate(22, 11)
    assert gw.is_documented_duplicate(22, 11) and not gw.is_documented_duplicate(22, 12)
    assert len(rest.comments[22]) == 1 and rest.issues[22]['state'] == 'open'


def test_reopen_only_opens_and_comments(rest, gw):
    rest.seed(30, state='closed')
    gw.reopen_issue(30, req(), 'retry')
    assert rest.issues[30]['state'] == 'open' and len(rest.comments[30]) == 1


def test_no_call_the_gateway_makes_can_close_an_issue(rest, gw, tmp_path):
    reg = TaskRegistry(str(tmp_path / 'r.db'))
    ensure_task(req(), reg, gw, claimant='w', trusted_authors=None)
    ensure_task(req(body='v2'), reg, gw, claimant='w', trusted_authors=None)
    for method, path, _ in rest.calls:
        assert method in ('GET', 'POST', 'PATCH')
    assert all(payload.get('state') != 'closed' for payload in rest.issues.values())
    assert all(i['state'] == 'open' for i in rest.issues.values())


def test_end_to_end_create_then_update_never_makes_a_second_issue(rest, gw, tmp_path):
    reg = TaskRegistry(str(tmp_path / 'r.db'))
    first = ensure_task(req(), reg, gw, claimant='w', trusted_authors=None)
    again = ensure_task(req(title='reworded'), reg, gw, claimant='w', trusted_authors=None)
    lost = ensure_task(req(), TaskRegistry(str(tmp_path / 'new.db')), gw, claimant='w', trusted_authors=None)
    assert (first.outcome, again.outcome, lost.outcome) == (EnsureOutcome.CREATED, EnsureOutcome.UPDATED, EnsureOutcome.RECOVERED)
    assert len(rest.issues) == 1 and first.issue_number == again.issue_number == lost.issue_number


def test_github_outage_during_lookup_blocks_nothing_and_creates_nothing(rest, gw, tmp_path):
    rest.fail[('GET', r'/issues$')] = 503
    reg = TaskRegistry(str(tmp_path / 'r.db'))
    with pytest.raises(GitHubError):
        ensure_task(req(), reg, gw, claimant='w', trusted_authors=None)
    assert not rest.issues
    assert not [c for c in rest.calls if c[0] == 'POST']


def test_constructor_validates_repository_and_token():
    with pytest.raises(ValueError):
        GitHubRestGateway('not a repo', TOKEN)
    with pytest.raises(ValueError):
        GitHubRestGateway('owner/repo', '')
