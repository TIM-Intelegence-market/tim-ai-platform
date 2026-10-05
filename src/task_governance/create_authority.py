"""Who may create Mission-Task issues (#68, decision gate, path A).

The create-once guarantee of `ensure_task` holds for workers that share one registry file. A registry file is local, so two hosts
with two files could still both create. Path A closes that: the *repository* names the one registry that may create, and
`ensure_task` asks before every create. Any other registry can still read, update and adopt, but it never creates.

The designation is an ordinary GitHub issue that an operator opens by hand (`python -m src.task_governance.create_authority body`):

    <!-- TIM_CREATE_AUTHORITY_V1 registry=<32 hex> repository=OWNER/NAME -->

and the gateway is built with `create_authority=IssueCreateAuthority(<that issue number>)`. The issue is read by number (a single
read is consistent, the listing lags). A create is allowed only when that issue

- exists in this repository and is not a pull request,
- is open (closing it revokes creation at once),
- was opened by one of the `trusted_authors` the caller passes (`None` never qualifies),
- carries exactly one marker, naming this registry and this repository.

Anything else, including an unreadable issue, refuses. Limits that remain, on purpose written down:
a copied registry file has the same id (rotate it with `TaskRegistry.rotate_registry_id`); the designation can be edited by anyone
who may edit issues; and GitHub cannot stop a person or tool with write access from opening an issue directly. Path A enforces the
code path, not every identity with a token.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass

from .repository_names import PRODUCTION_REPOSITORY, normalize_repository

MARKER_PREFIX = 'TIM_CREATE_AUTHORITY_V1'
_MARKER = re.compile(r'<!--\s*TIM_CREATE_AUTHORITY_V1\s+registry=([0-9a-f]{32})\s+repository=([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)\s*-->')
TOKEN_VARIABLE = 'TIM_LIVE_CHECK_TOKEN'        # the same read-only variable that live_check uses


class CreateNotAuthorized(Exception):
    """This registry may not create Mission-Task issues in this repository (nothing was created)."""


@dataclass(frozen=True)
class AuthorityIssue:
    number: int
    state: str
    author: str
    body: str
    is_pull_request: bool | None = None


def authority_marker(registry_id: str, repository: str) -> str:
    return f'<!-- {MARKER_PREFIX} registry={registry_id} repository={repository} -->'


def authority_body(registry_id: str, repository: str) -> str:
    return (f'TIM create authority: only the task registry `{registry_id}` may create Mission-Task issues in `{repository}`.\n'
            'Close this issue to revoke it. Do not edit the marker by hand.\n\n' + authority_marker(registry_id, repository))


def parse_authority(body: str) -> tuple[str, str] | None:
    """(registry id, repository) of the single marker in `body`; None when there is none or more than one."""
    found = _MARKER.findall(body or '')
    return found[0] if len(found) == 1 else None


class IssueCreateAuthority:
    """The repository's designation issue decides (see the module text)."""

    def __init__(self, issue_number: int):
        if not isinstance(issue_number, int) or isinstance(issue_number, bool) or issue_number <= 0:
            raise ValueError('issue_number must be a positive integer')
        self.issue_number = issue_number

    def check(self, gateway, registry_id: str, trusted_authors) -> None:
        if trusted_authors is None:
            raise CreateNotAuthorized('create authority needs trusted_authors: with None anybody would count as the designating author')
        issue = gateway.read_authority_issue(self.issue_number)
        where = f'authority issue #{self.issue_number}'
        if issue is None:
            raise CreateNotAuthorized(f'{where} does not exist')
        if issue.is_pull_request is not False:
            raise CreateNotAuthorized(f'{where} is a pull request or its kind is unknown')
        if issue.state != 'open':
            raise CreateNotAuthorized(f'{where} is {issue.state}, so creation is revoked')
        if issue.author.strip().lower() not in {a.strip().lower() for a in trusted_authors}:
            raise CreateNotAuthorized(f'{where} was opened by {issue.author!r}, who is not a trusted author')
        marker = parse_authority(issue.body)
        if marker is None:
            raise CreateNotAuthorized(f'{where} has no single {MARKER_PREFIX} marker')
        designated, repository = marker
        if normalize_repository(repository) != normalize_repository(gateway.repository):
            raise CreateNotAuthorized(f'{where} is for repository {repository}, not {gateway.repository}')
        if designated != registry_id:
            raise CreateNotAuthorized(f'{where} designates registry {designated[:8]}…, not this one ({registry_id[:8]}…)')


class UnrestrictedCreateAuthority:
    """Every registry may create. Only for tools that own the whole repository, such as `live_check` on a throw-away repository.

    It refuses the production repository, so a tool cannot use it there by mistake."""

    def check(self, gateway, registry_id: str, trusted_authors) -> None:
        if normalize_repository(gateway.repository) == PRODUCTION_REPOSITORY:
            raise CreateNotAuthorized('an unrestricted create authority is never valid for the production repository')


def main(argv=None, environ=None, transport=None) -> int:
    from .github_gateway import GitHubError, GitHubRestGateway
    from .registry import TaskRegistry
    parser = argparse.ArgumentParser(prog='create_authority', description='Designate the registry that may create Mission-Task issues.')
    sub = parser.add_subparsers(dest='command', required=True)
    for name, text in (('id', 'print the id of a registry file'),
                       ('body', 'print the body of the designation issue (open it by hand, with a trusted account)'),
                       ('verify', 'read the designation issue and say whether this registry may create (GET only)')):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument('--registry', required=True, help='path of the registry file')
        if name != 'id':
            cmd.add_argument('--repo', required=True, help='OWNER/NAME')
        if name == 'verify':
            cmd.add_argument('--issue', required=True, type=int)
            cmd.add_argument('--trusted-author', action='append', required=True, dest='trusted')
    args = parser.parse_args(argv)
    registry = TaskRegistry(args.registry)
    if args.command == 'id':
        print(registry.registry_id)
        return 0
    if args.command == 'body':
        print(authority_body(registry.registry_id, args.repo))
        return 0
    environ = os.environ if environ is None else environ
    token = environ.get(TOKEN_VARIABLE)
    if not token:
        print(f'{TOKEN_VARIABLE} is not set; the token is never taken from arguments', file=sys.stderr)
        return 2
    kwargs = {} if transport is None else {'transport': transport}
    gateway = GitHubRestGateway(args.repo, token, create_authority=IssueCreateAuthority(args.issue), **kwargs)
    try:
        gateway.authorize_create(registry.registry_id, args.trusted)
        result = {'ok': True, 'detail': 'this registry may create'}
    except (CreateNotAuthorized, GitHubError) as error:
        result = {'ok': False, 'detail': f'{type(error).__name__}: {error}'}
    print(json.dumps({'repository': args.repo, 'registry': registry.registry_id, 'issue': args.issue, **result}, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
