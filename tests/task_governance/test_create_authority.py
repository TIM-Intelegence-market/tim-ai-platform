"""#68 decision gate, path A: only the registry that the repository designates may create Mission-Task issues.

`concurrent_create_requests(N)` with SEPARATE registry files must create exactly one issue: the others are refused before the create
intent is written, and they can still read, update and adopt."""
import json
import threading

import pytest

from src.task_governance import (CreateNotAuthorized, EnsureOutcome, GitHubError, GitHubRestGateway, IssueCreateAuthority,
                                 MappingState, TaskRegistry, TaskRequest, UnrestrictedCreateAuthority, ensure_task)
from src.task_governance import create_authority as ca
from tests.task_governance.fake_rest import FakeRest
from tests.task_governance.fakes import FakeGitHub

pytestmark = pytest.mark.real_create_authority

TOKEN = 'ghp_SUPERSECRETTOKEN'
REPO = 'owner/repo'
OWNER = 'owner'
AUTH_ISSUE = 5


def req(**kw):
    base = dict(mission_id='M09', phase_id='P0', task_type='SAMPLE_TASK', target='TIM', schema_version='v1',
                title='Sample', body='the body')
    base.update(kw)
    return TaskRequest(**base)


def registry(tmp_path, name='a.db'):
    return TaskRegistry(str(tmp_path / name))


def designate(rest, reg, *, number=AUTH_ISSUE, login=OWNER, state='open', repository=REPO, body=None, pr=False):
    rest.seed(number, body if body is not None else ca.authority_body(reg.registry_id, repository), state=state, login=login, pr=pr)


def gateway(rest, **kw):
    kw.setdefault('create_authority', IssueCreateAuthority(AUTH_ISSUE))
    return GitHubRestGateway(rest.repo, TOKEN, transport=rest, **kw)


def ensure(reg, gw, **kw):
    kw.setdefault('trusted_authors', [OWNER])
    return ensure_task(req(), reg, gw, claimant=kw.pop('claimant', 'w'), **kw)


def task_issues(rest):
    return [n for n, i in rest.issues.items() if n != AUTH_ISSUE]


# -- registry identity ------------------------------------------------------------------------------------------------------

def test_a_registry_file_has_a_stable_id_and_two_files_differ(tmp_path):
    a = registry(tmp_path, 'a.db')
    first = a.registry_id
    assert len(first) == 32 and int(first, 16) >= 0
    assert TaskRegistry(str(tmp_path / 'a.db')).registry_id == first
    assert registry(tmp_path, 'b.db').registry_id != first


def test_many_processes_opening_a_fresh_file_agree_on_one_id(tmp_path):
    ids, errors = [], []

    def open_it():
        try:
            ids.append(TaskRegistry(str(tmp_path / 'race.db')).registry_id)
        except Exception as exc:                                  # pragma: no cover - would fail the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=open_it) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(set(ids)) == 1 and len(ids) == 12


def test_rotating_the_id_keeps_the_mappings_and_leaves_a_trace(tmp_path):
    reg = registry(tmp_path)
    fake = FakeGitHub(str(tmp_path / 'gh.db'))
    first = ensure_task(req(), reg, fake, claimant='w', trusted_authors=None)
    old = reg.registry_id
    with pytest.raises(ValueError):
        reg.rotate_registry_id('  ')
    new = reg.rotate_registry_id('file copied to the server')
    assert new != old and reg.registry_id == new and TaskRegistry(reg.path).registry_id == new
    assert reg.get(first.mapping.fingerprint).state is MappingState.MAPPED
    assert [i['reason'] for i in reg.incidents()] == ['REGISTRY_ID_ROTATED'] and old in reg.incidents()[0]['detail']


# -- the check in ensure_task -------------------------------------------------------------------------------------------------

def test_a_gateway_without_the_authority_hook_never_creates(tmp_path):
    class Silent(FakeGitHub):
        authorize_create = None

    fake = Silent(str(tmp_path / 'gh.db'))
    reg = registry(tmp_path)
    result = ensure_task(req(), reg, fake, claimant='w', trusted_authors=None)
    assert result.outcome is EnsureOutcome.BLOCKED and result.detail == 'CREATE_NOT_AUTHORIZED' and not result.created
    assert fake._db().execute("SELECT COUNT(*) FROM log WHERE op='create'").fetchone()[0] == 0


def test_a_refusal_leaves_no_create_intent_and_a_later_designation_creates(tmp_path):
    fake = FakeGitHub(str(tmp_path / 'gh.db'))
    fake.deny_create = 'not designated'
    reg = registry(tmp_path)
    refused = ensure_task(req(), reg, fake, claimant='w', trusted_authors=None)
    row = reg.get(refused.mapping.fingerprint)
    assert refused.detail == 'CREATE_NOT_AUTHORIZED' and row.state is MappingState.RELEASED and not row.create_intent
    assert [i['reason'] for i in reg.incidents()] == ['CREATE_NOT_AUTHORIZED']
    fake.deny_create = None
    created = ensure_task(req(), reg, fake, claimant='w', trusted_authors=None)
    assert created.outcome is EnsureOutcome.CREATED and fake.authorized == [reg.registry_id, reg.registry_id]


def test_a_retrying_scheduler_does_not_flood_the_incident_log(tmp_path):
    fake = FakeGitHub(str(tmp_path / 'gh.db'))
    fake.deny_create = 'not designated'
    reg = registry(tmp_path)
    for _ in range(5):
        ensure_task(req(), reg, fake, claimant='w', trusted_authors=None)
    assert [i['reason'] for i in reg.incidents()] == ['CREATE_NOT_AUTHORIZED']
    fake.deny_create = 'the designation was closed'
    ensure_task(req(), reg, fake, claimant='w', trusted_authors=None)
    assert len(reg.incidents()) == 2


def test_a_refused_registry_still_adopts_and_updates(tmp_path):
    fake = FakeGitHub(str(tmp_path / 'gh.db'))
    designated = registry(tmp_path, 'a.db')
    first = ensure_task(req(), designated, fake, claimant='w', trusted_authors=None)
    fake.deny_create = 'not designated'
    other = registry(tmp_path, 'b.db')
    adopted = ensure_task(req(), other, fake, claimant='x', trusted_authors=None)          # lost registry: marker found, no create
    assert adopted.outcome is EnsureOutcome.RECOVERED and adopted.issue_number == first.issue_number
    again = ensure_task(req(body='v2'), designated, fake, claimant='w', trusted_authors=None)
    assert again.outcome is EnsureOutcome.UPDATED
    assert fake._db().execute("SELECT COUNT(*) FROM log WHERE op='create'").fetchone()[0] == 1


def test_an_unreadable_authority_releases_the_claim_and_creates_nothing(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    rest.fail[('GET', rf'/issues/{AUTH_ISSUE}$')] = 503
    with pytest.raises(GitHubError):
        ensure(reg, gateway(rest))
    row = reg.get(req().fingerprint)
    assert task_issues(rest) == [] and row.state is MappingState.RELEASED and not row.create_intent
    del rest.fail[('GET', rf'/issues/{AUTH_ISSUE}$')]
    assert ensure(reg, gateway(rest)).outcome is EnsureOutcome.CREATED


# -- the gate: separate registries, one repository ---------------------------------------------------------------------------

def test_two_registries_race_and_only_the_designated_one_creates(tmp_path, monkeypatch):
    rest = FakeRest()
    a, b = registry(tmp_path, 'a.db'), registry(tmp_path, 'b.db')
    designate(rest, a)
    gw = gateway(rest)
    # Start barriers alone do not ensure both scans saw an empty repository:
    # a later scan may legitimately adopt the designated registry's new issue.
    # Synchronize at create authorization so this test exercises competing creates.
    authorization_barrier = threading.Barrier(2)
    original_authorize = gw.authorize_create

    def authorize_create(*args):
        authorization_barrier.wait(timeout=5)
        return original_authorize(*args)

    monkeypatch.setattr(gw, 'authorize_create', authorize_create)
    results = {}
    barrier = threading.Barrier(2)

    def run(name, reg):
        barrier.wait()
        results[name] = ensure(reg, gw, claimant=name)

    threads = [threading.Thread(target=run, args=(n, r)) for n, r in (('a', a), ('b', b))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(task_issues(rest)) == 1
    assert results['a'].outcome is EnsureOutcome.CREATED
    assert results['b'].detail == 'CREATE_NOT_AUTHORIZED' and results['b'].outcome is EnsureOutcome.BLOCKED


def test_many_separate_registries_create_exactly_one_issue(tmp_path):
    rest = FakeRest()
    regs = [registry(tmp_path, f'r{i}.db') for i in range(8)]
    designate(rest, regs[3])
    outcomes, errors = [], []
    barrier = threading.Barrier(len(regs))

    def run(i, reg):
        barrier.wait()
        try:
            outcomes.append(ensure(reg, gateway(rest), claimant=f'w{i}'))
        except Exception as exc:                                   # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i, r)) for i, r in enumerate(regs)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(task_issues(rest)) == 1
    assert sorted(o.outcome.value for o in outcomes).count('CREATED') == 1
    assert {o.detail for o in outcomes if o.outcome is EnsureOutcome.BLOCKED} == {'CREATE_NOT_AUTHORIZED'}


def test_a_lost_registry_adopts_but_cannot_create_until_it_is_designated(tmp_path):
    rest = FakeRest()
    old = registry(tmp_path, 'old.db')
    designate(rest, old)
    first = ensure(old, gateway(rest))
    fresh = registry(tmp_path, 'fresh.db')
    adopted = ensure(fresh, gateway(rest))
    assert adopted.outcome is EnsureOutcome.RECOVERED and adopted.issue_number == first.issue_number
    other = ensure_task(req(target='OTHER'), fresh, gateway(rest), claimant='w', trusted_authors=[OWNER])
    assert other.detail == 'CREATE_NOT_AUTHORIZED' and len(task_issues(rest)) == 1
    rest.issues[AUTH_ISSUE]['body'] = ca.authority_body(fresh.registry_id, REPO)           # the operator re-designates
    assert ensure_task(req(target='OTHER'), fresh, gateway(rest), claimant='w', trusted_authors=[OWNER]).outcome is EnsureOutcome.CREATED


def test_closing_the_authority_issue_revokes_creation_but_not_updates(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    assert ensure(reg, gateway(rest)).outcome is EnsureOutcome.CREATED
    rest.issues[AUTH_ISSUE]['state'] = 'closed'
    assert ensure_task(req(target='NEW'), reg, gateway(rest), claimant='w', trusted_authors=[OWNER]).detail == 'CREATE_NOT_AUTHORIZED'
    assert ensure(reg, gateway(rest)).outcome is EnsureOutcome.UPDATED


# -- what counts as a designation ------------------------------------------------------------------------------------------------

def refusal(tmp_path, *, trusted=(OWNER,), missing=False, **designation):
    rest = FakeRest()
    reg = registry(tmp_path)
    if not missing:
        designate(rest, reg, **designation)
    with pytest.raises(CreateNotAuthorized) as caught:
        gateway(rest).authorize_create(reg.registry_id, trusted)
    return str(caught.value)


def test_a_gateway_without_a_configured_authority_refuses(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    with pytest.raises(CreateNotAuthorized, match='no create authority'):
        GitHubRestGateway(rest.repo, TOKEN, transport=rest).authorize_create(reg.registry_id, [OWNER])


@pytest.mark.parametrize('designation, expected', [
    (dict(missing=True), 'does not exist'),
    (dict(state='closed'), 'revoked'),
    (dict(pr=True), 'pull request'),
    (dict(login='mallory'), 'not a trusted author'),
    (dict(body='nothing here'), 'no single'),
    (dict(repository='owner/other'), 'is for repository owner/other'),
])
def test_a_designation_that_is_not_valid_refuses(tmp_path, designation, expected):
    assert expected in refusal(tmp_path, **designation)


def test_a_designation_for_another_registry_refuses(tmp_path):
    other = ca.authority_body('0' * 32, REPO)
    assert 'not this one' in refusal(tmp_path, body=other)


def test_two_markers_are_ambiguous_and_refuse(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    two = ca.authority_body(reg.registry_id, REPO) + '\n' + ca.authority_marker('1' * 32, REPO)
    designate(rest, reg, body=two)
    with pytest.raises(CreateNotAuthorized, match='no single'):
        gateway(rest).authorize_create(reg.registry_id, [OWNER])


def test_trusted_authors_none_never_qualifies(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    with pytest.raises(CreateNotAuthorized, match='trusted_authors'):
        gateway(rest).authorize_create(reg.registry_id, None)


def test_author_and_repository_compare_without_case_and_across_the_transfer_alias(tmp_path):
    rest = FakeRest('TIM-Intelegence-market/tim-ai-platform')
    reg = registry(tmp_path)
    rest.seed(AUTH_ISSUE, ca.authority_body(reg.registry_id, 'uezeyiraydin-cell/tim-ai-platform'), login='Owner')
    gateway(rest).authorize_create(reg.registry_id, [' OWNER '])


def test_the_authority_issue_must_belong_to_this_repository(tmp_path):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    rest.issues[AUTH_ISSUE]['repository_url'] = 'https://api.github.com/repos/someone/else'
    with pytest.raises(GitHubError):
        gateway(rest).authorize_create(reg.registry_id, [OWNER])


def test_issue_number_must_be_a_positive_integer():
    for bad in (0, -1, '5', True, None):
        with pytest.raises(ValueError):
            IssueCreateAuthority(bad)


def test_a_direct_create_on_a_gateway_without_an_authority_is_refused(tmp_path):
    rest = FakeRest()
    gw = GitHubRestGateway(rest.repo, TOKEN, transport=rest)
    with pytest.raises(CreateNotAuthorized):
        gw.create_issue(req(), req().fingerprint, timeout=5)
    assert rest.writes() == []


# -- unrestricted authority (throw-away repositories only) -----------------------------------------------------------------------

@pytest.mark.parametrize('repo', ['TIM-Intelegence-market/tim-ai-platform', 'uezeyiraydin-cell/tim-ai-platform',
                                  'https://github.com/uezeyiraydin-cell/tim-ai-platform.git'])
def test_the_unrestricted_authority_never_applies_to_production(tmp_path, repo):
    class Stub:
        repository = repo
    with pytest.raises(CreateNotAuthorized, match='production'):
        UnrestrictedCreateAuthority().check(Stub(), 'x' * 32, None)


def test_the_unrestricted_authority_accepts_a_throw_away_repository(tmp_path):
    class Stub:
        repository = 'owner/throwaway'
    UnrestrictedCreateAuthority().check(Stub(), 'x' * 32, None)


# -- operator command ----------------------------------------------------------------------------------------------------------------

def test_cli_prints_the_id_and_the_body_and_writes_nothing(tmp_path, capsys):
    reg = registry(tmp_path)
    assert ca.main(['id', '--registry', reg.path]) == 0
    assert capsys.readouterr().out.strip() == reg.registry_id
    assert ca.main(['body', '--registry', reg.path, '--repo', REPO]) == 0
    body = capsys.readouterr().out
    assert ca.parse_authority(body) == (reg.registry_id, REPO)


def test_cli_verify_reads_only_and_reports_ok_or_the_reason(tmp_path, capsys):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    args = ['verify', '--registry', reg.path, '--repo', REPO, '--issue', str(AUTH_ISSUE), '--trusted-author', OWNER]
    env = {ca.TOKEN_VARIABLE: TOKEN}
    assert ca.main(args, environ=env, transport=rest) == 0
    assert json.loads(capsys.readouterr().out)['ok'] is True and rest.writes() == []
    rest.issues[AUTH_ISSUE]['state'] = 'closed'
    assert ca.main(args, environ=env, transport=rest) == 1
    out = capsys.readouterr().out
    assert json.loads(out)['ok'] is False and 'revoked' in out and TOKEN not in out and rest.writes() == []
    assert ca.main(args, environ={}, transport=rest) == 2


def test_cli_verify_reports_an_unreadable_issue_as_a_failure_not_a_crash(tmp_path, capsys):
    rest = FakeRest()
    reg = registry(tmp_path)
    designate(rest, reg)
    rest.fail[('GET', rf'/issues/{AUTH_ISSUE}$')] = 500
    args = ['verify', '--registry', reg.path, '--repo', REPO, '--issue', str(AUTH_ISSUE), '--trusted-author', OWNER]
    assert ca.main(args, environ={ca.TOKEN_VARIABLE: TOKEN}, transport=rest) == 1
    assert 'GitHubError' in capsys.readouterr().out
