"""Live check of the GitHub gateway (#68): `python -m src.task_governance.live_check --repo OWNER/NAME`.

Two modes:
- `readonly` (default): only GET requests. Repository visible, token user, complete listing, a missing issue is a confirmed 404.
- `roundtrip`: writes ONE issue through the bridge (create, update, adopt after a lost registry) and checks that there is
  exactly one issue afterwards. The gateway cannot close issues, so the test issue stays open: use a throw-away repository.
  It needs `--confirm-write OWNER/NAME` with the same repository, and refuses the production repository without
  `--allow-production-repo`.

The token is read from the environment variable TIM_LIVE_CHECK_TOKEN only (never from arguments) and is never printed."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

from .engine_bridge import sync_engine_task_to_issue
from .github_gateway import GitHubError, GitHubRestGateway
from .registry import TaskRegistry
from .sync import EnsureOutcome

PRODUCTION_REPOSITORY = 'uezeyiraydin-cell/tim-ai-platform'
TOKEN_VARIABLE = 'TIM_LIVE_CHECK_TOKEN'
MISSING_ISSUE = 2_000_000_000


def _check(results, name, action):
    """Run one check; an unexpected GitHubError is a failed check, never a crash that hides the others."""
    try:
        ok, detail = action()
    except GitHubError as error:
        ok, detail = False, f'GitHubError: {error}'
    results.append({'name': name, 'ok': bool(ok), 'detail': detail})
    return ok


def token_login(gateway):
    _, user = gateway._call('GET', '/user')
    login = user.get('login') if isinstance(user, dict) else None
    if not login:
        raise GitHubError('GET /user: no login in the answer')
    return login


def run_readonly(gateway, *, probe_issue=None):
    results = []
    _check(results, 'repository_visible', lambda: (gateway._require_repository() is None, 'repository answers with the token'))
    _check(results, 'token_user', lambda: (bool(token_login(gateway)), 'GET /user returned a login'))
    _check(results, 'listing_is_complete', lambda: (gateway.find_issues('0' * 64, 'LIVE|CHECK') == [], 'whole listing read, no foreign marker'))
    _check(results, 'missing_issue_is_a_confirmed_404', lambda: (gateway.get_issue(MISSING_ISSUE) is None, f'issue {MISSING_ISSUE}'))
    if probe_issue is not None:
        _check(results, 'probe_issue_readable', lambda: (gateway.get_issue(probe_issue).number == probe_issue, f'issue {probe_issue}'))
    return results


def _without_memory(gateway):
    """The same repository, token and transport, but none of the numbers this gateway created or saw."""
    return GitHubRestGateway(gateway.repository, gateway._token, max_create_seconds=gateway.max_create_seconds,
                             request_timeout=gateway._timeout, max_pages=gateway._max_pages, transport=gateway._transport,
                             api=gateway._api, clock=gateway._clock)


def run_roundtrip(gateway, workdir, *, login, run_id=None):
    from src.task_engine.repository import SqliteTaskRepository
    from src.task_engine.service import TaskEngine
    run_id = run_id or uuid.uuid4().hex[:10].upper()
    task_id = f'LIVECHECK-{run_id}'
    repository = SqliteTaskRepository(Path(workdir) / 'engine.db')
    engine = TaskEngine(repository)
    results = []
    try:
        engine.create_task(task_id, type='LIVE_CHECK', title=f'[LIVE-CHECK] gateway round trip {run_id} (safe to close)',
                           objective='Created by src.task_governance.live_check to prove the gateway. Safe to close.',
                           source='LIVE_CHECK', acceptance_criteria=['one issue only'], required_evidence=['live_check output'],
                           next_action='close this issue')
        registry = TaskRegistry(str(Path(workdir) / 'registry.db'))

        def sync(reg, gw=gateway):
            return sync_engine_task_to_issue(engine, task_id, reg, gw, mission_id='LIVECHECK', phase_id='P0', claimant='live-check',
                                             trusted_authors=[login])

        first = sync(registry)
        _check(results, 'create', lambda: (first.outcome is EnsureOutcome.CREATED and first.issue_number is not None, f'issue #{first.issue_number}'))
        if first.issue_number is None:
            return results
        second = sync(registry)
        _check(results, 'second_run_updates_the_same_issue',
               lambda: (second.outcome is EnsureOutcome.UPDATED and second.issue_number == first.issue_number, f'{second.outcome.value} #{second.issue_number}'))
        # a new process: a registry that never saw the task and a gateway that does not remember the created number
        lost = sync(TaskRegistry(str(Path(workdir) / 'registry-lost.db')), _without_memory(gateway))
        _check(results, 'lost_registry_adopts_instead_of_creating',
               lambda: (lost.outcome is EnsureOutcome.RECOVERED and lost.issue_number == first.issue_number, f'{lost.outcome.value} #{lost.issue_number}'))
        from .engine_bridge import request_from_engine_task
        request = request_from_engine_task(engine.get_task(task_id), mission_id='LIVECHECK', phase_id='P0')
        found = gateway.find_issues(request.fingerprint, request.key)
        _check(results, 'exactly_one_issue_carries_the_marker', lambda: ([f.number for f in found] == [first.issue_number], f'{[f.number for f in found]}'))
        results.append({'name': 'cleanup', 'ok': True, 'detail': f'issue #{first.issue_number} stays open: close it by hand (the gateway cannot close)'})
    finally:
        repository.close()
    return results


def main(argv=None, environ=None, transport=None):
    parser = argparse.ArgumentParser(prog='live_check', description=__doc__.split('\n\n')[0])
    parser.add_argument('--repo', required=True, help='OWNER/NAME')
    parser.add_argument('--mode', choices=('readonly', 'roundtrip'), default='readonly')
    parser.add_argument('--confirm-write', help='must equal --repo for the roundtrip mode')
    parser.add_argument('--allow-production-repo', action='store_true')
    parser.add_argument('--probe-issue', type=int, help='an existing issue number to read (readonly mode)')
    args = parser.parse_args(argv)
    environ = os.environ if environ is None else environ
    token = environ.get(TOKEN_VARIABLE)
    if not token:
        print(f'{TOKEN_VARIABLE} is not set; the token is never taken from arguments', file=sys.stderr)
        return 2
    if args.mode == 'roundtrip':
        if args.confirm_write != args.repo:
            print('roundtrip writes an issue: pass --confirm-write with the same OWNER/NAME', file=sys.stderr)
            return 2
        if args.repo.lower() == PRODUCTION_REPOSITORY and not args.allow_production_repo:
            print('refusing the production repository: use a throw-away repository or pass --allow-production-repo', file=sys.stderr)
            return 2
    kwargs = {} if transport is None else {'transport': transport}
    gateway = GitHubRestGateway(args.repo, token, **kwargs)
    try:
        if args.mode == 'readonly':
            results = run_readonly(gateway, probe_issue=args.probe_issue)
        else:
            login = token_login(gateway)
            with tempfile.TemporaryDirectory() as workdir:
                results = run_roundtrip(gateway, workdir, login=login)
    except GitHubError as error:
        results = [{'name': 'setup', 'ok': False, 'detail': f'GitHubError: {error}'}]
    print(json.dumps({'repository': args.repo, 'mode': args.mode, 'ok': all(r['ok'] for r in results), 'checks': results}, indent=2))
    return 0 if all(r['ok'] for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
